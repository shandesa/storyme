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
# Azure Blob Storage
# ============================================================================

class AzureBlobStorage(StorageInterface):
    """
    Azure Blob Storage implementation for StoryMe.

    Stores:
      - uploads/   → user uploaded photos (short-lived)
      - output/    → generated page images + final PDFs
      - templates/ → story template PNGs (read-mostly)

    Environment variables required:
      AZURE_STORAGE_CONNECTION_STRING  — from Azure portal → Storage Account → Access keys
      AZURE_STORAGE_CONTAINER_NAME     — blob container name (e.g. "storyme-assets")

    Enable in Azure App Service → Configuration → Application settings:
      STORAGE_TYPE = azure

    All blobs use the path structure:
      {container}/{path}  →  e.g.  storyme-assets/output/abc123_page1.png
    """

    def __init__(self, connection_string: str, container_name: str):
        """
        Initialise AzureBlobStorage.

        Raises:
            ValueError   — if connection_string is empty or clearly malformed.
                           Caught by get_storage() which falls back to LocalStorage.
            ImportError  — if azure-storage-blob is not installed.
                           Also caught by get_storage().
            Exception    — any SDK-level error (bad key, network, etc.).
                           Also caught by get_storage().

        Design decision:
            We raise early with a clear, actionable message rather than letting
            the Azure SDK raise a cryptic KeyError: 'ACCOUNTNAME' (the root cause
            of the production outage: server crashed at import time because
            AZURE_STORAGE_CONNECTION_STRING was empty).
        """
        self.container_name = container_name

        # ── Step 1: Validate connection string BEFORE hitting the SDK ─────────
        # An empty string causes BlobServiceClient.from_connection_string() to
        # raise KeyError: 'ACCOUNTNAME' — not helpful. We catch this ourselves.
        if not connection_string or not connection_string.strip():
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING is empty or not set. "
                "Go to Azure Portal → App Service → Configuration → "
                "Application settings and add AZURE_STORAGE_CONNECTION_STRING "
                "with the full connection string from your Storage Account → Access keys. "
                "The server will fall back to local disk storage until this is corrected."
            )

        # Basic structure check: a valid Azure Storage connection string must
        # contain 'AccountName' and either 'AccountKey' or 'SharedAccessSignature'.
        cs_lower = connection_string.lower()
        if "accountname" not in cs_lower:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING appears malformed — missing 'AccountName'. "
                "Copy the full connection string from Azure Portal → Storage Account → Access keys. "
                "The server will fall back to local disk storage until this is corrected."
            )

        # ── Step 2: Import SDK (lazy — not at module level) ───────────────────
        try:
            from azure.storage.blob import BlobServiceClient, ContentSettings
        except ImportError:
            raise ImportError(
                "azure-storage-blob is not installed. "
                "Add 'azure-storage-blob' to requirements.txt and redeploy."
            )

        # ── Step 3: Connect and verify container ─────────────────────────────
        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._container = self._client.get_container_client(container_name)
        self._ContentSettings = ContentSettings

        # Ensure container exists (idempotent — safe to call on every startup)
        try:
            self._container.get_container_properties()
        except Exception:
            self._container.create_container()
            logger.info(f"Created Azure container: {container_name}")

        logger.info(f"AzureBlobStorage initialized: container={container_name}")

    def get_file_path(self, path: str) -> str:
        """Returns a public/SAS URL — currently returns the blob path for internal use."""
        blob = self._container.get_blob_client(path)
        return blob.url

    def read_file(self, path: str) -> bytes:
        """
        Read a file from Azure Blob Storage or local filesystem.

        Routing logic:
          1. Absolute paths (e.g. /tmp/.../uploads/uuid.jpg) — always local FS.
             These are ephemeral temp files written by the app during the request
             (uploaded user photos, in-flight composites). They are never in blob.
          2. Relative paths (e.g. uploads/uuid.jpg) — try blob first.
             If not in blob, fall back to local FS (covers bundled template assets
             that ship with the app but haven't been uploaded to blob).

        Fixes:
          - Bug: generate_v2.py saves upload with open(absolute_path) then
            extract_face() calls storage.read_file(absolute_path) → blob 404.
          - Bug: compose_page() reads templates via storage.read_file(relative_path)
            but templates are bundled on local disk, not in blob → blob 404.
        """
        path_obj = Path(path)

        # ── Case 1: Absolute path → always read from local filesystem ────────
        if path_obj.is_absolute():
            if not path_obj.exists():
                raise FileNotFoundError(f"File not found on local filesystem: {path}")
            logger.debug(f"Azure storage: reading absolute path from local FS: {path}")
            return path_obj.read_bytes()

        # ── Case 2: Relative path → try blob, fallback to local FS ───────────
        try:
            blob = self._container.get_blob_client(path)
            downloader = blob.download_blob()
            return downloader.readall()
        except Exception as e:
            logger.warning(f"Azure blob not found [{path}], trying local FS fallback: {e}")

        # Fallback: resolve relative path against the backend root
        # (handles templates and other bundled assets not uploaded to blob)
        from core.config import config as _cfg
        local_path = _cfg.BACKEND_DIR / path
        if local_path.exists():
            logger.info(f"Azure fallback: reading from local FS: {local_path}")
            return local_path.read_bytes()

        raise FileNotFoundError(
            f"Blob not found in Azure and not on local filesystem: {path}"
        )

    def save_file(self, file: BinaryIO, path: str) -> str:
        try:
            blob = self._container.get_blob_client(path)

            # Infer content type for browser-friendly delivery
            suffix = Path(path).suffix.lower()
            content_type_map = {
                ".png":  "image/png",
                ".jpg":  "image/jpeg",
                ".jpeg": "image/jpeg",
                ".pdf":  "application/pdf",
                ".webp": "image/webp",
            }
            ct = content_type_map.get(suffix, "application/octet-stream")
            content_settings = self._ContentSettings(content_type=ct)

            blob.upload_blob(file, overwrite=True, content_settings=content_settings)
            logger.info(f"Azure blob saved: {path}")
            return blob.url

        except Exception as e:
            logger.error(f"Azure upload error [{path}]: {e}")
            raise

    def delete_file(self, path: str) -> bool:
        try:
            blob = self._container.get_blob_client(path)
            blob.delete_blob()
            logger.info(f"Azure blob deleted: {path}")
            return True
        except Exception as e:
            logger.error(f"Azure delete error [{path}]: {e}")
            return False

    def file_exists(self, path: str) -> bool:
        try:
            blob = self._container.get_blob_client(path)
            blob.get_blob_properties()
            return True
        except Exception:
            return False


# ============================================================================
# Factory + Singleton
# ============================================================================

def get_storage() -> StorageInterface:
    """
    Instantiate and return the configured storage backend.

    CRITICAL DESIGN RULE — must never raise at module import time:
        This function is called as `storage = get_storage()` at module level.
        Any unhandled exception here crashes the gunicorn worker during import,
        which kills the entire server before FastAPI registers a single route.
        The health endpoint never responds, warm-up probes time out, and the
        frontend shows "Server is warming up..." indefinitely.

        Root cause of the April 2026 production outage:
            STORAGE_TYPE=azure was set but AZURE_STORAGE_CONNECTION_STRING was
            empty. BlobServiceClient.from_connection_string('') raised
            KeyError: 'ACCOUNTNAME'. The exception propagated to module level
            and crashed every worker on startup.

    Fallback strategy:
        If the configured backend (azure/s3) fails to initialise for ANY reason
        (missing env var, bad connection string, network error, missing package),
        we fall back to LocalStorage and log a CRITICAL warning. The server
        starts, all routes are available, and file I/O uses local disk.
        This is far better than a dead server.

        The operator can fix the configuration and restart the app without a
        code deployment.
    """
    from core.config import config

    if config.STORAGE_TYPE == 'azure':
        conn_str = config.AZURE_STORAGE_CONNECTION_STRING
        container = config.AZURE_STORAGE_CONTAINER_NAME
        try:
            instance = AzureBlobStorage(
                connection_string=conn_str,
                container_name=container,
            )
            logger.info("Storage backend: Azure Blob Storage")
            return instance
        except ValueError as e:
            # Empty / malformed connection string — configuration error
            logger.critical(
                f"AzureBlobStorage configuration error: {e} "
                "Falling back to LocalStorage. "
                "Fix AZURE_STORAGE_CONNECTION_STRING in App Service → Configuration."
            )
        except ImportError as e:
            logger.critical(
                f"AzureBlobStorage import error: {e} "
                "Falling back to LocalStorage."
            )
        except Exception as e:
            # SDK-level errors: bad key, unreachable endpoint, etc.
            logger.critical(
                f"AzureBlobStorage init failed unexpectedly: {type(e).__name__}: {e} "
                "Falling back to LocalStorage."
            )
        # Fallback — server stays alive, operator can fix config and restart
        logger.warning(
            "Using LocalStorage as fallback. "
            "File writes go to local disk and will NOT persist across Azure restarts. "
            "Set AZURE_STORAGE_CONNECTION_STRING correctly and restart the app."
        )
        return LocalStorage(base_path=str(config.BACKEND_DIR))

    if config.STORAGE_TYPE == 's3':
        try:
            instance = S3Storage(
                bucket_name=config.S3_BUCKET_NAME,
                region=config.S3_REGION,
                access_key=config.S3_ACCESS_KEY,
                secret_key=config.S3_SECRET_KEY,
            )
            logger.info("Storage backend: Amazon S3")
            return instance
        except Exception as e:
            logger.critical(
                f"S3Storage init failed: {type(e).__name__}: {e} "
                "Falling back to LocalStorage."
            )
        return LocalStorage(base_path=str(config.BACKEND_DIR))

    # Default: local filesystem
    logger.info("Storage backend: LocalStorage (local disk)")
    return LocalStorage(base_path=str(config.BACKEND_DIR))


# Module-level singleton — imported as `from core.storage import storage`.
# get_storage() is guaranteed not to raise (see docstring above), so this
# line is safe at import time even when cloud storage is misconfigured.
storage = get_storage()
