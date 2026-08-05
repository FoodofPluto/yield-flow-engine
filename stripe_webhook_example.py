"""Trusted Stripe webhook backed by Supabase account state."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

import stripe
from flask import Flask, jsonify, request

from account_control import AccountOperationError, ServiceRoleAccountClient


app = Flask(__name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")


def _verified_reference(obj: dict) -> str | None:
    reference = obj.get("client_reference_id") or ""
    if reference.startswith("furuflow_user:"):
        reference = reference.removeprefix("furuflow_user:")
    else:
        reference = (obj.get("metadata") or {}).get("user_id") or ""
    try:
        return str(UUID(reference))
    except ValueError:
        return None


def _apply(client: ServiceRoleAccountClient, event_type: str, obj: dict) -> None:
    if event_type == "checkout.session.completed":
        if obj.get("mode") != "subscription":
            return  # One-time/lifetime fulfillment is never inferred automatically.
        client.apply_stripe_subscription(
            user_id=_verified_reference(obj),
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            checkout_session_id=obj.get("id"),
            status="active",
        )
    elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        period_end = obj.get("current_period_end")
        client.apply_stripe_subscription(
            user_id=_verified_reference(obj),
            customer_id=obj.get("customer"),
            subscription_id=obj.get("id"),
            status=obj.get("status") or "inactive",
            period_end=None if period_end is None else datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat(),
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
        )
    elif event_type == "invoice.payment_failed":
        client.apply_stripe_subscription(
            user_id=None,
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            status="past_due",
        )


@app.post("/stripe/webhook")
def stripe_webhook():
    try:
        event = stripe.Webhook.construct_event(request.data, request.headers.get("Stripe-Signature", ""), WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "invalid_webhook"}), 400
    event_id = event.get("id")
    event_type = event.get("type")
    if not isinstance(event_id, str) or not isinstance(event_type, str):
        return jsonify({"error": "invalid_event"}), 400
    client = ServiceRoleAccountClient()
    try:
        if not client.begin_webhook_event(event_id, event_type):
            return jsonify({"received": True, "duplicate": True})
        _apply(client, event_type, event["data"]["object"])
        client.finish_webhook_event(event_id, succeeded=True)
        return jsonify({"received": True})
    except (AccountOperationError, KeyError, TypeError, ValueError):
        try:
            client.finish_webhook_event(event_id, succeeded=False, error_code="fulfillment_failed")
        except AccountOperationError:
            pass
        return jsonify({"error": "fulfillment_failed"}), 500
