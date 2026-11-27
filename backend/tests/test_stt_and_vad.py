import io
import uuid
import wave
import httpx
import pytest
from app.models.agent import Agent
from app.providers.llm.base import BaseLLMProvider
from app.providers.stt.base import BaseSTTProvider, STTResult
from app.providers.stt.gemini_provider import GeminiSTTProvider, pcm16_to_wav_bytes
from app.providers.stt.vocab import build_vocab_hint_from_parts, extract_distinctive_terms
from app.providers.tts.base import BaseTTSProvider
from app.services.voice_orchestrator import VoiceOrchestrator, VoiceState
from app.vad.detector import StreamingVAD, VADResult


class _FakeFallbackSTT(BaseSTTProvider):
    def __init__(self, text: str = "fallback transcript"):
        self.text = text
        self.calls = 0
        self.last_context_prompt = None

    async def transcribe(
        self,
        audio_pcm16: bytes,
        sample_rate: int = 16000,
        language: str = "en",
        context_prompt=None,
    ) -> STTResult:
        self.calls += 1
        self.last_context_prompt = context_prompt
        return STTResult(
            text=self.text,
            language=language,
            duration_ms=500.0,
            latency_ms=42.0,
            avg_logprob=-0.25,
            no_speech_prob=0.05,
            provider="faster-whisper",
        )


class _DummyLLM(BaseLLMProvider):
    async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
        raise AssertionError("LLM should not be called on dropped utterance")
        yield ""


class _DummyTTS(BaseTTSProvider):
    async def synthesize_stream(self, text: str, voice: str = "", cancel_event=None):
        yield b"ID3-mock-mp3"


def test_pcm16_to_wav_bytes_valid_header():
    pcm = b"\x01\x00" * 1600  # 100ms @ 16kHz
    wav_bytes = pcm16_to_wav_bytes(pcm, sample_rate=16000)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 1600


@pytest.mark.anyio
async def test_gemini_stt_missing_key_falls_back_to_whisper():
    fb = _FakeFallbackSTT(text="hello from whisper")
    stt = GeminiSTTProvider(api_key="", fallback_provider=fb)
    res = await stt.transcribe(b"\x01\x00" * 3200, sample_rate=16000, language="en", context_prompt="resume, ECE")
    assert res.text == "hello from whisper"
    assert res.provider == "faster-whisper"
    assert fb.calls == 1
    assert fb.last_context_prompt == "resume, ECE"


@pytest.mark.anyio
async def test_gemini_stt_429_and_timeout_fallback(monkeypatch):
    fb = _FakeFallbackSTT(text="fallback ok")
    stt = GeminiSTTProvider(api_key="fake-key", max_retries=1, fallback_provider=fb)

    # 1. HTTP 429 rate limit -> retry once -> fallback
    class _Client429:
        def __init__(self):
            self.posts = 0

        async def post(self, url, json=None, timeout=None):
            self.posts += 1
            return httpx.Response(429, text="rate limited")

    client_429 = _Client429()
    monkeypatch.setattr("app.providers.stt.gemini_provider.get_gemini_stt_http_client", lambda t: client_429)
    res_429 = await stt.transcribe(b"\x01\x00" * 3200)
    assert client_429.posts == 2  # 1 initial + 1 retry
    assert res_429.provider == "faster-whisper"
    assert fb.calls == 1

    # 2. Timeout -> fall back immediately (no retry on timeout)
    class _ClientTimeout:
        def __init__(self):
            self.posts = 0

        async def post(self, url, json=None, timeout=None):
            self.posts += 1
            raise httpx.ReadTimeout("timed out")

    client_to = _ClientTimeout()
    monkeypatch.setattr("app.providers.stt.gemini_provider.get_gemini_stt_http_client", lambda t: client_to)
    res_to = await stt.transcribe(b"\x01\x00" * 3200)
    assert client_to.posts == 1
    assert res_to.provider == "faster-whisper"
    assert fb.calls == 2

    # 3. HTTP 200 success -> served by gemini
    class _Client200:
        async def post(self, url, json=None, timeout=None):
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "Review my resume for ECE."}]}}]},
            )

    monkeypatch.setattr("app.providers.stt.gemini_provider.get_gemini_stt_http_client", lambda t: _Client200())
    res_ok = await stt.transcribe(b"\x01\x00" * 3200, context_prompt="resume, ECE")
    assert res_ok.provider == "gemini"
    assert res_ok.text == "Review my resume for ECE."
    assert fb.calls == 2


def test_vocab_hint_building_extracts_distinctive_terms():
    terms = extract_distinctive_terms(
        ["Built an STM32 IoT telemetry node with MQTT and RTOS. CGPA is 9.2 in ECE."]
    )
    assert "STM32" in terms
    assert "CGPA" in terms
    assert "ECE" in terms

    hint = build_vocab_hint_from_parts(
        agent_name="CareerCoach",
        agent_description="Helps with embedded systems interviews",
        tool_names=["get_weather", "book_appointment"],
        filenames=["arish_resume_2026.pdf"],
        chunk_texts=["Designed ESP32 firmware and FreeRTOS tasks for robotics."],
        extra_vocab="resume, CGPA, ECE, IoT",
    )
    assert "resume" in hint
    assert "CareerCoach" in hint
    assert "get weather" in hint
    assert "arish resume 2026" in hint
    assert "ESP32" in hint


@pytest.mark.anyio
async def test_dropped_utterance_emits_event_transcript_note_and_tts():
    class _NoSpeechSTT(BaseSTTProvider):
        async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en", context_prompt=None) -> STTResult:
            return STTResult(
                text="uh",
                language="en",
                duration_ms=500.0,
                latency_ms=15.0,
                avg_logprob=-1.7,
                no_speech_prob=0.85,
                provider="faster-whisper",
            )

    events = []
    audio_bytes = []

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        audio_bytes.append(data)

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="NoiseTester",
        slug="noise-tester",
        system_prompt="Be helpful.",
        llm_provider="gemini",
        llm_model="gemini-3.5-flash-lite",
        temperature=0.5,
        stt_provider="gemini",
        stt_language="en",
        tts_provider="edge-tts",
        tts_voice="en-US-GuyNeural",
    )
    orch = VoiceOrchestrator(
        agent=agent,
        session_id=str(uuid.uuid4()),
        llm_provider=_DummyLLM(api_key="mock"),
        stt_provider=_NoSpeechSTT(),
        tts_provider=_DummyTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=send_json,
        send_bytes=send_bytes,
    )
    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test_drop")
    await orch._execute_turn(b"\x01\x00" * 4000, 250.0)

    assert orch.state == VoiceState.LISTENING
    dropped_evs = [e for e in events if e.get("type") == "utterance_dropped"]
    assert len(dropped_evs) == 1
    assert dropped_evs[0]["reason"] == "no_speech_prob"
    note_evs = [e for e in events if e.get("type") == "transcript" and e.get("dropped") is True]
    assert len(note_evs) == 1
    assert "didn't catch that" in note_evs[0]["text"]
    assert len(audio_bytes) > 0


@pytest.mark.anyio
async def test_4600ms_valid_transcript_is_not_dropped():
    class _GoodSTT(BaseSTTProvider):
        async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en", context_prompt=None) -> STTResult:
            return STTResult(
                text="Can you please motivate me?",
                language="en",
                duration_ms=4640.0,
                latency_ms=120.0,
                avg_logprob=-0.28,
                no_speech_prob=0.85,  # high no_speech_prob must not drop >=2 valid words
                provider="faster-whisper",
            )

    class _ReplyLLM(BaseLLMProvider):
        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            yield "You have got this! Keep pushing forward."

    events = []

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        pass

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="Motivator",
        slug="motivator",
        system_prompt="Be encouraging.",
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
        llm_provider=_ReplyLLM(api_key="mock"),
        stt_provider=_GoodSTT(),
        tts_provider=_DummyTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=send_json,
        send_bytes=send_bytes,
    )
    # Persist skipped via monkeypatch or fake session
    async def _noop_persist(**kwargs):
        return None
    orch._persist_turn = _noop_persist

    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test_keep_4640")
    vad_res = VADResult(
        utterance_pcm16=b"\x01\x00" * 74240,
        duration_ms=4640.0,
        avg_prob=0.18,
        peak_prob=0.88,
        speech_ratio=0.15,
        end_reason="silence",
    )
    await orch._execute_turn(b"\x01\x00" * 74240, 4640.0, vad_result=vad_res)

    assert not any(ev.get("type") == "utterance_dropped" for ev in events)
    assert any(
        ev.get("type") == "transcript" and ev.get("role") == "user" and ev.get("text") == "Can you please motivate me?"
        for ev in events
    )
    assert any(
        ev.get("type") == "transcript" and ev.get("role") == "assistant" and "Keep pushing forward" in ev.get("text", "")
        for ev in events
    )


@pytest.mark.anyio
async def test_200ms_no_speech_utterance_is_dropped_before_stt():
    class _FailIfCalledSTT(BaseSTTProvider):
        async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en", context_prompt=None) -> STTResult:
            raise AssertionError("STT should not be called when pre-STT VAD gate drops low_vad")

    events = []

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        pass

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="DropPreSTT",
        slug="drop-prestt",
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
        llm_provider=_DummyLLM(api_key="mock"),
        stt_provider=_FailIfCalledSTT(),
        tts_provider=_DummyTTS(),
        vad=StreamingVAD(backend="webrtcvad"),
        send_json=send_json,
        send_bytes=send_bytes,
    )
    await orch.start_listening()
    await orch.transition(VoiceState.THINKING, reason="test_200ms_drop")
    vad_res = VADResult(
        utterance_pcm16=b"\x01\x00" * 3200,
        duration_ms=200.0,
        avg_prob=0.12,
        peak_prob=0.22,
        speech_ratio=0.0,
        end_reason="silence",
    )
    await orch._execute_turn(b"\x01\x00" * 3200, 200.0, vad_result=vad_res)

    assert orch.state == VoiceState.LISTENING
    dropped = [ev for ev in events if ev.get("type") == "utterance_dropped"]
    assert len(dropped) == 1
    assert dropped[0]["reason"] == "low_vad"
