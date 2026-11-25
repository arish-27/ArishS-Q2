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
        stt = get_stt_provider(agent.stt_provider)
        tts = get_tts_provider(agent.tts_provider)
        vad = StreamingVAD(
            sample_rate=16000,
            silence_threshold_ms=settings.VAD_SILENCE_THRESHOLD_MS,
            speech_threshold=settings.VAD_SPEECH_THRESHOLD,
            min_speech_ms=settings.VAD_MIN_SPEECH_MS,
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
                        min_speech_ms=cmd.get("min_speech_ms"),
                    )
                    await safe_send_json({
                        "type": "config_updated",
                        "silence_threshold_ms": vad.silence_threshold_ms,
                        "speech_threshold": vad.speech_threshold,
                    })
                elif action == "ping":
                    await safe_send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Voice WebSocket disconnected session={session_id}")
    except Exception as exc:
        logger.error(f"Voice WebSocket error session={session_id}: {exc}")
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
