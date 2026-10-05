import math
from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from app.database import admin_repository as admin_repo
from app.database import auth_repository as repo
from app.extensions import limiter
from app.security.audit import audit
from app.security.plans import effective_plan
from app.security.sessions import admin_required, utcnow

admin_bp = Blueprint("admin", __name__)

MAX_PRO_DAYS = 3650


def iso(value):
    return value.isoformat() + "Z" if value else None


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def error(message, status=400):
    return jsonify({"error": message}), status


def paging(default_per_page=20):
    page = max(1, request.args.get("page", default=1, type=int))
    per_page = min(
        100,
        max(1, request.args.get("per_page", default=default_per_page, type=int)),
    )
    return page, per_page


def admin_user(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "email_verified": bool(row["email_verified"]),
        "role": row["role"],
        "status": row["status"],
        "plan": effective_plan(row),
        "plan_expires_at": iso(row.get("plan_expires_at")),
        "totp_enabled": bool(row["totp_enabled"]),
        "last_login_at": iso(row.get("last_login_at")),
        "created_at": iso(row.get("created_at")),
    }


def admin_user_detail(row):
    data = admin_user(row)

    data.update({
        "plan_source": row["plan_source"],
        "granted_by_email": row["granted_by_email"],
        "failed_logins": row["failed_logins"],
        "locked": bool(row["locked_until"] and row["locked_until"] > utcnow()),
        "locked_until": iso(row["locked_until"]),
        "watchlist_count": row["watchlist_count"],
        "active_sessions": row["active_sessions"],
        "settings": {
            "theme": row["theme"],
            "auto_refresh_minutes": row["auto_refresh_minutes"],
            "default_store": row["default_store"],
        },
    })

    return data


def audit_row(row):
    return {
        "id": row["id"],
        "action": row["action"],
        "actor_user_id": row["actor_user_id"],
        "actor_email": row["actor_email"],
        "target_user_id": row["target_user_id"],
        "target_email": row["target_email"],
        "details": row["details"],
        "ip": row["ip"],
        "created_at": iso(row["created_at"]),
    }


def target_or_404(user_id):
    target = repo.get_user_by_id(user_id)

    if target is None:
        return None, error("User not found", 404)

    return target, None


def protect_target(target):
    """Admins can't act on themselves or on other admins in these actions."""
    if target["id"] == g.session["id"]:
        return error("You can't do this to your own account.")

    if target["role"] == "admin":
        return error(
            "This action isn't allowed on admin accounts. Roles are managed in the database."
        )

    return None


# ------------------------------------------------------------- overview

@admin_bp.route("/admin/ping", methods=["GET"])
@admin_required
def ping():
    return jsonify({"ok": True, "admin": g.session["email"]})


@admin_bp.route("/admin/stats", methods=["GET"])
@admin_required
def stats():
    return jsonify(admin_repo.get_stats())


# ---------------------------------------------------------------- users

@admin_bp.route("/admin/users", methods=["GET"])
@admin_required
def list_users():
    page, per_page = paging()

    search = (request.args.get("q") or "").strip()[:100] or None
    role = request.args.get("role", "")
    plan = request.args.get("plan", "")
    status = request.args.get("status", "")
    sort = request.args.get("sort", "created")
    order = request.args.get("order", "desc").lower()

    if sort not in admin_repo.SORT_COLUMNS:
        sort = "created"

    if order not in ("asc", "desc"):
        order = "desc"

    rows, total = admin_repo.list_users(
        page, per_page, search, role, plan, status, sort, order
    )

    return jsonify({
        "users": [admin_user(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, math.ceil(total / per_page)),
    })


@admin_bp.route("/admin/users/<int:user_id>", methods=["GET"])
@admin_required
def user_detail(user_id):
    row = admin_repo.get_user_detail(user_id)

    if row is None:
        return error("User not found", 404)

    activity = admin_repo.recent_audit_for_user(user_id)

    return jsonify({
        "user": admin_user_detail(row),
        "activity": [audit_row(item) for item in activity],
    })


@admin_bp.route("/admin/users/<int:user_id>/suspend", methods=["POST"])
@limiter.limit("60 per minute")
@admin_required
def suspend_user(user_id):
    target, failure = target_or_404(user_id)
    if failure:
        return failure

    blocked = protect_target(target)
    if blocked:
        return blocked

    admin_repo.set_status(user_id, "suspended")
    repo.delete_user_sessions(user_id)

    audit("admin_suspend_user", actor_user_id=g.session["id"], target_user_id=user_id)

    return jsonify({"message": "Account suspended and logged out everywhere."})


@admin_bp.route("/admin/users/<int:user_id>/unsuspend", methods=["POST"])
@limiter.limit("60 per minute")
@admin_required
def unsuspend_user(user_id):
    target, failure = target_or_404(user_id)
    if failure:
        return failure

    admin_repo.set_status(user_id, "active")

    audit("admin_unsuspend_user", actor_user_id=g.session["id"], target_user_id=user_id)

    return jsonify({"message": "Account reactivated."})


@admin_bp.route("/admin/users/<int:user_id>/force-logout", methods=["POST"])
@limiter.limit("60 per minute")
@admin_required
def force_logout(user_id):
    target, failure = target_or_404(user_id)
    if failure:
        return failure

    if target["id"] == g.session["id"]:
        return error("Use the Logout button to end your own session.")

    repo.delete_user_sessions(user_id)

    audit("admin_force_logout", actor_user_id=g.session["id"], target_user_id=user_id)

    return jsonify({"message": "All sessions for this user were ended."})


@admin_bp.route("/admin/users/<int:user_id>/unlock", methods=["POST"])
@limiter.limit("60 per minute")
@admin_required
def unlock_user(user_id):
    target, failure = target_or_404(user_id)
    if failure:
        return failure

    repo.reset_failed_logins(user_id)

    audit("admin_unlock_user", actor_user_id=g.session["id"], target_user_id=user_id)

    return jsonify({"message": "Failed-login lock cleared."})


@admin_bp.route("/admin/users/<int:user_id>/verify-email", methods=["POST"])
@limiter.limit("60 per minute")
@admin_required
def verify_user_email(user_id):
    target, failure = target_or_404(user_id)
    if failure:
        return failure

    repo.mark_email_verified(user_id)

    audit("admin_verify_email", actor_user_id=g.session["id"], target_user_id=user_id)

    return jsonify({"message": "Email marked as verified."})


@admin_bp.route("/admin/users/<int:user_id>/plan", methods=["POST"])
@limiter.limit("60 per minute")
@admin_required
def set_user_plan(user_id):
    target, failure = target_or_404(user_id)
    if failure:
        return failure

    data = json_body()
    plan = data.get("plan")

    if plan == "free":
        admin_repo.set_plan(user_id, "free", None, None, None)

        audit(
            "admin_revoke_pro",
            actor_user_id=g.session["id"],
            target_user_id=user_id,
            previous_plan=effective_plan(target),
        )

        return jsonify({"message": "Pro revoked. The account is on the Free plan."})

    if plan != "pro":
        return error("Plan must be 'pro' or 'free'.")

    now = utcnow()
    currently_pro = effective_plan(target) == "pro"
    lifetime = data.get("lifetime") is True

    if lifetime:
        expires = None
    else:
        days = data.get("days")

        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_PRO_DAYS:
            return error(f"Days must be a whole number from 1 to {MAX_PRO_DAYS}.")

        current_expiry = target["plan_expires_at"]

        if currently_pro and current_expiry is None:
            return error("This account already has lifetime Pro. Revoke it first to set an expiry.")

        base = current_expiry if currently_pro and current_expiry > now else now
        expires = base + timedelta(days=days)

    admin_repo.set_plan(user_id, "pro", expires, "manual", g.session["id"])

    audit(
        "admin_grant_pro",
        actor_user_id=g.session["id"],
        target_user_id=user_id,
        lifetime=lifetime,
        days=None if lifetime else days,
        expires=iso(expires),
    )

    return jsonify({
        "message": "Pro granted for life."
        if lifetime
        else f"Pro active until {expires.strftime('%d %b %Y')}."
    })


@admin_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@limiter.limit("20 per minute")
@admin_required
def delete_user(user_id):
    target, failure = target_or_404(user_id)
    if failure:
        return failure

    blocked = protect_target(target)
    if blocked:
        return blocked

    confirm = str(json_body().get("confirm_email") or "").strip().lower()

    if confirm != target["email"].lower():
        return error("Type the user's email exactly to confirm.")

    # Logged first so the email survives in the log after the account is gone
    audit(
        "admin_delete_user",
        actor_user_id=g.session["id"],
        target_user_id=user_id,
        email=target["email"],
    )

    admin_repo.delete_user(user_id)

    return jsonify({"message": "Account deleted."})


# ----------------------------------------------------------- audit log

@admin_bp.route("/admin/audit", methods=["GET"])
@admin_required
def audit_log():
    page, per_page = paging(30)

    action = (request.args.get("action") or "").strip()[:60] or None
    user_id = request.args.get("user_id", type=int)

    rows, total = admin_repo.list_audit(page, per_page, action, user_id)

    return jsonify({
        "entries": [audit_row(row) for row in rows],
        "actions": admin_repo.list_audit_actions(),
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, math.ceil(total / per_page)),
    })