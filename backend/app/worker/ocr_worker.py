"""
OCR Worker – polls SQS for jobs, calls AWS Textract, saves results to DB.

Run locally:
    cd backend
    python -m app.worker.ocr_worker

In production run this as a separate container or ECS task.
"""

import json
import logging
import time

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import AuditLog, DocumentVersion

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _textract_client():
    return boto3.client(
        "textract",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
    )


def _sqs_client():
    return boto3.client(
        "sqs",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
    )


def process_ocr_job(version_id: str, s3_key: str) -> str:
    """Call Textract and return extracted text."""
    textract = _textract_client()
    response = textract.detect_document_text(
        Document={"S3Object": {"Bucket": settings.S3_BUCKET, "Name": s3_key}}
    )
    lines = [
        block["Text"]
        for block in response.get("Blocks", [])
        if block["BlockType"] == "LINE"
    ]
    return "\n".join(lines)


def run_worker(poll_interval: int = 5):
    if not settings.SQS_OCR_QUEUE_URL:
        logger.error("SQS_OCR_QUEUE_URL is not set. Worker cannot start.")
        return

    sqs = _sqs_client()
    logger.info("OCR worker started, polling %s", settings.SQS_OCR_QUEUE_URL)

    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=settings.SQS_OCR_QUEUE_URL,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=10,
            )
        except ClientError as exc:
            logger.error("SQS receive error: %s", exc)
            time.sleep(poll_interval)
            continue

        for msg in resp.get("Messages", []):
            body = json.loads(msg["Body"])
            version_id = body["version_id"]
            s3_key = body["s3_key"]

            db = SessionLocal()
            try:
                version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
                if not version:
                    logger.warning("Version %s not found, skipping.", version_id)
                    _delete_msg(sqs, msg)
                    continue

                version.ocr_status = "processing"
                db.commit()

                ocr_text = process_ocr_job(version_id, s3_key)

                version.ocr_text = ocr_text
                version.ocr_status = "done"
                db.add(
                    AuditLog(
                        document_id=version.document_id,
                        action="ocr_done",
                        detail=f"chars={len(ocr_text)}",
                    )
                )
                db.commit()
                logger.info("OCR done for version %s (%d chars)", version_id, len(ocr_text))

            except Exception as exc:
                logger.error("OCR failed for version %s: %s", version_id, exc)
                if version:
                    version.ocr_status = "failed"
                    db.add(
                        AuditLog(
                            document_id=version.document_id,
                            action="ocr_failed",
                            detail=str(exc),
                        )
                    )
                    db.commit()
            finally:
                db.close()
                _delete_msg(sqs, msg)

        time.sleep(poll_interval)


def _delete_msg(sqs, msg):
    try:
        sqs.delete_message(
            QueueUrl=settings.SQS_OCR_QUEUE_URL,
            ReceiptHandle=msg["ReceiptHandle"],
        )
    except ClientError as exc:
        logger.warning("Failed to delete SQS message: %s", exc)


if __name__ == "__main__":
    run_worker()
