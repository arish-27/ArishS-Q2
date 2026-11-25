import pytest
import urllib.request
import json
import uuid

def http_request(url, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            content = response.read().decode("utf-8")
            return response.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {"detail": err_body}

def test_agent_crud_and_user_isolation(server):
    # Register User A
    email_a = f"usera_{uuid.uuid4().hex[:8]}@example.com"
    _, res_a = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email_a,
        "password": "Password123!",
        "full_name": "User Alpha"
    })
    token_a = res_a["access_token"]

    # Register User B
    email_b = f"userb_{uuid.uuid4().hex[:8]}@example.com"
    _, res_b = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email_b,
        "password": "Password123!",
        "full_name": "User Beta"
    })
    token_b = res_b["access_token"]

    # 1. User A creates an agent
    create_payload = {
        "name": "Customer Support Agent",
        "description": "Handles inbound tier 1 support",
        "personality": "empathetic, concise, professional",
        "system_prompt": "You are a friendly support assistant for ACME Corp.",
        "llm_provider": "gemini",
        "llm_model": "gemini-4-hydrogen",
        "temperature": 0.5,
        "stt_provider": "faster-whisper",
        "stt_language": "en",
        "tts_provider": "edge-tts",
        "tts_voice": "en-US-GuyNeural"
    }
    status_create, agent_a = http_request(
        f"{server}/api/v1/agents",
        method="POST",
        data=create_payload,
        token=token_a
    )
    assert status_create == 201
    agent_id = agent_a["id"]
    slug = agent_a["slug"]
    assert agent_a["name"] == "Customer Support Agent"
    assert slug == "customer-support-agent"
    assert agent_a["is_published"] is False

    # 2. User A reads the agent
    status_get, agent_get = http_request(f"{server}/api/v1/agents/{agent_id}", method="GET", token=token_a)
    assert status_get == 200
    assert agent_get["id"] == agent_id

    # 3. User A updates the agent
    status_update, agent_updated = http_request(
        f"{server}/api/v1/agents/{agent_id}",
        method="PUT",
        data={"temperature": 0.2, "tts_voice": "en-US-JennyNeural"},
        token=token_a
    )
    assert status_update == 200
    assert agent_updated["temperature"] == 0.2
    assert agent_updated["tts_voice"] == "en-US-JennyNeural"

    # 4. User A publishes the agent
    status_pub, agent_pub = http_request(
        f"{server}/api/v1/agents/{agent_id}/publish",
        method="POST",
        data={"is_published": True, "slug": "acme-support"},
        token=token_a
    )
    assert status_pub == 200
    assert agent_pub["is_published"] is True
    assert agent_pub["slug"] == "acme-support"

    # 5. Public lookup without token
    status_public, public_agent = http_request(f"{server}/api/v1/agents/public/acme-support", method="GET")
    assert status_public == 200
    assert public_agent["name"] == "Customer Support Agent"
    assert "system_prompt" not in public_agent  # Sensitive prompt must not leak in public metadata

    # ==============================================================================
    # CRITICAL TENANT ISOLATION TESTS: User B cannot access User A's Agent
    # ==============================================================================

    # User B list agents -> must be empty
    status_b_list, list_b = http_request(f"{server}/api/v1/agents", method="GET", token=token_b)
    assert status_b_list == 200
    assert len(list_b) == 0

    # User B tries to GET User A's agent -> rejected 404
    status_b_get, _ = http_request(f"{server}/api/v1/agents/{agent_id}", method="GET", token=token_b)
    assert status_b_get == 404

    # User B tries to UPDATE User A's agent -> rejected 404
    status_b_put, _ = http_request(
        f"{server}/api/v1/agents/{agent_id}",
        method="PUT",
        data={"name": "Hacked Name"},
        token=token_b
    )
    assert status_b_put == 404

    # User B tries to DELETE User A's agent -> rejected 404
    status_b_del, _ = http_request(f"{server}/api/v1/agents/{agent_id}", method="DELETE", token=token_b)
    assert status_b_del == 404

    # User B tries to PUBLISH/UNPUBLISH User A's agent -> rejected 404
    status_b_pub, _ = http_request(
        f"{server}/api/v1/agents/{agent_id}/publish",
        method="POST",
        data={"is_published": False},
        token=token_b
    )
    assert status_b_pub == 404

    # 6. User A deletes their agent
    status_del, _ = http_request(f"{server}/api/v1/agents/{agent_id}", method="DELETE", token=token_a)
    assert status_del == 204

    # Confirm agent is deleted
    status_gone, _ = http_request(f"{server}/api/v1/agents/{agent_id}", method="GET", token=token_a)
    assert status_gone == 404
