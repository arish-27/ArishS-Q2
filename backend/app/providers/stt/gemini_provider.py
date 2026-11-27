import asyncio
import base64
import io
import time
import wave
from typing import Dict, Optional
import httpx
from app.core.config import settings
from app.core.logger import logger
from app.providers.stt.base import BaseSTTProvider, STTResult
from app.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider

_GEMINI_STT_CLIENTS: Dict[int, httpx.AsyncClient] = {}


def get_gemini_stt_http_client(timeout_s: float = 4.0) -> httpx.AsyncClient:
    """Returns a persistent keep-alive httpx.AsyncClient scoped to the active event loop."""
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    client = _GEMINI_STT_CLIENTS.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=timeout_s, read=timeout_s, write=timeout_s, pool=timeout_s),
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=60.0,
            ),
        )
        _GEMINI_STT_CLIENTS[loop_id] = client
    return client


def pcm16_to_wav_bytes(audio_pcm16: bytes, sample_rate: int = 16000) -> bytes:
    """Wraps raw 16-bit signed mono PCM audio bytes in a standard WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_pcm16)
    return buf.getvalue()


class GeminiSTTProvider(BaseSTTProvider):
    """
    Cloud Speech-to-Text provider using Gemini generateContent inline WAV audio.
    Automatically falls back to FasterWhisperSTTProvider on missing key, 429, 5xx, or timeout.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = settings.GEMINI_STT_MODEL,
        timeout_s: float = settings.GEMINI_STT_TIMEOUT_S,
        max_retries: int = 1,
        fallback_provider: Optional[BaseSTTProvider] = None,
    ):
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout_s = float(timeout_s)
        self.max_retries = max(0, int(max_retries))
        self.fallback_provider = fallback_provider or FasterWhisperSTTProvider()

    def _build_prompt(self, language: str, context_prompt: Optional[str]) -> str:
        lang = (language or "en").strip().lower()
        if lang.startswith("en"):
            prompt = (
                "Transcribe this audio verbatim. The speaker is speaking English with an Indian accent "
                "(pay careful attention to Indian names, cities, and technical terms). "
                "Return only the exact transcribed text, nothing else. If there is no speech, return an empty string."
            )
        else:
            prompt = (
                f"Transcribe this audio verbatim in language '{lang}'. "
                "Return only the transcribed text, nothing else. If there is no speech, return an empty string."
            )
        if context_prompt and context_prompt.strip():
            prompt += f" Context vocabulary (prefer these terms if phonetically similar): {context_prompt.strip()}."
        return prompt

    async def _fallback(
        self,
        reason: str,
        audio_pcm16: bytes,
        sample_rate: int,
        language: str,
        context_prompt: Optional[str],
    ) -> STTResult:
        logger.warning(f"GeminiSTT fallback to faster-whisper reason={reason}")
        try:
            res = await self.fallback_provider.transcribe(
                audio_pcm16,
                sample_rate=sample_rate,
                language=language,
                context_prompt=context_prompt,
            )
        except TypeError:
            res = await self.fallback_provider.transcribe(
                audio_pcm16,
                sample_rate=sample_rate,
                language=language,
            )
        if not getattr(res, "provider", None):
            res.provider = "faster-whisper"
        return res

    async def transcribe(
        self,
        audio_pcm16: bytes,
        sample_rate: int = 16000,
        language: str = "en",
        context_prompt: Optional[str] = None,
    ) -> STTResult:
        if not audio_pcm16 or len(audio_pcm16) < 3200:
            return STTResult(
                text="",
                language=language,
                duration_ms=0.0,
                latency_ms=0.0,
                provider="gemini",
            )

        if not self.api_key:
            return await self._fallback("missing_api_key", audio_pcm16, sample_rate, language, context_prompt)

        duration_ms = (len(audio_pcm16) / 2.0 / float(sample_rate)) * 1000.0
        wav_bytes = pcm16_to_wav_bytes(audio_pcm16, sample_rate=sample_rate)
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": self._build_prompt(language, context_prompt)},
                        {"inlineData": {"mimeType": "audio/wav", "data": audio_b64}},
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 256,
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }

        client = get_gemini_stt_http_client(self.timeout_s)
        last_reason = "unknown_error"

        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                response = await client.post(url, json=payload, timeout=self.timeout_s)
                latency_ms = (time.perf_counter() - start) * 1000.0

                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates") or []
                    text_parts = []
                    if candidates:
                        parts = (candidates[0].get("content") or {}).get("parts") or []
                        for part in parts:
                            txt = part.get("text")
                            if txt:
                                text_parts.append(txt)
                    transcript = " ".join(text_parts).strip()
                    logger.info(
                        f"GeminiSTT success model={self.model} attempt={attempt + 1} "
                        f"latency_ms={latency_ms:.1f} audio_ms={duration_ms:.1f} text={transcript!r}"
                    )
                    return STTResult(
                        text=transcript,
                        language=language,
                        duration_ms=round(duration_ms, 2),
                        latency_ms=round(latency_ms, 2),
                        provider="gemini",
                    )

                if response.status_code == 429 or response.status_code >= 500:
                    last_reason = f"http_{response.status_code}"
                    logger.warning(
                        f"GeminiSTT transient error status={response.status_code} "
                        f"attempt={attempt + 1}/{self.max_retries + 1}"
                    )
                else:
                    last_reason = f"http_{response.status_code}"
                    logger.warning(
                        f"GeminiSTT non-retryable error status={response.status_code}: {response.text[:200]}"
                    )
                    break
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_reason = f"{type(exc).__name__}"
                logger.warning(
                    f"GeminiSTT request error={last_reason} attempt={attempt + 1}/{self.max_retries + 1}: {exc}"
                )
            except Exception as exc:
                last_reason = f"{type(exc).__name__}"
                logger.warning(f"GeminiSTT unexpected error={last_reason}: {exc}")
                break

        return await self._fallback(last_reason, audio_pcm16, sample_rate, language, context_prompt)
