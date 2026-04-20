"""
models/generation.py
====================
MongoDB document models for generation sessions and orders.

Collections:
  generation_sessions   — one doc per storybook generation attempt
  orders                — one doc per print/delivery order (future)

Design notes:
  - All timestamps are UTC ISO-8601 strings for portable serialisation
  - generation_id is the primary key and also the blob storage prefix
  - generation_mode is stored so analytics can compare CV vs AI quality
  - order model is forward-compatible: status enum covers offline printing flow
  - No PII beyond child_name (no phone in generation docs; phone is in users)
"""

from __future__ import annotations
from typing import Optional, List
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid


# ─── Enums ────────────────────────────────────────────────────────────────────

class GenerationMode(str, Enum):
    """
    How page images are generated.

    OPENCV: face_blend.py pipeline — MediaPipe landmarks → affine align →
            colour match → seamlessClone into template. Fast, no API cost.

    AI:     Model-based — user face + reference image + scene prompt sent to
            an image generation model (e.g. DALL-E, Stable Diffusion).
            Higher quality potential, slower, incurs API cost.
    """
    OPENCV = "opencv"   # default — OpenCV seamlessClone pipeline
    AI     = "ai"       # AI model-based image generation


class Gender(str, Enum):
    """Gender variant of a story (affects which template set is used)."""
    MALE    = "male"
    FEMALE  = "female"
    NEUTRAL = "neutral"


class GenerationStatus(str, Enum):
    """Lifecycle states of a generation session."""
    PENDING    = "pending"     # session created, not started
    PREVIEWING = "previewing"  # page-1 preview being generated
    PREVIEW_OK = "preview_ok"  # preview shown to user, waiting for confirm
    GENERATING = "generating"  # full storybook being generated
    COMPLETE   = "complete"    # PDF ready for download
    FAILED     = "failed"      # generation failed


class OrderStatus(str, Enum):
    """
    Lifecycle states for a print/delivery order.
    Designed for offline printing + order management flow.

    Flow:
      PENDING → CONFIRMED → PRINTING → SHIPPED → DELIVERED
      Any state → CANCELLED
    """
    PENDING   = "pending"     # order created, payment not confirmed
    CONFIRMED = "confirmed"   # payment confirmed, queued for printing
    PRINTING  = "printing"    # sent to print partner
    SHIPPED   = "shipped"     # dispatched to delivery partner
    DELIVERED = "delivered"   # delivered to customer
    CANCELLED = "cancelled"   # cancelled by user or admin


# ─── Generation Session ───────────────────────────────────────────────────────

class PageResult(BaseModel):
    """Result for a single generated page."""
    page_number:    int
    blob_path:      Optional[str] = None   # storage_paths.generation_page_path()
    succeeded:      bool = False
    error_message:  Optional[str] = None
    generation_ms:  Optional[int] = None   # how long this page took


class GenerationSession(BaseModel):
    """
    One generation session = one storybook attempt by one user.

    Stored in MongoDB collection: generation_sessions
    Primary key: generation_id (also used as blob prefix in Azure)

    Lifecycle:
      Created when user requests preview.
      Updated as pages are generated.
      Finalised when PDF is ready or generation fails.
    """
    generation_id:   str = Field(default_factory=lambda: uuid.uuid4().hex)
    child_name:      str
    story_id:        str
    gender:          Gender = Gender.NEUTRAL
    generation_mode: GenerationMode = GenerationMode.OPENCV
    status:          GenerationStatus = GenerationStatus.PENDING

    # Storage paths (set as generation progresses)
    upload_blob_path:  Optional[str] = None   # transient user photo path
    preview_blob_path: Optional[str] = None   # page-1 preview PNG
    pdf_blob_path:     Optional[str] = None   # final PDF (permanent)
    pdf_filename:      Optional[str] = None   # filename for download header

    # Page-level results (set during full generation)
    page_results:     List[PageResult] = Field(default_factory=list)
    pages_succeeded:  int = 0
    pages_failed:     int = 0
    total_pages:      int = 0

    # Timing
    created_at:    str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    preview_at:    Optional[str] = None   # when preview was shown to user
    started_at:    Optional[str] = None   # when full generation started
    completed_at:  Optional[str] = None   # when PDF was ready

    # Error info (if status == FAILED)
    error_message: Optional[str] = None

    # Linked user (if authenticated; None for anonymous)
    user_mobile:   Optional[str] = None

    class Config:
        use_enum_values = True


# ─── Order (future: offline printing + delivery) ──────────────────────────────

class DeliveryAddress(BaseModel):
    """Shipping address for a print order."""
    full_name:    str
    line1:        str
    line2:        Optional[str] = None
    city:         str
    state:        str
    pincode:      str
    country:      str = "India"
    phone:        str


class Order(BaseModel):
    """
    A print order for a completed storybook.
    One order links to one GenerationSession (via generation_id).

    Stored in MongoDB collection: orders

    Future fields to add when payment is wired up:
      payment_id, payment_gateway, amount_paise, currency

    Designed for the offline printing flow:
      1. User views PDF, decides to order a physical copy
      2. Order created with status PENDING
      3. Admin confirms → CONFIRMED
      4. Sent to print partner → PRINTING
      5. Dispatched → SHIPPED (with tracking_id)
      6. Delivered → DELIVERED
    """
    order_id:       str = Field(default_factory=lambda: uuid.uuid4().hex)
    generation_id:  str   # links to GenerationSession
    child_name:     str
    story_id:       str
    pdf_blob_path:  str   # the specific PDF to print

    status:         OrderStatus = OrderStatus.PENDING
    delivery_address: Optional[DeliveryAddress] = None

    # Print details
    copies:         int = 1
    paper_size:     str = "A4"   # A4 | Letter | A5
    cover_type:     str = "soft" # soft | hard

    # Tracking (set when SHIPPED)
    tracking_id:    Optional[str] = None
    courier:        Optional[str] = None   # e.g. "BlueDart", "Delhivery"

    # Pricing (in paise; e.g. 29900 = ₹299.00)
    amount_paise:   Optional[int] = None
    currency:       str = "INR"

    # Payment
    payment_id:         Optional[str] = None
    payment_gateway:    Optional[str] = None  # e.g. "razorpay"
    payment_status:     Optional[str] = None  # "paid" | "refunded" | "failed"

    # Timestamps
    created_at:     str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    confirmed_at:   Optional[str] = None
    shipped_at:     Optional[str] = None
    delivered_at:   Optional[str] = None
    cancelled_at:   Optional[str] = None

    # Admin notes
    notes:          Optional[str] = None

    # Linked user
    user_mobile:    Optional[str] = None

    class Config:
        use_enum_values = True


# ─── MongoDB index spec (applied at startup) ──────────────────────────────────

GENERATION_INDEXES = [
    # Primary key — unique per generation session
    {"key": [("generation_id", 1)], "unique": True},
    # Lookup by user — "all books I've generated"
    {"key": [("user_mobile", 1), ("created_at", -1)]},
    # Lookup by child — "all books for Niku"
    {"key": [("child_name", 1), ("story_id", 1)]},
    # Status monitoring — "all pending generations"
    {"key": [("status", 1), ("created_at", -1)]},
]

ORDER_INDEXES = [
    {"key": [("order_id", 1)], "unique": True},
    # Link to generation
    {"key": [("generation_id", 1)]},
    # User's order history
    {"key": [("user_mobile", 1), ("created_at", -1)]},
    # Status dashboard for admin
    {"key": [("status", 1), ("created_at", -1)]},
    # Tracking lookup
    {"key": [("tracking_id", 1)], "sparse": True},
]
