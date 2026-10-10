from flask import Blueprint, g, jsonify, request

from app.database.repositories import create_connection
from app.extensions import limiter
from app.security.plans import effective_plan
from app.security.sessions import login_required

alerts_bp = Blueprint("alerts", __name__)


@alerts_bp.route("/watchlist/<int:product_id>/target", methods=["PUT"])
@limiter.limit("60 per hour")
@login_required
def set_target(product_id):
    from app.database.auth_repository import get_user_by_id

    user = get_user_by_id(g.session["id"])

    if effective_plan(user) != "pro":
        return jsonify({"error": "Target-price alerts are a Pro feature.",
                        "code": "pro_required"}), 403

    raw = (request.get_json(silent=True) or {}).get("target_price")

    try:
        target = None if raw in (None, "") else round(float(raw), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Enter a valid price."}), 400

    if target is not None and not (0 < target < 100_000_000):
        return jsonify({"error": "Enter a valid price."}), 400

    connection = create_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE watchlist SET target_price = %s, last_alerted_price = NULL "
            "WHERE user_id = %s AND product_id = %s",
            (target, user["id"], product_id),
        )
        connection.commit()
        found = cursor.rowcount > 0
    finally:
        connection.close()

    if not found:
        return jsonify({"error": "Product is not on your watchlist."}), 404

    return jsonify({"target_price": target})


@alerts_bp.route("/alerts/unsubscribe", methods=["GET"])
@limiter.limit("20 per hour")
def unsubscribe():
    token = request.args.get("token", "")

    if 20 <= len(token) <= 64:
        connection = create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE users SET alerts_email = 0 WHERE alert_token = %s", (token,)
            )
            connection.commit()
        finally:
            connection.close()

    return (
        "<p style='font-family:sans-serif;padding:40px'>"
        "You're unsubscribed from price alert emails. "
        "You can turn them back on in Settings.</p>"
    )