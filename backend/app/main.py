"""PLMS – Personal Legal/Document Management System.

FastAPI application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import documents, search, upload
from app.models import base  # noqa: F401 – registers all ORM models

app = FastAPI(
    title="PLMS – Evidence Management API",
    description="Upload, index, search and audit personal legal evidence files.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/documents", tags=["Documents"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"])
app.include_router(search.router, prefix="/search", tags=["Search"])


@app.get("/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
