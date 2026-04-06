import random
import logging
from core.local_user_store import get_user, create_user
from models.user import User

logger = logging.getLogger(__name__)

OTP_STORE = {}

class AuthService:

    @staticmethod
    def validate_mobile(mobile: str):
        if not mobile.isdigit() or len(mobile) != 10:
            raise ValueError("Invalid Indian mobile number")

    @staticmethod
    def send_otp(mobile: str):
        AuthService.validate_mobile(mobile)
        otp = str(random.randint(100000, 999999))
        OTP_STORE[mobile] = otp
        logger.info(f"[OTP SENT] {mobile} -> {otp}")
        return True

    @staticmethod
    def verify_otp(mobile: str, otp: str):
        return OTP_STORE.get(mobile) == otp

    @staticmethod
    def login_password(mobile: str, password: str):
        user = get_user(mobile)
        if not user:
            return None
        if user.password == password:
            return user
        return False

    @staticmethod
    def register(mobile: str, password: str):
        user = User(mobile=mobile, password=password)
        create_user(user)
        return user
