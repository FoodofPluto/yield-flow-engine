from __future__ import annotations

import base64
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import supabase_client

PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_" + "A" * 32


def _env(environment: str = "test") -> dict[str, str]:
    env = {
        "ENVIRONMENT": environment,
        "DEV_MODE": "false",
        "SUPABASE_URL": PROJECT_URL,
        "SUPABASE_ANON_KEY": PUBLISHABLE_KEY,
    }
    redirect_name = supabase_client.REDIRECT_ENV_BY_ENVIRONMENT[environment]
    env[redirect_name] = {
        "test": "http://localhost:8501",
        "development": "http://localhost:8501",
        "preview": "https://preview.furuflow.example/callback",
        "staging": "https://preview.furuflow.example/callback",
        "production": "https://app.furuflow.example/callback",
    }[environment]
    return env


@pytest.mark.parametrize("path", ["/rest/v1", "/rest/v1/", "/auth/v1", "/storage/v1/object"])
def test_project_url_rejects_every_api_subpath(path: str) -> None:
    env = _env("production")
    env["SUPABASE_URL"] = PROJECT_URL + path

    errors = supabase_client.auth_configuration_errors(env)

    assert any("project root" in error for error in errors)


@pytest.mark.parametrize(
    "url",
    ["not-a-url", "ftp://abcdefghijklmnopqrst.supabase.co", "https://", "https://user:pass@host.example"],
)
def test_project_url_rejects_malformed_or_unsafe_values(url: str) -> None:
    env = _env()
    env["SUPABASE_URL"] = url

    assert supabase_client.auth_configuration_errors(env)


@pytest.mark.parametrize(
    "key",
    ["anon", "your-public-anon-key", "placeholder", "sb_secret_" + "A" * 32, "not-a-provider-key"],
)
def test_public_key_rejects_placeholders_secrets_and_malformed_values(key: str) -> None:
    env = _env()
    env["SUPABASE_ANON_KEY"] = key

    assert supabase_client.auth_configuration_errors(env)


def test_missing_values_fail_healthcheck() -> None:
    with patch.dict(os.environ, {"ENVIRONMENT": "test", "DEV_MODE": "false"}, clear=True):
        health = supabase_client.healthcheck_auth()

    assert not health["ok"]
    assert "SUPABASE_URL" in health["configuration_errors"][0]
    assert "SUPABASE_ANON_KEY" in health["configuration_errors"][0]


def test_production_rejects_dev_mode_and_local_redirect() -> None:
    env = _env("production")
    env["DEV_MODE"] = "true"
    env["SUPABASE_REDIRECT_URL_PRODUCTION"] = "http://localhost:8501"

    errors = supabase_client.auth_configuration_errors(env)

    assert any("DEV_MODE=true" in error for error in errors)
    assert any("HTTPS" in error for error in errors)
    assert any("loopback" in error for error in errors)


def test_environment_selects_explicit_redirect_configuration() -> None:
    assert supabase_client.load_auth_config(_env("development")).redirect_env_name == (
        "SUPABASE_REDIRECT_URL_DEVELOPMENT"
    )
    assert supabase_client.load_auth_config(_env("preview")).redirect_env_name == "SUPABASE_REDIRECT_URL_PREVIEW"
    assert supabase_client.load_auth_config(_env("production")).redirect_env_name == (
        "SUPABASE_REDIRECT_URL_PRODUCTION"
    )


def test_configured_jwks_must_match_project_root() -> None:
    env = _env()
    env["SUPABASE_JWKS_URL"] = "https://different.example/auth/v1/.well-known/jwks.json"

    assert "must match" in " ".join(supabase_client.auth_configuration_errors(env))


def test_legacy_anon_jwt_project_reference_must_match_url() -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"role": "anon", "ref": "differentref"}).encode()).decode().rstrip("=")
    env = _env()
    env["SUPABASE_ANON_KEY"] = f"{header}.{payload}.{'s' * 32}"

    assert "does not match" in " ".join(supabase_client.auth_configuration_errors(env))


def test_connectivity_diagnostics_cover_dns_auth_jwks_and_key_coherence() -> None:
    env = _env()

    def fake_get(url: str, **_kwargs):
        if url.endswith("/.well-known/jwks.json"):
            return SimpleNamespace(status_code=200, json=lambda: {"keys": [{"kid": "one"}]})
        return SimpleNamespace(status_code=200, json=lambda: {})

    with patch.dict(os.environ, env, clear=True):
        with patch.object(supabase_client.socket, "getaddrinfo", return_value=[("resolved",)]):
            with patch.object(supabase_client.requests, "get", side_effect=fake_get) as request:
                result = supabase_client.diagnose_auth_connectivity()

    assert result["ok"]
    assert {check["name"] for check in result["checks"]} == {
        "dns_resolution",
        "auth_health",
        "jwks_availability",
        "project_url_key_coherence",
    }
    assert request.call_count == 3


def test_dns_failure_prevents_requests_and_fails_diagnostics() -> None:
    with patch.dict(os.environ, _env(), clear=True):
        with patch.object(supabase_client.socket, "getaddrinfo", side_effect=OSError):
            with patch.object(supabase_client.requests, "get") as request:
                result = supabase_client.diagnose_auth_connectivity()

    assert not result["ok"]
    request.assert_not_called()


def test_project_key_coherence_http_failure_is_observable_without_response_body() -> None:
    responses = [
        SimpleNamespace(status_code=200, json=lambda: {}),
        SimpleNamespace(status_code=200, json=lambda: {"keys": [{"kid": "one"}]}),
        SimpleNamespace(status_code=401, json=lambda: {"sensitive": "must not escape"}),
    ]
    with patch.dict(os.environ, _env(), clear=True):
        with patch.object(supabase_client.socket, "getaddrinfo", return_value=[("resolved",)]):
            with patch.object(supabase_client.requests, "get", side_effect=responses):
                result = supabase_client.diagnose_auth_connectivity()

    assert not result["ok"]
    serialized = json.dumps(result)
    assert "sensitive" not in serialized
    assert PUBLISHABLE_KEY not in serialized


def test_supabase_clients_are_isolated_per_operation() -> None:
    created = [Mock(name="client_one"), Mock(name="client_two")]
    with patch.dict(os.environ, _env(), clear=True):
        with patch("supabase.create_client", side_effect=created) as create:
            first = supabase_client.get_supabase_client()
            second = supabase_client.get_supabase_client()

    assert first is created[0]
    assert second is created[1]
    assert create.call_count == 2
    assert create.call_args_list[0].kwargs["options"].auto_refresh_token is False


def test_production_startup_rejects_api_subpath() -> None:
    env = _env("production")
    env["SUPABASE_URL"] = PROJECT_URL + "/rest/v1"
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(supabase_client.AuthConfigurationError):
            supabase_client.require_production_auth_config()
