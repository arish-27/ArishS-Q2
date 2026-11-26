import asyncio
import json
import time
import httpx
from typing import AsyncIterator, List, Dict, Optional, Any
from app.providers.llm.base import (
    BaseLLMProvider,
    ToolCallRequest,
    ToolTurnResult,
    LLMProviderError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError
)
from app.core.logger import logger

_GEMINI_HTTP_CLIENTS: Dict[int, httpx.AsyncClient] = {}


def get_gemini_http_client() -> httpx.AsyncClient:
    """Returns a persistent keep-alive httpx.AsyncClient scoped to the active event loop."""
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    client = _GEMINI_HTTP_CLIENTS.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=60.0,
            ),
        )
        _GEMINI_HTTP_CLIENTS[loop_id] = client
    return client


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini streaming LLM provider.
    Uses official Gemini REST SSE streamGenerateContent endpoint over a persistent HTTP client.
    """

    DEFAULT_MODEL = "gemini-3.5-flash-lite"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        thinking_level: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ):
        super().__init__(api_key)
        self.thinking_level = thinking_level
        self.max_output_tokens = max_output_tokens

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

        generation_config: Dict[str, any] = {
            "temperature": max(0.0, min(2.0, temperature)),
        }
        if self.max_output_tokens is not None:
            generation_config["maxOutputTokens"] = self.max_output_tokens
        if self.thinking_level:
            generation_config["thinkingConfig"] = {
                "thinkingLevel": self.thinking_level
            }

        payload: Dict[str, any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}]
            }

        logger.info(f"Gemini request model={target_model} generationConfig={generation_config}")
        client = get_gemini_http_client()
        req_start = time.perf_counter()
        first_byte_ms: Optional[float] = None
        first_token_ms: Optional[float] = None

        try:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code in (401, 403):
                    error_body = await response.aread()
                    logger.error(f"Gemini authentication failed: {error_body.decode('utf-8', errors='ignore')}")
                    raise LLMAuthenticationError("Invalid or unauthorized Gemini API key.")

                if response.status_code == 429:
                    error_body = await response.aread()
                    logger.warning(f"Gemini rate limit exceeded: {error_body.decode('utf-8', errors='ignore')}")
                    raise LLMRateLimitError("Gemini API quota or rate limit exceeded.")

                if response.status_code in (502, 503, 504):
                    error_body = await response.aread()
                    logger.warning(
                        f"Gemini service unavailable ({response.status_code}): "
                        f"{error_body.decode('utf-8', errors='ignore')}"
                    )
                    raise LLMServiceUnavailableError(
                        f"Gemini API temporarily unavailable (HTTP {response.status_code})."
                    )

                if response.status_code != 200:
                    error_body = await response.aread()
                    logger.error(f"Gemini error {response.status_code}: {error_body.decode('utf-8', errors='ignore')}")
                    raise LLMProviderError(f"Gemini API returned HTTP {response.status_code}")

                # Parse SSE stream
                async for line in response.aiter_lines():
                    if first_byte_ms is None:
                        first_byte_ms = (time.perf_counter() - req_start) * 1000.0
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
                                    if first_token_ms is None:
                                        first_token_ms = (time.perf_counter() - req_start) * 1000.0
                                    yield text
                    except json.JSONDecodeError:
                        continue

            total_ms = (time.perf_counter() - req_start) * 1000.0
            logger.info(
                f"GeminiStreamSplit model={target_model} "
                f"first_byte_ms={round(first_byte_ms or total_ms, 1)} "
                f"first_token_ms={round(first_token_ms or total_ms, 1)} "
                f"total_ms={round(total_ms, 1)}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Gemini request timed out: {e}")
            raise LLMTimeoutError("Gemini streaming request timed out.") from e
        except (LLMProviderError, LLMAuthenticationError, LLMRateLimitError, LLMServiceUnavailableError):
            raise
        except Exception as e:
            logger.error(f"Unexpected Gemini provider error: {e}")
            raise LLMProviderError(f"Gemini error: {str(e)}") from e

    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: str = "",
        temperature: float = 0.7,
        model: str = "",
    ) -> ToolTurnResult:
        """Executes a single Gemini generateContent turn with functionDeclarations."""
        target_model = model or self.DEFAULT_MODEL
        url = f"{self.BASE_URL}/{target_model}:generateContent?key={self.api_key}"

        contents: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.get("name", "tool"),
                            "response": {"result": msg.get("content", {})},
                        }
                    }],
                })
            elif role == "assistant" and msg.get("tool_calls"):
                parts = []
                if msg.get("content"):
                    parts.append({"text": str(msg["content"])})
                for tc in msg["tool_calls"]:
                    parts.append({
                        "functionCall": {
                            "name": tc["name"],
                            "args": tc.get("arguments", {}),
                        }
                    })
                contents.append({"role": "model", "parts": parts})
            else:
                gem_role = "model" if role == "assistant" else "user"
                contents.append({"role": gem_role, "parts": [{"text": str(msg.get("content", ""))}]})

        generation_config: Dict[str, Any] = {
            "temperature": max(0.0, min(2.0, temperature)),
        }
        if self.max_output_tokens is not None:
            generation_config["maxOutputTokens"] = self.max_output_tokens
        if self.thinking_level:
            generation_config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
        if tools:
            payload["tools"] = [{
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    }
                    for t in tools
                ]
            }]

        client = get_gemini_http_client()
        try:
            resp = await client.post(url, json=payload)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError("Gemini tool-calling request timed out.") from e

        if resp.status_code in (401, 403):
            raise LLMAuthenticationError("Invalid or unauthorized Gemini API key.")
        if resp.status_code == 429:
            raise LLMRateLimitError("Gemini API quota or rate limit exceeded.")
        if resp.status_code in (502, 503, 504):
            raise LLMServiceUnavailableError(f"Gemini API temporarily unavailable (HTTP {resp.status_code}).")
        if resp.status_code != 200:
            raise LLMProviderError(f"Gemini API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ToolTurnResult(text="", tool_calls=[])

        parts = candidates[0].get("content", {}).get("parts", [])
        texts: List[str] = []
        calls: List[ToolCallRequest] = []
        for idx, part in enumerate(parts):
            if "text" in part and part["text"]:
                texts.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                calls.append(
                    ToolCallRequest(
                        id=f"call_{idx}_{fc.get('name', 'tool')}",
                        name=fc.get("name", ""),
                        arguments=fc.get("args", {}) or {},
                    )
                )
        return ToolTurnResult(text="".join(texts).strip(), tool_calls=calls)
