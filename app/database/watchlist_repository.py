from app.database.auth_repository import db

MAX_WATCHLIST_ITEMS = 500

PRODUCT_COLUMNS = """
    p.id, p.product_name, p.store_name, p.product_url, p.image_url,
    p.current_price, p.old_price, p.discount_percent, p.rating,
    p.review_count, p.availability, p.last_checked
"""


def get_watchlist_ids(user_id):
    with db() as cursor:
        cursor.execute(
            """
            SELECT product_id FROM watchlist
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return [row["product_id"] for row in cursor.fetchall()]


def get_watchlist_products(user_id):
    with db() as cursor:
        cursor.execute(
            f"""
            SELECT {PRODUCT_COLUMNS}, w.created_at AS added_at, w.target_price
            FROM watchlist w
            JOIN products p ON p.id = w.product_id
            WHERE w.user_id = %s
            ORDER BY w.created_at DESC
            """,
            (user_id,),
        )
        return cursor.fetchall()


def add_to_watchlist(user_id, product_id):
    with db() as cursor:
        cursor.execute(
            "INSERT IGNORE INTO watchlist (user_id, product_id) VALUES (%s, %s)",
            (user_id, product_id),
        )


def remove_from_watchlist(user_id, product_id):
    with db() as cursor:
        cursor.execute(
            "DELETE FROM watchlist WHERE user_id = %s AND product_id = %s",
            (user_id, product_id),
        )
