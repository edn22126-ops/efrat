"""Upload router – generate pre-signed S3 URL and register document metadata."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.aws import compute_audit_hash, enqueue_ocr_job, generate_presigned_upload_url
from app.db.session import get_db
from app.models.document import AuditLog, Document, Tag

router = APIRouter()


class PresignedRequest(BaseModel):
    filename: str
    content_type: str
    category: str | None = None
    tags: list[str] = []


class PresignedResponse(BaseModel):
    document_id: uuid.UUID
    upload_url: str
    s3_key: str


@router.post("/presign", response_model=PresignedResponse)
async def request_presigned_url(
    body: PresignedRequest,
    db: AsyncSession = Depends(get_db),
):
    """Return a pre-signed S3 PUT URL.  Client uploads the file directly to S3, then calls /confirm."""
    doc_id = uuid.uuid4()
    s3_key = f"documents/{doc_id}/{body.filename}"

    try:
        upload_url = generate_presigned_upload_url(s3_key, body.content_type)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not generate presigned URL: {exc}",
        )

    doc = Document(
        id=doc_id,
        filename=body.filename,
        s3_key=s3_key,
        content_type=body.content_type,
        category=body.category,
        ocr_status="pending",
    )
    db.add(doc)

    for tag_name in body.tags:
        db.add(Tag(document_id=doc_id, name=tag_name.strip()))

    entry_hash = compute_audit_hash(str(doc_id), "presign_requested", f"key={s3_key}", None)
    db.add(
        AuditLog(
            document_id=doc_id,
            action="presign_requested",
            detail=f"key={s3_key}",
            prev_hash=None,
            entry_hash=entry_hash,
        )
    )

    await db.commit()
    await db.refresh(doc)

    return PresignedResponse(document_id=doc_id, upload_url=upload_url, s3_key=s3_key)


class ConfirmRequest(BaseModel):
    document_id: uuid.UUID
    sha256: str | None = None


@router.post("/confirm")
async def confirm_upload(body: ConfirmRequest, db: AsyncSession = Depends(get_db)):
    """Called after client has PUT the file to S3.  Triggers OCR job."""

    result = await db.execute(select(Document).where(Document.id == body.document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    doc.sha256 = body.sha256

    prev_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.document_id == doc.id)
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    prev_log = prev_result.scalar_one_or_none()
    prev_hash = prev_log.entry_hash if prev_log else None
    detail = f"sha256={body.sha256}"
    entry_hash = compute_audit_hash(str(doc.id), "upload_confirmed", detail, prev_hash)
    db.add(
        AuditLog(
            document_id=doc.id,
            action="upload_confirmed",
            detail=detail,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
    )

    await db.commit()

    enqueue_ocr_job(str(doc.id), doc.s3_key)

    return {"status": "queued", "document_id": str(doc.id)}
