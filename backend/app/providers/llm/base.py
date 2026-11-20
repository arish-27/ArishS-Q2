from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Dict, Any, Optional

class LLMProviderError(Exception):
    """Base exception for LLM provider errors."""
    pass

class LLMAuthenticationError(LLMProviderError):
    """Raised when provider API key is missing, invalid, or unauthorized."""
    pass

class LLMRateLimitError(LLMProviderError):
    """Raised when provider rate limit / quota is exceeded."""
    pass

class LLMTimeoutError(LLMProviderError):
    """Raised when provider request times out."""
    pass

class BaseLLMProvider(ABC):
    """
    Abstract interface for LLM providers (Gemini, OpenAI).
    Enforces normalized streaming token generation and prompt engineering.
    """

    def __init__(self, api_key: str):
        if not api_key or not api_key.strip():
            raise LLMAuthenticationError("API key is required to initialize LLM provider.")
        self.api_key = api_key.strip()

    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.7,
        model: str = ""
    ) -> AsyncIterator[str]:
        """
        Streams generated text tokens one by one as they arrive from the provider.
        messages format: [{'role': 'user'|'assistant'|'system', 'content': str}]
        """
        yield ""  # pragma: no cover

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.7,
        model: str = ""
    ) -> str:
        """Accumulates all streamed tokens and returns full text string."""
        tokens = []
        async for token in self.generate_stream(messages, system_prompt, temperature, model):
            tokens.append(token)
        return "".join(tokens)
