import io
import json
import re
from typing import Any, Dict, List, Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logger import logger
from app.models.document import Document, DocumentChunk
from app.providers.embeddings.base import BaseEmbeddingProvider
from app.providers.embeddings.gemini_embedding import GeminiEmbeddingProvider, l2_normalize


def extract_text_from_bytes(file_bytes: bytes, file_type: str) -> str:
    """Extracts plain text from PDF, DOCX, or TXT file bytes."""
    ext = (file_type or "").lower().lstrip(".")
    if ext == "txt":
        return file_bytes.decode("utf-8", errors="replace").strip()

    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                pages.append(txt.strip())
        return "\n\n".join(pages).strip()

    if ext == "docx":
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(file_bytes))
        parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    parts.append(row_text)
        return "\n\n".join(parts).strip()

    raise ValueError(f"Unsupported file type: {file_type}")


def chunk_text(
    text_content: str,
    chunk_tokens: int = settings.RAG_CHUNK_SIZE_TOKENS,
    overlap_tokens: int = settings.RAG_CHUNK_OVERLAP_TOKENS,
) -> List[str]:
    """
    Splits text into overlapping ~chunk_tokens word-token windows.
    Maintains `overlap_tokens` overlap between consecutive chunks.
    """
    if not text_content or not text_content.strip():
        return []

    normalized = re.sub(r"\s+", " ", text_content).strip()
    words = normalized.split(" ")
    if len(words) <= chunk_tokens:
        return [normalized]

    safe_chunk = max(50, int(chunk_tokens))
    safe_overlap = max(0, min(int(overlap_tokens), safe_chunk - 1))
    step = max(1, safe_chunk - safe_overlap)

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + safe_chunk)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
        start += step

    return chunks


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a = l2_normalize(vec_a)
    b = l2_normalize(vec_b)
    return sum(x * y for x, y in zip(a, b))


async def process_document_background(
    document_id: str,
    file_bytes: bytes,
    file_type: str,
    agent_id: str,
    api_key: str,
    db_session_factory=AsyncSessionLocal,
    embedding_provider: Optional[BaseEmbeddingProvider] = None,
) -> None:
    """
    Background ingestion pipeline:
    extract text -> chunk (~500 tokens w/ overlap) -> embed (gemini-embedding-001, 768-dim)
    -> store DocumentChunk rows -> update Document.status ('indexed' or 'failed').
    """
    provider = embedding_provider or GeminiEmbeddingProvider(api_key=api_key)
    async with db_session_factory() as db:
        doc = await db.get(Document, document_id)
        if not doc:
            logger.warning(f"RAG ingestion skipped: document {document_id} not found.")
            return

        try:
            raw_text = extract_text_from_bytes(file_bytes, file_type)
            if not raw_text:
                raise ValueError("No extractable text found in uploaded document.")

            chunks = chunk_text(raw_text)
            if not chunks:
                raise ValueError("Document produced zero chunks.")

            for idx, chunk_str in enumerate(chunks):
                vec = await provider.embed_text(chunk_str, task_type="RETRIEVAL_DOCUMENT")
                db.add(
                    DocumentChunk(
                        document_id=document_id,
                        agent_id=agent_id,
                        chunk_index=idx,
                        content=chunk_str,
                        embedding=vec,
                        metadata_json=json.dumps({"filename": doc.filename, "chunk_index": idx}),
                    )
                )

            doc.status = "indexed"
            await db.commit()
            logger.info(
                f"RAG indexed document_id={document_id} filename={doc.filename!r} chunks={len(chunks)}"
            )
        except Exception as exc:
            await db.rollback()
            doc = await db.get(Document, document_id)
            if doc:
                doc.status = "failed"
                await db.commit()
            logger.error(f"RAG ingestion failed document_id={document_id}: {exc}")


async def retrieve_relevant_chunks(
    db: AsyncSession,
    agent_id: str,
    query: str,
    api_key: str,
    top_k: int = settings.RAG_TOP_K,
    similarity_threshold: float = settings.RAG_SIMILARITY_THRESHOLD,
    embedding_provider: Optional[BaseEmbeddingProvider] = None,
) -> List[Dict[str, Any]]:
    """
    Embeds `query` and returns top-k indexed chunks for `agent_id` above `similarity_threshold`.
    Uses native pgvector HNSW cosine distance (`<=>`) on PostgreSQL and exact cosine on SQLite.
    """
    if not query or not query.strip():
        return []

    provider = embedding_provider or GeminiEmbeddingProvider(api_key=api_key)
    query_vec = await provider.embed_text(query.strip(), task_type="RETRIEVAL_QUERY")

    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "sqlite"

    if dialect_name == "postgresql":
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in query_vec) + "]"
        sql = text(
            """
            SELECT
                dc.document_id AS document_id,
                d.filename AS filename,
                dc.chunk_index AS chunk_index,
                dc.content AS content,
                (1.0 - (dc.embedding <=> CAST(:qvec AS vector))) AS score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.agent_id = :agent_id
              AND d.status = 'indexed'
              AND dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> CAST(:qvec AS vector) ASC
            LIMIT :top_k
            """
        )
        rows = (
            await db.execute(
                sql,
                {"qvec": vec_literal, "agent_id": agent_id, "top_k": max(1, int(top_k))},
            )
        ).mappings().all()

        results = []
        for r in rows:
            score = float(r["score"])
            if score >= similarity_threshold:
                results.append(
                    {
                        "document_id": r["document_id"],
                        "filename": r["filename"],
                        "chunk_index": int(r["chunk_index"]),
                        "content": r["content"],
                        "score": round(score, 4),
                    }
                )
        return results

    # SQLite fallback for unit tests
    stmt = (
        select(DocumentChunk, Document.filename)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.agent_id == agent_id,
            Document.status == "indexed",
            DocumentChunk.embedding.isnot(None),
        )
    )
    rows = (await db.execute(stmt)).all()

    scored: List[Dict[str, Any]] = []
    for chunk_row, filename in rows:
        emb = chunk_row.embedding
        if not isinstance(emb, list):
            continue
        score = _cosine_similarity(query_vec, emb)
        if score >= similarity_threshold:
            scored.append(
                {
                    "document_id": chunk_row.document_id,
                    "filename": filename,
                    "chunk_index": int(chunk_row.chunk_index),
                    "content": chunk_row.content,
                    "score": round(score, 4),
                }
            )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[: max(1, int(top_k))]
