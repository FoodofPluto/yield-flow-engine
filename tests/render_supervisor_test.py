from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from deploy.render.supervise import INTERNAL_BROKER_URL, _specs, build_child_environments, render_nginx_config


def _environment() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin",
        "PORT": "10000",
        "ENVIRONMENT": "staging",
        "DEV_MODE": "false",
        "SUPABASE_URL": "https://staging.invalid",
        "SUPABASE_ANON_KEY": "anon-test-value",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-test-value",
        "SUPABASE_REDIRECT_URL_PREVIEW": "https://staging.invalid",
        "SUPABASE_REDIRECT_URL_PRODUCTION": "https://staging.invalid",
        "FURUFLOW_SESSION_BROKER_INTERNAL_URL": INTERNAL_BROKER_URL,
        "FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN": "https://staging.invalid",
        "FURUFLOW_SESSION_ENCRYPTION_KEY": "encryption-test-value",
        "FURUFLOW_SESSION_BRIDGE_KEY": "bridge-test-value-that-is-long-enough",
        "STRIPE_SECRET_KEY": "sk_test_" + "S" * 32,
        "STRIPE_WEBHOOK_SECRET": "whsec_" + "W" * 32,
        "STRIPE_PRICE_ID": "price_" + "P" * 24,
        "STRIPE_PRODUCT_ID": "prod_" + "R" * 24,
    }


def test_child_environments_preserve_broker_only_credentials() -> None:
    streamlit, broker, nginx = build_child_environments(_environment())

    assert streamlit["FURUFLOW_SESSION_BROKER_INTERNAL_URL"] == "http://127.0.0.1:8510"
    assert "SUPABASE_SERVICE_ROLE_KEY" not in streamlit
    assert "FURUFLOW_SESSION_ENCRYPTION_KEY" not in streamlit
    assert "STRIPE_SECRET_KEY" not in streamlit
    assert "STRIPE_WEBHOOK_SECRET" not in streamlit
    assert streamlit["FURUFLOW_SESSION_BRIDGE_KEY"].startswith("bridge-test")

    assert broker["SUPABASE_SERVICE_ROLE_KEY"] == "service-role-test-value"
    assert broker["FURUFLOW_SESSION_ENCRYPTION_KEY"] == "encryption-test-value"
    assert broker["STRIPE_SECRET_KEY"].startswith("sk_test_")
    assert "SUPABASE_ANON_KEY" not in broker
    assert "SUPABASE_REDIRECT_URL_PREVIEW" not in broker

    assert not any(key.startswith("SUPABASE_") or key.startswith("FURUFLOW_") for key in nginx)


def test_nginx_template_keeps_broker_internal_and_websockets_enabled() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        template = Path("deploy/render/nginx.conf.template")
        destination = Path(directory) / "furuflow.conf"
        render_nginx_config(template, destination, "10000")
        rendered = destination.read_text(encoding="utf-8")

    assert "listen 10000;" in rendered
    assert "location = /v1/session" in rendered
    assert "location ^~ /v1/session/" in rendered
    assert "location = /auth/session/activate" in rendered
    assert "location = /billing/checkout" in rendered
    assert "location = /billing/portal" in rendered
    assert "location = /stripe/webhook" in rendered
    assert "proxy_pass http://127.0.0.1:8510;" in rendered
    assert "proxy_pass http://127.0.0.1:8501;" in rendered
    assert "proxy_set_header Upgrade $http_upgrade;" in rendered
    assert "access_log off;" in rendered


def test_nginx_config_rejects_invalid_port() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        with pytest.raises(RuntimeError, match="PORT"):
            render_nginx_config(
                Path("deploy/render/nginx.conf.template"), Path(directory) / "furuflow.conf", "not-a-port"
            )


def test_supervisor_binds_only_nginx_to_the_public_interface() -> None:
    streamlit, broker, nginx = build_child_environments(_environment())
    specs = {spec.name: spec for spec in _specs(streamlit, broker, nginx)}

    assert "127.0.0.1:8510" in specs["session-broker"].argv
    assert "127.0.0.1" in specs["streamlit"].argv
    assert "8501" in specs["streamlit"].argv
    assert specs["nginx"].argv == ("nginx", "-g", "daemon off;")
    assert specs["session-broker"].user == "furuflow-broker"
    assert specs["streamlit"].user == "furuflow-streamlit"


def test_supervisor_rejects_live_billing_credentials_in_staging() -> None:
    environment = {**_environment(), "STRIPE_SECRET_KEY": "sk_live_" + "L" * 32}
    with pytest.raises(RuntimeError, match="billing configuration"):
        build_child_environments(environment)


def test_blueprint_isolates_free_web_service_from_durable_cron_worker() -> None:
    blueprint = Path("render.yaml").read_text(encoding="utf-8")

    assert blueprint.count("- type: web") == 1
    assert blueprint.count("- type: cron") == 1
    assert "type: pserv" not in blueprint
    assert "plan: free" in blueprint
    assert "name: furuflow-telegram-worker-staging" in blueprint
    assert "plan: starter" in blueprint
    assert "dockerCommand: python telegram_worker.py run" in blueprint
    assert 'FURUFLOW_SYSTEM_TELEGRAM_RULE_ENABLED\n        value: "false"' in blueprint
    assert "dockerfilePath: ./deploy/render/Dockerfile" in blueprint
