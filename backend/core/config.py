"""Configuration Management

Centralised configuration for the entire application.
Loads environment variables and provides typed access.
"""

import os
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')


class Config:
    """Application configuration."""

    # =========================================================================
    # Storage Configuration
    # =========================================================================
    STORAGE_TYPE: Literal['local', 's3', 'azure'] = os.getenv('STORAGE_TYPE', 'local')

    BACKEND_DIR   = ROOT_DIR
    TEMPLATES_DIR = BACKEND_DIR / 'templates'
    UPLOADS_DIR   = BACKEND_DIR / 'uploads'
    OUTPUT_DIR    = BACKEND_DIR / 'output'

    # S3 (for future use)
    S3_BUCKET_NAME       = os.getenv('S3_BUCKET_NAME', '')
    S3_REGION            = os.getenv('S3_REGION', 'us-east-1')
    S3_ACCESS_KEY        = os.getenv('AWS_ACCESS_KEY_ID', '')
    S3_SECRET_KEY        = os.getenv('AWS_SECRET_ACCESS_KEY', '')
    S3_TEMPLATES_PREFIX  = os.getenv('S3_TEMPLATES_PREFIX', 'templates/')

    # =========================================================================
    # Database Configuration
    # =========================================================================
    MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    DB_NAME   = os.environ.get('DB_NAME', 'storyme_db')

    # =========================================================================
    # CORS Configuration
    # =========================================================================
    # Default to wildcard — safe because allow_credentials=False (no cookies).
    # Per the CORS spec, allow_origins=["*"] + allow_credentials=False is
    # fully valid and browsers accept it without restriction.
    # Override with a comma-separated list via the CORS_ORIGINS env var in
    # Azure App Service → Configuration → Application settings if needed.
    # Robust parsing to avoid empty/invalid values breaking CORS
    origins = os.getenv("CORS_ORIGINS", "")

    if not origins or origins.strip() == "":
        CORS_ORIGINS = ["*"]
    else:
        CORS_ORIGINS = [
            o.strip() for o in origins.split(",") if o.strip()
        ]

    

    # =========================================================================
    # Application Settings
    # =========================================================================
    MAX_UPLOAD_SIZE_MB   = int(os.getenv('MAX_UPLOAD_SIZE_MB', '5'))
    ALLOWED_IMAGE_TYPES  = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']

    # =========================================================================
    # Logging
    # =========================================================================
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    @classmethod
    def ensure_directories(cls):
        """Ensure required directories exist (local storage only)."""
        if cls.STORAGE_TYPE == 'local':
            cls.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_storage_info(cls) -> dict:
        if cls.STORAGE_TYPE == 's3':
            return {'type': 's3', 'bucket': cls.S3_BUCKET_NAME, 'region': cls.S3_REGION}
        return {
            'type': 'local',
            'templates_dir': str(cls.TEMPLATES_DIR),
            'uploads_dir':   str(cls.UPLOADS_DIR),
            'output_dir':    str(cls.OUTPUT_DIR),
        }


config = Config()
config.ensure_directories()


# NOTE: Config class body ends above. These module-level additions extend it.
# Azure Blob Storage settings are injected as class attributes below to
# keep the Config class compatible with existing code that imports Config directly.
Config.AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING', '')
Config.AZURE_STORAGE_CONTAINER_NAME = os.getenv('AZURE_STORAGE_CONTAINER_NAME', 'storyme-assets')
# Prefix paths within the container (mirrors LocalStorage directory structure)
Config.AZURE_UPLOADS_PREFIX   = os.getenv('AZURE_UPLOADS_PREFIX', 'uploads/')
Config.AZURE_OUTPUT_PREFIX    = os.getenv('AZURE_OUTPUT_PREFIX', 'output/')
Config.AZURE_TEMPLATES_PREFIX = os.getenv('AZURE_TEMPLATES_PREFIX', 'templates/')
