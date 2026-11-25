"""
Verifies the active Gemini & OpenAI model catalog and gemini-embedding-001 (768-dim)
against live official provider APIs when credentials are provided in environment.
"""
import asyncio
import json
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.schemas.agent import SUPPORTED_GEMINI_MODELS, SUPPORTED_OPENAI_MODELS
from app.providers.embeddings.gemini_embedding import GeminiEmbeddingProvider


async def verify_gemini() -> None:
    print("=== Gemini API Verification ===")
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        print("NO_KEY: GEMINI_API_KEY is not configured in environment/.env.")
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://generativelanguage.googleapis.com/v1beta/models")
            print(f"Unauthenticated probe HTTP {r.status_code}: {r.text[:160].strip()}")
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")
        print(f"GET /v1beta/models -> HTTP {r.status_code}")
        if r.status_code == 200:
            names = {m["name"].replace("models/", "") for m in r.json().get("models", [])}
            for model in SUPPORTED_GEMINI_MODELS:
                print(f"  - {model}: {'FOUND' if model in names else 'NOT_IN_LIST'}")
            print(f"  - {settings.RAG_EMBEDDING_MODEL}: {'FOUND' if settings.RAG_EMBEDDING_MODEL in names else 'NOT_IN_LIST'}")
        else:
            print(r.text[:300])
            return

    provider = GeminiEmbeddingProvider(api_key=api_key)
    vec = await provider.embed_text("Voice agent verification check", task_type="RETRIEVAL_QUERY")
    print(f"Embedding call succeeded: model={settings.RAG_EMBEDDING_MODEL}, dim={len(vec)}")


async def verify_openai() -> None:
    print("\n=== OpenAI API Verification ===")
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        print("NO_KEY: OPENAI_API_KEY is not configured in environment/.env.")
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://api.openai.com/v1/models")
            print(f"Unauthenticated probe HTTP {r.status_code}: {r.text[:160].strip()}")
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        print(f"GET /v1/models -> HTTP {r.status_code}")
        if r.status_code == 200:
            ids = {m["id"] for m in r.json().get("data", [])}
            for model in SUPPORTED_OPENAI_MODELS:
                print(f"  - {model}: {'FOUND' if model in ids else 'NOT_IN_LIST'}")
        else:
            print(r.text[:300])


async def main() -> None:
    await verify_gemini()
    await verify_openai()


if __name__ == "__main__":
    asyncio.run(main())
