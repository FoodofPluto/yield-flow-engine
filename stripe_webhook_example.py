"""
Example Flask webhook file for real Stripe fulfillment.

This version is set up for a recurring Pro subscription instead of a one-time unlock.
Host it on a backend, point Stripe webhooks to it, and keep the Streamlit app as the UI.
"""

from __future__ import annotations

import os

import stripe
from flask import Flask, jsonify, request

from db import (
    get_user_by_stripe_customer_id,
    get_user_by_subscription_id,
    init_db,
    set_subscription_state,
    upsert_user,
)

app = Flask(__name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

ACTIVE_STATUSES = {"trialing", "active", "past_due"}

init_db()


def _checkout_email(session: dict) -> str | None:
    customer_details = session.get("customer_details") or {}
    return customer_details.get("email") or session.get("customer_email")


def _upsert_from_subscription(*, customer_email: str | None, customer_id: str | None, subscription_id: str | None, status: str | None):
    if not customer_email and customer_id:
        existing = get_user_by_stripe_customer_id(customer_id)
        customer_email = existing["email"] if existing else None

    if not customer_email and subscription_id:
        existing = get_user_by_subscription_id(subscription_id)
        customer_email = existing["email"] if existing else None

    if not customer_email:
        return

    upsert_user(
        customer_email,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        subscription_status=status,
        purchase_source="stripe",
    )
    set_subscription_state(
        customer_email,
        pro_active=(status in ACTIVE_STATUSES),
        subscription_status=status,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        purchase_source="stripe",
    )


@app.post("/stripe/webhook")
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        mode = obj.get("mode")
        customer_email = _checkout_email(obj)
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")

        if mode == "subscription":
            _upsert_from_subscription(
                customer_email=customer_email,
                customer_id=customer_id,
                subscription_id=subscription_id,
                status="active",
            )
        else:
            # Keep one-time payments compatible if you ever sell lifetime unlocks later.
            if customer_email:
                upsert_user(customer_email, stripe_customer_id=customer_id, purchase_source="stripe")
                set_subscription_state(
                    customer_email,
                    pro_active=True,
                    subscription_status="one_time_paid",
                    stripe_customer_id=customer_id,
                    purchase_source="stripe",
                )

    elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        customer_id = obj.get("customer")
        subscription_id = obj.get("id")
        status = obj.get("status")
        customer_email = None

        if customer_id and not customer_email:
            try:
                customer = stripe.Customer.retrieve(customer_id)
                customer_email = customer.get("email")
            except Exception:
                customer_email = None

        _upsert_from_subscription(
            customer_email=customer_email,
            customer_id=customer_id,
            subscription_id=subscription_id,
            status=status,
        )

    elif event_type == "invoice.payment_failed":
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        _upsert_from_subscription(
            customer_email=None,
            customer_id=customer_id,
            subscription_id=subscription_id,
            status="past_due",
        )

    return jsonify({"received": True})
