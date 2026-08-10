"""Cloudflare R2 Storage Service with S3 Client API and local fallback."""

import logging
import os
import uuid
from typing import Optional
import boto3
from botocore.config import Config
from fastapi import UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)


class R2StorageService:
    """Service to handle Cloudflare R2 object uploads."""

    def __init__(self):
        self.account_id = settings.R2_ACCOUNT_ID
        self.access_key_id = settings.R2_ACCESS_KEY_ID
        self.secret_access_key = settings.R2_SECRET_ACCESS_KEY
        self.bucket_name = settings.R2_BUCKET_NAME
        self.public_url = settings.R2_PUBLIC_URL.rstrip('/') if settings.R2_PUBLIC_URL else ""
        self.upload_dir = settings.UPLOAD_DIR

    def _get_s3_client(self):
        """Build S3 client pointing to Cloudflare R2 endpoint if configured."""
        if not (self.account_id and self.access_key_id and self.secret_access_key):
            return None
        endpoint_url = f"https://{self.account_id}.r2.cloudflarestorage.com"
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto"
        )

    async def upload_file(self, file: UploadFile, folder: str = "logos") -> str:
        """
        Uploads an UploadFile to Cloudflare R2 bucket.
        Falls back to local file storage if R2 credentials are missing or fail.
        """
        contents = await file.read()
        file_ext = os.path.splitext(file.filename or "")[1].lower() or ".webp"
        filename = f"{folder}/{uuid.uuid4().hex}{file_ext}"

        s3_client = self._get_s3_client()
        content_type = file.content_type or "image/webp"

        if s3_client:
            try:
                s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=filename,
                    Body=contents,
                    ContentType=content_type
                )
                if self.public_url:
                    return f"{self.public_url}/{filename}"
                return f"https://{self.account_id}.r2.cloudflarestorage.com/{self.bucket_name}/{filename}"
            except Exception as e:
                logger.error(f"Failed to upload to R2 bucket {self.bucket_name}: {e}. Falling back to local storage.")

        # Local storage fallback for development
        os.makedirs(self.upload_dir, exist_ok=True)
        local_filename = f"{uuid.uuid4().hex}{file_ext}"
        local_path = os.path.join(self.upload_dir, local_filename)
        with open(local_path, "wb") as f:
            f.write(contents)

        return f"/static/uploads/{local_filename}"


r2_storage_service = R2StorageService()
