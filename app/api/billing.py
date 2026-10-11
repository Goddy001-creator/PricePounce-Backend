import json
import re

from flask import Blueprint, g, jsonify, request

from app.extensions import limiter
from app.security.sessions import login_required
from app.services import billing_service as billing

billing_bp = Blueprint("billing", __name__)

REFERENCE = re.compile(r"^pp_[a-f0-9]{24}$")


@billing_bp.route("/billing/plans", methods=["GET"])
def plans():
    return jsonify({
        "monthly": {"price": 2000, "per": "month"},
        "yearly": {"price": 1680, "per": "month", "billed": 20160},
    })


@billing_bp.route("/billing/checkout", methods=["POST"])
@limiter.limit("10 per hour")
@login_required
def checkout():
    payload = request.get_json(silent=True) or {}
    interval = payload.get("interval")

    if interval not in ("monthly", "yearly"):
        return jsonify({"error": "Choose monthly or yearly."}), 400

    try:
        url = billing.start_checkout(g.session["id"], g.session["email"], interval)
    except billing.BillingError as error:
        return jsonify({"error": str(error)}), 502

    return jsonify({"authorization_url": url})


@billing_bp.route("/billing/verify", methods=["GET"])
@limiter.limit("30 per hour")
@login_required
def verify():
    reference = request.args.get("reference", "")

    if not REFERENCE.match(reference):
        return jsonify({"error": "Invalid reference."}), 400

    try:
        paid = billing.verify_reference(reference, g.session["id"])
    except billing.BillingError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"paid": paid})


@billing_bp.route("/billing/status", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def status():
    return jsonify(billing.get_status(g.session["id"]))


@billing_bp.route("/billing/cancel", methods=["POST"])
@limiter.limit("5 per hour")
@login_required
def cancel():
    try:
        billing.cancel_subscription(g.session["id"])
    except billing.BillingError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"message": "Renewal cancelled. Pro stays active until it expires."})


@billing_bp.route("/billing/webhook", methods=["POST"])
@limiter.limit("600 per minute")
def webhook():
    raw = request.get_data()

    if not billing.signature_valid(raw, request.headers.get("x-paystack-signature", "")):
        return "", 401

    try:
        event = json.loads(raw)
    except ValueError:
        return "", 400

    try:
        billing.handle_event(event)
    except Exception:
        # A 500 makes Paystack retry later
        billing.logger.exception("Webhook handling failed")
        return "", 500

    return "", 200