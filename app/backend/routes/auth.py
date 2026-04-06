from fastapi import APIRouter, HTTPException
from services.auth_service import AuthService
from core.local_user_store import get_user

router = APIRouter(prefix="/api/auth")

@router.post("/send-otp")
def send_otp(data: dict):
    mobile = data.get("mobile")
    AuthService.send_otp(mobile)
    return {"message": "OTP sent"}

@router.post("/verify-otp")
def verify_otp(data: dict):
    mobile = data.get("mobile")
    otp = data.get("otp")

    if not AuthService.verify_otp(mobile, otp):
        raise HTTPException(400, "Invalid OTP")

    user = get_user(mobile)

    if not user:
        return {"status": "NEW_USER"}

    return {"status": "LOGIN_SUCCESS", "user": user.dict()}

@router.post("/login-password")
def login_password(data: dict):
    mobile = data.get("mobile")
    password = data.get("password")

    result = AuthService.login_password(mobile, password)

    if result is None:
        raise HTTPException(404, "User not found")

    if result is False:
        raise HTTPException(401, "Incorrect password")

    return {"status": "LOGIN_SUCCESS", "user": result.dict()}

@router.post("/register")
def register(data: dict):
    mobile = data.get("mobile")
    password = data.get("password")

    user = AuthService.register(mobile, password)
    return {"status": "REGISTERED", "user": user.dict()}
