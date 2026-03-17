"""
Example Flask webhook file for real Stripe fulfillment.

This is not wired into Streamlit directly. In production, you would:
1. Host this on your backend
2. Verify Stripe signatures
3. Use the customer's email or customer ID from the event
4. Mark lifetime_access=True in your database
"""

import os
import stripe
from flask import Flask, request, jsonify
from db import init_db, upsert_user, set_lifetime_access

app = Flask(__name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

init_db()

@app.post("/stripe/webhook")
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email") or session.get("customer_email")
        customer_id = session.get("customer")
        if customer_email:
            upsert_user(customer_email, stripe_customer_id=customer_id, purchase_source="stripe")
            set_lifetime_access(customer_email, True)

    return jsonify({"received": True})
