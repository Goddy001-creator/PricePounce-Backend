from flask import Blueprint, jsonify

from app.database.connection import create_connection
from app.extensions import limiter

preview_bp = Blueprint("preview", __name__)

FIELDS = (
    "id", "product_name", "store_name", "image_url",
    "current_price", "old_price", "discount_percent", "rating",
)
NUMERIC = ("current_price", "old_price", "discount_percent", "rating")


@preview_bp.route("/preview/recent", methods=["GET"])
@limiter.limit("60 per minute")
def recent_preview():
    """The five newest products, for the logged-out dashboard. Nothing else."""
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM products ORDER BY id DESC LIMIT 5")
        rows = cursor.fetchall()
    finally:
        connection.close()

    products = []

    for row in rows:
        item = {key: row.get(key) for key in FIELDS}

        for key in NUMERIC:
            if item[key] is not None:
                item[key] = float(item[key])

        products.append(item)

    return jsonify({"products": products, "count": len(products)})