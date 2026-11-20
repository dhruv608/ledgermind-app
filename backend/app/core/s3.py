"""
Where the app keeps files: the client's raw uploads (raw_uploads/<engagement>/...) and the workbooks it builds
(engagements/<engagement>/...).

FILE_STORAGE=local (the default, for running on a laptop) keeps them under data/storage.
FILE_STORAGE=s3 (on the server) keeps them in the S3 bucket AWS_S3_BUCKET_NAME, so they survive the server or its
containers being replaced. On the server the AWS keys can be left empty: boto3 then uses the server's own AWS role.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

S3_PREFIX = "s3://"


def aws_client(service: str, region: Optional[str] = None):
    """A boto3 client: with the keys in .env when given, otherwise the server's AWS role."""
    import boto3
    kw = {"region_name": region or settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kw.update(aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
    return boto3.client(service, **kw)


class S3Service:
    def __init__(self):
        self.bucket_name = settings.AWS_S3_BUCKET_NAME
        self.local_root = settings.LOCAL_STORAGE_DIR
        self._client = None

    @property
    def use_s3(self) -> bool:
        return settings.FILE_STORAGE.lower() == "s3" and bool(self.bucket_name)

    @property
    def s3(self):
        if self._client is None:
            self._client = aws_client("s3")
        return self._client

    @staticmethod
    def key_of(stored: str) -> str:
        """The file's key from what was saved in the database ('s3://bucket/key', a key, or an old local path)."""
        if stored.startswith(S3_PREFIX):
            return stored[len(S3_PREFIX):].split("/", 1)[1]
        return stored

    def upload_file_bytes(self, file_bytes: bytes, s3_key: str, content_type: str = "application/octet-stream") -> str:
        """Saves the file; returns where it is (kept in the database as the workbook's storage_path)."""
        if self.use_s3:
            self.s3.put_object(Bucket=self.bucket_name, Key=s3_key, Body=file_bytes, ContentType=content_type,
                               ServerSideEncryption="AES256")
            return f"{S3_PREFIX}{self.bucket_name}/{s3_key}"
        local_path = self.local_root / s3_key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(file_bytes)
        return str(local_path)

    def download_file_bytes(self, stored: str) -> Optional[bytes]:
        key = self.key_of(stored)
        if stored.startswith(S3_PREFIX) or (self.use_s3 and not Path(key).is_absolute()):
            try:
                return self.s3.get_object(Bucket=self.bucket_name, Key=key)["Body"].read()
            except Exception:
                pass
        # Files saved on this computer, also under the older folder name data/generated_workpapers
        old = key.replace("\\", "/").split("/generated_workpapers/", 1)
        candidates = [self.local_root / key, Path(key)] + ([self.local_root / old[1]] if len(old) == 2 else [])
        for path in candidates:
            if path.exists():
                return path.read_bytes()
        return None

    def list_files(self, prefix: str) -> List[Tuple[str, bytes]]:
        """(file name, contents) of every file under the prefix, oldest first."""
        if self.use_s3:
            objs = []
            for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket_name, Prefix=prefix):
                objs += page.get("Contents", [])
            objs.sort(key=lambda o: o["LastModified"])
            return [(o["Key"].rsplit("/", 1)[-1], self._object_bytes(o["Key"], o.get("ETag", ""))) for o in objs]
        folder = self.local_root / prefix
        if not folder.exists():
            return []
        return [(p.name, p.read_bytes()) for p in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime) if p.is_file()]

    def _object_bytes(self, key: str, etag: str) -> bytes:
        """An object's contents, downloaded once per version (key and ETag) while the server runs."""
        from backend.app.services.shared.file_cache import remember
        return remember("s3", f"{key}|{etag}",
                        lambda: self.s3.get_object(Bucket=self.bucket_name, Key=key)["Body"].read(), copy_out=False)

    def signature(self, prefix: str) -> List[Tuple[str, str]]:
        """(name, version) of every file under the prefix, without reading them: changes when a file is added,
        removed or written again."""
        if self.use_s3:
            out = []
            for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket_name, Prefix=prefix):
                out += [(o["Key"], o.get("ETag", "")) for o in page.get("Contents", [])]
            return sorted(out)
        folder = self.local_root / prefix
        if not folder.exists():
            return []
        return sorted((p.name, f"{p.stat().st_mtime_ns}:{p.stat().st_size}") for p in folder.iterdir() if p.is_file())

    def delete_prefix(self, prefix: str) -> None:
        """Removes every file under the prefix (a client's previous raw upload), on this computer and in S3."""
        import shutil
        local_target = self.local_root / prefix
        if local_target.exists():
            shutil.rmtree(local_target, ignore_errors=True)
        if self.use_s3:
            for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket_name, Prefix=prefix):
                if "Contents" in page:
                    self.s3.delete_objects(Bucket=self.bucket_name,
                                           Delete={"Objects": [{"Key": o["Key"]} for o in page["Contents"]]})

    def delete_engagement_files(self, engagement_id: str) -> None:
        """Removes a client's raw uploads and workbooks, on this computer and in S3."""
        import shutil
        for folder in ["raw_uploads", "engagements"]:
            local_target = self.local_root / folder / engagement_id
            if local_target.exists():
                shutil.rmtree(local_target, ignore_errors=True)
        if self.bucket_name:
            try:
                for prefix in [f"raw_uploads/{engagement_id}/", f"engagements/{engagement_id}/"]:
                    for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket_name, Prefix=prefix):
                        if "Contents" in page:
                            self.s3.delete_objects(Bucket=self.bucket_name,
                                                   Delete={"Objects": [{"Key": o["Key"]} for o in page["Contents"]]})
            except Exception:
                logger.warning("The S3 files of client %s could not be deleted", engagement_id, exc_info=True)


s3_service = S3Service()
