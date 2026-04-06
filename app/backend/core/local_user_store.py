import json
import os
from typing import Optional
from models.user import User

USER_DB_FILE = "app/backend/data/users.json"

def _ensure_file():
    os.makedirs(os.path.dirname(USER_DB_FILE), exist_ok=True)
    if not os.path.exists(USER_DB_FILE):
        with open(USER_DB_FILE, "w") as f:
            json.dump({}, f)

def load_users():
    _ensure_file()
    with open(USER_DB_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USER_DB_FILE, "w") as f:
        json.dump(users, f, indent=2)

def get_user(mobile: str) -> Optional[User]:
    users = load_users()
    if mobile in users:
        return User(**users[mobile])
    return None

def create_user(user: User):
    users = load_users()
    users[user.mobile] = user.dict()
    save_users(users)
