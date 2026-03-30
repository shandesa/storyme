"""Storage Abstraction Layer

Provides a unified interface for file storage operations.
Supports:
- Local filesystem storage
- Amazon S3 storage (extensible)

This abstraction allows switching storage backends without changing
business logic in services.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional
import shutil
import logging

logger = logging.getLogger(__name__)


class StorageInterface(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    def get_file_path(self, path: str) -> str:
        """Get the full path/URL for a file.
        
        Args:
            path: Relative path to file
        
        Returns:
            Full path (local) or URL (S3)
        """
        pass
    
    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read file content as bytes.
        
        Args:
            path: Relative path to file
        
        Returns:
            File content as bytes
        """
        pass
    
    @abstractmethod
    def save_file(self, file: BinaryIO, path: str) -> str:
        """Save file to storage.
        
        Args:
            file: File-like object to save
            path: Relative path where to save
        
        Returns:
            Full path/URL of saved file
        """
        pass
    
    @abstractmethod
    def delete_file(self, path: str) -> bool:
        """Delete file from storage.
        
        Args:
            path: Relative path to file
        
        Returns:
            True if deleted successfully
        """
        pass
    
    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """Check if file exists.
        
        Args:
            path: Relative path to file
        
        Returns:
            True if file exists
        """
        pass


class LocalStorage(StorageInterface):
    """Local filesystem storage implementation."""
    
    def __init__(self, base_path: str):
        """Initialize local storage.
        
        Args:
            base_path: Base directory for all file operations
        """
        self.base_path = Path(base_path)
        logger.info(f"LocalStorage initialized with base_path: {self.base_path}")
    
    def get_file_path(self, path: str) -> str:
        """Get absolute local file path."""
        full_path = self.base_path / path
        return str(full_path.absolute())
    
    def read_file(self, path: str) -> bytes:
        """Read file from local filesystem."""
        file_path = Path(self.get_file_path(path))
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(file_path, 'rb') as f:
            return f.read()
    
    def save_file(self, file: BinaryIO, path: str) -> str:
        """Save file to local filesystem."""
        dest_path = Path(self.get_file_path(path))
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(dest_path, 'wb') as f:
            shutil.copyfileobj(file, f)
        
        logger.info(f"File saved to local storage: {dest_path}")
        return str(dest_path.absolute())
    
    def delete_file(self, path: str) -> bool:
        """Delete file from local filesystem."""
        try:
            file_path = Path(self.get_file_path(path))
            if file_path.exists():
                file_path.unlink()
                logger.info(f"File deleted from local storage: {path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting file {path}: {e}")
            return False
    
    def file_exists(self, path: str) -> bool:
        """Check if file exists in local filesystem."""
        file_path = Path(self.get_file_path(path))
        return file_path.exists()


class S3Storage(StorageInterface):
    """Amazon S3 storage implementation (stub for future use)."""
    
    def __init__(self, bucket_name: str, region: str = 'us-east-1',
                 access_key: Optional[str] = None, secret_key: Optional[str] = None):
        """Initialize S3 storage.
        
        Args:
            bucket_name: S3 bucket name
            region: AWS region
            access_key: AWS access key (optional, uses boto3 defaults)
            secret_key: AWS secret key (optional, uses boto3 defaults)
        """
        self.bucket_name = bucket_name
        self.region = region
        
        # Import boto3 only if S3 storage is used
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
            raise ImportError(
                "boto3 is required for S3 storage. Install it with: pip install boto3"
            )
    
    def get_file_path(self, path: str) -> str:
        """Get S3 URL for file."""
        return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{path}"
    
    def read_file(self, path: str) -> bytes:
        """Read file from S3."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=path)
            return response['Body'].read()
        except self.ClientError as e:
            logger.error(f"Error reading file from S3: {e}")
            raise FileNotFoundError(f"File not found in S3: {path}")
    
    def save_file(self, file: BinaryIO, path: str) -> str:
        """Upload file to S3."""
        try:
            self.s3_client.upload_fileobj(file, self.bucket_name, path)
            logger.info(f"File uploaded to S3: s3://{self.bucket_name}/{path}")
            return self.get_file_path(path)
        except self.ClientError as e:
            logger.error(f"Error uploading file to S3: {e}")
            raise
    
    def delete_file(self, path: str) -> bool:
        """Delete file from S3."""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=path)
            logger.info(f"File deleted from S3: {path}")
            return True
        except self.ClientError as e:
            logger.error(f"Error deleting file from S3: {e}")
            return False
    
    def file_exists(self, path: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=path)
            return True
        except self.ClientError:
            return False


# ============================================================================
# Storage Factory
# ============================================================================

def get_storage() -> StorageInterface:
    """Get storage instance based on configuration.
    
    Returns:
        Storage instance (LocalStorage or S3Storage)
    """
    from core.config import config
    
    if config.STORAGE_TYPE == 's3':
        logger.info("Initializing S3 storage")
        return S3Storage(
            bucket_name=config.S3_BUCKET_NAME,
            region=config.S3_REGION,
            access_key=config.S3_ACCESS_KEY,
            secret_key=config.S3_SECRET_KEY,
        )
    
    # Default: Local storage
    logger.info("Initializing Local storage")
    return LocalStorage(base_path=str(config.BACKEND_DIR))


# Create singleton storage instance
storage = get_storage()
