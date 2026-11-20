from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")
    full_name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class ApiKeyCreate(BaseModel):
    provider: str = Field(..., description="Provider name: 'gemini', 'openai', 'elevenlabs', 'deepgram'")
    api_key: str = Field(..., min_length=1, description="Raw API key to be encrypted in vault")

class ApiKeyResponse(BaseModel):
    id: str
    provider: str
    masked_key: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
