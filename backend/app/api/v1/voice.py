import asyncio
import json
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logger import logger
from app.core.security import decode_access_token, decrypt_secret
from app.models.agent import Agent
from app.models.session import CallSession
from app.models.user import User, UserApiKey
from app.providers.llm import get_llm_provider
from app.providers.stt import get_stt_provider
from app.providers.tts import get_tts_provider
from app.services.rate_limiter import rate_limiter
from app.services.voice_orchestrator import VoiceOrchestrator
from app.vad.detector import StreamingVAD

router = APIRouter()


def _extract_ws_token(websocket: WebSocket) -> Optional[str]:
    """Extracts JWT from query param (?token=...) or Authorization Bearer header."""
    token = websocket.query_params.get("token")
    if token:
        return token.strip()
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


@router.websocket("/stream/{agent_id}")
async def voice_stream_websocket(websocket: WebSocket, agent_id: str):
    """
    Real-time bidirectional voice streaming endpoint:
    - JWT authenticated & strict agent owner isolation.
    - Rate limited per user & client IP via Redis (with active backend reporting).
    - Enforces configurable max frame size & max session duration.
    - Binary frames: 16kHz mono PCM16 input; MP3 chunks output.
    - Text JSON frames: control commands, live transcript, state transitions & latency metrics.
    """
    token = _extract_ws_token(websocket)
    if not token:
        await websocket.close(code=1008, reason="Authentication token required")
        return

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        await websocket.close(code=1008, reason="Invalid or expired access token")
        return

    user_id = payload["sub"]
    client_ip = websocket.client.host if websocket.client else "unknown"

    allowed, _, rl_backend = await rate_limiter.check_ws_connection(user_id, client_ip)
    if not allowed:
        logger.warning(f"Voice WebSocket rate limit exceeded user={user_id} ip={client_ip}")
        await websocket.close(code=1008, reason="Rate limit exceeded")
        return

    # Authenticate user, enforce agent ownership, decrypt provider key server-side
    agent: Optional[Agent] = None
    api_key: Optional[str] = None
    key_error: Optional[str] = None
    session_id: Optional[str] = None

    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        if not user or not user.is_active:
            await websocket.close(code=1008, reason="User not found or inactive")
            return

        agent_res = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = agent_res.scalar_one_or_none()
        if not agent or agent.user_id != user.id:
            await websocket.close(code=1008, reason="Agent not found or access denied")
            return

        provider_name = agent.llm_provider.lower().strip()
        key_res = await db.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user.id,
                UserApiKey.provider == provider_name,
            )
        )
        user_key_row = key_res.scalar_one_or_none()
        if user_key_row:
            try:
                api_key = decrypt_secret(user_key_row.encrypted_key)
            except Exception as exc:
                logger.error(f"Vault key decryption failed for provider={provider_name}: {exc}")
                key_error = "Failed to decrypt your stored API key. Please re-enter it in the Vault."
        else:
            if provider_name == "gemini" and settings.GEMINI_API_KEY:
                api_key = settings.GEMINI_API_KEY
            elif provider_name in ("openai", "gpt") and settings.OPENAI_API_KEY:
                api_key = settings.OPENAI_API_KEY

        if not api_key and not key_error:
            key_error = (
                f"No API key found for provider '{agent.llm_provider}'. "
                "Please add your key in the API Key Vault before starting voice chat."
            )

        rag_api_key = api_key if provider_name == "gemini" else settings.GEMINI_API_KEY
        if provider_name != "gemini":
            gem_res = await db.execute(
                select(UserApiKey).where(
                    UserApiKey.user_id == user.id,
                    UserApiKey.provider == "gemini",
                )
            )
            gem_row = gem_res.scalar_one_or_none()
            if gem_row:
                try:
                    rag_api_key = decrypt_secret(gem_row.encrypted_key)
                except Exception:
                    pass

        if not key_error:
            call_session = CallSession(
                agent_id=agent.id,
                user_id=user.id,
                status="active",
            )
            db.add(call_session)
            await db.commit()
            await db.refresh(call_session)
            session_id = call_session.id

    await websocket.accept()

    if key_error or not session_id or not agent:
        await websocket.send_json({
            "type": "error",
            "code": "MISSING_API_KEY",
            "message": key_error or "Unable to initialize session",
        })
        await websocket.close(code=1008, reason="Missing provider API key")
        return

    send_lock = asyncio.Lock()

    async def safe_send_json(data: dict) -> None:
        async with send_lock:
            await websocket.send_json(data)

    async def safe_send_bytes(chunk: bytes) -> None:
        async with send_lock:
            await websocket.send_bytes(chunk)

    try:
        llm = get_llm_provider(agent.llm_provider, api_key or "")
        if hasattr(llm, "thinking_level"):
            llm.thinking_level = "minimal"
        if hasattr(llm, "max_output_tokens"):
            llm.max_output_tokens = 150
        stt = get_stt_provider(agent.stt_provider, api_key=rag_api_key)
        tts = get_tts_provider(agent.tts_provider)
        vad = StreamingVAD(
            sample_rate=16000,
            silence_threshold_ms=settings.VAD_SILENCE_THRESHOLD_MS,
            speech_start_threshold=settings.VAD_SPEECH_START_THRESHOLD,
            speech_end_threshold=settings.VAD_SPEECH_END_THRESHOLD,
            energy_multiplier=settings.VAD_ENERGY_MULTIPLIER,
            min_speech_ms=settings.VAD_MIN_SPEECH_MS,
            max_utterance_seconds=settings.VAD_MAX_UTTERANCE_S,
        )
    except Exception as exc:
        logger.error(f"Voice pipeline initialization failed: {exc}")
        await safe_send_json({"type": "error", "code": "INIT_ERROR", "message": str(exc)})
        await websocket.close(code=1011, reason="Voice pipeline initialization failed")
        return

    orchestrator = VoiceOrchestrator(
        agent=agent,
        session_id=session_id,
        llm_provider=llm,
        stt_provider=stt,
        tts_provider=tts,
        vad=vad,
        send_json=safe_send_json,
        send_bytes=safe_send_bytes,
        db_session_factory=AsyncSessionLocal,
        rag_api_key=rag_api_key,
    )

    await safe_send_json({
        "type": "session_ready",
        "session_id": session_id,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "rate_limiter_backend": rl_backend,
        "vad_backend": vad.backend_name,
        "max_session_seconds": settings.VOICE_MAX_SESSION_SECONDS,
        "max_message_bytes": settings.WS_MAX_MESSAGE_BYTES,
        "state": orchestrator.state.value,
    })

    async def _prewarm_session_providers() -> None:
        """Pre-warms persistent LLM HTTP/TLS connection and TTS client on WebSocket connect."""
        try:
            await llm.generate(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Reply ok.",
                temperature=0.0,
                model=agent.llm_model,
            )
        except Exception as exc:
            logger.debug(f"Voice LLM prewarm skipped session={session_id}: {exc}")
        try:
            async for _ in tts.synthesize_stream("ok", voice=agent.tts_voice):
                break
        except Exception as exc:
            logger.debug(f"Voice TTS prewarm skipped session={session_id}: {exc}")

    prewarm_task = asyncio.create_task(_prewarm_session_providers())

    session_timed_out = False

    async def session_watchdog() -> None:
        nonlocal session_timed_out
        await asyncio.sleep(settings.VOICE_MAX_SESSION_SECONDS)
        session_timed_out = True
        try:
            await safe_send_json({
                "type": "error",
                "code": "SESSION_TIMEOUT",
                "message": f"Max voice session duration ({settings.VOICE_MAX_SESSION_SECONDS}s) reached.",
            })
            await websocket.close(code=1000, reason="Session duration limit reached")
        except Exception:
            pass

    watchdog_task = asyncio.create_task(session_watchdog())
    final_status = "completed"

    try:
        while True:
            message = await websocket.receive()
            msg_type = message.get("type")
            if msg_type == "websocket.disconnect":
                break

            binary_data = message.get("bytes")
            text_data = message.get("text")

            if binary_data is not None:
                if len(binary_data) > settings.WS_MAX_MESSAGE_BYTES:
                    await safe_send_json({
                        "type": "error",
                        "code": "MESSAGE_TOO_LARGE",
                        "message": f"Audio frame exceeds max size ({settings.WS_MAX_MESSAGE_BYTES} bytes).",
                    })
                    final_status = "error"
                    await websocket.close(code=1009, reason="Frame exceeds max message size")
                    break
                await orchestrator.handle_audio_frame(binary_data)

            elif text_data is not None:
                if len(text_data.encode("utf-8")) > settings.WS_MAX_MESSAGE_BYTES:
                    await safe_send_json({
                        "type": "error",
                        "code": "MESSAGE_TOO_LARGE",
                        "message": f"Control message exceeds max size ({settings.WS_MAX_MESSAGE_BYTES} bytes).",
                    })
                    final_status = "error"
                    await websocket.close(code=1009, reason="Message exceeds max message size")
                    break

                try:
                    cmd = json.loads(text_data)
                except json.JSONDecodeError:
                    await safe_send_json({
                        "type": "error",
                        "code": "INVALID_JSON",
                        "message": "Control frame must be valid JSON.",
                    })
                    continue

                action = (cmd.get("type") or "").lower().strip()
                if action == "start":
                    await orchestrator.start_listening()
                elif action == "stop":
                    await orchestrator.stop_listening()
                elif action == "end_utterance":
                    await orchestrator.force_end_utterance()
                elif action == "interrupt":
                    await orchestrator.interrupt()
                elif action == "config":
                    vad.update_config(
                        silence_threshold_ms=cmd.get("silence_threshold_ms"),
                        speech_threshold=cmd.get("speech_threshold"),
                        speech_start_threshold=cmd.get("speech_start_threshold"),
                        speech_end_threshold=cmd.get("speech_end_threshold"),
                        energy_multiplier=cmd.get("energy_multiplier"),
                        min_speech_ms=cmd.get("min_speech_ms"),
                    )
                    await safe_send_json({
                        "type": "config_updated",
                        "silence_threshold_ms": vad.silence_threshold_ms,
                        "speech_start_threshold": vad.speech_start_threshold,
                        "speech_end_threshold": vad.speech_end_threshold,
                        "energy_multiplier": vad.energy_multiplier,
                    })
                elif action == "tool_confirm_response":
                    orchestrator.resolve_tool_confirmation(
                        str(cmd.get("confirm_id") or ""),
                        bool(cmd.get("approved", False)),
                    )
                elif action == "ping":
                    await safe_send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Voice WebSocket disconnected session={session_id}")
    except Exception as exc:
        logger.error(f"Voice WebSocket error session={session_id}: {exc}")
        final_status = "error"
    finally:
        prewarm_task.cancel()
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        if session_timed_out:
            final_status = "completed"
        await orchestrator.finalize_session(status_value=final_status)


@router.websocket("/public/{slug}")
async def public_voice_stream_websocket(websocket: WebSocket, slug: str):
    """
    Anonymous public voice streaming endpoint for published agents:
    - Requires is_published=True and is_active=True.
    - Strict per-IP rate limiting (per-minute & per-hour via Redis).
    - Decrypts owner's API key server-side only; never exposes it to the client.
    - Saves CallSession with user_id=None and excludes sensitive tools.
    """
    client_ip = websocket.client.host if websocket.client else "unknown"

    allowed_conn, _, rl_backend = await rate_limiter.check_limit(
        f"ws:public:conn:{client_ip}",
        settings.WS_RATE_LIMIT_CONNECTIONS,
        settings.WS_RATE_LIMIT_WINDOW_SECONDS,
    )
    allowed_hour, _, _ = await rate_limiter.check_limit(
        f"ws:public:hour:{client_ip}",
        settings.PUBLIC_MAX_SESSIONS_PER_HOUR_PER_IP,
        3600,
    )
    if not allowed_conn or not allowed_hour:
        logger.warning(f"Public voice rate limit exceeded slug={slug} ip={client_ip}")
        await websocket.close(code=1008, reason="Rate limit exceeded")
        return

    agent: Optional[Agent] = None
    api_key: Optional[str] = None
    rag_api_key: Optional[str] = None
    key_error: Optional[str] = None
    session_id: Optional[str] = None

    async with AsyncSessionLocal() as db:
        agent_res = await db.execute(
            select(Agent).where(
                Agent.slug == slug,
                Agent.is_published == True,
                Agent.is_active == True,
            )
        )
        agent = agent_res.scalar_one_or_none()
        if not agent:
            await websocket.close(code=1008, reason="Agent not available")
            return

        provider_name = agent.llm_provider.lower().strip()
        key_res = await db.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == agent.user_id,
                UserApiKey.provider == provider_name,
            )
        )
        owner_key_row = key_res.scalar_one_or_none()
        if owner_key_row:
            try:
                api_key = decrypt_secret(owner_key_row.encrypted_key)
            except Exception as exc:
                logger.error(f"Owner vault key decryption failed slug={slug}: {exc}")
                key_error = "Agent provider key could not be decrypted."
        else:
            if provider_name == "gemini" and settings.GEMINI_API_KEY:
                api_key = settings.GEMINI_API_KEY
            elif provider_name in ("openai", "gpt") and settings.OPENAI_API_KEY:
                api_key = settings.OPENAI_API_KEY

        if not api_key and not key_error:
            key_error = "Agent provider key is not configured."

        rag_api_key = api_key if provider_name == "gemini" else settings.GEMINI_API_KEY

        if not key_error:
            call_session = CallSession(
                agent_id=agent.id,
                user_id=None,  # Anonymous public session
                status="active",
            )
            db.add(call_session)
            await db.commit()
            await db.refresh(call_session)
            session_id = call_session.id

    await websocket.accept()

    if key_error or not session_id or not agent:
        await websocket.send_json({
            "type": "error",
            "code": "AGENT_UNAVAILABLE",
            "message": key_error or "Agent not available",
        })
        await websocket.close(code=1008, reason="Agent unavailable")
        return

    send_lock = asyncio.Lock()

    async def safe_send_json(data: dict) -> None:
        async with send_lock:
            await websocket.send_json(data)

    async def safe_send_bytes(chunk: bytes) -> None:
        async with send_lock:
            await websocket.send_bytes(chunk)

    try:
        llm = get_llm_provider(agent.llm_provider, api_key or "")
        if hasattr(llm, "thinking_level"):
            llm.thinking_level = "minimal"
        if hasattr(llm, "max_output_tokens"):
            llm.max_output_tokens = 150
        stt = get_stt_provider(agent.stt_provider, api_key=rag_api_key)
        tts = get_tts_provider(agent.tts_provider)
        vad = StreamingVAD(
            sample_rate=16000,
            silence_threshold_ms=settings.VAD_SILENCE_THRESHOLD_MS,
            speech_start_threshold=settings.VAD_SPEECH_START_THRESHOLD,
            speech_end_threshold=settings.VAD_SPEECH_END_THRESHOLD,
            energy_multiplier=settings.VAD_ENERGY_MULTIPLIER,
            min_speech_ms=settings.VAD_MIN_SPEECH_MS,
            max_utterance_seconds=settings.VAD_MAX_UTTERANCE_S,
        )
    except Exception as exc:
        await safe_send_json({"type": "error", "code": "INIT_ERROR", "message": str(exc)})
        await websocket.close(code=1011, reason="Voice pipeline initialization failed")
        return

    orchestrator = VoiceOrchestrator(
        agent=agent,
        session_id=session_id,
        llm_provider=llm,
        stt_provider=stt,
        tts_provider=tts,
        vad=vad,
        send_json=safe_send_json,
        send_bytes=safe_send_bytes,
        db_session_factory=AsyncSessionLocal,
        rag_api_key=rag_api_key,
        is_public_session=True,
    )

    await safe_send_json({
        "type": "session_ready",
        "public": True,
        "session_id": session_id,
        "agent_name": agent.name,
        "rate_limiter_backend": rl_backend,
        "vad_backend": vad.backend_name,
        "max_session_seconds": settings.VOICE_MAX_SESSION_SECONDS,
        "state": orchestrator.state.value,
    })

    session_timed_out = False

    async def session_watchdog() -> None:
        nonlocal session_timed_out
        await asyncio.sleep(settings.VOICE_MAX_SESSION_SECONDS)
        session_timed_out = True
        try:
            await safe_send_json({
                "type": "error",
                "code": "SESSION_TIMEOUT",
                "message": f"Max voice session duration ({settings.VOICE_MAX_SESSION_SECONDS}s) reached.",
            })
            await websocket.close(code=1000, reason="Session duration limit reached")
        except Exception:
            pass

    watchdog_task = asyncio.create_task(session_watchdog())
    final_status = "completed"

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            binary_data = message.get("bytes")
            text_data = message.get("text")

            if binary_data is not None:
                if len(binary_data) > settings.WS_MAX_MESSAGE_BYTES:
                    await safe_send_json({"type": "error", "code": "MESSAGE_TOO_LARGE", "message": "Frame too large."})
                    final_status = "error"
                    await websocket.close(code=1009, reason="Frame exceeds max size")
                    break
                await orchestrator.handle_audio_frame(binary_data)
            elif text_data is not None:
                if len(text_data.encode("utf-8")) > settings.WS_MAX_MESSAGE_BYTES:
                    final_status = "error"
                    await websocket.close(code=1009, reason="Message exceeds max size")
                    break
                try:
                    cmd = json.loads(text_data)
                except json.JSONDecodeError:
                    continue
                action = (cmd.get("type") or "").lower().strip()
                if action == "start":
                    await orchestrator.start_listening()
                elif action == "stop":
                    await orchestrator.stop_listening()
                elif action == "interrupt":
                    await orchestrator.interrupt()
                elif action == "ping":
                    await safe_send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Public voice WS error slug={slug}: {exc}")
        final_status = "error"
    finally:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        if session_timed_out:
            final_status = "completed"
        await orchestrator.finalize_session(status_value=final_status)
