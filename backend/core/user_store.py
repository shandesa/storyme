"""
core/user_store.py
===================
Persistent user store backed by Azure Table Storage.

Replaces backend/core/local_user_store.py (JSON file store).
The JSON file was in the Azure App Service extraction directory
(/tmp/<hash>/) which is wiped on every deployment and restart —
making every user appear as NEW after any redeploy.

Azure Table: Users
  PK = "storyme"     (single partition — user count is small)
  RK = mobile        (10-digit Indian mobile number, unique)

Fields stored:
  mobile          string     10-digit number
  password_hash   string     bcrypt hash (via passlib)
  country_code    string     "+91"
  created_at      string     ISO-8601 UTC
  last_login_at   string     ISO-8601 UTC (updated on every successful login)

Fallback: If AZURE_STORAGE_CONNECTION_STRING is not set (local dev),
falls back to the original JSON file store so local development is
unaffected.

Password security:
  Passwords are stored as bcrypt hashes (cost factor 12).
  Plaintext passwords are NEVER stored or logged.
  Legacy plaintext passwords in the JSON store are migrated on first
  successful login (re-hashed and saved to Azure Table).
"""

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bcrypt as _bcrypt

logger = logging.getLogger(__name__)

_PARTITION_KEY = "storyme"
_TABLE_NAME    = "Users"

# ─── Password helpers ─────────────────────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    """Return bcrypt hash of plaintext password (cost=12)."""
    return _bcrypt.hashpw(
        plaintext.encode("utf-8"),
        _bcrypt.gensalt(rounds=12),
    ).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True if plaintext matches the stored hash."""
    try:
        # Support legacy plaintext passwords during migration window
        if not hashed.startswith("$2"):
            return plaintext == hashed
        return _bcrypt.checkpw(
            plaintext.encode("utf-8"),
            hashed.encode("utf-8"),
        )
    except Exception:
        return False


def is_hashed(password: str) -> bool:
    """Return True if the password field is already a bcrypt hash."""
    return password.startswith("$2")


# ─── Azure Table user store ───────────────────────────────────────────────────

class AzureUserStore:
    """User persistence in Azure Table Storage."""

    def __init__(self, connection_string: str):
        self._conn   = connection_string
        self._client = None

    def _get_client(self):
        if self._client is None:
            from azure.data.tables import TableServiceClient
            svc          = TableServiceClient.from_connection_string(self._conn)
            self._client = svc.get_table_client(_TABLE_NAME)
            try:
                self._client.create_table()
                logger.info("Azure Table '%s' created", _TABLE_NAME)
            except Exception:
                pass  # already exists
        return self._client

    def get_user(self, mobile: str) -> Optional[dict]:
        """Return user dict or None."""
        client = self._get_client()
        try:
            entity = client.get_entity(
                partition_key=_PARTITION_KEY, row_key=mobile
            )
            return self._to_dict(entity)
        except Exception:
            return None

    def upsert_user(self, user_dict: dict) -> None:
        """Create or update a user record. Idempotent."""
        client = self._get_client()
        mobile = user_dict["mobile"]
        entity = {
            "PartitionKey":       _PARTITION_KEY,
            "RowKey":             mobile,
            "mobile":             mobile,
            "password_hash":      user_dict.get("password_hash", ""),
            "country_code":       user_dict.get("country_code", "+91"),
            "created_at":         user_dict.get("created_at",
                                  datetime.now(timezone.utc).isoformat()),
            "last_login_at":      user_dict.get("last_login_at", ""),
            "terms_accepted":     user_dict.get("terms_accepted", False),
            "terms_accepted_at":  user_dict.get("terms_accepted_at", ""),
        }
        client.upsert_entity(entity)
        logger.info("UserStore: upserted user %s", mobile)

    def touch_login(self, mobile: str) -> None:
        """Update last_login_at timestamp."""
        user = self.get_user(mobile)
        if user:
            user["last_login_at"] = datetime.now(timezone.utc).isoformat()
            self.upsert_user(user)

    @staticmethod
    def _to_dict(entity) -> dict:
        return {
            "mobile":           entity.get("mobile", entity.get("RowKey", "")),
            "password_hash":    entity.get("password_hash", ""),
            "country_code":     entity.get("country_code", "+91"),
            "created_at":       entity.get("created_at", ""),
            "last_login_at":    entity.get("last_login_at", ""),
            "terms_accepted":   entity.get("terms_accepted", False),
            "terms_accepted_at": entity.get("terms_accepted_at", ""),
        }


# ─── JSON file fallback (local dev) ──────────────────────────────────────────

class JsonUserStore:
    """
    Local JSON file store — used when Azure is not configured.
    Suitable for local development only. Data is NOT persisted across
    Azure App Service restarts (extraction dir is ephemeral).
    """

    _DATA_DIR = Path(__file__).parent.parent / "data"
    _FILE     = _DATA_DIR / "users.json"

    def _load(self) -> dict:
        self._DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self._FILE.exists():
            self._FILE.write_text("{}")
        try:
            return json.loads(self._FILE.read_text())
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        self._DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._FILE.write_text(json.dumps(data, indent=2, default=str))

    def get_user(self, mobile: str) -> Optional[dict]:
        data = self._load()
        rec  = data.get(mobile)
        if rec is None:
            return None
        # Normalise: old records have 'password' instead of 'password_hash'
        if "password" in rec and "password_hash" not in rec:
            rec["password_hash"] = rec["password"]
        # Normalise: ensure terms fields exist for legacy records
        rec.setdefault("terms_accepted", False)
        rec.setdefault("terms_accepted_at", "")
        return rec

    def upsert_user(self, user_dict: dict) -> None:
        data = self._load()
        data[user_dict["mobile"]] = user_dict
        self._save(data)
        logger.info("JsonUserStore: upserted user %s", user_dict["mobile"])

    def touch_login(self, mobile: str) -> None:
        user = self.get_user(mobile)
        if user:
            user["last_login_at"] = datetime.now(timezone.utc).isoformat()
            self.upsert_user(user)


# ─── Factory + singleton ──────────────────────────────────────────────────────

def _create_user_store():
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn and conn.startswith("DefaultEndpointsProtocol"):
        logger.info("UserStore → AzureUserStore (table: %s)", _TABLE_NAME)
        return AzureUserStore(conn)
    logger.warning(
        "UserStore → JsonUserStore (local dev only — NOT persisted on Azure restarts)"
    )
    return JsonUserStore()


_store = _create_user_store()


# ─── Public API (drop-in replacement for local_user_store) ───────────────────

def get_user(mobile: str) -> Optional[dict]:
    """Return user dict or None. Compatible with old local_user_store.get_user()."""
    return _store.get_user(mobile)


def upsert_user(user_dict: dict) -> None:
    """Create or update user."""
    _store.upsert_user(user_dict)


def touch_login(mobile: str) -> None:
    """Update last_login_at on successful login."""
    _store.touch_login(mobile)


def user_exists(mobile: str) -> bool:
    """Return True if a user record exists for this mobile."""
    return _store.get_user(mobile) is not None


def update_user_terms(mobile: str, accepted: bool) -> Optional[dict]:
    """Record the user's Terms & Conditions acceptance decision.

    Fetches the existing record, sets terms_accepted + terms_accepted_at,
    writes it back, and returns the updated dict.
    Returns None if the user does not exist.
    """
    user = _store.get_user(mobile)
    if user is None:
        return None
    user["terms_accepted"]    = accepted
    user["terms_accepted_at"] = datetime.now(timezone.utc).isoformat()
    _store.upsert_user(user)
    logger.info("Terms acceptance recorded for %s: accepted=%s", mobile, accepted)
    return user
