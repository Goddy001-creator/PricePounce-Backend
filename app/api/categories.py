from flask import Blueprint, jsonify, request

from app.database.repositories import create_connection
from app.extensions import limiter

categories_bp = Blueprint("categories", __name__)


@categories_bp.route("/categories", methods=["GET"])
@limiter.limit("120 per minute")
def list_categories():
    connection = create_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.id, c.name, c.slug, c.parent_id,
                   COUNT(p.id) AS product_count
            FROM categories c
            LEFT JOIN products p ON p.category_id = c.id
            GROUP BY c.id, c.name, c.slug, c.parent_id
            ORDER BY c.name
        """)
        rows = cursor.fetchall()
    finally:
        connection.close()

    parents = {r["id"]: {**r, "children": []} for r in rows if r["parent_id"] is None}

    for r in rows:
        if r["parent_id"] in parents:
            parents[r["parent_id"]]["children"].append(r)
            parents[r["parent_id"]]["product_count"] += r["product_count"]

    return jsonify({"categories": sorted(parents.values(), key=lambda c: c["name"] == "Other")})


@categories_bp.route("/brands", methods=["GET"])
@limiter.limit("120 per minute")
def list_brands():
    slug = request.args.get("category", "").strip().lower()

    sql = """
        SELECT p.brand, COUNT(*) AS product_count
        FROM products p
        {join}
        WHERE p.brand IS NOT NULL AND p.brand <> ''
        {where}
        GROUP BY p.brand
        ORDER BY product_count DESC, p.brand
        LIMIT 100
    """
    params = ()
    join = where = ""

    if slug:
        join = "JOIN categories c ON c.id = p.category_id LEFT JOIN categories parent ON parent.id = c.parent_id"
        where = "AND (c.slug = %s OR parent.slug = %s)"
        params = (slug, slug)

    connection = create_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql.format(join=join, where=where), params)
        brands = cursor.fetchall()
    finally:
        connection.close()

    return jsonify({"brands": brands})