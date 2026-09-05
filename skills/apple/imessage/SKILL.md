---
name: imessage
description: Send and receive iMessages/SMS via the imsg CLI on macOS.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [iMessage, SMS, messaging, macOS, Apple]
prerequisites:
  commands: [imsg]
---

# iMessage Skill

Read and send iMessage/SMS on macOS by driving the `imsg` CLI through the
`terminal` tool. Covers listing chats, reading history, searching, and
sending. It does not manage group membership, and it is not the gateway's
BlueBubbles/Photon iMessage adapter — this skill operates your local
Messages.app directly.

## When to Use

- User asks to send an iMessage or text message.
- Reading iMessage conversation history or searching past messages.
- Checking who is reachable on iMessage vs SMS before sending.
- Finding a chat by contact name or phone number.

## When NOT to Use

- Telegram/Discord/Slack/WhatsApp → use the matching gateway channel.
- Bulk/mass messaging → confirm with the user first.

## Prerequisites

- macOS with Messages.app signed in.
- Install: `brew install steipete/tap/imsg`.
- Full Disk Access for the process that runs Hermes (System Settings →
  Privacy & Security → Full Disk Access). `imsg` reads `chat.db` and inherits
  its parent's permission — a CLI session inherits your terminal's grant, but
  the gateway under launchd does not; add the Python binary the venv resolves
  to (`readlink -f venv/bin/python`), then restart the gateway.
- Automation permission for Messages.app when prompted.

## How to Run

Run everything through the `terminal` tool. Use `scripts/find_chat.py` to
turn a contact name into a chat `id`/`identifier` instead of hand-writing
`jq` filters (chats output is newline-delimited JSON, not an array).

## Quick Reference

| Task | Command |
|------|---------|
| List recent chats | `imsg chats --limit 10 --json` |
| Find a chat by name/number | `scripts/find_chat.py "Mom"` |
| Read a chat's history | `imsg history --chat-id <id> --limit 20 --json` |
| History with attachments | `imsg history --chat-id <id> --attachments --json` |
| Search all history | `imsg search --query "pizza tonight"` |
| Check iMessage vs SMS reachability | `imsg whois --address +15551234567 --local` |
| Show the active account | `imsg account` |
| Show chat identity + participants | `imsg group --chat-id <id> --json` |
| Send text | `imsg send --to "+14155551212" --text "Hi"` |
| Send to an existing chat | `imsg send --chat-id <id> --text "Hi"` |
| Send with attachment | `imsg send --to <handle> --text "..." --file /path/file.jpg` |
| React to the latest message | `imsg react --chat-id <id> --reaction like` |
| Full CLI reference | `imsg completions llm` |

### Send flags

- `--to <phone|email>` — recipient handle.
- `--chat-id <id>` / `--chat-identifier <guid>` / `--chat-guid <guid>` —
  target an existing chat (prefer `--chat-id` once you know it).
- `--service imessage|sms|auto` — force the bubble color or let Messages
  decide (default `auto`).
- `--no-sms-fallback` — disable automatic iMessage→SMS fallback on auto phone
  sends (use when the recipient must receive an iMessage).
- `--file <path>` — attach a file. Verify the path exists first.
- `--json` — machine-readable result.

### Basic vs advanced features

Run `imsg status` to see what the machine supports. Basic commands
(`chats`, `group`, `history`, `watch`, `send`, `search`, `account`,
`whois --local`, `react`) work without System Integrity Protection disabled.
Advanced features (`typing`, `read`, `send-rich`, and most `chat-*`/`edit`/
`unsend`/`poll` commands) require the IMCore bridge: SIP disabled, `imsg
launch` to inject the dylib, and Messages.app running. Do not attempt those
without checking `imsg status` first; fall back to `send` for outbound text.

## Procedure

### Find a chat

```bash
# List recent chats (or search by name/number)
scripts/find_chat.py "Mom"

# Filter to a handle if the name isn't in Contacts
scripts/find_chat.py "+14155551212"
```

Each line gives the rowid (`id=…`), name, service, identifier, participants,
and last-activity time. Use the `id` with `--chat-id`.

### Read history

```bash
imsg history --chat-id 1 --limit 20 --json
# Narrow to a window or a participant
imsg history --chat-id 1 --start 2026-01-01T00:00:00Z --end 2026-02-01T00:00:00Z --json
imsg history --chat-id 1 --participants +15551234567 --json
```

`--convert-attachments` converts CAF voice notes/GIFs to cached files a model
can ingest.

### Send

```bash
imsg send --to "+14155551212" --text "I'll be late" --service imessage
```

Confirm recipient and content with the user before sending; never send to an
unknown number without explicit approval.

## Pitfalls

- **`chats --json` is newline-delimited JSON, not an array.** `jq '.[]'` on
  it breaks, and the field is `display_name`, not `displayName`. Use
  `scripts/find_chat.py` rather than hand-rolling `jq`.
- **`authorization denied` / `unable to open database` on `chat.db` after it
  used to work.** Full Disk Access is bound to the exact binary path; a
  Homebrew Python upgrade moves that path, so the gateway's grant silently
  stops applying. Toggle the new binary on in Full Disk Access and restart
  the gateway. Adding Terminal.app does nothing for a launchd job.
- **Advanced commands fail with SIP enabled.** `typing`/`read`/`send-rich`
  need SIP disabled plus `imsg launch`; confirm with `imsg status` before
  relying on them.
- **`react` only targets the most recent incoming message** and needs
  Messages.app running with accessibility permissions.

## Verification

- `imsg status` shows basic features available and whether advanced features
  are enabled.
- `imsg whois --address <handle> --local` confirms reachability before a send.
- `scripts/find_chat.py "<name>"` returns a chat with the expected `id`.
