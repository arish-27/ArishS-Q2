import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PROJECT_NAME: str = "AI Voice Agent Development & Deployment Platform"
    API_V1_PREFIX: str = "/api/v1"

    # Security
    JWT_SECRET_KEY: str = "supersecretjwtkeyforvoiceagentplatformdevelopment123456789"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ENCRYPTION_SECRET_KEY: str = "dGhpcy1pcy1hLTMyLWJ5dGUtYmFzZTY0LWtleS0xMjM0NTY="

    # Database & Redis
    DATABASE_URL: str = "postgresql+asyncpg://voiceagent:voiceagent_secret@postgres:5432/voiceagent_db"
    REDIS_URL: str = "redis://redis:6379/0"

    # AI Defaults
    DEFAULT_LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    DEFAULT_STT_PROVIDER: str = "faster-whisper"
    DEFAULT_TTS_PROVIDER: str = "edge-tts"
    DEFAULT_TTS_VOICE: str = "en-US-GuyNeural"

    # RAG Settings
    RAG_EMBEDDING_MODEL: str = "text-embedding-004"
    RAG_EMBEDDING_DIM: int = 768
    UPLOAD_STORAGE_DIR: str = "/app/uploads"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
