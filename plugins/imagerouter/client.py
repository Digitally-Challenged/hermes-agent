"""Thin ImageRouter HTTP client (https://api.imagerouter.io).

ImageRouter is a routing layer in front of many image backends. This client
covers the two endpoints the plugin needs: the public model catalog and
image generation. Stdlib only — no new dependency for one REST surface.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_URL = "https://api.imagerouter.io/v1"
MODELS_URL = f"{BASE_URL}/models"
GENERATE_URL = f"{BASE_URL}/openai/images/generations"

# Community SDXL fine-tunes that ship without a provider-side content filter.
# Everything else on ImageRouter (FLUX, Seedream, Qwen, HiDream) is filtered
# upstream, so a permissive prompt fails there no matter what we send.
UNFILTERED_MODELS = (
    "cyberdelia/CyberRealisticPony",
    "purplesmartai/pony-diffusion-v6-xl",
    "onomaai/illustrious-xl",
    "SG161222/RealVisXL",
    "asiryan/Realistic-Vision",
    "cagliostrolab/animagine-xl-3.0",
    "Lykon/DreamShaper",
    "run-diffusion/Juggernaut-XL",
)

DEFAULT_MODEL = "cyberdelia/CyberRealisticPony"
_MODELS_CACHE_TTL_S = 3600


class ImageRouterError(RuntimeError):
    """Any ImageRouter failure surfaced to the agent."""


class ImageRouterAuthError(ImageRouterError):
    """No usable API key, or the key was rejected."""


def _hermes_env_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / ".env"


def get_api_key() -> str:
    """Resolve the key: process env first, then ~/.hermes/.env.

    Never logged, never returned to the model.
    """
    for var in ("IMAGEROUTER_API_KEY", "IMAGE_ROUTER_API_KEY"):
        value = (os.environ.get(var) or "").strip()
        if value:
            return value
    env_path = _hermes_env_path()
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(("IMAGEROUTER_API_KEY=", "IMAGE_ROUTER_API_KEY=")):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    raise ImageRouterAuthError(
        f"No ImageRouter API key. Add IMAGEROUTER_API_KEY=<key> to {env_path} "
        "(the key lives in the 1Password item 'Image Router')."
    )


def has_api_key() -> bool:
    try:
        get_api_key()
        return True
    except ImageRouterError:
        return False


def _request(url: str, *, payload: Optional[Dict[str, Any]] = None,
             api_key: Optional[str] = None, timeout: int = 180) -> Any:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")[:400]
        if err.code in (401, 403):
            raise ImageRouterAuthError(
                f"ImageRouter rejected the API key (HTTP {err.code}). {body}"
            ) from err
        raise ImageRouterError(f"ImageRouter HTTP {err.code}: {body}") from err
    except urllib.error.URLError as err:
        raise ImageRouterError(f"ImageRouter unreachable: {err.reason}") from err
    except json.JSONDecodeError as err:
        raise ImageRouterError(f"ImageRouter returned non-JSON: {err}") from err


_models_cache: Dict[str, Any] = {}


def list_models(*, force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch the public model catalog (no auth needed). Cached for an hour."""
    now = time.time()
    if not force_refresh and _models_cache.get("at", 0) + _MODELS_CACHE_TTL_S > now:
        return _models_cache["data"]
    data = _request(MODELS_URL, timeout=30)
    if not isinstance(data, dict):
        raise ImageRouterError("Unexpected model catalog shape")
    _models_cache["data"] = data
    _models_cache["at"] = now
    return data


def image_models(catalog: Optional[Dict[str, Any]] = None) -> List[str]:
    cat = catalog if catalog is not None else list_models()
    return sorted(k for k, v in cat.items() if "image" in (v.get("output") or []))


def model_price(model: str, catalog: Optional[Dict[str, Any]] = None) -> Optional[float]:
    cat = catalog if catalog is not None else list_models()
    providers = (cat.get(model) or {}).get("providers") or []
    for provider in providers:
        value = (provider.get("pricing") or {}).get("value")
        if value is not None:
            return float(value)
    return None


def generate(prompt: str, *, model: str = DEFAULT_MODEL, size: str = "1024x1024",
             quality: str = "auto", n: int = 1, timeout: int = 180) -> List[Dict[str, Any]]:
    """Generate image(s). Returns the API's data entries (url or b64_json)."""
    payload: Dict[str, Any] = {"prompt": prompt, "model": model, "n": max(1, min(int(n), 4))}
    if size:
        payload["size"] = size
    if quality and quality != "auto":
        payload["quality"] = quality
    data = _request(GENERATE_URL, payload=payload, api_key=get_api_key(), timeout=timeout)
    entries = data.get("data") if isinstance(data, dict) else None
    if not entries:
        raise ImageRouterError(f"No image returned: {json.dumps(data)[:300]}")
    return entries
