from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class DocumentResponse(BaseModel):
    id: str
    user_id: str
    agent_id: Optional[str] = None
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RagQueryRequest(BaseModel):
    agent_id: str
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20)
    similarity_threshold: float = Field(default=0.35, ge=0.0, le=1.0)


class RagChunkResult(BaseModel):
    document_id: str
    filename: str
    chunk_index: int
    content: str
    score: float


class RagQueryResponse(BaseModel):
    agent_id: str
    query: str
    results: List[RagChunkResult]
