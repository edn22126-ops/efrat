"""OCR Worker – polls SQS for OCR jobs and processes document versions.

Run locally:
    cd backend
    python -m worker.ocr_worker

Environment variables required:
    SQS_QUEUE_URL   – URL of the SQS queue (set in .env or environment)
    DATABASE_URL    – sync Postgres URL (uses psycopg2)
    AWS_REGION / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (optional for LocalStack)
"""
import hashlib
import json
import logging
import os
import time

import boto3
import sqlalchemy
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
DATABASE_URL = os.environ.get(
    "DATABASE_URL_SYNC",
    os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""),
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
POLL_WAIT_SECONDS = 20  # SQS long-poll


# ---------------------------------------------------------------------------
# DB helpers (sync, for worker)
# ---------------------------------------------------------------------------

def get_sync_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# OCR stub
# ---------------------------------------------------------------------------

def run_ocr(document_id: str, s3_key: str) -> str:
    """Placeholder OCR. Replace with AWS Textract integration.

    TODO: call boto3 textract_client.start_document_text_detection(...)
    and poll for results; return extracted text.
    """
    logger.info("OCR stub called for document_id=%s s3_key=%s", document_id, s3_key)
    return f"[TODO: Textract OCR result for {s3_key}]"


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

def process_message(body: dict, engine: sqlalchemy.engine.Engine) -> None:
    document_id = body.get("document_id")
    s3_key = body.get("s3_key")
    if not document_id or not s3_key:
        logger.warning("Malformed message: %s", body)
        return

    logger.info("Processing OCR job: document_id=%s", document_id)

    # Import here to avoid circular imports when running standalone
    from app.models.document import AuditLog, Document, OcrStatus  # noqa: PLC0415

    with Session(engine) as session:
        doc = session.scalar(select(Document).where(Document.id == document_id))
        if doc is None:
            logger.warning("Document not found: %s", document_id)
            return

        doc.ocr_status = OcrStatus.processing
        session.commit()

        try:
            ocr_text = run_ocr(document_id, s3_key)
            doc.ocr_status = OcrStatus.done
            doc.ocr_text = ocr_text

            # Get last audit log for hash chain
            prev_log = session.scalar(
                select(AuditLog)
                .where(AuditLog.document_id == doc.id)
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
            prev_hash = prev_log.entry_hash if prev_log else None
            detail = f"ocr_chars={len(ocr_text)}"
            entry_hash = hashlib.sha256(
                f"{document_id}|ocr_completed|{detail}|{prev_hash or ''}".encode()
            ).hexdigest()

            session.add(
                AuditLog(
                    document_id=doc.id,
                    action="ocr_completed",
                    detail=detail,
                    prev_hash=prev_hash,
                    entry_hash=entry_hash,
                )
            )
            session.commit()
            logger.info("OCR done for document_id=%s", document_id)

        except Exception as exc:
            logger.error("OCR failed for document_id=%s: %s", document_id, exc)
            doc.ocr_status = OcrStatus.failed
            session.commit()


def run_worker() -> None:
    if not SQS_QUEUE_URL:
        logger.error("SQS_QUEUE_URL is not set. Exiting.")
        return

    logger.info("Starting OCR worker. Queue: %s", SQS_QUEUE_URL)
    engine = get_sync_engine()
    sqs = boto3.client("sqs", region_name=AWS_REGION)

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=POLL_WAIT_SECONDS,
            )
            messages = response.get("Messages", [])
            if not messages:
                continue

            for msg in messages:
                try:
                    body = json.loads(msg["Body"])
                    process_message(body, engine)
                    sqs.delete_message(
                        QueueUrl=SQS_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                except Exception as exc:
                    logger.error("Error processing message: %s", exc)

        except KeyboardInterrupt:
            logger.info("Worker stopped.")
            break
        except Exception as exc:
            logger.error("SQS polling error: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    run_worker()
