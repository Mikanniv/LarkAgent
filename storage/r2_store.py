from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from core.config import (
    R2_ACCESS_KEY_ID,
    R2_BUCKET,
    R2_ENABLED,
    R2_ENDPOINT,
    R2_PREFIX,
    R2_REGION,
    R2_SECRET_ACCESS_KEY,
)


def is_enabled() -> bool:
    return R2_ENABLED and all([R2_BUCKET, R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY])


def _normalized_endpoint() -> str:
    parsed = urlparse(R2_ENDPOINT)
    if not parsed.scheme or not parsed.netloc:
        return R2_ENDPOINT.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"


def object_key(*parts: str) -> str:
    clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
    if R2_PREFIX:
        clean_parts.insert(0, R2_PREFIX)
    return "/".join(clean_parts)


@lru_cache(maxsize=1)
def client():
    if not is_enabled():
        raise RuntimeError("R2 is not configured")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("boto3 is required for R2 storage") from exc

    return boto3.client(
        "s3",
        endpoint_url=_normalized_endpoint(),
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name=R2_REGION,
        config=Config(signature_version="s3v4"),
    )


def put_text(key: str, content: str, content_type: str = "text/plain; charset=utf-8") -> None:
    client().put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=(content or "").encode("utf-8"),
        ContentType=content_type,
    )


def get_text(key: str) -> str | None:
    try:
        response = client().get_object(Bucket=R2_BUCKET, Key=key)
    except Exception as exc:
        if exc.__class__.__name__ in {"NoSuchKey", "ClientError"}:
            try:
                if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                    return None
            except AttributeError:
                pass
        raise
    body = response["Body"].read()
    return body.decode("utf-8")


def list_keys(prefix: str = "") -> list[str]:
    paginator = client().get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if key:
                keys.append(key)
    return keys


def delete_keys(keys: list[str]) -> int:
    deleted = 0
    for start in range(0, len(keys), 1000):
        chunk = keys[start : start + 1000]
        if not chunk:
            continue
        client().delete_objects(
            Bucket=R2_BUCKET,
            Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True},
        )
        deleted += len(chunk)
    return deleted


def delete_prefix(prefix: str) -> int:
    return delete_keys(list_keys(prefix))

