"""Local JSON user store.

Persists users to backend/data/users.json.
Suitable for development / MVP; swap for a real DB when ready.
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional

from models.user import User

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_USER_DB  = _DATA_DIR / "users.json"


# ─── internal helpers ─────────────────────────────────────────────────────────

def _ensure_file() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _USER_DB.exists():
        _USER_DB.write_text("{}")


def _load() -> dict:
    _ensure_file()
    try:
        return json.loads(_USER_DB.read_text())
    except json.JSONDecodeError:
        logger.warning("users.json is corrupt — resetting to empty store")
        return {}


def _save(users: dict) -> None:
    _ensure_file()
    _USER_DB.write_text(json.dumps(users, indent=2, default=str))


# ─── public API ───────────────────────────────────────────────────────────────

def get_user(mobile: str) -> Optional[User]:
    """Return User for the given mobile number, or None if not found."""
    users = _load()
    record = users.get(mobile)
    if record:
        return User(**record)
    return None


def create_user(user: User) -> None:
    """Persist a new user (overwrites if mobile already exists)."""
    users = _load()
    users[user.mobile] = user.model_dump(mode="json")
    _save(users)
    logger.info(f"User created/updated: {user.mobile}")
