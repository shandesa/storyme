"""
core/kid_profile_store.py
==========================
Persistent store for kid (child) profiles per StoryMe user.

Each user can save up to MAX_KID_PROFILES_PER_USER profiles.
Each profile holds the child's name, gender, age, optional notes,
and a permanent blob path for their photo (used for story generation
without requiring a re-upload on every session).

Storage follows the same dual-backend pattern as address_store.py:
  Production  → AzureKidProfileStore  (Azure Table: KidProfiles)
  Local dev   → JsonKidProfileStore   (backend/data/kid_profiles.json)

Azure Table layout:
  Table:         KidProfiles
  PartitionKey = user_mobile    (10-digit mobile)
  RowKey       = profile_id     (uuid hex, unique per profile)

Fields stored — see KidProfile data model in SPEC-003.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_KID_PROFILES_PER_USER = 5
_TABLE_NAME = "KidProfiles"
_DATA_DIR   = Path(__file__).parent.parent / "data"


# ─── ABC ─────────────────────────────────────────────────────────────────────

class KidProfileStore(ABC):
    @abstractmethod
    def list_profiles(self, user_mobile: str) -> list[dict]: ...

    @abstractmethod
    def get_profile(self, user_mobile: str, profile_id: str) -> Optional[dict]: ...

    @abstractmethod
    def upsert_profile(self, user_mobile: str, profile: dict) -> dict: ...

    @abstractmethod
    def delete_profile(self, user_mobile: str, profile_id: str) -> bool: ...

    @abstractmethod
    def count_profiles(self, user_mobile: str) -> int: ...


# ─── Azure Table implementation ───────────────────────────────────────────────

class AzureKidProfileStore(KidProfileStore):
    """Persists kid profiles in Azure Table Storage (KidProfiles table)."""

    def __init__(self, connection_string: str):
        self._conn   = connection_string
        self._client = None

    @staticmethod
    def _safe(mobile: str) -> str:
        import re
        cleaned = re.sub(r"[^\w]", "_", str(mobile).strip().lower())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned[:64] or "unknown"

    def _get_client(self):
        if self._client is None:
            from azure.data.tables import TableServiceClient
            svc = TableServiceClient.from_connection_string(self._conn)
            self._client = svc.get_table_client(_TABLE_NAME)
            try:
                self._client.create_table()
                logger.info("Azure Table '%s' created", _TABLE_NAME)
            except Exception:
                pass  # already exists
        return self._client

    @staticmethod
    def _entity_to_dict(entity) -> dict:
        return {
            "profile_id":      entity.get("RowKey",         entity.get("profile_id", "")),
            "user_mobile":     entity.get("PartitionKey",   entity.get("user_mobile", "")),
            "name":            entity.get("name",           ""),
            "gender":          entity.get("gender",         "neutral"),
            "age":             int(entity.get("age", 0) or 0),
            "notes":           entity.get("notes",          "") or "",
            "photo_blob_path": entity.get("photo_blob_path","") or "",
            "created_at":      entity.get("created_at",    ""),
            "updated_at":      entity.get("updated_at",    ""),
        }

    def list_profiles(self, user_mobile: str) -> list[dict]:
        client = self._get_client()
        pk = self._safe(user_mobile)
        try:
            entities = client.query_entities(f"PartitionKey eq '{pk}'")
            profiles = [self._entity_to_dict(e) for e in entities]
            profiles.sort(key=lambda p: p.get("created_at", ""))
            return profiles
        except Exception as exc:
            logger.error("AzureKidProfileStore.list_profiles error: %s", exc)
            return []

    def get_profile(self, user_mobile: str, profile_id: str) -> Optional[dict]:
        client = self._get_client()
        pk = self._safe(user_mobile)
        try:
            entity = client.get_entity(partition_key=pk, row_key=profile_id)
            return self._entity_to_dict(entity)
        except Exception:
            return None

    def upsert_profile(self, user_mobile: str, profile: dict) -> dict:
        client = self._get_client()
        pk         = self._safe(user_mobile)
        now        = datetime.now(timezone.utc).isoformat()
        profile_id = profile.get("profile_id") or uuid.uuid4().hex
        entity = {
            "PartitionKey":    pk,
            "RowKey":          profile_id,
            "profile_id":      profile_id,
            "user_mobile":     user_mobile,
            "name":            profile.get("name",            ""),
            "gender":          profile.get("gender",          "neutral"),
            "age":             int(profile.get("age", 0) or 0),
            "notes":           profile.get("notes",           "") or "",
            "photo_blob_path": profile.get("photo_blob_path", "") or "",
            "created_at":      profile.get("created_at",      now),
            "updated_at":      now,
        }
        client.upsert_entity(entity)
        logger.info("AzureKidProfileStore: upserted profile %s for %s", profile_id[:8], user_mobile)
        return self._entity_to_dict(entity)

    def delete_profile(self, user_mobile: str, profile_id: str) -> bool:
        client = self._get_client()
        pk = self._safe(user_mobile)
        try:
            client.delete_entity(partition_key=pk, row_key=profile_id)
            logger.info("AzureKidProfileStore: deleted profile %s for %s", profile_id[:8], user_mobile)
            return True
        except Exception:
            return False

    def count_profiles(self, user_mobile: str) -> int:
        return len(self.list_profiles(user_mobile))


# ─── JSON fallback for local dev ──────────────────────────────────────────────

class JsonKidProfileStore(KidProfileStore):
    """
    Local-dev fallback — persists profiles to backend/data/kid_profiles.json.
    Structure: { mobile: { profile_id: profile_dict, ... }, ... }
    NOT suitable for production.
    """

    def __init__(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _DATA_DIR / "kid_profiles.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.error("JsonKidProfileStore._load error: %s", exc)
            return {}

    def _save(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_profiles(self, user_mobile: str) -> list[dict]:
        profiles = list(self._load().get(user_mobile, {}).values())
        profiles.sort(key=lambda p: p.get("created_at", ""))
        return profiles

    def get_profile(self, user_mobile: str, profile_id: str) -> Optional[dict]:
        return self._load().get(user_mobile, {}).get(profile_id)

    def upsert_profile(self, user_mobile: str, profile: dict) -> dict:
        data = self._load()
        now  = datetime.now(timezone.utc).isoformat()
        profile_id = profile.get("profile_id") or uuid.uuid4().hex
        record = {
            **profile,
            "profile_id":  profile_id,
            "user_mobile": user_mobile,
            "updated_at":  now,
        }
        if "created_at" not in record:
            record["created_at"] = now
        data.setdefault(user_mobile, {})[profile_id] = record
        self._save(data)
        return record

    def delete_profile(self, user_mobile: str, profile_id: str) -> bool:
        data = self._load()
        if user_mobile in data and profile_id in data[user_mobile]:
            del data[user_mobile][profile_id]
            self._save(data)
            return True
        return False

    def count_profiles(self, user_mobile: str) -> int:
        return len(self._load().get(user_mobile, {}))


# ─── Factory + singleton ──────────────────────────────────────────────────────

def _create_store() -> KidProfileStore:
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn and conn.startswith("DefaultEndpointsProtocol"):
        logger.info("KidProfileStore → AzureKidProfileStore (table: %s)", _TABLE_NAME)
        return AzureKidProfileStore(conn)
    logger.warning(
        "KidProfileStore → JsonKidProfileStore (local dev only — not persisted on Azure restarts)"
    )
    return JsonKidProfileStore()


_store = _create_store()


# ─── Public API ───────────────────────────────────────────────────────────────

def list_profiles(user_mobile: str) -> list[dict]:
    """Return all kid profiles for a user, ordered by creation date."""
    return _store.list_profiles(user_mobile)


def get_profile(user_mobile: str, profile_id: str) -> Optional[dict]:
    """Return a single profile by ID, or None if not found / wrong user."""
    return _store.get_profile(user_mobile, profile_id)


def upsert_profile(user_mobile: str, profile: dict) -> dict:
    """Create or update a kid profile. Returns the saved profile dict."""
    return _store.upsert_profile(user_mobile, profile)


def delete_profile(user_mobile: str, profile_id: str) -> bool:
    """Delete a kid profile. Returns True if deleted, False if not found."""
    return _store.delete_profile(user_mobile, profile_id)


def count_profiles(user_mobile: str) -> int:
    """Return the number of kid profiles for a user."""
    return _store.count_profiles(user_mobile)
