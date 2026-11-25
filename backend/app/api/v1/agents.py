import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.user import User
from app.models.agent import Agent
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentPublish,
    AgentResponse,
    PublicAgentResponse,
    SUPPORTED_GEMINI_MODELS,
    SUPPORTED_OPENAI_MODELS,
    slugify,
)
from app.core.config import settings
from app.api.deps import get_current_user

router = APIRouter()

async def get_unique_slug(db: AsyncSession, base_name: str, current_agent_id: Optional[str] = None) -> str:
    """Generates a URL-friendly unique slug, appending random/numeric suffix if needed."""
    base_slug = slugify(base_name) or "agent"
    candidate = base_slug

    counter = 1
    while True:
        query = select(Agent).where(Agent.slug == candidate)
        if current_agent_id:
            query = query.where(Agent.id != current_agent_id)
        result = await db.execute(query)
        if not result.scalar_one_or_none():
            return candidate
        candidate = f"{base_slug}-{counter}"
        counter += 1

@router.get("", response_model=List[AgentResponse])
async def list_agents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all agents belonging to the authenticated user (strict user isolation)."""
    result = await db.execute(
        select(Agent).where(Agent.user_id == current_user.id).order_by(Agent.created_at.desc())
    )
    agents = result.scalars().all()
    return agents

@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent_in: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Creates a new AI voice agent owned by current user."""
    # Ensure unique slug
    if agent_in.slug:
        # Check if requested slug is available
        slug_check = await db.execute(select(Agent).where(Agent.slug == agent_in.slug))
        if slug_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slug '{agent_in.slug}' is already taken"
            )
        final_slug = agent_in.slug
    else:
        final_slug = await get_unique_slug(db, agent_in.name)

    agent = Agent(
        user_id=current_user.id,
        name=agent_in.name,
        slug=final_slug,
        description=agent_in.description,
        personality=agent_in.personality,
        system_prompt=agent_in.system_prompt,
        llm_provider=agent_in.llm_provider,
        llm_model=agent_in.llm_model,
        temperature=agent_in.temperature,
        stt_provider=agent_in.stt_provider,
        stt_language=agent_in.stt_language,
        tts_provider=agent_in.tts_provider,
        tts_voice=agent_in.tts_voice,
        is_published=False,
        is_active=True
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent

@router.get("/catalog/models")
async def get_model_catalog():
    """Returns active, non-retired LLM and embedding models supported by the platform."""
    return {
        "llm": {
            "gemini": SUPPORTED_GEMINI_MODELS,
            "openai": SUPPORTED_OPENAI_MODELS,
        },
        "embedding": {
            "provider": "gemini",
            "model": settings.RAG_EMBEDDING_MODEL,
            "dimensions": settings.RAG_EMBEDDING_DIM,
        },
        "stt": ["faster-whisper"],
        "tts": ["edge-tts"],
    }

@router.get("/public/{slug}", response_model=PublicAgentResponse)
async def get_public_agent(slug: str, db: AsyncSession = Depends(get_db)):
    """
    Public lookup for published voice agents by slug.
    Used for anonymous call sessions at `/a/{slug}`.
    """
    result = await db.execute(
        select(Agent).where(
            Agent.slug == slug,
            Agent.is_published == True,
            Agent.is_active == True
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public agent not found or inactive"
        )
    return agent

@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetch specific agent. Enforces tenant isolation (User A cannot view User B's agent)."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent or agent.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )

    return agent

@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    agent_in: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Updates an existing agent. Enforces tenant isolation."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent or agent.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )

    update_data = agent_in.model_dump(exclude_unset=True)

    # Check slug uniqueness if updating slug
    if "slug" in update_data and update_data["slug"]:
        new_slug = update_data["slug"]
        slug_check = await db.execute(
            select(Agent).where(Agent.slug == new_slug, Agent.id != agent_id)
        )
        if slug_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slug '{new_slug}' is already taken"
            )

    for field, value in update_data.items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return agent

@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deletes an agent. Enforces tenant isolation."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent or agent.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )

    await db.delete(agent)
    await db.commit()
    return None

@router.post("/{agent_id}/publish", response_model=AgentResponse)
async def publish_agent(
    agent_id: str,
    publish_in: AgentPublish,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Toggles agent publication status and optionally customizes the shareable slug."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent or agent.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )

    agent.is_published = publish_in.is_published

    if publish_in.slug:
        slug_check = await db.execute(
            select(Agent).where(Agent.slug == publish_in.slug, Agent.id != agent_id)
        )
        if slug_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slug '{publish_in.slug}' is already in use"
            )
        agent.slug = publish_in.slug

    await db.commit()
    await db.refresh(agent)
    return agent
