"""Claude Agent SDK provider wiring: discovery, registry mirroring, CLI resolution, client factory."""

from __future__ import annotations

import stat

import pytest

from providers import get_provider_profile


@pytest.fixture
def profile():
    found = get_provider_profile("claude-agent-sdk")
    assert found is not None, "bundled claude-agent-sdk plugin was not discovered"
    return found


def test_profile_is_an_external_process_provider(profile):
    assert profile.auth_type == "external_process"
    assert profile.env_vars == ()  # no API key: the subscription login is the credential
    assert profile.process_command == "claude"


@pytest.mark.parametrize("alias", ["claude-max", "claude-subscription", "claude-code-sdk"])
def test_aliases_resolve_to_the_profile(alias):
    assert get_provider_profile(alias).name == "claude-agent-sdk"


def test_registry_mirrors_the_profile_so_resolve_provider_accepts_it():
    from hermes_cli.auth import resolve_provider

    assert resolve_provider("claude-agent-sdk") == "claude-agent-sdk"


def test_catalog_aliases_point_at_declared_models(profile):
    assert profile.model_aliases
    assert set(profile.model_aliases.values()) <= set(profile.fallback_models)


def test_credentials_resolve_the_cli_from_the_override_env(monkeypatch, tmp_path):
    from hermes_cli.auth import resolve_external_process_provider_credentials

    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("HERMES_CLAUDE_SDK_COMMAND", str(fake))
    creds = resolve_external_process_provider_credentials("claude-agent-sdk")
    assert creds["command"] == str(fake)
    assert creds["base_url"].startswith("acp://")


def test_missing_cli_is_an_actionable_auth_error(monkeypatch, tmp_path):
    from hermes_cli.auth import AuthError, resolve_external_process_provider_credentials

    monkeypatch.setenv("PATH", str(tmp_path))  # an empty directory: no `claude` anywhere
    monkeypatch.delenv("HERMES_CLAUDE_SDK_COMMAND", raising=False)
    monkeypatch.delenv("CLAUDE_CLI_PATH", raising=False)
    with pytest.raises(AuthError) as info:
        resolve_external_process_provider_credentials("claude-agent-sdk")
    assert "HERMES_CLAUDE_SDK_COMMAND" in str(info.value)


def test_create_client_builds_the_sdk_client_without_importing_the_sdk(profile, tmp_path):
    client = profile.create_client(
        api_key="claude-agent-sdk", base_url="acp://claude-agent-sdk", command="/x/claude", args=[], cwd=str(tmp_path))
    assert callable(client.chat.completions.create)
    assert client.is_closed is False
