from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import streamlit as st


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _token(secret: str, *, sub: str = "supabase-user-1", email: str = "user@example.com", exp: int | None = None, verified: bool = True) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "aud": "authenticated",
        "sub": sub,
        "email": email,
        "exp": exp or int(time.time()) + 3600,
        "user_metadata": {"email_verified": verified},
    }
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _unsigned_token(
    *,
    alg: str = "ES256",
    kid: str = "test-key",
    sub: str = "supabase-user-1",
    email: str = "user@example.com",
    exp: int | None = None,
    verified: bool = True,
) -> str:
    header = {"alg": alg, "typ": "JWT", "kid": kid}
    payload = {
        "aud": "authenticated",
        "sub": sub,
        "email": email,
        "exp": exp or int(time.time()) + 3600,
        "user_metadata": {"email_verified": verified},
    }
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    return f"{signing_input}.invalid-signature"


class SupabaseAuthMigrationTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.env_patch = patch.dict(
            os.environ,
            {
                "FURUFLOW_DB_PATH": self.db_path,
                "SUPABASE_JWT_SECRET": "test-secret",
                "ENVIRONMENT": "test",
                "DEV_MODE": "false",
            },
            clear=False,
        )
        self.env_patch.start()

        import db
        import supabase_auth
        import auth_service

        self.db = importlib.reload(db)
        self.db.init_db()
        self.supabase_auth = importlib.reload(supabase_auth)
        self.auth_service = importlib.reload(auth_service)
        self.session_state: dict[str, object] = {}
        self.supabase_state_patch = patch.object(self.supabase_auth.st, "session_state", self.session_state)
        self.auth_service_state_patch = patch.object(self.auth_service.st, "session_state", self.session_state)
        self.supabase_state_patch.start()
        self.auth_service_state_patch.start()

    def tearDown(self):
        self.auth_service_state_patch.stop()
        self.supabase_state_patch.stop()
        self.env_patch.stop()
        os.remove(self.db_path)

    def test_verified_supabase_login_succeeds_and_creates_canonical_user(self):
        auth_user = self.supabase_auth.validate_supabase_session(_token("test-secret"))
        identity = self.supabase_auth.resolve_verified_identity(auth_user)
        user = self.db.get_user_by_provider_user_id("supabase-user-1")

        self.assertEqual(identity["provider_user_id"], "supabase-user-1")
        self.assertEqual(user["auth_provider"], "supabase")
        self.assertTrue(user["email_verified"])
        self.assertTrue(user["user_id"])

    def test_invalid_token_is_rejected(self):
        bad_token = _token("wrong-secret")

        with self.assertRaises(self.supabase_auth.AuthSessionError):
            self.supabase_auth.validate_supabase_session(bad_token)

    def test_ecc_jwks_configuration_accepts_verified_token(self):
        token = _unsigned_token(alg="ES256", sub="jwks-user", email="jwks@example.com")
        claims = {
            "aud": "authenticated",
            "sub": "jwks-user",
            "email": "jwks@example.com",
            "exp": int(time.time()) + 3600,
            "user_metadata": {"email_verified": True},
        }

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "", "SUPABASE_URL": "https://example.supabase.co"}, clear=False):
            with patch.object(self.supabase_auth, "_validate_jwks_jwt", return_value=claims) as validate_jwks:
                auth_user = self.supabase_auth.validate_supabase_session(token)

        self.assertEqual(auth_user["provider_user_id"], "jwks-user")
        validate_jwks.assert_called_once_with(token, "https://example.supabase.co/auth/v1/.well-known/jwks.json")

    def test_invalid_jwks_token_fails_closed(self):
        token = _unsigned_token(alg="ES256")

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "", "SUPABASE_URL": "https://example.supabase.co"}, clear=False):
            with patch.object(self.supabase_auth, "_validate_jwks_jwt", side_effect=self.supabase_auth.AuthSessionError("bad jwks")):
                with patch.object(self.supabase_auth, "get_supabase_client") as get_client:
                    with self.assertRaises(self.supabase_auth.AuthSessionError):
                        self.supabase_auth.validate_supabase_session(token)

        get_client.assert_not_called()

    def test_expired_session_forces_logout_when_refresh_is_unavailable(self):
        st.session_state[self.supabase_auth.ACCESS_TOKEN_KEY] = _token("test-secret", exp=int(time.time()) - 10)

        with self.assertRaises(self.supabase_auth.AuthSessionError):
            self.supabase_auth.validate_authenticated_session()

    def test_legacy_typed_email_cannot_gain_pro_or_admin(self):
        user = self.db.upsert_user("legacy@example.com", is_admin=True)
        self.db.set_lifetime_access("legacy@example.com", True)
        self.db.set_pro_active("legacy@example.com", True)
        user = self.db.get_user_by_email("legacy@example.com")

        self.assertFalse(self.auth_service.is_admin(user))
        self.assertFalse(self.auth_service.can_access_pro(user))

    def test_verified_user_preserves_existing_entitlements(self):
        self.db.upsert_user("paid@example.com")
        self.db.set_lifetime_access("paid@example.com", True)
        auth_user = self.supabase_auth.validate_supabase_session(
            _token("test-secret", sub="supabase-paid", email="paid@example.com")
        )
        self.supabase_auth.resolve_verified_identity(auth_user)
        user = self.db.get_user_by_provider_user_id("supabase-paid")
        user["_identity_verified"] = True

        self.assertTrue(user["migrated_from_legacy"])
        self.assertTrue(user["lifetime_access"])
        self.assertTrue(self.auth_service.can_access_pro(user))

    def test_stripe_fulfillment_binds_to_internal_user_id_and_duplicates_reject(self):
        auth_user = self.supabase_auth.validate_supabase_session(_token("test-secret"))
        self.supabase_auth.resolve_verified_identity(auth_user)
        user = self.db.get_user_by_provider_user_id("supabase-user-1")

        self.db.set_latest_checkout_session(user["user_id"], "cs_test_1")
        self.db.set_subscription_state(
            user["email"],
            pro_active=True,
            stripe_customer_id="cus_1",
            stripe_subscription_id="sub_1",
            subscription_status="active",
            purchase_source="stripe",
        )
        updated = self.db.get_user_by_user_id(user["user_id"])

        self.assertEqual(updated["latest_checkout_session"], "cs_test_1")
        self.assertEqual(updated["stripe_subscription_id"], "sub_1")
        self.assertTrue(self.db.verify_webhook_idempotency("evt_1", "checkout.session.completed"))
        self.assertFalse(self.db.verify_webhook_idempotency("evt_1", "checkout.session.completed"))

    def test_admin_actions_create_audit_rows(self):
        actor = self.db.upsert_user("actor@example.com", provider_user_id="actor-1", auth_provider="supabase", email_verified=True)
        target = self.db.upsert_user("target@example.com", provider_user_id="target-1", auth_provider="supabase", email_verified=True)

        self.db.record_admin_audit(
            actor_user_id=actor["user_id"],
            target_user_id=target["user_id"],
            action="grant_lifetime_access",
            reason="unit_test",
        )
        rows = self.db.list_admin_audit()

        self.assertEqual(rows[0]["actor_user_id"], actor["user_id"])
        self.assertEqual(rows[0]["target_user_id"], target["user_id"])
        self.assertEqual(rows[0]["action"], "grant_lifetime_access")

    def test_session_refresh_preserves_identity(self):
        expired = _token("test-secret", exp=int(time.time()) - 10)
        refreshed = _token("test-secret", sub="refresh-user", email="refresh@example.com")
        st.session_state[self.supabase_auth.ACCESS_TOKEN_KEY] = expired
        st.session_state[self.supabase_auth.REFRESH_TOKEN_KEY] = "refresh-token"

        fake_session = SimpleNamespace(access_token=refreshed, refresh_token="new-refresh-token")
        fake_client = SimpleNamespace(auth=SimpleNamespace(refresh_session=lambda _token: SimpleNamespace(session=fake_session)))

        with patch.object(self.supabase_auth, "get_supabase_client", return_value=fake_client):
            identity = self.supabase_auth.validate_authenticated_session()

        self.assertEqual(identity["provider_user_id"], "refresh-user")
        self.assertEqual(st.session_state[self.supabase_auth.REFRESH_TOKEN_KEY], "new-refresh-token")


if __name__ == "__main__":
    unittest.main()
