"""
AI Engineering — Secrets Vault

Almacena y recupera secrets encriptados con Fernet (cryptography).
El Director envía secrets via Telegram con: /secret PROYECTO NOMBRE VALOR
"""
import json
import os
import logging
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_SECRETS_FILE = Path("/opt/ai_engineering/data/secrets.enc")
_KEY_FILE     = Path("/opt/ai_engineering/data/.vault_key")


def _get_or_create_key() -> bytes:
    """Carga o genera la clave Fernet del vault."""
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    _KEY_FILE.chmod(0o600)
    logger.info("Vault: nueva clave generada")
    return key


def _fernet() -> Fernet:
    return Fernet(_get_or_create_key())


def _load_all() -> dict:
    """Carga todos los secrets desencriptados como dict."""
    if not _SECRETS_FILE.exists():
        return {}
    try:
        encrypted = _SECRETS_FILE.read_bytes()
        decrypted = _fernet().decrypt(encrypted)
        return json.loads(decrypted)
    except Exception as e:
        logger.error(f"Vault: error leyendo secrets: {e}")
        return {}


def _save_all(data: dict) -> None:
    """Encripta y guarda todos los secrets."""
    _SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _fernet().encrypt(json.dumps(data).encode())
    _SECRETS_FILE.write_bytes(encrypted)
    _SECRETS_FILE.chmod(0o600)


def store_secret(project: str, name: str, value: str) -> None:
    """Almacena un secret encriptado para un proyecto."""
    data = _load_all()
    if project not in data:
        data[project] = {}
    data[project][name] = value
    _save_all(data)
    logger.info(f"Vault: secret '{name}' guardado para proyecto '{project}'")


def get_secret(project: str, name: str) -> str | None:
    """Recupera un secret desencriptado."""
    data = _load_all()
    return data.get(project, {}).get(name)


def list_secrets(project: str) -> list[str]:
    """Lista los nombres de secrets de un proyecto (sin valores)."""
    data = _load_all()
    return list(data.get(project, {}).keys())


def get_project_env(project: str) -> dict[str, str]:
    """Retorna todos los secrets de un proyecto como dict para inyectar en env."""
    data = _load_all()
    return dict(data.get(project, {}))
