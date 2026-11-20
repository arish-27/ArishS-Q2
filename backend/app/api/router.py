from fastapi import APIRouter
from app.api.v1 import health, auth, agents, chat

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication & Vault"])
api_router.include_router(agents.router, prefix="/agents", tags=["Agents"])
api_router.include_router(chat.router, prefix="/chat", tags=["Text Chat & LLM"])
