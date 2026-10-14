from flask import Blueprint, g, jsonify, request

from app.database.connection import create_connection
from app.extensions import limiter
from app.security.sessions import login_required

preferences_bp = Blueprint("preferences", __name__)


@preferences_bp.route("/account/preferences", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_preferences():
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT alerts_email FROM users WHERE id = %s", (g.session["id"],)
        )
        row = cursor.fetchone() or {}
    finally:
        connection.close()

    return jsonify({"email_alerts": bool(row.get("alerts_email"))})


@preferences_bp.route("/account/preferences", methods=["PUT"])
@limiter.limit("30 per hour")
@login_required
def update_preferences():
    payload = request.get_json(silent=True) or {}
    value = payload.get("email_alerts")

    if not isinstance(value, bool):
        return jsonify({"error": "email_alerts must be true or false."}), 400

    connection = create_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE users SET alerts_email = %s WHERE id = %s",
            (1 if value else 0, g.session["id"]),
        )
        connection.commit()
    finally:
        connection.close()

    return jsonify({"email_alerts": value})