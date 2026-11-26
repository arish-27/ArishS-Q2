from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.security import decrypt_secret
from app.models.agent import Agent
from app.models.document import Document, DocumentChunk
from app.models.user import User, UserApiKey
from app.schemas.knowledge import DocumentResponse, RagChunkResult, RagQueryRequest, RagQueryResponse
from app.services.rag_service import process_document_background, retrieve_relevant_chunks

router = APIRouter()

ALLOWED_EXTENSIONS = {"pdf", "txt", "docx"}


async def _resolve_gemini_key(user: User, db: AsyncSession) -> str:
    res = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == user.id, UserApiKey.provider == "gemini")
    )
    row = res.scalar_one_or_none()
    if row:
        try:
            return decrypt_secret(row.encrypted_key)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to decrypt stored Gemini API key: {exc}",
            )
    if settings.GEMINI_API_KEY:
        return settings.GEMINI_API_KEY
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="A Gemini API key is required for embeddings (gemini-embedding-001). Add one in the API Key Vault or .env.",
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    agent_id: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF, TXT, or DOCX document for an owned agent and index it asynchronously."""
    agent_res = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == current_user.id)
    )
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    filename = Path(file.filename or "document.txt").name
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Allowed: pdf, txt, docx.",
        )

    file_bytes = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size ({settings.MAX_UPLOAD_SIZE_MB} MB).",
        )

    api_key = await _resolve_gemini_key(current_user, db)

    doc = Document(
        user_id=current_user.id,
        agent_id=agent.id,
        filename=filename,
        file_type=ext,
        file_size=len(file_bytes),
        status="processing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(
        process_document_background,
        document_id=doc.id,
        file_bytes=file_bytes,
        file_type=ext,
        agent_id=agent.id,
        api_key=api_key,
        db_session_factory=AsyncSessionLocal,
    )

    return DocumentResponse(
        id=doc.id,
        user_id=doc.user_id,
        agent_id=doc.agent_id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        chunk_count=0,
        created_at=doc.created_at,
    )


@router.get("", response_model=List[DocumentResponse])
async def list_knowledge_documents(
    agent_id: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents owned by the current user, optionally filtered by agent_id."""
    stmt = (
        select(Document, func.count(DocumentChunk.id).label("chunk_count"))
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == current_user.id)
    )
    if agent_id:
        stmt = stmt.where(Document.agent_id == agent_id)
    stmt = stmt.group_by(Document.id).order_by(Document.created_at.desc())

    rows = (await db.execute(stmt)).all()
    return [
        DocumentResponse(
            id=doc.id,
            user_id=doc.user_id,
            agent_id=doc.agent_id,
            filename=doc.filename,
            file_type=doc.file_type,
            file_size=doc.file_size,
            status=doc.status,
            chunk_count=int(chunk_count or 0),
            created_at=doc.created_at,
        )
        for doc, chunk_count in rows
    ]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an owned knowledge document and its chunks."""
    res = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    await db.delete(doc)
    await db.commit()
    return None


@router.post("/query-test", response_model=RagQueryResponse)
async def query_test_knowledge(
    payload: RagQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test vector retrieval for an owned agent and return top matching chunks."""
    agent_res = await db.execute(
        select(Agent).where(Agent.id == payload.agent_id, Agent.user_id == current_user.id)
    )
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    api_key = await _resolve_gemini_key(current_user, db)
    chunks = await retrieve_relevant_chunks(
        db=db,
        agent_id=agent.id,
        query=payload.query,
        api_key=api_key,
        top_k=payload.top_k,
        similarity_threshold=payload.similarity_threshold,
    )
    return RagQueryResponse(
        agent_id=agent.id,
        query=payload.query,
        results=[RagChunkResult(**c) for c in chunks],
    )
