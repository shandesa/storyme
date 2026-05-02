"""
core/ai_page_store.py
======================
Persistence for AI-generated book pages (SPEC-004).

AIBackgroundPageStore  Table: AIBackgroundPages  PK=story_id  RK=page_number
  Global cache — generated once per story version+prompt, shared across all users.

AICharacterPageStore   Table: AICharacterPages   PK=generation_id  RK=page_number
  Per-user-generation character pages.
"""
from __future__ import annotations
import json, logging, os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
_BG_TABLE   = "AIBackgroundPages"
_CHAR_TABLE = "AICharacterPages"
_DATA_DIR   = Path(__file__).parent.parent / "data"


class AIBackgroundPageStore(ABC):
    @abstractmethod
    def get(self, story_id: str, page_number: int) -> Optional[dict]: ...
    @abstractmethod
    def save(self, story_id: str, page_number: int, data: dict) -> dict: ...


class AzureAIBackgroundPageStore(AIBackgroundPageStore):
    def __init__(self, conn: str):
        self._conn, self._client = conn, None

    def _get_client(self):
        if self._client is None:
            from azure.data.tables import TableServiceClient
            svc = TableServiceClient.from_connection_string(self._conn)
            self._client = svc.get_table_client(_BG_TABLE)
            try: self._client.create_table()
            except Exception: pass
        return self._client

    @staticmethod
    def _to(e) -> dict:
        return {
            "story_id":      e.get("PartitionKey", e.get("story_id","")),
            "page_number":   int(e.get("page_number",0)),
            "story_version": e.get("story_version",""),
            "blob_path":     e.get("blob_path",""),
            "prompt_hash":   e.get("prompt_hash",""),
            "model":         e.get("model","gpt-image-1"),
            "quality":       e.get("quality","medium"),
            "seed":          int(e.get("seed",0)),
            "text_area":     e.get("text_area","{}"),
            "generated_at":  e.get("generated_at",""),
            "generation_ms": int(e.get("generation_ms",0)),
        }

    def get(self, story_id: str, page_number: int) -> Optional[dict]:
        try:
            return self._to(self._get_client().get_entity(story_id, f"{page_number:02d}"))
        except Exception: return None

    def save(self, story_id: str, page_number: int, data: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        e = {"PartitionKey": story_id, "RowKey": f"{page_number:02d}",
             "story_id": story_id, "page_number": page_number,
             "story_version": data.get("story_version",""),
             "blob_path": data.get("blob_path",""),
             "prompt_hash": data.get("prompt_hash",""),
             "model": data.get("model","gpt-image-1"),
             "quality": data.get("quality","medium"),
             "seed": int(data.get("seed",0)),
             "text_area": json.dumps(data.get("text_area",{})),
             "generated_at": data.get("generated_at",now),
             "generation_ms": int(data.get("generation_ms",0))}
        self._get_client().upsert_entity(e)
        logger.info("AIBackgroundPages: saved %s p%02d", story_id, page_number)
        return self._to(e)


class JsonAIBackgroundPageStore(AIBackgroundPageStore):
    def __init__(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _DATA_DIR / "ai_background_pages.json"

    def _load(self) -> dict:
        try: return json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError: return {}

    def _save(self, d): self._path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def get(self, story_id, page_number):
        return self._load().get(story_id,{}).get(f"{page_number:02d}")

    def save(self, story_id, page_number, data):
        d = self._load(); now = datetime.now(timezone.utc).isoformat()
        r = {**data, "story_id": story_id, "page_number": page_number,
             "generated_at": data.get("generated_at",now)}
        d.setdefault(story_id,{})[f"{page_number:02d}"] = r
        self._save(d); return r


class AICharacterPageStore(ABC):
    @abstractmethod
    def get(self, generation_id: str, page_number: int) -> Optional[dict]: ...
    @abstractmethod
    def save(self, generation_id: str, page_number: int, data: dict) -> dict: ...
    @abstractmethod
    def list_pages(self, generation_id: str) -> list[dict]: ...


class AzureAICharacterPageStore(AICharacterPageStore):
    def __init__(self, conn: str):
        self._conn, self._client = conn, None

    def _get_client(self):
        if self._client is None:
            from azure.data.tables import TableServiceClient
            svc = TableServiceClient.from_connection_string(self._conn)
            self._client = svc.get_table_client(_CHAR_TABLE)
            try: self._client.create_table()
            except Exception: pass
        return self._client

    @staticmethod
    def _to(e) -> dict:
        return {
            "generation_id":   e.get("PartitionKey", e.get("generation_id","")),
            "page_number":     int(e.get("page_number",0)),
            "story_id":        e.get("story_id",""),
            "user_mobile":     e.get("user_mobile",""),
            "blob_path_raw":   e.get("blob_path_raw",""),
            "blob_path_final": e.get("blob_path_final",""),
            "face_bbox":       e.get("face_bbox","{}"),
            "text_area":       e.get("text_area","{}"),
            "is_anchor":       bool(e.get("is_anchor",False)),
            "is_placeholder":  bool(e.get("is_placeholder",False)),
            "seed":            int(e.get("seed",0)),
            "model":           e.get("model","gpt-image-1"),
            "quality":         e.get("quality","medium"),
            "generated_at":    e.get("generated_at",""),
            "generation_ms":   int(e.get("generation_ms",0)),
        }

    def get(self, generation_id, page_number):
        try:
            return self._to(self._get_client().get_entity(generation_id, f"{page_number:02d}"))
        except Exception: return None

    def save(self, generation_id, page_number, data):
        now = datetime.now(timezone.utc).isoformat()
        e = {"PartitionKey": generation_id, "RowKey": f"{page_number:02d}",
             "generation_id": generation_id, "page_number": page_number,
             "story_id": data.get("story_id",""), "user_mobile": data.get("user_mobile",""),
             "blob_path_raw": data.get("blob_path_raw",""),
             "blob_path_final": data.get("blob_path_final",""),
             "face_bbox": json.dumps(data.get("face_bbox",{})),
             "text_area": json.dumps(data.get("text_area",{})),
             "is_anchor": bool(data.get("is_anchor",False)),
             "is_placeholder": bool(data.get("is_placeholder",False)),
             "seed": int(data.get("seed",0)), "model": data.get("model","gpt-image-1"),
             "quality": data.get("quality","medium"),
             "generated_at": data.get("generated_at",now),
             "generation_ms": int(data.get("generation_ms",0))}
        self._get_client().upsert_entity(e)
        logger.info("AICharacterPages: saved gen %s p%02d", generation_id[:8], page_number)
        return self._to(e)

    def list_pages(self, generation_id):
        try:
            pages = [self._to(e) for e in self._get_client().query_entities(f"PartitionKey eq '{generation_id}'")]
            return sorted(pages, key=lambda p: p["page_number"])
        except Exception as exc:
            logger.error("list_pages %s: %s", generation_id[:8], exc); return []


class JsonAICharacterPageStore(AICharacterPageStore):
    def __init__(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _DATA_DIR / "ai_character_pages.json"

    def _load(self):
        try: return json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError: return {}

    def _save(self, d): self._path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def get(self, generation_id, page_number):
        return self._load().get(generation_id,{}).get(f"{page_number:02d}")

    def save(self, generation_id, page_number, data):
        d = self._load(); now = datetime.now(timezone.utc).isoformat()
        r = {**data, "generation_id": generation_id, "page_number": page_number,
             "generated_at": data.get("generated_at",now)}
        d.setdefault(generation_id,{})[f"{page_number:02d}"] = r
        self._save(d); return r

    def list_pages(self, generation_id):
        pages = list(self._load().get(generation_id,{}).values())
        return sorted(pages, key=lambda p: p.get("page_number",0))


def _make(klass_azure, klass_json, *args):
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING","")
    if conn and conn.startswith("DefaultEndpointsProtocol"):
        return klass_azure(conn)
    return klass_json()

_bg_store   = _make(AzureAIBackgroundPageStore, JsonAIBackgroundPageStore)
_char_store = _make(AzureAICharacterPageStore,  JsonAICharacterPageStore)

def get_background_page(story_id: str, page_number: int) -> Optional[dict]:
    return _bg_store.get(story_id, page_number)

def save_background_page(story_id: str, page_number: int, data: dict) -> dict:
    return _bg_store.save(story_id, page_number, data)

def get_character_page(generation_id: str, page_number: int) -> Optional[dict]:
    return _char_store.get(generation_id, page_number)

def save_character_page(generation_id: str, page_number: int, data: dict) -> dict:
    return _char_store.save(generation_id, page_number, data)

def list_character_pages(generation_id: str) -> list[dict]:
    return _char_store.list_pages(generation_id)
