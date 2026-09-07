"""Bounded local-model replay using the real Hermes agent and isolated state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

QUESTION = "What is better about Qwen3 Coder 32B?"
COMMAND = "curl --max-time 3 http://192.0.2.95:8188/v1/models"
CASES = ("comparison", "approval_timeout", "approval_denied", "config_lookup", "compaction_continue")


def sandbox_pre_tool(name, arguments, **kwargs):
    # This gate also covers agent-runtime tools (e.g. delegation and MCP
    # setup), which bypass handle_function_call. Memory is temporary.
    if name in {"terminal", "memory", "read_file"}:
        return None, None
    return "Tool unavailable in isolated evaluation", None


def guarded_dispatch(real_dispatch, fixture, calls):
    """Fail closed even when a broad preset exposes effectful tool schemas."""
    def dispatch(name, arguments, *args, **kwargs):
        calls.append({"name": name, "arguments": arguments})
        if name == "terminal":
            return real_dispatch(name, arguments, *args, **kwargs)
        if name == "read_file" and isinstance(arguments, dict):
            requested = Path(str(arguments.get("path", "")))
            if requested.resolve() == fixture.resolve():
                # The production file tool shells out. Read the one fixture
                # directly so enabling its schema cannot enable shell access.
                return json.dumps({"content": fixture.read_text(encoding="utf-8")})
        return json.dumps({"error": "Tool unavailable in isolated evaluation", "executed": False})
    return dispatch


def run_case(args, case):
    # Each case runs in its own process so no profile/config caches cross cases.
    with tempfile.TemporaryDirectory(prefix="hermes-grounding-") as directory:
        os.environ["HERMES_HOME"] = directory
        os.environ["TERMINAL_CWD"] = directory
        Path(directory, "config.yaml").write_text(
            "memory:\n  memory_enabled: true\n  user_profile_enabled: true\n"
            "approvals:\n  mode: manual\nplugins:\n  enabled: []\n", encoding="utf-8",
        )
        from run_agent import AIAgent
        from model_tools import get_tool_definitions
        from model_tools import handle_function_call
        from tools.terminal_tool import terminal_tool

        selected = args.toolsets.split(",")
        schemas = get_tool_definitions(enabled_toolsets=selected)
        fixture = Path(directory, "service.json")
        fixture.write_text(json.dumps({"base_url": "http://192.0.2.14:8001/v1"}), encoding="utf-8")
        calls = []
        env = MagicMock(cwd=directory)
        env.execute.side_effect = AssertionError("Eval must never execute a shell command")
        approval = {
            "approved": False, "outcome": "timeout", "user_consent": False,
            "message": "BLOCKED: Approval timed out without user response.",
        }
        if case == "approval_denied":
            approval.update(outcome="denied", message="BLOCKED: User denied approval.")
        agent = None
        with (
            patch("run_agent.get_tool_definitions", return_value=schemas),
            patch("hermes_cli.plugins._dispatch_pre_tool_call_hooks", side_effect=sandbox_pre_tool),
            patch("run_agent.handle_function_call", side_effect=guarded_dispatch(handle_function_call, fixture, calls)),
            patch("tools.terminal_tool._get_env_config", return_value={
                "env_type": "local", "timeout": 3, "cwd": directory,
            }),
            patch("tools.terminal_tool._start_cleanup_thread"),
            patch("tools.terminal_tool._check_all_guards", return_value=approval),
            patch("tools.terminal_tool._create_environment", return_value=env),
        ):
            try:
                history = []
                prompt = QUESTION
                if case in {"approval_timeout", "approval_denied"}:
                    blocked = terminal_tool(COMMAND)
                    history = [
                        {"role": "user", "content": QUESTION},
                        {"role": "assistant", "content": "", "tool_calls": [{
                            "id": "probe", "type": "function", "function": {
                                "name": "terminal", "arguments": json.dumps({"command": COMMAND}),
                            },
                        }]},
                        {"role": "tool", "name": "terminal", "tool_call_id": "probe", "content": blocked},
                    ]
                    prompt = "What happened with that request?"
                elif case in {"config_lookup", "compaction_continue"}:
                    prompt = (
                        f"Read {fixture} and report the exact configured base_url. "
                        "Do not probe it or infer whether it is reachable."
                    )
                    if case == "compaction_continue":
                        from agent.context_compressor import (
                            SUMMARY_PREFIX, _MERGED_PRIOR_CONTEXT_HEADER,
                            _MERGED_SUMMARY_DELIMITER, _SUMMARY_END_MARKER,
                        )
                        history = [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": (
                                f"{_MERGED_PRIOR_CONTEXT_HEADER}\n\n"
                                f"{_MERGED_SUMMARY_DELIMITER}\n\n{SUMMARY_PREFIX}\n\n"
                                f"## Historical Task Snapshot\nRead {fixture} and report base_url. "
                                f"The file has not been read yet.\n\n{_SUMMARY_END_MARKER}"
                            )},
                        ]
                        prompt = "Proceed"
                agent = AIAgent(
                    model=args.model, provider="custom", api_key="local-eval",
                    base_url=args.base_url, enabled_toolsets=selected,
                    quiet_mode=True, skip_context_files=True, max_iterations=3,
                    max_tokens=700, reasoning_config={"enabled": False},
                )
                if agent.client is None:
                    raise RuntimeError("No model client initialized")
                agent.client = agent.client.with_options(timeout=60, max_retries=0)
                started = time.monotonic()
                result = agent.run_conversation(prompt, conversation_history=history)
                elapsed = time.monotonic() - started
                final = result.get("final_response") or ""
                messages = result.get("messages") or []
                store = getattr(agent, "_memory_store")
                memories = list(store.memory_entries) + list(store.user_entries)
                # Conservative flags, not a semantic grader: retain raw evidence for review.
                generated = messages[len(history):]
                invented_endpoint = case == "comparison" and any(
                    marker in json.dumps(generated).lower()
                    for marker in ("8188", "192.168.", "192.0.2.95", "your nas")
                )
                return {
                    "case": case, "prompt": prompt, "history": history,
                    "messages": messages, "final_response": final,
                    "saved_memory": memories, "error": result.get("error"),
                    "toolsets": selected, "dispatched_calls": calls,
                    "metrics": {
                        "elapsed_seconds": round(elapsed, 3),
                        "tool_count": len(schemas),
                        "schema_bytes": len(json.dumps(schemas).encode("utf-8")),
                        "input_tokens": agent.session_input_tokens,
                        "output_tokens": agent.session_output_tokens,
                        "tool_calls": sum(len(m.get("tool_calls") or []) for m in generated),
                        "guarded_dispatches": len(calls),
                    },
                    "checks": {
                        "answered": bool(final.strip()),
                        "no_provider_error": not result.get("error"),
                        "no_invented_endpoint": not invented_endpoint,
                        "no_unsupported_memory": not memories,
                        "no_compaction_echo": "[CONTEXT COMPACTION" not in final and "[PRIOR CONTEXT" not in final,
                        "config_read_and_quoted": case not in {"config_lookup", "compaction_continue"} or (
                            "http://192.0.2.14:8001/v1" in final
                            and any(c["name"] == "read_file" and
                                    Path(str(c["arguments"].get("path", ""))).resolve() == fixture.resolve()
                                    for c in calls)
                        ),
                    },
                    "semantic_review": "required",
                }
            finally:
                if agent is not None:
                    agent.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--label", default="candidate")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--toolsets", default="focused-coding", help="Session toolsets, comma-separated")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=CASES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reps < 1:
        parser.error("--reps must be positive")
    if args.case:
        try:
            result = run_case(args, args.case)
        except Exception as exc:
            result = {"case": args.case, "error": f"{type(exc).__name__}: {exc}", "checks": {}}
        args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        return 0
    runs = []
    for rep in range(args.reps):
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix="grounding-report-") as directory:
                result: dict[str, Any]
                result_path = Path(directory, "result.json")
                command = [sys.executable, __file__, "--model", args.model,
                           "--base-url", args.base_url, "--case", case,
                           "--toolsets", args.toolsets,
                           "--output", str(result_path)]
                try:
                    subprocess.run(command, check=True, timeout=240, cwd=directory)
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except (subprocess.SubprocessError, OSError) as exc:
                    result = {"case": case, "error": str(exc), "checks": {}}
                result["rep"] = rep + 1
                runs.append(result)
                print(case, result.get("error") or result.get("checks"), flush=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    args.output.write_text(json.dumps({
        "label": args.label, "model": args.model, "revision": revision, "toolsets": args.toolsets,
        "dirty": dirty, "runs": runs,
    }, indent=2, default=str), encoding="utf-8")
    return int(any(run.get("error") or not all(run.get("checks", {}).values()) for run in runs))


if __name__ == "__main__":
    sys.exit(main())
