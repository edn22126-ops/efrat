"""AWS helper – S3 pre-signed URLs and SQS dispatch."""
import hashlib
import json

import boto3

from app.core.config import settings


def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
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


def generate_presigned_upload_url(s3_key: str, content_type: str, expires: int = 3600) -> str:
    """Return a pre-signed PUT URL that the client can use to upload directly to S3."""
    client = _s3_client()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires,
    )
    return url


def enqueue_ocr_job(document_id: str, s3_key: str) -> None:
    """Send an OCR job message to the SQS queue."""
    if not settings.sqs_queue_url:
        return
    client = _sqs_client()
    client.send_message(
        QueueUrl=settings.sqs_queue_url,
        MessageBody=json.dumps({"document_id": document_id, "s3_key": s3_key}),
    )


def compute_audit_hash(document_id: str, action: str, detail: str | None, prev_hash: str | None) -> str:
    """Return SHA-256 hash that chains this audit entry to the previous one."""
    payload = f"{document_id}|{action}|{detail or ''}|{prev_hash or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()
