import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.agent import Agent
from app.models.session import CallSession, ConversationMessage
from app.models.user import User

router = APIRouter()


@router.get("/overview")
async def get_analytics_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns aggregated session, latency, error, 14-day trend, and top agent metrics for the owner."""
    sess_res = await db.execute(
        select(CallSession, Agent.name)
        .join(Agent, Agent.id == CallSession.agent_id)
        .where(Agent.user_id == current_user.id)
        .order_by(CallSession.started_at.desc())
    )
    session_rows = sess_res.all()
    session_ids = [s.id for s, _ in session_rows]

    total_sessions = len(session_rows)
    total_seconds = sum((s.duration_seconds or 0) for s, _ in session_rows)
    total_minutes = round(total_seconds / 60.0, 2)
    error_count = sum(1 for s, _ in session_rows if s.status == "error")

    # Stage latency averages from assistant messages
    stt_vals: List[float] = []
    llm_ttft_vals: List[float] = []
    tts_ttfa_vals: List[float] = []
    e2e_vals: List[float] = []

    if session_ids:
        msg_res = await db.execute(
            select(ConversationMessage).where(
                ConversationMessage.session_id.in_(session_ids),
                ConversationMessage.role == "assistant",
            )
        )
        for m in msg_res.scalars().all():
            if m.stt_latency_ms and m.stt_latency_ms > 0:
                stt_vals.append(m.stt_latency_ms)
            if m.llm_first_token_ms and m.llm_first_token_ms > 0:
                llm_ttft_vals.append(m.llm_first_token_ms)
            if m.tts_first_audio_ms and m.tts_first_audio_ms > 0:
                tts_ttfa_vals.append(m.tts_first_audio_ms)
            if m.e2e_latency_ms and m.e2e_latency_ms > 0:
                e2e_vals.append(m.e2e_latency_ms)

    def _avg(arr: List[float]) -> float:
        return round(sum(arr) / len(arr), 1) if arr else 0.0

    # Sessions per day (last 14 days)
    today = datetime.now(timezone.utc).date()
    day_buckets: Dict[str, Dict[str, int]] = {}
    for offset in range(13, -1, -1):
        d_str = (today - timedelta(days=offset)).isoformat()
        day_buckets[d_str] = {"date": d_str, "sessions": 0, "errors": 0}

    agent_agg: Dict[str, Dict[str, Any]] = {}
    for s, agent_name in session_rows:
        if s.started_at:
            d_key = s.started_at.date().isoformat()
            if d_key in day_buckets:
                day_buckets[d_key]["sessions"] += 1
                if s.status == "error":
                    day_buckets[d_key]["errors"] += 1

        entry = agent_agg.setdefault(
            s.agent_id,
            {"agent_id": s.agent_id, "agent_name": agent_name, "sessions": 0, "lat_sum": 0.0, "lat_cnt": 0},
        )
        entry["sessions"] += 1
        if s.avg_latency_ms and s.avg_latency_ms > 0:
            entry["lat_sum"] += s.avg_latency_ms
            entry["lat_cnt"] += 1

    top_agents = sorted(
        [
            {
                "agent_id": v["agent_id"],
                "agent_name": v["agent_name"],
                "sessions": v["sessions"],
                "avg_e2e_ms": round(v["lat_sum"] / v["lat_cnt"], 1) if v["lat_cnt"] else 0.0,
            }
            for v in agent_agg.values()
        ],
        key=lambda x: x["sessions"],
        reverse=True,
    )[:5]

    return {
        "total_sessions": total_sessions,
        "total_minutes": total_minutes,
        "error_count": error_count,
        "avg_stt_latency_ms": _avg(stt_vals),
        "avg_llm_first_token_ms": _avg(llm_ttft_vals),
        "avg_tts_first_audio_ms": _avg(tts_ttfa_vals),
        "avg_e2e_latency_ms": _avg(e2e_vals),
        "sessions_per_day": list(day_buckets.values()),
        "top_agents": top_agents,
    }


@router.get("/sessions")
async def list_analytics_sessions(
    agent_id: Optional[str] = Query(default=None),
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists call sessions for the current user's agents with optional agent, date, and status filters."""
    stmt = (
        select(CallSession, Agent.name)
        .join(Agent, Agent.id == CallSession.agent_id)
        .where(Agent.user_id == current_user.id)
    )
    if agent_id:
        stmt = stmt.where(CallSession.agent_id == agent_id)
    if status_filter:
        stmt = stmt.where(CallSession.status == status_filter)
    stmt = stmt.order_by(CallSession.started_at.desc()).limit(200)

    rows = (await db.execute(stmt)).all()
    results = []
    for s, agent_name in rows:
        if date and s.started_at and s.started_at.date().isoformat() != date:
            continue
        results.append({
            "id": s.id,
            "agent_id": s.agent_id,
            "agent_name": agent_name,
            "is_public": s.user_id is None,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "duration_seconds": s.duration_seconds or 0,
            "status": s.status,
            "total_turns": s.total_turns or 0,
            "avg_latency_ms": round(s.avg_latency_ms or 0.0, 1),
        })
    return results


@router.get("/sessions/{session_id}")
async def get_analytics_session_detail(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns full transcript, per-turn latencies, tool calls, and RAG sources for an owned session."""
    res = await db.execute(
        select(CallSession, Agent.name)
        .join(Agent, Agent.id == CallSession.agent_id)
        .where(CallSession.id == session_id, Agent.user_id == current_user.id)
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    s, agent_name = row
    msg_res = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.session_id == s.id)
        .order_by(ConversationMessage.created_at.asc())
    )
    messages = []
    for m in msg_res.scalars().all():
        def _safe_json(raw: Optional[str]):
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return None

        messages.append({
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "audio_duration_ms": m.audio_duration_ms or 0,
            "stt_latency_ms": m.stt_latency_ms or 0.0,
            "llm_first_token_ms": m.llm_first_token_ms or 0.0,
            "llm_latency_ms": m.llm_latency_ms or 0.0,
            "tts_first_audio_ms": m.tts_first_audio_ms or 0.0,
            "tts_latency_ms": m.tts_latency_ms or 0.0,
            "e2e_latency_ms": m.e2e_latency_ms or 0.0,
            "tool_calls": _safe_json(m.tool_calls_json),
            "tool_results": _safe_json(m.tool_results_json),
            "rag_sources": _safe_json(m.rag_sources_json),
            "interrupted": bool(m.interrupted),
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return {
        "id": s.id,
        "agent_id": s.agent_id,
        "agent_name": agent_name,
        "is_public": s.user_id is None,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "duration_seconds": s.duration_seconds or 0,
        "status": s.status,
        "total_turns": s.total_turns or 0,
        "avg_latency_ms": round(s.avg_latency_ms or 0.0, 1),
        "messages": messages,
    }
