from __future__ import annotations

from beta_readiness import beta_diagnostics
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
