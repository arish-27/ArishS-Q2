import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models.agent import Agent
from app.models.tool import Tool
from app.providers.llm.base import BaseLLMProvider, ToolCallRequest, ToolTurnResult
from app.providers.stt.base import BaseSTTProvider, STTResult
from app.providers.tts.base import BaseTTSProvider
from app.services.tool_executor import (
    SSRFBlockedError,
    ToolValidationError,
    execute_tool,
    validate_tool_arguments,
    validate_webhook_url_ssrf,
)
from app.services.voice_orchestrator import VoiceOrchestrator, VoiceState
from app.vad.detector import StreamingVAD
from tests.test_voice_pipeline import http_request


def test_tool_schema_validation():
    schema = json.dumps({
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            "days": {"type": "integer"},
        },
        "required": ["location"],
    })
    assert validate_tool_arguments(schema, {"location": "Bengaluru", "unit": "celsius"})["location"] == "Bengaluru"

    with pytest.raises(ToolValidationError, match="Missing required"):
        validate_tool_arguments(schema, {"unit": "celsius"})

    with pytest.raises(ToolValidationError, match="must be a string"):
        validate_tool_arguments(schema, {"location": 123})

    with pytest.raises(ToolValidationError, match="must be one of"):
        validate_tool_arguments(schema, {"location": "Delhi", "unit": "kelvin"})


@pytest.mark.parametrize(
    "blocked_url",
    [
        "http://localhost:8000/hook",
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.10/api",
        "file:///etc/passwd",
    ],
)
def test_webhook_ssrf_blocks_private_and_loopback_urls(blocked_url):
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url_ssrf(blocked_url)


def test_webhook_ssrf_blocks_dns_resolving_to_loopback():
    with patch("app.services.tool_executor.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
        with pytest.raises(SSRFBlockedError, match="127.0.0.1"):
            validate_webhook_url_ssrf("https://evil.example.com/hook")


def test_tools_crud_and_user_isolation(server):
    email_a = f"toola_{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"toolb_{uuid.uuid4().hex[:8]}@example.com"
    _, reg_a = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email_a, "password": "Password123!"})
    _, reg_b = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email_b, "password": "Password123!"})
    token_a, token_b = reg_a["access_token"], reg_b["access_token"]

    st_create, tool_a = http_request(f"{server}/api/v1/tools", method="POST", data={
        "name": "get_weather",
        "description": "Weather lookup",
        "execution_type": "built_in",
        "is_sensitive": False,
        "parameters_schema": json.dumps({"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}),
    }, token=token_a)
    assert st_create == 201
    tool_id = tool_a["id"]

    # SSRF URL rejected at API level
    st_ssrf, _ = http_request(f"{server}/api/v1/tools", method="POST", data={
        "name": "bad_hook",
        "description": "SSRF attempt",
        "execution_type": "webhook",
        "webhook_url": "http://169.254.169.254/latest/meta-data/",
    }, token=token_a)
    assert st_ssrf == 400

    # User B cannot see, update, or delete User A's tool
    _, list_b = http_request(f"{server}/api/v1/tools", method="GET", token=token_b)
    assert not any(t["id"] == tool_id for t in list_b)
    st_upd_b, _ = http_request(f"{server}/api/v1/tools/{tool_id}", method="PUT", data={"description": "hacked"}, token=token_b)
    st_del_b, _ = http_request(f"{server}/api/v1/tools/{tool_id}", method="DELETE", token=token_b)
    assert st_upd_b == 404
    assert st_del_b == 404


class _MockSTT(BaseSTTProvider):
    def __init__(self, text="Check weather"):
        self._text = text

    async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en") -> STTResult:
        return STTResult(text=self._text, language="en", duration_ms=500.0, latency_ms=10.0)


class _MockTTS(BaseTTSProvider):
    async def synthesize_stream(self, text: str, voice: str = "", cancel_event=None):
        yield b"ID3-AUDIO"


@pytest.mark.anyio
async def test_mocked_llm_tool_call_round_trip():
    class ToolCallingLLM(BaseLLMProvider):
        def __init__(self, api_key: str):
            super().__init__(api_key)
            self.round = 0

        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            yield "Done."

        async def generate_with_tools(self, messages, tools, system_prompt="", temperature=0.7, model=""):
            self.round += 1
            if self.round == 1:
                return ToolTurnResult(tool_calls=[ToolCallRequest(id="c1", name="get_weather", arguments={"location": "Bengaluru"})])
            return ToolTurnResult(text="It is 26 degrees Celsius in Bengaluru.")

    weather_tool = Tool(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="get_weather",
        description="Get weather",
        parameters_schema=json.dumps({"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}),
        is_sensitive=False,
        execution_type="built_in",
    )
    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=weather_tool.user_id,
        name="WeatherAgent",
        slug="weatheragent",
        system_prompt="Be concise.",
        tools=[weather_tool],
    )
    events = []
    orch = VoiceOrchestrator(
        agent=agent,
        session_id=str(uuid.uuid4()),
        llm_provider=ToolCallingLLM(api_key="mock"),
        stt_provider=_MockSTT("What is the weather in Bengaluru?"),
        tts_provider=_MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=AsyncMock(side_effect=lambda d: events.append(d)),
        send_bytes=AsyncMock(),
    )
    orch._persist_turn = AsyncMock()
    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test")
    await orch._execute_turn(b"\x01\x00" * 4000, 250.0)

    assert any(ev.get("type") == "tool_call" and ev.get("name") == "get_weather" for ev in events)
    assert any(ev.get("type") == "transcript" and ev.get("role") == "assistant" and "26 degrees" in ev.get("text", "") for ev in events)
    assert orch._persist_turn.await_args.kwargs["tool_calls"][0]["name"] == "get_weather"


@pytest.mark.anyio
async def test_sensitive_tool_confirm_cancel_and_timeout():
    class SensitiveLLM(BaseLLMProvider):
        def __init__(self, api_key: str):
            super().__init__(api_key)
            self.round = 0

        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            yield "Okay."

        async def generate_with_tools(self, messages, tools, system_prompt="", temperature=0.7, model=""):
            self.round += 1
            if self.round == 1:
                return ToolTurnResult(tool_calls=[ToolCallRequest(id="c1", name="send_email", arguments={"to": "a@b.com", "subject": "Hi", "body": "Test"})])
            last_tool = [m for m in messages if m.get("role") == "tool"][-1]["content"]
            return ToolTurnResult(text=f"Result: {json.dumps(last_tool)}")

    email_tool = Tool(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="send_email",
        description="Send email",
        parameters_schema=json.dumps({"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}),
        is_sensitive=True,
        execution_type="built_in",
    )
    agent = Agent(id=str(uuid.uuid4()), user_id=email_tool.user_id, name="MailBot", slug="mailbot", system_prompt="Help.", tools=[email_tool])

    # 1. Confirm
    events_ok = []
    orch_ok = VoiceOrchestrator(
        agent=agent, session_id=str(uuid.uuid4()), llm_provider=SensitiveLLM("k"), stt_provider=_MockSTT(), tts_provider=_MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=AsyncMock(side_effect=lambda d: events_ok.append(d) or (orch_ok.resolve_tool_confirmation(d["confirm_id"], True) if d.get("type") == "tool_confirm" else None)),
        send_bytes=AsyncMock(),
    )
    orch_ok._persist_turn = AsyncMock()
    await orch_ok.start_listening()
    await orch_ok.transition(VoiceState.THINKING, reason="test")
    await orch_ok._execute_turn(b"\x01\x00" * 4000, 250.0)
    assert any(ev.get("type") == "tool_call" and ev["result"].get("status") == "sent" for ev in events_ok)

    # 2. Cancel
    events_no = []
    orch_no = VoiceOrchestrator(
        agent=agent, session_id=str(uuid.uuid4()), llm_provider=SensitiveLLM("k"), stt_provider=_MockSTT(), tts_provider=_MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=AsyncMock(side_effect=lambda d: events_no.append(d) or (orch_no.resolve_tool_confirmation(d["confirm_id"], False) if d.get("type") == "tool_confirm" else None)),
        send_bytes=AsyncMock(),
    )
    orch_no._persist_turn = AsyncMock()
    await orch_no.start_listening()
    await orch_no.transition(VoiceState.THINKING, reason="test")
    await orch_no._execute_turn(b"\x01\x00" * 4000, 250.0)
    assert any(ev.get("type") == "tool_call" and ev["result"].get("declined") is True for ev in events_no)

    # 3. Timeout
    events_to = []
    orch_to = VoiceOrchestrator(
        agent=agent, session_id=str(uuid.uuid4()), llm_provider=SensitiveLLM("k"), stt_provider=_MockSTT(), tts_provider=_MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=AsyncMock(side_effect=lambda d: events_to.append(d)),
        send_bytes=AsyncMock(),
    )
    orch_to._persist_turn = AsyncMock()
    await orch_to.start_listening()
    await orch_to.transition(VoiceState.THINKING, reason="test")
    with patch.object(settings, "TOOL_CONFIRM_TIMEOUT_S", 0.05):
        await orch_to._execute_turn(b"\x01\x00" * 4000, 250.0)
    assert any(ev.get("type") == "tool_call" and "timed out" in ev["result"].get("error", "") for ev in events_to)
