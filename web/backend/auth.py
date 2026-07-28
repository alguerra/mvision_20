"""
Authentication module for MVision Web Interface.
Handles password verification and session management.

Senhas: PBKDF2-HMAC-SHA256 com salt aleatorio. Hashes legados (SHA-256 puro)
sao aceitos na verificacao e migrados automaticamente no proximo login.
"""

import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Permite importar modulos do projeto (escrita atomica)
BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.atomic_io import atomic_write_json

# Path to auth config
AUTH_CONFIG_PATH = BASE_DIR / "config" / "web_auth.json"
DEFAULT_PASSWORD = "mvision123"

PBKDF2_ITERATIONS = 100_000

# Session storage (in-memory for simplicity)
sessions: dict = {}
SESSION_DURATION_HOURS = 24


def _pbkdf2_hash(password: str, salt_hex: str) -> str:
    """Deriva hash PBKDF2-HMAC-SHA256 da senha com o salt fornecido."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    ).hex()


def hash_password(password: str) -> dict:
    """Gera par (salt, hash) PBKDF2 para a senha."""
    salt_hex = secrets.token_hex(16)
    return {
        "salt": salt_hex,
        "password_hash": _pbkdf2_hash(password, salt_hex),
    }


def load_auth_config() -> Optional[dict]:
    """Load auth configuration from file (None se ausente/corrompido)."""
    try:
        if AUTH_CONFIG_PATH.exists():
            with open(AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Arquivo corrompido (ex: queda de energia com escrita legada):
        # regenera com a senha padrao em vez de derrubar todo o login
        return None
    return None


def save_auth_config(config: dict) -> None:
    """Save auth configuration to file (escrita atomica)."""
    atomic_write_json(AUTH_CONFIG_PATH, config, indent=4)


def init_auth() -> None:
    """Initialize auth config with default password if not exists."""
    if load_auth_config() is None:
        config = {
            **hash_password(DEFAULT_PASSWORD),
            "created_at": datetime.now().isoformat(),
            "last_changed": None,
            # Senha padrao de fabrica: exigir troca no primeiro acesso
            "must_change_password": True,
        }
        save_auth_config(config)


def _check_password(config: dict, password: str) -> bool:
    """Verifica senha contra o config (PBKDF2 ou legado SHA-256 sem salt)."""
    stored = config.get("password_hash", "")
    salt_hex = config.get("salt")
    if salt_hex:
        candidate = _pbkdf2_hash(password, salt_hex)
    else:
        # Formato legado (SHA-256 puro, sem salt)
        candidate = hashlib.sha256(password.encode()).hexdigest()
    return secrets.compare_digest(candidate, stored)


def verify_password(password: str) -> bool:
    """Verify if the provided password is correct."""
    config = load_auth_config()
    if config is None:
        init_auth()
        config = load_auth_config()

    if not _check_password(config, password):
        return False

    # Migra hash legado para PBKDF2 com salt no primeiro login valido
    if not config.get("salt"):
        config.update(hash_password(password))
        save_auth_config(config)

    return True


def must_change_password() -> bool:
    """Indica se a senha atual e a padrao de fabrica (troca obrigatoria)."""
    config = load_auth_config()
    if config is None:
        return True
    return bool(config.get("must_change_password", False))


def change_password(current_password: str, new_password: str) -> tuple:
    """
    Change the password.
    Returns (success, message).
    """
    if not verify_password(current_password):
        return False, "Senha atual incorreta"

    if len(new_password) < 6:
        return False, "Nova senha deve ter pelo menos 6 caracteres"

    if new_password == DEFAULT_PASSWORD:
        return False, "A nova senha nao pode ser a senha padrao de fabrica"

    config = load_auth_config()
    config.update(hash_password(new_password))
    config["last_changed"] = datetime.now().isoformat()
    config["must_change_password"] = False
    save_auth_config(config)

    return True, "Senha alterada com sucesso"


def create_session() -> str:
    """Create a new session and return the token."""
    cleanup_expired_sessions()
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
