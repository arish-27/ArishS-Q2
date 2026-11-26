import uuid
import pytest
from app.models.agent import Agent
from app.models.session import CallSession, ConversationMessage
from tests.test_voice_pipeline import http_request


def test_analytics_overview_sessions_detail_and_isolation(server):
    email_a = f"ana_{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"anb_{uuid.uuid4().hex[:8]}@example.com"
    _, reg_a = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email_a, "password": "Password123!"})
    _, reg_b = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email_b, "password": "Password123!"})
    token_a, token_b = reg_a["access_token"], reg_b["access_token"]

    _, agent_a = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "Analytics Bot",
        "llm_provider": "gemini",
        "llm_model": "gemini-3.5-flash-lite",
    }, token=token_a)
    agent_id = agent_a["id"]

    # Create a chat session via API so CallSession + ConversationMessage exist
    from tests.test_chat_llm import MockStreamingLLM
    from unittest.mock import patch

    _, _ = http_request(f"{server}/api/v1/auth/secrets", method="POST", data={"provider": "gemini", "api_key": "AIzaSyFakeKey"}, token=token_a)
    with patch("app.api.v1.chat.get_llm_provider", return_value=MockStreamingLLM("mock")):
        import urllib.request, json
        req = urllib.request.Request(
            f"{server}/api/v1/chat/{agent_id}",
            data=json.dumps({"message": "Hi analytics"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token_a}"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            _ = resp.read()

    # User A overview & sessions
    st_ov, ov = http_request(f"{server}/api/v1/analytics/overview", token=token_a)
    assert st_ov == 200
    assert ov["total_sessions"] >= 1
    assert len(ov["sessions_per_day"]) == 14
    assert len(ov["top_agents"]) >= 1

    st_sess, sessions = http_request(f"{server}/api/v1/analytics/sessions?agent_id={agent_id}", token=token_a)
    assert st_sess == 200
    assert len(sessions) >= 1
    sess_id = sessions[0]["id"]

    st_det, det = http_request(f"{server}/api/v1/analytics/sessions/{sess_id}", token=token_a)
    assert st_det == 200
    assert len(det["messages"]) >= 2

    # User B cannot see User A's sessions or detail
    st_ov_b, ov_b = http_request(f"{server}/api/v1/analytics/overview", token=token_b)
    assert st_ov_b == 200
    assert ov_b["total_sessions"] == 0
    st_det_b, _ = http_request(f"{server}/api/v1/analytics/sessions/{sess_id}", token=token_b)
    assert st_det_b == 404
