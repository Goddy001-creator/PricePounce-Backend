import csv
import io

from flask import Blueprint, Response, g, jsonify

from app.database import watchlist_repository as repo
from app.database.repositories import create_connection, get_product_by_id
from app.extensions import limiter
from app.security.plans import effective_plan
from app.security.sessions import login_required

pro_bp = Blueprint("pro", __name__)

FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _pro_only():
    if effective_plan(g.session) != "pro":
        return jsonify({
            "error": "This is a Pro feature.",
            "code": "pro_required",
        }), 403

    return None


def _safe_cell(value):
    # Stops spreadsheet programs treating a product name as a formula
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_CHARS) else text


@pro_bp.route("/products/<int:product_id>/insights", methods=["GET"])
@limiter.limit("120 per minute")
@login_required
def product_insights(product_id):
    blocked = _pro_only()
    if blocked:
        return blocked

    product = get_product_by_id(product_id)

    if product is None:
        return jsonify({"error": "Product not found"}), 404

    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT MIN(price) AS lowest, MAX(price) AS highest,
                   AVG(price) AS average, COUNT(*) AS points,
                   MIN(checked_at) AS first_seen
            FROM price_history WHERE product_id = %s
            """,
            (product_id,),
        )
        stats = cursor.fetchone()

        cursor.execute(
            "SELECT price FROM price_history WHERE product_id = %s "
            "ORDER BY checked_at DESC LIMIT 1",
            (product_id,),
        )
        latest = cursor.fetchone()

        low_date = None

        if stats["lowest"] is not None:
            cursor.execute(
                "SELECT checked_at FROM price_history "
                "WHERE product_id = %s AND price = %s "
                "ORDER BY checked_at DESC LIMIT 1",
                (product_id, stats["lowest"]),
            )
            low_row = cursor.fetchone()
            low_date = low_row["checked_at"] if low_row else None
    finally:
        connection.close()

    points = int(stats["points"] or 0)

    if points < 2:
        return jsonify({"verdict": "not_enough_data", "points": points})

    current = float(latest["price"]) if latest else float(product["current_price"])
    lowest = float(stats["lowest"])
    highest = float(stats["highest"])
    average = float(stats["average"])

    if current <= lowest:
        verdict = "all_time_low"
    elif current <= lowest * 1.03:
        verdict = "near_low"
    elif points >= 3 and current <= average * 0.90:
        verdict = "good_deal"
    elif points >= 3 and current >= average * 1.10:
        verdict = "pricey"
    else:
        verdict = "fair"

    return jsonify({
        "verdict": verdict,
        "points": points,
        "current": current,
        "lowest": lowest,
        "lowest_date": low_date,
        "highest": highest,
        "average": round(average, 2),
        "tracked_since": stats["first_seen"],
    })


@pro_bp.route("/watchlist/export.csv", methods=["GET"])
@limiter.limit("10 per hour")
@login_required
def export_watchlist():
    blocked = _pro_only()
    if blocked:
        return blocked

    products = repo.get_watchlist_products(g.session["id"])

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow([
        "Product", "Store", "Current price", "Original price",
        "Discount %", "Rating", "Target price", "Link", "Added on",
    ])

    for item in products:
        writer.writerow([
            _safe_cell(item["product_name"]),
            _safe_cell(item["store_name"]),
            item["current_price"],
            item["old_price"] if item["old_price"] is not None else "",
            item["discount_percent"] if item["discount_percent"] is not None else "",
            item["rating"] if item["rating"] is not None else "",
            item.get("target_price") or "",
            _safe_cell(item["product_url"]),
            item["added_at"],
        ])

    # The leading mark makes Excel read the file as UTF-8
    body = "\ufeff" + buffer.getvalue()

    return Response(
        body,
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="pricepounce-watchlist.csv"',
        },
    )