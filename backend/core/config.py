"""Configuration Management

Centralized configuration for the entire application.
Loads environment variables and provides typed access.
"""

import os
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

# Load environment variables
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')


class Config:
    """Application configuration."""
    
    # ========================================================================
    # Storage Configuration
    # ========================================================================
    STORAGE_TYPE: Literal['local', 's3'] = os.getenv('STORAGE_TYPE', 'local')
    
    # Local storage settings
    BACKEND_DIR = ROOT_DIR
    TEMPLATES_DIR = BACKEND_DIR / 'templates'
    UPLOADS_DIR = BACKEND_DIR / 'uploads'
    OUTPUT_DIR = BACKEND_DIR / 'output'
    
    # S3 storage settings (for future use)
    S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', '')
    S3_REGION = os.getenv('S3_REGION', 'us-east-1')
    S3_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID', '')
    S3_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')
    S3_TEMPLATES_PREFIX = os.getenv('S3_TEMPLATES_PREFIX', 'templates/')
    
    # ========================================================================
    # Database Configuration
    # ========================================================================
    MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    DB_NAME = os.environ.get('DB_NAME', 'storyme_db')
    
    # ========================================================================
    # CORS Configuration
    # ========================================================================
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')
    
    # ========================================================================
    # Application Settings
    # ========================================================================
    MAX_UPLOAD_SIZE_MB = int(os.getenv('MAX_UPLOAD_SIZE_MB', '5'))
    ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
    
    # ========================================================================
    # Logging
    # ========================================================================
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    @classmethod
    def ensure_directories(cls):
        """Ensure required directories exist (for local storage)."""
        if cls.STORAGE_TYPE == 'local':
            cls.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def get_storage_info(cls) -> dict:
        """Get storage configuration info for logging."""
        if cls.STORAGE_TYPE == 's3':
            return {
                'type': 's3',
                'bucket': cls.S3_BUCKET_NAME,
                'region': cls.S3_REGION,
            }
        return {
            'type': 'local',
            'templates_dir': str(cls.TEMPLATES_DIR),
            'uploads_dir': str(cls.UPLOADS_DIR),
            'output_dir': str(cls.OUTPUT_DIR),
        }


# Create singleton instance
config = Config()

# Ensure directories on import
config.ensure_directories()
