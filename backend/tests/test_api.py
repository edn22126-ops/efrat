"""Smoke tests for PLMS backend API.

Uses an in-memory SQLite database (StaticPool) to avoid needing Postgres.
AWS calls are mocked so tests run offline.
"""
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models.base import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_list_documents_empty(client):
    response = await client.get("/documents/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_presign_and_confirm(client):
    fake_url = "https://s3.example.com/presigned"

    with (
        patch("app.api.upload.generate_presigned_upload_url", return_value=fake_url),
        patch("app.api.upload.enqueue_ocr_job"),
    ):
        presign_resp = await client.post(
            "/upload/presign",
            json={
                "filename": "evidence.pdf",
                "content_type": "application/pdf",
                "category": "legal",
                "tags": ["invoice", "2024"],
            },
        )
        assert presign_resp.status_code == 200
        data = presign_resp.json()
        assert data["upload_url"] == fake_url
        doc_id = data["document_id"]

        confirm_resp = await client.post(
            "/upload/confirm",
            json={"document_id": doc_id, "sha256": "abc123"},
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == "queued"

        get_resp = await client.get(f"/documents/{doc_id}")
        assert get_resp.status_code == 200
        doc = get_resp.json()
        assert doc["filename"] == "evidence.pdf"
        assert doc["sha256"] == "abc123"
        assert len(doc["tags"]) == 2
