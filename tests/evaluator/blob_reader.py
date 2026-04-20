"""
tests/evaluator/blob_reader.py
================================
Discovers all generated page images for the quality evaluator.

Two discovery strategies (tried in order):
  1. SessionStore (preferred) — reads GenerationSession records from
     AzureTableSessionStore, MongoSessionStore, or NullSessionStore
     depending on what is configured. Fast, structured, filterable.

  2. Blob-scan fallback — lists blobs under generated/ prefix and infers
     scene from path pattern when no session store is configured or reachable.
     Slower but always works as long as images are in blob storage.

Storage backend is chosen automatically by `core.session_store.create_session_store()`
based on available environment variables — no code change needed.
"""

from __future__ import annotations
import asyncio
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional

# Allow running from repo root
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger(__name__)


@dataclass
class GeneratedImageRecord:
    """Metadata for one generated page image in Azure Blob."""
    generation_id:   str
    child_name:      str
    story_id:        str
    gender:          str
    generation_mode: str
    scene_file:      str      # e.g. "scene_03.png"
    page_number:     int
    blob_path:       str      # e.g. "generated/{id}/pages/page_03.png"


class BlobReader:
    """
    Discovers generated images and downloads them for evaluation.

    Initialise from environment variables:
        reader = BlobReader.from_env()

    Or pass credentials explicitly:
        reader = BlobReader(connection_string, container_name)
    """

    def __init__(self, connection_string: str, container_name: str):
        self._conn_str  = connection_string
        self._container = container_name
        self._container_client = None

    @classmethod
    def from_env(cls) -> "BlobReader":
        conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        ctr  = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "storyme-assets")
        if not conn:
            raise EnvironmentError(
                "AZURE_STORAGE_CONNECTION_STRING not set. "
                "Export it before running the evaluator."
            )
        return cls(conn, ctr)

    def _get_container(self):
        if self._container_client is None:
            from azure.storage.blob import BlobServiceClient
            svc = BlobServiceClient.from_connection_string(self._conn_str)
            self._container_client = svc.get_container_client(self._container)
        return self._container_client

    # ─── Discovery ────────────────────────────────────────────────────────────

    def list_generated_images(
        self,
        story_id:   Optional[str] = None,
        child_name: Optional[str] = None,
        gender:     Optional[str] = None,
        limit:      int = 1000,
    ) -> list[GeneratedImageRecord]:
        """
        Return GeneratedImageRecord objects matching the given filters.

        Tries SessionStore (Azure Table / MongoDB) first for structured,
        fast lookup. Falls back to blob-scan if unavailable.

        Args:
            story_id:   Filter by story e.g. "forest_of_smiles"
            child_name: Filter by child name e.g. "Niku"
            gender:     Filter by gender variant e.g. "neutral"
            limit:      Max records to return

        Returns:
            List of GeneratedImageRecord, newest-first.
        """
        try:
            records = self._discover_via_session_store(story_id, child_name, gender, limit)
            if records:
                return records
            logger.info(
                "SessionStore returned 0 records "
                "(no storybooks generated yet, or NullSessionStore) "
                "— falling back to blob scan"
            )
        except Exception as e:
            logger.warning(
                "SessionStore discovery failed (%s) — falling back to blob scan", e
            )
        return self._discover_via_blob_scan(story_id, child_name, limit)

    def _discover_via_session_store(
        self,
        story_id:   Optional[str],
        child_name: Optional[str],
        gender:     Optional[str],
        limit:      int,
    ) -> list[GeneratedImageRecord]:
        """
        Use the SessionStore abstraction to discover GenerationSession records.
        Works with AzureTableSessionStore, MongoSessionStore, or NullSessionStore.
        """
        from backend.core.session_store import create_session_store
        from backend.services.story_service import SCENE_FILES

        store    = create_session_store()
        # list_sessions is async — run synchronously from this non-async context
        sessions = asyncio.run(
            store.list_sessions(
                child_name=child_name,
                story_id=story_id,
                gender=gender,
                limit=limit,
            )
        )
        logger.info(
            "SessionStore (%s): found %d sessions",
            type(store).__name__, len(sessions),
        )

        records: list[GeneratedImageRecord] = []
        for s in sessions:
            for page_result in s.get("page_results", []):
                blob_path = page_result.get("blob_path")
                if not blob_path:
                    continue
                pn = page_result.get("page_number", 1)
                sf = (
                    SCENE_FILES[pn - 1]
                    if 1 <= pn <= len(SCENE_FILES)
                    else f"scene_{pn:02d}.png"
                )
                records.append(GeneratedImageRecord(
                    generation_id=s.get("generation_id", ""),
                    child_name=s.get("child_name", "unknown"),
                    story_id=s.get("story_id", "unknown"),
                    gender=s.get("gender", "neutral"),
                    generation_mode=s.get("generation_mode", "opencv"),
                    scene_file=sf,
                    page_number=pn,
                    blob_path=blob_path,
                ))
        return records

    def _discover_via_blob_scan(
        self,
        story_id:   Optional[str],
        child_name: Optional[str],
        limit:      int,
    ) -> list[GeneratedImageRecord]:
        """
        Fallback: list blobs under generated/ prefix and infer metadata from path.

        Path pattern: generated/{generation_id}/pages/page_{NN}.png
        Metadata (child_name, story_id etc.) cannot be inferred from path alone
        — these fields are set to "unknown" in fallback mode.
        """
        from backend.services.story_service import SCENE_FILES

        ctr     = self._get_container()
        blobs   = ctr.list_blobs(name_starts_with="generated/")
        PAT     = re.compile(r"generated/([a-f0-9]+)/pages/page_(\d+)\.png")
        records: list[GeneratedImageRecord] = []

        for blob in blobs:
            m = PAT.match(blob.name)
            if not m:
                continue
            gen_id = m.group(1)
            pn     = int(m.group(2))
            sf     = (
                SCENE_FILES[pn - 1]
                if 1 <= pn <= len(SCENE_FILES)
                else f"scene_{pn:02d}.png"
            )
            records.append(GeneratedImageRecord(
                generation_id=gen_id,
                child_name=child_name or "unknown",
                story_id=story_id    or "unknown",
                gender="neutral",
                generation_mode="opencv",
                scene_file=sf,
                page_number=pn,
                blob_path=blob.name,
            ))
            if len(records) >= limit:
                break

        logger.info("Blob scan: found %d page images", len(records))
        return records

    # ─── Download / cleanup ───────────────────────────────────────────────────

    def download_to_temp(self, blob_path: str) -> str:
        """
        Download a blob to a local temp file and return its absolute path.
        Caller must call cleanup(path) when done to avoid temp file accumulation.
        """
        ctr    = self._get_container()
        blob   = ctr.get_blob_client(blob_path)
        data   = blob.download_blob().readall()
        suffix = ".png" if blob_path.endswith(".png") else ".jpg"
        tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(data)
        tmp.close()
        return tmp.name

    def cleanup(self, local_path: str) -> None:
        """Delete a temp file created by download_to_temp."""
        try:
            os.unlink(local_path)
        except Exception:
            pass
