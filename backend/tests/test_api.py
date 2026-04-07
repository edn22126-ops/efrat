"""
Tests for the PLMS API.

Uses an in-memory SQLite database so no Postgres or AWS credentials are needed.
Pre-signed S3 URLs and SQS calls are mocked.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.document  # noqa: F401 – register models with Base
from app.db.session import Base, get_db
from app.main import app

# ─── SQLite in-memory DB setup ───────────────────────────────────────────────

SQLITE_URL = "sqlite://"  # in-memory

engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)

# ─── Helpers ─────────────────────────────────────────────────────────────────

FAKE_PRESIGNED = {
    "url": "https://s3.example.com/upload",
    "fields": {"key": "docs/x/1/file.pdf", "Content-Type": "application/pdf"},
}


@patch("app.api.v1.documents.generate_presigned_upload_url", return_value=FAKE_PRESIGNED)
@patch("app.api.v1.documents.enqueue_ocr_job", return_value="fake-sqs-id")
def init_upload(mock_enqueue, mock_presigned, **kwargs):
    """Helper that calls upload/init and returns the JSON response."""
    payload = {
        "title": "Test Document",
        "mime_type": "application/pdf",
        "file_name": "test.pdf",
        "tags": [{"name": "evidence", "category": "legal"}],
    }
    resp = client.post("/api/v1/documents/upload/init", json=payload)
    return resp, mock_enqueue, mock_presigned


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@patch("app.api.v1.documents.generate_presigned_upload_url", return_value=FAKE_PRESIGNED)
@patch("app.api.v1.documents.enqueue_ocr_job", return_value="")
def test_init_upload_creates_document(mock_enqueue, mock_presigned):
    payload = {
        "title": "Contract 2024",
        "mime_type": "application/pdf",
        "file_name": "contract.pdf",
        "tags": [{"name": "contract", "category": "legal"}],
    }
    resp = client.post("/api/v1/documents/upload/init", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "document_id" in data
    assert "version_id" in data
    assert "presigned_post" in data
    assert data["presigned_post"] == FAKE_PRESIGNED
    mock_presigned.assert_called_once()


@patch("app.api.v1.documents.generate_presigned_upload_url", return_value=FAKE_PRESIGNED)
@patch("app.api.v1.documents.enqueue_ocr_job", return_value="fake-sqs-id")
def test_confirm_upload(mock_enqueue, mock_presigned):
    # First init
    init_payload = {
        "title": "Audio Recording",
        "mime_type": "audio/mpeg",
        "file_name": "recording.mp3",
        "tags": [],
    }
    init_resp = client.post("/api/v1/documents/upload/init", json=init_payload)
    assert init_resp.status_code == 201
    init_data = init_resp.json()

    doc_id = init_data["document_id"]
    ver_id = init_data["version_id"]

    # Confirm
    confirm_resp = client.post(
        f"/api/v1/documents/{doc_id}/versions/{ver_id}/confirm",
        params={"sha256": "abc123", "file_size": 1024},
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["ocr_status"] == "queued"
    assert confirm_data["sha256"] == "abc123"
    mock_enqueue.assert_called_once()


@patch("app.api.v1.documents.generate_presigned_upload_url", return_value=FAKE_PRESIGNED)
@patch("app.api.v1.documents.enqueue_ocr_job", return_value="")
def test_list_documents(mock_enqueue, mock_presigned):
    # Create two documents
    for title in ["Alpha Doc", "Beta Doc"]:
        client.post(
            "/api/v1/documents/upload/init",
            json={"title": title, "mime_type": "text/plain", "file_name": "f.txt", "tags": []},
        )

    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 2
    titles = {d["title"] for d in docs}
    assert "Alpha Doc" in titles
    assert "Beta Doc" in titles


@patch("app.api.v1.documents.generate_presigned_upload_url", return_value=FAKE_PRESIGNED)
@patch("app.api.v1.documents.enqueue_ocr_job", return_value="")
def test_search_documents_by_title(mock_enqueue, mock_presigned):
    for title in ["Contract 2024", "Invoice 2024", "Photo evidence"]:
        client.post(
            "/api/v1/documents/upload/init",
            json={"title": title, "mime_type": "text/plain", "file_name": "f.txt", "tags": []},
        )

    resp = client.get("/api/v1/documents", params={"q": "Contract"})
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["title"] == "Contract 2024"


@patch("app.api.v1.documents.generate_presigned_upload_url", return_value=FAKE_PRESIGNED)
@patch("app.api.v1.documents.enqueue_ocr_job", return_value="")
def test_search_documents_by_tag(mock_enqueue, mock_presigned):
    client.post(
        "/api/v1/documents/upload/init",
        json={
            "title": "Doc with tag",
            "mime_type": "text/plain",
            "file_name": "f.txt",
            "tags": [{"name": "important", "category": "legal"}],
        },
    )
    client.post(
        "/api/v1/documents/upload/init",
        json={
            "title": "Doc without tag",
            "mime_type": "text/plain",
            "file_name": "f.txt",
            "tags": [],
        },
    )

    resp = client.get("/api/v1/documents", params={"tag": "important"})
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["title"] == "Doc with tag"


def test_get_document_not_found():
    resp = client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_confirm_upload_not_found():
    resp = client.post(
        f"/api/v1/documents/{uuid.uuid4()}/versions/{uuid.uuid4()}/confirm"
    )
    assert resp.status_code == 404
