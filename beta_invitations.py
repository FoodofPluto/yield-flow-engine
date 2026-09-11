"""Invitation boundary. No credential/body logging and no developer dotenv loading."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import deque
from typing import Any
from uuid import UUID

import httpx
from flask import Flask, make_response, request

INVITATION_COOKIE = "__Host-furuflow_invitation"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
SAFE_ERROR = "This invitation is unavailable. Ask for a new closed-beta invitation."


def digest(token: str) -> str:
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("invitation unavailable")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class InvitationService:
    def __init__(self, store: Any):
        self.store = store
        self._attempts: deque[float] = deque()
        self._lock = threading.Lock()

    def _within_budget(self) -> bool:
        # Bound bridge calls too; current deployment uses one broker worker.
        with self._lock:
            now = time.monotonic()
            while self._attempts and self._attempts[0] <= now - 60:
                self._attempts.popleft()
            if len(self._attempts) >= 60:
                return False
            self._attempts.append(now)
            return True

    def valid(self, token: str) -> bool:
        try:
            token_digest = digest(token)
            if not self._within_budget():
                return False
            return (
                self.store._request(
                    "POST", "rpc/service_validate_beta_invitation", body={"invitation_digest": token_digest}
                )
                is True
            )
        except Exception:
            return False

    def register(self, token: str, email: str, password: str) -> bool:
        # Validate before consuming. Provider remains authoritative for email and
        # password policy; never confirm email or modify an existing account.
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            return False
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            return False
        try:
            token_digest = digest(token)
            if not self._within_budget():
                return False
            reserved = self.store._request(
                "POST", "rpc/service_claim_beta_invitation", body={"invitation_digest": token_digest}
            )
            if not isinstance(reserved, str):
                return False
            UUID(reserved)
            with httpx.Client(timeout=10.0, transport=self.store._transport, follow_redirects=False) as client:
                response = client.post(
                    self.store._project_url + "/auth/v1/admin/users",
                    headers={"apikey": self.store._key, "Authorization": "Bearer " + self.store._key},
                    json={"id": reserved, "email": email, "password": password, "email_confirm": False},
                )
            if response.status_code not in (200, 201):
                return False
            payload = response.json()
            return isinstance(payload, dict) and payload.get("id") == reserved and not payload.get("email_confirmed_at")
        except Exception:
            # Includes ambiguous provider outcomes: do not reissue or release claim.
            return False


def register_invitation_routes(app: Flask, service: InvitationService, trusted: Any) -> None:
    def landing(valid: bool):
        destination = "/?page=Account&beta_invite=" + ("1" if valid else "unavailable")
        response = make_response(
            '<!doctype html><meta name="referrer" content="no-referrer">'
            '<title>FuruFlow invitation</title><script>history.replaceState(null,"","/create-account");'
            'location.replace("' + destination + '");</script>'
            "<noscript>Enable JavaScript to open your closed-beta invitation.</noscript>"
        )
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
            }
        )
        return response

    @app.get("/create-account")
    def invitation_entry():
        # Strict syntax prevents parameter smuggling and interpolation. No token in HTML.
        match = re.fullmatch(rb"invite=([A-Za-z0-9_-]{43})", request.query_string)
        token = match.group(1).decode("ascii") if match else ""
        valid = service.valid(token) if token else False
        response = landing(valid)
        if valid:
            response.set_cookie(
                INVITATION_COOKIE, token, secure=True, httponly=True, samesite="Lax", path="/", max_age=86400
            )
        else:
            response.delete_cookie(INVITATION_COOKIE, secure=True, httponly=True, samesite="Lax", path="/")
        return response

    @app.get("/create-account/complete")
    def invitation_complete():
        response = make_response("", 204)
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        response.delete_cookie(INVITATION_COOKIE, secure=True, httponly=True, samesite="Lax", path="/")
        return response

    @app.post("/v1/invitations/validate")
    def invitation_validate():
        if not trusted():
            return {"valid": False}, 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {"valid": False}, 400
        return {"valid": service.valid(body.get("invitation", ""))}

    @app.post("/v1/invitations/register")
    def invitation_register():
        if not trusted():
            return {"created": False}, 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"invitation", "email", "password"}:
            return {"created": False}, 400
        created = service.register(body["invitation"], body["email"], body["password"])
        return {"created": created}, 201 if created else 400


def invitation_bridge(action: str, token: str, **fields: str) -> bool:
    """Streamlit to existing loopback broker; never expose service credentials."""
    try:
        digest(token)
        if action not in {"validate", "register"}:
            return False
        if os.getenv("FURUFLOW_SESSION_BROKER_INTERNAL_URL", "").rstrip("/") != "http://127.0.0.1:8510":
            return False
        key = os.environ["FURUFLOW_SESSION_BRIDGE_KEY"]
        if len(key) < 32:
            return False
        response = httpx.post(
            "http://127.0.0.1:8510/v1/invitations/" + action,
            headers={"X-FuruFlow-Bridge-Key": key},
            json={"invitation": token, **fields},
            timeout=15,
            follow_redirects=False,
        )
        return (
            response.status_code in (200, 201)
            and response.json().get("valid" if action == "validate" else "created") is True
        )
    except Exception:
        return False
