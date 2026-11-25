import json
import httpx
from typing import AsyncIterator, List, Dict
from app.providers.llm.base import (
    BaseLLMProvider,
    LLMProviderError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError
)
from app.core.logger import logger

class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini streaming LLM provider.
    Uses official Gemini REST SSE streamGenerateContent endpoint.
    """

    DEFAULT_MODEL = "gemini-4-hydrogen"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.7,
        model: str = ""
    ) -> AsyncIterator[str]:
        target_model = model or self.DEFAULT_MODEL
        url = f"{self.BASE_URL}/{target_model}:streamGenerateContent?alt=sse&key={self.api_key}"

        # Construct Gemini API contents payload
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })

        payload: Dict[str, any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": max(0.0, min(2.0, temperature)),
            }
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}]
            }

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code in (401, 403):
                        error_body = await response.aread()
                        logger.error(f"Gemini authentication failed: {error_body.decode('utf-8', errors='ignore')}")
                        raise LLMAuthenticationError("Invalid or unauthorized Gemini API key.")

                    if response.status_code == 429:
                        error_body = await response.aread()
                        logger.warning(f"Gemini rate limit exceeded: {error_body.decode('utf-8', errors='ignore')}")
                        raise LLMRateLimitError("Gemini API quota or rate limit exceeded.")

                    if response.status_code != 200:
                        error_body = await response.aread()
                        logger.error(f"Gemini error {response.status_code}: {error_body.decode('utf-8', errors='ignore')}")
                        raise LLMProviderError(f"Gemini API returned HTTP {response.status_code}")

                    # Parse SSE stream
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            chunk = json.loads(data_str)
                            candidates = chunk.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    text = part.get("text", "")
                                    if text:
                                        yield text
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException as e:
            logger.error(f"Gemini request timed out: {e}")
            raise LLMTimeoutError("Gemini streaming request timed out.") from e
        except (LLMProviderError, LLMAuthenticationError, LLMRateLimitError):
            raise
        except Exception as e:
            logger.error(f"Unexpected Gemini provider error: {e}")
            raise LLMProviderError(f"Gemini error: {str(e)}") from e
