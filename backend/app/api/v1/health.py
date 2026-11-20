from fastapi import APIRouter
from pydantic import BaseModel
import time

router = APIRouter()

start_time = time.time()

class HealthResponse(BaseModel):
    status: str
    service: str
    uptime_seconds: float
    version: str

@router.get("/health", response_model=HealthResponse)
async def get_health():
    """
    Service health check endpoint.
    """
    return HealthResponse(
        status="healthy",
        service="AI Voice Agent Backend",
        uptime_seconds=round(time.time() - start_time, 2),
        version="0.1.0"
    )
