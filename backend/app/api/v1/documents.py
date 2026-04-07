import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document import AuditLog, Document, DocumentVersion, Tag
from app.services.aws import enqueue_ocr_job, generate_presigned_upload_url

router = APIRouter(prefix="/documents", tags=["documents"])


# ─── Pydantic schemas ────────────────────────────────────────────────────────


class TagIn(BaseModel):
    name: str
    category: Optional[str] = None


class DocumentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    tags: List[TagIn] = []


class VersionOut(BaseModel):
    id: uuid.UUID
    version_number: int
    s3_key: str
    sha256: Optional[str]
    mime_type: Optional[str]
    file_size: Optional[int]
    ocr_status: str
    ocr_text: Optional[str]

    model_config = {"from_attributes": True}


class TagOut(BaseModel):
    id: int
    name: str
    category: Optional[str]

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str]
    tags: List[TagOut]
    versions: List[VersionOut]

    model_config = {"from_attributes": True}


class UploadInitRequest(BaseModel):
    document_id: Optional[uuid.UUID] = None  # omit to create a new document
    title: str
    description: Optional[str] = None
    mime_type: str = "application/octet-stream"
    file_name: str
    tags: List[TagIn] = []


class UploadInitResponse(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    s3_key: str
    presigned_post: dict  # forward the S3 pre-signed POST to the client


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get_or_create_tags(db: Session, tags: List[TagIn]) -> List[Tag]:
    result = []
    for tag_in in tags:
        tag = db.query(Tag).filter(Tag.name == tag_in.name).first()
        if not tag:
            tag = Tag(name=tag_in.name, category=tag_in.category)
            db.add(tag)
            db.flush()
        result.append(tag)
    return result


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/upload/init", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
def init_upload(payload: UploadInitRequest, db: Session = Depends(get_db)):
    """
    Step 1 of upload flow:
    - Create (or retrieve) a Document record.
    - Create a new DocumentVersion record.
    - Return a pre-signed S3 POST URL for the client to push the file directly.
    After the client uploads to S3 it should call /documents/{doc_id}/versions/{ver_id}/confirm.
    """
    # Upsert document
    if payload.document_id:
        doc = db.query(Document).filter(Document.id == payload.document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
    else:
        doc = Document(title=payload.title, description=payload.description)
        db.add(doc)
        db.flush()

    # Tags
    tag_objs = _get_or_create_tags(db, payload.tags)
    for t in tag_objs:
        if t not in doc.tags:
            doc.tags.append(t)

    # Version number
    version_number = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == doc.id)
        .count()
        + 1
    )

    # S3 key: docs/{doc_id}/{version}/{filename}
    safe_name = payload.file_name.replace(" ", "_")
    s3_key = f"docs/{doc.id}/{version_number}/{safe_name}"

    version = DocumentVersion(
        document_id=doc.id,
        version_number=version_number,
        s3_key=s3_key,
        mime_type=payload.mime_type,
        ocr_status="pending",
    )
    db.add(version)

    # Audit log
    db.add(AuditLog(document_id=doc.id, action="upload_initiated", detail=s3_key))

    db.commit()
    db.refresh(doc)
    db.refresh(version)

    presigned = generate_presigned_upload_url(s3_key, payload.mime_type)

    return UploadInitResponse(
        document_id=doc.id,
        version_id=version.id,
        s3_key=s3_key,
        presigned_post=presigned,
    )


@router.post("/{document_id}/versions/{version_id}/confirm", response_model=VersionOut)
def confirm_upload(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    sha256: Optional[str] = Query(None, description="SHA-256 hex digest of the uploaded file"),
    file_size: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Step 2: Called after the client has successfully PUT the file to S3.
    Optionally accepts sha256 + file_size for immutability audit.
    Enqueues an OCR job on SQS.
    """
    version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.id == version_id, DocumentVersion.document_id == document_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if sha256:
        version.sha256 = sha256
    if file_size is not None:
        version.file_size = file_size

    version.ocr_status = "queued"

    msg_id = enqueue_ocr_job(str(version.id), version.s3_key)

    db.add(
        AuditLog(
            document_id=document_id,
            action="upload_confirmed",
            detail=f"sha256={sha256} sqs_msg={msg_id}",
        )
    )
    db.commit()
    db.refresh(version)
    return version


@router.get("", response_model=List[DocumentOut])
def list_documents(
    q: Optional[str] = Query(None, description="Search query (title, tags, OCR text)"),
    tag: Optional[str] = Query(None, description="Filter by tag name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List documents with optional full-text search (title / tag / OCR text)."""
    query = db.query(Document)

    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                Document.title.ilike(pattern),
                Document.description.ilike(pattern),
                Document.versions.any(DocumentVersion.ocr_text.ilike(pattern)),
            )
        )

    if tag:
        query = query.filter(Document.tags.any(Tag.name == tag))

    return query.offset(skip).limit(limit).all()


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
