"""
S3-compatible storage helper for EzPrint
Supports: MinIO, Cloudflare R2, AWS S3, DigitalOcean Spaces, and other S3-compatible services
"""
import os
import logging
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)

# Configuration from environment
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")  # For MinIO/R2: http://localhost:9000
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "ezprint-files")
S3_REGION = os.environ.get("S3_REGION", "auto")  # 'auto' for Cloudflare R2
S3_PUBLIC_URL = os.environ.get("S3_PUBLIC_URL")  # Custom domain if using CDN


def get_s3_client():
    """
    Get configured S3 client with proper error handling

    Returns:
        boto3.client: Configured S3 client

    Raises:
        Exception: If credentials are not configured
    """
    if not S3_ACCESS_KEY or not S3_SECRET_KEY:
        raise Exception("S3 credentials not configured. Please set S3_ACCESS_KEY and S3_SECRET_KEY environment variables.")

    # Configure client
    config_params = {
        'aws_access_key_id': S3_ACCESS_KEY,
        'aws_secret_access_key': S3_SECRET_KEY,
        'region_name': S3_REGION if S3_REGION != 'auto' else 'us-east-1',
    }

    # Add endpoint for MinIO/R2/non-AWS services
    if S3_ENDPOINT:
        config_params['endpoint_url'] = S3_ENDPOINT

    # Configure retries and timeout
    boto_config = Config(
        retries={
            'max_attempts': 3,
            'mode': 'standard'
        },
        connect_timeout=10,
        read_timeout=30
    )
    config_params['config'] = boto_config

    try:
        client = boto3.client('s3', **config_params)
        logger.debug(f"S3 client initialized successfully (endpoint: {S3_ENDPOINT or 'AWS'})")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        raise


def upload_file_to_s3(file_path, shop_id, original_filename):
    """
    Upload file to S3-compatible storage

    Args:
        file_path (str): Local path to file to upload
        shop_id (str): Shop identifier for organizing files
        original_filename (str): Original filename from upload

    Returns:
        tuple: (public_url, object_key)

    Raises:
        Exception: If upload fails
    """
    try:
        s3_client = get_s3_client()

        # Generate S3 object key (path in bucket)
        file_extension = Path(file_path).suffix.lower()
        # Sanitize shop_id and filename for S3 key
        safe_shop_id = ''.join(c if c.isalnum() or c in '-_' else '_' for c in shop_id)
        safe_filename = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in original_filename)

        object_key = f"ezprint/{safe_shop_id}/{safe_filename}"

        # Determine content type
        content_type = get_content_type(file_extension)

        logger.info(f"Uploading file to S3: {object_key}")

        # Calculate file size for logging
        file_size = os.path.getsize(file_path)
        logger.debug(f"File size: {file_size / 1024 / 1024:.2f} MB")

        # Upload file with metadata
        with open(file_path, 'rb') as file_data:
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=object_key,
                Body=file_data,
                ContentType=content_type,
                Metadata={
                    'shop_id': shop_id,
                    'original_filename': original_filename,
                    'uploaded_by': 'ezprint_agent'
                },
                # Optional: Set ACL for public read (if needed)
                # ACL='public-read'
            )

        # Generate public URL
        public_url = generate_public_url(object_key)

        logger.info(f"S3 upload successful: {public_url}")
        return public_url, object_key

    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        logger.error(f"S3 ClientError ({error_code}): {error_message}")
        raise Exception(f"Failed to upload file to S3: {error_message}")
    except BotoCoreError as e:
        logger.error(f"S3 BotoCoreError: {e}")
        raise Exception(f"Failed to upload file to S3: Connection error")
    except Exception as e:
        logger.error(f"S3 upload error: {e}")
        raise Exception(f"Failed to upload file to S3: {str(e)}")


def delete_file_from_s3(object_key):
    """
    Delete file from S3

    Args:
        object_key (str): S3 object key (path in bucket)

    Returns:
        bool: True if deleted successfully, False otherwise
    """
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=object_key)
        logger.info(f"S3 delete successful: {object_key}")
        return True
    except ClientError as e:
        logger.warning(f"S3 delete failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"S3 delete error: {e}")
        return False


def generate_presigned_url(object_key, expiration=3600):
    """
    Generate presigned URL for temporary access to private objects

    Args:
        object_key (str): S3 object key
        expiration (int): URL validity in seconds (default: 1 hour)

    Returns:
        str: Presigned URL or None if generation fails
    """
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': object_key},
            ExpiresIn=expiration
        )
        logger.debug(f"Generated presigned URL for {object_key} (expires in {expiration}s)")
        return url
    except Exception as e:
        logger.error(f"Presigned URL generation failed: {e}")
        return None


def generate_public_url(object_key):
    """
    Generate public URL for accessing S3 object

    Args:
        object_key (str): S3 object key

    Returns:
        str: Public URL
    """
    # Use custom domain if configured (e.g., CDN)
    if S3_PUBLIC_URL:
        return f"{S3_PUBLIC_URL.rstrip('/')}/{object_key}"

    # Use MinIO/custom endpoint
    if S3_ENDPOINT:
        endpoint_url = S3_ENDPOINT.rstrip('/')
        return f"{endpoint_url}/{S3_BUCKET_NAME}/{object_key}"

    # Use standard AWS S3 URL format
    if S3_REGION == 'us-east-1':
        return f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{object_key}"
    else:
        return f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{object_key}"


def get_content_type(file_extension):
    """
    Map file extension to MIME content type

    Args:
        file_extension (str): File extension (with or without dot)

    Returns:
        str: MIME content type
    """
    # Remove leading dot if present
    ext = file_extension.lower().lstrip('.')

    content_types = {
        # Documents
        'pdf': 'application/pdf',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'ppt': 'application/vnd.ms-powerpoint',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'txt': 'text/plain',
        'rtf': 'application/rtf',

        # Images
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
        'tiff': 'image/tiff',
        'tif': 'image/tiff',
        'webp': 'image/webp',
        'svg': 'image/svg+xml',

        # Archives
        'zip': 'application/zip',
        'rar': 'application/x-rar-compressed',
        '7z': 'application/x-7z-compressed',

        # Other
        'json': 'application/json',
        'xml': 'application/xml',
        'csv': 'text/csv',
    }

    return content_types.get(ext, 'application/octet-stream')


def init_s3_bucket():
    """
    Initialize S3 bucket if it doesn't exist

    Returns:
        bool: True if bucket exists or was created successfully
    """
    try:
        s3_client = get_s3_client()

        # Check if bucket exists
        try:
            s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
            logger.info(f"S3 bucket '{S3_BUCKET_NAME}' already exists")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                # Bucket doesn't exist, create it
                logger.info(f"Creating S3 bucket '{S3_BUCKET_NAME}'...")

                if S3_ENDPOINT:
                    # MinIO/local - simple creation
                    s3_client.create_bucket(Bucket=S3_BUCKET_NAME)
                else:
                    # AWS S3 - specify region (except us-east-1)
                    if S3_REGION == 'us-east-1':
                        s3_client.create_bucket(Bucket=S3_BUCKET_NAME)
                    else:
                        s3_client.create_bucket(
                            Bucket=S3_BUCKET_NAME,
                            CreateBucketConfiguration={'LocationConstraint': S3_REGION}
                        )

                logger.info(f"S3 bucket '{S3_BUCKET_NAME}' created successfully")

                # Optional: Set bucket policy for public read
                # Only enable if you want all files publicly accessible
                # set_public_read_policy(s3_client, S3_BUCKET_NAME)

                return True
            else:
                logger.error(f"Error checking bucket: {e}")
                return False

    except Exception as e:
        logger.error(f"S3 bucket initialization failed: {e}")
        return False


def set_public_read_policy(s3_client, bucket_name):
    """
    Set bucket policy to allow public read access (OPTIONAL)
    Use with caution - this makes all files in the bucket publicly accessible

    Args:
        s3_client: Boto3 S3 client
        bucket_name (str): Bucket name
    """
    import json

    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicRead",
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
        }]
    }

    try:
        s3_client.put_bucket_policy(
            Bucket=bucket_name,
            Policy=json.dumps(bucket_policy)
        )
        logger.info(f"Public read policy applied to bucket '{bucket_name}'")
    except Exception as e:
        logger.warning(f"Failed to set public read policy: {e}")


def calculate_file_checksum(file_path):
    """
    Calculate SHA256 checksum of a file

    Args:
        file_path (str): Path to file

    Returns:
        str: SHA256 hex digest
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def verify_file_integrity(file_path, expected_checksum):
    """
    Verify file integrity using SHA256 checksum

    Args:
        file_path (str): Path to file
        expected_checksum (str): Expected SHA256 hex digest

    Returns:
        bool: True if checksum matches
    """
    actual_checksum = calculate_file_checksum(file_path)
    return actual_checksum == expected_checksum


# Health check function for monitoring
def check_s3_connection():
    """
    Check S3 connection health

    Returns:
        dict: Connection status and details
    """
    try:
        s3_client = get_s3_client()

        # Try to list objects (lightweight operation)
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_NAME,
            MaxKeys=1
        )

        return {
            'status': 'healthy',
            'bucket': S3_BUCKET_NAME,
            'endpoint': S3_ENDPOINT or 'AWS S3',
            'region': S3_REGION
        }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e),
            'bucket': S3_BUCKET_NAME,
            'endpoint': S3_ENDPOINT or 'AWS S3'
        }
