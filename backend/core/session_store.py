"""
backend/core/session_store.py
==============================
Abstract session store interface + factory.

Decouples application code from any specific session storage backend.
The rest of the application only calls:
    session_store.write_session(session)
    session_store.list_sessions(child_name=..., story_id=...)
    session_store.read_session(generation_id)

Backend is chosen automatically at startup based on available configuration:

    AZURE_STORAGE_CONNECTION_STRING set  →  AzureTableSessionStore  (default on Azure)
    MONGO_URL set and reachable          →  MongoSessionStore        (explicit opt-in)
    Neither                              →  NullSessionStore         (no-op, local dev)

Nothing in routes/, services/, or tests/ imports a concrete store class.
They import `session_store` (the singleton) from this module only.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Abstract interface ───────────────────────────────────────────────────────

class SessionStore(ABC):
    """
    Storage backend for GenerationSession records.

    All methods are async to accommodate both network-IO backends
    (Azure Table, MongoDB) and sync-wrapped local backends.
    """

    @abstractmethod
    async def write_session(self, session_dict: dict) -> None:
        """
        Write (upsert) a GenerationSession document.
        Must be idempotent — calling twice with the same generation_id
        must not create duplicate records.
        """

    @abstractmethod
    async def read_session(self, generation_id: str) -> Optional[dict]:
        """
        Return the session document for a generation_id, or None if not found.
        """

    @abstractmethod
    async def list_sessions(
        self,
        child_name: Optional[str] = None,
        story_id: Optional[str] = None,
        gender: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """
        Return session documents matching the given filters.
        All filters are optional — omitting all returns everything up to limit.
        """


# ─── Azure Table Storage implementation ──────────────────────────────────────

class AzureTableSessionStore(SessionStore):
    """
    Stores GenerationSession records in Azure Table Storage.

    Uses the same AZURE_STORAGE_CONNECTION_STRING already configured for
    blob storage — no separate subscription or credential needed.

    Table design:
        Table name:   GenerationSessions
        PartitionKey: sanitised child_name  (enables fast "all books for Niku" queries)
        RowKey:       completed_at_gen_id   (ISO ts + gen_id → unique + sorted newest-last)

    The SDK creates the table automatically on first write.
    """

    TABLE_NAME = "GenerationSessions"

    def __init__(self, connection_string: str):
        self._conn_str = connection_string
        self._client   = None   # lazy init — avoid import errors if pkg missing

    def _get_client(self):
        if self._client is None:
            from azure.data.tables import TableServiceClient
            svc = TableServiceClient.from_connection_string(self._conn_str)
            # create_table_if_not_exists is idempotent
            self._client = svc.get_table_client(self.TABLE_NAME)
            try:
                self._client.create_table()
                logger.info("Azure Table '%s' created", self.TABLE_NAME)
            except Exception:
                pass   # table already exists — expected on all but first run
        return self._client

    @staticmethod
    def _safe(name: str, max_len: int = 64) -> str:
        """Sanitise a value for use as a PartitionKey / RowKey."""
        import re
        cleaned = re.sub(r"[^\w]", "_", str(name).strip().lower())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned[:max_len] or "unknown"

    @staticmethod
    def _make_row_key(session_dict: dict) -> str:
        """
        RowKey = completed_at + "_" + gen_id[:8]
        Lexicographic order = chronological order (ISO timestamps sort correctly).
        Example: "20260420_162530_a1b2c3d4"
        """
        ts  = (session_dict.get("completed_at") or "2000-01-01T00:00:00+00:00")[:19]
        ts  = ts.replace("-", "").replace("T", "_").replace(":", "")
        uid = session_dict.get("generation_id", "unknown")[:8]
        return f"{ts}_{uid}"

    async def write_session(self, session_dict: dict) -> None:
        """Upsert a GenerationSession as an Azure Table entity."""
        client  = self._get_client()
        pk      = self._safe(session_dict.get("child_name", "unknown"))
        rk      = self._make_row_key(session_dict)

        # Azure Table entities are flat key-value — serialise nested objects to JSON
        entity = {
            "PartitionKey":     pk,
            "RowKey":           rk,
            "generation_id":    session_dict.get("generation_id", ""),
            "child_name":       session_dict.get("child_name", ""),
            "story_id":         session_dict.get("story_id", ""),
            "gender":           str(session_dict.get("gender", "neutral")),
            "generation_mode":  str(session_dict.get("generation_mode", "opencv")),
            "status":           str(session_dict.get("status", "complete")),
            "pdf_blob_path":    session_dict.get("pdf_blob_path") or "",
            "pdf_filename":     session_dict.get("pdf_filename") or "",
            "pages_succeeded":  int(session_dict.get("pages_succeeded", 0)),
            "pages_failed":     int(session_dict.get("pages_failed", 0)),
            "total_pages":      int(session_dict.get("total_pages", 0)),
            "completed_at":     session_dict.get("completed_at") or "",
            # Serialise page_results list as JSON string — flat table can't nest
            "page_results_json": json.dumps(session_dict.get("page_results", [])),
        }

        # upsert_entity is idempotent — safe to call multiple times
        client.upsert_entity(entity=entity)
        logger.info(
            "AzureTable: session %s written (pk=%s rk=%s)",
            session_dict.get("generation_id", "?")[:8], pk, rk,
        )

    async def read_session(self, generation_id: str) -> Optional[dict]:
        """Scan for a session by generation_id (RowKey prefix scan)."""
        client = self._get_client()
        try:
            # Filter by generation_id property (not key — requires query)
            results = list(client.query_entities(
                f"generation_id eq '{generation_id}'",
                select=["generation_id", "child_name", "story_id", "gender",
                        "generation_mode", "status", "pdf_blob_path",
                        "pages_succeeded", "pages_failed", "total_pages",
                        "completed_at", "page_results_json"],
            ))
            if results:
                return self._entity_to_dict(results[0])
        except Exception as e:
            logger.warning("AzureTable read_session failed: %s", e)
        return None

    async def list_sessions(
        self,
        child_name: Optional[str] = None,
        story_id:   Optional[str] = None,
        gender:     Optional[str] = None,
        limit:      int = 1000,
    ) -> list[dict]:
        """
        List sessions matching optional filters.

        PartitionKey filter (child_name) uses the index — fast.
        story_id / gender filters are applied client-side — acceptable at this scale
        (< 10K rows for 300 stories × reasonable generations).
        """
        client     = self._get_client()
        filter_str = ""

        if child_name:
            pk = self._safe(child_name)
            filter_str = f"PartitionKey eq '{pk}'"

        try:
            entities = client.query_entities(
                filter_str or "PartitionKey ne ''",
                results_per_page=min(limit, 1000),
            )
            rows: list[dict] = []
            for entity in entities:
                d = self._entity_to_dict(entity)
                # Client-side filters
                if story_id and d.get("story_id") != story_id:
                    continue
                if gender and d.get("gender") != gender:
                    continue
                rows.append(d)
                if len(rows) >= limit:
                    break
            return rows
        except Exception as e:
            logger.warning("AzureTable list_sessions failed: %s", e)
            return []

    @staticmethod
    def _entity_to_dict(entity) -> dict:
        """Convert a flat Azure Table entity back to a GenerationSession-shaped dict."""
        page_results = []
        try:
            page_results = json.loads(entity.get("page_results_json", "[]"))
        except Exception:
            pass
        return {
            "generation_id":   entity.get("generation_id", ""),
            "child_name":      entity.get("child_name", ""),
            "story_id":        entity.get("story_id", ""),
            "gender":          entity.get("gender", "neutral"),
            "generation_mode": entity.get("generation_mode", "opencv"),
            "status":          entity.get("status", "complete"),
            "pdf_blob_path":   entity.get("pdf_blob_path", ""),
            "pdf_filename":    entity.get("pdf_filename", ""),
            "pages_succeeded": int(entity.get("pages_succeeded", 0)),
            "pages_failed":    int(entity.get("pages_failed", 0)),
            "total_pages":     int(entity.get("total_pages", 0)),
            "completed_at":    entity.get("completed_at", ""),
            "page_results":    page_results,
        }


# ─── MongoDB implementation ───────────────────────────────────────────────────

class MongoSessionStore(SessionStore):
    """
    Stores GenerationSession records in MongoDB.
    Requires MONGO_URL environment variable and motor package.
    Used automatically if MONGO_URL is set and Azure Table is not configured.
    Kept as a fully working alternative — not deprecated.
    """

    def __init__(self, mongo_url: str, db_name: str = "storyme_db"):
        self._url     = mongo_url
        self._db_name = db_name
        self._db      = None

    def _get_db(self):
        if self._db is None:
            from motor.motor_asyncio import AsyncIOMotorClient
            client    = AsyncIOMotorClient(self._url)
            self._db  = client[self._db_name]
        return self._db

    async def write_session(self, session_dict: dict) -> None:
        db = self._get_db()
        await db.generation_sessions.replace_one(
            {"generation_id": session_dict["generation_id"]},
            session_dict,
            upsert=True,
        )
        logger.info("MongoDB: session %s written", session_dict.get("generation_id", "?")[:8])

    async def read_session(self, generation_id: str) -> Optional[dict]:
        db  = self._get_db()
        doc = await db.generation_sessions.find_one({"generation_id": generation_id})
        if doc:
            doc.pop("_id", None)
        return doc

    async def list_sessions(
        self,
        child_name: Optional[str] = None,
        story_id:   Optional[str] = None,
        gender:     Optional[str] = None,
        limit:      int = 1000,
    ) -> list[dict]:
        db    = self._get_db()
        query = {"status": "complete"}
        if child_name:
            query["child_name"] = child_name
        if story_id:
            query["story_id"] = story_id
        if gender:
            query["gender"] = gender
        docs = await db.generation_sessions.find(query, {"_id": 0}).sort(
            "completed_at", -1
        ).to_list(limit)
        return docs


# ─── Null (no-op) implementation ──────────────────────────────────────────────

class NullSessionStore(SessionStore):
    """
    No-op session store. Used when neither Azure Table nor MongoDB is configured.
    Writes are silently discarded. Reads return None / empty list.
    The evaluator falls back to blob-scan discovery mode automatically.
    """

    async def write_session(self, session_dict: dict) -> None:
        logger.debug(
            "NullSessionStore: session %s discarded "
            "(no Azure Table or MongoDB configured)",
            session_dict.get("generation_id", "?")[:8],
        )

    async def read_session(self, generation_id: str) -> Optional[dict]:
        return None

    async def list_sessions(self, **_kwargs) -> list[dict]:
        return []


# ─── Factory ──────────────────────────────────────────────────────────────────

def create_session_store() -> SessionStore:
    """
    Return the appropriate SessionStore based on available configuration.

    Priority:
      1. AzureTableSessionStore  — if AZURE_STORAGE_CONNECTION_STRING is set
                                   (default on Azure App Service)
      2. MongoSessionStore       — if MONGO_URL is set (explicit opt-in)
      3. NullSessionStore        — local dev fallback (no crash)
    """
    azure_conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    mongo_url  = os.environ.get("MONGO_URL", "")

    if azure_conn and azure_conn.startswith("DefaultEndpointsProtocol"):
        logger.info("SessionStore: AzureTableSessionStore (table: GenerationSessions)")
        return AzureTableSessionStore(azure_conn)

    if mongo_url and "localhost" not in mongo_url and mongo_url != "":
        logger.info("SessionStore: MongoSessionStore (url: %s...)", mongo_url[:30])
        return MongoSessionStore(mongo_url)

    logger.warning(
        "SessionStore: NullSessionStore — no Azure Table or MongoDB configured. "
        "GenerationSession records will not be persisted. "
        "The quality evaluator will use blob-scan discovery mode."
    )
    return NullSessionStore()


# Module-level singleton — imported by server.py, generate.py, blob_reader.py
session_store: SessionStore = create_session_store()
