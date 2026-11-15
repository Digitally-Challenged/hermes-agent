"""Claude Agent SDK provider: prompt rendering, response mapping, error mapping, SDK isolation.

The SDK is replaced by a fake module so the suite needs neither the ``claude-agent-sdk``
extra nor a Claude login. The real SDK's option names are asserted against in the live smoke
procedure, not here (a change-detector on the SDK's surface would only restate the client).
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

MODULE = "plugins.model_providers.claude_agent_sdk.client"


@dataclass
class _TextBlock:
    text: str


@dataclass
class _ThinkingBlock:
    thinking: str
    signature: str = ""


@dataclass
class _AssistantMessage:
    content: list[Any]
    model: str = "claude-sonnet-5-5"
    error: str | None = None
    stop_reason: str | None = None
    parent_tool_use_id: str | None = None


@dataclass
class _ResultMessage:
    is_error: bool = False
    subtype: str = "success"
    result: str | None = None
    errors: list[str] | None = None
    api_error_status: int | None = None
    stop_reason: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class _Options:
    kwargs: dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _CLINotFoundError(Exception):
    pass


class _ProcessError(Exception):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class _FakeSDK(types.ModuleType):
    """Stands in for ``claude_agent_sdk``; ``script`` is the list of messages ``query`` yields."""

    def __init__(self) -> None:
        super().__init__("claude_agent_sdk")
        self.TextBlock, self.ThinkingBlock = _TextBlock, _ThinkingBlock
        self.AssistantMessage, self.ResultMessage = _AssistantMessage, _ResultMessage
        self.ClaudeAgentOptions = _Options
        self.CLINotFoundError, self.ProcessError = _CLINotFoundError, _ProcessError
        self.script: list[Any] = []
        self.raises: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    async def query(self, *, prompt: str, options: _Options):
        self.calls.append({"prompt": prompt, "options": options.kwargs})
        if self.raises is not None:
            raise self.raises
        for message in self.script:
            yield message


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> _FakeSDK:
    fake = _FakeSDK()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)
    return fake


@pytest.fixture
def client_mod(sdk: _FakeSDK):
    return importlib.import_module(MODULE)


@pytest.fixture
def client(client_mod, tmp_path):
    return client_mod.ClaudeAgentSDKClient(command="/usr/bin/claude", cwd=str(tmp_path))


def _ok(text: str, **result: Any) -> list[Any]:
    return [_AssistantMessage([_TextBlock(text)]), _ResultMessage(**result)]


def _create(client, **kwargs: Any):
    kwargs.setdefault("model", "claude-sonnet-5-5")
    kwargs.setdefault("messages", [{"role": "user", "content": "hi"}])
    return client.chat.completions.create(**kwargs)


# ── prompt rendering ────────────────────────────────────────────────────────────────────────

def test_system_messages_become_the_system_prompt_not_the_transcript(client_mod):
    system, prompt = client_mod.render_prompt(
        [{"role": "system", "content": "You are Hermes."}, {"role": "user", "content": "hello"}])
    assert system == "You are Hermes."
    assert "hello" in prompt
    assert "You are Hermes." not in prompt


def test_transcript_keeps_turn_order_and_tool_results(client_mod):
    messages = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "weather", "arguments": '{"city":"Austin"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "72F"},
    ]
    _, prompt = client_mod.render_prompt(messages)
    assert prompt.index("weather?") < prompt.index("call_1") < prompt.index("72F")
    assert '"name": "weather"' in prompt or '"name":"weather"' in prompt


def test_tool_schemas_travel_in_the_prompt_when_offered(client_mod):
    tools = [{"type": "function", "function": {"name": "lookup", "description": "d", "parameters": {"type": "object"}}}]
    _, with_tools = client_mod.render_prompt([{"role": "user", "content": "x"}], tools=tools)
    _, without = client_mod.render_prompt([{"role": "user", "content": "x"}])
    assert "lookup" in with_tools and "<tool_call>" in with_tools
    assert "lookup" not in without


def test_list_content_keeps_text_parts_and_flags_images(client_mod):
    content = [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    _, prompt = client_mod.render_prompt([{"role": "user", "content": content}])
    assert "look" in prompt
    assert "AAAA" not in prompt  # raw image bytes never land in a text prompt
    assert "image" in prompt.lower()


# ── response mapping ────────────────────────────────────────────────────────────────────────

def test_text_reply_maps_to_openai_shape(client, sdk):
    sdk.script = _ok("hello there", usage={"input_tokens": 5, "output_tokens": 7})
    reply = _create(client)
    choice = reply.choices[0]
    assert choice.message.content == "hello there"
    assert choice.message.tool_calls == []
    assert choice.finish_reason == "stop"
    assert reply.model == "claude-sonnet-5-5"


def test_usage_counts_cache_reads_as_prompt_tokens(client, sdk):
    sdk.script = _ok("x", usage={
        "input_tokens": 10, "output_tokens": 4, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20})
    usage = _create(client).usage
    assert usage.prompt_tokens == 130
    assert usage.completion_tokens == 4
    assert usage.total_tokens == 134
    assert usage.prompt_tokens_details.cached_tokens == 100


def test_missing_usage_reports_zeroes(client, sdk):
    sdk.script = _ok("x")
    assert _create(client).usage.total_tokens == 0


def test_tool_call_blocks_become_tool_calls_and_are_stripped_from_content(client, sdk):
    block = '<tool_call>{"id":"c1","type":"function","function":{"name":"lookup","arguments":"{\\"q\\":1}"}}</tool_call>'
    sdk.script = _ok(f"checking\n{block}")
    reply = _create(client)
    message = reply.choices[0].message
    assert [c.function.name for c in message.tool_calls] == ["lookup"]
    assert message.content == "checking"
    assert reply.choices[0].finish_reason == "tool_calls"


def test_thinking_blocks_surface_as_reasoning_not_content(client, sdk):
    sdk.script = [_AssistantMessage([_ThinkingBlock("pondering"), _TextBlock("answer")]), _ResultMessage()]
    message = _create(client).choices[0].message
    assert message.content == "answer"
    assert message.reasoning == "pondering"


def test_subagent_messages_are_ignored(client, sdk):
    sdk.script = [
        _AssistantMessage([_TextBlock("nested")], parent_tool_use_id="toolu_1"),
        _AssistantMessage([_TextBlock("top")]), _ResultMessage()]
    assert _create(client).choices[0].message.content == "top"


def test_max_tokens_stop_reason_is_length(client, sdk):
    sdk.script = [_AssistantMessage([_TextBlock("cut")], stop_reason="max_tokens"), _ResultMessage()]
    assert _create(client).choices[0].finish_reason == "length"


def test_stream_true_returns_chunks_carrying_the_content(client, sdk):
    sdk.script = _ok("streamed")
    chunks = list(_create(client, stream=True))
    assert chunks[0].choices[0].delta.content == "streamed"
    assert chunks[-1].usage is not None


# ── errors ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,status", [
    ("authentication_failed", 401), ("billing_error", 402), ("rate_limit", 429),
    ("invalid_request", 400), ("server_error", 500)])
def test_assistant_error_labels_map_to_http_status(client, client_mod, sdk, label, status):
    sdk.script = [_AssistantMessage([_TextBlock("oops")], error=label), _ResultMessage(is_error=True)]
    with pytest.raises(client_mod.ClaudeSDKCompletionError) as info:
        _create(client)
    assert info.value.status_code == status


def test_result_error_prefers_the_api_status(client, client_mod, sdk):
    sdk.script = [_ResultMessage(is_error=True, api_error_status=529, errors=["overloaded"])]
    with pytest.raises(client_mod.ClaudeSDKCompletionError) as info:
        _create(client)
    assert info.value.status_code == 529
    assert "overloaded" in str(info.value)


def test_missing_cli_explains_how_to_fix_it(client, client_mod, sdk):
    sdk.raises = _CLINotFoundError("nope")
    with pytest.raises(RuntimeError, match="HERMES_CLAUDE_SDK_COMMAND"):
        _create(client)


def test_process_failure_includes_exit_code_and_stderr(client, sdk):
    sdk.raises = _ProcessError("Command failed", exit_code=1, stderr="not logged in")
    with pytest.raises(RuntimeError, match="not logged in"):
        _create(client)


def test_timeout_raises_and_does_not_hang(client_mod, sdk, tmp_path):
    async def _slow(*, prompt, options):
        await asyncio.sleep(30)
        yield  # pragma: no cover

    sdk.query = _slow
    slow = client_mod.ClaudeAgentSDKClient(command="/usr/bin/claude", cwd=str(tmp_path))
    with pytest.raises(TimeoutError):
        _create(slow, timeout=0.2)


# ── isolation: Hermes stays the agent loop ─────────────────────────────────────────────────

def test_sdk_runs_as_a_single_toolless_unconfigured_completion(client, sdk):
    sdk.script = _ok("x")
    _create(client, messages=[{"role": "system", "content": "S"}, {"role": "user", "content": "u"}])
    options = sdk.calls[0]["options"]
    assert options["tools"] == []  # no Claude Code built-ins: Hermes owns the tools
    assert options["max_turns"] == 1
    assert options["setting_sources"] == []  # no user/project CLAUDE.md, hooks or settings
    assert options["strict_mcp_config"] is True and not options["mcp_servers"]
    assert options["verbatim_prompts"] is True  # prompt text may carry untrusted tool output
    assert options["system_prompt"] == "S"
    assert options["cli_path"] == "/usr/bin/claude"
    assert options["model"] == "claude-sonnet-5-5"
    assert "no-session-persistence" in options["extra_args"]


def test_session_runs_in_the_dedicated_cwd(client, sdk, tmp_path):
    sdk.script = _ok("x")
    _create(client)
    assert sdk.calls[0]["options"]["cwd"] == str(tmp_path)


def test_api_key_env_is_blanked_so_the_subscription_pays(client, client_mod, sdk, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-should-not-be-used")
    sdk.script = _ok("x")
    _create(client)
    env = sdk.calls[0]["options"]["env"]
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        assert env[name] == ""
    for name in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        assert env[name] == ""


def test_setup_token_is_forwarded_when_present(client_mod, sdk, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    sdk.script = _ok("x")
    c = client_mod.ClaudeAgentSDKClient(command="/usr/bin/claude", cwd=str(tmp_path))
    _create(c)
    assert sdk.calls[0]["options"]["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fake"


def test_blank_model_is_not_passed_so_the_cli_default_applies(client, sdk):
    sdk.script = _ok("x")
    _create(client, model="")
    assert sdk.calls[0]["options"].get("model") is None


def test_close_is_idempotent(client):
    client.close()
    client.close()
    assert client.is_closed
