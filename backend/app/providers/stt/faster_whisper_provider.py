import asyncio
import os
import re
import threading
import time
from typing import Dict, Optional, Tuple
import numpy as np
from app.core.config import settings
from app.core.logger import logger
from app.providers.stt.base import BaseSTTProvider, STTProviderError, STTResult

_MODEL_CACHE: Dict[Tuple[str, str, str, int], object] = {}
_MODEL_LOCK = threading.Lock()


def _resolve_cpu_threads() -> int:
    if settings.WHISPER_CPU_THREADS and settings.WHISPER_CPU_THREADS > 0:
        return settings.WHISPER_CPU_THREADS
    return os.cpu_count() or 4


def _get_or_load_whisper_model(
    model_size: str,
    device: str,
    compute_type: str,
    cpu_threads: Optional[int] = None,
):
    """Thread-safe lazy singleton loader for faster-whisper CTranslate2 model."""
    threads = cpu_threads or _resolve_cpu_threads()
    key = (model_size, device, compute_type, threads)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    with _MODEL_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        from faster_whisper import WhisperModel

        logger.info(
            f"Loading faster-whisper model size={model_size} device={device} "
            f"compute_type={compute_type} cpu_threads={threads}"
        )
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=threads,
        )
        _MODEL_CACHE[key] = model
        return model


def _warmup_sync() -> None:
    target_size = settings.WHISPER_ENGLISH_MODEL_SIZE or settings.WHISPER_MODEL_SIZE
    threads = _resolve_cpu_threads()
    model = _get_or_load_whisper_model(
        target_size,
        settings.WHISPER_DEVICE,
        settings.WHISPER_COMPUTE_TYPE,
        threads,
    )
    silence = np.zeros(3200, dtype=np.float32)  # 200ms @ 16kHz
    segments, _ = model.transcribe(
        silence,
        language="en",
        beam_size=settings.WHISPER_BEAM_SIZE,
        temperature=0.0,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    list(segments)


async def warmup_whisper_model() -> None:
    """Pre-loads and warms up the configured faster-whisper model at application startup."""
    start = time.perf_counter()
    await asyncio.to_thread(_warmup_sync)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    target_size = settings.WHISPER_ENGLISH_MODEL_SIZE or settings.WHISPER_MODEL_SIZE
    logger.info(
        f"faster-whisper warmup complete size={target_size} "
        f"device={settings.WHISPER_DEVICE} compute_type={settings.WHISPER_COMPUTE_TYPE} "
        f"cpu_threads={_resolve_cpu_threads()} beam_size={settings.WHISPER_BEAM_SIZE} "
        f"elapsed_ms={elapsed_ms:.1f}"
    )

# Common Whisper hallucinations on short noise / silence bursts
_HALLUCINATION_PHRASES = {
    "thank you",
    "thank you.",
    "thanks for watching",
    "thanks for watching.",
    "you",
    "bye",
    "bye.",
    "...",
}


def _is_hallucinated_or_empty(text: str, avg_logprob: Optional[float], duration_ms: float) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    alnum = re.sub(r"[^A-Za-z0-9]", "", cleaned)
    if len(alnum) < 2:
        return True
    if avg_logprob is not None and avg_logprob <= -1.0:
        return True
    if cleaned.lower() in _HALLUCINATION_PHRASES and duration_ms < 1500.0:
        return True
    return False


class FasterWhisperSTTProvider(BaseSTTProvider):
    """
    Local CPU int8 STT provider powered by faster-whisper (CTranslate2).
    Operates directly on in-memory PCM16 numpy buffers without temporary disk files.
    """

    def __init__(
        self,
        model_size: str = settings.WHISPER_MODEL_SIZE,
        device: str = settings.WHISPER_DEVICE,
        compute_type: str = settings.WHISPER_COMPUTE_TYPE,
        beam_size: int = settings.WHISPER_BEAM_SIZE,
        cpu_threads: Optional[int] = None,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = max(1, int(beam_size))
        self.cpu_threads = cpu_threads or _resolve_cpu_threads()

    def _resolve_model_for_language(self, lang_code: str) -> str:
        if (
            (lang_code == "en" or lang_code.startswith("en-"))
            and self.model_size == settings.WHISPER_MODEL_SIZE
            and settings.WHISPER_ENGLISH_MODEL_SIZE
        ):
            return settings.WHISPER_ENGLISH_MODEL_SIZE
        return self.model_size

    def _transcribe_sync(
        self,
        audio_pcm16: bytes,
        sample_rate: int,
        language: str,
        context_prompt: Optional[str] = None,
    ) -> STTResult:
        start = time.perf_counter()
        if not audio_pcm16 or len(audio_pcm16) < 3200:  # < 100ms at 16kHz PCM16
            return STTResult(
                text="",
                language=language,
                duration_ms=0.0,
                latency_ms=0.0,
                provider="faster-whisper",
            )

        samples_int16 = np.frombuffer(audio_pcm16, dtype=np.int16)
        duration_ms = (len(samples_int16) / float(sample_rate)) * 1000.0
        audio_f32 = samples_int16.astype(np.float32) / 32768.0

        # Resample linearly if caller supplied non-16kHz PCM
        if sample_rate != 16000 and len(audio_f32) > 1:
            target_len = int(len(audio_f32) * (16000.0 / sample_rate))
            x_old = np.linspace(0.0, 1.0, len(audio_f32), endpoint=False)
            x_new = np.linspace(0.0, 1.0, target_len, endpoint=False)
            audio_f32 = np.interp(x_new, x_old, audio_f32).astype(np.float32)

        lang_code = (language or "en").strip().lower() or "en"
        effective_model = self._resolve_model_for_language(lang_code)
        model = _get_or_load_whisper_model(
            effective_model,
            self.device,
            self.compute_type,
            self.cpu_threads,
        )
        transcribe_kwargs = {
            "language": "en" if lang_code.startswith("en") else lang_code,
            "beam_size": self.beam_size,
            "best_of": self.beam_size,
            "temperature": 0.0,
            "vad_filter": False,  # Already segmented by streaming server-side VAD
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.6,
            "log_prob_threshold": -1.0,
        }
        if context_prompt and context_prompt.strip():
            hint = context_prompt.strip()
            transcribe_kwargs["initial_prompt"] = f"Vocabulary: {hint}"
            transcribe_kwargs["hotwords"] = hint

        segments_iter, info = model.transcribe(audio_f32, **transcribe_kwargs)
        segments = list(segments_iter)

        kept_texts = []
        kept_logprobs = []
        kept_no_speech = []
        all_logprobs = []
        all_no_speech = []

        for seg in segments:
            seg_text = (seg.text or "").strip()
            seg_lp = getattr(seg, "avg_logprob", None)
            seg_nsp = getattr(seg, "no_speech_prob", None)
            if seg_lp is not None:
                all_logprobs.append(float(seg_lp))
            if seg_nsp is not None:
                all_no_speech.append(float(seg_nsp))

            if not seg_text:
                continue
            if seg_nsp is not None and seg_nsp >= 0.6:
                continue
            if seg_lp is not None and seg_lp <= -1.0:
                continue

            kept_texts.append(seg_text)
            if seg_lp is not None:
                kept_logprobs.append(float(seg_lp))
            if seg_nsp is not None:
                kept_no_speech.append(float(seg_nsp))

        transcript = " ".join(kept_texts).strip()
        avg_logprob = (
            round(sum(kept_logprobs) / len(kept_logprobs), 4)
            if kept_logprobs
            else (round(sum(all_logprobs) / len(all_logprobs), 4) if all_logprobs else None)
        )
        no_speech_prob = (
            round(sum(kept_no_speech) / len(kept_no_speech), 4)
            if kept_no_speech
            else (round(sum(all_no_speech) / len(all_no_speech), 4) if all_no_speech else None)
        )

        if _is_hallucinated_or_empty(transcript, avg_logprob, duration_ms):
            transcript = ""

        latency_ms = (time.perf_counter() - start) * 1000.0
        detected_lang = getattr(info, "language", lang_code) or lang_code
        return STTResult(
            text=transcript,
            language=detected_lang,
            duration_ms=round(duration_ms, 2),
            latency_ms=round(latency_ms, 2),
            avg_logprob=avg_logprob,
            no_speech_prob=no_speech_prob,
            provider="faster-whisper",
        )

    async def transcribe(
        self,
        audio_pcm16: bytes,
        sample_rate: int = 16000,
        language: str = "en",
        context_prompt: Optional[str] = None,
    ) -> STTResult:
        try:
            return await asyncio.to_thread(
                self._transcribe_sync,
                audio_pcm16,
                sample_rate,
                language,
                context_prompt,
            )
        except Exception as exc:
            logger.error(f"faster-whisper transcription failed: {exc}")
            raise STTProviderError(f"STT transcription failed: {exc}") from exc
