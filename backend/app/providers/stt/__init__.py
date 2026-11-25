from app.providers.stt.base import BaseSTTProvider, STTProviderError, STTResult
from app.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider


def get_stt_provider(provider_name: str = "faster-whisper") -> BaseSTTProvider:
    """Factory returning configured Speech-to-Text provider."""
    prov = (provider_name or "faster-whisper").lower().strip()
    if prov in ("faster-whisper", "whisper", "local"):
        return FasterWhisperSTTProvider()
    raise STTProviderError(f"Unsupported STT provider '{provider_name}'. Supported: faster-whisper")


__all__ = [
    "BaseSTTProvider",
    "STTProviderError",
    "STTResult",
    "FasterWhisperSTTProvider",
    "get_stt_provider",
]
