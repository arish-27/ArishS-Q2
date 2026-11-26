from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional
import numpy as np
from app.core.config import settings
from app.core.logger import logger


@dataclass
class VADResult:
    speech_start: bool = False
    utterance_pcm16: Optional[bytes] = None
    duration_ms: float = 0.0
    is_speech: bool = False


class StreamingVAD:
    """
    Stateful streaming Voice Activity Detector supporting:
    - 'silero-onnx': Silero VAD v6 via onnxruntime (bundled with faster-whisper, zero torch).
    - 'webrtcvad': Lightweight Google WebRTC VAD over 30ms frames.

    Detects speech onset, buffers pre-speech ring context (~300ms), and emits complete
    PCM16 utterances once trailing silence exceeds `silence_threshold_ms`.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold_ms: int = settings.VAD_SILENCE_THRESHOLD_MS,
        speech_threshold: float = settings.VAD_SPEECH_THRESHOLD,
        min_speech_ms: int = settings.VAD_MIN_SPEECH_MS,
        backend: str = "auto",
        max_utterance_seconds: int = 30,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold_ms = silence_threshold_ms
        self.speech_threshold = speech_threshold
        self.min_speech_ms = min_speech_ms
        self.max_utterance_bytes = int(max_utterance_seconds * sample_rate * 2)

        self._pcm_buffer = bytearray()
        self._pre_speech_ring: Deque[bytes] = deque(maxlen=10)  # ~320ms pre-roll
        self._speech_buffer = bytearray()
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0

        self.backend_name = self._init_backend(backend)
        self.frame_samples = 512 if self.backend_name == "silero-onnx" else 480
        self.frame_bytes = self.frame_samples * 2
        self.frame_ms = (self.frame_samples / float(self.sample_rate)) * 1000.0

        # Silero v6 ONNX streaming states
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def _init_backend(self, requested: str) -> str:
        req = (requested or "auto").lower().strip()
        if req in ("auto", "silero", "silero-onnx"):
            try:
                from faster_whisper.vad import get_vad_model
                self._silero_model = get_vad_model()
                return "silero-onnx"
            except Exception as exc:
                logger.warning(f"Silero VAD ONNX unavailable ({exc}); falling back to webrtcvad.")
                if req in ("silero", "silero-onnx"):
                    raise

        import webrtcvad
        self._webrtc_vad = webrtcvad.Vad(2)
        return "webrtcvad"

    def update_config(
        self,
        silence_threshold_ms: Optional[int] = None,
        speech_threshold: Optional[float] = None,
        min_speech_ms: Optional[int] = None,
    ) -> None:
        if silence_threshold_ms is not None:
            self.silence_threshold_ms = max(200, min(5000, int(silence_threshold_ms)))
        if speech_threshold is not None:
            self.speech_threshold = max(0.05, min(0.95, float(speech_threshold)))
        if min_speech_ms is not None:
            self.min_speech_ms = max(50, min(2000, int(min_speech_ms)))

    def reset(self) -> None:
        self._pcm_buffer.clear()
        self._pre_speech_ring.clear()
        self._speech_buffer.clear()
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._h.fill(0.0)
        self._c.fill(0.0)
        self._context.fill(0.0)

    @property
    def confirmed_speech_ms(self) -> float:
        """Continuous voiced duration (ms) in the current uncompleted speech segment."""
        return self._speech_ms if self._in_speech else 0.0

    def _score_frame(self, frame_bytes: bytes) -> float:
        if self.backend_name == "silero-onnx":
            audio_f32 = (np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0).reshape(1, -1)
            inp = np.concatenate([self._context, audio_f32], axis=1)
            out, self._h, self._c = self._silero_model.session.run(
                None,
                {"input": inp, "h": self._h, "c": self._c},
            )
            self._context = audio_f32[:, -64:]
            return float(out.squeeze())
        else:
            is_voiced = self._webrtc_vad.is_speech(frame_bytes, self.sample_rate)
            return 1.0 if is_voiced else 0.0

    def process_chunk(self, pcm16_bytes: bytes) -> List[VADResult]:
        """
        Accepts arbitrary-length 16kHz mono PCM16 bytes, processes whole VAD frames,
        and returns any speech_start / utterance_complete events.
        """
        if not pcm16_bytes:
            return []

        self._pcm_buffer.extend(pcm16_bytes)
        results: List[VADResult] = []

        while len(self._pcm_buffer) >= self.frame_bytes:
            frame = bytes(self._pcm_buffer[: self.frame_bytes])
            del self._pcm_buffer[: self.frame_bytes]

            prob = self._score_frame(frame)
            is_speech = prob >= self.speech_threshold

            if is_speech:
                if not self._in_speech:
                    self._in_speech = True
                    self._speech_ms = self.frame_ms
                    self._silence_ms = 0.0
                    self._speech_buffer.clear()
                    for pre_frame in self._pre_speech_ring:
                        self._speech_buffer.extend(pre_frame)
                    self._pre_speech_ring.clear()
                    self._speech_buffer.extend(frame)
                    results.append(VADResult(speech_start=True, is_speech=True))
                else:
                    self._speech_ms += self.frame_ms
                    self._silence_ms = 0.0
                    self._speech_buffer.extend(frame)
            else:
                if self._in_speech:
                    self._silence_ms += self.frame_ms
                    self._speech_buffer.extend(frame)

                    if (
                        self._silence_ms >= self.silence_threshold_ms
                        or len(self._speech_buffer) >= self.max_utterance_bytes
                    ):
                        utterance = bytes(self._speech_buffer)
                        valid_duration = self._speech_ms
                        self._in_speech = False
                        self._speech_buffer.clear()
                        self._silence_ms = 0.0
                        self._speech_ms = 0.0

                        if valid_duration >= self.min_speech_ms:
                            total_dur_ms = (len(utterance) / 2.0 / self.sample_rate) * 1000.0
                            results.append(
                                VADResult(
                                    speech_start=False,
                                    utterance_pcm16=utterance,
                                    duration_ms=total_dur_ms,
                                    is_speech=False,
                                )
                            )
                else:
                    self._pre_speech_ring.append(frame)

            # Force segment break if continuous speech hits safety buffer ceiling
            if self._in_speech and len(self._speech_buffer) >= self.max_utterance_bytes:
                utterance = bytes(self._speech_buffer)
                self._in_speech = False
                self._speech_buffer.clear()
                self._silence_ms = 0.0
                self._speech_ms = 0.0
                total_dur_ms = (len(utterance) / 2.0 / self.sample_rate) * 1000.0
                results.append(
                    VADResult(
                        utterance_pcm16=utterance,
                        duration_ms=total_dur_ms,
                        is_speech=False,
                    )
                )

        return results

    def flush(self) -> Optional[bytes]:
        """Flushes any buffered speech when user manually ends utterance or stops mic."""
        if not self._in_speech or not self._speech_buffer:
            self.reset()
            return None
        utterance = bytes(self._speech_buffer)
        valid_speech = self._speech_ms >= self.min_speech_ms
        self.reset()
        return utterance if valid_speech else None
