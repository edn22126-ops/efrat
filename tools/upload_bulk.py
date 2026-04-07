#!/usr/bin/env python3
r"""
tools/upload_bulk.py
====================
Bulk-upload a folder of files to the PLMS system.

Usage (Windows PowerShell example):
    python tools\\upload_bulk.py ^
        --folder "C:\\Users\\YourName\\Documents\\Evidence" ^
        --api-url "http://localhost:8000" ^
        --category "legal" ^
        --tags "2024,court,important"

Requirements:
    pip install requests tqdm

The script:
  1. Scans the folder (and sub-folders with --recursive) for files.
  2. For each file, calls POST /upload/presign to get a pre-signed S3 URL.
  3. Uploads the file directly to S3 via PUT.
  4. Calls POST /upload/confirm with the file's SHA-256.
  5. Prints a summary CSV of results.

IMPORTANT:
  - Files are uploaded to S3 through the API - they are NEVER committed to Git.
  - Keep your .env / AWS credentials out of this script and out of source control.
"""

import argparse
import csv
import hashlib
import mimetypes
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Please install 'requests': pip install requests")

try:
    from tqdm import tqdm
except ImportError:
    # Provide a minimal no-op fallback so the script works without tqdm
    def tqdm(iterable, **kwargs):  # type: ignore[misc]
        return iterable


SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
    ".txt", ".csv", ".mp4", ".mov", ".avi", ".zip",
}


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(folder: Path, recursive: bool) -> list[Path]:
    if recursive:
        files = [p for p in folder.rglob("*") if p.is_file()]
    else:
        files = [p for p in folder.iterdir() if p.is_file()]
    return [f for f in files if f.suffix.lower() in SUPPORTED_EXTENSIONS]


def upload_file(
    file_path: Path,
    api_url: str,
    category: str | None,
    tags: list[str],
    session: requests.Session,
) -> dict:
    filename = file_path.name
    content_type, _ = mimetypes.guess_type(str(file_path))
    if not content_type:
        content_type = "application/octet-stream"

    # 1. Request pre-signed URL
    presign_resp = session.post(
        f"{api_url}/upload/presign",
        json={
            "filename": filename,
            "content_type": content_type,
            "category": category,
            "tags": tags,
        },
        timeout=30,
    )
    presign_resp.raise_for_status()
    presign_data = presign_resp.json()
    upload_url = presign_data["upload_url"]
    document_id = presign_data["document_id"]

    # 2. Upload directly to S3
    with open(file_path, "rb") as f:
        put_resp = requests.put(
            upload_url,
            data=f,
            headers={"Content-Type": content_type},
            timeout=300,
        )
    put_resp.raise_for_status()

    # 3. Compute SHA-256 and confirm
    sha256 = sha256_of_file(file_path)
    confirm_resp = session.post(
        f"{api_url}/upload/confirm",
        json={"document_id": document_id, "sha256": sha256},
        timeout=30,
    )
    confirm_resp.raise_for_status()

    return {
        "file": str(file_path),
        "document_id": document_id,
        "sha256": sha256,
        "status": "ok",
        "error": "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-upload a folder of files to PLMS (S3 via API)."
    )
    parser.add_argument(
        "--folder",
        required=True,
        help="Path to the folder containing files to upload.",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the PLMS API (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Category label to assign to all uploaded files (e.g. 'legal', 'medical').",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated list of tags to assign (e.g. '2024,court,important').",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan sub-folders recursively.",
    )
    parser.add_argument(
        "--output-csv",
        default="upload_results.csv",
        help="Path to write a CSV log of results (default: upload_results.csv).",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        sys.exit(f"ERROR: Folder not found: {folder}")

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    files = collect_files(folder, args.recursive)
    if not files:
        print(f"No supported files found in {folder}")
        return

    print(f"Found {len(files)} file(s) to upload.")

    session = requests.Session()
    results = []

    for file_path in tqdm(files, desc="Uploading", unit="file"):
        try:
            result = upload_file(file_path, args.api_url, args.category, tags, session)
        except Exception as exc:
            result = {
                "file": str(file_path),
                "document_id": "",
                "sha256": "",
                "status": "error",
                "error": str(exc),
            }
            print(f"\nERROR uploading {file_path.name}: {exc}")
        results.append(result)

    # Write CSV summary
    output_path = Path(args.output_csv)
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["file", "document_id", "sha256", "status", "error"])
        writer.writeheader()
        writer.writerows(results)

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = len(results) - ok
    print(f"\nDone. {ok} uploaded successfully, {failed} failed.")
    print(f"Results written to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
