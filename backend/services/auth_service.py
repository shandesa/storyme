"""Authentication service.

OTP-based login flow:
  1. send_otp(mobile)          → generates & stores OTP
  2. verify_otp(mobile, otp)   → True/False
  3. register(mobile, password) → user_dict + token
  4. login_password(mobile, password) → user_dict + token | None | False
  5. login_otp_success(mobile)  → (user_dict | None, is_new_user: bool)
     Called after OTP is verified — returns existing user if found.

Storage:
  - Users: Azure Table (AzureUserStore) or local JSON (JsonUserStore dev fallback)
  - OTPs:  In-process dict (acceptable for simulated mode; use Redis for prod)

Passwords:
  - Stored as bcrypt hashes (passlib, cost=12)
  - Legacy plaintext passwords are re-hashed on first successful login
"""

import random
import logging
from datetime import datetime, timezone
from typing import Optional, Union, Tuple

from core.user_store import (
    get_user, upsert_user, touch_login, user_exists,
    hash_password, verify_password, is_hashed,
)
from core.session_tokens import create_token

logger = logging.getLogger(__name__)

# In-process OTP store {mobile: otp_string}
# Replace with Redis + TTL for production SMS delivery.
_OTP_STORE: dict[str, str] = {}


class AuthService:

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_mobile(mobile: str) -> None:
        if not mobile or not mobile.isdigit() or len(mobile) != 10:
            raise ValueError("Mobile must be a 10-digit Indian number (no country code)")

    # ── OTP ───────────────────────────────────────────────────────────────────

    @staticmethod
    def send_otp(mobile: str) -> str:
        AuthService._validate_mobile(mobile)
        otp = str(random.randint(100_000, 999_999))
        _OTP_STORE[mobile] = otp
        logger.info("[SIMULATED OTP] %s → %s", mobile, otp)
        return otp

    @staticmethod
    def verify_otp(mobile: str, otp: str) -> bool:
        stored = _OTP_STORE.get(mobile)
        if stored and stored == otp.strip():
            del _OTP_STORE[mobile]  # one-time use
            return True
        return False

    # ── OTP login (after verify_otp succeeds) ─────────────────────────────────

    @staticmethod
    def login_otp_success(mobile: str) -> Tuple[Optional[dict], bool, Optional[str]]:
        """
        Called after OTP is successfully verified.

        Returns:
          (user_dict, is_new_user, token)

          user_dict    — existing user or None if new
          is_new_user  — True if no account exists yet (→ RegisterPage)
          token        — session JWT if existing user, None if new user
        """
        user = get_user(mobile)
        if user is None:
            return None, True, None

        # Existing user — create session token and update login timestamp
        touch_login(mobile)
        token = create_token(mobile)
        logger.info("OTP login success (existing user): %s", mobile)
        return user, False, token

    # ── Registration ──────────────────────────────────────────────────────────

    @staticmethod
    def register(mobile: str, password: str, display_name: str = "") -> Tuple[dict, str]:
        """
        Create a new user account with a hashed password and optional display name.

        Returns (user_dict, session_token).
        Raises ValueError for validation failures.
        """
        AuthService._validate_mobile(mobile)
        if not password or len(password) < 6:
            raise ValueError("Password must be at least 6 characters")

        now = datetime.now(timezone.utc).isoformat()
        user_dict = {
            "mobile":                mobile,
            "password_hash":         hash_password(password),
            "country_code":          "+91",
            "display_name":          display_name.strip(),
            "email":                 "",
            "account_status":        "active",
            "deletion_requested_at": "",
            "created_at":            now,
            "last_login_at":         now,
        }
        upsert_user(user_dict)
        token = create_token(mobile)
        logger.info("New user registered: %s (name=%r)", mobile, display_name.strip())
        return user_dict, token

    # ── Password login ────────────────────────────────────────────────────────

    @staticmethod
    def login_password(
        mobile: str, password: str
    ) -> Union[Tuple[dict, str], None, bool]:
        """
        Authenticate with mobile + password.

        Returns:
          (user_dict, token)  — credentials correct
          False               — user exists but wrong password
          None                — user not found
        """
        user = get_user(mobile)
        if user is None:
            return None

        # Reject accounts that have been marked for deletion
        if user.get("account_status") == "deletion_requested":
            return "deleted"

        stored_hash = user.get("password_hash", "")

        # Migrate legacy plaintext password on first successful password login
        if not is_hashed(stored_hash):
            if stored_hash != password:
                return False
            # Re-hash and save
            user["password_hash"] = hash_password(password)
            user["last_login_at"] = datetime.now(timezone.utc).isoformat()
            upsert_user(user)
            logger.info("Migrated plaintext password to bcrypt for %s", mobile)
        else:
            if not verify_password(password, stored_hash):
                return False
            touch_login(mobile)

        token = create_token(mobile)
        logger.info("Password login success: %s", mobile)
        return user, token

    # ── Refresh token ─────────────────────────────────────────────────────────

    @staticmethod
    def refresh_token(mobile: str) -> str:
        """Issue a fresh token for an already-authenticated user."""
        touch_login(mobile)
        return create_token(mobile)
