"""Persistent echo guard for BlueBubbles self-chats.

A self-chat (Hermes's Mac and the human texting it share one Apple ID) makes
``isFromMe`` useless for telling "the user sent this from their phone" apart
from "Hermes sent this to itself" -- both look identical to BlueBubbles. The
adapter therefore lets configured self-chat GUIDs through the ``isFromMe``
filter and relies on this module to recognize Hermes's own outbound messages
instead, so they are never re-dispatched as new inbound turns.

Three independent guards, because each alone has a gap:

- ``was_sent_by_us(guid)`` -- a durable (state.db-backed) record of every
  message guid ``BlueBubblesAdapter.send()`` produced, checked by exact
  match. Durable rather than in-memory because the crash-recovery
  redelivery path in ``delivery_ledger.py`` resends unconfirmed replies
  *after a gateway restart* -- the one case an in-memory set can't cover,
  and exactly the case that caused a self-reply burst on 2026-09-03.
- ``looks_like_own_marker(text)`` -- a content check for boilerplate only
  Hermes emits (the delivery-ledger's recovered-reply marker). Catches the
  narrow race where BlueBubbles' webhook for a just-sent message arrives
  before the sender's HTTP response (carrying the real guid) comes back,
  so the guid was never recorded in time.
- ``was_text_sent_recently(chat_guid, text)`` -- identity-independent: did
  Hermes send this exact text to this chat in the last few minutes? Applied
  to EVERY inbound message, listed self-chat or not, ``isFromMe`` or not.
  Exists because of the second 2026-09-03 loop: with the Mac's iMessage
  identity set to the same phone number the iPhone sends from, Apple
  delivered each of Hermes's own replies back to the Mac as an *incoming*
  message from that number (``isFromMe=False``, a fresh guid) -- so neither
  guard above could see it, and Hermes answered itself every ~3s until the
  gateway was killed. The guid and isFromMe checks depend on how Apple
  labels the echo; the text check does not.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

_DB_LOCK = threading.Lock()
_RETENTION_SECONDS = 24 * 60 * 60  # sent guids only need to outlive one restart cycle
_MAX_ROWS = 500
# How long a sent text is treated as "ours" when it comes back inbound. An
# echo arrives within seconds; the window is generous for AppleScript
# backlogs (120s+ send latency was observed) while keeping the
# false-positive case -- the user typing the identical string Hermes just
# sent -- to a few minutes.
_TEXT_ECHO_WINDOW_SECONDS = 5 * 60


def _db_path():
    return get_hermes_home() / "state.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        _initialize_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _initialize_schema(conn: sqlite3.Connection) -> None:
    from hermes_state import apply_wal_with_fallback

    apply_wal_with_fallback(conn, db_label="state.db (bluebubbles_self_chat_guard)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS bluebubbles_self_chat_sent_guids (
            message_guid TEXT PRIMARY KEY,
            chat_guid TEXT NOT NULL,
            created_at REAL NOT NULL
        )"""
    )
    # Text echo guard: (chat, sha256 of stripped text) -> last send time.
    # Hashed so message content never sits in state.db; keyed per chat so a
    # reply to one thread can't suppress an identical message in another.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS bluebubbles_sent_texts (
            chat_guid TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (chat_guid, text_hash)
        )"""
    )


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def record_sent(
    message_guid: Optional[str], chat_guid: str, text: Optional[str] = None
) -> None:
    """Record a message BlueBubblesAdapter.send() just produced.

    ``message_guid`` feeds ``was_sent_by_us``; ``text`` (when given) feeds
    ``was_text_sent_recently``. Either may be absent -- BlueBubbles doesn't
    always return a guid -- and the other is still recorded.

    Best-effort: a failure here must never block the send it's recording,
    but it IS logged: a silent miss reopens the echo window with no trace.
    """
    if not message_guid and not (text and text.strip()):
        return
    now = time.time()
    try:
        with _DB_LOCK, _transaction() as conn:
            if message_guid:
                conn.execute(
                    """INSERT OR REPLACE INTO bluebubbles_self_chat_sent_guids
                       (message_guid, chat_guid, created_at) VALUES (?, ?, ?)""",
                    (message_guid, chat_guid, now),
                )
                conn.execute(
                    """DELETE FROM bluebubbles_self_chat_sent_guids
                       WHERE message_guid NOT IN (
                           SELECT message_guid FROM bluebubbles_self_chat_sent_guids
                           ORDER BY created_at DESC LIMIT ?
                       ) OR created_at < ?""",
                    (_MAX_ROWS, now - _RETENTION_SECONDS),
                )
            if text and text.strip():
                conn.execute(
                    """INSERT OR REPLACE INTO bluebubbles_sent_texts
                       (chat_guid, text_hash, created_at) VALUES (?, ?, ?)""",
                    (chat_guid, _text_hash(text), now),
                )
                conn.execute(
                    "DELETE FROM bluebubbles_sent_texts WHERE created_at < ?",
                    (now - _RETENTION_SECONDS,),
                )
    except Exception as exc:
        logger.warning(
            "[bluebubbles] self-chat guard failed to record sent message "
            "(echo protection degraded for this message): %s",
            exc,
        )


def was_sent_by_us(message_guid: Optional[str]) -> bool:
    """True if this guid was recorded by a prior ``record_sent`` call."""
    if not message_guid:
        return False
    try:
        with _DB_LOCK, _transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM bluebubbles_self_chat_sent_guids WHERE message_guid = ?",
                (message_guid,),
            ).fetchone()
            return row is not None
    except Exception:
        # Fail open toward "not ours" -- a missed dedup drops one message
        # into the agent loop; a false-positive dedup silently eats a real
        # reply from the user. The former is the safer failure.
        return False


def was_text_sent_recently(chat_guid: Optional[str], text: Optional[str]) -> bool:
    """True if Hermes sent exactly *text* to *chat_guid* within the echo window.

    Identity-independent echo detection -- see module docstring. Fails open
    (False) on any error for the same reason ``was_sent_by_us`` does.
    """
    if not chat_guid or not text or not text.strip():
        return False
    try:
        with _DB_LOCK, _transaction() as conn:
            row = conn.execute(
                """SELECT 1 FROM bluebubbles_sent_texts
                   WHERE chat_guid = ? AND text_hash = ? AND created_at >= ?""",
                (chat_guid, _text_hash(text), time.time() - _TEXT_ECHO_WINDOW_SECONDS),
            ).fetchone()
            return row is not None
    except Exception:
        return False


def looks_like_own_marker(text: str) -> bool:
    """True when *text* is boilerplate only Hermes itself emits.

    Independent of guid timing: covers the race where BlueBubbles' webhook
    for a just-sent message arrives before the sender's HTTP response (and
    thus the real guid) comes back to ``record_sent``.
    """
    if not text:
        return False
    from gateway.delivery_ledger import RECOVERED_MARKER

    return text.startswith(RECOVERED_MARKER.strip().split("\n")[0])
