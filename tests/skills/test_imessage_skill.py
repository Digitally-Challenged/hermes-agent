"""Tests for skills/apple/imessage/scripts/find_chat.py."""

import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[2] / "skills" / "apple" / "imessage" / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

import find_chat  # noqa: E402


_CHAT = {
    "id": 1,
    "identifier": "+14155551212",
    "guid": "iMessage;-;+14155551212",
    "service": "iMessage",
    "last_message_at": "2026-09-05T16:11:22.282Z",
    "display_name": "Mom",
    "name": "Mom",
    "participants": ["+14155551212"],
    "last_addressed_handle": "mom@icloud.com",
}


class TestParseChats:
    def test_newline_delimited_objects(self):
        out = "\n".join(
            [
                '{"id":1,"identifier":"+14155551212"}',
                '{"id":2,"identifier":"+18136960541"}',
            ]
        )
        assert find_chat.parse_chats(out) == [
            {"id": 1, "identifier": "+14155551212"},
            {"id": 2, "identifier": "+18136960541"},
        ]

    def test_ignores_blank_and_non_json_lines(self):
        out = '{"id":1}\n\nsome log noise\n{"id":2}\n'
        assert find_chat.parse_chats(out) == [{"id": 1}, {"id": 2}]

    def test_ignores_non_dict_json(self):
        assert find_chat.parse_chats('["not","a","chat"]\n{"id":1}\n') == [{"id": 1}]


class TestMatches:
    def test_matches_display_name_case_insensitive(self):
        assert find_chat.matches(_CHAT, "mom")
        assert find_chat.matches(_CHAT, "MOM")

    def test_matches_identifier(self):
        assert find_chat.matches(_CHAT, "+14155551212")

    def test_matches_guid(self):
        assert find_chat.matches(_CHAT, "imessage;-;+1415")

    def test_matches_participant(self):
        chat = {**_CHAT, "display_name": "", "name": ""}
        assert find_chat.matches(chat, "+14155551212")

    def test_matches_last_addressed_handle(self):
        chat = {**_CHAT, "display_name": "", "name": ""}
        assert find_chat.matches(chat, "mom@icloud.com")

    def test_no_match(self):
        assert not find_chat.matches(_CHAT, "zzz-not-present")

    def test_empty_query_matches_all(self):
        assert find_chat.matches(_CHAT, "")
        assert find_chat.matches(_CHAT, "   ")


class TestFormatChat:
    def test_summary_contains_id_name_service(self):
        line = find_chat.format_chat(_CHAT)
        assert "id=1" in line
        assert "Mom" in line
        assert "[iMessage]" in line
        assert "+14155551212" in line

    def test_missing_name_uses_placeholder(self):
        line = find_chat.format_chat({**_CHAT, "name": "", "display_name": ""})
        assert "(no name)" in line


class TestMain:
    def test_filters_and_prints(self, capsys):
        chats = [
            _CHAT,
            {
                **_CHAT,
                "id": 2,
                "display_name": "",
                "name": "",
                "identifier": "+19998887777",
                "last_addressed_handle": "+19998887777",
                "participants": ["+19998887777"],
            },
        ]
        with mock.patch.object(find_chat, "run_chats", return_value=chats):
            assert find_chat.main(["Mom"]) == 0
        out = capsys.readouterr().out
        assert "id=1" in out
        assert "id=2" not in out

    def test_no_match_exits_nonzero(self, capsys):
        with mock.patch.object(find_chat, "run_chats", return_value=[_CHAT]):
            assert find_chat.main(["nobody"]) == 1
        assert "No chats match" in capsys.readouterr().out

    def test_json_flag_emits_array(self, capsys):
        import json

        with mock.patch.object(find_chat, "run_chats", return_value=[_CHAT]):
            assert find_chat.main(["Mom", "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == [_CHAT]
