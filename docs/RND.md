# Research & Development (R&D) Specification
## AI Voice Agent Development & Deployment Platform

---

## 1. Problem Statement and Objectives

Building real-time conversational AI voice agents requires orchestrating low-latency duplex audio streaming, voice activity detection (VAD), speech-to-text (STT), context-managed LLM inference, sentence-level text-to-speech (TTS), retrieval-augmented generation (RAG), and safe tool execution.

Managed proprietary platforms (Vapi, Retell AI, Bland AI) abstract this pipeline behind closed APIs, creating vendor lock-in, higher per-minute costs, and third-party data exposure. The objective of this project is to build a **self-hosted, modular, open-architecture voice agent platform** (comparable to Dograh) with:
1. Full-duplex 16kHz PCM16 WebSocket audio streaming between browser and FastAPI.
2. In-house **Silero/WebRTC VAD -> faster-whisper STT -> Gemini/OpenAI LLM -> Edge-TTS** pipeline with debounced barge-in.
3. PostgreSQL `pgvector` RAG grounding (`gemini-embedding-001`, 768-dim HNSW).
4. JSON-schema function calling with SSRF-protected webhooks and human-in-the-loop confirmation for sensitive actions.
5. Public shareable agent links (`/a/{slug}`) and turn-level latency/error analytics.

---

## 2. Existing Platforms and Competitor Analysis

| Dimension | Dograh | Vapi | Retell AI | Bland AI | This Project |
| --- | --- | --- | --- | --- | --- |
| **Approach** | Open/modular voice agent framework | Managed SaaS voice orchestration | Managed SaaS low-latency voice | Managed SaaS AI phone calls | **Self-hosted Dockerized FastAPI + Next.js** |
| **Strengths** | Open architecture, customizable | Rich integrations, quick setup | Polished turn-taking & telephony | High-concurrency outbound calls | **Zero vendor lock-in, full code control, Fernet vault, pgvector RAG** |
| **Weaknesses** | Self-managed infra | Per-minute markup, closed core | Proprietary pipeline, vendor lock-in | Opaque internals, telephony-centric | **CPU STT latency (~1.7s), no PSTN/WebRTC yet** |
| **How This Project Differs** | Similar modular philosophy | Replaces black-box orchestration with inspectable Python state machine | Replaces SaaS VAD/TTS with local Silero-ONNX + Edge-TTS | Focuses on browser WebSocket studio, RAG, and sensitive tool gates | **Inspectable pipeline metrics, HNSW RAG, and per-user encrypted vault** |

---

## 3. Technical Research on STT, TTS, LLMs, and Real-Time Communication

- **WebSocket vs. WebRTC:** WebSocket (`/api/v1/voice/stream/{agent_id}` and `/api/v1/voice/public/{slug}`) was chosen over WebRTC because it multiplexes binary 16kHz PCM16 / MP3 frames and JSON control events (`state`, `vad_prob`, `tool_confirm`, `rag_sources`, `interrupt`) over a single TLS/HTTP-compatible connection without ICE/STUN/TURN infrastructure. WebRTC remains a future upgrade for jitter-resilient UDP transport.
- **VAD Options:** `silero-onnx` (bundled via `faster-whisper`, zero PyTorch dependency) was selected as the primary VAD with `webrtcvad` as automatic fallback. Hysteresis (`0.6` start / `0.45` end), 200ms onset confirmation, adaptive RMS energy gating (`2.0x` noise floor), and a 12s hard cap prevent background noise from keeping turns open.
- **Whisper Model Sizes:** `base` had noticeable word-error rate on Indian English accents; upgrading to `small.en` (`int8`, CPU, `beam_size=1`, `cpu_threads=12`) improved English recognition while running in `1699.2 ms` for a 2s synthetic speech utterance.
- **Edge-TTS vs. Alternatives:** `edge-tts` provides free neural streaming MP3 synthesis (`~812.8–1203.3 ms` first audio in container probes). Local Piper or paid ElevenLabs/OpenAI TTS can be plugged into `BaseTTSProvider` for lower RTT or higher expressiveness.

---

## 4. System Architecture and Component Design

- **Frontend (`frontend/`):** Next.js 14 App Router (`next build` + `next start`) with an `AudioWorklet` (`/worklets/pcm16-processor.js`) capturing mono 16kHz PCM16 frames, `GaplessAudioPlayer` (`audioQueue.ts`) for queued MP3 playback with instant flush on `interrupt`/`audio_stop`, and a real-time Pipeline Inspector.
- **VoiceOrchestrator (`backend/app/services/voice_orchestrator.py`):** Explicit state machine (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`) enforcing valid transitions under an `asyncio.Lock`. Coordinates VAD -> STT -> RAG -> LLM/Tools -> `StreamingSentenceSplitter` (sentence boundaries + commas after 8 words) -> TTS -> PostgreSQL persistence.

---

## 5. Database Schema and API Architecture

- **Models (`backend/app/models/`):**
  - `users`: authentication credentials (`bcrypt`).
  - `user_api_keys`: per-user Fernet-encrypted provider keys.
  - `agents`: prompt, model, voice, language, `is_published`, `slug`, many-to-many `agent_tools`.
  - `documents` & `document_chunks`: `UniversalVector(768)` column with PostgreSQL HNSW cosine index (`ix_document_chunks_embedding_hnsw`).
  - `tools`: JSON schema, `execution_type` (`mock`/`webhook`/`built_in`), webhook config, `is_sensitive`.
  - `call_sessions` & `conversation_messages`: `user_id` (nullable for public calls), `error_count`, `last_error`, per-stage latencies, `rag_sources_json`, `tool_calls_json`, `tool_results_json`, `interrupted`.
- **Routers (`backend/app/api/v1/`):** `/auth`, `/agents`, `/chat`, `/voice`, `/knowledge`, `/tools`, `/analytics`, `/health`.

---

## 6. AI Model and Provider Selection with Justification

- **Primary LLM (`gemini-3.5-flash-lite`) & Fallback (`gemini-3.8-flash`):** Selected for low cost/latency and native function calling. Using `scripts/profile_gemini_stream.py` inside `voiceagent_backend`, we proved:
  - `first_byte_ms == first_token_ms` (`1245.7 ms` vs `1245.8 ms` warm; `1609.6 ms` cold; `1135.7 ms` without `thinkingConfig`), confirming Gemini API/network RTT—not SSE parsing—dominates TTFT.
  - `thinkingBudget: 0` and `thinkingLevel: "none"` both return `HTTP 400` on `gemini-3.5-flash-lite`; `thinkingLevel: "minimal"` is the lowest valid setting and returns `HTTP 200`.
  - Persistent `httpx.AsyncClient` keep-alive + `maxOutputTokens: 150` + WebSocket-connect pre-warm eliminate cold TLS overhead.
  - Retries (`1` on `8s` first-token timeout, `2` exponential-backoff retries on `503/429`) + fallback to `gemini-3.8-flash` + spoken TTS fallback (`"Sorry, I had trouble. Could you repeat that?"`) prevent silent failures.
- **Embeddings (`gemini-embedding-001` @ 768-dim):** Replaces deprecated `text-embedding-004` via MRL `outputDimensionality=768` with unit L2 normalization.

---

## 7. Implementation Approach and Challenges Actually Faced

1. **AudioWorklet Serving:** Next.js dev/prod asset serving needed verification that `/worklets/pcm16-processor.js` returned `200 OK` with `application/javascript` rather than 404 HTML.
2. **Gemini 503/429 & Thinking Config:** Free-tier 15 RPM limits and transient 503s caused silent hangs until `LLM_FIRST_TOKEN_TIMEOUT_S=8`, retry/fallback, and `thinkingLevel: "minimal"` (discovered via live API probing after `thinkingBudget: 0` returned 400) were added.
3. **STT Accuracy & CPU Contention:** Upgraded `base` -> `small.en`, added `avg_logprob` / `no_speech_prob` filtering, and tuned `cpu_threads=12` (`1699.2 ms` vs `2423.0 ms` at 6 threads).
4. **VAD Noise Hysteresis:** Single-threshold VAD stayed stuck in `SPEAKING`/`LISTENING` under background noise; fixed with `0.60/0.45` hysteresis, 200ms onset confirmation, adaptive RMS noise floor, and 12s hard cap.
5. **Barge-in Debounce:** Added 250ms confirmed-speech debounce so echo/clicks do not cancel TTS, while preserving the onset audio buffer for the interrupting utterance.
6. **SQLite vs. PostgreSQL Vector Type:** `UniversalVector(768)` maps to `pgvector.Vector(768)` on PostgreSQL and JSON `Text` on SQLite so unit tests run cleanly without Postgres, while Docker tests hit real Postgres (`test_rag_retrieval_ranking_with_fake_embeddings` uses an isolated in-memory SQLite engine to avoid `asyncpg` cross-loop pool errors).

---

## 8. Testing Methodology and AI Evaluation

- **Automated Suite (`docker compose exec backend pytest --cov=app`):** `44 passed in 18.34s`, `65%` coverage across auth, vault, agents, chat streaming, VAD, barge-in, RAG, tools/SSRF, public agents, and analytics.
- **RAG Evaluation (`scripts/eval_rag.py` on 20 in-knowledge + 5 out-of-knowledge Qs):** `100.0%` top-4 retrieval hit rate, `100.0%` keyword match accuracy, `1.000 / 1.0` Gemini LLM-as-judge average, `100.0%` out-of-knowledge abstention; `1199.5 ms` avg retrieval, `1238.0 ms` avg LLM TTFT.
- **Load Check (`scripts/load_check.py`):** 10 concurrent text chats completed with `0` errors (`avg=745.6 ms`, `p95=1396.3 ms`).

---

## 9. Security, Scalability, and Optimization

- **Implemented:** Fernet AES-256 vault, HS256 JWT, strict `user_id` isolation, Redis per-user/per-IP rate limiting, post-DNS SSRF blocking, sensitive tool confirmation gate, and startup validation rejecting missing/placeholder secrets.
- **Next Steps for Scale:** Stateless backend workers behind sticky WebSocket load balancing, Redis Pub/Sub for distributed session state, dedicated GPU STT workers (or Deepgram streaming STT) to cut STT from `~1.7s` to `<300ms` (estimate), and asynchronous background queues (Celery/ARQ) for large document ingestion.

---

## 10. Future Improvements

- **Telephony Integration:** SIP/PSTN bridge (Twilio Media Streams or LiveKit) for inbound/outbound phone calls.
- **WebRTC Transport:** Optional WebRTC data/audio tracks for lossy mobile networks.
- **Streaming STT:** Token-by-token incremental STT (e.g., Deepgram Nova or Whisper streaming) to overlap transcription with speech.
- **Multi-Language Auto-Detection:** Dynamic language switching across STT, LLM, and TTS voices.
- **CI Evals:** Run `eval_rag.py` and `pytest --cov` automatically on pull requests with regression thresholds.
