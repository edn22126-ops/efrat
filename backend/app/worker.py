"""OCR worker – polls SQS queue and processes documents with AWS Textract."""
import asyncio
import hashlib
import json
import logging

import boto3
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.document import AuditLog, Document, OcrStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _textract_client():
    return boto3.client(
        "textract",
        region_name=settings.textract_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )


def _sqs_client():
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )


def extract_text_from_s3(s3_key: str) -> str:
    """Call Textract synchronously (suitable for single-page PDFs / images)."""
    client = _textract_client()
    response = client.detect_document_text(
        Document={
            "S3Object": {
                "Bucket": settings.s3_bucket,
                "Name": s3_key,
            }
        }
    )
    lines = [
        block["Text"]
        for block in response.get("Blocks", [])
        if block["BlockType"] == "LINE"
    ]
    return "\n".join(lines)


async def process_message(message: dict) -> None:
    body = json.loads(message["Body"])
    document_id = body["document_id"]
    s3_key = body["s3_key"]

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if doc is None:
            logger.warning("Document %s not found, skipping", document_id)
            return

        doc.ocr_status = OcrStatus.processing
        await db.commit()

        try:
            text = extract_text_from_s3(s3_key)
            doc.ocr_text = text
            doc.ocr_status = OcrStatus.done
            entry_hash = hashlib.sha256(text.encode()).hexdigest()
            db.add(
                AuditLog(
                    document_id=doc.id,
                    action="ocr_done",
                    detail=f"lines={text.count(chr(10))+1}",
                    entry_hash=entry_hash,
                )
            )
        except Exception as exc:
            logger.error("OCR failed for %s: %s", document_id, exc)
            doc.ocr_status = OcrStatus.failed
            db.add(AuditLog(document_id=doc.id, action="ocr_failed", detail=str(exc)))

        await db.commit()


async def run_worker() -> None:
    if not settings.sqs_queue_url:
        logger.warning("SQS_QUEUE_URL not set – worker idle (development mode).")
        while True:
            await asyncio.sleep(60)

    sqs = _sqs_client()
    logger.info("OCR worker started, polling %s", settings.sqs_queue_url)

    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,
        )
        messages = response.get("Messages", [])
        for msg in messages:
            try:
                await process_message(msg)
                sqs.delete_message(
                    QueueUrl=settings.sqs_queue_url,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
            except Exception as exc:
                logger.error("Error processing message: %s", exc)


if __name__ == "__main__":
    asyncio.run(run_worker())
