import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class ToolBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    description: str = Field(..., min_length=2, max_length=1000)
    parameters_schema: str = Field(default='{"type": "object", "properties": {}, "required": []}')
    is_sensitive: bool = Field(default=False)
    execution_type: str = Field(default="mock")  # 'mock', 'webhook', 'built_in'
    webhook_url: Optional[str] = Field(default=None, max_length=500)
    webhook_method: Optional[str] = Field(default="POST")
    webhook_headers: Optional[str] = Field(default="{}")
    webhook_body_template: Optional[str] = Field(default=None)

    @field_validator("execution_type")
    @classmethod
    def validate_exec_type(cls, v: str) -> str:
        t = v.strip().lower()
        if t not in ("mock", "webhook", "built_in"):
            raise ValueError("execution_type must be 'mock', 'webhook', or 'built_in'")
        return t

    @field_validator("parameters_schema")
    @classmethod
    def validate_schema_json(cls, v: str) -> str:
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"parameters_schema must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("parameters_schema must be a JSON object")
        return json.dumps(parsed)

    @field_validator("webhook_headers")
    @classmethod
    def validate_headers_json(cls, v: Optional[str]) -> str:
        if not v:
            return "{}"
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"webhook_headers must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("webhook_headers must be a JSON object")
        return json.dumps(parsed)

    @field_validator("webhook_method")
    @classmethod
    def validate_method(cls, v: Optional[str]) -> str:
        m = (v or "POST").strip().upper()
        if m not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise ValueError("webhook_method must be GET, POST, PUT, PATCH, or DELETE")
        return m


class ToolCreate(ToolBase):
    pass


class ToolUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    description: Optional[str] = Field(default=None, min_length=2, max_length=1000)
    parameters_schema: Optional[str] = None
    is_sensitive: Optional[bool] = None
    execution_type: Optional[str] = None
    webhook_url: Optional[str] = Field(default=None, max_length=500)
    webhook_method: Optional[str] = None
    webhook_headers: Optional[str] = None
    webhook_body_template: Optional[str] = None


class ToolResponse(ToolBase):
    id: str
    user_id: str
    agent_ids: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BuiltinToolPreset(BaseModel):
    name: str
    description: str
    parameters_schema: str
    is_sensitive: bool
    execution_type: str = "built_in"
