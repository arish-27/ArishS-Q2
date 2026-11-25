from abc import ABC, abstractmethod
from typing import List


class EmbeddingProviderError(Exception):
    """Base error for embedding provider failures."""
    pass


class BaseEmbeddingProvider(ABC):
    """Abstract interface for text embedding models producing fixed-dimension vectors."""

    def __init__(self, api_key: str, model: str, dimensions: int = 768):
        if not api_key or not api_key.strip():
            raise EmbeddingProviderError("API key is required for embedding generation.")
        self.api_key = api_key.strip()
        self.model = model
        self.dimensions = dimensions

    @abstractmethod
    async def embed_text(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
        """Generates normalized embedding vector of length self.dimensions."""
        raise NotImplementedError
