import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PROJECT_NAME: str = "AI Voice Agent Development & Deployment Platform"
    API_V1_PREFIX: str = "/api/v1"

    # Frontend URLs & CORS
    FRONTEND_URL: str = "http://localhost:3001"
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]

    # Security & JWT
    JWT_SECRET_KEY: str = "supersecretjwtkeyforvoiceagentplatformdevelopment123456789"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    # Fernet 32-byte base64 encryption key for at-rest API key vault
    ENCRYPTION_SECRET_KEY: str = "dGhpcy1pcy1hLTMyLWJ5dGUtYmFzZTY0LWtleS0xMjM0NTY="

    # Database & Redis
    # Uses SQLite async fallback if PostgreSQL is unavailable locally
    DATABASE_URL: str = "sqlite+aiosqlite:///./voiceagent.db"
    REDIS_URL: str = "redis://redis:6379/0"

    # AI Defaults
    DEFAULT_LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    DEFAULT_STT_PROVIDER: str = "faster-whisper"
    DEFAULT_TTS_PROVIDER: str = "edge-tts"
    DEFAULT_TTS_VOICE: str = "en-US-GuyNeural"

    # Single Unified Embedding Model: Gemini text-embedding-004 (768 dimensions)
    RAG_EMBEDDING_MODEL: str = "text-embedding-004"
    RAG_EMBEDDING_DIM: int = 768
    UPLOAD_STORAGE_DIR: str = "./uploads"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
