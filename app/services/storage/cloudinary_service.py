"""Cloudinary Image Storage Service with automatic CDN delivery and local fallback."""

import logging
import os
import uuid
from typing import Optional
from fastapi import UploadFile
import cloudinary
import cloudinary.uploader

from app.core.config import settings

logger = logging.getLogger(__name__)


class CloudinaryStorageService:
    """Service to handle Cloudinary CDN image uploads."""

    def __init__(self):
        self.cloud_name = settings.CLOUDINARY_CLOUD_NAME
        self.api_key = settings.CLOUDINARY_API_KEY
        self.api_secret = settings.CLOUDINARY_API_SECRET
        self.cloudinary_url = settings.CLOUDINARY_URL
        self.upload_dir = settings.UPLOAD_DIR

    def _is_configured(self) -> bool:
        """Checks whether Cloudinary environment keys are set."""
        if self.cloudinary_url or (self.cloud_name and self.api_key and self.api_secret):
            return True
        return False

    def _configure_cloudinary(self):
        """Configures the cloudinary global instance."""
        if self.cloudinary_url:
            cloudinary.config(cloudinary_url=self.cloudinary_url, secure=True)
        elif self.cloud_name and self.api_key and self.api_secret:
            cloudinary.config(
                cloud_name=self.cloud_name,
                api_key=self.api_key,
                api_secret=self.api_secret,
                secure=True
            )

    async def upload_file(self, file: UploadFile, folder: str = "paza/organizers") -> str:
        """
        Uploads an UploadFile to Cloudinary.
        Falls back to local disk storage if Cloudinary credentials are missing or upload fails.
        """
        contents = await file.read()
        file_ext = os.path.splitext(file.filename or "")[1].lower() or ".webp"

        if self._is_configured():
            try:
                self._configure_cloudinary()
                res = cloudinary.uploader.upload(
                    contents,
                    folder=folder,
                    resource_type="auto"
                )
                secure_url = res.get("secure_url") or res.get("url")
                if secure_url:
                    logger.info(f"Successfully uploaded image to Cloudinary: {secure_url}")
                    return secure_url
            except Exception as e:
                logger.error(f"Failed to upload to Cloudinary: {e}. Falling back to local storage.")

        # Local storage fallback for development
        os.makedirs(self.upload_dir, exist_ok=True)
        local_filename = f"{uuid.uuid4().hex}{file_ext}"
        local_path = os.path.join(self.upload_dir, local_filename)
        with open(local_path, "wb") as f:
            f.write(contents)

        return f"/static/uploads/{local_filename}"


cloudinary_storage_service = CloudinaryStorageService()
