"""Upload router – generate pre-signed S3 URL and register document metadata."""
import hashlib
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.aws import generate_presigned_upload_url, enqueue_ocr_job
from app.db.session import get_db
from app.models.document import Document, Tag, AuditLog

router = APIRouter()


class PresignedRequest(BaseModel):
    filename: str
    content_type: str
    category: Optional[str] = None
    tags: List[str] = []


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

    db.add(
        AuditLog(document_id=doc_id, action="presign_requested", detail=f"key={s3_key}")
    )

    await db.commit()
    await db.refresh(doc)

    return PresignedResponse(document_id=doc_id, upload_url=upload_url, s3_key=s3_key)


class ConfirmRequest(BaseModel):
    document_id: uuid.UUID
    sha256: Optional[str] = None


@router.post("/confirm")
async def confirm_upload(body: ConfirmRequest, db: AsyncSession = Depends(get_db)):
    """Called after client has PUT the file to S3.  Triggers OCR job."""
    from sqlalchemy import select

    result = await db.execute(select(Document).where(Document.id == body.document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    doc.sha256 = body.sha256
    db.add(AuditLog(document_id=doc.id, action="upload_confirmed", detail=f"sha256={body.sha256}"))

    await db.commit()

    enqueue_ocr_job(str(doc.id), doc.s3_key)

    return {"status": "queued", "document_id": str(doc.id)}
