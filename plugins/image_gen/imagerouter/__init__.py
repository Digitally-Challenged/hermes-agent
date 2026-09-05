"""ImageRouter image generation backend (https://imagerouter.io).

ImageRouter fronts ~140 image models behind one OpenAI-compatible endpoint
(``/v1/openai/images/generations``). This backend drives it through the
openai SDK the same way the DeepInfra plugin does, so the built-in
``image_generate`` tool, the ``hermes tools`` picker, and the gateway's
automatic attachment of generated files all work unchanged.

The default model is an unfiltered community FLUX fine-tune so creative
prompts (artistic nudity, horror/violence, mature fiction) are not refused
by a provider-side filter. Pin another model with ``image_gen.model`` or
``image_gen.imagerouter.model`` in config.yaml.

Fork-local: ImageRouter is a third-party paid service, so this plugin is not
upstreamable as-is (CONTRIBUTING.md, "Third-Party Product Integrations").
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_b64_image,
    save_url_image,
    success_response,
)
from agent.secret_scope import get_secret

logger = logging.getLogger(__name__)

PROVIDER = "imagerouter"
API_KEY_VAR = "IMAGEROUTER_API_KEY"
OPENAI_BASE_URL = "https://api.imagerouter.io/v1/openai"
MODELS_URL = "https://api.imagerouter.io/v1/models"

# Community fine-tunes that ship without a provider-side content filter, in
# rough order of general usefulness. The run-diffusion/* entries are FLUX
# architecture; the rest are SDXL. Verified 2026-09-02 against permissive and
# political prompts — none refused at the API layer.
UNFILTERED_MODELS = (
    # FLUX-architecture (newer, better prompt adherence and anatomy)
    "run-diffusion/Juggernaut-Pro-Flux",
    "run-diffusion/Juggernaut-Flux",
    "run-diffusion/Juggernaut-Lightning-Flux",
    "run-diffusion/RunDiffusion-Photo-Flux",
    # SDXL-architecture (huge community prompt corpus)
    "cyberdelia/CyberRealisticPony",
    "purplesmartai/pony-diffusion-v6-xl",
    "onomaai/illustrious-xl",
    "SG161222/RealVisXL",
    "asiryan/Realistic-Vision",
    "cagliostrolab/animagine-xl-3.0",
    "Lykon/DreamShaper",
    "run-diffusion/Juggernaut-XL",
)

# Fastest of the permissive set (~6-7 s) with FLUX's prompt adherence.
DEFAULT_MODEL = "run-diffusion/Juggernaut-Pro-Flux"

# aspect_ratio (the image_gen contract) → ImageRouter ``size``. Standard
# FLUX/SDXL training buckets: ~1 MP each, multiples of 64.
_SIZES = {
    "square": "1024x1024",
    "landscape": "1344x768",
    "portrait": "768x1344",
}

_REQUEST_TIMEOUT = 180.0
_CATALOG_TIMEOUT = 30.0
_CATALOG_TTL_S = 3600
_catalog_cache: Dict[str, Any] = {}


def _api_key() -> str:
    return (get_secret(API_KEY_VAR, "") or "").strip()


def _scrub(text: str, secret: str) -> str:
    """Never let the API key ride along in an error message."""
    return text.replace(secret, "***") if secret else text


def _load_imagerouter_config() -> Dict[str, Any]:
    """Read ``image_gen.imagerouter`` from config.yaml (``{}`` on failure)."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        sub = section.get(PROVIDER) if isinstance(section, dict) else None
        return sub if isinstance(sub, dict) else {}
    except Exception as exc:  # noqa: BLE001 - config is best-effort
        logger.debug("Could not load image_gen.imagerouter config: %s", exc)
        return {}


def _resolve_model(explicit: Any, cfg: Dict[str, Any]) -> str:
    """Explicit (``image_gen.model`` via the tool) > ``image_gen.imagerouter.model`` > default."""
    for candidate in (explicit, cfg.get("model")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return DEFAULT_MODEL


def _fetch_catalog() -> Dict[str, Any]:
    """GET the public model catalog (no auth needed), cached for an hour."""
    now = time.time()
    if _catalog_cache.get("at", 0) + _CATALOG_TTL_S > now:
        return _catalog_cache["data"]
    response = requests.get(MODELS_URL, timeout=_CATALOG_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("unexpected ImageRouter catalog shape")
    _catalog_cache.update(data=data, at=now)
    return data


def _price_label(entry: Dict[str, Any]) -> str:
    """``$x/image`` for fixed pricing, ``~$avg/image`` for post-generation ranges."""
    for provider in entry.get("providers") or []:
        pricing = provider.get("pricing") if isinstance(provider, dict) else None
        if not isinstance(pricing, dict):
            continue
        value, approx = pricing.get("value"), ""
        if value is None:
            price_range = pricing.get("range")
            value = price_range.get("average") if isinstance(price_range, dict) else None
            approx = "~"
        if value is None:
            continue
        try:
            return f"{approx}${float(value):.4f}/image"
        except (TypeError, ValueError):
            return ""
    return ""


def _catalog_rows(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Picker rows for every image-output model, unfiltered ones first."""
    image_ids = [
        mid
        for mid, entry in catalog.items()
        if isinstance(entry, dict) and "image" in (entry.get("output") or [])
    ]
    ordered = [m for m in UNFILTERED_MODELS if m in image_ids]
    ordered += sorted(m for m in image_ids if m not in UNFILTERED_MODELS)
    rows: List[Dict[str, Any]] = []
    for mid in ordered:
        row: Dict[str, Any] = {
            "id": mid,
            "display": mid.split("/", 1)[-1],
            "strengths": "unfiltered community fine-tune" if mid in UNFILTERED_MODELS else "",
        }
        price = _price_label(catalog[mid])
        if price:
            row["price"] = price
        rows.append(row)
    return rows


class ImageRouterImageGenProvider(ImageGenProvider):
    """ImageRouter ``images.generations`` backend (text-to-image)."""

    @property
    def name(self) -> str:
        return PROVIDER

    @property
    def display_name(self) -> str:
        return "ImageRouter"

    def is_available(self) -> bool:
        return bool(_api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            return _catalog_rows(_fetch_catalog())
        except Exception as exc:  # noqa: BLE001 - picker must never crash on network
            logger.debug("ImageRouter catalog unavailable: %s", exc)
            return []

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text"], "max_reference_images": 0}

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "ImageRouter",
            "badge": "paid",
            "tag": "~140 models behind one key; default is an unfiltered FLUX fine-tune",
            "env_vars": [
                {
                    "key": API_KEY_VAR,
                    "prompt": "ImageRouter API key",
                    "url": "https://imagerouter.io/",
                },
            ],
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)

        def fail(error: str, error_type: str, model: str = "") -> Dict[str, Any]:
            return error_response(
                error=error,
                error_type=error_type,
                provider=PROVIDER,
                model=model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        if kwargs.get("image_url") or kwargs.get("reference_image_urls"):
            return fail(
                "The ImageRouter backend is text-to-image only; image_url and "
                "reference_image_urls are unsupported.",
                "modality_unsupported",
            )
        if not prompt:
            return fail("Prompt is required and must be a non-empty string", "invalid_argument")

        api_key = _api_key()
        if not api_key:
            return fail(
                f"{API_KEY_VAR} not set. Run `hermes tools` → Image Generation → "
                "ImageRouter to configure, or add the key to .env.",
                "auth_required",
            )

        model_id = _resolve_model(kwargs.get("model"), _load_imagerouter_config())
        size = _SIZES.get(aspect, _SIZES["square"])

        try:
            import openai
        except ImportError:
            return fail(
                "openai Python package not installed (pip install openai)",
                "missing_dependency",
                model_id,
            )

        client = None
        try:
            # max_retries=0: the SDK would otherwise retry 5xx/408/429/timeouts
            # three times, and a generation that timed out but completed
            # server-side is billed again on every retry.
            client = openai.OpenAI(
                api_key=api_key,
                base_url=OPENAI_BASE_URL,
                timeout=_REQUEST_TIMEOUT,
                max_retries=0,
            )
            response = client.images.generate(
                model=model_id,
                prompt=prompt,
                size=size,
                n=1,
                response_format="b64_json",
                output_format="png",
            )
        except Exception as exc:  # noqa: BLE001 - every SDK failure becomes a tool error
            logger.debug("ImageRouter image generation failed: %s", _scrub(str(exc), api_key))
            return fail(
                f"ImageRouter image generation failed: {_scrub(str(exc), api_key)}",
                "api_error",
                model_id,
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:  # noqa: BLE001 - cleanup must never escape
                    logger.debug("ImageRouter client close failed: %s", _scrub(str(exc), api_key))

        data = getattr(response, "data", None) or []
        if not data:
            return fail("ImageRouter returned no image data", "empty_response", model_id)

        first = data[0]
        b64 = getattr(first, "b64_json", None)
        url = getattr(first, "url", None)
        prefix = f"imagerouter_{model_id.split('/', 1)[-1].replace(':', '_')}"
        try:
            if b64:
                image_ref = str(save_b64_image(b64, prefix=prefix))
            elif url:
                # Materialise the delivery URL locally: messaging surfaces
                # attach a file path, never a remote link.
                image_ref = str(save_url_image(url, prefix=prefix))
            else:
                return fail(
                    "ImageRouter response contained neither b64_json nor a URL",
                    "empty_response",
                    model_id,
                )
        except Exception as exc:  # noqa: BLE001 - surface I/O failures as a tool error
            return fail(
                f"Could not save image to cache: {_scrub(str(exc), api_key)}",
                "io_error",
                model_id,
            )

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider=PROVIDER,
            extra={"size": size, "unfiltered": model_id in UNFILTERED_MODELS},
        )


def register(ctx) -> None:
    """Plugin entry point — wire ``ImageRouterImageGenProvider`` into the registry."""
    ctx.register_image_gen_provider(ImageRouterImageGenProvider())
