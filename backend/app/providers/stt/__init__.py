from typing import Optional
from app.core.config import settings
from app.providers.stt.base import BaseSTTProvider, STTProviderError, STTResult
from app.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider
from app.providers.stt.gemini_provider import GeminiSTTProvider


def get_stt_provider(
    provider_name: str = settings.DEFAULT_STT_PROVIDER,
    api_key: Optional[str] = None,
) -> BaseSTTProvider:
    """Factory returning configured Speech-to-Text provider."""
    prov = (provider_name or settings.DEFAULT_STT_PROVIDER).lower().strip()
    if prov in ("gemini", "gemini-stt", "gemini-cloud"):
        return GeminiSTTProvider(api_key=api_key)
    if prov in ("faster-whisper", "whisper", "local"):
        return FasterWhisperSTTProvider()
    raise STTProviderError(
        f"Unsupported STT provider '{provider_name}'. Supported: gemini, faster-whisper"
    )


__all__ = [
    "BaseSTTProvider",
    "STTProviderError",
    "STTResult",
    "FasterWhisperSTTProvider",
    "GeminiSTTProvider",
    "get_stt_provider",
]
