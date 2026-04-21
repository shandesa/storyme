"""
services/product_catalog.py
============================
Product catalog for print ordering.

Azure Table: PrintProducts
  PK = "storyme"  (single partition — catalogue has < 20 products ever)
  RK = product_id  e.g. "paperback_a4"

Products are seeded at application startup (idempotent — skipped if
the row already exists). Real prices/descriptions updated by replacing
the entity — no schema migration needed.

Access pattern:
  GET /api/v2/print/products   → list_products()
  (cover images served separately via cover_image_gen.py)
"""

from __future__ import annotations
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_PARTITION_KEY = "storyme"

# ─── Seed data ────────────────────────────────────────────────────────────────
# Source of truth for the initial product catalogue.
# Format: each dict maps directly to an Azure Table entity.
#
# price_paise: price in smallest currency unit (paise for INR, 100 paise = ₹1)
# available:   only True products are shown to users in the current release
# sort_order:  display order on the PrintOrderPage

SEED_PRODUCTS = [
    {
        "product_id":   "paperback_a4",
        "display_name": "Paperback — A4",
        "cover_type":   "paperback",
        "paper_size":   "A4",
        "dimensions":   "210 × 297 mm",
        "price_paise":  29900,          # ₹299
        "description":  "Soft cover, full colour print, 10 story pages, A4 size. "
                        "Perfect for little hands. Delivered in 7–10 business days.",
        "pages":        12,             # 10 story + cover + back
        "weight_grams": 120,
        "available":    True,
        "sort_order":   1,
    },
    {
        "product_id":   "hardcover_a4",
        "display_name": "Hardcover — A4",
        "cover_type":   "hardcover",
        "paper_size":   "A4",
        "dimensions":   "210 × 297 mm",
        "price_paise":  49900,          # ₹499
        "description":  "Premium hardcover, full colour print, 10 story pages, A4 size. "
                        "Durable cover perfect for a keepsake. Delivered in 10–14 business days.",
        "pages":        12,
        "weight_grams": 280,
        "available":    True,
        "sort_order":   2,
    },
    {
        "product_id":   "paperback_a5",
        "display_name": "Paperback — A5",
        "cover_type":   "paperback",
        "paper_size":   "A5",
        "dimensions":   "148 × 210 mm",
        "price_paise":  24900,          # ₹249
        "description":  "Compact soft cover, full colour print, A5 size. "
                        "Great for travel. Delivered in 7–10 business days.",
        "pages":        12,
        "weight_grams": 80,
        "available":    False,          # Phase 2 — not shown yet
        "sort_order":   3,
    },
    {
        "product_id":   "hardcover_a5",
        "display_name": "Hardcover — A5",
        "cover_type":   "hardcover",
        "paper_size":   "A5",
        "dimensions":   "148 × 210 mm",
        "price_paise":  44900,          # ₹449
        "description":  "Compact premium hardcover, A5 size. "
                        "Delivered in 10–14 business days.",
        "pages":        12,
        "weight_grams": 200,
        "available":    False,          # Phase 2
        "sort_order":   4,
    },
]


class ProductCatalogStore:
    """
    Read / seed print product metadata from Azure Table Storage.

    Separate from SessionStore because:
      - Different access pattern (read-heavy, write-once at startup)
      - Different Azure Table (PrintProducts)
      - Never needs MongoDB fallback — products are static catalogue data
    """

    TABLE_NAME = "PrintProducts"

    def __init__(self, connection_string: str):
        self._conn   = connection_string
        self._client = None

    @classmethod
    def from_env(cls) -> Optional["ProductCatalogStore"]:
        conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        if not conn:
            return None
        return cls(conn)

    def _get_client(self):
        if self._client is None:
            from azure.data.tables import TableServiceClient
            svc          = TableServiceClient.from_connection_string(self._conn)
            self._client = svc.get_table_client(self.TABLE_NAME)
            try:
                self._client.create_table()
                logger.info("Azure Table '%s' created", self.TABLE_NAME)
            except Exception:
                pass  # already exists
        return self._client

    # ── Seed ─────────────────────────────────────────────────────────────────

    def seed_products(self) -> None:
        """
        Insert all SEED_PRODUCTS into Azure Table if they don't already exist.
        Idempotent — safe to call on every startup.
        """
        client = self._get_client()
        for p in SEED_PRODUCTS:
            pk = _PARTITION_KEY
            rk = p["product_id"]
            try:
                # Try to read — if it exists, skip (preserve any admin edits)
                client.get_entity(partition_key=pk, row_key=rk)
                logger.debug("Product '%s' already exists — skipping seed", rk)
            except Exception:
                # Doesn't exist — create it
                entity = {
                    "PartitionKey":  pk,
                    "RowKey":        rk,
                    "product_id":    p["product_id"],
                    "display_name":  p["display_name"],
                    "cover_type":    p["cover_type"],
                    "paper_size":    p["paper_size"],
                    "dimensions":    p["dimensions"],
                    "price_paise":   int(p["price_paise"]),
                    "description":   p["description"],
                    "pages":         int(p["pages"]),
                    "weight_grams":  int(p["weight_grams"]),
                    "available":     bool(p["available"]),
                    "sort_order":    int(p["sort_order"]),
                }
                client.upsert_entity(entity)
                logger.info("Seeded product '%s'", rk)

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_products(self, available_only: bool = True) -> list[dict]:
        """Return all products, optionally filtered to available only."""
        client = self._get_client()
        flt    = f"PartitionKey eq '{_PARTITION_KEY}'"
        if available_only:
            flt += " and available eq true"
        try:
            products = [self._to_dict(e) for e in client.query_entities(flt)]
            products.sort(key=lambda p: p.get("sort_order", 99))
            return products
        except Exception as ex:
            logger.warning("list_products failed: %s", ex)
            return []

    def get_product(self, product_id: str) -> Optional[dict]:
        """Return a single product by ID, or None."""
        client = self._get_client()
        try:
            entity = client.get_entity(
                partition_key=_PARTITION_KEY, row_key=product_id
            )
            return self._to_dict(entity)
        except Exception:
            return None

    # ── Serialise ─────────────────────────────────────────────────────────────

    @staticmethod
    def _to_dict(e) -> dict:
        price_paise = int(e.get("price_paise", 0))
        return {
            "product_id":    e.get("product_id",   e.get("RowKey", "")),
            "display_name":  e.get("display_name", ""),
            "cover_type":    e.get("cover_type",   "paperback"),
            "paper_size":    e.get("paper_size",   "A4"),
            "dimensions":    e.get("dimensions",   ""),
            "price_paise":   price_paise,
            "price_display": f"₹{price_paise // 100}",
            "description":   e.get("description",  ""),
            "pages":         int(e.get("pages",         12)),
            "weight_grams":  int(e.get("weight_grams",   0)),
            "available":     bool(e.get("available",   True)),
            "sort_order":    int(e.get("sort_order",    99)),
        }


# ─── Module-level singleton ───────────────────────────────────────────────────

_catalog_store: Optional[ProductCatalogStore] = None

def get_catalog_store() -> Optional[ProductCatalogStore]:
    """Return the singleton ProductCatalogStore, or None if not configured."""
    global _catalog_store
    if _catalog_store is None:
        _catalog_store = ProductCatalogStore.from_env()
    return _catalog_store
