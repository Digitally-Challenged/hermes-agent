"""Honcho's config storage backend for the generic desktop panel.

Reached generically by ``web_server`` through the ``config_storage.py``
convention (see ``plugins/memory/config_schema.py``). This module is imported
by path only when the panel reads or writes Honcho's config, so the agent
runtime never loads into the web server just to render a schema.
"""

from __future__ import annotations

import json
import logging

_log = logging.getLogger(__name__)


def _resolvers() -> tuple:
    from plugins.memory.honcho.client import (
        _host_block,
        resolve_active_host,
        resolve_config_path,
    )

    return resolve_active_host, resolve_config_path, _host_block


def _read_raw_config(path) -> dict:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        _log.warning("Failed to read Honcho config from %s", path, exc_info=True)
        return {}


def read_state(provider) -> dict:
    """Return the read-state the generic renderer needs (see config_schema.py)."""
    resolve_active_host, resolve_config_path, host_block_of = _resolvers()
    host = resolve_active_host()
    raw = _read_raw_config(resolve_config_path())
    host_block = host_block_of(raw, host)

    def sources_for(field) -> tuple:
        return (host_block, raw) if field.scope == "host" else (raw,)

    return {
        "sources_for": sources_for,
        "host": host,
        "placeholder_keys": {"workspace", "aiPeer"},
        "presence_is_set": True,
    }


def write(provider, values: dict) -> None:
    """Persist submitted fields to Honcho's real config for the active host.

    Only keys present in ``values`` are touched, so a partial save (e.g. the
    inline panel) never clobbers fields owned by the full-config editor. Blank
    text clears a key so it falls back to the host/default mapping.
    """
    from plugins.memory.config_schema import apply_field_values
    from plugins.memory.honcho.oauth import ACCESS_TOKEN_PREFIX, _config_refresh_lock
    from hermes_cli.config import save_env_value
    from utils import atomic_json_write

    resolve_active_host, resolve_config_path, host_block_of = _resolvers()
    host = resolve_active_host()
    # Write the file reads resolve, or a save shadows it with a sparse copy.
    path = resolve_config_path()

    # OAuth rotation is single-use; an unlocked RMW here can revoke the grant.
    with _config_refresh_lock(path):
        cfg = _read_raw_config(path)

        hosts = cfg.get("hosts")
        cfg["hosts"] = hosts = hosts if isinstance(hosts, dict) else {}
        # Update the block reads resolve (legacy dot-form included), never shadow it.
        existing = host_block_of(cfg, host)
        host_key = next((k for k, v in hosts.items() if v is existing), host) if existing else host
        host_block = hosts.setdefault(host_key, existing)

        for field in provider.fields:
            if not field.is_secret:
                continue
            submitted = (values.get(field.key) or "").strip()
            if not submitted:
                continue
            if field.env_key:
                save_env_value(field.env_key, submitted)
            # Persist where the client reads first; an OAuth token owns that slot.
            stored = host_block.get(field.key)
            if not (isinstance(stored, str) and stored.startswith(ACCESS_TOKEN_PREFIX)):
                host_block[field.key] = submitted

        apply_field_values(provider, values, lambda field: host_block if field.scope == "host" else cfg)

        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, cfg, mode=0o600)
