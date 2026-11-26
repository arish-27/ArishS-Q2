import asyncio
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal, utc_now
from app.core.logger import logger
from app.models.agent import Agent
from app.models.session import CallSession, ConversationMessage
from app.providers.llm.base import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)
from app.providers.stt.base import BaseSTTProvider
from app.providers.tts.base import BaseTTSProvider
from app.services.context_manager import ConversationContextManager
from app.services.sentence_splitter import StreamingSentenceSplitter
from app.vad.detector import StreamingVAD


class VoiceState(str, Enum):
    """Explicit lifecycle states of a real-time duplex voice session."""
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


class InvalidStateTransition(Exception):
    """Raised when attempting an illegal voice orchestrator state transition."""
    pass


# Allowed state transition table enforced by the orchestrator state machine.
ALLOWED_TRANSITIONS: Dict[VoiceState, set] = {
    VoiceState.IDLE: {VoiceState.LISTENING, VoiceState.IDLE},
    VoiceState.LISTENING: {VoiceState.THINKING, VoiceState.IDLE, VoiceState.LISTENING},
    VoiceState.THINKING: {VoiceState.SPEAKING, VoiceState.LISTENING, VoiceState.IDLE},
    VoiceState.SPEAKING: {VoiceState.LISTENING, VoiceState.IDLE},
}


@dataclass
class TurnLatencyMetrics:
    stt_latency_ms: float
    llm_first_token_ms: float
    llm_total_ms: float
    tts_first_audio_ms: float
    tts_total_ms: float
    e2e_latency_ms: float


SendJsonFn = Callable[[Dict[str, Any]], Awaitable[None]]
SendBytesFn = Callable[[bytes], Awaitable[None]]


VOICE_SYSTEM_PROMPT_ADDENDUM = (
    "\n\n[Voice Mode]: Reply in 1-2 short, natural spoken sentences. "
    "Avoid markdown, bullet points, or emojis."
)
FALLBACK_ERROR_SPEECH = "Sorry, I had trouble. Could you repeat that?"
TRANSIENT_LLM_ERRORS = (LLMServiceUnavailableError, LLMRateLimitError, LLMTimeoutError)


class VoiceOrchestrator:
    """
    Coordinates the real-time voice turn pipeline:
    Audio Frames -> Server-side VAD -> STT -> Context-Managed LLM Stream
    -> Sentence Splitter -> Sentence-level TTS Stream -> Browser Playback.
    """

    def __init__(
        self,
        agent: Agent,
        session_id: str,
        llm_provider: BaseLLMProvider,
        stt_provider: BaseSTTProvider,
        tts_provider: BaseTTSProvider,
        vad: StreamingVAD,
        send_json: SendJsonFn,
        send_bytes: SendBytesFn,
        db_session_factory=AsyncSessionLocal,
        context_manager: Optional[ConversationContextManager] = None,
    ):
        self.agent = agent
        self.session_id = session_id
        self.llm = llm_provider
        self.stt = stt_provider
        self.tts = tts_provider
        self.vad = vad
        self.send_json = send_json
        self.send_bytes = send_bytes
        self.db_session_factory = db_session_factory
        self.context_manager = context_manager or ConversationContextManager()

        self._state: VoiceState = VoiceState.IDLE
        self._history: List[Dict[str, str]] = []
        self._turn_task: Optional[asyncio.Task] = None
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._state_lock = asyncio.Lock()

    @property
    def state(self) -> VoiceState:
        return self._state

    async def transition(self, target: VoiceState, reason: str = "") -> None:
        """
        Validates and executes a state machine transition, notifying the WebSocket client.
        """
        async with self._state_lock:
            current = self._state
            if target not in ALLOWED_TRANSITIONS[current]:
                raise InvalidStateTransition(
                    f"Illegal voice state transition: {current.value} -> {target.value} ({reason})"
                )
            if current == target:
                return
            self._state = target
            logger.info(
                f"VoiceOrchestrator session={self.session_id} transition {current.value}->{target.value} reason={reason}"
            )
        await self.send_json({"type": "state", "state": target.value, "reason": reason})

    async def start_listening(self) -> None:
        """Transition: IDLE -> LISTENING when client activates microphone stream."""
        self.vad.reset()
        await self.transition(VoiceState.LISTENING, reason="mic_stream_started")

    async def stop_listening(self) -> None:
        """Transition: LISTENING|THINKING|SPEAKING -> IDLE when session stops or pauses."""
        await self.cancel_active_turn()
        self.vad.reset()
        await self.transition(VoiceState.IDLE, reason="client_stopped")

    async def interrupt(self) -> None:
        """
        Transition: THINKING|SPEAKING -> LISTENING on user barge-in / manual interrupt.
        Stops active LLM/TTS tasks immediately so the user can speak cleanly.
        """
        await self.cancel_active_turn()
        self.vad.reset()
        if self._state in (VoiceState.THINKING, VoiceState.SPEAKING):
            await self.send_json({"type": "audio_stop", "reason": "interrupted"})
            await self.transition(VoiceState.LISTENING, reason="user_interrupted")

    async def cancel_active_turn(self) -> None:
        self._cancel_event.set()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except asyncio.CancelledError:
                pass
        self._turn_task = None

    async def handle_audio_frame(self, pcm16_bytes: bytes) -> None:
        """Feeds incoming 16kHz PCM16 audio into server-side VAD while LISTENING."""
        if self._state != VoiceState.LISTENING:
            return

        events = self.vad.process_chunk(pcm16_bytes)
        for ev in events:
            if ev.speech_start:
                await self.send_json({"type": "vad_speech_start"})
            if ev.utterance_pcm16 is not None:
                await self._begin_turn(ev.utterance_pcm16, ev.duration_ms)
                break  # Turn transitions state to THINKING

    async def force_end_utterance(self) -> None:
        """Manually flushes buffered speech (e.g. push-to-talk release) and starts turn."""
        if self._state != VoiceState.LISTENING:
            return
        utterance = self.vad.flush()
        if utterance:
            duration_ms = (len(utterance) / 2.0 / self.vad.sample_rate) * 1000.0
            await self._begin_turn(utterance, duration_ms)

    async def _begin_turn(self, utterance_pcm16: bytes, duration_ms: float) -> None:
        """Transition: LISTENING -> THINKING once VAD detects end of utterance."""
        await self.send_json({"type": "vad_speech_end", "duration_ms": round(duration_ms, 1)})
        await self.transition(VoiceState.THINKING, reason="vad_utterance_complete")
        self._cancel_event.clear()
        self._turn_task = asyncio.create_task(
            self._execute_turn(utterance_pcm16, duration_ms)
        )

    async def _execute_turn(self, utterance_pcm16: bytes, audio_duration_ms: float) -> None:
        """
        Executes STT -> Context-Managed LLM Stream -> Sentence-level TTS streaming -> DB persistence.
        """
        turn_start = time.perf_counter()
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        collected_tokens: List[str] = []

        # Shared timing holders updated across concurrent LLM producer & TTS consumer
        timings: Dict[str, Optional[float]] = {
            "llm_first_token_ms": None,
            "llm_total_ms": None,
            "tts_first_audio_ms": None,
            "tts_total_ms": None,
            "first_audio_sent_perf": None,
            "first_sentence_queued_perf": None,
        }

        try:
            # 1. Speech-to-Text
            stt_result = await self.stt.transcribe(
                utterance_pcm16,
                sample_rate=self.vad.sample_rate,
                language=self.agent.stt_language,
            )
            if self._cancel_event.is_set():
                return

            user_text = stt_result.text.strip()
            alnum_count = len(re.sub(r"[^A-Za-z0-9]", "", user_text))
            if (
                not user_text
                or alnum_count < 2
                or (stt_result.avg_logprob is not None and stt_result.avg_logprob <= -1.0)
            ):
                # Transition: THINKING -> LISTENING when audio had no recognizable speech
                logger.info(
                    f"VoiceTurn dropped session={self.session_id} transcript={user_text!r} "
                    f"stt_avg_logprob={stt_result.avg_logprob} reason=empty_or_low_confidence"
                )
                await self.transition(VoiceState.LISTENING, reason="empty_transcript")
                return

            await self.send_json({
                "type": "transcript",
                "role": "user",
                "text": user_text,
                "stt_latency_ms": round(stt_result.latency_ms, 2),
                "audio_duration_ms": round(audio_duration_ms, 1),
            })

            self._history.append({"role": "user", "content": user_text})
            prepared_messages = await self.context_manager.prepare_context(
                messages=list(self._history),
                llm_provider=self.llm,
                model=self.agent.llm_model,
            )

            voice_system_prompt = f"{self.agent.system_prompt or ''}{VOICE_SYSTEM_PROMPT_ADDENDUM}".strip()
            turn_meta: Dict[str, Any] = {
                "model_used": self.agent.llm_model,
                "retry_count": 0,
            }

            # 2. Concurrent LLM producer & TTS consumer
            async def llm_producer() -> None:
                llm_start = time.perf_counter()
                splitter = StreamingSentenceSplitter()
                max_transient_retries = 2
                max_timeout_retries = 1
                primary_model = self.agent.llm_model
                fallback_model = (
                    settings.DEFAULT_GEMINI_FALLBACK_MODEL
                    if (
                        self.agent.llm_provider == "gemini"
                        and settings.DEFAULT_GEMINI_FALLBACK_MODEL
                        and settings.DEFAULT_GEMINI_FALLBACK_MODEL != primary_model
                    )
                    else None
                )

                last_exc: Optional[Exception] = None
                candidate_model = primary_model
                primary_attempt = 0
                using_fallback = False

                try:
                    while True:
                        if self._cancel_event.is_set():
                            return
                        turn_meta["model_used"] = candidate_model
                        if not using_fallback:
                            turn_meta["retry_count"] = primary_attempt

                        any_token_emitted = False
                        stream_iter = self.llm.generate_stream(
                            messages=prepared_messages,
                            system_prompt=voice_system_prompt,
                            temperature=self.agent.temperature,
                            model=candidate_model,
                        ).__aiter__()
                        try:
                            while True:
                                try:
                                    if not any_token_emitted:
                                        token = await asyncio.wait_for(
                                            stream_iter.__anext__(),
                                            timeout=settings.LLM_FIRST_TOKEN_TIMEOUT_S,
                                        )
                                    else:
                                        token = await stream_iter.__anext__()
                                except StopAsyncIteration:
                                    break
                                except asyncio.TimeoutError as timeout_exc:
                                    aclose = getattr(stream_iter, "aclose", None)
                                    if aclose:
                                        try:
                                            await aclose()
                                        except Exception:
                                            pass
                                    raise LLMTimeoutError(
                                        f"LLM first-token timed out after {settings.LLM_FIRST_TOKEN_TIMEOUT_S}s "
                                        f"on model={candidate_model}"
                                    ) from timeout_exc

                                if self._cancel_event.is_set():
                                    break
                                if token:
                                    any_token_emitted = True
                                    if timings["llm_first_token_ms"] is None:
                                        timings["llm_first_token_ms"] = (time.perf_counter() - llm_start) * 1000.0
                                collected_tokens.append(token)
                                await self.send_json({"type": "llm_token", "token": token})

                                for sentence in splitter.feed(token):
                                    if timings["first_sentence_queued_perf"] is None:
                                        timings["first_sentence_queued_perf"] = time.perf_counter()
                                    await sentence_queue.put(sentence)

                            for sentence in splitter.flush():
                                if timings["first_sentence_queued_perf"] is None:
                                    timings["first_sentence_queued_perf"] = time.perf_counter()
                                await sentence_queue.put(sentence)

                            timings["llm_total_ms"] = (time.perf_counter() - llm_start) * 1000.0
                            last_exc = None
                            break
                        except TRANSIENT_LLM_ERRORS as exc:
                            last_exc = exc
                            if any_token_emitted or self._cancel_event.is_set():
                                raise
                            is_timeout = isinstance(exc, LLMTimeoutError)
                            allowed_retries = max_timeout_retries if is_timeout else max_transient_retries

                            if not using_fallback and primary_attempt < allowed_retries:
                                primary_attempt += 1
                                turn_meta["retry_count"] = primary_attempt
                                backoff_s = 0.25 if is_timeout else 0.5 * (2 ** (primary_attempt - 1))
                                logger.warning(
                                    f"LLM failed on model={candidate_model} retry_count={primary_attempt} "
                                    f"error={exc}; retrying in {backoff_s:.2f}s"
                                )
                                await asyncio.sleep(backoff_s)
                                continue

                            if not using_fallback and fallback_model:
                                logger.warning(
                                    f"LLM failed on model={candidate_model} retry_count={turn_meta['retry_count']} "
                                    f"error={exc}; switching to fallback_model={fallback_model}"
                                )
                                using_fallback = True
                                candidate_model = fallback_model
                                continue

                            logger.error(
                                f"LLM failed on model={candidate_model} retry_count={turn_meta['retry_count']} "
                                f"error={exc}; no retries/fallback remaining"
                            )
                            raise
                    if last_exc is not None:
                        raise last_exc
                finally:
                    await sentence_queue.put(None)

            async def tts_consumer() -> None:
                sentence_idx = 0
                tts_total_start: Optional[float] = None
                while True:
                    sentence = await sentence_queue.get()
                    if sentence is None or self._cancel_event.is_set():
                        break

                    if tts_total_start is None:
                        tts_total_start = time.perf_counter()

                    sentence_tts_start = time.perf_counter()
                    sent_header = False

                    async for audio_chunk in self.tts.synthesize_stream(
                        sentence,
                        voice=self.agent.tts_voice,
                        cancel_event=self._cancel_event,
                    ):
                        if self._cancel_event.is_set():
                            break
                        if not sent_header:
                            # Transition: THINKING -> SPEAKING on first synthesized TTS audio frame
                            if self._state == VoiceState.THINKING:
                                await self.transition(VoiceState.SPEAKING, reason="tts_first_audio_ready")
                            if timings["tts_first_audio_ms"] is None:
                                now_perf = time.perf_counter()
                                ref = timings["first_sentence_queued_perf"] or sentence_tts_start
                                timings["tts_first_audio_ms"] = (now_perf - ref) * 1000.0
                                timings["first_audio_sent_perf"] = now_perf
                            await self.send_json({
                                "type": "audio_start",
                                "sentence_index": sentence_idx,
                                "text": sentence,
                                "format": "mp3",
                            })
                            sent_header = True
                        await self.send_bytes(audio_chunk)

                    if sent_header:
                        await self.send_json({
                            "type": "audio_end",
                            "sentence_index": sentence_idx,
                        })
                        sentence_idx += 1

                if tts_total_start is not None:
                    timings["tts_total_ms"] = (time.perf_counter() - tts_total_start) * 1000.0

            await asyncio.gather(llm_producer(), tts_consumer())

            if self._cancel_event.is_set():
                return

            assistant_text = "".join(collected_tokens).strip()
            if assistant_text:
                self._history.append({"role": "assistant", "content": assistant_text})
                await self.send_json({
                    "type": "transcript",
                    "role": "assistant",
                    "text": assistant_text,
                })

            llm_first_ms = round(timings["llm_first_token_ms"] or 0.0, 2)
            llm_total_ms = round(timings["llm_total_ms"] or 0.0, 2)
            tts_first_ms = round(timings["tts_first_audio_ms"] or 0.0, 2)
            tts_total_ms = round(timings["tts_total_ms"] or 0.0, 2)
            end_perf = timings["first_audio_sent_perf"] or time.perf_counter()
            e2e_ms = round((end_perf - turn_start) * 1000.0, 2)

            metrics = TurnLatencyMetrics(
                stt_latency_ms=round(stt_result.latency_ms, 2),
                llm_first_token_ms=llm_first_ms,
                llm_total_ms=llm_total_ms,
                tts_first_audio_ms=tts_first_ms,
                tts_total_ms=tts_total_ms,
                e2e_latency_ms=e2e_ms,
            )

            await self._persist_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                audio_duration_ms=int(round(audio_duration_ms)),
                metrics=metrics,
            )

            await self.send_json({
                "type": "turn_metrics",
                "stt_latency_ms": metrics.stt_latency_ms,
                "llm_first_token_ms": metrics.llm_first_token_ms,
                "llm_total_ms": metrics.llm_total_ms,
                "tts_first_audio_ms": metrics.tts_first_audio_ms,
                "tts_total_ms": metrics.tts_total_ms,
                "e2e_latency_ms": metrics.e2e_latency_ms,
            })

            # Log per-turn diagnostics
            logger.info(
                f"VoiceTurn session={self.session_id} transcript={user_text!r} "
                f"stt_avg_logprob={stt_result.avg_logprob} model_used={turn_meta['model_used']} "
                f"retry_count={turn_meta['retry_count']}"
            )

            # Transition: THINKING|SPEAKING -> LISTENING once full turn response finishes
            if self._state in (VoiceState.SPEAKING, VoiceState.THINKING):
                await self.transition(VoiceState.LISTENING, reason="turn_complete")

        except asyncio.CancelledError:
            logger.info(f"Turn task cancelled in session {self.session_id}")
            raise
        except LLMAuthenticationError as exc:
            await self._handle_turn_failure("AUTH_ERROR", str(exc), user_text=locals().get("user_text"), stt_result=locals().get("stt_result"), turn_meta=locals().get("turn_meta"))
        except LLMRateLimitError as exc:
            await self._handle_turn_failure("RATE_LIMIT", str(exc), user_text=locals().get("user_text"), stt_result=locals().get("stt_result"), turn_meta=locals().get("turn_meta"))
        except LLMTimeoutError as exc:
            await self._handle_turn_failure("TIMEOUT", str(exc), user_text=locals().get("user_text"), stt_result=locals().get("stt_result"), turn_meta=locals().get("turn_meta"))
        except LLMServiceUnavailableError as exc:
            await self._handle_turn_failure("SERVICE_UNAVAILABLE", str(exc), user_text=locals().get("user_text"), stt_result=locals().get("stt_result"), turn_meta=locals().get("turn_meta"))
        except Exception as exc:
            logger.error(f"Voice turn error in session {self.session_id}: {exc}")
            await self._handle_turn_failure("PIPELINE_ERROR", str(exc), user_text=locals().get("user_text"), stt_result=locals().get("stt_result"), turn_meta=locals().get("turn_meta"))

    async def _handle_turn_failure(
        self,
        code: str,
        message: str,
        user_text: Optional[str] = None,
        stt_result: Any = None,
        turn_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Reports error to UI, shows & speaks fallback line via TTS, and returns to LISTENING."""
        meta = turn_meta or {"model_used": self.agent.llm_model, "retry_count": 0}
        avg_lp = getattr(stt_result, "avg_logprob", None) if stt_result is not None else None
        logger.warning(
            f"VoiceTurn failed session={self.session_id} code={code} transcript={user_text!r} "
            f"stt_avg_logprob={avg_lp} model_used={meta.get('model_used')} "
            f"retry_count={meta.get('retry_count')} error={message}"
        )
        await self.send_json({"type": "error", "code": code, "message": message})
        await self.send_json({
            "type": "transcript",
            "role": "assistant",
            "text": FALLBACK_ERROR_SPEECH,
        })
        await self._speak_fallback_line(FALLBACK_ERROR_SPEECH)
        if self._state != VoiceState.IDLE:
            await self.transition(VoiceState.LISTENING, reason=f"fallback_{code.lower()}")

    async def _speak_fallback_line(self, text: str) -> None:
        """Synthesizes and streams a short spoken fallback prompt on pipeline failure."""
        if self._cancel_event.is_set():
            return
        sent_header = False
        try:
            async for chunk in self.tts.synthesize_stream(
                text,
                voice=self.agent.tts_voice,
                cancel_event=self._cancel_event,
            ):
                if self._cancel_event.is_set():
                    break
                if not sent_header:
                    if self._state == VoiceState.THINKING:
                        await self.transition(VoiceState.SPEAKING, reason="tts_fallback_audio")
                    await self.send_json({
                        "type": "audio_start",
                        "sentence_index": 0,
                        "text": text,
                        "format": "mp3",
                    })
                    sent_header = True
                await self.send_bytes(chunk)
            if sent_header:
                await self.send_json({"type": "audio_end", "sentence_index": 0})
        except Exception as tts_exc:
            logger.warning(f"Fallback TTS playback failed in session {self.session_id}: {tts_exc}")

    async def _persist_turn(
        self,
        user_text: str,
        assistant_text: str,
        audio_duration_ms: int,
        metrics: TurnLatencyMetrics,
    ) -> None:
        """Persists both user and assistant messages plus latency metrics to PostgreSQL/SQLite."""
        async with self.db_session_factory() as db:
            user_msg = ConversationMessage(
                session_id=self.session_id,
                role="user",
                content=user_text,
                audio_duration_ms=audio_duration_ms,
                stt_latency_ms=metrics.stt_latency_ms,
            )
            asst_msg = ConversationMessage(
                session_id=self.session_id,
                role="assistant",
                content=assistant_text,
                stt_latency_ms=metrics.stt_latency_ms,
                llm_first_token_ms=metrics.llm_first_token_ms,
                llm_latency_ms=metrics.llm_total_ms,
                tts_first_audio_ms=metrics.tts_first_audio_ms,
                tts_latency_ms=metrics.tts_total_ms,
                e2e_latency_ms=metrics.e2e_latency_ms,
            )
            db.add(user_msg)
            db.add(asst_msg)

            sess = await db.get(CallSession, self.session_id)
            if sess:
                sess.total_turns += 1
                prev_avg = sess.avg_latency_ms or 0.0
                sess.avg_latency_ms = round(
                    (prev_avg * (sess.total_turns - 1) + metrics.e2e_latency_ms) / sess.total_turns,
                    2,
                )
            await db.commit()

    async def finalize_session(self, status_value: str = "completed") -> None:
        """Closes active tasks and marks CallSession ended in the database."""
        await self.cancel_active_turn()
        async with self.db_session_factory() as db:
            sess = await db.get(CallSession, self.session_id)
            if sess:
                now = utc_now()
                sess.ended_at = now
                sess.status = status_value
                if sess.started_at:
                    sess.duration_seconds = max(0, int((now - sess.started_at).total_seconds()))
                await db.commit()
