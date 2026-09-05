#!/usr/bin/env python3
"""Find an iMessage/SMS chat by name or handle, wrapping ``imsg chats``.

``imsg chats --json`` emits *newline-delimited* JSON objects (one object per
chat), not a JSON array, so the naive ``jq '.[]'`` pipeline fails. This
helper parses that stream and filters chats whose display name, contact name,
handle, guid, or participants match a query. Run without a query to list
recent chats.

Usage:
    find_chat.py "Mom"                 # match name/handle containing "Mom"
    find_chat.py "+14155551212"        # match an exact-ish handle
    find_chat.py --limit 200 --json    # list recent chats as a JSON array
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def parse_chats(stdout: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON chat objects from ``imsg chats --json``."""
    chats: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            chat = json.loads(line)
        except json.JSONDecodeError:
            # Log lines and other non-JSON output are ignored, not fatal.
            continue
        if isinstance(chat, dict):
            chats.append(chat)
    return chats


def _searchable_fields(chat: dict[str, Any]) -> list[str]:
    return [
        str(chat.get("name") or ""),
        str(chat.get("display_name") or ""),
        str(chat.get("identifier") or ""),
        str(chat.get("guid") or ""),
        str(chat.get("last_addressed_handle") or ""),
        *[str(p) for p in (chat.get("participants") or [])],
    ]


def matches(chat: dict[str, Any], query: str) -> bool:
    """Return True if any searchable field contains ``query`` (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return True
    return q in " ".join(_searchable_fields(chat)).lower()


def format_chat(chat: dict[str, Any]) -> str:
    """Render a single chat as a one-line summary keyed on its rowid."""
    name = chat.get("name") or chat.get("display_name") or "(no name)"
    service = chat.get("service") or "?"
    identifier = chat.get("identifier") or ""
    participants = ", ".join(chat.get("participants") or [])
    last = (chat.get("last_message_at") or "")[:19]
    return (
        f"id={chat.get('id')}  {name}  [{service}]  {identifier}"
        f"  participants={participants}  last={last}"
    )


def run_chats(limit: int) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["imsg", "chats", "--limit", str(limit), "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "imsg chats failed\n")
        raise SystemExit(proc.returncode or 1)
    return parse_chats(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "query",
        nargs="?",
        help="name or handle substring to match (omit to list recent chats)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="max chats to scan (default 100)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit matching chats as a JSON array",
    )
    args = parser.parse_args(argv)

    chats = run_chats(args.limit)
    if args.query:
        chats = [c for c in chats if matches(c, args.query)]

    if args.json:
        print(json.dumps(chats, indent=2))
        return 0

    if not chats:
        print(
            f"No chats match {args.query!r}" if args.query else "No chats found."
        )
        return 1

    for chat in chats:
        print(format_chat(chat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
