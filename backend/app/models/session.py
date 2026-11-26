import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base, utc_now

def generate_uuid() -> str:
    return str(uuid.uuid4())

class CallSession(Base):
    __tablename__ = "call_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_token = Column(String(100), unique=True, index=True, default=generate_uuid)
    started_at = Column(DateTime, default=utc_now)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    status = Column(String(50), default="active", nullable=False)  # 'active', 'completed', 'interrupted', 'error'
    total_turns = Column(Integer, default=0)
    avg_latency_ms = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utc_now)

    agent = relationship("Agent", back_populates="sessions")
    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan")

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("call_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'system', 'tool'
    content = Column(Text, nullable=False)
    audio_duration_ms = Column(Integer, default=0)
    stt_latency_ms = Column(Float, default=0.0)
    llm_first_token_ms = Column(Float, default=0.0)
    llm_latency_ms = Column(Float, default=0.0)
    tts_first_audio_ms = Column(Float, default=0.0)
    tts_latency_ms = Column(Float, default=0.0)
    e2e_latency_ms = Column(Float, default=0.0)
    tool_calls_json = Column(Text, nullable=True)
    tool_results_json = Column(Text, nullable=True)
    rag_sources_json = Column(Text, nullable=True)
    interrupted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    session = relationship("CallSession", back_populates="messages")
