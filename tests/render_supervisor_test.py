from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pytest

from deploy.render.supervise import (
    INTERNAL_BROKER_URL,
    ManagedChild,
    _signal_child,
    _specs,
    build_child_environments,
    render_nginx_config,
)


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
        "FURUFLOW_HISTORY_PATH": "/tmp/furuflow/pool_history.json",
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
    assert streamlit["FURUFLOW_HISTORY_PATH"] == "/tmp/furuflow/pool_history.json"

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
    assert "location = /auth/session {" in rendered
    assert "location ^~ /auth/session/" in rendered
    assert "location = /billing/checkout" in rendered
    assert "location = /billing/portal" in rendered
    assert "location = /stripe/webhook" in rendered
    assert "proxy_pass http://127.0.0.1:8510;" in rendered
    assert "proxy_pass http://127.0.0.1:8501;" in rendered
    assert "proxy_set_header Upgrade $http_upgrade;" in rendered
    assert "access_log off;" in rendered
    exact_activation_start = rendered.index("location = /auth/session/activate")
    blocked_session_root_start = rendered.index("location = /auth/session {")
    blocked_activation_start = rendered.index("location ^~ /auth/session/")
    streamlit_start = rendered.index("location / {")
    assert exact_activation_start < blocked_session_root_start < blocked_activation_start < streamlit_start
    activation_location = rendered[exact_activation_start:blocked_session_root_start]
    assert "access_log off;" in activation_location
    assert "error_log /dev/null crit;" in activation_location
    assert "proxy_pass http://127.0.0.1:8510;" in activation_location
    blocked_locations = (
        rendered[blocked_session_root_start:blocked_activation_start],
        rendered[blocked_activation_start:streamlit_start],
    )
    for blocked_location in blocked_locations:
        assert 'return 404 "Session activation unavailable.\\n";' in blocked_location
        assert 'add_header Cache-Control "no-store" always;' in blocked_location
        assert 'add_header Referrer-Policy "no-referrer" always;' in blocked_location
        assert 'add_header X-Content-Type-Options "nosniff" always;' in blocked_location
        assert "proxy_pass http://127.0.0.1:8501;" not in blocked_location


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


def test_supervisor_shutdown_retries_permission_denied_signal_as_child_user() -> None:
    process = Mock(pid=42)
    process.send_signal.side_effect = PermissionError(1, "Operation not permitted")
    child = ManagedChild("streamlit", process, "furuflow-streamlit")
    completed = Mock(returncode=0)

    with patch("deploy.render.supervise.subprocess.run", return_value=completed) as run:
        assert _signal_child(child, 15) is True

    run.assert_called_once()
    argv = run.call_args.args[0]
    assert argv == ("kill", "-TERM", "42")
    assert run.call_args.kwargs["preexec_fn"] is not None


def test_supervisor_shutdown_permission_failure_is_controlled() -> None:
    process = Mock(pid=43)
    process.send_signal.side_effect = PermissionError(1, "Operation not permitted")

    assert _signal_child(ManagedChild("nginx", process, None), 15) is False


def test_supervisor_rejects_live_billing_credentials_in_staging() -> None:
    environment = {**_environment(), "STRIPE_SECRET_KEY": "sk_live_" + "L" * 32}
    with pytest.raises(RuntimeError, match="billing configuration"):
        build_child_environments(environment)


def test_supervisor_rejects_enabled_beta_without_an_allowlist() -> None:
    environment = {**_environment(), "FURUFLOW_BETA_ENABLED": "true"}

    with pytest.raises(RuntimeError, match="closed-beta configuration"):
        build_child_environments(environment)


def test_supervisor_accepts_enabled_beta_with_uuid_allowlist() -> None:
    environment = {
        **_environment(),
        "FURUFLOW_BETA_ENABLED": "true",
        "FURUFLOW_BETA_ALLOWED_USER_IDS": "9dadb18d-37bd-4b48-b6f0-f5947fab6e85",
    }

    streamlit, _broker, _nginx = build_child_environments(environment)

    assert streamlit["FURUFLOW_BETA_ENABLED"] == "true"
    assert streamlit["FURUFLOW_BETA_ALLOWED_USER_IDS"] == "9dadb18d-37bd-4b48-b6f0-f5947fab6e85"


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
    assert "FURUFLOW_HISTORY_PATH\n        value: /tmp/furuflow/pool_history.json" in blueprint
    assert "dockerfilePath: ./deploy/render/Dockerfile" in blueprint


def test_container_keeps_application_source_read_only_and_does_not_prepare_history_beside_code() -> None:
    dockerfile = Path("deploy/render/Dockerfile").read_text(encoding="utf-8")

    assert "chmod -R a+rX /app" in dockerfile
    assert "touch /app/pool_history.json" not in dockerfile
    assert "chown furuflow-streamlit:furuflow-streamlit /app/pool_history.json" not in dockerfile
