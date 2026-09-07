"""The live-model replay must not dispatch tools outside its fixture sandbox."""

import json
from unittest.mock import Mock

from evals.grounding.runner import guarded_dispatch, sandbox_pre_tool


def test_runtime_tools_cannot_bypass_sandbox():
    for name in ("delegate_task", "setup_mcp", "clarify", "session_search", "execute_code", "drive_preview"):
        block, replacement = sandbox_pre_tool(name, {}, session_id="eval")
        assert block
        assert replacement is None
    for name in ("terminal", "memory", "read_file"):
        assert sandbox_pre_tool(name, {}) == (None, None)


def test_dispatch_reads_only_fixture_and_blocks_effects(tmp_path):
    fixture = tmp_path / "service.json"
    fixture.write_text('{"base_url":"http://192.0.2.14/v1"}')
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    real = Mock(side_effect=AssertionError("Unexpected real tool dispatch"))
    calls = []
    dispatch = guarded_dispatch(real, fixture, calls)
    assert json.loads(dispatch("read_file", {"path": str(fixture)}))["content"] == fixture.read_text()
    for name, arguments in (
        ("read_file", {"path": str(outside)}),
        ("read_file", {}),
        ("write_file", {"path": str(fixture), "content": "changed"}),
        ("image_generate", {"prompt": "test"}),
        ("tool_call", {"name": "terminal", "arguments": {"command": "touch unexpected"}}),
    ):
        assert json.loads(dispatch(name, arguments))["executed"] is False
    assert "base_url" in fixture.read_text()
    real.assert_not_called()
    assert len(calls) == 6


def test_terminal_reaches_real_approval_path(tmp_path):
    real = Mock(return_value='{"executed": false, "outcome": "timeout"}')
    dispatch = guarded_dispatch(real, tmp_path / "service.json", [])
    assert json.loads(dispatch("terminal", {"command": "pwd"}, "eval-task"))["executed"] is False
    real.assert_called_once_with("terminal", {"command": "pwd"}, "eval-task")
