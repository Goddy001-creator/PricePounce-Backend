import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, request

from app.config.settings import (
    COOKIE_NAME,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    REQUIRE_LOGIN_FOR_DATA,
    SESSION_DAYS,
)
from app.database import auth_repository as repo

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id, mfa_verified=False):
    token = new_token()
    csrf_token = secrets.token_hex(32)

    repo.create_session(
        user_id,
        hash_token(token),
        csrf_token,
        utcnow() + timedelta(days=SESSION_DAYS),
        mfa_verified,
    )

    return token, csrf_token


def set_session_cookie(response, token):
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_session_cookie(response):
    response.set_cookie(
        COOKIE_NAME,
        "",
        max_age=0,
        expires=0,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def load_session():
    token = request.cookies.get(COOKIE_NAME)

    if not token:
        return None

    token_hash = hash_token(token)
    row = repo.get_session(token_hash)

    if row is None:
        return None

    # Expired sessions and suspended accounts are cut off immediately
    if row["expires_at"] <= utcnow() or row["status"] != "active":
        repo.delete_session(token_hash)
        return None

    return row


def optional_session():
    row = load_session()
    g.session = row
    return row


def _authenticate():
    """Returns (session_row, None) or (None, error_response)."""
    row = load_session()

    if row is None:
        return None, (jsonify({"error": "Authentication required"}), 401)

    if request.method not in SAFE_METHODS:
        sent = request.headers.get("X-CSRF-Token", "")

        if not secrets.compare_digest(
            sent.encode("utf-8"),
            row["csrf_token"].encode("utf-8"),
        ):
            return None, (jsonify({"error": "Invalid CSRF token"}), 403)

    g.session = row
    return row, None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        _row, failure = _authenticate()

        if failure:
            return failure

        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        row, failure = _authenticate()

        if failure:
            return failure

        # Hide the existence of admin routes from everyone else
        if row["role"] != "admin":
            return jsonify({"error": "Not found"}), 404

        if not row["totp_enabled"] or not row["mfa_verified"]:
            return jsonify({
                "error": "Two-factor authentication is required for admin access.",
                "code": "mfa_required",
            }), 403

        return view(*args, **kwargs)

    return wrapper


def enforce_data_access():
    """Used as a before_request hook on the products and analytics blueprints."""
    if (
        REQUIRE_LOGIN_FOR_DATA
        and request.method != "OPTIONS"
        and load_session() is None
    ):
        return jsonify({"error": "Authentication required"}), 401

    return None