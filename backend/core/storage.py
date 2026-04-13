"""
Storage Abstraction Layer

Provides a unified interface for file storage operations.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional
import shutil
import logging

logger = logging.getLogger(__name__)

# ✅ BASE_DIR points to backend/
BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================================
# Abstract Interface
# ============================================================================

class StorageInterface(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def get_file_path(self, path: str) -> str:
        pass

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        pass

    @abstractmethod
    def save_file(self, file: BinaryIO, path: str) -> str:
        pass

    @abstractmethod
    def delete_file(self, path: str) -> bool:
        pass

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        pass


# ============================================================================
# Local Storage (FIXED)
# ============================================================================

class LocalStorage(StorageInterface):
    """Local filesystem storage implementation."""

    def __init__(self, base_path: str):
        # Always normalize to backend root
        self.base_path = Path(base_path)

        # ✅ Ensure base_path is absolute (important for Azure)
        if not self.base_path.is_absolute():
            self.base_path = BASE_DIR

        logger.info(f"LocalStorage initialized with base_path: {self.base_path}")

    # ✅ CENTRAL FIX
    def _resolve_path(self, path: str) -> Path:
        """
        Resolve relative paths like:
        templates/... → backend/templates/...
        """
        path_obj = Path(path)

        # If already absolute, return as-is
        if path_obj.is_absolute():
            return path_obj

        return self.base_path / path_obj

    def get_file_path(self, path: str) -> str:
        full_path = self._resolve_path(path)
        return str(full_path)

    def read_file(self, path: str) -> bytes:
        file_path = self._resolve_path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, 'rb') as f:
            return f.read()

    def save_file(self, file: BinaryIO, path: str) -> str:
        dest_path = self._resolve_path(path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(dest_path, 'wb') as f:
            shutil.copyfileobj(file, f)

        logger.info(f"File saved to local storage: {dest_path}")
        return str(dest_path)

    def delete_file(self, path: str) -> bool:
        try:
            file_path = self._resolve_path(path)

            if file_path.exists():
                file_path.unlink()
                logger.info(f"File deleted: {file_path}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error deleting file {path}: {e}")
            return False

    def file_exists(self, path: str) -> bool:
        try:
            file_path = self._resolve_path(path)
            return file_path.exists()
        except Exception as e:
            logger.error(f"Error checking file existence: {path} → {e}")
            return False


# ============================================================================
# S3 Storage (UNCHANGED)
# ============================================================================

class S3Storage(StorageInterface):
    """Amazon S3 storage implementation."""

    def __init__(
        self,
        bucket_name: str,
        region: str = 'us-east-1',
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None
    ):
        self.bucket_name = bucket_name
        self.region = region

        try:
            import boto3
            from botocore.exceptions import ClientError

            session_kwargs = {}
            if access_key and secret_key:
                session_kwargs['aws_access_key_id'] = access_key
                session_kwargs['aws_secret_access_key'] = secret_key
                session_kwargs['region_name'] = region

            self.s3_client = boto3.client('s3', **session_kwargs)
            self.ClientError = ClientError

            logger.info(f"S3Storage initialized: bucket={bucket_name}, region={region}")

        except ImportError:
            raise ImportError("boto3 is required for S3 storage")

    def get_file_path(self, path: str) -> str:
        return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{path}"

    def read_file(self, path: str) -> bytes:
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=path)
            return response['Body'].read()
        except self.ClientError as e:
            logger.error(f"S3 read error: {e}")
            raise FileNotFoundError(f"File not found in S3: {path}")

    def save_file(self, file: BinaryIO, path: str) -> str:
        try:
            self.s3_client.upload_fileobj(file, self.bucket_name, path)
            return self.get_file_path(path)
        except self.ClientError as e:
            logger.error(f"S3 upload error: {e}")
            raise

    def delete_file(self, path: str) -> bool:
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=path)
            return True
        except self.ClientError as e:
            logger.error(f"S3 delete error: {e}")
            return False

    def file_exists(self, path: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=path)
            return True
        except self.ClientError:
            return False


# ============================================================================
# Factory
# ============================================================================

def get_storage() -> StorageInterface:
    from core.config import config

    if config.STORAGE_TYPE == 's3':
        return S3Storage(
            bucket_name=config.S3_BUCKET_NAME,
            region=config.S3_REGION,
            access_key=config.S3_ACCESS_KEY,
            secret_key=config.S3_SECRET_KEY,
        )

    return LocalStorage(base_path=str(config.BACKEND_DIR))


# Singleton
storage = get_storage()
