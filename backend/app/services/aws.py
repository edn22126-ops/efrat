import json
import logging

import boto3

from app.core.config import settings

logger = logging.getLogger(__name__)


def _s3_client():
    return boto3.client(
        "s3",
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


def generate_presigned_upload_url(s3_key: str, mime_type: str = "application/octet-stream") -> dict:
    """Return a pre-signed POST URL so the client can upload directly to S3."""
    client = _s3_client()
    response = client.generate_presigned_post(
        Bucket=settings.S3_BUCKET,
        Key=s3_key,
        Fields={"Content-Type": mime_type},
        Conditions=[{"Content-Type": mime_type}],
        ExpiresIn=settings.PRESIGNED_URL_EXPIRY,
    )
    return response


def generate_presigned_get_url(s3_key: str) -> str:
    """Return a pre-signed GET URL for downloading a file."""
    client = _s3_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": s3_key},
        ExpiresIn=settings.PRESIGNED_URL_EXPIRY,
    )
    return url


def enqueue_ocr_job(version_id: str, s3_key: str) -> str:
    """Push an OCR job onto the SQS queue. Returns the SQS message ID."""
    if not settings.SQS_OCR_QUEUE_URL:
        logger.warning("SQS_OCR_QUEUE_URL not set – OCR job not enqueued.")
        return ""
    client = _sqs_client()
    body = json.dumps({"version_id": version_id, "s3_key": s3_key})
    response = client.send_message(
        QueueUrl=settings.SQS_OCR_QUEUE_URL,
        MessageBody=body,
    )
    return response["MessageId"]
