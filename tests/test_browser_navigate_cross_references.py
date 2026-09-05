"""Tests for the browser_navigate cross-reference stripping in get_tool_definitions.

The static browser_navigate description names web_search / web_extract /
terminal. When any of those tools are absent from an agent's toolset, the
description must stop naming them or the model hallucinates calls to tools it
does not have. Exercises the pure helper against the real shipped schema
description so the assertions track the actual contract rather than a copy.
"""

from __future__ import annotations

import model_tools
from tools.browser_tool import BROWSER_TOOL_SCHEMAS

_NAV_DESC = next(
    s["description"] for s in BROWSER_TOOL_SCHEMAS if s["name"] == "browser_navigate"
)


def _strip(*available: str) -> str:
    return model_tools._strip_browser_navigate_cross_references(
        _NAV_DESC, set(available)
    )


def test_all_available_unchanged():
    assert _strip("web_search", "web_extract", "terminal") == _NAV_DESC


def test_none_available_names_nothing():
    desc = _strip()
    assert "web_search" not in desc
    assert "web_extract" not in desc
    assert "terminal tool" not in desc


def test_web_search_only_drops_web_extract():
    desc = _strip("web_search")
    assert "web_search" in desc
    assert "web_extract" not in desc


def test_web_extract_only_drops_web_search_and_terminal():
    desc = _strip("web_extract")
    assert "web_extract" in desc
    assert "web_search" not in desc
    assert "terminal tool" not in desc


def test_terminal_only_drops_web_tools():
    desc = _strip("terminal")
    assert "curl via the terminal tool" in desc
    assert "web_search" not in desc
    assert "web_extract" not in desc


def test_web_search_and_extract_drops_terminal():
    desc = _strip("web_search", "web_extract")
    assert "web_search" in desc
    assert "web_extract" in desc
    assert "terminal tool" not in desc
