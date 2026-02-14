"""
Cloudinary integration helper for file uploads
"""
import os
import logging
from pathlib import Path

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

logger = logging.getLogger(__name__)

# Configure Cloudinary from environment variables
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)


def upload_file_to_cloudinary(file_path, shop_id, original_filename):
    """
    Upload file to Cloudinary and return a SIGNED delivery URL
    (Required for Restricted RAW Delivery)
    """
    try:
        file_extension = Path(file_path).suffix.lower().lstrip('.')

        if file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
            resource_type = "image"
        else:
            resource_type = "raw"

        # 1️⃣ Upload file
        result = cloudinary.uploader.upload(
            file_path,
            resource_type=resource_type,
            folder=f"ezprint/{shop_id}",
            use_filename=True,
            unique_filename=True,
            type="upload",
            access_mode="public"
        )

        # 2️⃣ Generate SIGNED delivery URL (ROOT FIX)
        signed_url, _ = cloudinary_url(
            result["public_id"],
            resource_type=resource_type,
            secure=True,
            sign_url=True
        )

        logger.info(f"Cloudinary upload successful: {signed_url}")
        return signed_url, result.get("public_id")

    except Exception as e:
        logger.error(f"Cloudinary upload failed: {e}")
        raise Exception(f"Failed to upload file to cloud storage: {str(e)}")


def delete_file_from_cloudinary(cloudinary_url):
    """Optional cleanup"""
    try:
        parts = cloudinary_url.split('/')
        if 'upload' in parts:
            upload_index = parts.index('upload')
            public_id = '/'.join(parts[upload_index + 2:]).rsplit('.', 1)[0]
            resource_type = parts[upload_index - 1]

            result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
            return result.get("result") == "ok"
    except Exception as e:
        logger.warning(f"Cloudinary delete failed: {e}")
        return False
