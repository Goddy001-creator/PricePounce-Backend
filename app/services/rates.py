"""Daily currency rates.

Fetches market rates from ExchangeRate-API (open access) and stores how many
naira one unit of each currency costs, one row per currency per day.
Rates by Exchange Rate API: https://www.exchangerate-api.com
"""
import logging
from datetime import datetime, timezone

import requests

from app.database.connection import create_connection

log = logging.getLogger(__name__)

API_URL = "https://open.er-api.com/v6/latest/USD"
CURRENCIES = ["USD", "GBP", "EUR", "CNY", "CAD", "AED", "GHS", "ZAR"]


def fetch_rates():
    """Return (rate_date, {currency: naira_per_unit}) from the provider."""
    resp = requests.get(
        API_URL,
        timeout=15,
        headers={"User-Agent": "PricePounce/1.0 (support@pricepounce.app)"},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise RuntimeError(f"Rates provider error: {data.get('error-type')}")

    rates = data["rates"]
    ngn_per_usd = rates.get("NGN")
    if not ngn_per_usd:
        raise RuntimeError("Rates provider returned no NGN rate")

    rate_date = datetime.fromtimestamp(
        data["time_last_update_unix"], tz=timezone.utc
    ).date()

    out = {}
    for code in CURRENCIES:
        per_usd = rates.get(code)
        if per_usd:
            out[code] = round(ngn_per_usd / per_usd, 4)
    return rate_date, out


def store_rates(rate_date, rates):
    """Save one row per currency for the given day (safe to run twice)."""
    conn = create_connection()
    try:
        cur = conn.cursor()
        for code, value in rates.items():
            cur.execute(
                "INSERT INTO currency_rates (rate_date, currency, ngn_per_unit) "
                "VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE ngn_per_unit = VALUES(ngn_per_unit), "
                "fetched_at = NOW()",
                (rate_date, code, value),
            )
        conn.commit()
    finally:
        conn.close()


def update_rates():
    rate_date, rates = fetch_rates()
    store_rates(rate_date, rates)
    log.info("Stored %d currency rates for %s", len(rates), rate_date)
    return rate_date, rates


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    day, saved = update_rates()
    print(day)
    for code, value in saved.items():
        print(code, value)