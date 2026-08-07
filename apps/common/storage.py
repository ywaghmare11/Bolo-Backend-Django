"""Thin S3 wrapper -- the only place boto3 is imported/called directly.

IAM-role-only via the default boto3 credential provider chain (no explicit
access-key/secret settings) -- see docs/api/api-spec.md §5 and CLAUDE.md's env
var table. Kept as free functions rather than a class so call sites can mock
each one individually in tests without needing a real S3 bucket.
"""
import boto3
from django.conf import settings


def _client():
    return boto3.client("s3", region_name=settings.AWS_S3_REGION)


def generate_presigned_put_url(key: str, content_type: str, expires_in: int) -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.AWS_S3_BUCKET_NAME, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def generate_presigned_get_url(key: str, expires_in: int) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.AWS_S3_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )


def copy_object(source_key: str, dest_key: str) -> None:
    _client().copy_object(
        Bucket=settings.AWS_S3_BUCKET_NAME,
        CopySource={"Bucket": settings.AWS_S3_BUCKET_NAME, "Key": source_key},
        Key=dest_key,
    )


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=key)


def get_object_stream(key: str):
    """Returns (body, content_type). `body` is a botocore StreamingBody --
    file-like, safe to hand straight to a StreamingHttpResponse."""
    response = _client().get_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=key)
    return response["Body"], response.get("ContentType")
