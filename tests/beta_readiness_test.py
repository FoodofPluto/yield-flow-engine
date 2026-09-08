from __future__ import annotations

from beta_readiness import FailureKind, beta_access, beta_config, beta_diagnostics, failure_presentation
from product_capabilities import ProductTier, capability_presentation, capabilities_for_tier


def test_beta_diagnostics_exposes_only_safe_environment_driven_values() -> None:
    diagnostics = beta_diagnostics(
        {
            "ENVIRONMENT": "staging",
            "RENDER_GIT_COMMIT": "abcdef0123456789abcdef0123456789abcdef01",
            "FURUFLOW_SUPPORT_URL": "https://support.example.test/beta?product=furuflow",
            "SUPABASE_SERVICE_ROLE_KEY": "must-not-appear",
        },
        app_version="v-test",
    )

    assert diagnostics.environment == "Staging"
    assert diagnostics.app_version == "v-test"
    assert diagnostics.build_id == "abcdef012345"
    assert diagnostics.support_url == "https://support.example.test/beta?product=furuflow"
    assert "must-not-appear" not in repr(diagnostics)


def test_beta_diagnostics_rejects_unsafe_or_unconfigured_destinations_and_builds() -> None:
    diagnostics = beta_diagnostics(
        {
            "ENVIRONMENT": "custom-secret-environment",
            "FURUFLOW_BUILD_ID": "build id with spaces and credentials",
            "FURUFLOW_SUPPORT_URL": "http://user:password@example.test/support",
        },
        app_version="v-test",
    )

    assert diagnostics.environment == "Unspecified"
    assert diagnostics.build_id is None
    assert diagnostics.support_url is None


def test_account_presentation_uses_the_canonical_four_tier_capability_matrix() -> None:
    presentations = {
        tier: capability_presentation(capabilities_for_tier(tier))
        for tier in ProductTier
    }

    assert presentations[ProductTier.FREE]["plan"] == "Free"
    assert "Durable Watchlists" not in presentations[ProductTier.FREE]["included"]
    assert "Durable Watchlists" in presentations[ProductTier.CORE]["included"]
    assert "Telegram Alerts" not in presentations[ProductTier.CORE]["included"]
    assert "Telegram Alerts" in presentations[ProductTier.PLUS]["included"]
    assert "CSV export" not in presentations[ProductTier.PLUS]["included"]
    assert "CSV export" in presentations[ProductTier.PRO]["included"]


def test_closed_beta_config_is_uuid_allowlisted_and_invitation_only_by_default() -> None:
    participant_id = "9dadb18d-37bd-4b48-b6f0-f5947fab6e85"
    config = beta_config(
        {
            "FURUFLOW_BETA_ENABLED": "true",
            "FURUFLOW_BETA_ALLOWED_USER_IDS": participant_id.upper(),
            "FURUFLOW_BETA_LABEL": "Closed Beta",
        }
    )

    assert config.enabled is True
    assert config.allowed_user_ids == frozenset({participant_id})
    assert config.allow_signup is False
    assert config.label == "Closed Beta"
    assert config.errors == ()


def test_closed_beta_configuration_fails_closed_without_valid_participants() -> None:
    config = beta_config(
        {
            "FURUFLOW_BETA_ENABLED": "true",
            "FURUFLOW_BETA_ALLOWED_USER_IDS": "not-an-email-or-uuid",
            "FURUFLOW_BETA_LABEL": "<script>not safe</script>",
        }
    )

    assert config.label == "Closed Beta"
    assert config.allowed_user_ids == frozenset()
    assert len(config.errors) == 2
    assert beta_access(config, None).reason == "configuration_unavailable"


def test_beta_access_is_separate_from_paid_tier_and_does_not_enumerate_accounts() -> None:
    participant_id = "9dadb18d-37bd-4b48-b6f0-f5947fab6e85"
    config = beta_config(
        {"FURUFLOW_BETA_ENABLED": "true", "FURUFLOW_BETA_ALLOWED_USER_IDS": participant_id}
    )
    participant = {
        "provider_user_id": participant_id,
        "_identity_verified": True,
        "_account_authority": "supabase",
        "pro_active": False,
    }
    rejected = {
        "provider_user_id": "ab22f72e-161b-4533-a727-866680d8af45",
        "_identity_verified": True,
        "_account_authority": "supabase",
        "pro_active": True,
        "email": "must-not-appear@example.invalid",
    }

    assert beta_access(config, participant).reason == "allowlisted"
    denied = beta_access(config, rejected)
    assert denied.allowed is False
    assert denied.reason == "beta_access_required"
    assert "email" not in repr(denied)


def test_verified_admin_remains_separately_protected_and_beta_accepted() -> None:
    config = beta_config(
        {
            "FURUFLOW_BETA_ENABLED": "true",
            "FURUFLOW_BETA_ALLOWED_USER_IDS": "9dadb18d-37bd-4b48-b6f0-f5947fab6e85",
        }
    )
    untrusted_admin = {"_identity_verified": True, "is_admin": True, "_account_authority": "unavailable"}
    trusted_admin = {"_identity_verified": True, "is_admin": True, "_account_authority": "supabase"}

    assert beta_access(config, untrusted_admin).allowed is False
    assert beta_access(config, trusted_admin).reason == "verified_admin"


def test_maintenance_copy_is_bounded_and_control_characters_are_removed() -> None:
    config = beta_config({"FURUFLOW_MAINTENANCE_MESSAGE": "  Planned\nmaintenance\twindow  " + "x" * 300})

    assert config.maintenance_message is not None
    assert "\n" not in config.maintenance_message
    assert len(config.maintenance_message) == 240


def test_operational_failure_taxonomy_has_specific_recovery_for_every_required_state() -> None:
    presentations = {kind: failure_presentation(kind) for kind in FailureKind}

    assert set(presentations) == set(FailureKind)
    assert presentations[FailureKind.NO_DATA].title == "No data"
    assert presentations[FailureKind.INSUFFICIENT_EVIDENCE].title == "Insufficient evidence"
    assert presentations[FailureKind.STALE_DATA].status_kind == "stale"
    assert "No current values were inferred" in presentations[FailureKind.PROVIDER_UNAVAILABLE].message
    assert "stopped this refresh" in presentations[FailureKind.RATE_LIMITED].message
    assert "sign in" in presentations[FailureKind.AUTHENTICATION_REQUIRED].action
    assert "capability" in presentations[FailureKind.AUTHORIZATION_REQUIRED].message
    assert "server-side" in presentations[FailureKind.CONFIGURATION_UNAVAILABLE].message
    assert all(presentation.action for presentation in presentations.values())
