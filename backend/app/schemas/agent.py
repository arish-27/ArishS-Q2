import re
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List
from datetime import datetime

SUPPORTED_GEMINI_MODELS = [
    "gemini-4-hydrogen",
    "gemini-4-neon",
    "gemini-4-carbon",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
]

SUPPORTED_OPENAI_MODELS = [
    "gpt-6-luna",
    "gpt-6.1-terra",
    "gpt-6.2-sol",
    "gpt-6.2-astra",
]

RETIRED_OR_DEPRECATED_MODELS = {
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-pro",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "o1-mini",
    "o1-preview",
    "o1",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-5",
    "gpt-5-mini",
}

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

class AgentBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: Optional[str] = None
    description: Optional[str] = None
    personality: Optional[str] = "helpful, friendly, concise"
    system_prompt: str = Field(default="You are a helpful, conversational voice assistant.")

    llm_provider: str = Field(default="gemini", description="'gemini' or 'openai'")
    llm_model: str = Field(default="gemini-4-hydrogen")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)

    stt_provider: str = Field(default="faster-whisper")
    stt_language: str = Field(default="en")
    tts_provider: str = Field(default="edge-tts")
    tts_voice: str = Field(default="en-US-GuyNeural")

    @field_validator("slug")
    def validate_slug(cls, v):
        if v is not None and not re.match(r'^[a-z0-9-]+$', v):
            raise ValueError("Slug must contain only lowercase alphanumeric characters and hyphens")
        return v

    @field_validator("llm_model")
    def validate_llm_model(cls, v):
        return v.strip()

class AgentCreate(AgentBase):
    @field_validator("llm_provider")
    def validate_provider(cls, v):
        prov = v.lower().strip()
        if prov not in ("gemini", "openai"):
            raise ValueError("llm_provider must be 'gemini' or 'openai'")
        return prov

    @field_validator("llm_model")
    def validate_active_model(cls, v, info):
        model = v.strip()
        if model in RETIRED_OR_DEPRECATED_MODELS:
            raise ValueError(
                f"Model '{model}' is retired or deprecated. "
                f"Active Gemini models: {SUPPORTED_GEMINI_MODELS}; Active OpenAI models: {SUPPORTED_OPENAI_MODELS}"
            )
        prov = (info.data.get("llm_provider") or "gemini").lower().strip()
        allowed = SUPPORTED_GEMINI_MODELS if prov == "gemini" else SUPPORTED_OPENAI_MODELS
        if model not in allowed:
            raise ValueError(f"Unsupported model '{model}' for provider '{prov}'. Allowed: {allowed}")
        return model

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    personality: Optional[str] = None
    system_prompt: Optional[str] = None

    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    stt_provider: Optional[str] = None
    stt_language: Optional[str] = None
    tts_provider: Optional[str] = None
    tts_voice: Optional[str] = None

    is_published: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("llm_model")
    def validate_active_model(cls, v):
        if v is None:
            return v
        model = v.strip()
        if model in RETIRED_OR_DEPRECATED_MODELS:
            raise ValueError(f"Model '{model}' is retired or deprecated.")
        if model not in SUPPORTED_GEMINI_MODELS and model not in SUPPORTED_OPENAI_MODELS:
            raise ValueError(
                f"Unsupported model '{model}'. Allowed: {SUPPORTED_GEMINI_MODELS + SUPPORTED_OPENAI_MODELS}"
            )
        return model

class AgentPublish(BaseModel):
    is_published: bool
    slug: Optional[str] = None

class AgentResponse(AgentBase):
    id: str
    user_id: str
    slug: str
    is_published: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PublicAgentResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    personality: Optional[str] = None
    stt_language: str
    tts_voice: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
