import logging
import secrets
from collections import defaultdict

from app.config.settings import BACKEND_URL
from app.database.repositories import create_connection
from app.security.plans import effective_plan
from app.services.email_service import send_price_alert_email

logger = logging.getLogger(__name__)

LATEST_PRICES_SQL = """
    SELECT product_id, price, prev_price FROM (
        SELECT
            product_id,
            price,
            LAG(price) OVER (PARTITION BY product_id ORDER BY checked_at) AS prev_price,
            ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY checked_at DESC) AS rn
        FROM price_history
        WHERE product_id IN (SELECT DISTINCT product_id FROM watchlist)
    ) t
    WHERE rn = 1
"""

WATCH_SQL = """
    SELECT w.user_id, w.product_id, w.target_price, w.last_alerted_price,
           p.product_name, p.store_name
    FROM watchlist w
    JOIN products p ON p.id = w.product_id
"""


def run_alerts():
    """Call after a scrape. One email per Pro user, never the same price twice."""
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(LATEST_PRICES_SQL)
        latest = {r["product_id"]: r for r in cursor.fetchall()}

        cursor.execute("SELECT * FROM users WHERE alerts_email = 1")
        users = {u["id"]: u for u in cursor.fetchall()}

        cursor.execute(WATCH_SQL)
        rows = cursor.fetchall()

        per_user = defaultdict(list)
        resets = []
        updates = []

        for row in rows:
            user = users.get(row["user_id"])
            price_row = latest.get(row["product_id"])

            if not user or not price_row:
                continue

            # Pro only, active accounts only
            if effective_plan(user) != "pro" or user.get("status", "active") != "active":
                continue

            price = float(price_row["price"])
            prev = float(price_row["prev_price"]) if price_row["prev_price"] else None
            last = float(row["last_alerted_price"]) if row["last_alerted_price"] else None
            target = float(row["target_price"]) if row["target_price"] else None

            # Price went back up: allow the next drop to alert again
            if last is not None and price > last:
                resets.append((row["user_id"], row["product_id"]))
                last = None

            if last is not None and price == last:
                continue

            item = None

            if target is not None and price <= target:
                item = {"kind": "target", "target": target}
            elif prev and price < prev and (last is None or price < last):
                item = {
                    "kind": "drop",
                    "old": prev,
                    "percent": (prev - price) / prev * 100,
                }

            if item:
                item.update(
                    name=row["product_name"],
                    store=row["store_name"],
                    price=price,
                )
                per_user[row["user_id"]].append(item)
                updates.append((price, row["user_id"], row["product_id"]))

        for user_id, product_id in resets:
            cursor.execute(
                "UPDATE watchlist SET last_alerted_price = NULL "
                "WHERE user_id = %s AND product_id = %s",
                (user_id, product_id),
            )

        for user_id, items in per_user.items():
            user = users[user_id]
            token = user.get("alert_token")

            if not token:
                token = secrets.token_urlsafe(24)
                cursor.execute(
                    "UPDATE users SET alert_token = %s WHERE id = %s",
                    (token, user_id),
                )

            send_price_alert_email(
                user.get("name"),
                user["email"],
                items,
                f"{BACKEND_URL}/api/alerts/unsubscribe?token={token}",
            )

        for price, user_id, product_id in updates:
            cursor.execute(
                "UPDATE watchlist SET last_alerted_price = %s "
                "WHERE user_id = %s AND product_id = %s",
                (price, user_id, product_id),
            )

        connection.commit()
        logger.info("Alerts sent to %d users", len(per_user))

    except Exception:
        connection.rollback()
        logger.exception("Alerts run failed")
    finally:
        connection.close()