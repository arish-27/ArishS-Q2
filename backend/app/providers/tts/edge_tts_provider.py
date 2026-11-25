import asyncio
from typing import AsyncIterator, Optional
import edge_tts
from app.core.config import settings
from app.core.logger import logger
from app.providers.tts.base import BaseTTSProvider, TTSProviderError


class EdgeTTSProvider(BaseTTSProvider):
    """
    Free neural streaming TTS provider using Microsoft Edge Read Aloud voices.
    Streams MP3 chunks directly without writing intermediate audio files.
    """

    DEFAULT_VOICE = settings.DEFAULT_TTS_VOICE

    async def synthesize_stream(
        self,
        text: str,
        voice: str = "",
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[bytes]:
        clean = (text or "").strip()
        if not clean:
            return

        target_voice = (voice or self.DEFAULT_VOICE).strip()
        try:
            communicate = edge_tts.Communicate(text=clean, voice=target_voice)
            async for chunk in communicate.stream():
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("EdgeTTS synthesis cancelled mid-stream.")
                    break
                if chunk.get("type") == "audio" and chunk.get("data"):
                    yield chunk["data"]
        except Exception as exc:
            logger.error(f"EdgeTTS synthesis error for voice '{target_voice}': {exc}")
            raise TTSProviderError(f"TTS synthesis failed: {exc}") from exc
