import os
import base64
from typing import Optional, List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet

INSECURE_PLACEHOLDERS = {
    "supersecretjwtkeyforvoiceagentplatformdevelopment123456789",
    "dGhpcy1pcy1hLTMyLWJ5dGUtYmFzZTY0LWtleS0xMjM0NTY=",
    "generate_with_openssl_rand_hex_32",
    "generate_with_fernet_generate_key_base64",
    "changeme",
    "secret",
    "placeholder"
}

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

    # Security & JWT - No hardcoded fallback, strict validation against placeholders
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Secret Encryption Key (Fernet key) - No hardcoded fallback
    ENCRYPTION_SECRET_KEY: str

    # Database & Redis
    DATABASE_URL: str = "sqlite+aiosqlite:///./voiceagent.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # AI Defaults (Active non-retired models only - verified against Nov 2026 docs)
    DEFAULT_LLM_PROVIDER: str = "gemini"
    DEFAULT_GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    DEFAULT_GEMINI_FALLBACK_MODEL: str = "gemini-3.8-flash"
    DEFAULT_OPENAI_MODEL: str = "gpt-6-luna"
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    # Context window & token management
    CONTEXT_WINDOW_TURNS: int = 6
    CONTEXT_TOKEN_BUDGET: int = 2000
    LLM_FIRST_TOKEN_TIMEOUT_S: float = 8.0

    # Speech, STT & TTS Defaults
    DEFAULT_STT_PROVIDER: str = "faster-whisper"
    WHISPER_MODEL_SIZE: str = "small"
    WHISPER_COMPUTE_TYPE: str = "int8"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_WARMUP_ON_STARTUP: bool = True
    DEFAULT_TTS_PROVIDER: str = "edge-tts"
    DEFAULT_TTS_VOICE: str = "en-US-GuyNeural"

    # Server-Side VAD Settings
    VAD_SILENCE_THRESHOLD_MS: int = 700
    VAD_SPEECH_THRESHOLD: float = 0.5
    VAD_MIN_SPEECH_MS: int = 200

    # Voice WebSocket Security & Rate Limiting
    VOICE_MAX_SESSION_SECONDS: int = 900
    WS_MAX_MESSAGE_BYTES: int = 65536
    WS_RATE_LIMIT_CONNECTIONS: int = 20
    WS_RATE_LIMIT_WINDOW_SECONDS: int = 60
    WS_RATE_LIMIT_FRAMES_PER_MIN: int = 3600

    # Active Gemini Embedding model with 768 output dimensionality (MRL)
    RAG_EMBEDDING_MODEL: str = "gemini-embedding-001"
    RAG_EMBEDDING_DIM: int = 768
    UPLOAD_STORAGE_DIR: str = "./uploads"

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if not v or v.strip().lower() in INSECURE_PLACEHOLDERS:
            raise RuntimeError(
                "Critical Security Error: JWT_SECRET_KEY is missing or set to an insecure placeholder. "
                "Provide a secure key with at least 32 characters in .env."
            )
        if len(v.strip()) < 32:
            raise RuntimeError(
                "Critical Security Error: JWT_SECRET_KEY must be at least 32 characters."
            )
        return v.strip()

    @field_validator("ENCRYPTION_SECRET_KEY")
    @classmethod
    def validate_encryption_secret(cls, v: str) -> str:
        if not v or v.strip().lower() in INSECURE_PLACEHOLDERS:
            raise RuntimeError(
                "Critical Security Error: ENCRYPTION_SECRET_KEY is missing or set to an insecure placeholder. "
                "Provide a valid 32-byte base64 Fernet key in .env."
            )
        # Validate that it is a valid base64 key for Fernet
        try:
            Fernet(v.strip().encode())
        except Exception as e:
            raise RuntimeError(
                f"Critical Security Error: ENCRYPTION_SECRET_KEY is not a valid Fernet key: {e}"
            )
        return v.strip()

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

try:
    settings = Settings()
except Exception as e:
    # Raise clear error if configuration fails at startup
    raise RuntimeError(f"Startup configuration error: {e}") from e
