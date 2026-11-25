import asyncio
import threading
import time
from typing import Dict, Tuple
import numpy as np
from app.core.config import settings
from app.core.logger import logger
from app.providers.stt.base import BaseSTTProvider, STTProviderError, STTResult

_MODEL_CACHE: Dict[Tuple[str, str, str], object] = {}
_MODEL_LOCK = threading.Lock()


def _get_or_load_whisper_model(model_size: str, device: str, compute_type: str):
    """Thread-safe lazy singleton loader for faster-whisper CTranslate2 model."""
    key = (model_size, device, compute_type)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    with _MODEL_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        from faster_whisper import WhisperModel

        logger.info(
            f"Loading faster-whisper model size={model_size} device={device} compute_type={compute_type}"
        )
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _MODEL_CACHE[key] = model
        return model


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
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def _transcribe_sync(self, audio_pcm16: bytes, sample_rate: int, language: str) -> STTResult:
        start = time.perf_counter()
        if not audio_pcm16 or len(audio_pcm16) < 3200:  # < 100ms at 16kHz PCM16
            return STTResult(text="", language=language, duration_ms=0.0, latency_ms=0.0)

        samples_int16 = np.frombuffer(audio_pcm16, dtype=np.int16)
        duration_ms = (len(samples_int16) / float(sample_rate)) * 1000.0
        audio_f32 = samples_int16.astype(np.float32) / 32768.0

        # Resample linearly if caller supplied non-16kHz PCM
        if sample_rate != 16000 and len(audio_f32) > 1:
            target_len = int(len(audio_f32) * (16000.0 / sample_rate))
            x_old = np.linspace(0.0, 1.0, len(audio_f32), endpoint=False)
            x_new = np.linspace(0.0, 1.0, target_len, endpoint=False)
            audio_f32 = np.interp(x_new, x_old, audio_f32).astype(np.float32)

        model = _get_or_load_whisper_model(self.model_size, self.device, self.compute_type)
        segments, info = model.transcribe(
            audio_f32,
            language=language or "en",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=False,  # Already segmented by streaming server-side VAD
            condition_on_previous_text=False,
        )
        transcript = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
        latency_ms = (time.perf_counter() - start) * 1000.0
        detected_lang = getattr(info, "language", language) or language
        return STTResult(
            text=transcript,
            language=detected_lang,
            duration_ms=round(duration_ms, 2),
            latency_ms=round(latency_ms, 2),
        )

    async def transcribe(
        self,
        audio_pcm16: bytes,
        sample_rate: int = 16000,
        language: str = "en",
    ) -> STTResult:
        try:
            return await asyncio.to_thread(self._transcribe_sync, audio_pcm16, sample_rate, language)
        except Exception as exc:
            logger.error(f"faster-whisper transcription failed: {exc}")
            raise STTProviderError(f"STT transcription failed: {exc}") from exc
