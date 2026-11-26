"""
Standalone profiler for Gemini streaming latency inside the backend container.
Measures:
  1. Cold request (new client / TLS handshake): request_sent -> first_byte -> first_token -> total
  2. Warm keep-alive request (reused persistent AsyncClient): request_sent -> first_byte -> first_token -> total
  3. Compares thinkingConfig options on gemini-3.5-flash-lite.

Usage:
  docker compose exec backend python scripts/profile_gemini_stream.py
"""
import asyncio
import json
import os
import sys
import time
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings


async def time_stream_call(
    client: httpx.AsyncClient,
    model: str,
    generation_config: dict,
    label: str,
) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={settings.GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Say hello in one short sentence."}]}],
        "system_instruction": {"parts": [{"text": "Reply in 1 short spoken sentence."}]},
        "generationConfig": generation_config,
    }
    t_start = time.perf_counter()
    first_byte_ms = None
    first_token_ms = None
    chunks = 0
    tokens = []

    async with client.stream("POST", url, json=payload) as resp:
        status = resp.status_code
        if status != 200:
            body = (await resp.aread()).decode("utf-8", errors="ignore")
            print(f"[{label}] HTTP {status}: {body[:200]}")
            return {"label": label, "status": status}

        async for line in resp.aiter_lines():
            now_ms = (time.perf_counter() - t_start) * 1000.0
            if first_byte_ms is None:
                first_byte_ms = now_ms
            s = line.strip()
            if not s.startswith("data:"):
                continue
            data_str = s[5:].strip()
            if not data_str:
                continue
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            cands = chunk.get("candidates", [])
            if cands:
                for part in cands[0].get("content", {}).get("parts", []):
                    txt = part.get("text", "")
                    if txt:
                        chunks += 1
                        if first_token_ms is None:
                            first_token_ms = (time.perf_counter() - t_start) * 1000.0
                        tokens.append(txt)

    total_ms = (time.perf_counter() - t_start) * 1000.0
    print(
        f"[{label}] status={status} first_byte={first_byte_ms:.1f}ms "
        f"first_token={first_token_ms or 0:.1f}ms total={total_ms:.1f}ms "
        f"chunks={chunks} text={''.join(tokens).strip()!r}"
    )
    return {
        "label": label,
        "status": status,
        "first_byte_ms": round(first_byte_ms or 0.0, 1),
        "first_token_ms": round(first_token_ms or 0.0, 1),
        "total_ms": round(total_ms, 1),
        "chunks": chunks,
    }


async def main() -> None:
    if not settings.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is not set.")
        return

    model = settings.DEFAULT_GEMINI_MODEL
    print(f"Profiling Gemini stream model={model}")

    # 1. Cold new client (old behavior)
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=30.0)) as cold_client:
        await time_stream_call(
            cold_client,
            model,
            {"temperature": 0.4, "maxOutputTokens": 150, "thinkingConfig": {"thinkingLevel": "minimal"}},
            "cold_new_client_minimal",
        )

    # 2. Persistent keep-alive client
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, read=30.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0),
    ) as warm_client:
        await time_stream_call(
            warm_client,
            model,
            {"temperature": 0.4, "maxOutputTokens": 150, "thinkingConfig": {"thinkingLevel": "minimal"}},
            "warm_1_minimal",
        )
        await time_stream_call(
            warm_client,
            model,
            {"temperature": 0.4, "maxOutputTokens": 150, "thinkingConfig": {"thinkingLevel": "minimal"}},
            "warm_2_minimal",
        )
        await time_stream_call(
            warm_client,
            model,
            {"temperature": 0.4, "maxOutputTokens": 150, "thinkingConfig": {"thinkingLevel": "none"}},
            "warm_thinking_none",
        )
        await time_stream_call(
            warm_client,
            model,
            {"temperature": 0.4, "maxOutputTokens": 150},
            "warm_no_thinking_cfg",
        )


if __name__ == "__main__":
    asyncio.run(main())
