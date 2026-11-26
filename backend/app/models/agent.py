import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Float, Table
from sqlalchemy.orm import relationship
from app.core.database import Base, utc_now

def generate_uuid() -> str:
    return str(uuid.uuid4())

# Association table between Agents and Tools
agent_tools = Table(
    "agent_tools",
    Base.metadata,
    Column("agent_id", String(36), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("tool_id", String(36), ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True)
)

class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    personality = Column(String(255), nullable=True, default="helpful, friendly, concise")
    system_prompt = Column(Text, nullable=False, default="You are a helpful, conversational voice assistant.")

    # Model & Provider Configuration
    llm_provider = Column(String(50), default="gemini", nullable=False)  # 'gemini', 'openai'
    llm_model = Column(String(100), default="gemini-3.5-flash-lite", nullable=False)
    temperature = Column(Float, default=0.7, nullable=False)

    # STT & TTS Configuration
    stt_provider = Column(String(50), default="faster-whisper", nullable=False)
    stt_language = Column(String(10), default="en", nullable=False)
    tts_provider = Column(String(50), default="edge-tts", nullable=False)
    tts_voice = Column(String(100), default="en-US-GuyNeural", nullable=False)

    # Status & Deployment
    is_published = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    user = relationship("User", back_populates="agents")
    tools = relationship("Tool", secondary=agent_tools, back_populates="agents", lazy="selectin")
    documents = relationship("Document", back_populates="agent", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="agent", cascade="all, delete-orphan")
    sessions = relationship("CallSession", back_populates="agent", cascade="all, delete-orphan")
