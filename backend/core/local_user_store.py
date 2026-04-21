"""
core/local_user_store.py — DEPRECATED COMPATIBILITY SHIM
=========================================================
This module previously held the JSON file user store.
It now delegates to core.user_store which uses Azure Table Storage.

Kept to avoid breaking any code that imports from here.
All new code should import from core.user_store directly.
"""
from core.user_store import get_user, upsert_user, user_exists

# Legacy compat: the old API used a User pydantic model
# Wrap dicts in a simple object that has .model_dump() for backward compat
from models.user import User as _User

def create_user(user: _User) -> None:
    """Legacy: accepts a User model. Delegates to user_store.upsert_user."""
    from core.user_store import hash_password, is_hashed
    d = {
        "mobile":        user.mobile,
        "password_hash": user.password if is_hashed(user.password)
                         else hash_password(user.password),
        "country_code":  user.country_code,
        "created_at":    user.created_at.isoformat() if user.created_at else "",
        "last_login_at": "",
    }
    upsert_user(d)
