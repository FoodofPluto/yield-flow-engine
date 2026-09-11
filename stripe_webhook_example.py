"""Compatibility launcher for the trusted billing/session sidecar.

The deployable webhook is registered by ``session_broker.create_app`` so Stripe
secrets and Supabase service-role authority share the existing isolated backend
boundary. This module intentionally contains no separate fulfillment logic.
"""

from session_broker import create_app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8510)
