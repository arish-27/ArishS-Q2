import os
import re
from collections import Counter
from typing import Iterable, List, Optional, Sequence, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.agent import Agent
from app.models.document import Document, DocumentChunk

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "will", "would", "could", "should", "can", "may",
    "into", "onto", "about", "over", "under", "between", "through", "during",
    "your", "you", "our", "their", "they", "them", "his", "her", "she", "him",
    "its", "not", "but", "all", "any", "each", "more", "most", "other", "some",
    "such", "only", "own", "same", "than", "too", "very", "just", "also", "been",
    "being", "both", "few", "how", "what", "when", "where", "which", "who", "why",
    "use", "used", "using", "work", "worked", "working", "project", "projects",
    "experience", "system", "systems", "based", "data", "time", "user", "users",
    "agent", "assistant", "voice", "helpful", "friendly", "concise",
}


def extract_distinctive_terms(texts: Sequence[str], max_terms: int = 20) -> List[str]:
    """Extracts distinctive domain terms, acronyms, and technical keywords from text chunks."""
    scores: Counter[str] = Counter()
    canonical: dict[str, str] = {}

    for text in texts:
        if not text:
            continue
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{1,30}", text):
            cleaned = token.strip(".-_")
            if len(cleaned) < 2:
                continue
            low = cleaned.lower()
            if low in _STOPWORDS:
                continue
            # Boost acronyms, CamelCase, alphanumeric identifiers, and longer domain words
            weight = 1.0
            if cleaned.isupper() and len(cleaned) >= 2:
                weight = 3.0
            elif any(c.isdigit() for c in cleaned) or any(c.isupper() for c in cleaned[1:]):
                weight = 2.5
            elif len(cleaned) >= 7:
                weight = 1.5
            scores[low] += weight
            if low not in canonical or (cleaned[0].isupper() and not canonical[low][0].isupper()):
                canonical[low] = cleaned

    ranked = [canonical[k] for k, _ in scores.most_common(max_terms)]
    return ranked


def build_vocab_hint_from_parts(
    agent_name: Optional[str] = None,
    agent_description: Optional[str] = None,
    tool_names: Iterable[str] = (),
    filenames: Iterable[str] = (),
    chunk_texts: Sequence[str] = (),
    extra_vocab: Optional[str] = None,
    max_terms: int = 40,
) -> str:
    """Builds a deduplicated comma-separated STT vocabulary hint string."""
    terms: List[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        val = " ".join((raw or "").strip().split())
        if not val or len(val) < 2:
            return
        low = val.lower()
        if low in seen or low in _STOPWORDS:
            return
        seen.add(low)
        terms.append(val)

    vocab_str = settings.STT_EXTRA_VOCAB if extra_vocab is None else extra_vocab
    for item in (vocab_str or "").split(","):
        _add(item)

    if agent_name:
        _add(agent_name)
    if agent_description:
        for term in extract_distinctive_terms([agent_description], max_terms=6):
            _add(term)

    for tool_name in tool_names:
        if tool_name:
            _add(tool_name.replace("_", " "))

    for fname in filenames:
        if fname:
            stem = os.path.splitext(os.path.basename(fname))[0]
            _add(re.sub(r"[_-]+", " ", stem))

    for term in extract_distinctive_terms(chunk_texts, max_terms=20):
        _add(term)

    return ", ".join(terms[:max_terms])


async def build_session_stt_vocab_hint(
    agent: Agent,
    db: AsyncSession,
    extra_vocab: Optional[str] = None,
) -> Tuple[str, bool]:
    """
    Loads agent documents/chunks from DB and builds a per-session STT vocabulary hint.
    Returns (vocab_hint, has_knowledge_base).
    """
    doc_rows = (
        await db.execute(
            select(Document.filename)
            .where(Document.agent_id == agent.id, Document.status == "indexed")
        )
    ).scalars().all()
    has_kb = len(doc_rows) > 0

    chunk_texts: List[str] = []
    if has_kb:
        chunk_texts = list(
            (
                await db.execute(
                    select(DocumentChunk.content)
                    .where(DocumentChunk.agent_id == agent.id)
                    .limit(50)
                )
            ).scalars().all()
        )

    tool_names = [t.name for t in (getattr(agent, "tools", None) or []) if getattr(t, "name", None)]
    hint = build_vocab_hint_from_parts(
        agent_name=getattr(agent, "name", None),
        agent_description=getattr(agent, "description", None),
        tool_names=tool_names,
        filenames=doc_rows,
        chunk_texts=chunk_texts,
        extra_vocab=extra_vocab,
    )
    return hint, has_kb
