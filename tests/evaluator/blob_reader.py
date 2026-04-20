"""
tests/evaluator/blob_reader.py
================================
Discovers all generated page images from Azure Blob Storage.

Two discovery strategies:
  1. MongoDB-first (preferred): query generation_sessions collection
     to get all blob paths, then download each image.
  2. Blob-scan fallback: list blobs under generated/ prefix and infer
     scene from filename pattern when MongoDB is unavailable.

Usage:
    reader  = BlobReader.from_env()
    records = reader.list_generated_images()   # → List[GeneratedImageRecord]
    for r in records:
        local_path = reader.download_to_temp(r.blob_path)
        # ... evaluate ...
        reader.cleanup(local_path)
"""

from __future__ import annotations
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GeneratedImageRecord:
    """Metadata for one generated page image in Azure Blob."""
    generation_id:  str
    child_name:     str
    story_id:       str
    gender:         str
    generation_mode: str
    scene_file:     str         # e.g. "scene_03.png"
    page_number:    int
    blob_path:      str         # e.g. "generated/{id}/pages/page_03.png"


class BlobReader:
    """
    Reads generated images from Azure Blob Storage.

    Initialise with a connection string and container name, or use
    BlobReader.from_env() to read from environment variables.
    """

    def __init__(self, connection_string: str, container_name: str, mongo_url: str = ""):
        self._conn_str  = connection_string
        self._container = container_name
        self._mongo_url = mongo_url
        self._client    = None
        self._container_client = None

    @classmethod
    def from_env(cls) -> "BlobReader":
        conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        ctr  = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "storyme-assets")
        murl = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        if not conn:
            raise EnvironmentError(
                "AZURE_STORAGE_CONNECTION_STRING not set. "
                "Export it before running the evaluator."
            )
        return cls(conn, ctr, murl)

    def _get_container(self):
        if self._container_client is None:
            from azure.storage.blob import BlobServiceClient
            svc = BlobServiceClient.from_connection_string(self._conn_str)
            self._container_client = svc.get_container_client(self._container)
        return self._container_client

    # ─── Discovery ────────────────────────────────────────────────────────────

    def list_generated_images(
        self,
        story_id:     Optional[str] = None,
        child_name:   Optional[str] = None,
        gender:       Optional[str] = None,
        limit:        int = 1000,
    ) -> list[GeneratedImageRecord]:
        """
        Return all GeneratedImageRecord objects matching the filters.

        Tries MongoDB first (structured, fast).
        Falls back to blob-scan if MongoDB is unavailable.

        Args:
            story_id:   Filter by story (e.g. "forest_of_smiles")
            child_name: Filter by child name
            gender:     Filter by gender variant
            limit:      Maximum records to return

        Returns:
            List of GeneratedImageRecord, ordered by generation_id.
        """
        try:
            return self._discover_via_mongodb(story_id, child_name, gender, limit)
        except Exception as e:
            logger.warning("MongoDB discovery failed (%s) — falling back to blob scan", e)
            return self._discover_via_blob_scan(story_id, child_name, limit)

    def _discover_via_mongodb(
        self,
        story_id:   Optional[str],
        child_name: Optional[str],
        gender:     Optional[str],
        limit:      int,
    ) -> list[GeneratedImageRecord]:
        """Query generation_sessions MongoDB collection."""
        import pymongo
        from backend.services.story_service import SCENE_FILES

        client = pymongo.MongoClient(self._mongo_url, serverSelectionTimeoutMS=5000)
        db     = client.get_default_database()

        query: dict = {"status": "complete"}
        if story_id:
            query["story_id"]   = story_id
        if child_name:
            query["child_name"] = child_name
        if gender:
            query["gender"]     = gender

        sessions = list(
            db.generation_sessions.find(query).sort("completed_at", -1).limit(limit)
        )
        logger.info("MongoDB: found %d sessions matching query", len(sessions))

        records: list[GeneratedImageRecord] = []
        for s in sessions:
            for page_result in s.get("page_results", []):
                blob_path = page_result.get("blob_path")
                if not blob_path:
                    continue
                pn = page_result.get("page_number", 1)
                sf = SCENE_FILES[pn - 1] if 1 <= pn <= len(SCENE_FILES) else f"scene_{pn:02d}.png"
                records.append(GeneratedImageRecord(
                    generation_id=s["generation_id"],
                    child_name=s.get("child_name", "unknown"),
                    story_id=s.get("story_id", "unknown"),
                    gender=s.get("gender", "neutral"),
                    generation_mode=s.get("generation_mode", "opencv"),
                    scene_file=sf,
                    page_number=pn,
                    blob_path=blob_path,
                ))

        client.close()
        return records

    def _discover_via_blob_scan(
        self,
        story_id:   Optional[str],
        child_name: Optional[str],
        limit:      int,
    ) -> list[GeneratedImageRecord]:
        """
        Fallback: list blobs under generated/ and infer metadata from path.

        Path pattern: generated/{generation_id}/pages/page_{NN}.png
        """
        from backend.services.story_service import SCENE_FILES

        ctr     = self._get_container()
        prefix  = "generated/"
        blobs   = ctr.list_blobs(name_starts_with=prefix)

        # Pattern: generated/{id}/pages/page_NN.png
        PAT = re.compile(r"generated/([a-f0-9]+)/pages/page_(\d+)\.png")
        records: list[GeneratedImageRecord] = []

        for blob in blobs:
            m = PAT.match(blob.name)
            if not m:
                continue
            gen_id = m.group(1)
            pn     = int(m.group(2))
            sf     = SCENE_FILES[pn - 1] if 1 <= pn <= len(SCENE_FILES) else f"scene_{pn:02d}.png"
            records.append(GeneratedImageRecord(
                generation_id=gen_id,
                child_name=child_name or "unknown",
                story_id=story_id   or "unknown",
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
        Download a blob to a local temp file and return its path.
        Caller must call cleanup(path) when done.
        """
        ctr   = self._get_container()
        blob  = ctr.get_blob_client(blob_path)
        data  = blob.download_blob().readall()

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
