import logging

from flask import Blueprint, g, jsonify, request

from app.database.connection import create_connection
from app.extensions import limiter
from app.security.passwords import verify_password
from app.security.sessions import login_required
from app.services.billing_service import cancel_subscription

logger = logging.getLogger(__name__)

account_delete_bp = Blueprint("account_delete", __name__)

MAX_PASSWORD_LENGTH = 1024


@account_delete_bp.route("/account/delete", methods=["POST"])
@limiter.limit("5 per hour")
@login_required
def delete_account():
    payload = request.get_json(silent=True) or {}
    password = payload.get("password")

    if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD_LENGTH:
        return jsonify({"error": "Enter your password to confirm."}), 400

    user_id = g.session["id"]
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT password_hash, role FROM users WHERE id = %s", (user_id,)
        )
        user = cursor.fetchone()

        if user is None:
            return jsonify({"error": "Account not found."}), 404

        if user["role"] == "admin":
            return jsonify({"error": "Admin accounts can't be deleted here."}), 403

        if not verify_password(password, user["password_hash"]):
            return jsonify({"error": "That password is not correct."}), 403

        # Stop Paystack from charging a deleted account.
        cursor.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = %s AND status = 'active'",
            (user_id,),
        )
        has_active_subscription = cursor.fetchone() is not None
    finally:
        connection.close()

    if has_active_subscription:
        try:
            cancel_subscription(user_id)
        except Exception:
            logger.exception("Could not cancel subscription for user %s", user_id)
            return jsonify({
                "error": "We couldn't cancel your subscription, so your account was "
                         "not deleted. Please try again or contact support."
            }), 502

    connection = create_connection()

    try:
        cursor = connection.cursor()

        # Remove personal traces from the security log.
        cursor.execute(
            "UPDATE audit_log SET actor_user_id = NULL, ip = NULL, "
            "user_agent = NULL, details = NULL WHERE actor_user_id = %s",
            (user_id,),
        )
        cursor.execute(
            "UPDATE audit_log SET target_user_id = NULL, details = NULL "
            "WHERE target_user_id = %s",
            (user_id,),
        )
        cursor.execute(
            "UPDATE users SET plan_granted_by = NULL WHERE plan_granted_by = %s",
            (user_id,),
        )
        cursor.execute("DELETE FROM subscriptions WHERE user_id = %s", (user_id,))

        # sessions, auth_tokens, watchlist and recovery_codes cascade.
        # payments rows stay: they hold only a user id, no name or email.
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        logger.exception("Account deletion failed for user %s", user_id)
        return jsonify({"error": "Could not delete your account. Please try again."}), 500
    finally:
        connection.close()

    return jsonify({"deleted": True})