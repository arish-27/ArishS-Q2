from fastapi import APIRouter
from pydantic import BaseModel
import time
from app.core.database import engine
from app.services.rate_limiter import rate_limiter

router = APIRouter()

start_time = time.time()


class HealthResponse(BaseModel):
    status: str
    service: str
    uptime_seconds: float
    version: str
    database_dialect: str
    rate_limiter_backend: str


@router.get("/health", response_model=HealthResponse)
async def get_health():
    """
    Service health check endpoint reporting database dialect and active rate limiter backend.
    """
    limiter_backend = await rate_limiter.get_backend_status()
    return HealthResponse(
        status="healthy",
        service="AI Voice Agent Backend",
        uptime_seconds=round(time.time() - start_time, 2),
        version="0.3.0",
        database_dialect=engine.dialect.name,
        rate_limiter_backend=limiter_backend,
    )
