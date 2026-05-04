"""
core/session_store.py
=====================
Abstract session store + concrete implementations for Azure Table, MongoDB, Null.

Three record types — each in its own Azure Table:
  GenerationSessions  PK=child_name_safe    RK=ts_genid
  CartItems           PK=user_mobile_safe   RK=cart_item_id
  Orders              PK=user_mobile_safe   RK=ts_orderid

Backend selected at startup:
  1. AzureTableSessionStore  (AZURE_STORAGE_CONNECTION_STRING set — default on Azure)
  2. MongoSessionStore        (MONGO_URL set to non-localhost)
  3. NullSessionStore         (local dev fallback)
"""

from __future__ import annotations
import json, logging, os, uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── ABC ─────────────────────────────────────────────────────────────────────

class SessionStore(ABC):

    # Generation sessions
    @abstractmethod
    async def write_session(self, session_dict: dict) -> None: ...
    @abstractmethod
    async def read_session(self, generation_id: str) -> Optional[dict]: ...
    @abstractmethod
    async def list_sessions(self, child_name=None, story_id=None, gender=None, limit=1000) -> list[dict]: ...

    # Cart items
    @abstractmethod
    async def write_cart_item(self, item_dict: dict) -> None: ...
    @abstractmethod
    async def read_cart_items(self, user_mobile: str, status: Optional[str] = None) -> list[dict]: ...
    @abstractmethod
    async def delete_cart_item(self, user_mobile: str, cart_item_id: str) -> None: ...

    # Session update (for async generation status)
    @abstractmethod
    async def update_session(self, generation_id: str, updates: dict) -> bool: ...

    # Orders
    @abstractmethod
    async def write_order(self, order_dict: dict) -> None: ...
    @abstractmethod
    async def read_order(self, order_id: str) -> Optional[dict]: ...
    @abstractmethod
    async def list_orders(self, user_mobile=None, status=None, limit=100) -> list[dict]: ...


# ─── Azure Table ──────────────────────────────────────────────────────────────

class AzureTableSessionStore(SessionStore):
    _SESSION_TABLE = "GenerationSessions"
    _CART_TABLE    = "CartItems"
    _ORDER_TABLE   = "Orders"

    def __init__(self, conn: str):
        self._conn = conn
        self._clients: dict[str, object] = {}

    def _client(self, table: str):
        if table not in self._clients:
            from azure.data.tables import TableServiceClient
            svc = TableServiceClient.from_connection_string(self._conn)
            c   = svc.get_table_client(table)
            try:
                c.create_table()
                logger.info("Azure Table '%s' created", table)
            except Exception:
                pass
            self._clients[table] = c
        return self._clients[table]

    @staticmethod
    def _safe(s: str, n: int = 64) -> str:
        import re
        c = re.sub(r"[^\w]", "_", str(s).strip().lower())
        c = re.sub(r"_+", "_", c).strip("_")
        return c[:n] or "unknown"

    # ── Sessions ──────────────────────────────────────────────────────────────

    async def write_session(self, d: dict) -> None:
        c   = self._client(self._SESSION_TABLE)
        pk  = self._safe(d.get("child_name", "unknown"))
        ts  = (d.get("completed_at") or datetime.now(timezone.utc).isoformat())[:19]
        ts  = ts.replace("-","").replace("T","_").replace(":","")
        rk  = f"{ts}_{d.get('generation_id','')[:8]}"
        c.upsert_entity({
            "PartitionKey":      pk, "RowKey": rk,
            "generation_id":     d.get("generation_id",""),
            "child_name":        d.get("child_name",""),
            "story_id":          d.get("story_id",""),
            "gender":            str(d.get("gender","neutral")),
            "generation_mode":   str(d.get("generation_mode","opencv")),
            "status":            str(d.get("status","complete")),
            "pdf_blob_path":     d.get("pdf_blob_path") or "",
            "pdf_filename":      d.get("pdf_filename") or "",
            "pages_succeeded":   int(d.get("pages_succeeded",0)),
            "pages_failed":      int(d.get("pages_failed",0)),
            "total_pages":       int(d.get("total_pages",0)),
            "completed_at":      d.get("completed_at",""),
            "page_results_json": json.dumps(d.get("page_results",[])),
        })
        logger.info("AzureTable: session %s written", d.get("generation_id","?")[:8])

    async def read_session(self, generation_id: str) -> Optional[dict]:
        c = self._client(self._SESSION_TABLE)
        try:
            r = list(c.query_entities(f"generation_id eq '{generation_id}'"))
            return self._ses_dict(r[0]) if r else None
        except Exception as e:
            logger.warning("read_session: %s", e)
            return None

    async def list_sessions(self, child_name=None, story_id=None, gender=None, limit=1000):
        c   = self._client(self._SESSION_TABLE)
        flt = f"PartitionKey eq '{self._safe(child_name)}'" if child_name else "PartitionKey ne ''"
        try:
            rows = []
            for e in c.query_entities(flt, results_per_page=min(limit,1000)):
                d = self._ses_dict(e)
                if story_id and d.get("story_id") != story_id: continue
                if gender   and d.get("gender")   != gender:   continue
                rows.append(d)
                if len(rows) >= limit: break
            return rows
        except Exception as e:
            logger.warning("list_sessions: %s", e); return []

    @staticmethod
    def _ses_dict(e) -> dict:
        try: pr = json.loads(e.get("page_results_json","[]"))
        except: pr = []
        return {"generation_id":e.get("generation_id",""),"child_name":e.get("child_name",""),
                "story_id":e.get("story_id",""),"gender":e.get("gender","neutral"),
                "generation_mode":e.get("generation_mode","opencv"),"status":e.get("status","complete"),
                "pdf_blob_path":e.get("pdf_blob_path",""),"pdf_filename":e.get("pdf_filename",""),
                "pages_succeeded":int(e.get("pages_succeeded",0)),"pages_failed":int(e.get("pages_failed",0)),
                "total_pages":int(e.get("total_pages",0)),"completed_at":e.get("completed_at",""),
                "page_results":pr}

    async def update_session(self, generation_id: str, updates: dict) -> bool:
        """Merge updates into an existing GenerationSession row (same PK/RK)."""
        c = self._client(self._SESSION_TABLE)
        try:
            rows = list(c.query_entities(f"generation_id eq '{generation_id}'"))
            if not rows:
                logger.warning("update_session: generation_id %s not found", generation_id[:8])
                return False
            entity = dict(rows[0])   # includes PartitionKey, RowKey from table
            entity.update(updates)   # merge in the caller's changes
            c.upsert_entity(entity)  # write back — same PK/RK so it replaces in-place
            logger.info("AzureTable: session %s updated %s", generation_id[:8], list(updates.keys()))
            return True
        except Exception as e:
            logger.warning("update_session %s: %s", generation_id[:8], e)
            return False

    # ── Cart ──────────────────────────────────────────────────────────────────

    async def write_cart_item(self, d: dict) -> None:
        c  = self._client(self._CART_TABLE)
        pk = self._safe(d.get("user_mobile","anonymous"))
        rk = d.get("cart_item_id", uuid.uuid4().hex)
        c.upsert_entity({
            "PartitionKey":     pk, "RowKey": rk,
            "cart_item_id":     rk,
            "user_mobile":      d.get("user_mobile",""),
            "generation_id":    d.get("generation_id",""),
            "product_id":       d.get("product_id",""),
            "child_name":       d.get("child_name",""),
            "story_id":         d.get("story_id",""),
            "pdf_blob_path":    d.get("pdf_blob_path",""),
            "quantity":         int(d.get("quantity",1)),
            "unit_price_paise": int(d.get("unit_price_paise",0)),
            "status":           d.get("status","pending_order"),
            "created_at":       d.get("created_at",datetime.now(timezone.utc).isoformat()),
            "order_id":         d.get("order_id",""),
        })
        logger.info("AzureTable: cart_item %s written", rk[:8])

    async def read_cart_items(self, user_mobile: str, status=None) -> list[dict]:
        c  = self._client(self._CART_TABLE)
        pk = self._safe(user_mobile)
        flt = f"PartitionKey eq '{pk}'"
        if status: flt += f" and status eq '{status}'"
        try:
            return [self._cart_dict(e) for e in c.query_entities(flt)]
        except Exception as e:
            logger.warning("read_cart_items: %s", e); return []

    async def delete_cart_item(self, user_mobile: str, cart_item_id: str) -> None:
        c = self._client(self._CART_TABLE)
        try: c.delete_entity(partition_key=self._safe(user_mobile), row_key=cart_item_id)
        except Exception as e: logger.warning("delete_cart_item: %s", e)

    @staticmethod
    def _cart_dict(e) -> dict:
        return {"cart_item_id":e.get("cart_item_id",e.get("RowKey","")),"user_mobile":e.get("user_mobile",""),
                "generation_id":e.get("generation_id",""),"product_id":e.get("product_id",""),
                "child_name":e.get("child_name",""),"story_id":e.get("story_id",""),
                "pdf_blob_path":e.get("pdf_blob_path",""),"quantity":int(e.get("quantity",1)),
                "unit_price_paise":int(e.get("unit_price_paise",0)),"status":e.get("status","pending_order"),
                "created_at":e.get("created_at",""),"order_id":e.get("order_id","")}

    # ── Orders ────────────────────────────────────────────────────────────────

    async def write_order(self, d: dict) -> None:
        c  = self._client(self._ORDER_TABLE)
        pk = self._safe(d.get("user_mobile","anonymous"))
        ts = (d.get("created_at") or datetime.now(timezone.utc).isoformat())[:19]
        ts = ts.replace("-","").replace("T","_").replace(":","")
        rk = f"{ts}_{d.get('order_id','')[:8]}"
        addr = d.get("delivery_address") or {}
        c.upsert_entity({
            "PartitionKey":          pk, "RowKey": rk,
            "order_id":              d.get("order_id",""),
            "user_mobile":           d.get("user_mobile",""),
            "generation_id":         d.get("generation_id",""),
            "product_id":            d.get("product_id",""),
            "cart_item_ids_json":    json.dumps(d.get("cart_item_ids",[])),
            "child_name":            d.get("child_name",""),
            "story_id":              d.get("story_id",""),
            "pdf_blob_path":         d.get("pdf_blob_path",""),
            "quantity":              int(d.get("quantity",1)),
            "total_amount_paise":    int(d.get("total_amount_paise",0)),
            "currency":              d.get("currency","INR"),
            "status":                d.get("status","pending"),
            "delivery_address_json": json.dumps(addr) if isinstance(addr,dict) else str(addr),
            "payment_id":            d.get("payment_id",""),
            "payment_gateway":       d.get("payment_gateway",""),
            "payment_status":        d.get("payment_status",""),
            "tracking_id":           d.get("tracking_id",""),
            "courier":               d.get("courier",""),
            "created_at":            d.get("created_at",datetime.now(timezone.utc).isoformat()),
            "confirmed_at":          d.get("confirmed_at",""),
            "shipped_at":            d.get("shipped_at",""),
            "delivered_at":          d.get("delivered_at",""),
            "cancelled_at":          d.get("cancelled_at",""),
            "notes":                 d.get("notes",""),
        })
        logger.info("AzureTable: order %s written (status=%s)", d.get("order_id","?")[:8], d.get("status"))

    async def read_order(self, order_id: str) -> Optional[dict]:
        c = self._client(self._ORDER_TABLE)
        try:
            r = list(c.query_entities(f"order_id eq '{order_id}'"))
            return self._ord_dict(r[0]) if r else None
        except Exception as e:
            logger.warning("read_order: %s", e); return None

    async def list_orders(self, user_mobile=None, status=None, limit=100) -> list[dict]:
        c   = self._client(self._ORDER_TABLE)
        flt = f"PartitionKey eq '{self._safe(user_mobile)}'" if user_mobile else "PartitionKey ne ''"
        if status: flt += f" and status eq '{status}'"
        try:
            rows = []
            for e in c.query_entities(flt, results_per_page=min(limit,1000)):
                rows.append(self._ord_dict(e))
                if len(rows) >= limit: break
            rows.sort(key=lambda x: x.get("created_at",""), reverse=True)
            return rows
        except Exception as e:
            logger.warning("list_orders: %s", e); return []

    @staticmethod
    def _ord_dict(e) -> dict:
        try: addr = json.loads(e.get("delivery_address_json","{}"))
        except: addr = {}
        try: cids = json.loads(e.get("cart_item_ids_json","[]"))
        except: cids = []
        return {"order_id":e.get("order_id",""),"user_mobile":e.get("user_mobile",""),
                "generation_id":e.get("generation_id",""),"product_id":e.get("product_id",""),
                "cart_item_ids":cids,"child_name":e.get("child_name",""),"story_id":e.get("story_id",""),
                "pdf_blob_path":e.get("pdf_blob_path",""),"quantity":int(e.get("quantity",1)),
                "total_amount_paise":int(e.get("total_amount_paise",0)),"currency":e.get("currency","INR"),
                "status":e.get("status","pending"),"delivery_address":addr,
                "payment_id":e.get("payment_id",""),"payment_gateway":e.get("payment_gateway",""),
                "payment_status":e.get("payment_status",""),"tracking_id":e.get("tracking_id",""),
                "courier":e.get("courier",""),"created_at":e.get("created_at",""),
                "confirmed_at":e.get("confirmed_at",""),"shipped_at":e.get("shipped_at",""),
                "delivered_at":e.get("delivered_at",""),"cancelled_at":e.get("cancelled_at",""),
                "notes":e.get("notes","")}


# ─── MongoDB implementation ───────────────────────────────────────────────────

class MongoSessionStore(SessionStore):
    """MongoDB backend. Kept fully implemented. Activated when MONGO_URL is set."""

    def __init__(self, url: str, db_name: str = "storyme_db"):
        self._url = url; self._db_name = db_name; self.__db = None

    def _get_db(self):
        if self.__db is None:
            from motor.motor_asyncio import AsyncIOMotorClient
            self.__db = AsyncIOMotorClient(self._url)[self._db_name]
        return self.__db

    async def write_session(self, d):
        await self._get_db().generation_sessions.replace_one(
            {"generation_id":d["generation_id"]},d,upsert=True)

    async def read_session(self, gid):
        d = await self._get_db().generation_sessions.find_one({"generation_id":gid})
        if d: d.pop("_id",None)
        return d

    async def list_sessions(self, child_name=None, story_id=None, gender=None, limit=1000):
        q = {}
        if child_name: q["child_name"] = child_name
        if story_id:   q["story_id"]   = story_id
        if gender:     q["gender"]     = gender
        return await self._get_db().generation_sessions.find(q,{"_id":0}).to_list(limit)

    async def update_session(self, generation_id: str, updates: dict) -> bool:
        result = await self._get_db().generation_sessions.update_one(
            {"generation_id": generation_id}, {"$set": updates})
        return result.matched_count > 0

    async def write_cart_item(self, d):
        await self._get_db().cart_items.replace_one(
            {"cart_item_id":d["cart_item_id"]},d,upsert=True)

    async def read_cart_items(self, user_mobile, status=None):
        q = {"user_mobile":user_mobile}
        if status: q["status"]=status
        return await self._get_db().cart_items.find(q,{"_id":0}).to_list(100)

    async def delete_cart_item(self, user_mobile, cart_item_id):
        await self._get_db().cart_items.delete_one(
            {"user_mobile":user_mobile,"cart_item_id":cart_item_id})

    async def write_order(self, d):
        await self._get_db().orders.replace_one({"order_id":d["order_id"]},d,upsert=True)

    async def read_order(self, order_id):
        d = await self._get_db().orders.find_one({"order_id":order_id})
        if d: d.pop("_id",None)
        return d

    async def list_orders(self, user_mobile=None, status=None, limit=100):
        q = {}
        if user_mobile: q["user_mobile"]=user_mobile
        if status:      q["status"]=status
        return await self._get_db().orders.find(q,{"_id":0}).sort("created_at",-1).to_list(limit)


# ─── Null (no-op) ────────────────────────────────────────────────────────────

class NullSessionStore(SessionStore):
    async def write_session(self,d): pass
    async def read_session(self,i):  return None
    async def list_sessions(self,**k): return []
    async def update_session(self,g,u): return False
    async def write_cart_item(self,d): pass
    async def read_cart_items(self,*a,**k): return []
    async def delete_cart_item(self,*a): pass
    async def write_order(self,d): pass
    async def read_order(self,i): return None
    async def list_orders(self,**k): return []


# ─── Factory + singleton ──────────────────────────────────────────────────────

def create_session_store() -> SessionStore:
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING","")
    murl = os.environ.get("MONGO_URL","")
    if conn and conn.startswith("DefaultEndpointsProtocol"):
        logger.info("SessionStore → AzureTableSessionStore (tables: GenerationSessions, CartItems, Orders)")
        return AzureTableSessionStore(conn)
    if murl and "localhost" not in murl:
        logger.info("SessionStore → MongoSessionStore")
        return MongoSessionStore(murl)
    logger.warning("SessionStore → NullSessionStore")
    return NullSessionStore()

session_store: SessionStore = create_session_store()
