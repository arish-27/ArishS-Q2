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

class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI streaming LLM provider.
    Uses official OpenAI chat completions SSE streaming endpoint.
    """

    DEFAULT_MODEL = "gpt-6-luna"
    BASE_URL = "https://api.openai.com/v1/chat/completions"

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.7,
        model: str = ""
    ) -> AsyncIterator[str]:
        target_model = model or self.DEFAULT_MODEL
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Build message history with system prompt at index 0
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        payload = {
            "model": target_model,
            "messages": formatted_messages,
            "stream": True,
            "temperature": max(0.0, min(2.0, temperature))
        }

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", self.BASE_URL, headers=headers, json=payload) as response:
                    if response.status_code == 401:
                        error_body = await response.aread()
                        logger.error(f"OpenAI authentication failed: {error_body.decode('utf-8', errors='ignore')}")
                        raise LLMAuthenticationError("Invalid or unauthorized OpenAI API key.")

                    if response.status_code == 429:
                        error_body = await response.aread()
                        logger.warning(f"OpenAI rate limit exceeded: {error_body.decode('utf-8', errors='ignore')}")
                        raise LLMRateLimitError("OpenAI API rate limit or quota exceeded.")

                    if response.status_code != 200:
                        error_body = await response.aread()
                        logger.error(f"OpenAI error {response.status_code}: {error_body.decode('utf-8', errors='ignore')}")
                        raise LLMProviderError(f"OpenAI API returned HTTP {response.status_code}")

                    # Parse SSE lines
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    yield token
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException as e:
            logger.error(f"OpenAI request timed out: {e}")
            raise LLMTimeoutError("OpenAI streaming request timed out.") from e
        except (LLMProviderError, LLMAuthenticationError, LLMRateLimitError):
            raise
        except Exception as e:
            logger.error(f"Unexpected OpenAI provider error: {e}")
            raise LLMProviderError(f"OpenAI error: {str(e)}") from e
