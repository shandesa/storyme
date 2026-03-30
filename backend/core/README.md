# Backend Core - Infrastructure Layer

## Purpose

The `core/` directory contains fundamental infrastructure components that support the entire backend application. These are low-level utilities that handle configuration management and storage abstraction.

## Placement in Architecture

```
Application
    │
    ├── Routes (HTTP Layer)
    │
    ├── Services (Business Logic)
    │
    └── CORE (Infrastructure)  ← YOU ARE HERE
            │
            ├── Configuration Management
            └── Storage Abstraction
```

## Files

### `config.py` - Configuration Management

**Purpose**: Centralized configuration for the entire application.

**Responsibilities**:
- Load environment variables from `.env`
- Provide typed access to configuration
- Validate configuration on startup
- Support multiple environments (dev, staging, prod)

**Key Features**:
```python
from core.config import config

# Access configuration
config.STORAGE_TYPE        # 'local' or 's3'
config.MONGO_URL           # Database connection
config.TEMPLATES_DIR       # Template directory path
config.MAX_UPLOAD_SIZE_MB  # File size limit
```

**Configuration Sources**:
1. Environment variables (`.env` file)
2. Default values (fallbacks)
3. Runtime validation

**Why Centralized Configuration?**
- Single source of truth
- Easy to change settings
- Environment-specific overrides
- Type safety

---

### `storage.py` - Storage Abstraction Layer

**Purpose**: Provide unified interface for file operations across different storage backends.

**Responsibilities**:
- Abstract file operations (read, write, delete, exists)
- Support multiple storage backends (local, S3)
- Enable seamless migration between backends
- No business logic - pure infrastructure

**Interface Design**:
```python
class StorageInterface(ABC):
    def get_file_path(self, path: str) -> str
    def read_file(self, path: str) -> bytes
    def save_file(self, file: BinaryIO, path: str) -> str
    def delete_file(self, path: str) -> bool
    def file_exists(self, path: str) -> bool
```

**Implementations**:

1. **LocalStorage**:
   - Reads/writes to local filesystem
   - Base path: `/app/backend/`
   - Fast, simple, good for development

2. **S3Storage**:
   - Reads/writes to Amazon S3
   - Requires boto3 library
   - Scalable, production-ready
   - Supports CloudFront CDN

**Usage**:
```python
from core.storage import storage

# Read file (works with local or S3)
content = storage.read_file("templates/stories/forest_of_smiles/page1.png")

# Save file
storage.save_file(file_obj, "uploads/photo.jpg")

# Check existence
if storage.file_exists("templates/page1.png"):
    # ...
```

**Factory Pattern**:
```python
def get_storage() -> StorageInterface:
    if config.STORAGE_TYPE == 's3':
        return S3Storage(...)
    return LocalStorage(...)
```

---

## Capabilities

### 1. Environment-Based Configuration

**Development**:
```bash
STORAGE_TYPE=local
LOG_LEVEL=DEBUG
```

**Production**:
```bash
STORAGE_TYPE=s3
S3_BUCKET_NAME=storyme-prod
LOG_LEVEL=INFO
```

### 2. Storage Backend Switching

**Zero Code Changes Required**:
```bash
# Switch from local to S3
STORAGE_TYPE=s3

# Restart application
sudo supervisorctl restart backend

# All services automatically use S3
```

### 3. Extensibility

**Add New Storage Backend**:
```python
class AzureBlobStorage(StorageInterface):
    def read_file(self, path: str) -> bytes:
        # Azure-specific implementation
        ...

# Update factory
def get_storage():
    if config.STORAGE_TYPE == 'azure':
        return AzureBlobStorage(...)
    # ...
```

### 4. Configuration Validation

```python
# On startup
config.ensure_directories()  # Create required directories
config.get_storage_info()    # Log storage configuration
```

---

## Design Principles

### 1. Dependency Inversion

**Problem**: Services shouldn't depend on specific storage implementations.

**Solution**: Services depend on `StorageInterface`, not concrete classes.

```python
# Bad
from core.storage import LocalStorage
storage = LocalStorage()  # Hardcoded dependency

# Good  
from core.storage import storage  # Interface-based
```

### 2. Single Responsibility

**config.py**: Only manages configuration
**storage.py**: Only handles file operations

No business logic, no HTTP concerns, no database operations.

### 3. Open/Closed Principle

**Open for extension**: Easy to add new storage backends
**Closed for modification**: Existing code doesn't change

---

## Usage Examples

### Configuration

```python
from core.config import config
import logging

# Setup logging
logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))

# Validate file size
if file_size > config.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
    raise ValueError("File too large")

# Get storage info
print(config.get_storage_info())
# Output: {'type': 'local', 'templates_dir': '/app/backend/templates'}
```

### Storage Operations

```python
from core.storage import storage

# Save uploaded file
with open('/tmp/uploaded.jpg', 'rb') as f:
    path = storage.save_file(f, "uploads/photo.jpg")
    print(f"Saved to: {path}")

# Read template
try:
    template_bytes = storage.read_file("templates/stories/forest_of_smiles/page1.png")
    img = Image.open(io.BytesIO(template_bytes))
except FileNotFoundError:
    print("Template not found")

# Check before reading
if storage.file_exists("templates/page1.png"):
    content = storage.read_file("templates/page1.png")

# Cleanup
storage.delete_file("uploads/temp.jpg")
```

---

## Testing

### Test Configuration

```python
import os
os.environ['STORAGE_TYPE'] = 'local'
os.environ['LOG_LEVEL'] = 'DEBUG'

from core.config import config
assert config.STORAGE_TYPE == 'local'
```

### Mock Storage

```python
class MockStorage(StorageInterface):
    def __init__(self):
        self.files = {}
    
    def save_file(self, file, path):
        self.files[path] = file.read()
        return path
    
    def read_file(self, path):
        return self.files[path]
```

---

## Migration Guide

### Local → S3

**Step 1: Install boto3**
```bash
pip install boto3
pip freeze > requirements.txt
```

**Step 2: Upload templates to S3**
```bash
aws s3 sync templates/ s3://your-bucket/templates/
```

**Step 3: Update configuration**
```bash
# .env
STORAGE_TYPE=s3
S3_BUCKET_NAME=your-bucket
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=yyy
```

**Step 4: Restart**
```bash
sudo supervisorctl restart backend
```

**Step 5: Verify**
```bash
curl http://localhost:8001/api/stories/verify/forest_of_smiles
# Should show: {"verified": 10, "total_pages": 10}
```

---

## Environment Variables

### Required
```bash
STORAGE_TYPE=local              # Storage backend
MONGO_URL=mongodb://...         # Database
DB_NAME=storyme_db             # Database name
```

### Optional (Local Storage)
```bash
MAX_UPLOAD_SIZE_MB=5           # Default: 5
LOG_LEVEL=INFO                 # Default: INFO
CORS_ORIGINS=*                 # Default: *
```

### Required (S3 Storage)
```bash
STORAGE_TYPE=s3
S3_BUCKET_NAME=your-bucket     # S3 bucket
S3_REGION=us-east-1           # AWS region
AWS_ACCESS_KEY_ID=xxx         # AWS credentials
AWS_SECRET_ACCESS_KEY=yyy     # AWS credentials
```

---

## Error Handling

### Configuration Errors

```python
# Missing required variable
if not config.MONGO_URL:
    raise ValueError("MONGO_URL not configured")

# Invalid storage type
if config.STORAGE_TYPE not in ['local', 's3']:
    raise ValueError(f"Invalid STORAGE_TYPE: {config.STORAGE_TYPE}")
```

### Storage Errors

```python
try:
    content = storage.read_file("missing.png")
except FileNotFoundError:
    logger.error("File not found")
    # Handle gracefully
```

---

## Best Practices

### DO
✅ Use `storage` singleton for all file operations
✅ Load configuration from `config` module
✅ Use relative paths (storage handles resolution)
✅ Handle `FileNotFoundError` gracefully
✅ Log storage operations

### DON'T
❌ Hardcode file paths
❌ Access environment variables directly
❌ Use `open()` for template files
❌ Import specific storage classes
❌ Mix configuration logic with business logic

---

## Dependencies

```txt
# Required
python-dotenv>=1.0.0       # For .env file loading
pydantic>=2.6.0            # For type validation

# Optional (for S3)
boto3>=1.34.0              # AWS SDK
```

---

## Future Enhancements

### Planned
1. **Google Cloud Storage** support
2. **Azure Blob Storage** support
3. **CDN URL generation** for templates
4. **Caching layer** (Redis)
5. **Signed URLs** for secure downloads

### Possible
- Configuration hot-reload
- Storage health checks
- Metrics collection
- Rate limiting configuration

---

## Summary

The `core/` directory provides:
- ✅ Centralized configuration management
- ✅ Storage abstraction for local/S3
- ✅ Environment-based setup
- ✅ Zero-code backend switching
- ✅ Foundation for scalable architecture

**Key Takeaway**: All file operations and configuration access goes through this layer, enabling clean architecture and easy migration.
