"""Tests for the ImageRouter plugin. No live network."""

import base64
import json
import urllib.error
from unittest import mock

import pytest

from plugins.imagerouter import client as ir_client
from plugins.imagerouter import tools as ir_tools

CATALOG = {
    "cyberdelia/CyberRealisticPony": {
        "output": ["image"],
        "providers": [{"id": "runware", "pricing": {"type": "post_generation", "value": 0.01}}],
        "supported_params": {"text": True, "edit": False},
    },
    "black-forest-labs/FLUX-1.1-pro": {
        "output": ["image"],
        "providers": [{"id": "runware", "pricing": {"type": "post_generation", "value": 0.04}}],
        "supported_params": {"text": True, "edit": True},
    },
    "some/text-model": {"output": ["text"], "providers": []},
}

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def _clear_cache():
    ir_client._models_cache.clear()
    yield
    ir_client._models_cache.clear()


@pytest.fixture
def _image_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ir_tools, "_image_dir", lambda: tmp_path)
    return tmp_path


def test_default_model_is_unfiltered():
    assert ir_client.DEFAULT_MODEL in ir_client.UNFILTERED_MODELS


def test_image_models_excludes_text_only():
    names = ir_client.image_models(CATALOG)
    assert "some/text-model" not in names
    assert "cyberdelia/CyberRealisticPony" in names


def test_model_price_reads_first_priced_provider():
    assert ir_client.model_price("black-forest-labs/FLUX-1.1-pro", CATALOG) == 0.04
    assert ir_client.model_price("some/text-model", CATALOG) is None


def test_get_api_key_prefers_process_env(monkeypatch):
    monkeypatch.setenv("IMAGEROUTER_API_KEY", "from-env")
    assert ir_client.get_api_key() == "from-env"


def test_get_api_key_falls_back_to_hermes_env(tmp_path, monkeypatch):
    monkeypatch.delenv("IMAGEROUTER_API_KEY", raising=False)
    monkeypatch.delenv("IMAGE_ROUTER_API_KEY", raising=False)
    (tmp_path / ".env").write_text('OTHER=x\nIMAGEROUTER_API_KEY="from-file"\n')
    monkeypatch.setattr(ir_client, "_hermes_env_path", lambda: tmp_path / ".env")
    assert ir_client.get_api_key() == "from-file"


def test_missing_key_raises_auth_error(tmp_path, monkeypatch):
    monkeypatch.delenv("IMAGEROUTER_API_KEY", raising=False)
    monkeypatch.delenv("IMAGE_ROUTER_API_KEY", raising=False)
    monkeypatch.setattr(ir_client, "_hermes_env_path", lambda: tmp_path / "nope.env")
    with pytest.raises(ir_client.ImageRouterAuthError):
        ir_client.get_api_key()
    assert ir_client.has_api_key() is False


def test_generate_persists_b64_and_reports_cost(_image_dir, monkeypatch):
    monkeypatch.setattr(ir_tools, "ir_generate",
                        lambda *a, **k: [{"b64_json": base64.b64encode(PNG_1PX).decode()}])
    monkeypatch.setattr(ir_tools, "model_price", lambda *a, **k: 0.01)
    out = json.loads(ir_tools._handle_imagerouter_generate({"prompt": "a cat"}))
    assert out["success"] is True
    assert out["model"] == ir_client.DEFAULT_MODEL
    assert out["unfiltered"] is True
    assert out["approx_cost_usd"] == 0.01
    assert open(out["image"], "rb").read() == PNG_1PX


def test_generate_downloads_url_entries(_image_dir, monkeypatch):
    monkeypatch.setattr(ir_tools, "ir_generate", lambda *a, **k: [{"url": "https://x/i.png"}])
    monkeypatch.setattr(ir_tools, "_download", lambda url: PNG_1PX)
    monkeypatch.setattr(ir_tools, "model_price", lambda *a, **k: None)
    out = json.loads(ir_tools._handle_imagerouter_generate({"prompt": "a dog"}))
    assert out["success"] is True
    assert "approx_cost_usd" not in out


def test_generate_marks_filtered_model_as_not_unfiltered(_image_dir, monkeypatch):
    monkeypatch.setattr(ir_tools, "ir_generate",
                        lambda *a, **k: [{"b64_json": base64.b64encode(PNG_1PX).decode()}])
    monkeypatch.setattr(ir_tools, "model_price", lambda *a, **k: None)
    out = json.loads(ir_tools._handle_imagerouter_generate(
        {"prompt": "x", "model": "black-forest-labs/FLUX-1.1-pro"}))
    assert out["unfiltered"] is False


def test_generate_requires_prompt():
    assert "error" in json.loads(ir_tools._handle_imagerouter_generate({}))
    assert "error" in json.loads(ir_tools._handle_imagerouter_generate({"prompt": "   "}))


def test_generate_rejects_bad_quality():
    out = json.loads(ir_tools._handle_imagerouter_generate({"prompt": "x", "quality": "ultra"}))
    assert "error" in out


def test_generate_surfaces_auth_error_as_tool_error(monkeypatch):
    def boom(*a, **k):
        raise ir_client.ImageRouterAuthError("no key")
    monkeypatch.setattr(ir_tools, "ir_generate", boom)
    out = json.loads(ir_tools._handle_imagerouter_generate({"prompt": "x"}))
    assert "no key" in out["error"]


def test_generate_clamps_n(_image_dir, monkeypatch):
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw)
        return [{"b64_json": base64.b64encode(PNG_1PX).decode()}]

    monkeypatch.setattr(ir_tools, "ir_generate", fake)
    monkeypatch.setattr(ir_tools, "model_price", lambda *a, **k: None)
    ir_tools._handle_imagerouter_generate({"prompt": "x", "n": 99})
    assert seen["n"] == 4


def test_models_lists_and_filters(monkeypatch):
    monkeypatch.setattr(ir_tools, "list_models", lambda **k: CATALOG)
    monkeypatch.setattr(ir_tools, "image_models", lambda c: ir_client.image_models(c))
    monkeypatch.setattr(ir_tools, "model_price",
                        lambda n, c=None: ir_client.model_price(n, CATALOG))

    every = json.loads(ir_tools._handle_imagerouter_models({}))
    assert every["default"] == ir_client.DEFAULT_MODEL
    assert every["count"] == 2

    only = json.loads(ir_tools._handle_imagerouter_models({"unfiltered_only": True}))
    assert [r["model"] for r in only["models"]] == ["cyberdelia/CyberRealisticPony"]

    hit = json.loads(ir_tools._handle_imagerouter_models({"query": "flux"}))
    assert hit["count"] == 1
    assert hit["models"][0]["edit"] is True


def test_models_surfaces_catalog_failure(monkeypatch):
    def boom(**k):
        raise ir_client.ImageRouterError("catalog down")
    monkeypatch.setattr(ir_tools, "list_models", boom)
    assert "catalog down" in json.loads(ir_tools._handle_imagerouter_models({}))["error"]


def test_http_401_becomes_auth_error(monkeypatch):
    def raise_401(req, timeout):
        raise urllib.error.HTTPError("u", 401, "unauth", {}, None)
    monkeypatch.setattr(ir_client.urllib.request, "urlopen", raise_401)
    with pytest.raises(ir_client.ImageRouterAuthError):
        ir_client._request("https://x", api_key="k")


def test_catalog_is_cached(monkeypatch):
    calls = []

    def fake_request(url, **kw):
        calls.append(url)
        return CATALOG

    monkeypatch.setattr(ir_client, "_request", fake_request)
    ir_client.list_models()
    ir_client.list_models()
    assert len(calls) == 1
    ir_client.list_models(force_refresh=True)
    assert len(calls) == 2


def test_registered_tools_match_plugin_manifest():
    import yaml
    from pathlib import Path
    import plugins.imagerouter as pkg

    manifest = yaml.safe_load(
        (Path(pkg.__file__).parent / "plugin.yaml").read_text())
    assert sorted(manifest["provides_tools"]) == sorted(n for n, _, _, _ in pkg._TOOLS)


def test_tools_are_wired_into_a_toolset():
    from toolsets import TOOLSETS
    import plugins.imagerouter as pkg

    listed = set(TOOLSETS["imagerouter"]["tools"])
    assert listed == {n for n, _, _, _ in pkg._TOOLS}
