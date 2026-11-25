import math
from typing import List
import httpx
from app.core.config import settings
from app.core.logger import logger
from app.providers.embeddings.base import BaseEmbeddingProvider, EmbeddingProviderError


def l2_normalize(vector: List[float]) -> List[float]:
    """Normalizes vector to unit L2 norm (required for MRL truncated gemini-embedding-001)."""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """
    Google Gemini embedding provider using gemini-embedding-001 with outputDimensionality=768.
    Replaces retired text-embedding-004 while preserving pgvector(768) compatibility.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model: str = settings.RAG_EMBEDDING_MODEL,
        dimensions: int = settings.RAG_EMBEDDING_DIM,
    ):
        super().__init__(api_key=api_key, model=model, dimensions=dimensions)

    async def embed_text(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
        if not text or not text.strip():
            raise EmbeddingProviderError("Cannot embed empty text.")

        url = f"{self.BASE_URL}/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": self.dimensions,
            "taskType": task_type,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code != 200:
            body = resp.text[:300]
            logger.error(f"Gemini embedding error {resp.status_code}: {body}")
            raise EmbeddingProviderError(f"Gemini embedding API returned HTTP {resp.status_code}: {body}")

        data = resp.json()
        values = data.get("embedding", {}).get("values", [])
        if len(values) != self.dimensions:
            raise EmbeddingProviderError(
                f"Expected {self.dimensions}-dim embedding from {self.model}, got {len(values)}"
            )

        # Normalize when truncated below native 3072 dims per Gemini MRL docs
        return l2_normalize(values) if self.dimensions != 3072 else values
