import asyncio
import json
import math
import urllib.request
import uuid
from typing import AsyncIterator, List
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.core.config import settings
from app.models.agent import Agent
from app.providers.embeddings.gemini_embedding import GeminiEmbeddingProvider
from app.providers.llm.base import BaseLLMProvider, LLMServiceUnavailableError
from app.providers.stt.base import BaseSTTProvider, STTResult
from app.providers.tts.base import BaseTTSProvider
from app.services.rate_limiter import RateLimiter
from app.services.sentence_splitter import StreamingSentenceSplitter
from app.services.voice_orchestrator import InvalidStateTransition, VoiceOrchestrator, VoiceState
from app.vad.detector import StreamingVAD


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


def _generate_synthetic_speech_pcm16(duration_s: float = 1.5, sample_rate: int = 16000) -> bytes:
    """Generates an offline glottal + formant-modulated 16kHz PCM16 speech-like waveform."""
    t = np.linspace(0, duration_s, int(duration_s * sample_rate), endpoint=False)
    f0 = 130.0 + 25.0 * np.sin(2 * np.pi * 3.0 * t)
    phase = np.cumsum(2 * np.pi * f0 / sample_rate)
    glottal = (
        np.tanh(3.0 * np.sin(phase))
        + 0.5 * np.sin(2 * phase)
        + 0.35 * np.sin(3 * phase)
        + 0.25 * np.sin(5 * phase)
        + 0.2 * np.sin(8 * phase)
    )
    f1 = 500.0 + 300.0 * np.sin(2 * np.pi * 5.0 * t)
    f2 = 1500.0 + 500.0 * np.cos(2 * np.pi * 4.0 * t)
    formants = 0.5 * np.sin(np.cumsum(2 * np.pi * f1 / sample_rate)) + 0.3 * np.sin(
        np.cumsum(2 * np.pi * f2 / sample_rate)
    )
    env = np.clip(np.sin(2 * np.pi * 3.5 * t) + 0.65, 0.25, 1.0)
    sig = env * (0.6 * glottal + 0.4 * formants)
    return (np.clip(sig, -1.0, 1.0) * 18000).astype(np.int16).tobytes()


class MockSTT(BaseSTTProvider):
    def __init__(self, transcript: str = "Hello, can you help me?"):
        self.transcript = transcript

    async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en") -> STTResult:
        await asyncio.sleep(0.01)
        return STTResult(text=self.transcript, language=language, duration_ms=1000.0, latency_ms=18.5)


class MockLLM(BaseLLMProvider):
    async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
        tokens = ["Sure", "! ", "I can", " help", " you", " with that. ", "What do ", "you need?"]
        for t in tokens:
            await asyncio.sleep(0.005)
            yield t


class MockTTS(BaseTTSProvider):
    async def synthesize_stream(self, text: str, voice: str = "", cancel_event=None) -> AsyncIterator[bytes]:
        await asyncio.sleep(0.005)
        if cancel_event and cancel_event.is_set():
            return
        yield b"ID3-MOCK-MP3-CHUNK-1-" + text[:8].encode("utf-8")
        yield b"MOCK-MP3-CHUNK-2"


# ==============================================================================
# 1. Active Model Catalog & Gemini Embedding 001 (768-dim)
# ==============================================================================

def test_retired_models_rejected_and_active_catalog(server):
    email = f"catalog_{uuid.uuid4().hex[:8]}@example.com"
    _, reg = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email,
        "password": "Password123!",
    })
    token = reg["access_token"]

    # Retired Gemini 1.5 & OpenAI o1-mini must be rejected
    st1, _ = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "Legacy Bot",
        "llm_provider": "gemini",
        "llm_model": "gemini-1.5-flash",
    }, token=token)
    assert st1 == 422

    st2, _ = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "Legacy OpenAI Bot",
        "llm_provider": "openai",
        "llm_model": "o1-mini",
    }, token=token)
    assert st2 == 422

    # Active catalog endpoint check
    st_cat, cat = http_request(f"{server}/api/v1/agents/catalog/models")
    assert st_cat == 200
    assert "gemini-4-hydrogen" in cat["llm"]["gemini"]
    assert "gpt-6-luna" in cat["llm"]["openai"]
    assert "gemini-1.5-flash" not in cat["llm"]["gemini"]
    assert "o1-mini" not in cat["llm"]["openai"]
    assert cat["embedding"]["model"] == "gemini-embedding-001"
    assert cat["embedding"]["dimensions"] == 768


@pytest.mark.anyio
async def test_gemini_embedding_001_768_dim_normalization():
    raw_vec = [float(i + 1) for i in range(768)]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embedding": {"values": raw_vec}}

    with patch("app.providers.embeddings.gemini_embedding.httpx.AsyncClient") as client_cls:
        client_inst = client_cls.return_value.__aenter__.return_value
        client_inst.post = AsyncMock(return_value=mock_resp)

        emb = GeminiEmbeddingProvider(api_key="test-gemini-key")
        vec = await emb.embed_text("Voice RAG query check", task_type="RETRIEVAL_QUERY")

        assert len(vec) == 768
        # Verify unit L2 normalization
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

        call_kwargs = client_inst.post.call_args
        assert "gemini-embedding-001:embedContent" in call_kwargs.args[0]
        assert call_kwargs.kwargs["json"]["outputDimensionality"] == 768


# ==============================================================================
# 2. Server-side VAD with Synthetic Audio
# ==============================================================================

@pytest.mark.parametrize("vad_backend", ["silero-onnx", "webrtcvad"])
def test_vad_with_synthetic_audio(vad_backend):
    vad = StreamingVAD(
        sample_rate=16000,
        silence_threshold_ms=350,
        speech_threshold=0.5,
        min_speech_ms=100,
        backend=vad_backend,
    )

    pure_silence = np.zeros(16000, dtype=np.int16).tobytes()
    silence_events = vad.process_chunk(pure_silence)
    assert all(not ev.speech_start and ev.utterance_pcm16 is None for ev in silence_events)

    speech_pcm = _generate_synthetic_speech_pcm16(duration_s=1.5, sample_rate=16000)
    speech_events = vad.process_chunk(speech_pcm)
    trailing_events = vad.process_chunk(pure_silence)
    all_events = speech_events + trailing_events

    assert any(ev.speech_start for ev in all_events), f"{vad_backend} should detect speech onset"
    utterances = [ev.utterance_pcm16 for ev in all_events if ev.utterance_pcm16 is not None]
    assert len(utterances) >= 1, f"{vad_backend} should emit completed utterance after silence"
    assert len(utterances[0]) > 3200


# ==============================================================================
# 3. Sentence Splitter & Voice Orchestrator State Machine
# ==============================================================================

def test_sentence_splitter():
    splitter = StreamingSentenceSplitter(min_sentence_chars=10)
    tokens = ["Hello Dr.", " Smith! ", "The value is 3.14 ", "today. **Awesome** news?", " Yes"]
    out: List[str] = []
    for t in tokens:
        out.extend(splitter.feed(t))
    out.extend(splitter.flush())

    assert len(out) == 4
    assert out[0] == "Hello Dr. Smith!"
    assert out[1] == "The value is 3.14 today."
    assert out[2] == "Awesome news?"
    assert out[3] == "Yes"


@pytest.mark.anyio
async def test_voice_orchestrator_state_machine_and_persistence():
    sent_json = []
    sent_bytes = []

    async def capture_json(data):
        sent_json.append(data)

    async def capture_bytes(chunk):
        sent_bytes.append(chunk)

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="State Machine Test Bot",
        slug=f"sm-bot-{uuid.uuid4().hex[:6]}",
        system_prompt="You are concise.",
        llm_provider="gemini",
        llm_model="gemini-4-hydrogen",
        temperature=0.5,
        stt_provider="faster-whisper",
        stt_language="en",
        tts_provider="edge-tts",
        tts_voice="en-US-GuyNeural",
    )

    vad = StreamingVAD(silence_threshold_ms=300, min_speech_ms=100, backend="webrtcvad")
    orch = VoiceOrchestrator(
        agent=agent,
        session_id="mock-session-id",
        llm_provider=MockLLM(api_key="mock-key"),
        stt_provider=MockSTT("How is the latency today?"),
        tts_provider=MockTTS(),
        vad=vad,
        send_json=capture_json,
        send_bytes=capture_bytes,
    )
    # Mock DB persistence cleanly so state-machine unit test is isolated
    orch._persist_turn = AsyncMock()

    assert orch.state == VoiceState.IDLE

    # Illegal transition IDLE -> SPEAKING must fail
    with pytest.raises(InvalidStateTransition):
        await orch.transition(VoiceState.SPEAKING, reason="illegal_jump")

    # IDLE -> LISTENING
    await orch.start_listening()
    assert orch.state == VoiceState.LISTENING

    # Trigger turn manually via force_end_utterance with synthetic speech
    speech_pcm = _generate_synthetic_speech_pcm16(duration_s=1.0)
    await orch.handle_audio_frame(speech_pcm)
    if orch.state == VoiceState.LISTENING:
        await orch.force_end_utterance()

    assert orch.state == VoiceState.THINKING
    assert orch._turn_task is not None
    await orch._turn_task

    # Returned to LISTENING after SPEAKING completed
    assert orch.state == VoiceState.LISTENING
    states_emitted = [m["state"] for m in sent_json if m.get("type") == "state"]
    assert states_emitted == ["LISTENING", "THINKING", "SPEAKING", "LISTENING"]
    assert len(sent_bytes) >= 2

    metrics_msgs = [m for m in sent_json if m.get("type") == "turn_metrics"]
    assert len(metrics_msgs) == 1
    assert metrics_msgs[0]["stt_latency_ms"] > 0
    assert metrics_msgs[0]["llm_first_token_ms"] > 0
    assert metrics_msgs[0]["tts_first_audio_ms"] > 0
    assert metrics_msgs[0]["e2e_latency_ms"] > 0
    orch._persist_turn.assert_awaited_once()

    # Empty transcript returns THINKING -> LISTENING cleanly
    orch.stt = MockSTT("")
    await orch.transition(VoiceState.THINKING, reason="empty_check")
    await orch._execute_turn(speech_pcm, 500.0)
    assert orch.state == VoiceState.LISTENING

    # Stop transitions LISTENING -> IDLE
    await orch.stop_listening()
    assert orch.state == VoiceState.IDLE


@pytest.mark.anyio
async def test_rate_limiter_enforces_limits():
    # Use unreachable Redis port to exercise explicit fallback & limit counting deterministically
    limiter = RateLimiter(redis_url="redis://127.0.0.1:63999/0")
    key = f"test:rl:{uuid.uuid4().hex}"
    for _ in range(3):
        allowed, _, backend = await limiter.check_limit(key, max_requests=3, window_seconds=60)
        assert allowed is True
        assert backend in ("redis", "memory")

    allowed_4, rem_4, _ = await limiter.check_limit(key, max_requests=3, window_seconds=60)
    assert allowed_4 is False
    assert rem_4 == 0


# ==============================================================================
# 4. WebSocket Auth Rejection, Isolation, Security Limits & Mocked Stream
# ==============================================================================

def _ws_url(http_base: str, agent_id: str, token: str = "") -> str:
    ws_base = http_base.replace("http://", "ws://", 1)
    if token:
        return f"{ws_base}/api/v1/voice/stream/{agent_id}?token={token}"
    return f"{ws_base}/api/v1/voice/stream/{agent_id}"


def test_websocket_auth_rejection_isolation_and_pipeline(server):
    # Setup User A and User B
    email_a = f"voicea_{uuid.uuid4().hex[:8]}@example.com"
    _, reg_a = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email_a,
        "password": "Password123!",
    })
    token_a = reg_a["access_token"]

    email_b = f"voiceb_{uuid.uuid4().hex[:8]}@example.com"
    _, reg_b = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email_b,
        "password": "Password123!",
    })
    token_b = reg_b["access_token"]

    _, agent_a = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "Voice Pipeline Agent",
        "llm_provider": "gemini",
        "llm_model": "gemini-4-hydrogen",
    }, token=token_a)
    agent_id = agent_a["id"]

    # Store API key in vault for User A
    st_vault, _ = http_request(f"{server}/api/v1/auth/secrets", method="POST", data={
        "provider": "gemini",
        "api_key": "AIzaSyMockVoiceTestKey1234567890",
    }, token=token_a)
    assert st_vault == 200

    async def run_ws_checks():
        # 1. Missing token -> rejected
        with pytest.raises((InvalidStatus, ConnectionClosed)):
            async with websockets.connect(_ws_url(server, agent_id)):
                pass

        # 2. Invalid token -> rejected
        with pytest.raises((InvalidStatus, ConnectionClosed)):
            async with websockets.connect(_ws_url(server, agent_id, "invalid.jwt.token")):
                pass

        # 3. User B accessing User A's agent -> rejected (owner only)
        with pytest.raises((InvalidStatus, ConnectionClosed)):
            async with websockets.connect(_ws_url(server, agent_id, token_b)):
                pass

        # 4. Authorized User A full mocked turn
        with (
            patch("app.api.v1.voice.get_llm_provider", return_value=MockLLM(api_key="mock")),
            patch("app.api.v1.voice.get_stt_provider", return_value=MockSTT("Testing one two three")),
            patch("app.api.v1.voice.get_tts_provider", return_value=MockTTS()),
        ):
            async with websockets.connect(_ws_url(server, agent_id, token_a)) as ws:
                ready = json.loads(await ws.recv())
                assert ready["type"] == "session_ready"
                assert ready["rate_limiter_backend"] in ("redis", "memory")

                await ws.send(json.dumps({"type": "config", "silence_threshold_ms": 400, "min_speech_ms": 100}))
                cfg_msg = json.loads(await ws.recv())
                assert cfg_msg["type"] == "config_updated"

                await ws.send(json.dumps({"type": "start"}))
                state_msg = json.loads(await ws.recv())
                assert state_msg["type"] == "state"
                assert state_msg["state"] == "LISTENING"

                # Send synthetic speech in chunks <= WS_MAX_MESSAGE_BYTES, then silence
                speech = _generate_synthetic_speech_pcm16(duration_s=1.5)
                silence = np.zeros(16000, dtype=np.int16).tobytes()
                chunk_size = 4096
                for payload in (speech, silence):
                    for i in range(0, len(payload), chunk_size):
                        await ws.send(payload[i : i + chunk_size])

                # Collect turn events until turn_metrics arrives
                seen_types = []
                received_audio = bytearray()
                while True:
                    frame = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    if isinstance(frame, bytes):
                        received_audio.extend(frame)
                        continue
                    ev = json.loads(frame)
                    seen_types.append(ev["type"])
                    if ev["type"] == "turn_metrics":
                        assert ev["stt_latency_ms"] > 0
                        assert ev["llm_first_token_ms"] > 0
                        assert ev["tts_first_audio_ms"] > 0
                        assert ev["e2e_latency_ms"] > 0
                        break

                assert "transcript" in seen_types
                assert "audio_start" in seen_types
                assert "audio_end" in seen_types
                assert len(received_audio) > 0

                # Test oversized message rejection
                oversized = b"\x00" * (settings.WS_MAX_MESSAGE_BYTES + 1024)
                await ws.send(oversized)
                err_frame = None
                while True:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    if isinstance(msg_raw, bytes):
                        continue
                    parsed = json.loads(msg_raw)
                    if parsed.get("type") == "error":
                        err_frame = parsed
                        break
                assert err_frame is not None
                assert err_frame["code"] == "MESSAGE_TOO_LARGE"

    asyncio.run(run_ws_checks())


# ==============================================================================
# 5. Comma Clause Splitting, Low-Confidence STT Drop, Retry/Fallback & Spoken Error
# ==============================================================================

def test_sentence_splitter_splits_clause_on_comma_after_8_words():
    splitter = StreamingSentenceSplitter(min_sentence_chars=12, min_clause_words=8)
    # Short comma (< 8 words) should NOT split early
    assert splitter.feed("Hello there, ") == []
    # Reaching >= 8 words before comma SHOULD split
    emitted = splitter.feed("how are you doing on this fine morning, my friend.")
    assert emitted == ["Hello there, how are you doing on this fine morning,"]
    flushed = splitter.flush()
    assert flushed == ["my friend."]


@pytest.mark.anyio
async def test_orchestrator_drops_low_confidence_or_short_stt():
    class LowConfSTT(BaseSTTProvider):
        async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en") -> STTResult:
            return STTResult(text=".", language="en", duration_ms=400.0, latency_ms=10.0, avg_logprob=-1.4)

    class FailIfCalledLLM(BaseLLMProvider):
        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            raise AssertionError("LLM should not be called for low-confidence/empty transcript")
            yield ""

    events = []

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        pass

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="DropCheck",
        slug="dropcheck",
        system_prompt="Be concise.",
        llm_provider="gemini",
        llm_model="gemini-3.5-flash-lite",
        temperature=0.5,
        stt_provider="faster-whisper",
        stt_language="en",
        tts_provider="edge-tts",
        tts_voice="en-US-GuyNeural",
    )
    orch = VoiceOrchestrator(
        agent=agent,
        session_id=str(uuid.uuid4()),
        llm_provider=FailIfCalledLLM(api_key="mock"),
        stt_provider=LowConfSTT(),
        tts_provider=MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=send_json,
        send_bytes=send_bytes,
    )
    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test")
    await orch._execute_turn(b"\x01\x00" * 3200, 200.0)
    assert orch.state == VoiceState.LISTENING
    assert not any(ev.get("type") == "transcript" for ev in events)


@pytest.mark.anyio
async def test_orchestrator_retries_and_falls_back_on_503():
    calls = []

    class Flaky503ThenFallbackLLM(BaseLLMProvider):
        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            calls.append(model)
            if model == "gemini-3.5-flash-lite":
                raise LLMServiceUnavailableError("Gemini 503")
            yield "Hello from fallback."

    events = []
    audio_out = bytearray()

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        audio_out.extend(data)

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="FallbackBot",
        slug="fallbackbot",
        system_prompt="Be helpful.",
        llm_provider="gemini",
        llm_model="gemini-3.5-flash-lite",
        temperature=0.5,
        stt_provider="faster-whisper",
        stt_language="en",
        tts_provider="edge-tts",
        tts_voice="en-US-GuyNeural",
    )
    orch = VoiceOrchestrator(
        agent=agent,
        session_id=str(uuid.uuid4()),
        llm_provider=Flaky503ThenFallbackLLM(api_key="mock"),
        stt_provider=MockSTT("Hello there"),
        tts_provider=MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=send_json,
        send_bytes=send_bytes,
    )
    orch._persist_turn = AsyncMock()
    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test")

    with patch("app.services.voice_orchestrator.asyncio.sleep", new=AsyncMock()):
        await orch._execute_turn(b"\x01\x00" * 8000, 500.0)

    # Primary retried 2 times (3 total calls) + 1 fallback call to gemini-3.8-flash
    assert calls == [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    ]
    assert orch.state == VoiceState.LISTENING
    assert any(ev.get("type") == "transcript" and ev.get("role") == "assistant" and "fallback" in ev.get("text", "") for ev in events)
    assert len(audio_out) > 0


@pytest.mark.anyio
async def test_orchestrator_speaks_fallback_error_when_all_models_fail():
    class AlwaysFailLLM(BaseLLMProvider):
        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            raise LLMServiceUnavailableError("All Gemini models down (503)")
            yield ""

    events = []
    audio_out = bytearray()

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        audio_out.extend(data)

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="ErrorBot",
        slug="errorbot",
        system_prompt="Be helpful.",
        llm_provider="gemini",
        llm_model="gemini-3.5-flash-lite",
        temperature=0.5,
        stt_provider="faster-whisper",
        stt_language="en",
        tts_provider="edge-tts",
        tts_voice="en-US-GuyNeural",
    )
    orch = VoiceOrchestrator(
        agent=agent,
        session_id=str(uuid.uuid4()),
        llm_provider=AlwaysFailLLM(api_key="mock"),
        stt_provider=MockSTT("Hello there"),
        tts_provider=MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=send_json,
        send_bytes=send_bytes,
    )
    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test")

    with patch("app.services.voice_orchestrator.asyncio.sleep", new=AsyncMock()):
        await orch._execute_turn(b"\x01\x00" * 8000, 500.0)

    assert orch.state == VoiceState.LISTENING
    assert any(ev.get("type") == "error" and ev.get("code") == "SERVICE_UNAVAILABLE" for ev in events)
    assert any(
        ev.get("type") == "transcript"
        and ev.get("role") == "assistant"
        and ev.get("text") == "Sorry, I had trouble. Could you repeat that?"
        for ev in events
    )
    assert len(audio_out) > 0


# ==============================================================================
# 6. VAD Noise Robustness: Constant Noise, Hysteresis Silence & Max Cap
# ==============================================================================

def test_vad_constant_noise_never_starts_utterance():
    vad = StreamingVAD(
        sample_rate=16000,
        silence_threshold_ms=700,
        speech_start_threshold=0.6,
        speech_end_threshold=0.45,
        energy_multiplier=2.0,
        min_speech_ms=200,
        backend="silero-onnx",
    )
    rng = np.random.default_rng(42)
    # 3 seconds of steady background white/pink-like noise (RMS ~0.015)
    noise = (rng.normal(0.0, 0.015, 16000 * 3) * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
    events = []
    for i in range(0, len(noise), 1024):
        events.extend(vad.process_chunk(noise[i : i + 1024]))

    assert not any(ev.speech_start for ev in events)
    assert not any(ev.utterance_pcm16 is not None for ev in events)


def test_vad_speech_followed_by_mid_noise_ends_by_silence_timer():
    vad = StreamingVAD(
        sample_rate=16000,
        silence_threshold_ms=500,
        speech_start_threshold=0.6,
        speech_end_threshold=0.45,
        energy_multiplier=2.0,
        min_speech_ms=200,
        backend="silero-onnx",
    )
    speech = _generate_synthetic_speech_pcm16(duration_s=1.0)
    mid_noise = np.zeros(16000, dtype=np.int16).tobytes()

    # Simulate Silero returning 0.85 during speech and 0.50 (between 0.45 and 0.60) during trailing noise.
    # Silence timer must NOT reset on 0.50, so utterance ends via silence timer!
    probs = [0.85] * 32 + [0.50] * 32
    with patch.object(vad, "_score_frame", side_effect=probs):
        events = []
        for chunk in (speech, mid_noise):
            for i in range(0, len(chunk), 1024):
                events.extend(vad.process_chunk(chunk[i : i + 1024]))

    assert any(ev.speech_start for ev in events)
    completed = [ev for ev in events if ev.utterance_pcm16 is not None]
    assert len(completed) == 1
    assert completed[0].end_reason == "silence"
    assert completed[0].avg_prob > 0.0


def test_vad_max_utterance_cap_triggers():
    vad = StreamingVAD(
        sample_rate=16000,
        silence_threshold_ms=700,
        speech_start_threshold=0.6,
        speech_end_threshold=0.45,
        energy_multiplier=2.0,
        min_speech_ms=200,
        backend="silero-onnx",
        max_utterance_seconds=2,
    )
    long_speech = _generate_synthetic_speech_pcm16(duration_s=3.5)
    with patch.object(vad, "_score_frame", return_value=0.90):
        events = []
        for i in range(0, len(long_speech), 1024):
            events.extend(vad.process_chunk(long_speech[i : i + 1024]))

    completed = [ev for ev in events if ev.utterance_pcm16 is not None]
    assert len(completed) >= 1
    assert completed[0].end_reason == "max_cap"


@pytest.mark.anyio
async def test_orchestrator_first_token_timeout_retries_once_then_fallback():
    calls = []

    class SlowTimeoutLLM(BaseLLMProvider):
        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            calls.append(model)
            await asyncio.Event().wait()
            yield "Too late"

    events = []
    audio_out = bytearray()

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        audio_out.extend(data)

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="TimeoutBot",
        slug="timeoutbot",
        system_prompt="Be helpful.",
        llm_provider="gemini",
        llm_model="gemini-3.5-flash-lite",
        temperature=0.5,
        stt_provider="faster-whisper",
        stt_language="en",
        tts_provider="edge-tts",
        tts_voice="en-US-GuyNeural",
    )
    orch = VoiceOrchestrator(
        agent=agent,
        session_id=str(uuid.uuid4()),
        llm_provider=SlowTimeoutLLM(api_key="mock"),
        stt_provider=MockSTT("Hello there"),
        tts_provider=MockTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=send_json,
        send_bytes=send_bytes,
    )
    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test")

    with (
        patch.object(settings, "LLM_FIRST_TOKEN_TIMEOUT_S", 0.05),
        patch("app.services.voice_orchestrator.asyncio.sleep", new=AsyncMock()),
    ):
        await orch._execute_turn(b"\x01\x00" * 8000, 500.0)

    # On timeout: initial + 1 retry on primary, then 1 attempt on fallback gemini-3.8-flash
    assert calls == [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    ]
    assert orch.state == VoiceState.LISTENING
    assert any(ev.get("type") == "error" and ev.get("code") == "TIMEOUT" for ev in events)
    assert any(
        ev.get("type") == "transcript"
        and ev.get("role") == "assistant"
        and ev.get("text") == "Sorry, I had trouble. Could you repeat that?"
        for ev in events
    )
    assert len(audio_out) > 0


# ==============================================================================
# 6. VAD Noise Robustness: Constant Noise, Hysteresis Silence & Max Cap
# ==============================================================================

def test_vad_constant_noise_never_starts_utterance():
    vad = StreamingVAD(
        sample_rate=16000,
        silence_threshold_ms=700,
        speech_start_threshold=0.6,
        speech_end_threshold=0.45,
        energy_multiplier=2.0,
        min_speech_ms=200,
        backend="silero-onnx",
    )
    rng = np.random.default_rng(42)
    # 3 seconds of steady background white/pink-like noise (RMS ~0.015)
    noise = (rng.normal(0.0, 0.015, 16000 * 3) * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
    events = []
    for i in range(0, len(noise), 1024):
        events.extend(vad.process_chunk(noise[i : i + 1024]))

    assert not any(ev.speech_start for ev in events)
    assert not any(ev.utterance_pcm16 is not None for ev in events)


def test_vad_speech_followed_by_mid_noise_ends_by_silence_timer():
    vad = StreamingVAD(
        sample_rate=16000,
        silence_threshold_ms=500,
        speech_start_threshold=0.6,
        speech_end_threshold=0.45,
        energy_multiplier=2.0,
        min_speech_ms=200,
        backend="silero-onnx",
    )
    speech = _generate_synthetic_speech_pcm16(duration_s=1.0)
    mid_noise = np.zeros(16000, dtype=np.int16).tobytes()

    # Simulate Silero returning 0.85 during speech and 0.50 (between 0.45 and 0.60) during trailing noise.
    # Silence timer must NOT reset on 0.50, so utterance ends via silence timer!
    probs = [0.85] * 32 + [0.50] * 32
    with patch.object(vad, "_score_frame", side_effect=probs):
        events = []
        for chunk in (speech, mid_noise):
            for i in range(0, len(chunk), 1024):
                events.extend(vad.process_chunk(chunk[i : i + 1024]))

    assert any(ev.speech_start for ev in events)
    completed = [ev for ev in events if ev.utterance_pcm16 is not None]
    assert len(completed) == 1
    assert completed[0].end_reason == "silence"
    assert completed[0].avg_prob > 0.0


def test_vad_max_utterance_cap_triggers():
    vad = StreamingVAD(
        sample_rate=16000,
        silence_threshold_ms=700,
        speech_start_threshold=0.6,
        speech_end_threshold=0.45,
        energy_multiplier=2.0,
        min_speech_ms=200,
        backend="silero-onnx",
        max_utterance_seconds=2,
    )
    long_speech = _generate_synthetic_speech_pcm16(duration_s=3.5)
    with patch.object(vad, "_score_frame", return_value=0.90):
        events = []
        for i in range(0, len(long_speech), 1024):
            events.extend(vad.process_chunk(long_speech[i : i + 1024]))

    completed = [ev for ev in events if ev.utterance_pcm16 is not None]
    assert len(completed) >= 1
    assert completed[0].end_reason == "max_cap"
