from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

MIN_LENGTH = 10
MAX_LENGTH = 128

_hasher = PasswordHasher()  # Argon2id with safe defaults

# Verified against when an email doesn't exist, so timing doesn't reveal it
_DUMMY_HASH = _hasher.hash("pricepounce-dummy-password")

COMMON_PASSWORDS = {
    "1234567890", "0123456789", "0987654321", "1234512345", "123456789a",
    "password12", "password123", "password1234", "passw0rd123",
    "qwertyuiop", "qwerty12345", "qwerty123456", "1q2w3e4r5t",
    "iloveyou12", "iloveyou123", "welcome123", "letmein1234",
    "administrator", "abcdefghij", "abcd123456", "pricepounce",
}


def hash_password(password):
    return _hasher.hash(password)


def verify_password(password, stored_hash):
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy(password):
    verify_password(password, _DUMMY_HASH)


def needs_rehash(stored_hash):
    return _hasher.check_needs_rehash(stored_hash)


def validate_password(password, email=""):
    """Returns a list of problems. An empty list means the password is fine."""
    errors = []

    if len(password) < MIN_LENGTH:
        errors.append(f"Use at least {MIN_LENGTH} characters.")

    if len(password) > MAX_LENGTH:
        errors.append(f"Use at most {MAX_LENGTH} characters.")

    if password.lower() in COMMON_PASSWORDS:
        errors.append("That password is too common.")

    local_part = (email or "").split("@")[0].lower()

    if len(local_part) >= 4 and local_part in password.lower():
        errors.append("Don't include your email name in the password.")

    if password and len(set(password)) < 4:
        errors.append("Use a wider mix of characters.")

    return errors