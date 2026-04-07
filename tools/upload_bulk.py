#!/usr/bin/env python3
"""
tools/upload_bulk.py
====================
Bulk-upload a directory of files to the PLMS API.

For each file the script will:
  1. Call POST /api/v1/documents/upload/init  → get a pre-signed S3 POST URL.
  2. Upload the file directly to S3 using the pre-signed URL.
  3. Call POST /api/v1/documents/{doc_id}/versions/{ver_id}/confirm with the
     SHA-256 digest and file size.

Usage
-----
    python tools/upload_bulk.py --dir /path/to/files \\
        --api http://localhost:8000 \\
        --tags "evidence,2024" \\
        --category "legal"

Options
-------
    --dir           Directory of files to upload (required)
    --api           Base URL of the PLMS API (default: http://localhost:8000)
    --tags          Comma-separated list of tag names to attach
    --category      Category assigned to all tags
    --recursive     Also process sub-directories (default: False)
    --dry-run       Print what would be uploaded without actually uploading
    --ext           Only upload files with these extensions, e.g. "pdf,docx,mp3"
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

import requests

SUPPORTED_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_file(
    api_base: str,
    file_path: Path,
    tags: list,
    dry_run: bool,
) -> bool:
    mime_type = SUPPORTED_MIME.get(file_path.suffix.lower(), "application/octet-stream")
    file_size = file_path.stat().st_size
    title = file_path.name

    if dry_run:
        print(f"[DRY-RUN] Would upload: {file_path}  ({mime_type}, {file_size} bytes)")
        return True

    # Step 1: init upload
    payload = {
        "title": title,
        "mime_type": mime_type,
        "file_name": file_path.name,
        "tags": tags,
    }
    try:
        resp = requests.post(f"{api_base}/api/v1/documents/upload/init", json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[ERROR] init failed for {file_path}: {exc}", file=sys.stderr)
        return False

    data = resp.json()
    doc_id = data["document_id"]
    ver_id = data["version_id"]
    presigned = data["presigned_post"]

    # Step 2: upload to S3 (pre-signed POST)
    try:
        with file_path.open("rb") as f:
            files_payload = {"file": (file_path.name, f, mime_type)}
            s3_resp = requests.post(
                presigned["url"],
                data=presigned["fields"],
                files=files_payload,
                timeout=120,
            )
        if s3_resp.status_code not in (200, 204):
            print(
                f"[ERROR] S3 upload failed for {file_path}: HTTP {s3_resp.status_code}",
                file=sys.stderr,
            )
            return False
    except requests.RequestException as exc:
        print(f"[ERROR] S3 upload error for {file_path}: {exc}", file=sys.stderr)
        return False

    # Step 3: confirm
    digest = sha256_of_file(file_path)
    try:
        confirm_resp = requests.post(
            f"{api_base}/api/v1/documents/{doc_id}/versions/{ver_id}/confirm",
            params={"sha256": digest, "file_size": file_size},
            timeout=30,
        )
        confirm_resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[ERROR] confirm failed for {file_path}: {exc}", file=sys.stderr)
        return False

    print(f"[OK] {file_path.name}  doc={doc_id}  ver={ver_id}  sha256={digest[:12]}…")
    return True


def main():
    parser = argparse.ArgumentParser(description="Bulk-upload files to PLMS")
    parser.add_argument("--dir", required=True, help="Directory of files to upload")
    parser.add_argument("--api", default="http://localhost:8000", help="PLMS API base URL")
    parser.add_argument("--tags", default="", help="Comma-separated tag names")
    parser.add_argument("--category", default=None, help="Category for all tags")
    parser.add_argument("--recursive", action="store_true", help="Process sub-directories")
    parser.add_argument("--dry-run", action="store_true", help="Print without uploading")
    parser.add_argument(
        "--ext",
        default="",
        help="Only upload files with these extensions (comma-separated, e.g. pdf,docx)",
    )
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        print(f"[ERROR] Not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    tag_names = [t.strip() for t in args.tags.split(",") if t.strip()]
    tags = [{"name": n, "category": args.category} for n in tag_names]

    allowed_ext = set()
    if args.ext:
        allowed_ext = {f".{e.strip().lstrip('.')}" for e in args.ext.split(",") if e.strip()}

    pattern = "**/*" if args.recursive else "*"
    files = [p for p in root.glob(pattern) if p.is_file()]

    if allowed_ext:
        files = [p for p in files if p.suffix.lower() in allowed_ext]

    if not files:
        print("[INFO] No files found.")
        sys.exit(0)

    print(f"[INFO] Found {len(files)} file(s) to upload.")

    success = 0
    for file_path in sorted(files):
        if upload_file(args.api, file_path, tags, args.dry_run):
            success += 1

    print(f"\n[DONE] {success}/{len(files)} file(s) uploaded successfully.")
    if success < len(files):
        sys.exit(1)


if __name__ == "__main__":
    main()
