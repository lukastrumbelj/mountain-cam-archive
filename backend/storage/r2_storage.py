from __future__ import annotations

import os
from pathlib import Path


class LocalStorage:
    """Enak vmesnik kot R2Storage, ampak na disku. Za lokalni test brez Cloudflare računa."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str, cache_control: str | None = None) -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        p = self._p(key)
        return p.read_bytes() if p.exists() else None

    def delete(self, keys: list[str]) -> None:
        for k in keys:
            p = self._p(k)
            if p.exists():
                p.unlink()

    def list(self, prefix: str) -> list[str]:
        base = self.root
        return sorted(str(p.relative_to(base)) for p in base.rglob("*")
                      if p.is_file() and str(p.relative_to(base)).startswith(prefix))


class R2Storage:
    """Cloudflare R2 prek S3 API (boto3)."""

    def __init__(self, account_id: str, access_key: str, secret_key: str, bucket: str):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    @classmethod
    def from_env(cls) -> "R2Storage":
        names = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
        missing = [n for n in names if not os.environ.get(n)]
        if missing:
            raise RuntimeError("Manjkajo okoljske spremenljivke: " + ", ".join(missing))
        return cls(*(os.environ[n] for n in names))

    def put(self, key: str, data: bytes, content_type: str, cache_control: str | None = None) -> None:
        extra = {"CacheControl": cache_control} if cache_control else {}
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra)

    def get(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def delete(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):
            chunk = keys[i:i + 1000]
            self.s3.delete_objects(Bucket=self.bucket,
                                   Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True})

    def list(self, prefix: str) -> list[str]:
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.s3.list_objects_v2(**kw)
            out += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return out
            token = r["NextContinuationToken"]
