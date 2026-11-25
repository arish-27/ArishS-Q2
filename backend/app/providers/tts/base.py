import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class TTSProviderError(Exception):
    """Base exception for Text-to-Speech provider errors."""
    pass


class BaseTTSProvider(ABC):
    """Abstract interface for sentence-level streaming Text-to-Speech providers."""

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        voice: str = "",
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[bytes]:
        """Yields synthesized audio byte chunks as they become available."""
        yield b""  # pragma: no cover
