"""OpenAI-shaped client that runs each Hermes request as one Claude Agent SDK completion.

The Claude Agent SDK drives the ``claude`` CLI, which authenticates with the user's Claude
subscription (Pro/Max) login or a ``claude setup-token`` token. Hermes stays the agent loop: every
call is a stateless, single-turn, tool-less SDK session, so the SDK contributes inference and
nothing else. Hermes' own tools reach the model as schemas in the prompt and come back as
``<tool_call>`` blocks, the same bridge the ACP providers use (``agent.acp_openai_bridge``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from types import SimpleNamespace
from typing import Any, Mapping

from agent.acp_openai_bridge import (
    completion_to_stream_chunks,
    extract_tool_calls_from_text,
    render_tool_bridge_sections,
)
from agent.secret_scope import get_secret_str

logger = logging.getLogger(__name__)

SDK_EXTRA = "claude-agent-sdk"
DEFAULT_MODEL_PLACEHOLDER = "claude-agent-sdk"
_DEFAULT_TIMEOUT_SECONDS = 900.0
_ROLE_LABELS = {"user": "User", "assistant": "Assistant", "tool": "Tool", "context": "Context"}
# Credentials and routing that would make the CLI bill an API key / cloud account instead of the
# subscription. Blanked (not removed) because the SDK merges ``env`` over the parent environment.
_BILLING_OVERRIDE_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)
_SETUP_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
_ERROR_LABEL_STATUS = {
    "authentication_failed": 401, "billing_error": 402, "rate_limit": 429,
    "invalid_request": 400, "server_error": 500,
}
_CLI_HINT = "Install Claude Code, or set HERMES_CLAUDE_SDK_COMMAND (or CLAUDE_CLI_PATH) to the `claude` binary."
_PROMPT_CLOSER = "Continue the conversation with the next assistant turn."


class ClaudeSDKCompletionError(RuntimeError):
    """The SDK reported a failed completion. ``status_code`` feeds Hermes' error classifier."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ── prompt rendering ────────────────────────────────────────────────────────────────────────

def _content_text(content: Any) -> str:
    """Flatten OpenAI message content to text; image parts become a placeholder, never raw bytes."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return str(content).strip()
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part.strip())
        elif isinstance(part, dict):
            if isinstance(part.get("text"), str):
                parts.append(part["text"].strip())
            elif str(part.get("type", "")).startswith("image"):
                parts.append("[image omitted: not supported by this provider]")
    return "\n".join(p for p in parts if p)


def _render_tool_calls(tool_calls: Any) -> str:
    """Prior assistant tool calls, in the same ``<tool_call>`` shape the model is asked to emit."""
    blocks: list[str] = []
    for call in tool_calls or []:
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        blocks.append("<tool_call>" + json.dumps(
            {"id": call.get("id", ""), "type": "function",
             "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", "{}")}},
            ensure_ascii=False) + "</tool_call>")
    return "\n".join(blocks)


def render_prompt(
    messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: Any = None,
) -> tuple[str, str]:
    """``(system_prompt, prompt)``: system messages go to the SDK's system prompt, the rest becomes a transcript."""
    system_parts: list[str] = []
    turns: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user")
        text = _content_text(message.get("content"))
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        label = _ROLE_LABELS.get(role, role.title())
        if role == "tool":
            call_id = message.get("tool_call_id") or ""
            label = f"Tool result ({call_id})" if call_id else "Tool result"
        body = "\n".join(p for p in (text, _render_tool_calls(message.get("tool_calls"))) if p)
        if body:
            turns.append(f"{label}:\n{body}")
    sections = [*render_tool_bridge_sections(tools, tool_choice), *turns, _PROMPT_CLOSER]
    return "\n\n".join(system_parts), "\n\n".join(sections)


# ── SDK plumbing ────────────────────────────────────────────────────────────────────────────

def _load_sdk() -> Any:
    """Import ``claude_agent_sdk``, installing the optional extra on first use."""
    try:
        import claude_agent_sdk
        return claude_agent_sdk
    except ImportError:
        from pm.extras import ensure_import

        ensure_import(SDK_EXTRA)
        import claude_agent_sdk
        return claude_agent_sdk


def _subprocess_env() -> dict[str, str]:
    """Env overrides for the CLI: subscription auth only, never an API key or cloud route."""
    env = {name: "" for name in _BILLING_OVERRIDE_ENV}
    if token := get_secret_str(_SETUP_TOKEN_ENV).strip():
        env[_SETUP_TOKEN_ENV] = token
    return env


def _effective_timeout(timeout: Any) -> float:
    """Wall-clock seconds from a float or an httpx.Timeout-like object (largest component wins)."""
    if isinstance(timeout, (int, float)):
        return float(timeout)
    parts = [getattr(timeout, attr, None) for attr in ("read", "write", "connect", "pool", "timeout")]
    return max((float(p) for p in parts if isinstance(p, (int, float))), default=_DEFAULT_TIMEOUT_SECONDS)


def _build_options(sdk: Any, *, system_prompt: str, model: str | None, command: str | None,
                   cwd: str | None, env: Mapping[str, str]) -> Any:
    """One tool-less, settings-less, single-turn session that leaves no transcript on disk."""
    return sdk.ClaudeAgentOptions(
        tools=[],
        max_turns=1,
        setting_sources=[],
        mcp_servers={},
        strict_mcp_config=True,
        verbatim_prompts=True,
        system_prompt=system_prompt,
        model=model or None,
        cli_path=command or None,
        cwd=cwd,
        env=dict(env),
        extra_args={"no-session-persistence": None},
    )


class _Reply(SimpleNamespace):
    """Accumulated SDK output: text, reasoning, usage dict, stop reason."""


def _raise_for_error(message: Any, result: Any) -> None:
    """Translate an SDK-reported failure into ``ClaudeSDKCompletionError`` with an HTTP-like status."""
    label = getattr(message, "error", None)
    status = getattr(result, "api_error_status", None) or _ERROR_LABEL_STATUS.get(label or "")
    detail = "; ".join(getattr(result, "errors", None) or []) or getattr(result, "result", None) or label or "unknown error"
    raise ClaudeSDKCompletionError(f"Claude Agent SDK request failed: {detail}", status)


async def _collect(sdk: Any, prompt: str, options: Any) -> _Reply:
    reply = _Reply(text=[], reasoning=[], usage=None, stop_reason=None)
    failed_message: Any = None
    async for message in sdk.query(prompt=prompt, options=options):
        if isinstance(message, sdk.AssistantMessage):
            if getattr(message, "parent_tool_use_id", None):
                continue  # subagent chatter is not the reply
            if getattr(message, "error", None):
                failed_message = message
            reply.stop_reason = getattr(message, "stop_reason", None) or reply.stop_reason
            for block in message.content:
                if isinstance(block, sdk.TextBlock):
                    reply.text.append(block.text)
                elif isinstance(block, sdk.ThinkingBlock):
                    reply.reasoning.append(block.thinking)
        elif isinstance(message, sdk.ResultMessage):
            reply.usage = getattr(message, "usage", None)
            reply.stop_reason = getattr(message, "stop_reason", None) or reply.stop_reason
            if getattr(message, "is_error", False) or failed_message is not None:
                _raise_for_error(failed_message, message)
    return reply


def _usage(raw: Mapping[str, Any] | None) -> SimpleNamespace:
    raw = raw or {}
    cached = int(raw.get("cache_read_input_tokens") or 0)
    prompt = int(raw.get("input_tokens") or 0) + cached + int(raw.get("cache_creation_input_tokens") or 0)
    completion = int(raw.get("output_tokens") or 0)
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached))


class ClaudeAgentSDKClient:
    """Drop-in for the slice of ``openai.OpenAI`` Hermes uses: ``client.chat.completions.create``."""

    def __init__(self, *, command: str | None = None, cwd: str | None = None, **_: Any) -> None:
        self._command = command
        self._cwd = cwd or _default_cwd()
        self._lock = threading.Lock()
        self._active: set[tuple[asyncio.AbstractEventLoop, asyncio.Task]] = set()
        self.is_closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat_completion))

    def close(self) -> None:
        """Cancel any in-flight completion (interrupts a running turn). Safe to call repeatedly."""
        with self._lock:
            self.is_closed = True
            active = list(self._active)
        for loop, task in active:
            loop.call_soon_threadsafe(task.cancel)

    def _create_chat_completion(
        self, *, model: str | None = None, messages: list[dict[str, Any]] | None = None, timeout: Any = None,
        tools: list[dict[str, Any]] | None = None, tool_choice: Any = None, stream: bool = False, **_: Any,
    ) -> Any:
        system_prompt, prompt = render_prompt(messages or [], tools=tools, tool_choice=tool_choice)
        sdk_model = None if model in (None, "", DEFAULT_MODEL_PLACEHOLDER) else model
        reply = self._run(prompt, system_prompt, sdk_model, _effective_timeout(timeout))
        tool_calls, content = extract_tool_calls_from_text("".join(reply.text))
        reasoning = "".join(reply.reasoning) or None
        finish = "tool_calls" if tool_calls else ("length" if reply.stop_reason == "max_tokens" else "stop")
        message = SimpleNamespace(
            content=content, tool_calls=tool_calls, reasoning=reasoning, reasoning_content=reasoning,
            reasoning_details=None)
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=_usage(reply.usage),
            model=model or DEFAULT_MODEL_PLACEHOLDER)
        return completion_to_stream_chunks(completion) if stream else completion

    def _run(self, prompt: str, system_prompt: str, model: str | None, timeout: float) -> _Reply:
        """Run the SDK coroutine on a private loop in a worker thread (callers may already sit in a loop)."""
        self.is_closed = False
        sdk = _load_sdk()
        options = _build_options(
            sdk, system_prompt=system_prompt, model=model, command=self._command, cwd=self._cwd,
            env=_subprocess_env())
        outcome: dict[str, Any] = {}

        async def _main() -> _Reply:
            task = asyncio.current_task()
            entry = (asyncio.get_running_loop(), task)
            with self._lock:
                self._active.add(entry)
            try:
                return await asyncio.wait_for(_collect(sdk, prompt, options), timeout)
            finally:
                with self._lock:
                    self._active.discard(entry)

        def _worker() -> None:
            try:
                outcome["reply"] = asyncio.run(_main())
            except BaseException as exc:  # noqa: BLE001 — re-raised on the caller's thread
                outcome["error"] = exc

        thread = threading.Thread(target=_worker, name="claude-agent-sdk", daemon=True)
        thread.start()
        thread.join()
        if (error := outcome.get("error")) is not None:
            raise _translate(sdk, error)
        return outcome["reply"]


def _translate(sdk: Any, error: BaseException) -> BaseException:
    """Map SDK transport failures to errors that say how to fix them; pass everything else through."""
    if isinstance(error, sdk.CLINotFoundError):
        return RuntimeError(f"Could not start the Claude CLI. {_CLI_HINT}")
    if isinstance(error, sdk.ProcessError):
        stderr = (getattr(error, "stderr", None) or "").strip()
        code = getattr(error, "exit_code", None)
        return RuntimeError(f"The Claude CLI exited with code {code}: {stderr or error}")
    if isinstance(error, asyncio.TimeoutError):
        return TimeoutError("Claude Agent SDK request timed out")
    if isinstance(error, asyncio.CancelledError):
        return RuntimeError("Claude Agent SDK request was interrupted")
    return error


def _default_cwd() -> str:
    """A private working directory so CLI-side bookkeeping never mixes with real project history."""
    from hermes_constants import get_hermes_home

    path = get_hermes_home() / "claude-agent-sdk"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
