import re
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List
from datetime import datetime

SUPPORTED_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

SUPPORTED_OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "o1-mini",
    "o1",
]

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
    llm_model: str = Field(default="gemini-2.5-flash")
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
    def validate_llm_model(cls, v, values):
        # Allow any supported active model or custom model
        return v.strip()

class AgentCreate(AgentBase):
    pass

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
