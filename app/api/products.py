import math
from datetime import timedelta

from flask import Blueprint, jsonify, request

from app.database.repositories import (
    SORT_COLUMNS,
    get_all_products,
    get_price_history,
    get_product_by_id,
    get_products_page,
    search_products,
)
from app.security.plans import PLAN_LIMITS, limits_for
from app.security.sessions import optional_session, utcnow


products_bp = Blueprint("products", __name__)


@products_bp.route("/products", methods=["GET"])
def products():
    page = request.args.get("page", type=int)

    # No page parameter: return everything, as before
    if page is None:
        products = get_all_products()

        return jsonify({
            "products": products,
            "count": len(products)
        })

    per_page = request.args.get("per_page", default=10, type=int)
    sort = request.args.get("sort", default="updated")
    order = request.args.get("order", default="desc").lower()
    search = request.args.get("q", default="").strip() or None
    store = request.args.get("store", default="").strip() or None
    category = request.args.get("category", default="").strip().lower() or None
    brand = request.args.get("brand", default="").strip() or None

    if page < 1:
        return jsonify({"error": "Page must be 1 or higher"}), 400

    if per_page < 1 or per_page > 100:
        return jsonify({"error": "per_page must be between 1 and 100"}), 400

    if sort not in SORT_COLUMNS:
        return jsonify({
            "error": f"sort must be one of: {', '.join(SORT_COLUMNS)}"
        }), 400

    if order not in ("asc", "desc"):
        return jsonify({"error": "order must be asc or desc"}), 400

    if (category and len(category) > 120) or (brand and len(brand) > 100):
        return jsonify({"error": "Invalid filter"}), 400

    items, total = get_products_page(
        page=page,
        per_page=per_page,
        search=search,
        store=store,
        sort=sort,
        order=order,
        category=category,
        brand=brand,
    )

    return jsonify({
        "products": items,
        "count": len(items),
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, math.ceil(total / per_page)),
    })


@products_bp.route("/products/<int:product_id>", methods=["GET"])
def product(product_id):
    product = get_product_by_id(product_id)

    if product is None:
        return jsonify({
            "error": "Product not found"
        }), 404

    return jsonify(product)


@products_bp.route("/products/<int:product_id>/history", methods=["GET"])
def product_history(product_id):
    product = get_product_by_id(product_id)

    if product is None:
        return jsonify({
            "error": "Product not found"
        }), 404

    session = optional_session()
    limits = limits_for(session) if session else PLAN_LIMITS["free"]
    days = limits["history_days"]

    history = get_price_history(product_id)
    limited = False

    if days is not None:
        cutoff = utcnow() - timedelta(days=days)
        recent = [row for row in history if row["checked_at"] >= cutoff]
        older = [row for row in history if row["checked_at"] < cutoff]

        # Keep the price that was in effect at the start of the window
        if older:
            recent.insert(0, older[-1])

        limited = len(older) > 1
        history = recent

    return jsonify({
        "product_id": product_id,
        "history": history,
        "history_days": days,
        "history_limited": limited,
    })


@products_bp.route("/products/search", methods=["GET"])
def product_search():
    keyword = request.args.get("q", "").strip()

    if not keyword:
        return jsonify({
            "error": "Search query is required"
        }), 400

    products = search_products(keyword)

    return jsonify({
        "products": products,
        "count": len(products),
        "query": keyword
    })