from abc import ABC, abstractmethod
from dataclasses import dataclass


class STTProviderError(Exception):
    """Base exception for STT provider errors."""
    pass


@dataclass
class STTResult:
    text: str
    language: str
    duration_ms: float
    latency_ms: float


class BaseSTTProvider(ABC):
    """Abstract interface for Speech-to-Text providers."""

    @abstractmethod
    async def transcribe(
        self,
        audio_pcm16: bytes,
        sample_rate: int = 16000,
        language: str = "en",
    ) -> STTResult:
        """Transcribes raw 16-bit signed mono PCM audio bytes into text."""
        raise NotImplementedError
