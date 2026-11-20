"""
One-off: copy the files kept on this computer (data/storage: raw uploads and built workbooks) into the
S3 bucket, and point the workbook records in the database at S3. Run once before switching the server to
FILE_STORAGE=s3. Nothing is deleted from this computer.

    PYTHONPATH=. python backend/scripts/move_files_to_s3.py          # shows what it would do
    PYTHONPATH=. python backend/scripts/move_files_to_s3.py --apply   # copies and updates the records
"""

import sys
from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.core.s3 import S3_PREFIX, aws_client
from backend.app.models.database import GeneratedWorkpaper


def main(apply: bool):
    root = settings.LOCAL_STORAGE_DIR
    bucket = settings.AWS_S3_BUCKET_NAME
    if not bucket:
        sys.exit("AWS_S3_BUCKET_NAME is not set")
    s3 = aws_client("s3")
    files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
    existing = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        existing |= {o["Key"] for o in page.get("Contents", [])}
    todo = [p for p in files if p.relative_to(root).as_posix() not in existing]
    print(f"{len(files)} file(s) on this computer, {len(todo)} not yet in s3://{bucket}")
    for p in todo:
        key = p.relative_to(root).as_posix()
        if apply:
            s3.put_object(Bucket=bucket, Key=key, Body=p.read_bytes(), ServerSideEncryption="AES256")
        print(("copied " if apply else "would copy ") + key)

    db = SessionLocal()
    changed = 0
    for wp in db.query(GeneratedWorkpaper).all():
        if wp.storage_path.startswith(S3_PREFIX):
            continue
        path = Path(wp.storage_path)
        try:
            key = path.relative_to(root).as_posix()
        except ValueError:
            key = None
        if not key or not path.exists():
            print(f"skipped workbook {wp.id} ({wp.filename}): its file is not on this computer")
            continue
        changed += 1
        if apply:
            wp.storage_path = f"{S3_PREFIX}{bucket}/{key}"
    if apply:
        db.commit()
    print(f"{changed} workbook record(s) {'now point' if apply else 'would point'} at S3")


if __name__ == "__main__":
    main("--apply" in sys.argv)
