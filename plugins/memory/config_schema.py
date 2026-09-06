"""Declarative configuration schema for memory provider plugins.

Each memory provider plugin *declares* its configurable surface in a
``config_schema.py`` next to its ``__init__.py`` — the fields, their types,
which values are secrets, and (for selects) the allowed options. A single
generic renderer in the desktop UI and a single generic ``GET/PUT
/api/memory/providers/{name}/config`` endpoint pair drive the whole
experience, so adding a provider config surface is pure declaration with no
bespoke UI components.

Schema files are loaded by path (like the provider plugins themselves), never
via package import: plugin ``__init__.py`` files pull in the agent runtime,
which must not load into the web server. A ``config_schema.py`` may only
import from this module.

This module is data plus the storage-agnostic helpers that interpret a
declaration: it imports nothing from the config/env layer. ``web_server``
drives the generic read/write flow, dispatching on ``ProviderConfigSchema.storage``
to a storage backend:

* ``STORAGE_FLAT_JSON`` — the built-in backend (a JSON file per provider under
  ``$HERMES_HOME/<name>/config.json``), implemented in ``web_server``.
* any other value — a provider-owned backend in ``<provider_dir>/config_storage.py``
  (e.g. Honcho's host-block backend), loaded by path. It exposes:

  ``read_state(provider) -> dict``
      ``sources_for`` — callable(field) -> tuple of source dicts, precedence order
      ``host``        — active host key, used as the placeholder for blank identity fields
      ``placeholder_keys`` — set of field keys whose blank value surfaces ``host``
      ``presence_is_set``  — True means "is_set" is key presence; False means truthy

  ``write(provider, values) -> None``
      Persist submitted non-secret fields (and secrets via env) to the backend.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable

_log = logging.getLogger(__name__)

# Field kinds understood by the generic renderer.
KIND_TEXT = "text"
KIND_SELECT = "select"
KIND_SECRET = "secret"
KIND_BOOL = "bool"
KIND_NUMBER = "number"
KIND_JSON = "json"

# Storage backends understood by web_server (see its read/write dispatch).
STORAGE_FLAT_JSON = "flat_json"
STORAGE_HONCHO_HOST_BLOCK = "honcho_host_block"


@dataclass(frozen=True)
class ProviderFieldOption:
    """A single choice for a ``select`` field."""

    value: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class ProviderField:
    """One configurable field on a memory provider.

    A field is stored in exactly one place, decided by ``kind``:

    * non-secret kinds — persisted to the provider's config via its storage
      backend under ``key``.
    * ``secret`` — persisted to the env store under ``env_key`` and never read
      back out over the API (only an ``is_set`` flag is surfaced).

    ``aliases`` and ``env_fallbacks`` let a field read legacy values written by
    earlier CLI/env setup without re-introducing per-provider code. ``inline``
    marks the curated subset shown in the compact panel; the rest surface only
    in the full-config modal. ``group`` buckets fields within that modal.
    """

    key: str
    label: str
    kind: str = KIND_TEXT
    default: str = ""
    description: str = ""
    placeholder: str = ""
    options: tuple[ProviderFieldOption, ...] = ()
    env_key: str | None = None
    aliases: tuple[str, ...] = ()
    env_fallbacks: tuple[str, ...] = ()
    inline: bool = False
    group: str = ""
    # Longer help text surfaced as an info tooltip next to the field label.
    info: str = ""
    # Host-block placement: "host" (per-profile) or "root"; flat-json ignores it.
    scope: str = "host"

    @property
    def is_secret(self) -> bool:
        return self.kind == KIND_SECRET

    def allowed_values(self) -> set[str]:
        return {opt.value for opt in self.options}


@dataclass(frozen=True)
class ProviderConfigSchema:
    """A provider plugin's declared config surface."""

    name: str
    label: str
    storage: str = STORAGE_FLAT_JSON
    # Optional link to the provider's config docs, shown in the full-config modal.
    docs_url: str = ""
    fields: tuple[ProviderField, ...] = dataclass_field(default_factory=tuple)

    def inline_fields(self) -> tuple[ProviderField, ...]:
        return tuple(f for f in self.fields if f.inline)


_SCHEMA_CACHE: dict[str, ProviderConfigSchema] = {}


def get_provider_config_schema(name: str) -> ProviderConfigSchema | None:
    """Return the ``CONFIG_SCHEMA`` declared by the provider plugin ``name``.

    Providers without a ``config_schema.py`` (e.g. ``builtin``) return ``None``
    and simply render no config panel. The cache keys on the resolved schema
    file, not the name: user-installed plugins are per-profile, so one
    profile's lookup must never answer for another's.
    """

    from plugins.memory import find_provider_dir

    provider_dir = find_provider_dir(name)
    path = provider_dir / "config_schema.py" if provider_dir else None
    if path is None or not path.is_file():
        return None

    key = str(path)
    if key in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[key]

    try:
        spec = importlib.util.spec_from_file_location(f"_hermes_memory_config_schema.{name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        schema = getattr(module, "CONFIG_SCHEMA", None)
    except Exception:
        # Never cache a failed load: it would pin an empty panel until restart.
        _log.exception("failed to load config schema for memory provider %r", name)
        return None

    if schema is not None:
        _SCHEMA_CACHE[key] = schema
    return schema


# ---------------------------------------------------------------------------
# Storage-agnostic field interpretation
# ---------------------------------------------------------------------------
#
# These interpret a declaration for the generic renderer, independent of the
# storage backend. Both ``web_server``'s built-in flat-json backend and a
# plugin's ``config_storage.py`` import them, so the coercion/read/apply rules
# can never drift between backends.

# Sentinel: remove this key so it falls back to the host or built-in default.
UNSET: Any = object()


def provider_field_entry(field: ProviderField) -> dict:
    """Static, storage-independent shape of one field for the UI payload."""
    return {
        "key": field.key,
        "label": field.label,
        "kind": field.kind,
        "description": field.description,
        "info": field.info,
        "placeholder": field.placeholder,
        "inline": field.inline,
        "group": field.group,
        "options": [
            {"value": opt.value, "label": opt.label, "description": opt.description}
            for opt in field.options
        ],
    }


def coerce_field_value(field: ProviderField, raw: str) -> Any:
    """Coerce a submitted non-secret value to its native JSON type.

    Values arrive as strings over the API; this converts them to the type the
    provider resolver expects (bool/number/list/dict), so e.g. a boolean is
    stored as a JSON ``false`` rather than the string ``"false"`` (which would
    read as truthy). Returns :data:`UNSET` when the field should be removed.
    Raises ``ValueError`` on malformed input.
    """
    value = (raw or "").strip()
    kind = field.kind

    if kind == "select":
        if not value:
            value = field.default
        if value not in field.allowed_values():
            raise ValueError(f"Invalid value for '{field.key}'")
        return value

    if kind == "bool":
        from utils import is_truthy_value

        return is_truthy_value(value)

    if kind == "number":
        if not value:
            return UNSET
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"Invalid number for '{field.key}'") from exc
        return int(number) if number.is_integer() else number

    if kind == "json":
        if not value:
            return UNSET
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid JSON for '{field.key}'") from exc
        if not isinstance(parsed, (dict, list)):
            raise ValueError(f"'{field.key}' must be a JSON object or array")
        return parsed

    # text / secret — blank clears the key so it falls back to host/default.
    return value if value else UNSET


def serialize_field_value(field: ProviderField, value: Any) -> str:
    """Render a stored native value as the string the generic UI edits.

    ``None`` (key absent) yields the field's declared default. Bools become
    ``"true"``/``"false"``, JSON objects/arrays are re-encoded, numbers are
    stringified — so the renderer's per-kind controls always get the shape they
    expect regardless of how the value sits on disk.
    """
    if value is None:
        return field.default
    if field.kind == "bool":
        from utils import is_truthy_value

        return "true" if is_truthy_value(value) else "false"
    if field.kind == "json":
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value)
    return str(value)


def read_field(field: ProviderField, sources: tuple, env: dict) -> Any:
    """Return the stored native value from the first source holding it, or ``None``.

    Presence (``key in source``) decides, not truthiness, so a stored ``False``
    or ``0`` survives instead of being mistaken for "unset".
    """
    for source in sources:
        for source_key in (field.key, *field.aliases):
            if source_key in source and source[source_key] is not None:
                return source[source_key]
    for env_key in field.env_fallbacks:
        value = env.get(env_key)
        if value:
            return value
    return None


def declared_field_is_set(field: ProviderField, sources: tuple, env: dict) -> bool:
    for env_key in (field.env_key, *field.env_fallbacks):
        if env_key and env.get(env_key):
            return True
    return any(source.get(k) for source in sources for k in (field.key, *field.aliases))


def apply_field_values(provider: ProviderConfigSchema, values: dict, target_for: Callable) -> None:
    """Apply submitted non-secret fields to their backend dict, in place.

    Only keys present in ``values`` are touched, so a partial save never
    clobbers fields owned by another surface. :data:`UNSET` clears the key (and
    its aliases) so it falls back to the host/default mapping.
    """
    for field in provider.fields:
        if field.is_secret or field.key not in values:
            continue
        target = target_for(field)
        coerced = coerce_field_value(field, values[field.key])
        if coerced is UNSET:
            target.pop(field.key, None)
            for alias in field.aliases:
                target.pop(alias, None)
        else:
            target[field.key] = coerced
