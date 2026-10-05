from flask import Blueprint, g, jsonify

from app.database import watchlist_repository as repo
from app.database.repositories import get_product_by_id
from app.extensions import limiter
from app.security.plans import effective_plan, limits_for
from app.security.sessions import login_required

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/watchlist", methods=["GET"])
@login_required
def get_watchlist():
    products = repo.get_watchlist_products(g.session["id"])

    return jsonify({"products": products, "count": len(products)})


@watchlist_bp.route("/watchlist/ids", methods=["GET"])
@login_required
def get_watchlist_ids():
    return jsonify({"ids": repo.get_watchlist_ids(g.session["id"])})


@watchlist_bp.route("/watchlist/<int:product_id>", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
def add_to_watchlist(product_id):
    if get_product_by_id(product_id) is None:
        return jsonify({"error": "Product not found"}), 404

    user_id = g.session["id"]
    ids = repo.get_watchlist_ids(user_id)

    if product_id not in ids:
        limit = limits_for(g.session)["watchlist_max"]

        if len(ids) >= limit:
            plan = effective_plan(g.session)

            message = (
                f"Your free plan allows up to {limit} products on the watchlist. "
                "Upgrade to Pro to follow more."
                if plan == "free"
                else f"Your watchlist is full ({limit} products)."
            )

            return jsonify({
                "error": message,
                "code": "watchlist_limit",
                "limit": limit,
            }), 403

        repo.add_to_watchlist(user_id, product_id)

    return jsonify({"watching": True})


@watchlist_bp.route("/watchlist/<int:product_id>", methods=["DELETE"])
@limiter.limit("60 per minute")
@login_required
def remove_from_watchlist(product_id):
    repo.remove_from_watchlist(g.session["id"], product_id)

    return jsonify({"watching": False})