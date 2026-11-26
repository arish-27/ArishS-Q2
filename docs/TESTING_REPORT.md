# Testing, Evaluation & Latency Report

All automated tests, coverage, RAG evaluation, and load checks below were executed inside the running Docker Compose stack (`voiceagent_backend` on Python 3.12.16, PostgreSQL 16 + `pgvector`, Redis 7).

## 1. Pytest Suite & Coverage (`docker compose exec backend pytest --cov=app --cov-report=term-missing`)

- **Result:** `44 passed in 18.34s`
- **Total Coverage:** `65%` (`3255` statements, `1155` missed)

| Module Group | Coverage Highlights |
| --- | --- |
| `app/vad/detector.py` | `94%` (hysteresis, energy gate, max cap, synthetic audio) |
| `app/services/sentence_splitter.py` | `91%` (sentence + comma-clause splitting) |
| `app/services/voice_orchestrator.py` | `85%` (state machine, barge-in, retries/fallback, tools, RAG) |
| `app/services/rate_limiter.py` | `88%` (Redis + memory fallback) |
| `app/core/config.py`, `security.py`, `database.py` | `81% – 92%` |
| `app/models/*`, `app/schemas/*` | `88% – 100%` |

### Honest Test Setup Notes & Limitations
- Inside Docker, HTTP and WebSocket integration tests (`test_agents.py`, `test_auth.py`, `test_chat_llm.py`, `test_tools.py`, `test_public_agent.py`, `test_analytics.py`, `test_voice_pipeline.py`) run against live **PostgreSQL 16 + pgvector** and **Redis 7** via `uvicorn.Server` in `conftest.py`.
- `test_rag_retrieval_ranking_with_fake_embeddings` uses an isolated in-memory **SQLite** engine (`sqlite+aiosqlite:///:memory:`) with JSON-serialized 768-dim vectors so it does not share `asyncpg` connection pools across separate event loops.
- LLM/TTS/STT unit tests mock external providers (`MockLLM`, `MockSTT`, `MockTTS`, `FakeEmbeddingProvider`); real Gemini API + pgvector behavior is verified separately in `scripts/eval_rag.py` and `scripts/profile_gemini_stream.py`.

## 2. RAG Evaluation (`docker compose exec backend python scripts/eval_rag.py`)

Evaluated against `docs/eval/company_handbook.txt` and `docs/eval/qa_pairs.json` (20 in-knowledge Q&A pairs + 5 out-of-knowledge questions) using `gemini-embedding-001` (768-dim) + PostgreSQL `pgvector` HNSW + `gemini-3.5-flash-lite`:

| Metric | Measured Result |
| --- | --- |
| In-Knowledge Questions | `20` |
| Retrieval Hit Rate (`top-4`) | `100.0%` |
| Keyword Match Accuracy | `100.0%` |
| LLM-as-Judge Avg Score | `1.000 / 1.0` |
| Out-of-Knowledge Abstention (`5` Qs) | `100.0%` |
| Retrieval Latency (avg / p95) | `1199.5 ms / 875.9 ms` (includes 1 cold `12.4s` initial embedding request) |
| LLM TTFT (avg / p95) | `1238.0 ms / 2147.9 ms` |
| Total Turn Latency (avg / p95) | `2451.2 ms / 4395.7 ms` |

Full per-question results are saved in `docs/eval/results.json` and `docs/eval/results.md`.

## 3. Voice Stage Latency & Gemini Network Profiling

Measured inside `voiceagent_backend` (`scripts/profile_gemini_stream.py` + stage probes):

| Stage | Before | After | Evidence / Notes |
| --- | --- | --- | --- |
| STT (2s speech) | `~2100 ms` (`5196.8 ms` cold `small`) | `1699.2 ms` | `small.en`, `int8`, `beam_size=1`, `cpu_threads=12` |
| LLM TTFT | `~3500 ms` (`1609.6 ms` cold client) | `1245.8 ms` warm (`minimal`) | Persistent `httpx.AsyncClient`; `first_byte == first_token` within `0.1ms` |
| TTS First Audio | `812.8 ms` | `1203.3 ms` | Edge-TTS network RTT; pre-warmed on WebSocket connect |

**Gemini Network Bottleneck Evidence:** `scripts/profile_gemini_stream.py` confirmed `first_byte_ms == first_token_ms` (`1245.7ms` vs `1245.8ms`, `2057.0ms` vs `2057.0ms`), and full stream completion occurs `5–20ms` after the first byte. `thinkingLevel: "none"` and `thinkingBudget: 0` are rejected (`HTTP 400`) on `gemini-3.5-flash-lite`; `thinkingLevel: "minimal"` is the lowest accepted setting.

## 4. Concurrency Load Check (`docker compose exec backend python scripts/load_check.py`)

- **Scenario:** 10 concurrent `POST /api/v1/chat/{agent_id}` requests
- **Result:** `requests=10 errors=0 wall_ms=1406.3 min_ms=524.4 avg_ms=745.6 p95_ms=1396.3 max_ms=1396.3`

## 5. Security & Fresh-Clone Verification

- `git ls-files` confirms `.env`, `*.db`, and `*.key` are not tracked (`.env.example` only).
- `git grep` across source and commit history confirmed zero real API keys committed (only synthetic test strings in `backend/tests/`).
- **Fresh Clone Commands:**
  ```bash
  cp .env.example .env
  # Generate JWT_SECRET_KEY (openssl rand -hex 32) and ENCRYPTION_SECRET_KEY (Fernet) in .env
  docker compose up --build -d
  docker compose exec backend alembic upgrade head
  docker compose exec backend python scripts/seed_demo.py
  ```
