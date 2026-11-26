import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import websockets
from websockets.exceptions import InvalidStatus

from app.core.config import settings
from app.providers.llm.base import BaseLLMProvider
from app.providers.stt.base import BaseSTTProvider, STTResult
from app.providers.tts.base import BaseTTSProvider
from app.services.rate_limiter import rate_limiter
from tests.test_voice_pipeline import http_request


def test_public_agent_rejects_unpublished_and_never_leaks_api_key(server):
    email = f"pub_{uuid.uuid4().hex[:8]}@example.com"
    _, reg = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email, "password": "Password123!"})
    token = reg["access_token"]

    secret_key = "AIzaSySecretKeyShouldNeverAppearInPublicFrames999"
    st_sec, _ = http_request(f"{server}/api/v1/auth/secrets", method="POST", data={
        "provider": "gemini",
        "api_key": secret_key,
    }, token=token)
    assert st_sec == 200

    slug = f"public-bot-{uuid.uuid4().hex[:6]}"
    _, agent = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "Public Bot",
        "slug": slug,
        "llm_provider": "gemini",
        "llm_model": "gemini-3.5-flash-lite",
    }, token=token)
    agent_id = agent["id"]

    # Unpublished agent must be rejected on both HTTP & WebSocket
    st_pub_404, body_404 = http_request(f"{server}/api/v1/agents/public/{slug}")
    assert st_pub_404 == 404
    assert secret_key not in json.dumps(body_404)

    ws_base = server.replace("http://", "ws://")

    async def check_unpublished_ws():
        with pytest.raises((InvalidStatus, websockets.exceptions.ConnectionClosed)):
            async with websockets.connect(f"{ws_base}/api/v1/voice/public/{slug}"):
                pass

    asyncio.run(check_unpublished_ws())

    # Publish the agent
    st_pub, pub_res = http_request(f"{server}/api/v1/agents/{agent_id}/publish", method="POST", data={"is_published": True}, token=token)
    assert st_pub == 200
    assert secret_key not in json.dumps(pub_res)

    st_get, get_res = http_request(f"{server}/api/v1/agents/public/{slug}")
    assert st_get == 200
    assert secret_key not in json.dumps(get_res)

    class _MockLLM(BaseLLMProvider):
        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            yield "Hi!"

    class _MockSTT(BaseSTTProvider):
        async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en"):
            return STTResult(text="Hello", language="en", duration_ms=500.0, latency_ms=10.0)

    class _MockTTS(BaseTTSProvider):
        async def synthesize_stream(self, text: str, voice: str = "", cancel_event=None):
            yield b"ID3-PUB"

    async def check_published_ws():
        with (
            patch("app.api.v1.voice.get_llm_provider", return_value=_MockLLM("mock")),
            patch("app.api.v1.voice.get_stt_provider", return_value=_MockSTT()),
            patch("app.api.v1.voice.get_tts_provider", return_value=_MockTTS()),
        ):
            async with websockets.connect(f"{ws_base}/api/v1/voice/public/{slug}") as ws:
                ready_raw = await ws.recv()
                assert secret_key not in ready_raw
                ready = json.loads(ready_raw)
                assert ready["type"] == "session_ready"
                assert ready["public"] is True

    asyncio.run(check_published_ws())


def test_public_ws_rate_limit_enforced(server):
    email = f"pubrl_{uuid.uuid4().hex[:8]}@example.com"
    _, reg = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email, "password": "Password123!"})
    token = reg["access_token"]
    slug = f"rl-bot-{uuid.uuid4().hex[:6]}"
    _, agent = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "RateLimit Bot",
        "slug": slug,
        "llm_provider": "gemini",
        "llm_model": "gemini-3.5-flash-lite",
    }, token=token)
    http_request(f"{server}/api/v1/agents/{agent['id']}/publish", method="POST", data={"is_published": True}, token=token)

    ws_base = server.replace("http://", "ws://")

    async def check_rl():
        with patch.object(rate_limiter, "check_limit", new=AsyncMock(return_value=(False, 0, "memory"))):
            with pytest.raises((InvalidStatus, websockets.exceptions.ConnectionClosed)):
                async with websockets.connect(f"{ws_base}/api/v1/voice/public/{slug}"):
                    pass

    asyncio.run(check_rl())
