import requests

from app.config.settings import PAYSTACK_SECRET_KEY

if not PAYSTACK_SECRET_KEY:
    raise SystemExit("Set PAYSTACK_SECRET_KEY in .env first")

PLANS = [
    ("PricePounce Pro Monthly", 200000, "monthly", "PAYSTACK_PLAN_MONTHLY"),
    ("PricePounce Pro Yearly", 2016000, "annually", "PAYSTACK_PLAN_YEARLY"),
]

for name, amount, interval, env_name in PLANS:
    response = requests.post(
        "https://api.paystack.co/plan",
        json={"name": name, "amount": amount, "interval": interval, "currency": "NGN"},
        headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
        timeout=20,
    )
    body = response.json()

    if not body.get("status"):
        raise SystemExit(f"Failed: {body}")

    print(f"{env_name}={body['data']['plan_code']}")