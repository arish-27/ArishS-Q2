import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base, UniversalVector, utc_now

def generate_uuid() -> str:
    return str(uuid.uuid4())

class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # 'pdf', 'docx', 'txt'
    file_size = Column(Integer, nullable=False, default=0)
    status = Column(String(50), default="processing", nullable=False)  # 'processing', 'indexed', 'failed'
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", back_populates="documents")
    agent = relationship("Agent", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    # Fixed 768-dim embeddings for Gemini gemini-embedding-001 (outputDimensionality=768)
    embedding = Column(UniversalVector(768), nullable=True)
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime, default=utc_now)

    document = relationship("Document", back_populates="chunks")
    agent = relationship("Agent", back_populates="chunks")
