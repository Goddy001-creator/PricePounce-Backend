import hashlib
import secrets
import time

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import APP_NAME, TOTP_ENCRYPTION_KEY


def _fernet():
    if not TOTP_ENCRYPTION_KEY:
        raise RuntimeError("TOTP_ENCRYPTION_KEY is not set in .env")

    return Fernet(TOTP_ENCRYPTION_KEY.encode())


def new_secret():
    return pyotp.random_base32()


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def provisioning_uri(secret, email):
    return pyotp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name=APP_NAME,
    )


def verify_code(secret, code, last_step):
    """Returns the accepted 30-second step, or None.

    A step that was already used is refused, so a code works only once.
    """
    code = str(code or "").strip().replace(" ", "")

    if not (code.isdigit() and len(code) == 6):
        return None

    totp = pyotp.TOTP(secret)
    current = int(time.time() // 30)

    for step in (current - 1, current, current + 1):
        if last_step is not None and step <= last_step:
            continue

        if secrets.compare_digest(totp.at(step * 30), code):
            return step

    return None


def normalize_recovery_code(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def hash_recovery_code(code):
    return hashlib.sha256(normalize_recovery_code(code).encode()).hexdigest()


def new_recovery_codes(count=8):
    codes = []

    for _ in range(count):
        raw = secrets.token_hex(6).upper()
        codes.append(f"{raw[:6]}-{raw[6:]}")

    return codes