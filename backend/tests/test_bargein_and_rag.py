import asyncio
import json
import math
import uuid
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings
from app.core.database import Base
from app.models.agent import Agent
from app.models.document import Document, DocumentChunk
from app.providers.embeddings.base import BaseEmbeddingProvider
from app.providers.llm.base import BaseLLMProvider
from app.providers.stt.base import BaseSTTProvider, STTResult
from app.providers.tts.base import BaseTTSProvider
from app.services.rag_service import chunk_text, retrieve_relevant_chunks
from app.services.voice_orchestrator import VoiceOrchestrator, VoiceState
from app.vad.detector import StreamingVAD
from tests.test_voice_pipeline import http_request


class FakeEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic 768-dim embedding provider keyed by keyword topic for testing."""

    def __init__(self):
        super().__init__(api_key="fake-key", model="gemini-embedding-001", dimensions=768)

    async def embed_text(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT"):
        low = text.lower()
        vec = [0.0] * 768
        if "refund" in low or "return" in low:
            vec[0] = 1.0
        elif "shipping" in low or "delivery" in low:
            vec[1] = 1.0
        else:
            vec[2] = 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


# ==============================================================================
# PART 1: Barge-in State Transitions, Debounce & Partial Persistence
# ==============================================================================

@pytest.mark.anyio
async def test_barge_in_cancels_speaking_turn_and_persists_partial():
    class SlowStreamLLM(BaseLLMProvider):
        async def generate_stream(self, messages, system_prompt="", temperature=0.7, model=""):
            yield "Here is the first part "
            await asyncio.sleep(0.05)
            yield "and this should be interrupted. "
            await asyncio.sleep(5.0)
            yield "Never reached."

    class SlowTTS(BaseTTSProvider):
        async def synthesize_stream(self, text: str, voice: str = "", cancel_event=None):
            yield b"ID3-FIRST-AUDIO"
            await asyncio.sleep(5.0)

    class SimpleSTT(BaseSTTProvider):
        async def transcribe(self, audio_pcm16: bytes, sample_rate: int = 16000, language: str = "en"):
            return STTResult(text="Tell me a long story", language="en", duration_ms=1000.0, latency_ms=15.0)

    events = []

    async def send_json(data):
        events.append(data)

    async def send_bytes(data):
        pass

    agent = Agent(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        name="BargeBot",
        slug=f"bargebot-{uuid.uuid4().hex[:6]}",
        system_prompt="Be helpful.",
        llm_provider="gemini",
        llm_model="gemini-3.5-flash-lite",
        temperature=0.5,
        stt_provider="faster-whisper",
        stt_language="en",
        tts_provider="edge-tts",
        tts_voice="en-US-GuyNeural",
    )

    vad = StreamingVAD(backend="webrtcvad")
    orch = VoiceOrchestrator(
        agent=agent,
        session_id=str(uuid.uuid4()),
        llm_provider=SlowStreamLLM(api_key="mock"),
        stt_provider=SimpleSTT(),
        tts_provider=SlowTTS(),
        vad=vad,
        send_json=send_json,
        send_bytes=send_bytes,
    )
    orch._persist_turn = AsyncMock()

    await orch.start_listening()
    await orch._begin_turn(b"\x01\x00" * 8000, 500.0)
    # Wait until assistant reaches SPEAKING
    for _ in range(40):
        if orch.state == VoiceState.SPEAKING:
            break
        await asyncio.sleep(0.02)
    assert orch.state == VoiceState.SPEAKING

    # Simulate debounced speech during SPEAKING:
    # First < 250ms should NOT interrupt
    with patch.object(vad, "process_chunk", return_value=[]):
        vad._in_speech = True
        vad._speech_ms = 120.0
        await orch.handle_audio_frame(b"\x01\x00" * 480)
        assert orch.state == VoiceState.SPEAKING

        # Once confirmed speech >= 250ms, barge-in triggers!
        vad._speech_ms = 260.0
        await orch.handle_audio_frame(b"\x01\x00" * 480)

    assert orch.state == VoiceState.LISTENING
    assert any(ev.get("type") == "interrupt" and ev.get("reason") == "barge_in" for ev in events)
    # Partial interrupted assistant turn must be saved with interrupted=True
    assert orch._persist_turn.await_count == 1
    persist_kwargs = orch._persist_turn.await_args.kwargs
    assert persist_kwargs["interrupted"] is True
    assert "first part" in persist_kwargs["assistant_text"]


# ==============================================================================
# PART 2: RAG Chunking, Retrieval Ranking & Multi-Tenant Isolation
# ==============================================================================

def test_rag_chunking_with_overlap():
    words = [f"word{i}" for i in range(1100)]
    text_in = " ".join(words)
    chunks = chunk_text(text_in, chunk_tokens=500, overlap_tokens=50)
    assert len(chunks) == 3
    # Verify 50-token overlap between chunk 0 and chunk 1
    c0_words = chunks[0].split(" ")
    c1_words = chunks[1].split(" ")
    assert len(c0_words) == 500
    assert c0_words[-50:] == c1_words[:50]


@pytest.mark.anyio
async def test_rag_retrieval_ranking_with_fake_embeddings():
    fake_emb = FakeEmbeddingProvider()
    doc_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # Use an isolated in-memory SQLite engine so we never share asyncpg pools across event loops
    from app.models.user import User
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with TestSession() as db:
            user = User(id=user_id, email=f"rag_{uuid.uuid4().hex[:6]}@example.com", hashed_password="x")
            db.add(user)
            agent = Agent(
                id=agent_id,
                user_id=user_id,
                name="RagAgent",
                slug=f"ragagent-{uuid.uuid4().hex[:6]}",
                system_prompt="Answer from context.",
            )
            db.add(agent)
            doc = Document(
                id=doc_id,
                user_id=user_id,
                agent_id=agent_id,
                filename="policies.txt",
                file_type="txt",
                file_size=128,
                status="indexed",
            )
            db.add(doc)

            c0_vec = await fake_emb.embed_text("Full refund within 30 days.")
            c1_vec = await fake_emb.embed_text("Standard shipping takes 5 business days.")
            c2_vec = await fake_emb.embed_text("Company founded in 2020.")

            db.add_all([
                DocumentChunk(document_id=doc_id, agent_id=agent_id, chunk_index=0, content="Full refund within 30 days.", embedding=c0_vec),
                DocumentChunk(document_id=doc_id, agent_id=agent_id, chunk_index=1, content="Standard shipping takes 5 business days.", embedding=c1_vec),
                DocumentChunk(document_id=doc_id, agent_id=agent_id, chunk_index=2, content="Company founded in 2020.", embedding=c2_vec),
            ])
            await db.commit()

            results = await retrieve_relevant_chunks(
                db=db,
                agent_id=agent_id,
                query="What is your refund policy?",
                api_key="fake",
                top_k=4,
                similarity_threshold=0.5,
                embedding_provider=fake_emb,
            )
            assert len(results) == 1
            assert results[0]["filename"] == "policies.txt"
            assert results[0]["chunk_index"] == 0
            assert results[0]["score"] == 1.0
            assert "refund" in results[0]["content"].lower()
    finally:
        await test_engine.dispose()


def test_knowledge_endpoints_and_user_isolation(server):
    email_a = f"kna_{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"knb_{uuid.uuid4().hex[:8]}@example.com"
    _, reg_a = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email_a, "password": "Password123!"})
    _, reg_b = http_request(f"{server}/api/v1/auth/register", method="POST", data={"email": email_b, "password": "Password123!"})
    token_a = reg_a["access_token"]
    token_b = reg_b["access_token"]

    _, agent_a = http_request(f"{server}/api/v1/agents", method="POST", data={
        "name": "Knowledge Bot A",
        "llm_provider": "gemini",
        "llm_model": "gemini-3.5-flash-lite",
    }, token=token_a)
    agent_a_id = agent_a["id"]

    # Multipart upload by User A
    import urllib.request
    boundary = "----TestBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="agent_id"\r\n\r\n{agent_a_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="faq.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
        f"Refunds are processed within 3 business days.\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{server}/api/v1/knowledge/upload",
        data=body,
        headers={
            "Authorization": f"Bearer {token_a}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with (
        patch("app.api.v1.knowledge.process_document_background", new=AsyncMock()),
        urllib.request.urlopen(req) as resp,
    ):
        assert resp.status == 201
        uploaded = json.loads(resp.read().decode("utf-8"))
    doc_id = uploaded["id"]

    # User A sees the document; User B sees empty list
    st_list_a, list_a = http_request(f"{server}/api/v1/knowledge", method="GET", token=token_a)
    st_list_b, list_b = http_request(f"{server}/api/v1/knowledge", method="GET", token=token_b)
    assert st_list_a == 200 and any(d["id"] == doc_id for d in list_a)
    assert st_list_b == 200 and not any(d["id"] == doc_id for d in list_b)

    # User B cannot delete User A's document or query-test User A's agent
    st_del_b, _ = http_request(f"{server}/api/v1/knowledge/{doc_id}", method="DELETE", token=token_b)
    st_qry_b, _ = http_request(f"{server}/api/v1/knowledge/query-test", method="POST", data={
        "agent_id": agent_a_id,
        "query": "refunds",
    }, token=token_b)
    assert st_del_b == 404
    assert st_qry_b == 404

    # User A can delete their document
    st_del_a, _ = http_request(f"{server}/api/v1/knowledge/{doc_id}", method="DELETE", token=token_a)
    assert st_del_a == 204
