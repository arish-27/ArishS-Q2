import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal, utc_now
from app.core.logger import logger
from app.models.agent import Agent
from app.models.document import Document
from app.models.session import CallSession, ConversationMessage
from app.providers.embeddings.base import BaseEmbeddingProvider
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
from app.services.rag_service import retrieve_relevant_chunks
from app.services.sentence_splitter import StreamingSentenceSplitter
from app.services.tool_executor import SSRFBlockedError, ToolValidationError, execute_tool
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
    "Avoid markdown, bullet points, or emojis. "
    "The user's speech is transcribed by an imperfect STT; when a word does not fit the context, "
    "silently infer the intended word from the conversation and any retrieved documents "
    "(for example, 'recipe' while discussing a CV or document means 'resume'), "
    "and do not mention the transcription error unless it is truly ambiguous."
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
        rag_api_key: Optional[str] = None,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        is_public_session: bool = False,
        stt_vocab_hint: Optional[str] = None,
        has_knowledge_base: Optional[bool] = None,
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
        self.context_manager = context_manager or ConversationContextManager(max_turns=6)
        self.rag_api_key = rag_api_key
        self.embedding_provider = embedding_provider
        self.is_public_session = is_public_session
        self.stt_vocab_hint = stt_vocab_hint
        self.has_knowledge_base = has_knowledge_base

        self._state: VoiceState = VoiceState.IDLE
        self._history: List[Dict[str, str]] = []
        self._turn_task: Optional[asyncio.Task] = None
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._state_lock = asyncio.Lock()
        self._vad_prob_frame_counter: int = 0
        self._pending_confirmations: Dict[str, asyncio.Future] = {}

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
        Transition: THINKING|SPEAKING -> LISTENING on manual interrupt.
        Stops active LLM/TTS tasks immediately and resets VAD.
        """
        await self.cancel_active_turn()
        self.vad.reset()
        if self._state in (VoiceState.THINKING, VoiceState.SPEAKING):
            await self.send_json({"type": "interrupt", "reason": "user_interrupted"})
            await self.send_json({"type": "audio_stop", "reason": "interrupted"})
            await self.transition(VoiceState.LISTENING, reason="user_interrupted")

    async def barge_in(self) -> None:
        """
        Transition: THINKING|SPEAKING -> LISTENING on VAD-confirmed speech (~250ms debounce).
        Cancels active LLM/TTS tasks, flushes browser audio queue, and preserves the active
        VAD speech buffer so the interrupting utterance is captured without clipping.
        """
        await self.cancel_active_turn()
        if self._state in (VoiceState.THINKING, VoiceState.SPEAKING):
            await self.send_json({"type": "interrupt", "reason": "barge_in"})
            await self.send_json({"type": "audio_stop", "reason": "barge_in"})
            await self.transition(VoiceState.LISTENING, reason="barge_in")

    def resolve_tool_confirmation(self, confirm_id: str, approved: bool) -> None:
        fut = self._pending_confirmations.pop(confirm_id, None)
        if fut and not fut.done():
            fut.set_result(approved)

    async def cancel_active_turn(self) -> None:
        self._cancel_event.set()
        for fut in list(self._pending_confirmations.values()):
            if not fut.done():
                fut.cancel()
        self._pending_confirmations.clear()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except asyncio.CancelledError:
                pass
        self._turn_task = None

    async def handle_audio_frame(self, pcm16_bytes: bytes) -> None:
        """Feeds incoming 16kHz PCM16 audio into server-side VAD for turn-taking and barge-in."""
        if self._state == VoiceState.IDLE:
            return

        events = self.vad.process_chunk(pcm16_bytes)

        # Barge-in detection while assistant is THINKING or SPEAKING (debounced ~250ms)
        if self._state in (VoiceState.SPEAKING, VoiceState.THINKING):
            if self.vad.confirmed_speech_ms >= settings.VAD_BARGE_IN_DEBOUNCE_MS:
                await self.barge_in()
                await self.send_json({"type": "vad_speech_start", "barge_in": True})
            return

        self._vad_prob_frame_counter += 1
        if self._vad_prob_frame_counter % 3 == 0:
            await self.send_json({
                "type": "vad_prob",
                "prob": round(self.vad.last_prob, 3),
                "noise_floor": round(self.vad.noise_floor_rms, 5),
            })

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
        rag_sources: List[Dict[str, Any]] = []
        user_text: Optional[str] = None
        stt_result: Any = None

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
            # 0. For public anonymous sessions, verify agent is still published & active before each turn
            if self.is_public_session:
                async with self.db_session_factory() as pub_db:
                    pub_row = (
                        await pub_db.execute(
                            select(Agent.is_published, Agent.is_active).where(Agent.id == self.agent.id)
                        )
                    ).first()
                    if not pub_row or not pub_row[0] or not pub_row[1]:
                        await self.send_json({
                            "type": "error",
                            "code": "AGENT_UNPUBLISHED",
                            "message": "Agent is no longer published or active.",
                        })
                        await self.stop_listening()
                        return

            # 1. Speech-to-Text
            try:
                stt_result = await self.stt.transcribe(
                    utterance_pcm16,
                    sample_rate=self.vad.sample_rate,
                    language=self.agent.stt_language,
                    context_prompt=self.stt_vocab_hint,
                )
            except TypeError:
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

            # 1b. Fast RAG retrieval when agent has indexed knowledge documents
            rag_context_block = ""
            if self.rag_api_key or self.embedding_provider is not None:
                try:
                    async with self.db_session_factory() as rag_db:
                        has_doc = (
                            await rag_db.execute(
                                select(Document.id)
                                .where(Document.agent_id == self.agent.id, Document.status == "indexed")
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if has_doc:
                            chunks = await retrieve_relevant_chunks(
                                db=rag_db,
                                agent_id=self.agent.id,
                                query=user_text,
                                api_key=self.rag_api_key or "",
                                top_k=settings.RAG_TOP_K,
                                similarity_threshold=settings.RAG_SIMILARITY_THRESHOLD,
                                embedding_provider=self.embedding_provider,
                            )
                            if chunks:
                                rag_sources = [
                                    {
                                        "file": c["filename"],
                                        "score": c["score"],
                                        "chunk_index": c["chunk_index"],
                                    }
                                    for c in chunks
                                ]
                                context_lines = "\n\n".join(
                                    f"[Source: {c['filename']} (score={c['score']})]\n{c['content']}"
                                    for c in chunks
                                )
                                rag_context_block = (
                                    "\n\n[Knowledge Base Context]: Use the following retrieved context "
                                    "to answer the user's question accurately when relevant:\n"
                                    f"{context_lines}"
                                )
                                await self.send_json({"type": "rag_sources", "sources": rag_sources})
                except Exception as rag_exc:
                    logger.warning(f"RAG retrieval skipped session={self.session_id}: {rag_exc}")

            voice_system_prompt = (
                f"{self.agent.system_prompt or ''}{rag_context_block}{VOICE_SYSTEM_PROMPT_ADDENDUM}"
            ).strip()
            turn_meta: Dict[str, Any] = {
                "model_used": self.agent.llm_model,
                "retry_count": 0,
            }

            executed_tool_calls: List[Dict[str, Any]] = []
            executed_tool_results: List[Dict[str, Any]] = []
            direct_tool_final_text: Optional[str] = None

            active_tools = self._get_active_tools()
            if active_tools:
                tools_by_name = {t.name: t for t in active_tools}
                tool_decls = []
                for t in active_tools:
                    try:
                        params = json.loads(t.parameters_schema or "{}")
                    except json.JSONDecodeError:
                        params = {"type": "object", "properties": {}}
                    tool_decls.append({"name": t.name, "description": t.description, "parameters": params})

                working_msgs: List[Dict[str, Any]] = list(prepared_messages)
                for _ in range(3):
                    if self._cancel_event.is_set():
                        return
                    tool_turn = await self.llm.generate_with_tools(
                        messages=working_msgs,
                        tools=tool_decls,
                        system_prompt=voice_system_prompt,
                        temperature=self.agent.temperature,
                        model=self.agent.llm_model,
                    )
                    if not tool_turn.tool_calls:
                        direct_tool_final_text = tool_turn.text
                        break

                    working_msgs.append({
                        "role": "assistant",
                        "content": tool_turn.text or "",
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in tool_turn.tool_calls
                        ],
                    })
                    for tc in tool_turn.tool_calls:
                        if self._cancel_event.is_set():
                            return
                        tool_obj = tools_by_name.get(tc.name)
                        if not tool_obj:
                            res_payload: Dict[str, Any] = {"error": f"Unknown tool '{tc.name}'"}
                            dur_ms = 0.0
                        else:
                            res_payload, dur_ms = await self._run_single_voice_tool(tool_obj, tc.arguments)

                        executed_tool_calls.append({"name": tc.name, "arguments": tc.arguments})
                        executed_tool_results.append({"name": tc.name, "result": res_payload, "duration_ms": dur_ms})
                        await self.send_json({
                            "type": "tool_call",
                            "name": tc.name,
                            "arguments": tc.arguments,
                            "result": res_payload,
                            "duration_ms": dur_ms,
                        })
                        working_msgs.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": res_payload,
                        })

            # 2. Concurrent LLM producer & TTS consumer
            async def llm_producer() -> None:
                llm_start = time.perf_counter()
                splitter = StreamingSentenceSplitter()

                if direct_tool_final_text is not None:
                    try:
                        if direct_tool_final_text:
                            timings["llm_first_token_ms"] = 1.0
                            collected_tokens.append(direct_tool_final_text)
                            await self.send_json({"type": "llm_token", "token": direct_tool_final_text})
                            for sentence in splitter.feed(direct_tool_final_text):
                                if timings["first_sentence_queued_perf"] is None:
                                    timings["first_sentence_queued_perf"] = time.perf_counter()
                                await sentence_queue.put(sentence)
                            for sentence in splitter.flush():
                                if timings["first_sentence_queued_perf"] is None:
                                    timings["first_sentence_queued_perf"] = time.perf_counter()
                                await sentence_queue.put(sentence)
                        timings["llm_total_ms"] = (time.perf_counter() - llm_start) * 1000.0
                    finally:
                        await sentence_queue.put(None)
                    return
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
                rag_sources=rag_sources,
                tool_calls=executed_tool_calls,
                tool_results=executed_tool_results,
                interrupted=False,
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
                f"stt_provider={getattr(stt_result, 'provider', 'unknown')} "
                f"stt_avg_logprob={stt_result.avg_logprob} model_used={turn_meta['model_used']} "
                f"retry_count={turn_meta['retry_count']}"
            )

            # Transition: THINKING|SPEAKING -> LISTENING once full turn response finishes
            if self._state in (VoiceState.SPEAKING, VoiceState.THINKING):
                await self.transition(VoiceState.LISTENING, reason="turn_complete")

        except asyncio.CancelledError:
            logger.info(f"Turn task cancelled in session {self.session_id}")
            partial_text = "".join(collected_tokens).strip()
            if user_text and partial_text:
                self._history.append({"role": "assistant", "content": partial_text})
                try:
                    await self.send_json({
                        "type": "transcript",
                        "role": "assistant",
                        "text": partial_text,
                        "interrupted": True,
                    })
                except Exception:
                    pass
                try:
                    partial_metrics = TurnLatencyMetrics(
                        stt_latency_ms=round(getattr(stt_result, "latency_ms", 0.0) or 0.0, 2),
                        llm_first_token_ms=round(timings["llm_first_token_ms"] or 0.0, 2),
                        llm_total_ms=round((time.perf_counter() - turn_start) * 1000.0, 2),
                        tts_first_audio_ms=round(timings["tts_first_audio_ms"] or 0.0, 2),
                        tts_total_ms=round(timings["tts_total_ms"] or 0.0, 2),
                        e2e_latency_ms=round((time.perf_counter() - turn_start) * 1000.0, 2),
                    )
                    await asyncio.shield(
                        self._persist_turn(
                            user_text=user_text,
                            assistant_text=partial_text,
                            audio_duration_ms=int(round(audio_duration_ms)),
                            metrics=partial_metrics,
                            rag_sources=rag_sources,
                            interrupted=True,
                        )
                    )
                except Exception as persist_exc:
                    logger.warning(f"Failed to persist interrupted turn: {persist_exc}")
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
        await self._record_session_error(code, message)
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

    def _get_active_tools(self) -> List[Any]:
        tools = list(getattr(self.agent, "tools", []) or [])
        if self.is_public_session and not settings.ALLOW_SENSITIVE_TOOLS_IN_PUBLIC:
            return [t for t in tools if not getattr(t, "is_sensitive", False)]
        return tools

    async def _run_single_voice_tool(self, tool_obj: Any, raw_args: Dict[str, Any]) -> tuple[Dict[str, Any], float]:
        from app.services.tool_executor import validate_tool_arguments

        try:
            validate_tool_arguments(tool_obj.parameters_schema, raw_args)
        except ToolValidationError as exc:
            return {"error": f"Invalid arguments: {exc}"}, 0.0

        if getattr(tool_obj, "is_sensitive", False):
            confirm_id = str(uuid.uuid4())
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending_confirmations[confirm_id] = fut

            await self.send_json({
                "type": "tool_confirm",
                "confirm_id": confirm_id,
                "tool_name": tool_obj.name,
                "arguments": raw_args,
            })
            spoken_prompt = f"Should I go ahead and run {tool_obj.name.replace('_', ' ')}?"
            await self._speak_fallback_line(spoken_prompt)

            try:
                approved = await asyncio.wait_for(fut, timeout=settings.TOOL_CONFIRM_TIMEOUT_S)
            except asyncio.TimeoutError:
                self._pending_confirmations.pop(confirm_id, None)
                return {"error": "User confirmation timed out after 30 seconds.", "declined": True}, 0.0
            except asyncio.CancelledError:
                self._pending_confirmations.pop(confirm_id, None)
                raise

            if not approved:
                return {"error": "User declined to execute sensitive tool.", "declined": True}, 0.0

        # Non-sensitive or confirmed: speak short filler while executing
        filler_task = asyncio.create_task(self._speak_fallback_line("Let me check that for you."))
        try:
            result, dur_ms = await execute_tool(tool_obj, raw_args)
            await filler_task
            return result, dur_ms
        except (ToolValidationError, SSRFBlockedError) as exc:
            await filler_task
            await self._record_session_error("TOOL_ERROR", str(exc))
            return {"error": str(exc)}, 0.0
        except Exception as exc:
            await filler_task
            await self._record_session_error("TOOL_ERROR", f"Tool execution error: {exc}")
            return {"error": f"Tool execution error: {exc}"}, 0.0

    async def _record_session_error(self, code: str, message: str) -> None:
        """Increments turn-level error_count and records last_error on CallSession."""
        try:
            async with self.db_session_factory() as db:
                sess = await db.get(CallSession, self.session_id)
                if sess:
                    sess.error_count = (sess.error_count or 0) + 1
                    sess.last_error = f"{code}: {message}"[:500]
                    await db.commit()
        except Exception as db_exc:
            logger.warning(f"Failed to record session error: {db_exc}")

    async def _persist_turn(
        self,
        user_text: str,
        assistant_text: str,
        audio_duration_ms: int,
        metrics: TurnLatencyMetrics,
        rag_sources: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        interrupted: bool = False,
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
                rag_sources_json=json.dumps(rag_sources) if rag_sources else None,
                tool_calls_json=json.dumps(tool_calls) if tool_calls else None,
                tool_results_json=json.dumps(tool_results) if tool_results else None,
                interrupted=interrupted,
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
