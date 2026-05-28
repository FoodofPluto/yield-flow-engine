from __future__ import annotations

import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import auth_service


class AuthServiceHardeningTests(unittest.TestCase):
    def test_typed_email_does_not_imply_admin_access(self):
        legacy_user = {
            "email": "admin@example.com",
            "is_admin": True,
            "email_verified": False,
            "_identity_verified": False,
        }

        self.assertFalse(auth_service.is_admin(legacy_user))

    def test_typed_email_does_not_imply_pro_access(self):
        legacy_user = {
            "email": "paid@example.com",
            "is_admin": False,
            "lifetime_access": True,
            "pro_active": True,
            "email_verified": False,
            "_identity_verified": False,
        }

        self.assertFalse(auth_service.can_access_pro(legacy_user))

    def test_dev_mode_crashes_production_boot(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "DEV_MODE": "true"}, clear=False):
            with self.assertRaises(RuntimeError):
                importlib.reload(auth_service)

        with patch.dict(os.environ, {"ENVIRONMENT": "test", "DEV_MODE": "false"}, clear=False):
            importlib.reload(auth_service)

    def test_can_access_pro_requires_verified_identity(self):
        unverified_user = {
            "email": "paid@example.com",
            "is_admin": False,
            "lifetime_access": False,
            "pro_active": True,
            "email_verified": False,
            "_identity_verified": False,
        }
        verified_user = {
            **unverified_user,
            "email_verified": True,
            "provider_user_id": "supabase-user-1",
            "_identity_verified": True,
        }

        self.assertFalse(auth_service.can_access_pro(unverified_user))
        self.assertTrue(auth_service.can_access_pro(verified_user))

    def test_admin_role_cannot_self_bootstrap_without_verified_identity(self):
        legacy_admin_row = {
            "email": "configured-admin@example.com",
            "is_admin": True,
            "email_verified": False,
            "_identity_verified": False,
        }

        self.assertFalse(auth_service.is_admin(legacy_admin_row))

    def test_legacy_auth_flow_still_allows_non_privileged_user_row(self):
        legacy_user = {
            "email": "free@example.com",
            "is_admin": False,
            "lifetime_access": False,
            "pro_active": False,
            "email_verified": False,
            "_identity_verified": False,
        }

        self.assertFalse(auth_service.is_admin(legacy_user))
        self.assertFalse(auth_service.can_access_pro(legacy_user))

    def test_streamlit_apps_import_shared_auth_logic(self):
        root = Path(__file__).resolve().parents[1]
        app_py = (root / "app.py").read_text(encoding="utf-8")
        linkdebug_py = (root / "app_linkdebug.py").read_text(encoding="utf-8")

        for source in (app_py, linkdebug_py):
            self.assertIn("from auth_service import", source)
            self.assertNotIn("from entitlements import can_access_pro", source)
            self.assertNotIn("ADMIN_EMAILS", source)
            self.assertNotIn("from db import claim_session", source)


if __name__ == "__main__":
    unittest.main()
