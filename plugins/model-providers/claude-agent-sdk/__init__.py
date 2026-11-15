"""Claude subscription (Pro/Max) via the Claude Agent SDK.

Inference runs through the ``claude`` CLI that the Claude Agent SDK drives, so it bills the user's
Claude subscription instead of an API key. Hermes stays the agent loop (see ``client.py``): the
SDK is used as a tool-less, single-turn completion transport, exactly like the ACP providers.

Login: ``claude`` (interactive) or ``claude setup-token`` with ``CLAUDE_CODE_OAUTH_TOKEN`` in
``~/.hermes/.env`` (a long-lived token that survives the keychain login expiring).
Setup: ``hermes model`` → "Claude (subscription via Agent SDK)", or ``model.provider: claude-agent-sdk``.
"""

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


class ClaudeAgentSDKProfile(ProviderProfile):
    """External-process provider: the SDK spawns the CLI, which owns authentication."""

    def create_client(self, **client_kwargs: Any) -> Any:
        """Build the SDK-backed client rather than an HTTP client."""
        from .client import ClaudeAgentSDKClient

        return ClaudeAgentSDKClient(**client_kwargs)


claude_agent_sdk = ClaudeAgentSDKProfile(
    name="claude-agent-sdk",
    aliases=("claude-max", "claude-subscription", "claude-code-sdk"),
    display_name="Claude (subscription via Agent SDK)",
    description="Claude Pro/Max subscription through the Claude Agent SDK (no API key)",
    signup_url="https://claude.com/pricing",
    api_mode="chat_completions",  # the client is OpenAI-shaped; no HTTP route is involved
    env_vars=(),  # the CLI owns auth; CLAUDE_CODE_OAUTH_TOKEN is read by the client, not the registry
    base_url="acp://claude-agent-sdk",  # internal scheme: core routes ``acp://`` runtimes to create_client()
    auth_type="external_process",
    supports_model_listing=False,
    supports_health_check=False,
    default_aux_model="claude-haiku-5-5",
    process_command="claude",
    process_command_env_vars=("HERMES_CLAUDE_SDK_COMMAND", "CLAUDE_CLI_PATH"),
    fallback_models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
    model_aliases={
        "opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5",
    },
)

register_provider(claude_agent_sdk)
