"""Auth API routes.

Endpoints
---------
POST /api/auth/send-otp
POST /api/auth/verify-otp
POST /api/auth/login-password
POST /api/auth/register
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.auth_service import AuthService
from core.local_user_store import get_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ─── request bodies ───────────────────────────────────────────────────────────

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


# ─── endpoints ────────────────────────────────────────────────────────────────

@router.post("/send-otp")
def send_otp(body: SendOtpRequest):
    """Send (simulated) OTP to the given mobile number.

    Returns the OTP in the response body so the frontend can surface it
    in a toast for demo / simulated mode.  Remove the ``otp`` field when
    real SMS delivery is wired up.
    """
    try:
        otp = AuthService.send_otp(body.mobile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(f"OTP sent (simulated) to {body.mobile}")
    return {
        "message": "OTP sent successfully",
        "otp": otp,          # ← simulated mode: expose so frontend can display it
    }


@router.post("/verify-otp")
def verify_otp(body: VerifyOtpRequest):
    """Verify OTP and return whether this is a new or existing user."""
    is_valid = AuthService.verify_otp(body.mobile, body.otp)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    user = get_user(body.mobile)
    if user is None:
        return {"status": "NEW_USER"}

    return {"status": "LOGIN_SUCCESS", "user": user.model_dump(mode="json")}


@router.post("/login-password")
def login_password(body: LoginPasswordRequest):
    """Authenticate with mobile + password."""
    result = AuthService.login_password(body.mobile, body.password)

    if result is None:
        raise HTTPException(status_code=404, detail="No account found for this mobile number")
    if result is False:
        raise HTTPException(status_code=401, detail="Incorrect password")

    return {"status": "LOGIN_SUCCESS", "user": result.model_dump(mode="json")}


@router.post("/register")
def register(body: RegisterRequest):
    """Register a new user account."""
    try:
        user = AuthService.register(body.mobile, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "REGISTERED", "user": user.model_dump(mode="json")}
