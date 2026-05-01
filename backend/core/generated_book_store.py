"""
core/generated_book_store.py
=============================
Tracks generated PDF storybooks per (user, kid profile, story).

Once a PDF is generated, the result is stored here so the user can retrieve
it on re-login without re-generating. This powers the "Resume Download" banner
on the home page when the user is logged out before downloading.

Key constraint: one active GeneratedBook per (user_mobile, profile_id, story_id).
Re-generating the same story for the same profile replaces the existing record.

Azure Table layout:
  Table:         GeneratedBooks
  PartitionKey = user_mobile
  RowKey       = book_id   (uuid hex)

Fields stored — see GeneratedBook data model in SPEC-003.
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

_TABLE_NAME = "GeneratedBooks"
_DATA_DIR   = Path(__file__).parent.parent / "data"


# ─── ABC ─────────────────────────────────────────────────────────────────────

class GeneratedBookStore(ABC):
    @abstractmethod
    def upsert_book(self, user_mobile: str, book: dict) -> dict: ...

    @abstractmethod
    def get_book(self, user_mobile: str, book_id: str) -> Optional[dict]: ...

    @abstractmethod
    def find_book(
        self, user_mobile: str, profile_id: str, story_id: str
    ) -> Optional[dict]: ...

    @abstractmethod
    def list_pending_downloads(self, user_mobile: str) -> list[dict]: ...

    @abstractmethod
    def increment_download_count(self, user_mobile: str, book_id: str) -> bool: ...

    @abstractmethod
    def update_book_status(
        self, user_mobile: str, book_id: str, updates: dict
    ) -> bool: ...


# ─── Azure Table implementation ───────────────────────────────────────────────

class AzureGeneratedBookStore(GeneratedBookStore):

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
                pass
        return self._client

    @staticmethod
    def _entity_to_dict(entity) -> dict:
        return {
            "book_id":              entity.get("RowKey",              entity.get("book_id", "")),
            "user_mobile":          entity.get("PartitionKey",        entity.get("user_mobile", "")),
            "profile_id":           entity.get("profile_id",          ""),
            "story_id":             entity.get("story_id",            ""),
            "generation_id":        entity.get("generation_id",       ""),
            "child_name":           entity.get("child_name",          ""),
            "pdf_blob_path":        entity.get("pdf_blob_path",       "") or "",
            "pdf_filename":         entity.get("pdf_filename",        "") or "",
            "status":               entity.get("status",              "generating"),
            "download_count":       int(entity.get("download_count",  0) or 0),
            "first_downloaded_at":  entity.get("first_downloaded_at", "") or "",
            "created_at":           entity.get("created_at",         ""),
            "completed_at":         entity.get("completed_at",        "") or "",
        }

    def upsert_book(self, user_mobile: str, book: dict) -> dict:
        client = self._get_client()
        pk      = self._safe(user_mobile)
        now     = datetime.now(timezone.utc).isoformat()
        book_id = book.get("book_id") or uuid.uuid4().hex
        entity  = {
            "PartitionKey":         pk,
            "RowKey":               book_id,
            "book_id":              book_id,
            "user_mobile":          user_mobile,
            "profile_id":           book.get("profile_id",          ""),
            "story_id":             book.get("story_id",            ""),
            "generation_id":        book.get("generation_id",       ""),
            "child_name":           book.get("child_name",          ""),
            "pdf_blob_path":        book.get("pdf_blob_path",       "") or "",
            "pdf_filename":         book.get("pdf_filename",        "") or "",
            "status":               book.get("status",              "generating"),
            "download_count":       int(book.get("download_count",  0) or 0),
            "first_downloaded_at":  book.get("first_downloaded_at", "") or "",
            "created_at":           book.get("created_at",          now),
            "completed_at":         book.get("completed_at",        "") or "",
        }
        client.upsert_entity(entity)
        logger.info(
            "AzureGeneratedBookStore: upserted book %s profile=%s story=%s status=%s",
            book_id[:8], book.get("profile_id", "")[:8],
            book.get("story_id", ""), book.get("status", ""),
        )
        return self._entity_to_dict(entity)

    def get_book(self, user_mobile: str, book_id: str) -> Optional[dict]:
        client = self._get_client()
        pk = self._safe(user_mobile)
        try:
            entity = client.get_entity(partition_key=pk, row_key=book_id)
            return self._entity_to_dict(entity)
        except Exception:
            return None

    def find_book(
        self, user_mobile: str, profile_id: str, story_id: str
    ) -> Optional[dict]:
        """Find the most recent book for a (profile, story) pair, or None."""
        client = self._get_client()
        pk     = self._safe(user_mobile)
        flt    = (
            f"PartitionKey eq '{pk}' "
            f"and profile_id eq '{profile_id}' "
            f"and story_id eq '{story_id}'"
        )
        try:
            results = list(client.query_entities(flt))
            if not results:
                return None
            # Sort by created_at descending — take the most recent
            results.sort(key=lambda e: e.get("created_at", ""), reverse=True)
            return self._entity_to_dict(results[0])
        except Exception as exc:
            logger.error("AzureGeneratedBookStore.find_book error: %s", exc)
            return None

    def list_pending_downloads(self, user_mobile: str) -> list[dict]:
        """
        Return completed books that have never been downloaded.
        Used by the home page Resume Banner on login.
        Ordered by completed_at descending (most recent first), max 10.
        """
        client = self._get_client()
        pk     = self._safe(user_mobile)
        flt    = (
            f"PartitionKey eq '{pk}' "
            f"and status eq 'complete' "
            f"and download_count eq 0"
        )
        try:
            results = list(client.query_entities(flt))
            books   = [self._entity_to_dict(e) for e in results]
            books.sort(key=lambda b: b.get("completed_at", ""), reverse=True)
            return books[:10]
        except Exception as exc:
            logger.error("AzureGeneratedBookStore.list_pending_downloads error: %s", exc)
            return []

    def increment_download_count(self, user_mobile: str, book_id: str) -> bool:
        """Increment download_count by 1. Set first_downloaded_at if this is the first."""
        client = self._get_client()
        pk     = self._safe(user_mobile)
        try:
            entity = dict(client.get_entity(partition_key=pk, row_key=book_id))
            count  = int(entity.get("download_count", 0) or 0)
            entity["download_count"] = count + 1
            if count == 0:
                entity["first_downloaded_at"] = datetime.now(timezone.utc).isoformat()
            client.upsert_entity(entity)
            logger.info(
                "AzureGeneratedBookStore: download_count → %d for book %s",
                count + 1, book_id[:8],
            )
            return True
        except Exception as exc:
            logger.error("increment_download_count error %s: %s", book_id[:8], exc)
            return False

    def update_book_status(
        self, user_mobile: str, book_id: str, updates: dict
    ) -> bool:
        client = self._get_client()
        pk     = self._safe(user_mobile)
        try:
            entity = dict(client.get_entity(partition_key=pk, row_key=book_id))
            entity.update(updates)
            client.upsert_entity(entity)
            return True
        except Exception as exc:
            logger.error("update_book_status %s: %s", book_id[:8], exc)
            return False


# ─── JSON fallback for local dev ──────────────────────────────────────────────

class JsonGeneratedBookStore(GeneratedBookStore):
    """Local-dev fallback — backend/data/generated_books.json"""

    def __init__(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _DATA_DIR / "generated_books.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.error("JsonGeneratedBookStore._load: %s", exc)
            return {}

    def _save(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def upsert_book(self, user_mobile: str, book: dict) -> dict:
        data    = self._load()
        now     = datetime.now(timezone.utc).isoformat()
        book_id = book.get("book_id") or uuid.uuid4().hex
        record  = {**book, "book_id": book_id, "user_mobile": user_mobile}
        if "created_at" not in record:
            record["created_at"] = now
        data.setdefault(user_mobile, {})[book_id] = record
        self._save(data)
        return record

    def get_book(self, user_mobile: str, book_id: str) -> Optional[dict]:
        return self._load().get(user_mobile, {}).get(book_id)

    def find_book(
        self, user_mobile: str, profile_id: str, story_id: str
    ) -> Optional[dict]:
        user_books = list(self._load().get(user_mobile, {}).values())
        matches = [
            b for b in user_books
            if b.get("profile_id") == profile_id and b.get("story_id") == story_id
        ]
        if not matches:
            return None
        matches.sort(key=lambda b: b.get("created_at", ""), reverse=True)
        return matches[0]

    def list_pending_downloads(self, user_mobile: str) -> list[dict]:
        user_books = list(self._load().get(user_mobile, {}).values())
        pending = [
            b for b in user_books
            if b.get("status") == "complete" and int(b.get("download_count", 0)) == 0
        ]
        pending.sort(key=lambda b: b.get("completed_at", ""), reverse=True)
        return pending[:10]

    def increment_download_count(self, user_mobile: str, book_id: str) -> bool:
        data = self._load()
        book = data.get(user_mobile, {}).get(book_id)
        if not book:
            return False
        count = int(book.get("download_count", 0))
        book["download_count"] = count + 1
        if count == 0:
            book["first_downloaded_at"] = datetime.now(timezone.utc).isoformat()
        data[user_mobile][book_id] = book
        self._save(data)
        return True

    def update_book_status(
        self, user_mobile: str, book_id: str, updates: dict
    ) -> bool:
        data = self._load()
        book = data.get(user_mobile, {}).get(book_id)
        if not book:
            return False
        book.update(updates)
        data[user_mobile][book_id] = book
        self._save(data)
        return True


# ─── Factory + singleton ──────────────────────────────────────────────────────

def _create_store() -> GeneratedBookStore:
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn and conn.startswith("DefaultEndpointsProtocol"):
        logger.info("GeneratedBookStore → AzureGeneratedBookStore (table: %s)", _TABLE_NAME)
        return AzureGeneratedBookStore(conn)
    logger.warning("GeneratedBookStore → JsonGeneratedBookStore (local dev only)")
    return JsonGeneratedBookStore()


_store = _create_store()


# ─── Public API ───────────────────────────────────────────────────────────────

def upsert_book(user_mobile: str, book: dict) -> dict:
    return _store.upsert_book(user_mobile, book)

def get_book(user_mobile: str, book_id: str) -> Optional[dict]:
    return _store.get_book(user_mobile, book_id)

def find_book(user_mobile: str, profile_id: str, story_id: str) -> Optional[dict]:
    return _store.find_book(user_mobile, profile_id, story_id)

def list_pending_downloads(user_mobile: str) -> list[dict]:
    return _store.list_pending_downloads(user_mobile)

def increment_download_count(user_mobile: str, book_id: str) -> bool:
    return _store.increment_download_count(user_mobile, book_id)

def update_book_status(user_mobile: str, book_id: str, updates: dict) -> bool:
    return _store.update_book_status(user_mobile, book_id, updates)
