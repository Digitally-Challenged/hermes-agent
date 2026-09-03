"""ImageRouter tools — generation across ImageRouter's model catalog.

Defaults to an unfiltered community SDXL fine-tune so creative prompts
(artistic nudity, horror/violence, mature fiction) are not silently refused
by a provider-side filter. Any of ImageRouter's ~140 image models can be
selected per call via ``model``.
"""

from __future__ import annotations

import base64
import binascii
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

from plugins.imagerouter.client import (
    DEFAULT_MODEL,
    UNFILTERED_MODELS,
    ImageRouterAuthError,
    ImageRouterError,
    generate as ir_generate,
    has_api_key,
    image_models,
    list_models,
    model_price,
)
from tools.registry import tool_error, tool_result

_VALID_QUALITY = ("auto", "low", "medium", "high")
_DOWNLOAD_TIMEOUT_S = 120
_MAX_IMAGE_BYTES = 40 * 1024 * 1024


def _check_imagerouter_available() -> bool:
    """Gate dispatch on a resolvable API key (tool stays listed either way)."""
    return has_api_key()


def _image_dir() -> Path:
    from hermes_constants import get_hermes_home

    path = get_hermes_home() / "cache" / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_bytes(data: bytes, model: str) -> str:
    slug = model.replace("/", "_").replace(":", "-")
    out = _image_dir() / f"imagerouter_{slug}_{int(time.time() * 1000)}.png"
    out.write_bytes(data)
    return str(out)


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-imagerouter/1.0"})
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
        data = resp.read(_MAX_IMAGE_BYTES + 1)
    if len(data) > _MAX_IMAGE_BYTES:
        raise ImageRouterError("Image exceeds the 40 MB size cap")
    return data


def _persist(entry: Dict[str, Any], model: str) -> str:
    """Turn one API data entry (url or b64_json) into a local file path."""
    b64 = entry.get("b64_json")
    if b64:
        try:
            return _save_bytes(base64.b64decode(b64), model)
        except (binascii.Error, ValueError) as exc:
            raise ImageRouterError(f"Malformed base64 image: {exc}") from exc
    url = entry.get("url")
    if url:
        return _save_bytes(_download(url), model)
    raise ImageRouterError("Image entry had neither url nor b64_json")


def _handle_imagerouter_generate(args: Dict[str, Any], **_kw: Any) -> str:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required")

    model = (args.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    size = (args.get("size") or "1024x1024").strip()
    quality = (args.get("quality") or "auto").strip()
    if quality not in _VALID_QUALITY:
        return tool_error(f"quality must be one of {', '.join(_VALID_QUALITY)}")
    try:
        n = max(1, min(int(args.get("n") or 1), 4))
    except (TypeError, ValueError):
        n = 1

    try:
        entries = ir_generate(prompt, model=model, size=size, quality=quality, n=n)
        paths = [_persist(entry, model) for entry in entries]
    except ImageRouterAuthError as exc:
        return tool_error(str(exc))
    except ImageRouterError as exc:
        return tool_error(str(exc))
    except (urllib.error.URLError, OSError) as exc:
        return tool_error(f"Could not save image: {type(exc).__name__}: {exc}")

    payload: Dict[str, Any] = {
        "success": True,
        "image": paths[0],
        "model": model,
        "unfiltered": model in UNFILTERED_MODELS,
    }
    if len(paths) > 1:
        payload["images"] = paths
    try:
        price = model_price(model)
        if price is not None:
            payload["approx_cost_usd"] = round(price * len(paths), 4)
    except ImageRouterError:
        pass
    return tool_result(payload)


def _handle_imagerouter_models(args: Dict[str, Any], **_kw: Any) -> str:
    query = (args.get("query") or "").strip().lower()
    unfiltered_only = bool(args.get("unfiltered_only"))
    try:
        catalog = list_models(force_refresh=bool(args.get("refresh")))
        names = image_models(catalog)
    except ImageRouterError as exc:
        return tool_error(str(exc))

    if unfiltered_only:
        names = [n for n in names if n in UNFILTERED_MODELS]
    if query:
        names = [n for n in names if query in n.lower()]

    rows = []
    for name in names[:60]:
        row: Dict[str, Any] = {"model": name}
        price = model_price(name, catalog)
        if price is not None:
            row["usd_per_image"] = price
        if name in UNFILTERED_MODELS:
            row["unfiltered"] = True
        params = (catalog.get(name) or {}).get("supported_params") or {}
        if params.get("edit"):
            row["edit"] = True
        rows.append(row)

    return tool_result({
        "success": True,
        "count": len(names),
        "shown": len(rows),
        "default": DEFAULT_MODEL,
        "models": rows,
    })


IMAGEROUTER_GENERATE_SCHEMA = {
    "name": "imagerouter_generate",
    "description": (
        "Generate an image via ImageRouter. Defaults to an unfiltered community "
        "SDXL model, so mature or violent creative prompts are not refused by a "
        "provider filter. Pass `model` to pick any other ImageRouter model "
        "(use imagerouter_models to browse). Returns a local file path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What to generate."},
            "model": {
                "type": "string",
                "description": (
                    f"ImageRouter model id. Default {DEFAULT_MODEL} (unfiltered). "
                    "Other unfiltered options: "
                    + ", ".join(UNFILTERED_MODELS[1:4])
                    + ". Filtered but higher fidelity: black-forest-labs/FLUX-1.1-pro, "
                    "qwen/qwen-image-3, bytedance/seedream-4.5."
                ),
            },
            "size": {"type": "string", "description": "WxH, e.g. 1024x1024 or 832x1216. Default 1024x1024."},
            "quality": {"type": "string", "enum": list(_VALID_QUALITY)},
            "n": {"type": "integer", "description": "How many images (1-4). Default 1."},
        },
        "required": ["prompt"],
    },
}

IMAGEROUTER_MODELS_SCHEMA = {
    "name": "imagerouter_models",
    "description": (
        "Browse ImageRouter's image models with prices. Filter with `query`, or "
        "set `unfiltered_only` to list just the models with no content filter."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring filter on the model id."},
            "unfiltered_only": {"type": "boolean", "description": "Only models without a provider-side filter."},
            "refresh": {"type": "boolean", "description": "Bypass the 1-hour catalog cache."},
        },
        "required": [],
    },
}
