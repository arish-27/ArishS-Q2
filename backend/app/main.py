from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.logger import logger
from app.api.router import api_router
from app.core.database import engine, Base
from app.providers.stt.faster_whisper_provider import warmup_whisper_model
from app.services.rate_limiter import rate_limiter
import app.models  # Load all models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database schema is initialized
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            from sqlalchemy import text
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        if conn.dialect.name == "sqlite":
            await conn.run_sync(Base.metadata.create_all)
    await rate_limiter.get_backend_status()
    warmup_task = None
    if settings.WHISPER_WARMUP_ON_STARTUP and settings.DEFAULT_STT_PROVIDER == "faster-whisper":
        async def _safe_warmup():
            try:
                await warmup_whisper_model()
            except Exception as exc:
                logger.warning(f"faster-whisper startup warmup skipped: {exc}")

        import asyncio
        warmup_task = asyncio.create_task(_safe_warmup())
    yield
    if warmup_task and not warmup_task.done():
        warmup_task.cancel()
    from app.providers.llm.gemini_provider import _GEMINI_HTTP_CLIENTS
    for client in list(_GEMINI_HTTP_CLIENTS.values()):
        if not client.is_closed:
            await client.aclose()
    _GEMINI_HTTP_CLIENTS.clear()
    await rate_limiter.close()
    await engine.dispose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API and WebSocket streaming service for AI Voice Agent Development & Deployment Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Middleware setup supporting port 3001 and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

@app.get("/")
async def root():
    return {
        "message": "AI Voice Agent Development & Deployment Platform API",
        "docs": "/docs",
        "status": "online"
    }
