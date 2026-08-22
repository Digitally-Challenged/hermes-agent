from __future__ import annotations

from typing import Any


def _coerce_timeout(raw: object) -> float | None:
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        return None
    return timeout if timeout > 0 else None


def _resolve_provider_config(
    config: dict[str, Any], provider_id: str, base_url: str | None
) -> dict[str, Any] | None:
    """Find the ``providers`` entry that governs this request.

    Priority:
      1. ``providers.<provider_id>`` — an explicit, configured provider key.
      2. The first ``providers`` entry whose ``base_url`` matches ``base_url``
         (route identity, so scheme case / trailing slashes don't matter).
      3. Same match over legacy ``custom_providers`` list entries.

    Step 2/3 exist because a *named* custom provider (``providers.mlx-lm``)
    runs with ``AIAgent.provider == "custom"`` — the config key never reaches
    the agent, so keying on ``provider_id`` alone silently ignores every
    timeout the user set on that entry. Matching by ``base_url`` mirrors
    :func:`hermes_cli.config.get_custom_provider_context_length`.
    """
    providers = config.get("providers", {})
    if isinstance(providers, dict):
        explicit = providers.get(provider_id)
        if isinstance(explicit, dict) and explicit:
            return explicit

    if not base_url:
        return None
    try:
        from hermes_cli.route_identity import normalize_route_base_url
    except Exception:
        return None
    target = normalize_route_base_url(base_url)
    if not target:
        return None

    candidates: list[Any] = []
    if isinstance(providers, dict):
        candidates.extend(providers.values())
    legacy = config.get("custom_providers")
    if isinstance(legacy, list):
        candidates.extend(legacy)
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        if normalize_route_base_url(entry.get("base_url")) == target:
            return entry
    return None


def _provider_config_for(provider_id: str, base_url: str | None) -> dict[str, Any] | None:
    """The ``providers`` entry governing this request, or None. Never raises."""
    if not provider_id and not base_url:
        return None
    try:
        from hermes_cli.config import load_config_readonly
        config = load_config_readonly()
    except Exception:
        return None
    if not isinstance(config, dict):
        return None
    return _resolve_provider_config(config, provider_id or "", base_url)


def _configured_timeout(
    provider_id: str, model: str | None, model_key: str, provider_key: str, base_url: str | None = None
) -> float | None:
    """Per-model ``providers.<id>.models.<model>.<model_key>`` wins over ``providers.<id>.<provider_key>``.

    ``base_url`` lets named custom providers (runtime ``provider_id == "custom"``) resolve their entry.
    """
    provider_config = _provider_config_for(provider_id, base_url)
    if provider_config is None:
        return None
    model_config = _get_model_config(provider_config, model)
    if model_config is not None:
        timeout = _coerce_timeout(model_config.get(model_key))
        if timeout is not None:
            return timeout
    return _coerce_timeout(provider_config.get(provider_key))


def get_provider_request_timeout(
    provider_id: str, model: str | None = None, base_url: str | None = None
) -> float | None:
    """Return a configured provider request timeout in seconds, if any."""
    return _configured_timeout(provider_id, model, "timeout_seconds", "request_timeout_seconds", base_url)


def get_provider_stale_timeout(
    provider_id: str, model: str | None = None, base_url: str | None = None
) -> float | None:
    """Return a configured non-stream stale timeout in seconds, if any."""
    return _configured_timeout(provider_id, model, "stale_timeout_seconds", "stale_timeout_seconds", base_url)


def _get_model_config(provider_config: dict[str, object], model: str | None) -> dict[str, object] | None:
    if not model:
        return None
    models = provider_config.get("models", {})
    model_config = models.get(model, {}) if isinstance(models, dict) else {}
    return model_config if isinstance(model_config, dict) else None