from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from app.config.settings import REQUIRE_EMAIL_VERIFICATION
from app.database import auth_repository as repo
from app.extensions import limiter
from app.security.audit import audit
from app.security.passwords import (
    MAX_LENGTH,
    hash_password,
    needs_rehash,
    validate_password,
    verify_dummy,
    verify_password,
)
from app.security.plans import effective_plan, limits_for
from app.security.sessions import (
    clear_session_cookie,
    create_session,
    hash_token,
    login_required,
    new_token,
    set_session_cookie,
    utcnow,
)
from app.security.totp import (
    decrypt_secret,
    encrypt_secret,
    hash_recovery_code,
    new_recovery_codes,
    new_secret,
    normalize_recovery_code,
    provisioning_uri,
    verify_code,
)
from app.security.validators import clean_name, normalize_email
from app.services import email_service

auth_bp = Blueprint("auth", __name__)

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
VERIFY_HOURS = 24
RESET_MINUTES = 60
MFA_MINUTES = 5
AUTO_REFRESH_OPTIONS = (15, 30, 60)

GENERIC_LOGIN_ERROR = (
    "Incorrect email or password, or the account is temporarily locked."
)
MFA_ERROR = "That code is not correct, or the account is temporarily locked."
NAME_ERROR = "Enter your name (2 to 60 characters)."
EMAIL_ERROR = "Enter a valid email address."
LINK_ERROR = "This link is invalid or has expired."


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def error(message, status=400, **extra):
    return jsonify({"error": message, **extra}), status


def iso(value):
    return value.isoformat() + "Z" if value else None


def public_user(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "email_verified": bool(row["email_verified"]),
        "role": row["role"],
        "plan": effective_plan(row),
        "plan_expires_at": iso(row["plan_expires_at"]),
        "limits": limits_for(row),
        "totp_enabled": bool(row["totp_enabled"]),
        "settings": {
            "theme": row["theme"],
            "auto_refresh_minutes": row["auto_refresh_minutes"],
            "default_store": row["default_store"],
        },
    }


def issue_token(user_id, purpose, ttl):
    token = new_token()
    now = utcnow()
    repo.create_token(user_id, hash_token(token), purpose, now + ttl, now)
    return token


def is_locked(user, now):
    return bool(user["locked_until"] and user["locked_until"] > now)


def finish_login(user, mfa_verified):
    repo.reset_failed_logins(user["id"])
    repo.touch_last_login(user["id"])
    repo.delete_expired_sessions()

    token, csrf_token = create_session(user["id"], mfa_verified)

    audit(
        "login_success",
        actor_user_id=user["id"],
        target_user_id=user["id"],
        mfa=mfa_verified,
    )

    response = jsonify({
        "user": public_user(user),
        "csrf_token": csrf_token,
    })

    set_session_cookie(response, token)
    return response


def verify_second_factor(user, raw_code):
    """True if the authenticator code or a recovery code is valid.

    A code that is accepted is consumed so it can't be used again.
    """
    raw = str(raw_code or "").strip().replace(" ", "")

    if raw.isdigit() and len(raw) == 6:
        secret = (
            decrypt_secret(user["totp_secret"]) if user["totp_secret"] else None
        )

        if not secret:
            return False

        step = verify_code(secret, raw, user["totp_last_step"])

        return step is not None and repo.update_totp_step(user["id"], step)

    if len(normalize_recovery_code(raw)) == 12:
        used = repo.consume_recovery_code(
            user["id"], hash_recovery_code(raw), utcnow()
        )

        if used:
            audit(
                "recovery_code_used",
                actor_user_id=user["id"],
                target_user_id=user["id"],
            )

        return used

    return False


# ---------------------------------------------------------------- signup

@auth_bp.route("/auth/signup", methods=["POST"])
@limiter.limit("10 per hour")
def signup():
    data = json_body()
    name = clean_name(data.get("name"))
    email = normalize_email(data.get("email"))
    password = str(data.get("password") or "")

    fields = {}

    if name is None:
        fields["name"] = NAME_ERROR

    if email is None:
        fields["email"] = EMAIL_ERROR

    password_errors = validate_password(password, email or "")

    if password_errors:
        fields["password"] = password_errors[0]

    if fields:
        return error("Please fix the highlighted fields.", 400, fields=fields)

    # Hash before looking the email up so both paths take the same time
    password_hash = hash_password(password)
    existing = repo.get_user_by_email(email)

    if existing:
        email_service.send_account_exists_email(existing["name"], email)
    else:
        user_id = repo.create_user(
            name, email, password_hash, not REQUIRE_EMAIL_VERIFICATION
        )

        if user_id and REQUIRE_EMAIL_VERIFICATION:
            token = issue_token(
                user_id, "verify_email", timedelta(hours=VERIFY_HOURS)
            )
            email_service.send_verification_email(name, email, token)

    message = (
        "Account created. Check your email to verify your address."
        if REQUIRE_EMAIL_VERIFICATION
        else "Account created. You can log in now."
    )

    return jsonify({"message": message}), 201


# ----------------------------------------------------------------- login

@auth_bp.route("/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = json_body()
    email = normalize_email(data.get("email"))
    password = str(data.get("password") or "")

    if len(password) > MAX_LENGTH:
        password = ""

    user = repo.get_user_by_email(email) if email else None
    now = utcnow()

    if user is None or is_locked(user, now):
        verify_dummy(password)
        return error(GENERIC_LOGIN_ERROR, 401)

    if not verify_password(password, user["password_hash"]):
        repo.register_failed_login(
            user["id"],
            MAX_FAILED_LOGINS,
            now + timedelta(minutes=LOCK_MINUTES),
        )
        audit("login_failed", target_user_id=user["id"])
        return error(GENERIC_LOGIN_ERROR, 401)

    if user["status"] != "active":
        audit("login_blocked_suspended", target_user_id=user["id"])
        return error(
            "This account has been suspended. Please contact support.",
            403,
            code="account_suspended",
        )

    if REQUIRE_EMAIL_VERIFICATION and not user["email_verified"]:
        return error(
            "Please verify your email address before logging in.",
            403,
            code="email_not_verified",
        )

    if needs_rehash(user["password_hash"]):
        repo.set_password(user["id"], hash_password(password))

    if user["totp_enabled"]:
        token = issue_token(
            user["id"], "mfa_login", timedelta(minutes=MFA_MINUTES)
        )

        return jsonify({"mfa_required": True, "mfa_token": token})

    return finish_login(user, mfa_verified=False)


@auth_bp.route("/auth/login/2fa", methods=["POST"])
@limiter.limit("10 per minute")
def login_two_factor():
    data = json_body()
    token = str(data.get("mfa_token") or "")
    code = str(data.get("code") or "")

    token_hash = hash_token(token)
    found = (
        repo.find_token_user(token_hash, "mfa_login", utcnow()) if token else None
    )

    if not found:
        return error(
            "Your login session expired. Please log in again.",
            401,
            code="mfa_expired",
        )

    user = repo.get_user_by_id(found["id"])
    now = utcnow()

    if (
        user is None
        or user["status"] != "active"
        or not user["totp_enabled"]
        or is_locked(user, now)
    ):
        return error(MFA_ERROR, 401)

    if not verify_second_factor(user, code):
        repo.register_failed_login(
            user["id"],
            MAX_FAILED_LOGINS,
            now + timedelta(minutes=LOCK_MINUTES),
        )
        audit("mfa_failed", target_user_id=user["id"])
        return error(MFA_ERROR, 401)

    repo.consume_token(token_hash, "mfa_login", now)

    return finish_login(user, mfa_verified=True)


@auth_bp.route("/auth/me", methods=["GET"])
@login_required
def me():
    return jsonify({
        "user": public_user(g.session),
        "csrf_token": g.session["csrf_token"],
    })


@auth_bp.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    audit("logout", actor_user_id=g.session["id"])

    repo.delete_session(g.session["token_hash"])

    response = jsonify({"message": "Logged out"})
    clear_session_cookie(response)
    return response


# ------------------------------------------------- email verification

@auth_bp.route("/auth/verify-email", methods=["POST"])
@limiter.limit("10 per minute")
def verify_email():
    token = str(json_body().get("token") or "")

    user_id = (
        repo.consume_token(hash_token(token), "verify_email", utcnow())
        if token
        else None
    )

    if not user_id:
        return error(LINK_ERROR, 400)

    repo.mark_email_verified(user_id)

    return jsonify({"message": "Email verified. You can now log in."})


@auth_bp.route("/auth/resend-verification", methods=["POST"])
@limiter.limit("3 per hour")
def resend_verification():
    email = normalize_email(json_body().get("email"))
    user = repo.get_user_by_email(email) if email else None

    if user and not user["email_verified"]:
        token = issue_token(
            user["id"], "verify_email", timedelta(hours=VERIFY_HOURS)
        )
        email_service.send_verification_email(user["name"], user["email"], token)

    return jsonify({
        "message": "If that account needs verification, we've sent a new link."
    })


# ---------------------------------------------------- password reset

@auth_bp.route("/auth/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    email = normalize_email(json_body().get("email"))
    user = repo.get_user_by_email(email) if email else None

    if user:
        token = issue_token(
            user["id"], "reset_password", timedelta(minutes=RESET_MINUTES)
        )
        email_service.send_reset_email(user["name"], user["email"], token)

    return jsonify({
        "message": "If an account exists for that email, we've sent a reset link."
    })


@auth_bp.route("/auth/reset-password", methods=["POST"])
@limiter.limit("10 per hour")
def reset_password():
    data = json_body()
    token = str(data.get("token") or "")
    password = str(data.get("password") or "")

    token_hash = hash_token(token)
    user = (
        repo.find_token_user(token_hash, "reset_password", utcnow())
        if token
        else None
    )

    if not user:
        return error(LINK_ERROR, 400)

    password_errors = validate_password(password, user["email"])

    if password_errors:
        return error(
            "Please choose a stronger password.",
            400,
            fields={"password": password_errors[0]},
        )

    if not repo.consume_token(token_hash, "reset_password", utcnow()):
        return error(LINK_ERROR, 400)

    repo.set_password(user["id"], hash_password(password))
    repo.reset_failed_logins(user["id"])
    repo.mark_email_verified(user["id"])
    repo.delete_user_sessions(user["id"])

    audit(
        "password_reset",
        actor_user_id=user["id"],
        target_user_id=user["id"],
    )

    return jsonify({"message": "Password updated. You can now log in."})


# ------------------------------------------------------------ account

@auth_bp.route("/account/profile", methods=["PATCH"])
@login_required
def update_profile():
    name = clean_name(json_body().get("name"))

    if name is None:
        return error(NAME_ERROR, 400, fields={"name": NAME_ERROR})

    repo.update_name(g.session["id"], name)

    return jsonify({"user": public_user(repo.get_user_by_id(g.session["id"]))})


@auth_bp.route("/account/settings", methods=["PATCH"])
@login_required
def update_settings():
    data = json_body()
    updates = {}

    if "theme" in data:
        if data["theme"] not in ("light", "dark"):
            return error("Invalid theme.")
        updates["theme"] = data["theme"]

    if "auto_refresh_minutes" in data:
        value = data["auto_refresh_minutes"]
        if isinstance(value, bool) or value not in AUTO_REFRESH_OPTIONS:
            return error("Invalid auto refresh value.")
        updates["auto_refresh_minutes"] = value

    if "default_store" in data:
        store = data["default_store"]
        if not isinstance(store, str) or not 1 <= len(store) <= 50:
            return error("Invalid default store.")
        updates["default_store"] = store

    if not updates:
        return error("No settings to update.")

    repo.update_settings(g.session["id"], updates)

    return jsonify({"user": public_user(repo.get_user_by_id(g.session["id"]))})


@auth_bp.route("/account/change-password", methods=["POST"])
@limiter.limit("5 per 10 minutes")
@login_required
def change_password():
    data = json_body()
    current = str(data.get("current_password") or "")
    new_password = str(data.get("new_password") or "")

    user = repo.get_user_by_id(g.session["id"])

    if len(current) > MAX_LENGTH or not verify_password(
        current, user["password_hash"]
    ):
        message = "Your current password is incorrect."
        return error(message, 400, fields={"current_password": message})

    errors = validate_password(new_password, user["email"])

    if new_password == current:
        errors = ["Choose a password different from the current one."]

    if errors:
        return error(
            "Please choose a stronger password.",
            400,
            fields={"new_password": errors[0]},
        )

    repo.set_password(user["id"], hash_password(new_password))
    repo.delete_other_sessions(user["id"], g.session["token_hash"])

    audit(
        "password_changed",
        actor_user_id=user["id"],
        target_user_id=user["id"],
    )

    return jsonify({
        "message": "Password changed. Your other devices were logged out."
    })


# ------------------------------------------- two-factor authentication

@auth_bp.route("/security/2fa/setup", methods=["POST"])
@limiter.limit("10 per hour")
@login_required
def two_factor_setup():
    user = repo.get_user_by_id(g.session["id"])

    if user["totp_enabled"]:
        return error("Two-factor authentication is already enabled.")

    secret = new_secret()
    repo.save_pending_totp(user["id"], encrypt_secret(secret))

    return jsonify({
        "secret": secret,
        "otpauth_uri": provisioning_uri(secret, user["email"]),
    })


@auth_bp.route("/security/2fa/enable", methods=["POST"])
@limiter.limit("10 per 10 minutes")
@login_required
def two_factor_enable():
    user = repo.get_user_by_id(g.session["id"])
    code = str(json_body().get("code") or "")

    if user["totp_enabled"]:
        return error("Two-factor authentication is already enabled.")

    if not user["totp_secret"]:
        return error("Start the setup first.")

    secret = decrypt_secret(user["totp_secret"])
    step = verify_code(secret, code, None) if secret else None

    if step is None:
        return error(
            "That code is not correct. Check your authenticator app and try again."
        )

    codes = new_recovery_codes()

    repo.enable_totp(user["id"], step, [hash_recovery_code(c) for c in codes])
    repo.set_session_mfa_verified(g.session["token_hash"])
    repo.delete_other_sessions(user["id"], g.session["token_hash"])

    audit(
        "2fa_enabled",
        actor_user_id=user["id"],
        target_user_id=user["id"],
    )

    return jsonify({
        "recovery_codes": codes,
        "user": public_user(repo.get_user_by_id(user["id"])),
    })


@auth_bp.route("/security/2fa/disable", methods=["POST"])
@limiter.limit("5 per 10 minutes")
@login_required
def two_factor_disable():
    data = json_body()
    password = str(data.get("password") or "")
    code = str(data.get("code") or "")

    user = repo.get_user_by_id(g.session["id"])

    if user["role"] == "admin":
        return error(
            "Admin accounts must keep two-factor authentication enabled.", 403
        )

    if not user["totp_enabled"]:
        return error("Two-factor authentication is not enabled.")

    if len(password) > MAX_LENGTH or not verify_password(
        password, user["password_hash"]
    ):
        return error("Your password is incorrect.")

    if not verify_second_factor(user, code):
        return error("That code is not correct.")

    repo.disable_totp(user["id"])
    repo.delete_other_sessions(user["id"], g.session["token_hash"])

    audit(
        "2fa_disabled",
        actor_user_id=user["id"],
        target_user_id=user["id"],
    )

    return jsonify({"user": public_user(repo.get_user_by_id(user["id"]))})


@auth_bp.route("/security/2fa/recovery-codes", methods=["POST"])
@limiter.limit("5 per 10 minutes")
@login_required
def two_factor_recovery_codes():
    user = repo.get_user_by_id(g.session["id"])
    code = str(json_body().get("code") or "")

    if not user["totp_enabled"]:
        return error("Two-factor authentication is not enabled.")

    if not verify_second_factor(user, code):
        return error("That code is not correct.")

    codes = new_recovery_codes()
    repo.replace_recovery_codes(user["id"], [hash_recovery_code(c) for c in codes])

    audit(
        "recovery_codes_regenerated",
        actor_user_id=user["id"],
        target_user_id=user["id"],
    )

    return jsonify({"recovery_codes": codes})