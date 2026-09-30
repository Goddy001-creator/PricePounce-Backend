from flask import Blueprint, jsonify, request

from app.database.repositories import (
    get_all_products,
    get_last_update,
    get_price_drops,
    get_price_trends,
    get_product_ratings,
    get_products_by_store,
    get_store_summaries,
    get_top_discounted_products,
)
from app.processing.preprocessing import preprocess_products
from app.processing.statistics import product_statistics


analytics_bp = Blueprint(
    "analytics",
    __name__
)


@analytics_bp.route(
    "/analytics/summary",
    methods=["GET"]
)
def summary():
    products = get_all_products()

    processed = preprocess_products(
        products
    )

    return jsonify(
        product_statistics(
            processed
        )
    )


@analytics_bp.route(
    "/analytics/top-discounts",
    methods=["GET"]
)
def top_discounts():
    limit = request.args.get(
        "limit",
        default=5,
        type=int
    )

    if limit < 1 or limit > 50:
        return jsonify({
            "error": "Limit must be between 1 and 50"
        }), 400

    products = get_top_discounted_products(
        limit
    )

    return jsonify({
        "products": products,
        "count": len(products)
    })


@analytics_bp.route(
    "/analytics/ratings",
    methods=["GET"]
)
def ratings():
    ratings = get_product_ratings()

    processed = preprocess_products(
        ratings
    )

    return jsonify({
        "ratings": processed,
        "count": len(processed)
    })


@analytics_bp.route(
    "/analytics/stores/<store_name>",
    methods=["GET"]
)
def store_products(store_name):
    products = get_products_by_store(
        store_name
    )

    return jsonify({
        "store": store_name,
        "products": products,
        "count": len(products)
    })


@analytics_bp.route("/analytics/price-drops", methods=["GET"])
def price_drops():
    limit = request.args.get("limit", default=20, type=int)

    if limit < 1 or limit > 100:
        return jsonify({"error": "Limit must be between 1 and 100"}), 400

    drops = get_price_drops(limit)

    return jsonify({"drops": drops, "count": len(drops)})


@analytics_bp.route("/analytics/stores", methods=["GET"])
def store_summaries():
    stores = get_store_summaries()

    return jsonify({"stores": stores, "count": len(stores)})


@analytics_bp.route("/analytics/last-update", methods=["GET"])
def last_update():
    return jsonify(get_last_update())


@analytics_bp.route("/analytics/price-trends", methods=["GET"])
def price_trends():
    days = request.args.get("days", default=7, type=int)

    if days < 1 or days > 30:
        return jsonify({"error": "Days must be between 1 and 30"}), 400

    trends = get_price_trends(days)

    return jsonify({"trends": trends, "count": len(trends)})