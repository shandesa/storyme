from pathlib import Path
import shutil
from typing import BinaryIO


def save_file(file: BinaryIO, path: str) -> str:
    """Save uploaded file to specified path.
    
    Args:
        file: File-like object to save
        path: Destination path
    
    Returns:
        Absolute path where file was saved
    """
    dest_path = Path(path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(dest_path, 'wb') as f:
        shutil.copyfileobj(file, f)
    
    return str(dest_path.absolute())


def delete_file(path: str) -> bool:
    """Delete file at specified path.
    
    Args:
        path: Path to file to delete
    
    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
            return True
        return False
    except Exception:
        return False


def ensure_directory(path: str) -> None:
    """Ensure directory exists."""
    Path(path).mkdir(parents=True, exist_ok=True)
