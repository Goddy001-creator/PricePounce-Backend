from flask import Blueprint, jsonify

from app.database.connection import create_connection
from app.extensions import limiter
from app.services.rates import CURRENCIES

rates_bp = Blueprint("rates", __name__)


@rates_bp.route("/rates", methods=["GET"])
@limiter.limit("60 per minute")
def latest_rates():
    """Latest market rate for each currency, with the change since the day before."""
    connection = create_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT DISTINCT rate_date FROM currency_rates "
            "ORDER BY rate_date DESC LIMIT 2"
        )
        days = [row[0] for row in cursor.fetchall()]

        if not days:
            return jsonify({"date": None, "rates": []})

        latest = days[0]
        previous = days[1] if len(days) > 1 else None

        cursor.execute(
            "SELECT currency, ngn_per_unit FROM currency_rates WHERE rate_date = %s",
            (latest,),
        )
        today = {code: float(value) for code, value in cursor.fetchall()}

        before = {}
        if previous:
            cursor.execute(
                "SELECT currency, ngn_per_unit FROM currency_rates "
                "WHERE rate_date = %s",
                (previous,),
            )
            before = {code: float(value) for code, value in cursor.fetchall()}
    finally:
        connection.close()

    rates = []
    for code in CURRENCIES:
        if code not in today:
            continue

        change = None
        old = before.get(code)
        if old:
            change = round((today[code] - old) / old * 100, 2)

        rates.append(
            {
                "currency": code,
                "ngn_per_unit": today[code],
                "change_percent": change,
            }
        )

    return jsonify(
        {
            "date": latest.isoformat(),
            "rates": rates,
            "credit": "Rates By Exchange Rate API",
            "credit_url": "https://www.exchangerate-api.com",
        }
    )