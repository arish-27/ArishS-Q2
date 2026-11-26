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
    prob: float = 0.0
    avg_prob: float = 0.0
    noise_floor_rms: float = 0.0
    end_reason: str = ""


class StreamingVAD:
    """
    Stateful streaming Voice Activity Detector with hysteresis, adaptive RMS energy gate,
    confirmed speech-onset debounce, and hard utterance duration cap.

    Supports:
    - 'silero-onnx': Silero VAD v6 via onnxruntime (bundled with faster-whisper, zero torch).
    - 'webrtcvad': Lightweight Google WebRTC VAD over 30ms frames.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold_ms: int = settings.VAD_SILENCE_THRESHOLD_MS,
        speech_threshold: Optional[float] = None,
        speech_start_threshold: float = settings.VAD_SPEECH_START_THRESHOLD,
        speech_end_threshold: float = settings.VAD_SPEECH_END_THRESHOLD,
        energy_multiplier: float = settings.VAD_ENERGY_MULTIPLIER,
        min_speech_ms: int = settings.VAD_MIN_SPEECH_MS,
        backend: str = "auto",
        max_utterance_seconds: int = settings.VAD_MAX_UTTERANCE_S,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold_ms = silence_threshold_ms
        # Backwards-compatible alias if caller passes speech_threshold directly
        self.speech_start_threshold = (
            float(speech_threshold) if speech_threshold is not None else float(speech_start_threshold)
        )
        self.speech_end_threshold = min(
            float(speech_end_threshold),
            self.speech_start_threshold,
        )
        self.energy_multiplier = max(1.0, float(energy_multiplier))
        self.min_speech_ms = min_speech_ms
        self.max_utterance_seconds = max(1, int(max_utterance_seconds))
        self.max_utterance_bytes = int(self.max_utterance_seconds * sample_rate * 2)

        self._pcm_buffer = bytearray()
        self._pre_speech_ring: Deque[bytes] = deque(maxlen=10)  # ~320ms pre-roll
        self._pending_frames: List[bytes] = []
        self._pending_probs: List[float] = []
        self._pending_ms: float = 0.0
        self._pending_miss_count: int = 0

        self._speech_buffer = bytearray()
        self._utterance_probs: List[float] = []
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._noise_floor_rms: float = 0.002
        self.last_prob: float = 0.0

        self.backend_name = self._init_backend(backend)
        self.frame_samples = 512 if self.backend_name == "silero-onnx" else 480
        self.frame_bytes = self.frame_samples * 2
        self.frame_ms = (self.frame_samples / float(self.sample_rate)) * 1000.0

        # Silero v6 ONNX streaming states
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    @property
    def speech_threshold(self) -> float:
        return self.speech_start_threshold

    @property
    def noise_floor_rms(self) -> float:
        return self._noise_floor_rms

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
        speech_start_threshold: Optional[float] = None,
        speech_end_threshold: Optional[float] = None,
        energy_multiplier: Optional[float] = None,
        min_speech_ms: Optional[int] = None,
    ) -> None:
        if silence_threshold_ms is not None:
            self.silence_threshold_ms = max(200, min(5000, int(silence_threshold_ms)))
        start_val = speech_start_threshold if speech_start_threshold is not None else speech_threshold
        if start_val is not None:
            self.speech_start_threshold = max(0.1, min(0.95, float(start_val)))
        if speech_end_threshold is not None:
            self.speech_end_threshold = max(0.05, min(self.speech_start_threshold, float(speech_end_threshold)))
        if energy_multiplier is not None:
            self.energy_multiplier = max(1.0, min(10.0, float(energy_multiplier)))
        if min_speech_ms is not None:
            self.min_speech_ms = max(50, min(2000, int(min_speech_ms)))

    def reset(self) -> None:
        self._pcm_buffer.clear()
        self._pre_speech_ring.clear()
        self._pending_frames.clear()
        self._pending_probs.clear()
        self._pending_ms = 0.0
        self._pending_miss_count = 0
        self._speech_buffer.clear()
        self._utterance_probs.clear()
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self.last_prob = 0.0
        self._h.fill(0.0)
        self._c.fill(0.0)
        self._context.fill(0.0)

    @property
    def confirmed_speech_ms(self) -> float:
        """Continuous voiced duration (ms) in the current uncompleted speech segment."""
        if self._in_speech:
            return self._speech_ms
        return self._pending_ms

    def _frame_rms(self, frame_bytes: bytes) -> float:
        samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples * samples)))

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
        Accepts arbitrary-length 16kHz mono PCM16 bytes, processes whole VAD frames
        with hysteresis + adaptive energy gate, and returns speech_start / utterance events.
        """
        if not pcm16_bytes:
            return []

        self._pcm_buffer.extend(pcm16_bytes)
        results: List[VADResult] = []

        while len(self._pcm_buffer) >= self.frame_bytes:
            frame = bytes(self._pcm_buffer[: self.frame_bytes])
            del self._pcm_buffer[: self.frame_bytes]

            rms = self._frame_rms(frame)
            prob = self._score_frame(frame)
            self.last_prob = prob
            energy_ok = rms >= (self._noise_floor_rms * self.energy_multiplier)

            if not self._in_speech:
                is_start_speech = energy_ok and (prob >= self.speech_start_threshold)
                if is_start_speech:
                    self._pending_miss_count = 0
                    self._pending_frames.append(frame)
                    self._pending_probs.append(prob)
                    self._pending_ms += self.frame_ms

                    if self._pending_ms >= self.min_speech_ms:
                        self._in_speech = True
                        self._speech_ms = self._pending_ms
                        self._silence_ms = 0.0
                        self._speech_buffer.clear()
                        for pre_frame in self._pre_speech_ring:
                            self._speech_buffer.extend(pre_frame)
                        self._pre_speech_ring.clear()
                        for pend in self._pending_frames:
                            self._speech_buffer.extend(pend)
                        self._utterance_probs = list(self._pending_probs)
                        self._pending_frames.clear()
                        self._pending_probs.clear()
                        self._pending_ms = 0.0
                        self._pending_miss_count = 0
                        results.append(
                            VADResult(
                                speech_start=True,
                                is_speech=True,
                                prob=prob,
                                noise_floor_rms=self._noise_floor_rms,
                            )
                        )
                else:
                    if self._pending_frames:
                        self._pending_miss_count += 1
                        if self._pending_miss_count >= 2 or (prob < self.speech_end_threshold and not energy_ok and self._pending_miss_count >= 2):
                            for pend in self._pending_frames:
                                self._pre_speech_ring.append(pend)
                            self._pending_frames.clear()
                            self._pending_probs.clear()
                            self._pending_ms = 0.0
                            self._pending_miss_count = 0
                        else:
                            self._pending_frames.append(frame)
                            self._pending_probs.append(prob)

                    # Update adaptive noise floor only during confirmed non-speech
                    if not self._pending_frames:
                        if rms > 0.0 and prob < self.speech_end_threshold:
                            self._noise_floor_rms = min(
                                0.08,
                                max(0.001, 0.95 * self._noise_floor_rms + 0.05 * rms),
                            )
                        self._pre_speech_ring.append(frame)
            else:
                self._speech_buffer.extend(frame)
                self._utterance_probs.append(prob)

                # Reset silence counter ONLY when probability >= start threshold & energy gate passes
                if energy_ok and prob >= self.speech_start_threshold:
                    self._speech_ms += self.frame_ms
                    self._silence_ms = 0.0
                else:
                    self._silence_ms += self.frame_ms

                hit_silence = self._silence_ms >= self.silence_threshold_ms
                hit_cap = len(self._speech_buffer) >= self.max_utterance_bytes

                if hit_silence or hit_cap:
                    utterance = bytes(self._speech_buffer)
                    avg_prob = (
                        sum(self._utterance_probs) / len(self._utterance_probs)
                        if self._utterance_probs
                        else 0.0
                    )
                    end_reason = "max_cap" if hit_cap and not hit_silence else "silence"
                    self._in_speech = False
                    self._speech_buffer.clear()
                    self._utterance_probs.clear()
                    self._silence_ms = 0.0
                    self._speech_ms = 0.0

                    total_dur_ms = (len(utterance) / 2.0 / self.sample_rate) * 1000.0
                    logger.info(
                        f"VAD utterance complete duration_ms={total_dur_ms:.1f} "
                        f"avg_prob={avg_prob:.3f} noise_floor={self._noise_floor_rms:.5f} "
                        f"end_reason={end_reason}"
                    )
                    results.append(
                        VADResult(
                            speech_start=False,
                            utterance_pcm16=utterance,
                            duration_ms=total_dur_ms,
                            is_speech=False,
                            prob=prob,
                            avg_prob=round(avg_prob, 4),
                            noise_floor_rms=round(self._noise_floor_rms, 5),
                            end_reason=end_reason,
                        )
                    )

        return results

    def flush(self) -> Optional[bytes]:
        """Flushes any buffered speech when user manually ends utterance or stops mic."""
        if not self._in_speech or not self._speech_buffer:
            self.reset()
            return None
        utterance = bytes(self._speech_buffer)
        total_dur_ms = (len(utterance) / 2.0 / self.sample_rate) * 1000.0
        avg_prob = (
            sum(self._utterance_probs) / len(self._utterance_probs)
            if self._utterance_probs
            else 0.0
        )
        valid_speech = self._speech_ms >= self.min_speech_ms
        if valid_speech:
            logger.info(
                f"VAD utterance complete duration_ms={total_dur_ms:.1f} "
                f"avg_prob={avg_prob:.3f} noise_floor={self._noise_floor_rms:.5f} "
                f"end_reason=manual"
            )
        self.reset()
        return utterance if valid_speech else None
