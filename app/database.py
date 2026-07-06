"""
SQLite database for chat sessions.
Each user gets their own conversation history.
"""
import sqlite3
import time
import os
from config import settings


def _get_db_path() -> str:
    path = settings.SESSION_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(_get_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_user
        ON messages(username, id)
    """)
    conn.commit()
    conn.close()


def save_message(username: str, role: str, content: str):
    """Save a message to the user's conversation."""
    conn = sqlite3.connect(_get_db_path())
    conn.execute(
        "INSERT INTO messages (username, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (username, role, content, time.time()),
    )
    conn.commit()
    conn.close()


def get_history(username: str, limit: int = 50) -> list:
    """Get conversation history for a user."""
    conn = sqlite3.connect(_get_db_path())
    rows = conn.execute(
        "SELECT role, content, timestamp FROM messages WHERE username = ? ORDER BY id DESC LIMIT ?",
        (username, limit),
    ).fetchall()
    conn.close()
    # Reverse to chronological order
    return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in reversed(rows)]


def clear_history(username: str):
    """Clear all messages for a user (new conversation)."""
    conn = sqlite3.connect(_get_db_path())
    conn.execute("DELETE FROM messages WHERE username = ?", (username,))
    conn.commit()
    conn.close()
