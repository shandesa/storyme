"""
core/address_store.py
======================
Persistent address book for StoryMe users.

Each user can save up to MAX_ADDRESSES_PER_USER delivery addresses for
reuse at checkout. Storage follows the same dual-backend pattern as
user_store.py:

  Production  → AzureAddressStore  (Azure Table: UserAddresses)
  Local dev   → JsonAddressStore   (backend/data/addresses.json)

Azure Table layout:
  Table:         UserAddresses
  PartitionKey = safe(mobile)   — 10-digit mobile, lowercased
  RowKey       = address_id     — uuid hex, unique per address

Fields stored:
  address_id    string  uuid hex
  label         string  e.g. "Home", "Office"
  full_name     string
  line1         string
  line2         string  (optional, may be empty)
  city          string
  state         string
  pincode       string  6 digits
  phone         string  10 digits
  country       string  default "India"
  created_at    string  ISO-8601 UTC
  updated_at    string  ISO-8601 UTC
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

MAX_ADDRESSES_PER_USER = 10
_TABLE_NAME = "UserAddresses"
_DATA_DIR = Path(__file__).parent.parent / "data"


# ─── ABC ─────────────────────────────────────────────────────────────────────

class AddressStore(ABC):
    @abstractmethod
    def list_addresses(self, mobile: str) -> list[dict]: ...

    @abstractmethod
    def get_address(self, mobile: str, address_id: str) -> Optional[dict]: ...

    @abstractmethod
    def upsert_address(self, mobile: str, address: dict) -> dict: ...

    @abstractmethod
    def delete_address(self, mobile: str, address_id: str) -> bool: ...

    @abstractmethod
    def count_addresses(self, mobile: str) -> int: ...


# ─── Azure Table implementation ───────────────────────────────────────────────

class AzureAddressStore(AddressStore):
    """Persists addresses in Azure Table Storage (UserAddresses table)."""

    def __init__(self, connection_string: str):
        self._conn = connection_string
        self._client = None

    @staticmethod
    def _safe(mobile: str) -> str:
        """Sanitise mobile for use as a PartitionKey."""
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
            "address_id": entity.get("RowKey", entity.get("address_id", "")),
            "label":      entity.get("label", "Home"),
            "full_name":  entity.get("full_name", ""),
            "line1":      entity.get("line1", ""),
            "line2":      entity.get("line2", "") or "",
            "city":       entity.get("city", ""),
            "state":      entity.get("state", ""),
            "pincode":    entity.get("pincode", ""),
            "phone":      entity.get("phone", ""),
            "country":    entity.get("country", "India"),
            "created_at": entity.get("created_at", ""),
            "updated_at": entity.get("updated_at", ""),
        }

    def list_addresses(self, mobile: str) -> list[dict]:
        client = self._get_client()
        pk = self._safe(mobile)
        try:
            entities = client.query_entities(
                query_filter=f"PartitionKey eq '{pk}'"
            )
            addrs = [self._entity_to_dict(e) for e in entities]
            addrs.sort(key=lambda a: a.get("created_at", ""))
            return addrs
        except Exception as exc:
            logger.error("AzureAddressStore.list_addresses error: %s", exc)
            return []

    def get_address(self, mobile: str, address_id: str) -> Optional[dict]:
        client = self._get_client()
        pk = self._safe(mobile)
        try:
            entity = client.get_entity(partition_key=pk, row_key=address_id)
            return self._entity_to_dict(entity)
        except Exception:
            return None

    def upsert_address(self, mobile: str, address: dict) -> dict:
        client = self._get_client()
        pk = self._safe(mobile)
        now = datetime.now(timezone.utc).isoformat()
        address_id = address.get("address_id") or uuid.uuid4().hex
        entity = {
            "PartitionKey": pk,
            "RowKey":       address_id,
            "address_id":   address_id,
            "label":        address.get("label", "Home"),
            "full_name":    address.get("full_name", ""),
            "line1":        address.get("line1", ""),
            "line2":        address.get("line2", "") or "",
            "city":         address.get("city", ""),
            "state":        address.get("state", ""),
            "pincode":      address.get("pincode", ""),
            "phone":        address.get("phone", ""),
            "country":      address.get("country", "India"),
            "created_at":   address.get("created_at", now),
            "updated_at":   now,
        }
        client.upsert_entity(entity)
        logger.info("AzureAddressStore: upserted address %s for %s", address_id[:8], mobile)
        return self._entity_to_dict(entity)

    def delete_address(self, mobile: str, address_id: str) -> bool:
        client = self._get_client()
        pk = self._safe(mobile)
        try:
            client.delete_entity(partition_key=pk, row_key=address_id)
            logger.info("AzureAddressStore: deleted address %s for %s", address_id[:8], mobile)
            return True
        except Exception:
            return False

    def count_addresses(self, mobile: str) -> int:
        return len(self.list_addresses(mobile))


# ─── JSON fallback for local dev ──────────────────────────────────────────────

class JsonAddressStore(AddressStore):
    """
    Local-dev fallback — persists addresses to backend/data/addresses.json.
    Structure: { mobile: { address_id: address_dict, ... }, ... }
    NOT suitable for production (single-process, no concurrency safety).
    """

    def __init__(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _DATA_DIR / "addresses.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.error("JsonAddressStore._load error: %s", exc)
            return {}

    def _save(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_addresses(self, mobile: str) -> list[dict]:
        user_addrs = self._load().get(mobile, {})
        addrs = list(user_addrs.values())
        addrs.sort(key=lambda a: a.get("created_at", ""))
        return addrs

    def get_address(self, mobile: str, address_id: str) -> Optional[dict]:
        return self._load().get(mobile, {}).get(address_id)

    def upsert_address(self, mobile: str, address: dict) -> dict:
        data = self._load()
        now = datetime.now(timezone.utc).isoformat()
        address_id = address.get("address_id") or uuid.uuid4().hex
        record = {**address, "address_id": address_id, "updated_at": now}
        if "created_at" not in record:
            record["created_at"] = now
        data.setdefault(mobile, {})[address_id] = record
        self._save(data)
        return record

    def delete_address(self, mobile: str, address_id: str) -> bool:
        data = self._load()
        if mobile in data and address_id in data[mobile]:
            del data[mobile][address_id]
            self._save(data)
            return True
        return False

    def count_addresses(self, mobile: str) -> int:
        return len(self._load().get(mobile, {}))


# ─── Factory + singleton ─────────────────────────────────────────────────────

def _create_address_store() -> AddressStore:
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn and conn.startswith("DefaultEndpointsProtocol"):
        logger.info("AddressStore → AzureAddressStore (table: %s)", _TABLE_NAME)
        return AzureAddressStore(conn)
    logger.warning(
        "AddressStore → JsonAddressStore (local dev only — not persisted on Azure restarts)"
    )
    return JsonAddressStore()


_store = _create_address_store()


# ─── Public API ───────────────────────────────────────────────────────────────

def list_addresses(mobile: str) -> list[dict]:
    """Return all saved addresses for a user, ordered by creation date."""
    return _store.list_addresses(mobile)


def get_address(mobile: str, address_id: str) -> Optional[dict]:
    """Return a single address by ID, or None."""
    return _store.get_address(mobile, address_id)


def upsert_address(mobile: str, address: dict) -> dict:
    """Create or update an address record. Returns the saved address dict."""
    return _store.upsert_address(mobile, address)


def delete_address(mobile: str, address_id: str) -> bool:
    """Delete an address. Returns True if deleted, False if not found."""
    return _store.delete_address(mobile, address_id)


def count_addresses(mobile: str) -> int:
    """Return the number of saved addresses for a user."""
    return _store.count_addresses(mobile)
