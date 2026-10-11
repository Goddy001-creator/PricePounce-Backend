import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import mysql.connector
import requests

from app.config.settings import (
    FRONTEND_URL,
    PAYSTACK_PLAN_MONTHLY,
    PAYSTACK_PLAN_YEARLY,
    PAYSTACK_SECRET_KEY,
)
from app.database.connection import create_connection
from app.services.email_service import send_payment_email

logger = logging.getLogger(__name__)

# Amounts are in kobo. Days include a little slack for renewal timing.
PLANS = {
    "monthly": {"amount": 200000, "days": 31, "label": "Monthly", "code": PAYSTACK_PLAN_MONTHLY},
    "yearly": {"amount": 2016000, "days": 366, "label": "Yearly", "code": PAYSTACK_PLAN_YEARLY},
}


class BillingError(Exception):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _paystack(method, path, payload=None):
    if not PAYSTACK_SECRET_KEY:
        raise BillingError("Payments are not set up yet.")

    try:
        response = requests.request(
            method,
            f"https://api.paystack.co{path}",
            json=payload,
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
            timeout=20,
        )
        body = response.json()
    except (requests.RequestException, ValueError):
        raise BillingError("Couldn't reach the payment provider. Please try again.")

    if not response.ok or not body.get("status"):
        logger.error("Paystack error on %s: %s", path, body)
        raise BillingError("The payment provider rejected the request.")

    return body["data"]


def signature_valid(raw_body, signature):
    if not PAYSTACK_SECRET_KEY or not signature:
        return False

    expected = hmac.new(
        PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def start_checkout(user_id, email, interval):
    plan = PLANS.get(interval)

    if plan is None or not plan["code"]:
        raise BillingError("That plan isn't available.")

    reference = "pp_" + secrets.token_hex(12)

    data = _paystack("POST", "/transaction/initialize", {
        "email": email,
        "amount": plan["amount"],
        "plan": plan["code"],
        "reference": reference,
        "callback_url": f"{FRONTEND_URL}/",
        "metadata": {"user_id": user_id, "interval": interval},
    })

    connection = create_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO payments (user_id, reference, plan_interval, amount_kobo) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, reference, interval, plan["amount"]),
        )
        connection.commit()
    finally:
        connection.close()

    return data["authorization_url"]


def apply_charge(data):
    """Grants or extends Pro for a successful charge. Safe to call twice."""
    if data.get("status") != "success" or data.get("currency", "NGN") != "NGN":
        return False

    reference = data.get("reference")
    paid = int(data.get("amount") or 0)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    plan_field = data.get("plan")
    plan_code = plan_field.get("plan_code") if isinstance(plan_field, dict) else plan_field

    interval = None

    if plan_code and plan_code == PAYSTACK_PLAN_YEARLY:
        interval = "yearly"
    elif plan_code and plan_code == PAYSTACK_PLAN_MONTHLY:
        interval = "monthly"
    elif metadata.get("interval") in PLANS:
        interval = metadata["interval"]

    if not reference or interval is None or paid < PLANS[interval]["amount"]:
        logger.warning("Ignoring charge %s (interval=%s, paid=%s)", reference, interval, paid)
        return False

    plan = PLANS[interval]
    email = (data.get("customer") or {}).get("email")

    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT id, status FROM payments WHERE reference = %s FOR UPDATE",
            (reference,),
        )
        existing = cursor.fetchone()

        if existing and existing["status"] == "success":
            return False

        user = None

        try:
            user_id = int(metadata.get("user_id"))
        except (TypeError, ValueError):
            user_id = None

        columns = "id, name, email, plan, plan_expires_at"

        if user_id:
            cursor.execute(
                f"SELECT {columns} FROM users WHERE id = %s FOR UPDATE", (user_id,)
            )
            user = cursor.fetchone()

        if user is None and email:
            cursor.execute(
                f"SELECT {columns} FROM users WHERE LOWER(email) = LOWER(%s) FOR UPDATE",
                (email,),
            )
            user = cursor.fetchone()

        if user is None:
            logger.error("Charge %s has no matching user", reference)
            return False

        now = _utcnow()
        expires = user["plan_expires_at"]
        lifetime = user["plan"] == "pro" and expires is None
        new_expiry = None

        if not lifetime:
            start = expires if (user["plan"] == "pro" and expires and expires > now) else now
            new_expiry = start + timedelta(days=plan["days"])

            cursor.execute(
                "UPDATE users SET plan = 'pro', plan_expires_at = %s, "
                "plan_source = 'payment', plan_granted_by = NULL WHERE id = %s",
                (new_expiry, user["id"]),
            )

        if existing:
            cursor.execute(
                "UPDATE payments SET status = 'success', paid_at = %s WHERE reference = %s",
                (now, reference),
            )
        else:
            cursor.execute(
                "INSERT INTO payments (user_id, reference, plan_interval, amount_kobo, "
                "status, paid_at) VALUES (%s, %s, %s, %s, 'success', %s)",
                (user["id"], reference, interval, paid, now),
            )

        connection.commit()

    except mysql.connector.IntegrityError:
        connection.rollback()
        return False
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    if new_expiry:
        send_payment_email(user["name"], user["email"], plan["label"], new_expiry)

    return True


def _find_user_id_by_email(cursor, email):
    cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
    row = cursor.fetchone()
    return row["id"] if row else None


def _save_subscription(data):
    email = (data.get("customer") or {}).get("email")
    code = data.get("subscription_code")
    token = data.get("email_token")

    if not (email and code and token):
        return

    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        user_id = _find_user_id_by_email(cursor, email)

        if user_id is None:
            return

        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, subscription_code, email_token, plan_code, status)
            VALUES (%s, %s, %s, %s, 'active')
            ON DUPLICATE KEY UPDATE subscription_code = VALUES(subscription_code),
                email_token = VALUES(email_token), plan_code = VALUES(plan_code),
                status = 'active'
            """,
            (user_id, code, token, (data.get("plan") or {}).get("plan_code")),
        )
        connection.commit()
    finally:
        connection.close()


def _end_subscription(code):
    if not code:
        return

    connection = create_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE subscriptions SET status = 'cancelled' WHERE subscription_code = %s",
            (code,),
        )
        connection.commit()
    finally:
        connection.close()


def handle_event(event):
    name = event.get("event")
    data = event.get("data") or {}

    if name == "charge.success":
        apply_charge(data)
    elif name == "subscription.create":
        _save_subscription(data)
    elif name in ("subscription.disable", "subscription.not_renew"):
        _end_subscription(data.get("subscription_code"))
    elif name == "invoice.payment_failed":
        logger.warning("Renewal payment failed: %s", data.get("subscription", {}))


def verify_reference(reference, user_id):
    data = _paystack("GET", f"/transaction/verify/{quote(reference, safe='')}")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    if str(metadata.get("user_id")) != str(user_id):
        raise BillingError("This payment belongs to another account.")

    apply_charge(data)
    return data.get("status") == "success"


def get_status(user_id):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT plan, plan_expires_at, plan_source FROM users WHERE id = %s",
            (user_id,),
        )
        user = cursor.fetchone() or {}

        cursor.execute("SELECT status FROM subscriptions WHERE user_id = %s", (user_id,))
        subscription = cursor.fetchone()
    finally:
        connection.close()

    return {
        "plan": user.get("plan"),
        "expires_at": user.get("plan_expires_at"),
        "source": user.get("plan_source"),
        "renewing": bool(subscription and subscription["status"] == "active"),
    }


def cancel_subscription(user_id):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT subscription_code, email_token FROM subscriptions "
            "WHERE user_id = %s AND status = 'active'",
            (user_id,),
        )
        row = cursor.fetchone()

        if row is None:
            raise BillingError("You have no active subscription to cancel.")

        _paystack("POST", "/subscription/disable", {
            "code": row["subscription_code"],
            "token": row["email_token"],
        })

        cursor.execute(
            "UPDATE subscriptions SET status = 'cancelled' WHERE user_id = %s",
            (user_id,),
        )
        connection.commit()
    finally:
        connection.close()