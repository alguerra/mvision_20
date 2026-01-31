"""
Authentication module for MVision Web Interface.
Handles password verification and session management.
"""

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Path to auth config
AUTH_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "web_auth.json"
DEFAULT_PASSWORD = "mvision123"

# Session storage (in-memory for simplicity)
sessions: dict[str, datetime] = {}
SESSION_DURATION_HOURS = 24


def hash_password(password: str) -> str:
    """Hash password using SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()


def load_auth_config() -> dict:
    """Load auth configuration from file."""
    if AUTH_CONFIG_PATH.exists():
        with open(AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_auth_config(config: dict) -> None:
    """Save auth configuration to file."""
    AUTH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUTH_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def init_auth() -> None:
    """Initialize auth config with default password if not exists."""
    if not AUTH_CONFIG_PATH.exists():
        config = {
            "password_hash": hash_password(DEFAULT_PASSWORD),
            "created_at": datetime.now().isoformat(),
            "last_changed": None
        }
        save_auth_config(config)


def verify_password(password: str) -> bool:
    """Verify if the provided password is correct."""
    config = load_auth_config()
    if config is None:
        init_auth()
        config = load_auth_config()

    return config["password_hash"] == hash_password(password)


def change_password(current_password: str, new_password: str) -> tuple[bool, str]:
    """
    Change the password.
    Returns (success, message).
    """
    if not verify_password(current_password):
        return False, "Senha atual incorreta"

    if len(new_password) < 6:
        return False, "Nova senha deve ter pelo menos 6 caracteres"

    config = load_auth_config()
    config["password_hash"] = hash_password(new_password)
    config["last_changed"] = datetime.now().isoformat()
    save_auth_config(config)

    return True, "Senha alterada com sucesso"


def create_session() -> str:
    """Create a new session and return the token."""
    token = secrets.token_urlsafe(32)
    sessions[token] = datetime.now() + timedelta(hours=SESSION_DURATION_HOURS)
    return token


def verify_session(token: Optional[str]) -> bool:
    """Verify if a session token is valid."""
    if not token:
        return False

    if token not in sessions:
        return False

    if datetime.now() > sessions[token]:
        # Session expired
        del sessions[token]
        return False

    return True


def invalidate_session(token: str) -> None:
    """Invalidate a session token."""
    if token in sessions:
        del sessions[token]


def cleanup_expired_sessions() -> None:
    """Remove expired sessions from memory."""
    now = datetime.now()
    expired = [token for token, expiry in sessions.items() if now > expiry]
    for token in expired:
        del sessions[token]
