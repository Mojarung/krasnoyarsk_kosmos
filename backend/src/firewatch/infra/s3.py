from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import ClientError

from firewatch.config import get_settings


@lru_cache
def client() -> BaseClient:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket() -> None:
    bucket = get_settings().s3_bucket
    try:
        client().head_bucket(Bucket=bucket)
    except ClientError:
        client().create_bucket(Bucket=bucket)


def exists(key: str) -> bool:
    try:
        client().head_object(Bucket=get_settings().s3_bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def upload_file(path: Path, key: str) -> None:
    client().upload_file(str(path), get_settings().s3_bucket, key)


def download_file(key: str, path: Path) -> None:
    client().download_file(get_settings().s3_bucket, key, str(path))


def put_bytes(key: str, body: bytes, content_type: str) -> None:
    client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=body, ContentType=content_type)


def get_bytes(key: str) -> bytes:
    return client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()
