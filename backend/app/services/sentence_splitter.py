import re
from typing import List

ABBREVIATIONS = (
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
    "st.", "vs.", "etc.", "e.g.", "i.e.", "u.s.", "u.k.", "inc.", "ltd.",
)


def clean_for_tts(text: str) -> str:
    """Strips markdown syntax and normalizes whitespace so TTS speaks natural prose."""
    if not text:
        return ""
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"[*_~#>]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


class StreamingSentenceSplitter:
    """
    Buffers streamed LLM tokens and emits complete speakable sentences or clauses
    as soon as boundaries appear, enabling low-latency sentence-level TTS streaming.
    """

    def __init__(self, min_sentence_chars: int = 12, min_clause_words: int = 8):
        self.min_sentence_chars = min_sentence_chars
        self.min_clause_words = min_clause_words
        self._buffer = ""

    def _is_real_boundary(self, text: str, idx: int) -> bool:
        ch = text[idx]
        # Require trailing whitespace after punctuation so mid-word/decimal dots aren't split
        if idx + 1 >= len(text) or not text[idx + 1].isspace():
            return False

        if ch == "\n":
            return True

        # Avoid splitting decimal numbers like 3.14 or grouped numbers like 1,000
        if ch in (".", ",") and idx > 0 and text[idx - 1].isdigit():
            if idx + 1 < len(text) and text[idx + 1].isdigit():
                return False

        # Clause boundary (comma/semicolon/colon): split once enough words accumulated
        if ch in (",", ";", ":"):
            words = text[: idx + 1].strip().split()
            return len(words) >= self.min_clause_words

        # Avoid splitting common abbreviations like "Dr. Smith"
        prefix = text[: idx + 1].lower().rstrip()
        if ch == "." and any(prefix.endswith(abbr) for abbr in ABBREVIATIONS):
            return False

        candidate = text[: idx + 1].strip()
        return len(candidate) >= self.min_sentence_chars

    def feed(self, token: str) -> List[str]:
        """Appends a streamed token and returns any newly completed sentences or clauses."""
        if not token:
            return []
        self._buffer += token
        emitted: List[str] = []

        while True:
            split_pos = -1
            for i, ch in enumerate(self._buffer):
                if ch in (".", "!", "?", "\n", ",", ";", ":") and self._is_real_boundary(self._buffer, i):
                    split_pos = i
                    break

            if split_pos == -1:
                break

            raw_sentence = self._buffer[: split_pos + 1]
            self._buffer = self._buffer[split_pos + 1 :].lstrip()
            cleaned = clean_for_tts(raw_sentence)
            if cleaned:
                emitted.append(cleaned)

        return emitted

    def flush(self) -> List[str]:
        """Flushes any remaining buffered text at the end of the LLM response."""
        remaining = clean_for_tts(self._buffer)
        self._buffer = ""
        return [remaining] if remaining else []
