"""
Authentication: JWT + bcrypt.
Users are defined via USERS env var (JSON array).
Passwords are hashed with bcrypt on first boot.
"""
import time
from typing import Optional
import bcrypt
import jwt
from config import settings


# Hash passwords on import
_users_db: dict = {}

for username, info in settings.USERS.items():
    pw = info["password"]
    if not pw:
        continue
    # Hash if not already hashed (bcrypt hashes start with $2b$)
    if not pw.startswith("$2b$"):
        pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    else:
        pw_hash = pw
    _users_db[username] = {
        "password_hash": pw_hash,
        "name": info["name"],
    }


def verify_user(username: str, password: str) -> Optional[dict]:
    """Verify credentials, return user dict if valid, None otherwise."""
    username = username.strip().lower()
    user = _users_db.get(username)
    if not user:
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return {"username": username, "name": user["name"]}
    return None


def create_token(user: dict) -> str:
    """Create JWT token for authenticated user."""
    payload = {
        "sub": user["username"],
        "name": user["name"],
        "iat": int(time.time()),
        "exp": int(time.time()) + (settings.JWT_EXPIRE_HOURS * 3600),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Verify JWT, return payload if valid, None otherwise."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return {"username": payload["sub"], "name": payload["name"]}
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
