from app.providers.tts.base import BaseTTSProvider, TTSProviderError
from app.providers.tts.edge_tts_provider import EdgeTTSProvider


def get_tts_provider(provider_name: str = "edge-tts") -> BaseTTSProvider:
    """Factory returning configured Text-to-Speech provider."""
    prov = (provider_name or "edge-tts").lower().strip()
    if prov in ("edge-tts", "edge"):
        return EdgeTTSProvider()
    raise TTSProviderError(f"Unsupported TTS provider '{provider_name}'. Supported: edge-tts")


__all__ = [
    "BaseTTSProvider",
    "TTSProviderError",
    "EdgeTTSProvider",
    "get_tts_provider",
]
