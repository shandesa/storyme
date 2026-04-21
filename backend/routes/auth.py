"""Auth API routes.

Endpoints
---------
POST /api/auth/send-otp          → send (simulated) OTP
POST /api/auth/verify-otp        → verify OTP; returns token if existing user
POST /api/auth/register          → create account + return token
POST /api/auth/login-password    → password login + return token
POST /api/auth/refresh           → refresh session token (requires valid token)
GET  /api/auth/me                → return current user info (requires token)

Session tokens:
  All success responses include a `token` field (JWT, HS256).
  Frontend stores it in sessionStorage as `storyme_token`.
  Sent on protected requests as: Authorization: Bearer <token>
  Expiry: SESSION_TIMEOUT_SECONDS (default 600s, configurable via env var).
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.auth_service import AuthService
from core.session_tokens import (
    require_mobile_from_request, get_mobile_from_request, create_token,
)
from core.user_store import get_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ─── Request bodies ───────────────────────────────────────────────────────────

class SendOtpRequest(BaseModel):
    mobile: str

class VerifyOtpRequest(BaseModel):
    mobile: str
    otp: str

class LoginPasswordRequest(BaseModel):
    mobile: str
    password: str

class RegisterRequest(BaseModel):
    mobile: str
    password: str


# ─── Helper ───────────────────────────────────────────────────────────────────

def _safe_user(user_dict: dict) -> dict:
    """Return user dict without sensitive fields for API responses."""
    return {
        "mobile":       user_dict.get("mobile", ""),
        "country_code": user_dict.get("country_code", "+91"),
        "created_at":   user_dict.get("created_at", ""),
        "last_login_at": user_dict.get("last_login_at", ""),
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/send-otp")
async def send_otp(body: SendOtpRequest):
    """Send (simulated) OTP. Returns the OTP in dev/simulated mode."""
    try:
        otp = AuthService.send_otp(body.mobile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info("OTP sent (simulated) to %s", body.mobile)
    return {
        "message": "OTP sent successfully",
        "otp": otp,   # dev/simulated mode only — remove when real SMS is wired
    }


@router.post("/verify-otp")
async def verify_otp(body: VerifyOtpRequest):
    """
    Verify OTP.

    Response for EXISTING user:
      { status: "LOGIN_SUCCESS", token: "...", user: {...} }
      → Frontend stores token and navigates to /home directly.
      → RegisterPage is SKIPPED for existing users.

    Response for NEW user:
      { status: "NEW_USER" }
      → Frontend navigates to /register to create a password.
      → No token yet (issued after registration).
    """
    is_valid = AuthService.verify_otp(body.mobile, body.otp)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    user_dict, is_new, token = AuthService.login_otp_success(body.mobile)

    if is_new:
        return {"status": "NEW_USER"}

    return {
        "status": "LOGIN_SUCCESS",
        "token":  token,
        "user":   _safe_user(user_dict),
    }


@router.post("/register")
async def register(body: RegisterRequest):
    """
    Register a new user with mobile + password.
    Returns a session token immediately after registration.
    """
    try:
        user_dict, token = AuthService.register(body.mobile, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "REGISTERED",
        "token":  token,
        "user":   _safe_user(user_dict),
    }


@router.post("/login-password")
async def login_password(body: LoginPasswordRequest):
    """
    Authenticate with mobile + password.
    Returns a session token on success.
    """
    result = AuthService.login_password(body.mobile, body.password)

    if result is None:
        raise HTTPException(status_code=404, detail="No account found for this mobile number")
    if result is False:
        raise HTTPException(status_code=401, detail="Incorrect password")

    user_dict, token = result
    return {
        "status": "LOGIN_SUCCESS",
        "token":  token,
        "user":   _safe_user(user_dict),
    }


@router.post("/refresh")
async def refresh_token(request: Request):
    """
    Issue a fresh session token for an already-authenticated user.
    Call this on user activity to reset the inactivity timer.
    Requires: Authorization: Bearer <token>
    """
    mobile = require_mobile_from_request(request)
    token  = AuthService.refresh_token(mobile)
    return {"token": token}


@router.get("/me")
async def get_me(request: Request):
    """
    Return current user info.
    Used by ProtectedRoute to validate session on page load/refresh.
    Returns 401 if token is missing or expired.
    """
    mobile    = require_mobile_from_request(request)
    user_dict = get_user(mobile)
    if user_dict is None:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "status": "OK",
        "user":   _safe_user(user_dict),
    }
