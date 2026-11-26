"""
Small concurrency load check: 10 concurrent text chat requests against the live FastAPI backend.

Usage:
  docker compose exec backend python scripts/load_check.py
"""
import asyncio
import os
import sys
import time
import uuid
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings

API_BASE = "http://127.0.0.1:8000/api/v1"


async def main() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        email = f"load_{uuid.uuid4().hex[:8]}@example.com"
        reg = (await client.post(f"{API_BASE}/auth/register", json={"email": email, "password": "Password123!"})).json()
        token = reg["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        agent = (
            await client.post(
                f"{API_BASE}/agents",
                json={
                    "name": "Load Check Agent",
                    "llm_provider": "gemini",
                    "llm_model": settings.DEFAULT_GEMINI_MODEL,
                    "temperature": 0.2,
                },
                headers=headers,
            )
        ).json()
        agent_id = agent["id"]

        async def one_chat(idx: int) -> dict:
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    f"{API_BASE}/chat/{agent_id}",
                    json={"message": f"Say hello #{idx} in five words."},
                    headers=headers,
                )
                ms = (time.perf_counter() - t0) * 1000.0
                return {"idx": idx, "status": resp.status_code, "ms": round(ms, 1), "ok": resp.status_code == 200}
            except Exception as exc:
                ms = (time.perf_counter() - t0) * 1000.0
                return {"idx": idx, "status": 0, "ms": round(ms, 1), "ok": False, "error": str(exc)}

        t_wall0 = time.perf_counter()
        results = await asyncio.gather(*(one_chat(i) for i in range(10)))
        wall_ms = (time.perf_counter() - t_wall0) * 1000.0

        latencies = sorted(r["ms"] for r in results)
        errors = [r for r in results if not r["ok"]]
        avg_ms = round(sum(latencies) / len(latencies), 1)
        p95_ms = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))]

        print(f"LOAD_CHECK: requests=10 errors={len(errors)} wall_ms={round(wall_ms, 1)} min_ms={latencies[0]} avg_ms={avg_ms} p95_ms={p95_ms} max_ms={latencies[-1]}")
        if errors:
            print("ERRORS:", errors)


if __name__ == "__main__":
    asyncio.run(main())
