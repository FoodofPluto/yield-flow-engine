from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, make_response, request

from billing_service import BillingConfigurationError, BillingOperationError, BillingService, BillingWebhookInvalid


COOKIE_NAME = "__Host-furuflow_session"


class _RedactActivationTicket(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                re.sub(r"ticket=[A-Za-z0-9_-]+", "ticket=[REDACTED]", str(value)) for value in record.args
            )
        return True


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required by the session broker.")
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class BrokerStore:
    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        project_url = _required("SUPABASE_URL").rstrip("/")
        parsed = urlparse(project_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise RuntimeError("SUPABASE_URL must be the HTTPS project root.")
        self._project_url = project_url
        self._url = project_url + "/rest/v1"
        self._key = _required("SUPABASE_SERVICE_ROLE_KEY")
        self._cipher = Fernet(_required("FURUFLOW_SESSION_ENCRYPTION_KEY").encode("ascii"))
        self._transport = transport

    def _crypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode("ascii")

    def _decrypt(self, value: str) -> str:
        return self._cipher.decrypt(value.encode("ascii")).decode()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: Any = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        with httpx.Client(timeout=10.0, transport=self._transport) as client:
            response = client.request(method, f"{self._url}/{path}", headers=headers, params=params, json=body)
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Session persistence operation failed.")
        return response.json() if response.content else None

    def issue(self, *, user_id: str, access_token: str, refresh_token: str | None) -> str:
        UUID(user_id)
        opaque = secrets.token_urlsafe(48)
        ticket = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        session_rows = self._request(
            "POST",
            "browser_sessions",
            body={
                "user_id": user_id,
                "opaque_hash": _hash(opaque),
                "access_token_ciphertext": self._crypt(access_token),
                "refresh_token_ciphertext": self._crypt(refresh_token) if refresh_token else None,
                "expires_at": _iso(now + timedelta(days=7)),
            },
            prefer="return=representation",
        )
        self._request(
            "POST",
            "browser_session_tickets",
            body={
                "ticket_hash": _hash(ticket),
                "browser_session_id": session_rows[0]["id"],
                "opaque_ciphertext": self._crypt(opaque),
                "expires_at": _iso(now + timedelta(minutes=2)),
            },
        )
        return ticket

    def consume_ticket(self, ticket: str) -> str | None:
        rows = self._request(
            "GET",
            "browser_session_tickets",
            params={"ticket_hash": f"eq.{_hash(ticket)}", "select": "*", "limit": "1"},
        )
        if not rows or rows[0].get("consumed_at") or datetime.fromisoformat(rows[0]["expires_at"]) <= datetime.now(timezone.utc):
            return None
        changed = self._request(
            "PATCH",
            "browser_session_tickets",
            params={"ticket_hash": f"eq.{_hash(ticket)}", "consumed_at": "is.null"},
            body={"consumed_at": _iso(datetime.now(timezone.utc))},
            prefer="return=representation",
        )
        if len(changed or []) != 1:
            return None
        try:
            return self._decrypt(rows[0]["opaque_ciphertext"])
        except InvalidToken:
            return None

    def restore(self, opaque: str) -> dict[str, str | None] | None:
        now = datetime.now(timezone.utc)
        rows = self._request(
            "GET",
            "browser_sessions",
            params={"opaque_hash": f"eq.{_hash(opaque)}", "select": "*", "limit": "1"},
        )
        if not rows or rows[0].get("revoked_at") or datetime.fromisoformat(rows[0]["expires_at"]) <= now:
            return None
        row = rows[0]
        try:
            tokens = {
                "access_token": self._decrypt(row["access_token_ciphertext"]),
                "refresh_token": self._decrypt(row["refresh_token_ciphertext"]) if row.get("refresh_token_ciphertext") else None,
            }
        except InvalidToken:
            self.revoke(opaque)
            return None
        self._request(
            "PATCH",
            "browser_sessions",
            params={"id": f"eq.{row['id']}"},
            body={"last_seen_at": _iso(now)},
        )
        return tokens

    def verified_identity(self, opaque: str) -> dict[str, Any] | None:
        tokens = self.restore(opaque)
        if not tokens or not tokens.get("access_token"):
            return None
        rows = self._request(
            "GET",
            "browser_sessions",
            params={"opaque_hash": f"eq.{_hash(opaque)}", "select": "user_id", "limit": "1"},
        )
        if not rows:
            return None
        try:
            with httpx.Client(timeout=5.0, transport=self._transport) as client:
                response = client.get(
                    f"{self._project_url}/auth/v1/user",
                    headers={
                        "apikey": self._key,
                        "Authorization": f"Bearer {tokens['access_token']}",
                        "Accept": "application/json",
                    },
                )
            if response.status_code != 200:
                return None
            identity = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        verified = identity.get("email_confirmed_at") or identity.get("confirmed_at")
        if identity.get("id") != rows[0].get("user_id") or not verified or identity.get("is_anonymous"):
            return None
        return identity

    def update(self, opaque: str, access_token: str, refresh_token: str | None) -> bool:
        rows = self._request(
            "PATCH",
            "browser_sessions",
            params={"opaque_hash": f"eq.{_hash(opaque)}", "revoked_at": "is.null"},
            body={
                "access_token_ciphertext": self._crypt(access_token),
                "refresh_token_ciphertext": self._crypt(refresh_token) if refresh_token else None,
                "last_seen_at": _iso(datetime.now(timezone.utc)),
            },
            prefer="return=representation",
        )
        return len(rows or []) == 1

    def revoke(self, opaque: str) -> None:
        self._request(
            "PATCH",
            "browser_sessions",
            params={"opaque_hash": f"eq.{_hash(opaque)}", "revoked_at": "is.null"},
            body={"revoked_at": _iso(datetime.now(timezone.utc))},
        )


def create_app(store: BrokerStore | None = None, billing_service: BillingService | None = None) -> Flask:
    app = Flask(__name__)
    broker_store = store or BrokerStore()
    bridge_key = _required("FURUFLOW_SESSION_BRIDGE_KEY")
    logging.getLogger("werkzeug").addFilter(_RedactActivationTicket())

    def trusted() -> bool:
        return secrets.compare_digest(request.headers.get("X-FuruFlow-Bridge-Key", ""), bridge_key)

    def billing() -> BillingService:
        nonlocal billing_service
        if billing_service is None:
            billing_service = BillingService()
        return billing_service

    def same_origin() -> bool:
        expected = os.getenv("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "").strip().rstrip("/")
        supplied = request.headers.get("Origin", "").strip().rstrip("/")
        return bool(expected and supplied and secrets.compare_digest(expected, supplied))

    def current_billing_identity() -> dict[str, Any] | None:
        opaque = request.cookies.get(COOKIE_NAME, "")
        if not opaque or not hasattr(broker_store, "verified_identity"):
            return None
        return broker_store.verified_identity(opaque)

    @app.post("/v1/session/tickets")
    def issue_ticket():
        if not trusted():
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True) or {}
        try:
            ticket = broker_store.issue(
                user_id=body["user_id"], access_token=body["access_token"], refresh_token=body.get("refresh_token")
            )
        except (KeyError, ValueError, RuntimeError):
            return jsonify({"error": "session_not_created"}), 400
        return jsonify({"activation_path": f"/auth/session/activate?ticket={ticket}"}), 201

    @app.get("/auth/session/activate")
    def activate():
        opaque = broker_store.consume_ticket(request.args.get("ticket", ""))
        if not opaque:
            return "Session activation expired.", 400, {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        response = make_response("<script>window.top.location.replace('/');</script>")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.set_cookie(COOKIE_NAME, opaque, secure=True, httponly=True, samesite="Lax", path="/", max_age=604800)
        return response

    @app.get("/v1/session/restore")
    def restore():
        if not trusted():
            return jsonify({"error": "unauthorized"}), 401
        tokens = broker_store.restore(request.headers.get("X-FuruFlow-Session", ""))
        return (jsonify(tokens), 200) if tokens else (jsonify({"error": "session_unavailable"}), 401)

    @app.put("/v1/session")
    def update():
        if not trusted():
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True) or {}
        updated = broker_store.update(
            request.headers.get("X-FuruFlow-Session", ""), body.get("access_token", ""), body.get("refresh_token")
        )
        return ("", 204) if updated else (jsonify({"error": "session_unavailable"}), 401)

    @app.delete("/v1/session")
    def revoke():
        if not trusted():
            return jsonify({"error": "unauthorized"}), 401
        broker_store.revoke(request.headers.get("X-FuruFlow-Session", ""))
        return "", 204

    @app.post("/billing/checkout")
    def checkout():
        if not same_origin():
            return jsonify({"error": "billing_request_denied"}), 403
        identity = current_billing_identity()
        if not identity:
            return jsonify({"error": "authentication_required"}), 401
        try:
            return "", 303, {"Location": billing().create_checkout(identity), "Cache-Control": "no-store"}
        except BillingOperationError:
            return jsonify({"error": "checkout_unavailable"}), 409
        except BillingConfigurationError:
            return jsonify({"error": "billing_unavailable"}), 503

    @app.post("/billing/portal")
    def portal():
        if not same_origin():
            return jsonify({"error": "billing_request_denied"}), 403
        identity = current_billing_identity()
        if not identity:
            return jsonify({"error": "authentication_required"}), 401
        try:
            return "", 303, {"Location": billing().create_portal(identity), "Cache-Control": "no-store"}
        except BillingOperationError:
            return jsonify({"error": "portal_unavailable"}), 409
        except BillingConfigurationError:
            return jsonify({"error": "billing_unavailable"}), 503

    @app.post("/stripe/webhook")
    def stripe_webhook():
        try:
            processed = billing().handle_webhook(request.get_data(cache=False), request.headers.get("Stripe-Signature", ""))
            return jsonify({"received": True, "duplicate": not processed})
        except BillingWebhookInvalid:
            return jsonify({"error": "invalid_webhook"}), 400
        except BillingOperationError:
            return jsonify({"error": "fulfillment_failed"}), 500
        except BillingConfigurationError:
            return jsonify({"error": "billing_unavailable"}), 503

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8510)
