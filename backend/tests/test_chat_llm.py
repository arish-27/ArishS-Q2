import pytest
import urllib.request
import json
import uuid
import asyncio
from unittest.mock import patch, MagicMock
from app.providers.llm.base import BaseLLMProvider, LLMAuthenticationError
from app.providers.llm import get_llm_provider
from app.services.context_manager import ConversationContextManager, calculate_history_tokens

def http_request(url, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            content = response.read().decode("utf-8")
            return response.status, response.headers, content
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, e.headers, json.loads(err_body)
        except Exception:
            return e.code, e.headers, {"detail": err_body}

# ==============================================================================
# 1. Mocked LLM Provider Streaming Tests
# ==============================================================================

class MockStreamingLLM(BaseLLMProvider):
    async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
        tokens = ["Hello", "!", " How", " can", " I", " assist", " you", " today", "?"]
        for t in tokens:
            await asyncio.sleep(0.01)
            yield t

@pytest.mark.anyio
async def test_mocked_llm_provider_streaming():
    provider = MockStreamingLLM(api_key="mock-key-12345")
    tokens = []
    async for token in provider.generate_stream(messages=[{"role": "user", "content": "Hi"}]):
        tokens.append(token)
    assert "".join(tokens) == "Hello! How can I assist you today?"

    # Test full generate accumulation
    full = await provider.generate(messages=[{"role": "user", "content": "Hi"}])
    assert full == "Hello! How can I assist you today?"

def test_provider_factory_validation():
    # Unsupported provider
    with pytest.raises(Exception):
        get_llm_provider("anthropic", "some-key")

    # Missing API key
    with pytest.raises(LLMAuthenticationError):
        get_llm_provider("gemini", "")

# ==============================================================================
# 2. Conversation Context Manager Trimming & Summarization Tests
# ==============================================================================

@pytest.mark.anyio
async def test_context_manager_trimming_and_summarization():
    mgr = ConversationContextManager(max_turns=4, token_budget=100)

    # Short dialogue (3 turns) - within max_turns and budget
    short_history = [
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What is the weather?"}
    ]
    prepared = await mgr.prepare_context(short_history)
    assert len(prepared) == 3
    assert prepared == short_history

    # Long dialogue (10 turns) - exceeds max_turns (4)
    long_history = [
        {"role": "user", "content": f"Turn {i} question about topic {i}"} if i % 2 == 1
        else {"role": "assistant", "content": f"Turn {i} detailed answer explaining topic {i}"}
        for i in range(1, 11)
    ]
    assert len(long_history) == 10

    prepared_long = await mgr.prepare_context(long_history)
    # Must have summarized older turns into a system summary + kept recent turns
    assert len(prepared_long) <= 5
    assert prepared_long[0]["role"] == "system"
    assert "Earlier conversation summary" in prepared_long[0]["content"]

    # Recent turns must be preserved at the end
    assert prepared_long[-1]["content"] == "Turn 10 detailed answer explaining topic 10"

# ==============================================================================
# 3. Chat Endpoint: Streaming, Vault Key Usage & Tenant Isolation
# ==============================================================================

def test_chat_endpoint_streaming_and_isolation(server):
    # Register User A
    email_a = f"chata_{uuid.uuid4().hex[:8]}@example.com"
    _, _, res_a_raw = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email_a,
        "password": "Password123!"
    })
    token_a = json.loads(res_a_raw)["access_token"]

    # Register User B
    email_b = f"chatb_{uuid.uuid4().hex[:8]}@example.com"
    _, _, res_b_raw = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email_b,
        "password": "Password123!"
    })
    token_b = json.loads(res_b_raw)["access_token"]

    # User A creates an agent
    _, _, agent_raw = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "Chatbot Alpha",
        "system_prompt": "You are a concise AI.",
        "llm_provider": "gemini",
        "llm_model": "gemini-2.5-flash"
    }, token=token_a)
    agent_a = json.loads(agent_raw)
    agent_id = agent_a["id"]

    # Case A: Chat without API key in vault -> clear 400 Bad Request
    status_nokey, _, res_nokey = http_request(
        f"{server}/api/v1/chat/{agent_id}",
        method="POST",
        data={"message": "Hello without key"},
        token=token_a
    )
    assert status_nokey == 400
    assert "No API key found" in res_nokey["detail"]

    # User A stores encrypted Gemini key in vault
    status_vault, _, _ = http_request(
        f"{server}/api/v1/auth/secrets",
        method="POST",
        data={"provider": "gemini", "api_key": "AIzaSyFakeKeyForTesting1234567890"},
        token=token_a
    )
    assert status_vault == 200

    # Case B: Chat with mocked streaming provider
    with patch("app.api.v1.chat.get_llm_provider", return_value=MockStreamingLLM(api_key="valid-mock-key")):
        status_chat, headers, stream_body = http_request(
            f"{server}/api/v1/chat/{agent_id}",
            method="POST",
            data={"message": "Tell me a greeting"},
            token=token_a
        )
        assert status_chat == 200
        assert "text/event-stream" in headers.get("Content-Type", "")
        assert "event: first_token" in stream_body
        assert "event: token" in stream_body
        assert "event: done" in stream_body
        assert "Hello!" in stream_body

    # Case C: Tenant Isolation - User B attempts to chat with User A's agent -> 404
    status_iso, _, res_iso = http_request(
        f"{server}/api/v1/chat/{agent_id}",
        method="POST",
        data={"message": "Hacking conversation"},
        token=token_b
    )
    assert status_iso == 404
    assert "Agent not found" in res_iso["detail"]
