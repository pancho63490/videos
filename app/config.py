"""Configuración guardada desde el propio panel.

Permite usar el programa sin definir variables de entorno: la cuenta de
administrador, la clave del modelo de IA y el secreto de la sesión se pueden
capturar o generar desde el navegador y quedan en la tabla `settings`.

Si existe la variable de entorno equivalente, esta siempre tiene prioridad.
"""
import hashlib
import hmac
import os
import secrets
from typing import Optional

from .db import SessionLocal
from .models import Setting

# Claves de `settings` que nunca deben mostrarse en pantalla.
PRIVATE_KEYS = {
    "admin_email",
    "admin_password_hash",
    "setup_code",
    "session_secret",
    "anthropic_api_key",
    "anthropic_model",
    "seeded",
}

PBKDF2_ITERATIONS = 310_000
MIN_PASSWORD_LENGTH = 10


def get_value(key: str) -> Optional[str]:
    with SessionLocal() as db:
        setting = db.get(Setting, key)
        return setting.value if setting and setting.value else None


def set_value(key: str, value: str) -> None:
    with SessionLocal() as db:
        setting = db.get(Setting, key)
        if setting is None:
            db.add(Setting(key=key, value=value))
        else:
            setting.value = value
        db.commit()


def delete_value(key: str) -> None:
    with SessionLocal() as db:
        setting = db.get(Setting, key)
        if setting is not None:
            db.delete(setting)
            db.commit()


# --------------------------------------------------------------------------
# Secreto de la sesión
# --------------------------------------------------------------------------
def session_secret() -> str:
    """Secreto para firmar la sesión: variable de entorno o uno generado y guardado."""
    env = os.getenv("SECRET_KEY")
    if env:
        return env
    stored = get_value("session_secret")
    if stored:
        return stored
    generated = secrets.token_urlsafe(48)
    set_value("session_secret", generated)
    return generated


# --------------------------------------------------------------------------
# Cuenta de administrador
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _env_admin() -> Optional[tuple]:
    email, password = os.getenv("ADMIN_EMAIL", "").strip(), os.getenv("ADMIN_PASSWORD", "")
    return (email, password) if email and password else None


def admin_source() -> Optional[str]:
    """'env' si la cuenta viene de variables de entorno, 'panel' si se creó aquí, None si no hay."""
    if _env_admin():
        return "env"
    if get_value("admin_email") and get_value("admin_password_hash"):
        return "panel"
    return None


def admin_exists() -> bool:
    return admin_source() is not None


def check_login(email: str, password: str) -> Optional[str]:
    """Devuelve el correo de la cuenta si los datos son correctos."""
    email = email.strip().lower()
    env = _env_admin()
    if env:
        ok = hmac.compare_digest(email.encode(), env[0].lower().encode()) and hmac.compare_digest(
            password.encode(), env[1].encode()
        )
        return env[0] if ok else None
    stored_email = get_value("admin_email")
    stored_hash = get_value("admin_password_hash")
    if not stored_email or not stored_hash:
        return None
    email_ok = hmac.compare_digest(email.encode(), stored_email.lower().encode())
    password_ok = verify_password(password, stored_hash)
    return stored_email if email_ok and password_ok else None


def create_admin(email: str, password: str) -> None:
    set_value("admin_email", email.strip().lower())
    set_value("admin_password_hash", hash_password(password))
    delete_value("setup_code")


def change_password(password: str) -> None:
    set_value("admin_password_hash", hash_password(password))


def setup_code() -> str:
    """Código de un solo uso que protege la creación de la primera cuenta."""
    code = get_value("setup_code")
    if not code:
        raw = secrets.token_hex(4).upper()
        code = f"{raw[:4]}-{raw[4:]}"
        set_value("setup_code", code)
    return code


def check_setup_code(code: str) -> bool:
    expected = get_value("setup_code")
    given = code.strip().upper().replace(" ", "")
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


# --------------------------------------------------------------------------
# Modelo de IA
# --------------------------------------------------------------------------
def api_key() -> Optional[str]:
    return os.getenv("ANTHROPIC_API_KEY") or get_value("anthropic_api_key")


def api_key_source() -> Optional[str]:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "env"
    if get_value("anthropic_api_key"):
        return "panel"
    return None


def model_override() -> Optional[str]:
    return os.getenv("ANTHROPIC_MODEL") or get_value("anthropic_model")
