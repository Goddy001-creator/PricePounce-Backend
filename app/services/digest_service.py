import logging
import secrets
from collections import defaultdict

from app.config.settings import BACKEND_URL
from app.database.repositories import create_connection
from app.security.plans import effective_plan
from app.services.email_service import send_weekly_digest_email

logger = logging.getLogger(__name__)


def _weekly_change(points, week_ago):
    """Returns (price now, price a week ago, percent change) or None."""
    if len(points) < 2:
        return None

    base = None

    for row in points:
        if row["checked_at"] <= week_ago:
            base = row

    if base is None:
        base = points[0]

    if base is points[-1]:
        return None

    now_price = float(points[-1]["price"])
    base_price = float(base["price"])

    if base_price <= 0 or now_price == base_price:
        return None

    return now_price, base_price, (now_price - base_price) / base_price * 100


def run_weekly_digest(only_email=None, force=False, send_if_empty=False):
    connection = create_connection()
    sent = 0

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT NOW() - INTERVAL 7 DAY AS week_ago, "
            "NOW() - INTERVAL 6 DAY AS min_gap"
        )
        clock = cursor.fetchone()

        query = "SELECT * FROM users WHERE alerts_email = 1"
        params = []

        if only_email:
            query += " AND email = %s"
            params.append(only_email)

        cursor.execute(query, params)

        users = [
            user for user in cursor.fetchall()
            if effective_plan(user) == "pro"
            and user.get("status", "active") == "active"
            and (
                force
                or not user.get("last_digest_at")
                or user["last_digest_at"] <= clock["min_gap"]
            )
        ]

        if not users:
            return 0

        marks = ",".join(["%s"] * len(users))

        cursor.execute(
            f"""
            SELECT w.user_id, w.product_id, p.product_name, p.store_name
            FROM watchlist w JOIN products p ON p.id = w.product_id
            WHERE w.user_id IN ({marks})
            """,
            [user["id"] for user in users],
        )
        rows = cursor.fetchall()

        product_ids = list({row["product_id"] for row in rows})
        history = defaultdict(list)

        if product_ids:
            marks = ",".join(["%s"] * len(product_ids))

            cursor.execute(
                f"""
                SELECT product_id, price, checked_at FROM price_history
                WHERE product_id IN ({marks})
                ORDER BY product_id, checked_at
                """,
                product_ids,
            )

            for row in cursor.fetchall():
                history[row["product_id"]].append(row)

        by_user = defaultdict(list)

        for row in rows:
            by_user[row["user_id"]].append(row)

        for user in users:
            items = by_user.get(user["id"], [])
            drops = []
            rises = 0

            for item in items:
                change = _weekly_change(history[item["product_id"]], clock["week_ago"])

                if change is None:
                    continue

                now_price, old_price, percent = change

                if percent < 0:
                    drops.append({
                        "name": item["product_name"],
                        "store": item["store_name"],
                        "old": old_price,
                        "price": now_price,
                        "percent": percent,
                    })
                else:
                    rises += 1

            drops.sort(key=lambda entry: entry["percent"])

            if items and (drops or rises or send_if_empty):
                token = user.get("alert_token")

                if not token:
                    token = secrets.token_urlsafe(24)
                    cursor.execute(
                        "UPDATE users SET alert_token = %s WHERE id = %s",
                        (token, user["id"]),
                    )

                send_weekly_digest_email(
                    user.get("name"),
                    user["email"],
                    drops[:5],
                    rises,
                    len(items),
                    f"{BACKEND_URL}/api/alerts/unsubscribe?token={token}",
                )
                sent += 1

            cursor.execute(
                "UPDATE users SET last_digest_at = NOW() WHERE id = %s",
                (user["id"],),
            )

        connection.commit()
        logger.info("Weekly digest sent to %d users", sent)
        return sent

    except Exception:
        connection.rollback()
        logger.exception("Weekly digest failed")
        return sent
    finally:
        connection.close()