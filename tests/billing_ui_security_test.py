from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_ui_uses_fixed_post_routes_without_static_payment_links_or_browser_identifiers() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    legacy_app = (ROOT / "app_linkdebug.py").read_text(encoding="utf-8")
    rendered_sources = app + legacy_app
    assert "buy.stripe.com" not in rendered_sources
    assert "prefilled_email" not in rendered_sources
    assert "client_reference_id=" not in rendered_sources
    assert 'action="/billing/checkout"' in rendered_sources
    assert '"/billing/portal"' in app
    assert "stripe_customer_id" not in app
    assert "stripe_subscription_id" not in app


def test_billing_urls_and_backend_errors_are_safe_and_non_authoritative() -> None:
    service = (ROOT / "billing_service.py").read_text(encoding="utf-8")
    broker = (ROOT / "session_broker.py").read_text(encoding="utf-8")
    assert "/?billing=return" in service
    assert "/?billing=cancelled" in service
    assert "success=true" not in service
    assert "payment=success" not in service
    assert "raw provider" not in broker.lower()
    assert "Stripe-Signature" not in (ROOT / "deploy/render/nginx.conf.template").read_text(encoding="utf-8")


def test_prompt8_migration_preserves_manual_access_and_denies_browser_writes() -> None:
    sql = (ROOT / "supabase/migrations/202608170002_prompt8_production_billing.sql").read_text(encoding="utf-8")
    assert "subscription_pro_active" in sql
    assert "update public.entitlements set subscription_pro_active = now_active" in sql
    assert "set pro_active = now_active" not in sql
    assert "last_provider_event_created" in sql
    assert "provider event user mapping mismatch" in sql
    assert "revoke all on function public.service_apply_stripe_subscription" in sql
    assert "from public, anon, authenticated" in sql
