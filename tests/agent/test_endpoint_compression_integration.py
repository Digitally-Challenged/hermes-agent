"""Exercise native startup and route lifecycle, not a duplicate of the wiring under test."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import run_agent  # noqa: F401 -- bootstrap before the per-test home-I/O guard is installed

from agent.agent_init import _build_context_engine, _parse_compression_config
from agent.agent_runtime_helpers import _update_switch_compressor
from agent.route_binding import bind_route_entry, reinstall_runtime_snapshot
from hermes_cli.config import load_config_readonly
from hermes_constants import reset_hermes_home_override, set_hermes_home_override

LOCAL = "http://127.0.0.1:8001/v1"
PROXY = "http://127.0.0.1:8788/v1"
CLOUD = "https://example.com/v1"
WINDOW = 1_000_000
RESERVATION = 32_768
CLOUD_TRIGGER = 483_616


def _write_profile(home, endpoints):
    home.mkdir()
    cfg = {
        "compression": {"threshold": 0.5, "threshold_tokens": None,
                        "endpoint_threshold_tokens": endpoints},
        "custom_providers": [
            {"name": f"route-{i}", "base_url": url, "context_length": WINDOW,
             "models": [{"id": "same-model", "context_length": WINDOW}]}
            for i, url in enumerate((LOCAL, PROXY, CLOUD))
        ],
    }
    # JSON is YAML; use the real loader without adding a second serialization dependency.
    (home / "config.yaml").write_text(json.dumps(cfg), encoding="utf-8")


def _build(cfg, endpoint=CLOUD):
    agent = SimpleNamespace(
        model="same-model", provider="custom", requested_provider="custom",
        api_mode="chat_completions", base_url=endpoint, api_key="",
        quiet_mode=True, session_id="endpoint-test", max_tokens=RESERVATION,
        _custom_providers=cfg.get("custom_providers", []), request_overrides={},
        _config_context_length=WINDOW, _compression_feasibility_checked=False,
    )
    settings = _parse_compression_config(agent, cfg)
    _build_context_engine(agent, cfg, settings, agent._custom_providers, WINDOW, None)
    return agent


def test_real_config_startup_and_context_local_profile_isolation(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write_profile(a, {LOCAL + "/": 120_000})
    _write_profile(b, {})
    agents = []
    for home, expected in ((a, 120_000), (b, CLOUD_TRIGGER), (a, 120_000)):
        token = set_hermes_home_override(home)
        try:
            cfg = load_config_readonly()
            agent = _build(cfg, LOCAL)
            assert agent.context_compressor.threshold_tokens == expected
            agents.append(agent)
        finally:
            reset_hermes_home_override(token)
    # Neither a later profile nor a mutation of its config can alter an existing compressor.
    cfg["compression"]["endpoint_threshold_tokens"][LOCAL + "/"] = 1
    assert agents[0].context_compressor.threshold_tokens == 120_000
    assert agents[1].context_compressor.endpoint_threshold_tokens == {}


def test_real_manual_switch_helper_uses_destination_endpoint(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    _write_profile(home, {LOCAL: 120_000})
    token = set_hermes_home_override(home)
    try:
        agent = _build(load_config_readonly())
        # Feasibility probes are an independent auxiliary-LLM transport concern.
        monkeypatch.setattr("agent.conversation_compression_feasibility.revalidate_compression_feasibility", lambda agent: None)
        for endpoint, expected in ((LOCAL + "/", 120_000), (PROXY, CLOUD_TRIGGER), (CLOUD, CLOUD_TRIGGER)):
            agent.base_url = endpoint
            _update_switch_compressor(agent, agent._custom_providers, WINDOW, {})
            assert agent.context_compressor.threshold_tokens == expected
            assert agent.context_compressor.max_tokens == RESERVATION
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize("endpoint, expected", [(LOCAL + "/", 120_000), (PROXY, CLOUD_TRIGGER)])
def test_real_route_bind_and_snapshot_restore(tmp_path, monkeypatch, endpoint, expected):
    home = tmp_path / "profile"
    _write_profile(home, {LOCAL: 120_000})
    token = set_hermes_home_override(home)
    try:
        agent = _build(load_config_readonly())
        snapshot = {
            "model": agent.model, "provider": agent.provider, "base_url": CLOUD,
            "api_mode": agent.api_mode, "api_key": "", "client_kwargs": {},
            "use_prompt_caching": False, "compressor_model": agent.model,
            "compressor_context_length": WINDOW, "compressor_base_url": CLOUD,
            "compressor_api_key": "", "compressor_provider": agent.provider,
        }
        # Only client/credential boundaries are faked: config, metadata, route binding,
        # fallback compressor update and restoration all execute their real implementations.
        client = SimpleNamespace(base_url=endpoint)
        monkeypatch.setattr("agent.auxiliary_client.resolve_provider_client", lambda *a, **kw: (client, "same-model"))
        monkeypatch.setattr("agent.chat_completion_helpers._rebind_fallback_credential_pool", lambda *a: None)
        monkeypatch.setattr("agent.client_lifecycle._swap_fallback_clients", lambda *a: None)
        monkeypatch.setattr("agent.agent_runtime_helpers.sync_credential_pool_entry_id", lambda *a: None)
        monkeypatch.setattr("agent.agent_runtime_helpers._rebuild_primary_client", lambda *a, **kw: None)
        agent._anthropic_prompt_cache_policy = lambda **kw: (False, False)
        agent._ensure_lmstudio_runtime_loaded = lambda: None
        assert bind_route_entry(agent, {"base_url": endpoint, "api_key": "fixture", "api_mode": "chat_completions"}, "custom", "same-model")
        assert agent.context_compressor.context_length == WINDOW
        assert agent.context_compressor.threshold_tokens == expected
        reinstall_runtime_snapshot(agent, snapshot)
        assert agent.context_compressor.base_url == CLOUD
        assert agent.context_compressor.threshold_tokens == CLOUD_TRIGGER
        assert agent.context_compressor.max_tokens == RESERVATION
    finally:
        reset_hermes_home_override(token)


def test_real_safe_worker_binding_omits_raw_endpoint_map(tmp_path):
    root = Path(__file__).resolve().parents[2]
    code = f'''
from agent.safe_worker_policy import _bind_safe_worker_policy
_bind_safe_worker_policy(safe_mode=True, ignore_user_config=True, config={{}})
from types import SimpleNamespace
from agent.agent_init import _parse_compression_config, _build_context_engine
cfg = {{"compression": {{"threshold_tokens": None, "endpoint_threshold_tokens": {{{LOCAL!r}: 120000}}}}}}
a = SimpleNamespace(model="same-model", provider="custom", api_mode="chat_completions", base_url={LOCAL!r}, api_key="", quiet_mode=True, session_id="safe", max_tokens={RESERVATION})
cs = _parse_compression_config(a, cfg)
_build_context_engine(a, cfg, cs, [], {WINDOW}, None)
assert a.context_compressor.endpoint_threshold_tokens == {{}}
assert a.context_compressor.threshold_tokens == {CLOUD_TRIGGER}
print("safe-worker endpoint policy isolated")
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root,
        env=dict(os.environ, HERMES_HOME=str(tmp_path), HOME=str(tmp_path)),
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "safe-worker endpoint policy isolated" in result.stdout


def test_live_config_updates_and_removes_endpoint_policy(tmp_path):
    from tui_gateway import server

    home = tmp_path / "profile"
    _write_profile(home, {LOCAL: 120_000})
    token = set_hermes_home_override(home)
    try:
        cfg = load_config_readonly()
        agent = _build(cfg, LOCAL)
        cfg["compression"]["endpoint_threshold_tokens"] = {LOCAL + "/": 100_000}
        server._apply_live_compression_config(agent, cfg)
        assert agent.context_compressor.threshold_tokens == 100_000
        cfg["compression"].pop("endpoint_threshold_tokens")
        server._apply_live_compression_config(agent, cfg)
        assert agent.context_compressor.threshold_tokens == CLOUD_TRIGGER
    finally:
        reset_hermes_home_override(token)


def test_endpoint_policy_is_a_gateway_cache_busting_key():
    from gateway.run import GatewayRunner

    assert ("compression", "endpoint_threshold_tokens") in GatewayRunner._CACHE_BUSTING_CONFIG_KEYS
