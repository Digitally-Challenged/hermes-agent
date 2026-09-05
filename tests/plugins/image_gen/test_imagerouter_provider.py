"""Tests for the bundled ImageRouter image_gen plugin.

Invariants only — no snapshots of the live catalog. ImageRouter speaks the
OpenAI images protocol, so the plugin drives it through the openai SDK the
same way the DeepInfra backend does. These tests pin the ImageRouter-specific
contract: endpoint and key, aspect-ratio → size mapping, model precedence,
the unfiltered default, catalog shaping for the ``hermes tools`` picker, and
the saved-file path in ``image`` that the gateway auto-attaches.
"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

import plugins.image_gen.imagerouter as ir_plugin

# 1×1 transparent PNG — valid bytes for save_b64_image()
_PNG_HEX = (
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6300010000000500010d0a2db40000000049454e44"
    "ae426082"
)
_PNG_BYTES = bytes.fromhex(_PNG_HEX)

# Mirrors the shape of GET https://api.imagerouter.io/v1/models: a dict keyed
# by model id. Dict order deliberately lists a filtered image model BEFORE the
# unfiltered one so ordering is observable.
_CATALOG = {
    "some-lab/chat-model": {
        "providers": [{"id": "some-lab", "pricing": {"type": "fixed", "value": 0.001}}],
        "arena_score": None,
        "release_date": "2026-01-01",
        "output": ["text"],
        "supported_params": {},
    },
    "big-vendor/filtered-image": {
        "providers": [{"id": "big-vendor", "pricing": {"type": "fixed", "value": 0.04}}],
        "arena_score": 1100,
        "release_date": "2026-02-01",
        "output": ["image"],
        "supported_params": {"quality": True, "size": True},
    },
    "run-diffusion/Juggernaut-Pro-Flux": {
        "providers": [{"id": "run-diffusion", "pricing": {"type": "fixed", "value": 0.0079}}],
        "arena_score": None,
        "release_date": "2025-06-01",
        "output": ["image"],
        "supported_params": {"size": True},
    },
}


def _b64_png() -> str:
    return base64.b64encode(_PNG_BYTES).decode()


@pytest.fixture(autouse=True)
def _isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("IMAGEROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ir_plugin, "_catalog_cache", {})
    yield


class _FakeSDK:
    """Stand-in for the ``openai`` package: records client construction and
    every ``images.generate`` call; replies with a canned response or error."""

    def __init__(self, response=None, error: Exception | None = None):
        self.calls: list = []
        self.client_kwargs: dict | None = None
        sdk = self

        class _Images:
            def generate(_self, **kwargs):
                sdk.calls.append(kwargs)
                if error is not None:
                    raise error
                return response

        class _Client:
            def __init__(_self, api_key=None, base_url=None, **kw):
                sdk.client_kwargs = {"api_key": api_key, "base_url": base_url, **kw}
                _self.images = _Images()

            def close(_self):
                pass

        self.module = MagicMock()
        self.module.OpenAI = _Client


def _b64_response():
    return SimpleNamespace(data=[SimpleNamespace(b64_json=_b64_png(), url=None)])


def _generate(sdk: _FakeSDK, **kwargs):
    with patch.dict("sys.modules", {"openai": sdk.module}):
        return ir_plugin.ImageRouterImageGenProvider().generate(**kwargs)


class _CatalogResponse:
    def __init__(self, payload=None):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _serve_catalog(monkeypatch, payload=_CATALOG):
    calls: list = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        return _CatalogResponse(payload)

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


# ── identity / availability ─────────────────────────────────────────────────


def test_is_available_tracks_the_api_key(monkeypatch):
    provider = ir_plugin.ImageRouterImageGenProvider()
    assert provider.is_available() is True
    monkeypatch.delenv("IMAGEROUTER_API_KEY")
    assert provider.is_available() is False


def test_setup_schema_prompts_for_the_imagerouter_key():
    schema = ir_plugin.ImageRouterImageGenProvider().get_setup_schema()
    assert {e["key"] for e in schema["env_vars"]} == {"IMAGEROUTER_API_KEY"}


def test_capabilities_advertise_text_to_image_only():
    assert ir_plugin.ImageRouterImageGenProvider().capabilities() == {
        "modalities": ["text"],
        "max_reference_images": 0,
    }


def test_register_wires_the_provider_into_the_registry():
    ctx = MagicMock()
    ir_plugin.register(ctx)
    ctx.register_image_gen_provider.assert_called_once()
    (registered,), _ = ctx.register_image_gen_provider.call_args
    assert registered.name == "imagerouter"


# ── catalog (hermes tools picker) ───────────────────────────────────────────


def test_list_models_keeps_image_models_with_unfiltered_first(monkeypatch):
    _serve_catalog(monkeypatch)
    rows = ir_plugin.ImageRouterImageGenProvider().list_models()
    assert [r["id"] for r in rows] == [
        "run-diffusion/Juggernaut-Pro-Flux",
        "big-vendor/filtered-image",
    ]
    assert rows[0]["price"] == "$0.0079/image"


def test_range_priced_models_show_their_average_price(monkeypatch):
    """ImageRouter prices most community models as a post-generation range
    ({"type": "post_generation", "range": {"min", "average", "max"}}); the
    default model is one of them, so a value-only reader shows no price."""
    catalog = {
        "run-diffusion/Juggernaut-Pro-Flux": {
            "providers": [
                {
                    "id": "run-diffusion",
                    "pricing": {
                        "type": "post_generation",
                        "range": {"min": 0.0025, "average": 0.005, "max": 0.038},
                    },
                }
            ],
            "arena_score": None,
            "release_date": "2025-06-01",
            "output": ["image"],
            "supported_params": {"size": True},
        },
    }
    _serve_catalog(monkeypatch, catalog)
    (row,) = ir_plugin.ImageRouterImageGenProvider().list_models()
    assert row["price"] == "~$0.0050/image"


def test_list_models_is_empty_when_the_catalog_is_unreachable(monkeypatch):
    def fake_get(url, *args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fake_get)
    assert ir_plugin.ImageRouterImageGenProvider().list_models() == []


def test_catalog_is_fetched_once_within_the_ttl(monkeypatch):
    calls = _serve_catalog(monkeypatch)
    provider = ir_plugin.ImageRouterImageGenProvider()
    provider.list_models()
    provider.list_models()
    assert len(calls) == 1


def test_default_model_is_unfiltered_and_needs_no_catalog(monkeypatch):
    def fake_get(url, *args, **kwargs):
        raise AssertionError("default_model must not hit the network")

    monkeypatch.setattr(requests, "get", fake_get)
    assert ir_plugin.ImageRouterImageGenProvider().default_model() in ir_plugin.UNFILTERED_MODELS


# ── generate: request contract ──────────────────────────────────────────────


def test_generate_sends_the_request_to_imagerouters_openai_endpoint():
    sdk = _FakeSDK(_b64_response())
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")

    assert result["success"] is True
    assert sdk.client_kwargs["api_key"] == "test-key"
    assert sdk.client_kwargs["base_url"] == "https://api.imagerouter.io/v1/openai"
    (call,) = sdk.calls
    assert call["prompt"] == "a cat"
    assert call["model"] in ir_plugin.UNFILTERED_MODELS
    assert call["size"] == "1024x1024"
    assert call["n"] == 1
    assert call["response_format"] == "b64_json"


def test_generate_makes_a_single_attempt_on_the_metered_api():
    """The openai SDK retries 5xx/408/429/timeouts three times by default. A
    generation that timed out but completed server-side would then be billed
    again on every retry, so the client must be built to make one attempt."""
    sdk = _FakeSDK(_b64_response())
    _generate(sdk, prompt="a cat", aspect_ratio="square")
    assert sdk.client_kwargs["max_retries"] == 0


@pytest.mark.parametrize(
    "aspect, size",
    [("square", "1024x1024"), ("landscape", "1344x768"), ("portrait", "768x1344")],
)
def test_aspect_ratio_maps_to_a_flux_bucket_size(aspect, size):
    sdk = _FakeSDK(_b64_response())
    _generate(sdk, prompt="a cat", aspect_ratio=aspect)
    assert sdk.calls[0]["size"] == size


def test_generate_returns_the_absolute_path_of_the_saved_png(tmp_path):
    sdk = _FakeSDK(_b64_response())
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")

    saved = Path(result["image"])
    assert saved.is_absolute()
    assert saved.parent == tmp_path / "cache" / "images"
    assert saved.suffix == ".png"
    assert saved.read_bytes() == _PNG_BYTES
    assert result["provider"] == "imagerouter"
    assert result["model"] == sdk.calls[0]["model"]


def test_url_only_response_is_downloaded_into_the_cache(tmp_path, monkeypatch):
    class _Download:
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield _PNG_BYTES

    fetched: list = []

    def fake_get(url, *args, **kwargs):
        fetched.append(url)
        return _Download()

    monkeypatch.setattr(requests, "get", fake_get)
    sdk = _FakeSDK(
        SimpleNamespace(data=[SimpleNamespace(b64_json=None, url="https://cdn.example/out.png")])
    )
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")

    assert fetched == ["https://cdn.example/out.png"]
    saved = Path(result["image"])
    assert saved.parent == tmp_path / "cache" / "images"
    assert saved.read_bytes() == _PNG_BYTES


# ── generate: model precedence ──────────────────────────────────────────────


def _write_config(tmp_path: Path, model: str) -> None:
    (tmp_path / "config.yaml").write_text(
        f"image_gen:\n  provider: imagerouter\n  imagerouter:\n    model: {model}\n",
        encoding="utf-8",
    )


def test_configured_model_overrides_the_default(tmp_path):
    _write_config(tmp_path, "vendor/pinned")
    sdk = _FakeSDK(_b64_response())
    _generate(sdk, prompt="a cat", aspect_ratio="square")
    assert sdk.calls[0]["model"] == "vendor/pinned"


def test_explicit_model_kwarg_overrides_the_configured_model(tmp_path):
    _write_config(tmp_path, "vendor/pinned")
    sdk = _FakeSDK(_b64_response())
    _generate(sdk, prompt="a cat", aspect_ratio="square", model="vendor/explicit")
    assert sdk.calls[0]["model"] == "vendor/explicit"


# ── generate: errors ────────────────────────────────────────────────────────


def test_missing_key_is_reported_without_calling_the_api(monkeypatch):
    monkeypatch.delenv("IMAGEROUTER_API_KEY")
    sdk = _FakeSDK(_b64_response())
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")

    assert result["success"] is False
    assert result["error_type"] == "auth_required"
    assert sdk.client_kwargs is None
    assert sdk.calls == []


def test_api_failure_is_reported_without_leaking_the_key():
    sdk = _FakeSDK(error=RuntimeError("401 Unauthorized for key test-key"))
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")

    assert result["success"] is False
    assert result["error_type"] == "api_error"
    assert "401" in result["error"]
    assert "test-key" not in result["error"]


def test_empty_response_is_reported_as_empty():
    sdk = _FakeSDK(SimpleNamespace(data=[]))
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")
    assert result["success"] is False
    assert result["error_type"] == "empty_response"


def test_image_to_image_is_rejected_before_any_request():
    sdk = _FakeSDK(_b64_response())
    result = _generate(
        sdk, prompt="a cat", aspect_ratio="square", image_url="https://x/y.png"
    )
    assert result["success"] is False
    assert result["error_type"] == "modality_unsupported"
    assert sdk.calls == []


def test_empty_prompt_is_rejected_before_any_request():
    sdk = _FakeSDK(_b64_response())
    result = _generate(sdk, prompt="   ", aspect_ratio="square")
    assert result["success"] is False
    assert result["error_type"] == "invalid_argument"
    assert sdk.calls == []


# ── manifest (through the real plugin loader, not by grepping YAML) ─────────


def test_bundled_manifest_is_an_auto_loading_backend_that_declares_its_key():
    from hermes_cli.plugins import PluginManager

    manifests = {m.key or m.name: m for m in PluginManager()._collect_directory_manifests()}
    manifest = manifests["image_gen/imagerouter"]
    assert manifest.kind == "backend"
    assert "IMAGEROUTER_API_KEY" in manifest.requires_env


def test_client_construction_failure_is_reported_without_leaking_the_key():
    """The SDK client is built with the key in hand; a failure there must be
    caught and scrubbed like any other SDK failure, not escape to the tool
    dispatcher, which echoes exception text to the model."""
    sdk = _FakeSDK(_b64_response())

    class _Boom:
        def __init__(self, api_key=None, base_url=None, **_kw):
            raise RuntimeError(f"client init failed for {api_key}")

    sdk.module.OpenAI = _Boom
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")
    assert result["success"] is False
    assert result["error_type"] == "api_error"
    assert "test-key" not in result["error"]


# ── the whole delivery chain ────────────────────────────────────────────────


def test_image_generate_result_reaches_the_gateway_attachment_without_a_media_tag(
    tmp_path, monkeypatch
):
    """config.yaml selects the provider → the built-in image_generate handler
    discovers the bundled plugin and dispatches through the registry → the
    gateway extracts the saved path from the JSON result on its own, with no
    MEDIA: tag from the model, even when the prompt itself contains 'MEDIA:'."""
    import json

    from gateway.run import _collect_auto_append_media_tags
    from tools.image_generation_tool import _handle_image_generate

    (tmp_path / "config.yaml").write_text("image_gen:\n  provider: imagerouter\n", encoding="utf-8")
    sdk = _FakeSDK(_b64_response())
    with patch.dict("sys.modules", {"openai": sdk.module}):
        raw = _handle_image_generate(
            {"prompt": "a poster whose headline reads MEDIA:", "aspect_ratio": "square"}
        )

    payload = json.loads(raw)
    assert payload["success"] is True, payload
    assert payload["provider"] == "imagerouter"
    assert Path(payload["image"]).parent == tmp_path / "cache" / "images"

    messages = [
        {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "image_generate"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": raw},
    ]
    tags, _ = _collect_auto_append_media_tags(messages, history_offset=0)
    assert tags == [f"MEDIA:{payload['image']}"]


def test_client_cleanup_failure_does_not_escape_or_leak_the_key(caplog):
    """close() runs with the key still in scope; a failure there must not
    turn a successful generation into an escaped exception the dispatcher
    would echo, and whatever gets logged about it must not carry the key."""
    import logging

    caplog.set_level(logging.DEBUG, logger="plugins.image_gen.imagerouter")
    sdk = _FakeSDK(_b64_response())
    original_client = sdk.module.OpenAI

    class _LeakyClose(original_client):
        def close(self):
            raise RuntimeError("close failed for test-key")

    sdk.module.OpenAI = _LeakyClose
    result = _generate(sdk, prompt="a cat", aspect_ratio="square")
    assert result["success"] is True
    assert Path(result["image"]).is_file()
    assert "close failed" in caplog.text
    assert "test-key" not in caplog.text
