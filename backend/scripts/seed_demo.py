"""
Idempotent demo seed script:
Creates a demo user (demo@voiceagent.local / DemoPass123!),
a published demo agent ('demo-assistant') with 2 built-in tools (get_current_time, get_weather),
and indexes one sample knowledge document if GEMINI_API_KEY is configured.

Usage:
  docker compose exec backend python scripts/seed_demo.py
"""
import asyncio
import json
import os
import sys
from sqlalchemy import select
from sqlalchemy.orm import selectinload

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.agent import Agent
from app.models.document import Document
from app.models.tool import Tool
from app.models.user import User
from app.services.rag_service import process_document_background
from app.services.tool_executor import BUILTIN_TOOL_PRESETS


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).where(User.email == "demo@voiceagent.local"))
        user = user_res.scalar_one_or_none()
        if not user:
            user = User(
                email="demo@voiceagent.local",
                full_name="Demo Builder",
                hashed_password=get_password_hash("DemoPass123!"),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print("Created demo user: demo@voiceagent.local / DemoPass123!")
        else:
            print("Demo user already exists: demo@voiceagent.local")

        agent_res = await db.execute(
            select(Agent).options(selectinload(Agent.tools)).where(Agent.slug == "demo-assistant")
        )
        agent = agent_res.scalar_one_or_none()
        if not agent:
            agent = Agent(
                user_id=user.id,
                name="AetherGrid Demo Assistant",
                slug="demo-assistant",
                description="Published demo voice & text assistant with weather/time tools and product knowledge.",
                personality="friendly, concise, helpful",
                system_prompt="You are AetherGrid's helpful voice assistant. Reply concisely in 1-2 short sentences.",
                llm_provider="gemini",
                llm_model=settings.DEFAULT_GEMINI_MODEL,
                temperature=0.5,
                stt_provider="faster-whisper",
                stt_language="en",
                tts_provider="edge-tts",
                tts_voice="en-US-GuyNeural",
                is_published=True,
                is_active=True,
            )
            db.add(agent)
            await db.commit()
            await db.refresh(agent, attribute_names=["tools"])
            print(f"Created published demo agent: slug={agent.slug} id={agent.id}")
        else:
            print(f"Demo agent already exists: slug={agent.slug} id={agent.id}")

        # Ensure 2 built-in tools are created and assigned
        for tool_name in ("get_current_time", "get_weather"):
            preset = BUILTIN_TOOL_PRESETS[tool_name]
            t_res = await db.execute(
                select(Tool).where(Tool.user_id == user.id, Tool.name == tool_name)
            )
            tool = t_res.scalar_one_or_none()
            if not tool:
                tool = Tool(
                    user_id=user.id,
                    name=preset["name"],
                    description=preset["description"],
                    parameters_schema=preset["parameters_schema"],
                    is_sensitive=preset["is_sensitive"],
                    execution_type=preset["execution_type"],
                )
                db.add(tool)
                await db.commit()
                await db.refresh(tool)
            if all(existing.id != tool.id for existing in agent.tools):
                agent.tools.append(tool)
                await db.commit()
        print("Assigned 2 tools (get_current_time, get_weather) to demo-assistant.")

        # Seed 1 sample knowledge document
        doc_res = await db.execute(
            select(Document).where(Document.agent_id == agent.id, Document.filename == "demo_faq.txt")
        )
        doc = doc_res.scalar_one_or_none()
        if not doc:
            sample_text = (
                "AetherGrid Robotics Demo FAQ\n"
                "Headquarters: Indiranagar, Bengaluru, India.\n"
                "Support Hours: Monday to Saturday, 07:00 to 22:00 IST.\n"
                "Rover-S1 carries 35 kg for 10 hours and costs $490/month on RaaS.\n"
                "Hardware returns are accepted within 30 days.\n"
            ).encode("utf-8")
            doc = Document(
                user_id=user.id,
                agent_id=agent.id,
                filename="demo_faq.txt",
                file_type="txt",
                file_size=len(sample_text),
                status="processing",
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            if settings.GEMINI_API_KEY:
                await process_document_background(
                    document_id=doc.id,
                    file_bytes=sample_text,
                    file_type="txt",
                    agent_id=agent.id,
                    api_key=settings.GEMINI_API_KEY,
                    db_session_factory=AsyncSessionLocal,
                )
                print(f"Indexed sample document demo_faq.txt (id={doc.id}).")
            else:
                print(f"Created sample document demo_faq.txt (id={doc.id}, status=processing; set GEMINI_API_KEY to embed).")
        else:
            print(f"Sample document already exists: demo_faq.txt (status={doc.status})")


if __name__ == "__main__":
    asyncio.run(main())
