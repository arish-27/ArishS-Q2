from app.providers.llm.base import (
    BaseLLMProvider,
    LLMProviderError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.providers.llm.gemini_provider import GeminiProvider
from app.providers.llm.openai_provider import OpenAIProvider

def get_llm_provider(provider_name: str, api_key: str) -> BaseLLMProvider:
    """
    Factory to instantiate LLM provider with dynamic in-memory decrypted API key.
    """
    prov = (provider_name or "").lower().strip()
    if prov in ("gemini", "google"):
        return GeminiProvider(api_key=api_key)
    elif prov in ("openai", "gpt"):
        return OpenAIProvider(api_key=api_key)
    else:
        raise LLMProviderError(f"Unsupported LLM provider '{provider_name}'. Supported: gemini, openai")

__all__ = [
    "BaseLLMProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "get_llm_provider",
    "LLMProviderError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMTimeoutError",
]
