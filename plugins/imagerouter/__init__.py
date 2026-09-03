"""ImageRouter integration plugin — bundled, auto-loaded.

Registers two tools into the ``imagerouter`` toolset:

- ``imagerouter_generate`` — text-to-image across ImageRouter's catalog,
  defaulting to an unfiltered community SDXL fine-tune so creative prompts
  are not refused by a provider-side filter.
- ``imagerouter_models`` — browse the catalog with prices.

Why a plugin rather than a ``tools/`` file: the Footprint Ladder in AGENTS.md
puts third-party service integrations in ``plugins/``. The in-tree
``image_generate`` tool is fal-specific; this sits beside it rather than
growing it, and neither touches the other.

Auth: ``IMAGEROUTER_API_KEY`` in ``~/.hermes/.env`` (secrets only). The key
lives in the 1Password item "Image Router". Tools stay registered without a
key so they appear in ``hermes tools``; ``check_fn`` blocks dispatch until
one is present.
"""

from __future__ import annotations

from plugins.imagerouter.tools import (
    IMAGEROUTER_GENERATE_SCHEMA,
    IMAGEROUTER_MODELS_SCHEMA,
    _check_imagerouter_available,
    _handle_imagerouter_generate,
    _handle_imagerouter_models,
)

_TOOLS = (
    ("imagerouter_generate", IMAGEROUTER_GENERATE_SCHEMA, _handle_imagerouter_generate, "🖼️"),
    ("imagerouter_models", IMAGEROUTER_MODELS_SCHEMA, _handle_imagerouter_models, "📇"),
)


def register(ctx) -> None:
    """Register the ImageRouter tools. Called once by the plugin loader."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="imagerouter",
            schema=schema,
            handler=handler,
            check_fn=_check_imagerouter_available,
            emoji=emoji,
        )
