"""
Config loader — reads all settings from environment variables.
No YAML files to manage, everything is env-based (NaN Cloud friendly).
"""
import os
import json
import secrets


def _get_users_from_env() -> dict:
    """
    Parse USERS env var as JSON:
    [{"username": "ruben", "password": "xxx", "name": "Ruben"}, ...]

    Passwords are plaintext in the env var on first boot;
    the app hashes them on startup and stores in the SQLite DB.
    After first boot, you can remove plaintext passwords from env.
    """
    raw = os.getenv("USERS", "[]")
    try:
        users = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("USERS env var must be valid JSON array")

    result = {}
    for u in users:
        username = u.get("username", "").strip().lower()
        if not username:
            continue
        result[username] = {
            "password": u.get("password", ""),
            "name": u.get("name", username.capitalize()),
        }
    return result


class Settings:
    # Hermes API Server (OpenAI-compatible)
    HERMES_API_URL: str = os.getenv("HERMES_API_URL", "http://localhost:8642/v1")
    HERMES_API_KEY: str = os.getenv("HERMES_API_KEY", "")
    HERMES_MODEL: str = os.getenv("HERMES_MODEL", "hermes-agent")

    # Auth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

    # Session
    SESSION_DB_PATH: str = os.getenv("SESSION_DB_PATH", "/data/hvac-webapp.db")

    # Server
    APP_PORT: int = int(os.getenv("APP_PORT", "8080"))

    # Users
    USERS: dict = _get_users_from_env()


settings = Settings()

# Auto-generate JWT secret if not provided (dev only — should be set in prod)
if not settings.JWT_SECRET:
    settings.JWT_SECRET = secrets.token_urlsafe(32)
    import warnings
    warnings.warn("JWT_SECRET not set — generated random secret. "
                  "Sessions will not survive restart. Set JWT_SECRET env var.")
