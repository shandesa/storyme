"""
core/session_tokens.py
========================
JWT-based session token management.

Tokens are signed with HS256 using SESSION_SECRET_KEY env var.
They carry the user's mobile number and expire after SESSION_TIMEOUT_SECONDS
(default 600 = 10 minutes, configurable).

The timeout is "absolute from issue" — a fresh token is issued on every
successful API call so the frontend inactivity timer and token expiry align.

Token payload:
  sub   — mobile number
  iat   — issued-at (UTC epoch)
  exp   — expiry (UTC epoch = iat + SESSION_TIMEOUT_SECONDS)
  type  — "session"

Usage:
  token  = create_token(mobile)
  mobile = validate_token(token)   # raises HTTPException if invalid/expired
"""

from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_DEFAULT_SECRET  = "CHANGE_ME_SET_SESSION_SECRET_KEY_ENV_VAR"
_DEFAULT_TIMEOUT = 600   # seconds


def _secret() -> str:
    s = os.environ.get("SESSION_SECRET_KEY", _DEFAULT_SECRET)
    if s == _DEFAULT_SECRET:
        logger.warning(
            "SESSION_SECRET_KEY is not set — using insecure default. "
            "Set it in Azure App Service → Configuration → Application Settings."
        )
    return s


def _timeout() -> int:
    try:
        return int(os.environ.get("SESSION_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT))
    except (ValueError, TypeError):
        return _DEFAULT_TIMEOUT


def create_token(mobile: str) -> str:
    """
    Create a signed JWT session token for the given mobile number.
    Called on: OTP-verified login, password login, registration.
    """
    now     = datetime.now(timezone.utc)
    timeout = _timeout()
    payload = {
        "sub":  mobile,
        "iat":  int(now.timestamp()),
        "exp":  int((now + timedelta(seconds=timeout)).timestamp()),
        "type": "session",
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def validate_token(token: str) -> str:
    """
    Validate a JWT session token and return the mobile number (sub).
    Raises HTTPException 401 if invalid, expired, or malformed.
    """
    try:
        payload = jwt.decode(
            token, _secret(), algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat"]},
        )
        if payload.get("type") != "session":
            raise ValueError("wrong token type")
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid session token: {e}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth error: {e}")


def get_token_from_request(request) -> Optional[str]:
    """
    Extract token from Authorization: Bearer <token> header.
    Returns the raw token string or None.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return None


def get_mobile_from_request(request) -> Optional[str]:
    """
    Validate session token in the request and return mobile, or None.
    Does NOT raise — returns None for unauthenticated requests.
    Used by endpoints that work for both auth and anonymous users.
    """
    token = get_token_from_request(request)
    if not token:
        return None
    try:
        return validate_token(token)
    except HTTPException:
        return None


def require_mobile_from_request(request) -> str:
    """
    Validate session token and return mobile.
    Raises HTTPException 401 if not authenticated.
    Used by endpoints that require a logged-in user.
    """
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in.",
        )
    return validate_token(token)
