"""Authentication service.

OTP-based login flow:
  1. send_otp(mobile)   → generates & stores a random 6-digit OTP
  2. verify_otp(mobile, otp) → True/False
  3. register(mobile, password) → creates User
  4. login_password(mobile, password) → User | None | False

The OTP store is in-process memory (dict).
For production, replace with Redis TTL keys.
"""

import random
import logging
from typing import Optional, Union

from core.local_user_store import get_user, create_user
from models.user import User

logger = logging.getLogger(__name__)

# In-process OTP store  {mobile: otp_string}
# Acceptable for MVP/simulated mode; use Redis + TTL in production.
_OTP_STORE: dict[str, str] = {}


class AuthService:

    # ── OTP ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_mobile(mobile: str) -> None:
        """Raise ValueError for invalid Indian mobile numbers."""
        if not mobile or not mobile.isdigit() or len(mobile) != 10:
            raise ValueError("Mobile must be a 10-digit Indian number (no country code)")

    @staticmethod
    def send_otp(mobile: str) -> str:
        """Generate OTP, store it, log it, and return it (for simulated mode)."""
        AuthService._validate_mobile(mobile)
        otp = str(random.randint(100_000, 999_999))
        _OTP_STORE[mobile] = otp
        # Always log so developers can see it in server output
        logger.info(f"[SIMULATED OTP] {mobile} → {otp}")
        return otp

    @staticmethod
    def verify_otp(mobile: str, otp: str) -> bool:
        """Return True iff the supplied OTP matches the stored one."""
        stored = _OTP_STORE.get(mobile)
        if stored and stored == otp.strip():
            # Consume the OTP (one-time use)
            del _OTP_STORE[mobile]
            return True
        return False

    # ── Registration & Login ──────────────────────────────────────────────────

    @staticmethod
    def register(mobile: str, password: str) -> User:
        """Create and persist a new user."""
        AuthService._validate_mobile(mobile)
        if not password or len(password) < 6:
            raise ValueError("Password must be at least 6 characters")
        user = User(mobile=mobile, password=password)
        create_user(user)
        logger.info(f"New user registered: {mobile}")
        return user

    @staticmethod
    def login_password(mobile: str, password: str) -> Optional[Union[User, bool]]:
        """
        Returns:
          User  — credentials correct
          False — user exists but wrong password
          None  — user not found
        """
        user = get_user(mobile)
        if user is None:
            return None
        if user.password == password:
            return user
        return False
