"""Documents router – list, get, update, delete."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.document import Document

router = APIRouter()


class TagOut(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    s3_key: str
    content_type: str | None
    sha256: str | None
    ocr_status: str
    category: str | None
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[DocumentOut])
async def list_documents(
    category: str | None = None,
    tag: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Document).options(selectinload(Document.tags))
    if category:
        stmt = stmt.where(Document.category == category)
    result = await db.execute(stmt)
    docs = result.scalars().all()
    if tag:
        docs = [d for d in docs if any(t.name == tag for t in d.tags)]
    return docs


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document).where(Document.id == doc_id).options(selectinload(Document.tags))
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await db.delete(doc)
    await db.commit()
