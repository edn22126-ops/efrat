# PLMS – Personal Legal Management System

A self-hosted document management system designed for organising legal evidence:
SHA-256 immutability, OCR via AWS Textract, full-text search, and an audit chain.

---

## Table of Contents

1. [Quick Start (local)](#1-quick-start-local)
2. [Project structure](#2-project-structure)
3. [Environment variables](#3-environment-variables)
4. [AWS provisioning checklist](#4-aws-provisioning-checklist)
5. [API reference](#5-api-reference)
6. [Bulk-upload documents](#6-bulk-upload-documents)
7. [Run the OCR worker](#7-run-the-ocr-worker)
8. [Running tests & lint](#8-running-tests--lint)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Quick Start (local)

### Prerequisites

| Tool | Minimum version |
|------|----------------|
| Docker + Docker Compose | 24 |
| Python | 3.11 |
| `requests` pip package (for bulk-upload script) | 2.31 |

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/edn22126-ops/efrat.git
cd efrat

# 2. Copy the example env file and fill in your values
cp .env.example .env
#    (for local dev without AWS, the defaults work fine)

# 3. Start API + Postgres
docker compose up --build -d

# 4. Run DB migrations (once)
docker compose run --rm migrate

# 5. Check the API is healthy
curl http://localhost:8000/health
# → {"status":"ok"}

# 6. Open the interactive docs
open http://localhost:8000/docs
```

> **Tip** – All data is stored in a named Docker volume (`pgdata`).
> To reset, run `docker compose down -v`.

---

## 2. Project structure

```
efrat/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   └── documents.py   # Upload, list, search endpoints
│   │   ├── core/
│   │   │   └── config.py      # Settings (pydantic-settings)
│   │   ├── db/
│   │   │   └── session.py     # SQLAlchemy engine + session
│   │   ├── models/
│   │   │   └── document.py    # ORM models: Document, Version, Tag, AuditLog
│   │   ├── services/
│   │   │   └── aws.py         # S3 pre-signed URLs + SQS helpers
│   │   ├── worker/
│   │   │   └── ocr_worker.py  # SQS poller + Textract OCR
│   │   └── main.py            # FastAPI app entrypoint
│   ├── alembic/               # DB migrations
│   ├── tests/
│   │   └── test_api.py        # Pytest tests (SQLite in-memory)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── pyproject.toml         # ruff + pytest config
├── tools/
│   └── upload_bulk.py         # Bulk-upload CLI
├── docker-compose.yml
├── .env.example
└── .github/workflows/ci.yml   # GitHub Actions CI
```

---

## 3. Environment variables

Copy `.env.example` to `.env` and fill in the values:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL DSN |
| `AWS_REGION` | yes | e.g. `us-east-1` |
| `AWS_ACCESS_KEY_ID` | yes (prod) | IAM key with S3/SQS/Textract access |
| `AWS_SECRET_ACCESS_KEY` | yes (prod) | IAM secret |
| `S3_BUCKET` | yes | S3 bucket name for documents |
| `SQS_OCR_QUEUE_URL` | no | If empty, OCR jobs are not enqueued |
| `SECRET_KEY` | yes | Random secret for the app |
| `PRESIGNED_URL_EXPIRY` | no | Seconds until S3 URL expires (default 3600) |

> **Never commit `.env` to git.** It is in `.gitignore`.

---

## 4. AWS provisioning checklist

### 4.1 S3 bucket

```bash
# Create the bucket
aws s3api create-bucket \
  --bucket plms-documents \
  --region us-east-1 \
  --create-bucket-configuration LocationConstraint=us-east-1

# Block public access
aws s3api put-public-access-block \
  --bucket plms-documents \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,\
    BlockPublicPolicy=true,RestrictPublicBuckets=true

# Enable versioning (extra immutability)
aws s3api put-bucket-versioning \
  --bucket plms-documents \
  --versioning-configuration Status=Enabled

# Enable server-side encryption
aws s3api put-bucket-encryption \
  --bucket plms-documents \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

### 4.2 RDS Postgres

```bash
# Create a parameter group for Postgres 16
aws rds create-db-instance \
  --db-instance-identifier plms-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --engine-version 16 \
  --master-username plms \
  --master-user-password <STRONG_PASSWORD> \
  --allocated-storage 20 \
  --db-name plms \
  --storage-encrypted \
  --no-publicly-accessible
```

Set `DATABASE_URL=postgresql://plms:<password>@<rds-endpoint>:5432/plms` in `.env`.

### 4.3 SQS queue

```bash
aws sqs create-queue \
  --queue-name plms-ocr-jobs \
  --attributes VisibilityTimeout=300,MessageRetentionPeriod=86400
```

Copy the queue URL into `.env` as `SQS_OCR_QUEUE_URL`.

### 4.4 IAM policy

Create an IAM user / role with this minimal policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::plms-documents/*"
    },
    {
      "Effect": "Allow",
      "Action": ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage"],
      "Resource": "<SQS_QUEUE_ARN>"
    },
    {
      "Effect": "Allow",
      "Action": ["textract:DetectDocumentText"],
      "Resource": "*"
    }
  ]
}
```

---

## 5. API reference

Interactive docs are available at `http://localhost:8000/docs`.

### Upload a document (2-step)

**Step 1 – Initialise upload**

```
POST /api/v1/documents/upload/init
Content-Type: application/json

{
  "title": "Contract 2024",
  "mime_type": "application/pdf",
  "file_name": "contract.pdf",
  "tags": [{"name": "contract", "category": "legal"}]
}
```

Response includes `presigned_post` — a pre-signed S3 POST URL.

**Step 2 – Upload file to S3**

```bash
curl -X POST "https://<presigned_post.url>" \
  -F "key=<presigned_post.fields.key>" \
  -F "Content-Type=application/pdf" \
  -F "file=@/path/to/contract.pdf"
```

**Step 3 – Confirm upload**

```
POST /api/v1/documents/{document_id}/versions/{version_id}/confirm
  ?sha256=<hex>&file_size=<bytes>
```

This enqueues an OCR job on SQS and sets `ocr_status = queued`.

### List & search documents

```
GET /api/v1/documents?q=contract&tag=legal&skip=0&limit=50
```

- `q` – searches title, description, and OCR text (ILIKE)
- `tag` – filters by exact tag name

---

## 6. Bulk-upload documents

```bash
# Install dependency
pip install requests

# Upload all PDFs in ~/Documents/case-files, tagged as "evidence"
python tools/upload_bulk.py \
  --dir ~/Documents/case-files \
  --api http://localhost:8000 \
  --tags "evidence,2024" \
  --category "legal" \
  --ext pdf,docx,txt

# Preview what would be uploaded (no network calls)
python tools/upload_bulk.py \
  --dir ~/Documents/case-files \
  --dry-run

# Recursive upload
python tools/upload_bulk.py \
  --dir ~/Documents \
  --recursive \
  --tags "backup"
```

---

## 7. Run the OCR worker

The OCR worker polls SQS for jobs, calls AWS Textract, and stores the extracted
text in the `document_versions.ocr_text` column.

**Locally:**

```bash
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql://plms:plms@localhost:5432/plms \
  AWS_REGION=us-east-1 \
  AWS_ACCESS_KEY_ID=... \
  AWS_SECRET_ACCESS_KEY=... \
  S3_BUCKET=plms-documents \
  SQS_OCR_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/... \
  python -m app.worker.ocr_worker
```

**In Docker (separate container):**

```yaml
# Add to docker-compose.yml:
  worker:
    build:
      context: ./backend
    command: python -m app.worker.ocr_worker
    environment:
      DATABASE_URL: postgresql://plms:plms@db:5432/plms
      # ... same env vars as api service
    depends_on:
      db:
        condition: service_healthy
```

---

## 8. Running tests & lint

```bash
cd backend
pip install -r requirements.txt

# Lint
ruff check .

# Tests (no AWS / Postgres needed — uses SQLite in-memory)
pytest -v
```

CI runs automatically on every PR via `.github/workflows/ci.yml`.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `Connection refused` on port 8000 | Run `docker compose up -d` and wait for `healthy` status |
| `FATAL: password authentication failed` | Check `DATABASE_URL` in `.env` matches docker-compose |
| `NoCredentialsError` from boto3 | Set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in `.env` |
| S3 upload returns 403 | Check IAM policy grants `s3:PutObject` on the bucket |
| OCR status stays `queued` | Worker is not running — see [Run the OCR worker](#7-run-the-ocr-worker) |
| `alembic.util.exc.CommandError: Can't locate revision` | Run `docker compose run --rm migrate` to apply migrations |
| Port 5432 already in use | Stop a local Postgres instance or change the port in `docker-compose.yml` |

### Sanity checks

```bash
# 1. API health
curl http://localhost:8000/health

# 2. List all documents
curl http://localhost:8000/api/v1/documents | python3 -m json.tool

# 3. Search
curl "http://localhost:8000/api/v1/documents?q=contract" | python3 -m json.tool

# 4. DB direct check
docker compose exec db psql -U plms -c "SELECT id, title FROM documents LIMIT 5;"
```

---

> **Security note** — Do not commit real documents, credentials, or personal data
> to this repository.  All documents are stored in S3; only metadata lives in Postgres.
> The `.env` file is excluded from git via `.gitignore`.