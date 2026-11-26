import time
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decrypt_secret
from app.core.config import settings
from app.core.logger import logger
from app.models.user import User, UserApiKey
from app.models.agent import Agent
from app.models.session import CallSession, ConversationMessage
from app.api.deps import get_current_user
from app.providers.llm import (
    get_llm_provider,
    LLMProviderError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError
)
from app.services.context_manager import ConversationContextManager
from app.services.tool_executor import ToolValidationError, SSRFBlockedError, execute_tool

router = APIRouter()

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = None

@router.post("/{agent_id}")
async def chat_with_agent(
    agent_id: str,
    chat_in: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Streaming text chat endpoint with LLM provider orchestration:
    - Enforces strict agent ownership.
    - Decrypts API key in-memory per request from the vault.
    - Context window management and rolling summarization.
    - Emits Server-Sent Events (SSE) with token-by-token stream.
    - Records first-token and total response latency.
    """
    # 1. Verify agent ownership
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent or agent.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found or access denied."
        )

    # 2. Retrieve & decrypt API key
    provider_name = agent.llm_provider.lower().strip()
    key_result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == current_user.id,
            UserApiKey.provider == provider_name
        )
    )
    user_key_row = key_result.scalar_one_or_none()

    api_key: Optional[str] = None
    if user_key_row:
        try:
            api_key = decrypt_secret(user_key_row.encrypted_key)
        except Exception as e:
            logger.error(f"Failed to decrypt vault key for {provider_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to decrypt your stored API key. Please re-enter it in the Vault."
            )
    else:
        # Fallback to system env keys if configured
        if provider_name == "gemini" and settings.GEMINI_API_KEY:
            api_key = settings.GEMINI_API_KEY
        elif provider_name in ("openai", "gpt") and settings.OPENAI_API_KEY:
            api_key = settings.OPENAI_API_KEY

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API key found for provider '{agent.llm_provider}'. Please store your key in the API Key Vault."
        )

    # 3. Retrieve or create session
    session: Optional[CallSession] = None
    if chat_in.session_id:
        sess_result = await db.execute(
            select(CallSession).where(
                CallSession.id == chat_in.session_id,
                CallSession.agent_id == agent.id,
                CallSession.user_id == current_user.id
            )
        )
        session = sess_result.scalar_one_or_none()

    if not session:
        session = CallSession(
            agent_id=agent.id,
            user_id=current_user.id,
            status="active"
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

    session_id = session.id

    # 4. Fetch prior messages in session
    msg_result = await db.execute(
        select(ConversationMessage).where(
            ConversationMessage.session_id == session_id
        ).order_by(ConversationMessage.created_at.asc())
    )
    existing_messages = msg_result.scalars().all()

    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in existing_messages
    ]

    # Save user message
    user_msg_record = ConversationMessage(
        session_id=session_id,
        role="user",
        content=chat_in.message.strip()
    )
    db.add(user_msg_record)
    await db.commit()

    conversation_history.append({"role": "user", "content": chat_in.message.strip()})

    # 5. Initialize provider & context manager
    try:
        llm = get_llm_provider(provider_name, api_key)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to initialize provider '{provider_name}': {str(e)}"
        )

    context_manager = ConversationContextManager()
    prepared_messages = await context_manager.prepare_context(
        messages=conversation_history,
        llm_provider=llm,
        model=agent.llm_model
    )

    # 6. Stream SSE generator
    agent_tools_list = list(getattr(agent, "tools", []) or [])
    tools_by_name = {t.name: t for t in agent_tools_list}
    tool_decls = []
    for t in agent_tools_list:
        try:
            params = json.loads(t.parameters_schema or "{}")
        except json.JSONDecodeError:
            params = {"type": "object", "properties": {}}
        tool_decls.append({"name": t.name, "description": t.description, "parameters": params})

    async def event_generator():
        start_time = time.time()
        first_token_time: Optional[float] = None
        collected_tokens = []
        executed_tool_calls = []
        executed_tool_results = []

        try:
            working_messages = list(prepared_messages)
            final_text_from_tool_turn: Optional[str] = None

            if tool_decls:
                for _ in range(3):
                    turn_res = await llm.generate_with_tools(
                        messages=working_messages,
                        tools=tool_decls,
                        system_prompt=agent.system_prompt,
                        temperature=agent.temperature,
                        model=agent.llm_model,
                    )
                    if not turn_res.tool_calls:
                        final_text_from_tool_turn = turn_res.text
                        break

                    working_messages.append({
                        "role": "assistant",
                        "content": turn_res.text or "",
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in turn_res.tool_calls
                        ],
                    })

                    for tc in turn_res.tool_calls:
                        tool_obj = tools_by_name.get(tc.name)
                        if not tool_obj:
                            res_payload = {"error": f"Unknown tool '{tc.name}'"}
                            dur_ms = 0.0
                        elif tool_obj.is_sensitive:
                            res_payload = {
                                "error": f"Tool '{tc.name}' is marked sensitive and requires voice confirmation."
                            }
                            dur_ms = 0.0
                        else:
                            try:
                                res_payload, dur_ms = await execute_tool(tool_obj, tc.arguments)
                            except (ToolValidationError, SSRFBlockedError) as exc:
                                res_payload = {"error": str(exc)}
                                dur_ms = 0.0
                            except Exception as exc:
                                res_payload = {"error": f"Tool execution error: {exc}"}
                                dur_ms = 0.0

                        executed_tool_calls.append({"name": tc.name, "arguments": tc.arguments})
                        executed_tool_results.append({"name": tc.name, "result": res_payload, "duration_ms": dur_ms})
                        yield f"event: tool_call\ndata: {json.dumps({'name': tc.name, 'arguments': tc.arguments, 'result': res_payload, 'duration_ms': dur_ms})}\n\n"
                        working_messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": res_payload})

            if final_text_from_tool_turn is not None:
                first_token_time = time.time()
                ft_latency = (first_token_time - start_time) * 1000.0
                yield f"event: first_token\ndata: {json.dumps({'type': 'first_token', 'latency_ms': round(ft_latency, 1)})}\n\n"
                collected_tokens.append(final_text_from_tool_turn)
                yield f"event: token\ndata: {json.dumps({'token': final_text_from_tool_turn})}\n\n"
            else:
                stream_msgs = [
                    {"role": m["role"], "content": json.dumps(m["content"]) if isinstance(m.get("content"), dict) else str(m.get("content", ""))}
                    for m in working_messages
                    if m.get("role") in ("user", "assistant", "system")
                ]
                async for token in llm.generate_stream(
                    messages=stream_msgs,
                    system_prompt=agent.system_prompt,
                    temperature=agent.temperature,
                    model=agent.llm_model
                ):
                    if first_token_time is None:
                        first_token_time = time.time()
                        ft_latency = (first_token_time - start_time) * 1000.0
                        meta_event = {
                            "type": "first_token",
                            "latency_ms": round(ft_latency, 1)
                        }
                        yield f"event: first_token\ndata: {json.dumps(meta_event)}\n\n"

                    collected_tokens.append(token)
                    token_event = {"token": token}
                    yield f"event: token\ndata: {json.dumps(token_event)}\n\n"

            end_time = time.time()
            total_latency = (end_time - start_time) * 1000.0
            ft_latency = ((first_token_time - start_time) * 1000.0) if first_token_time else total_latency
            full_response = "".join(collected_tokens)

            # Persist assistant turn to DB in a new session block
            async with AsyncSession(db.bind) as save_db:
                asst_msg = ConversationMessage(
                    session_id=session_id,
                    role="assistant",
                    content=full_response,
                    llm_latency_ms=round(total_latency, 2),
                    tool_calls_json=json.dumps(executed_tool_calls) if executed_tool_calls else None,
                    tool_results_json=json.dumps(executed_tool_results) if executed_tool_results else None,
                )
                save_db.add(asst_msg)

                # Update session stats
                sess_record = await save_db.get(CallSession, session_id)
                if sess_record:
                    sess_record.total_turns += 1
                    sess_record.avg_latency_ms = round(
                        (sess_record.avg_latency_ms * (sess_record.total_turns - 1) + total_latency) / sess_record.total_turns,
                        2
                    )
                await save_db.commit()

            done_event = {
                "session_id": session_id,
                "first_token_latency_ms": round(ft_latency, 1),
                "total_latency_ms": round(total_latency, 1),
                "content": full_response
            }
            yield f"event: done\ndata: {json.dumps(done_event)}\n\n"

        except LLMAuthenticationError as e:
            err_data = {"error": str(e), "code": "AUTH_ERROR"}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
        except LLMRateLimitError as e:
            err_data = {"error": str(e), "code": "RATE_LIMIT"}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
        except LLMTimeoutError as e:
            err_data = {"error": str(e), "code": "TIMEOUT"}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
        except Exception as e:
            logger.error(f"Streaming chat error: {e}")
            err_data = {"error": f"LLM error: {str(e)}", "code": "PROVIDER_ERROR"}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
