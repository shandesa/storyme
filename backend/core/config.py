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
    STORAGE_TYPE: Literal['local', 's3'] = os.getenv('STORAGE_TYPE', 'local')

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
    # Default includes the deployed SWA origin and localhost for local dev.
    # Override with a comma-separated list via the CORS_ORIGINS env var
    # in Azure App Service → Configuration → Application settings.
    #
    # Example:
    #   CORS_ORIGINS=https://gray-moss-04c4be41e7.azurestaticapps.net,http://localhost:3000
    #
    # The frontend uses credentials:"omit" so allow_credentials=False,
    # which means allow_origins=["*"] is valid per the CORS spec.
    _default_origins = ",".join([
        "https://gray-moss-04c4be41e7.azurestaticapps.net",   # Azure SWA (production)
        "http://localhost:3000",                                # local frontend dev
        "http://127.0.0.1:3000",
    ])
    CORS_ORIGINS: list = os.getenv('CORS_ORIGINS', _default_origins).split(',')

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
