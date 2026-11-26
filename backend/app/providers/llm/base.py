from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Dict, Any, Optional


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolTurnResult:
    text: str = ""
    tool_calls: List[ToolCallRequest] = field(default_factory=list)

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

class LLMServiceUnavailableError(LLMProviderError):
    """Raised when provider returns transient 502/503/504 service unavailable."""
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

    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: str = "",
        temperature: float = 0.7,
        model: str = "",
    ) -> ToolTurnResult:
        """
        Single non-streaming turn with function/tool declarations.
        Subclasses override with native Gemini/OpenAI tool calling; default falls back to text.
        """
        simple_msgs = [
            {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
            for m in messages
            if m.get("content")
        ]
        txt = await self.generate(simple_msgs, system_prompt=system_prompt, temperature=temperature, model=model)
        return ToolTurnResult(text=txt, tool_calls=[])
