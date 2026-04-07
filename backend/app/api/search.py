"""Search router – full-text search over OCR-extracted text."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.document import Document

router = APIRouter()


class SearchResult(BaseModel):
    id: str
    filename: str
    category: Optional[str]
    ocr_status: str
    snippet: Optional[str]

    model_config = {"from_attributes": True}


@router.get("/", response_model=List[SearchResult])
async def search_documents(
    q: str = Query(..., min_length=1, description="Search term"),
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Document).where(
        or_(
            Document.filename.ilike(f"%{q}%"),
            Document.ocr_text.ilike(f"%{q}%"),
        )
    )
    if category:
        stmt = stmt.where(Document.category == category)

    result = await db.execute(stmt)
    docs = result.scalars().all()

    out = []
    for doc in docs:
        snippet = None
        if doc.ocr_text:
            idx = doc.ocr_text.lower().find(q.lower())
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(doc.ocr_text), idx + 120)
                snippet = doc.ocr_text[start:end]
        out.append(
            SearchResult(
                id=str(doc.id),
                filename=doc.filename,
                category=doc.category,
                ocr_status=doc.ocr_status,
                snippet=snippet,
            )
        )
    return out
