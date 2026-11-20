import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.agent import agent_tools

def generate_uuid() -> str:
    return str(uuid.uuid4())

class Tool(Base):
    __tablename__ = "tools"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    parameters_schema = Column(Text, nullable=False, default="{}")  # JSON-schema string
    is_sensitive = Column(Boolean, default=False, nullable=False)   # Human/voice confirmation required
    execution_type = Column(String(50), default="mock", nullable=False)  # 'mock', 'webhook', 'built_in'
    webhook_url = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="tools")
    agents = relationship("Agent", secondary=agent_tools, back_populates="tools")
