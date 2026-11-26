from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.agent import Agent
from app.models.tool import Tool
from app.models.user import User
from app.schemas.tool import BuiltinToolPreset, ToolCreate, ToolResponse, ToolUpdate
from app.services.tool_executor import BUILTIN_TOOL_PRESETS, SSRFBlockedError, validate_webhook_url_ssrf

router = APIRouter()


def _to_tool_response(tool: Tool) -> ToolResponse:
    return ToolResponse(
        id=tool.id,
        user_id=tool.user_id,
        name=tool.name,
        description=tool.description,
        parameters_schema=tool.parameters_schema,
        is_sensitive=tool.is_sensitive,
        execution_type=tool.execution_type,
        webhook_url=tool.webhook_url,
        webhook_method=tool.webhook_method or "POST",
        webhook_headers=tool.webhook_headers or "{}",
        webhook_body_template=tool.webhook_body_template,
        agent_ids=[a.id for a in (tool.agents or [])],
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


@router.get("/builtins", response_model=List[BuiltinToolPreset])
async def list_builtin_presets():
    """List read-only built-in tool presets."""
    return [BuiltinToolPreset(**preset) for preset in BUILTIN_TOOL_PRESETS.values()]


@router.get("", response_model=List[ToolResponse])
async def list_tools(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tools owned by the current user."""
    res = await db.execute(
        select(Tool)
        .options(selectinload(Tool.agents))
        .where(Tool.user_id == current_user.id)
        .order_by(Tool.created_at.desc())
    )
    return [_to_tool_response(t) for t in res.scalars().all()]


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
async def create_tool(
    tool_in: ToolCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom or built-in tool owned by the current user."""
    if tool_in.execution_type == "webhook":
        try:
            validate_webhook_url_ssrf(tool_in.webhook_url or "")
        except SSRFBlockedError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    tool = Tool(
        user_id=current_user.id,
        name=tool_in.name.strip(),
        description=tool_in.description.strip(),
        parameters_schema=tool_in.parameters_schema,
        is_sensitive=tool_in.is_sensitive,
        execution_type=tool_in.execution_type,
        webhook_url=tool_in.webhook_url.strip() if tool_in.webhook_url else None,
        webhook_method=tool_in.webhook_method,
        webhook_headers=tool_in.webhook_headers,
        webhook_body_template=tool_in.webhook_body_template,
    )
    db.add(tool)
    await db.commit()
    res = await db.execute(
        select(Tool).options(selectinload(Tool.agents)).where(Tool.id == tool.id)
    )
    return _to_tool_response(res.scalar_one())


@router.put("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: str,
    tool_in: ToolUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an owned tool."""
    res = await db.execute(
        select(Tool)
        .options(selectinload(Tool.agents))
        .where(Tool.id == tool_id, Tool.user_id == current_user.id)
    )
    tool = res.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

    update_data = tool_in.model_dump(exclude_unset=True)
    new_exec = update_data.get("execution_type", tool.execution_type)
    new_url = update_data.get("webhook_url", tool.webhook_url)
    if new_exec == "webhook":
        try:
            validate_webhook_url_ssrf(new_url or "")
        except SSRFBlockedError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    for field, val in update_data.items():
        setattr(tool, field, val)

    await db.commit()
    await db.refresh(tool)
    return _to_tool_response(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an owned tool."""
    res = await db.execute(
        select(Tool).where(Tool.id == tool_id, Tool.user_id == current_user.id)
    )
    tool = res.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

    await db.delete(tool)
    await db.commit()
    return None


@router.post("/{tool_id}/assign/{agent_id}", response_model=ToolResponse)
async def assign_tool_to_agent(
    tool_id: str,
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign an owned tool to an owned agent."""
    tool_res = await db.execute(
        select(Tool)
        .options(selectinload(Tool.agents))
        .where(Tool.id == tool_id, Tool.user_id == current_user.id)
    )
    tool = tool_res.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

    agent_res = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == current_user.id)
    )
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if all(a.id != agent.id for a in tool.agents):
        tool.agents.append(agent)
        await db.commit()
        await db.refresh(tool)

    return _to_tool_response(tool)


@router.delete("/{tool_id}/assign/{agent_id}", response_model=ToolResponse)
async def unassign_tool_from_agent(
    tool_id: str,
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unassign an owned tool from an owned agent."""
    tool_res = await db.execute(
        select(Tool)
        .options(selectinload(Tool.agents))
        .where(Tool.id == tool_id, Tool.user_id == current_user.id)
    )
    tool = tool_res.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

    tool.agents = [a for a in tool.agents if a.id != agent_id]
    await db.commit()
    await db.refresh(tool)
    return _to_tool_response(tool)
