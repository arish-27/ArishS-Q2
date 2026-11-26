from fastapi import APIRouter
from app.api.v1 import health, auth, agents, chat, voice, knowledge, tools, analytics

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication & Vault"])
api_router.include_router(agents.router, prefix="/agents", tags=["Agents"])
api_router.include_router(chat.router, prefix="/chat", tags=["Text Chat & LLM"])
api_router.include_router(voice.router, prefix="/voice", tags=["Real-Time Voice"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge Base & RAG"])
api_router.include_router(tools.router, prefix="/tools", tags=["Function Tools"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
