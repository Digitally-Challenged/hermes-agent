#!/usr/bin/env python3
"""
wiki_lint.py — Comprehensive health check for a Hermes LLM Wiki directory.

Performs 13 validation checks across a markdown wiki structured as:
  SCHEMA.md, index.md, log.md
  entities/   concepts/   comparisons/   queries/
  raw/ (articles/, papers/, transcripts/, assets/)
  _archive/

Usage:
  wiki_lint.py [WIKI_DIR]           # default: ~/wiki or $WIKI_PATH
  wiki_lint.py --json               # machine-readable JSON output
  wiki_lint.py --summary-only       # stats only, no issue details

Exit code 0 if no critical issues, 1 otherwise.

Requirements: Python 3.9+, stdlib only (no pip dependencies).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Constants ────────────────────────────────────────────────────────────────

# Canonical four, used when SCHEMA.md declares no page types.
DEFAULT_PAGE_DIRS = frozenset({"entities", "concepts", "comparisons", "queries"})
# Mutable: replaced at run time by whatever SCHEMA.md declares under
# "## Page Types". Domains legitimately need more than the canonical four —
# this competitive-intel wiki adds products/, models/, regulations/, timelines/.
WIKI_PAGE_DIRS: Set[str] = set(DEFAULT_PAGE_DIRS)
RAW_SUBDIRS = frozenset({"articles", "papers", "transcripts", "assets"})
STALE_DAYS = 90
PAGE_MAX_LINES = 200
LOG_MAX_ENTRIES = 500

WIKI_REQUIRED_FIELDS = frozenset({"title", "created", "updated", "type", "tags", "sources"})
RAW_REQUIRED_FIELDS = frozenset({"source_url", "ingested", "sha256"})

SEVERITY_ORDER: Dict[str, int] = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
SEVERITY_SORT_KEY = lambda s: SEVERITY_ORDER.get(s, 99)


# ── Frontmatter parser ──────────────────────────────────────────────────────

_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_LIST_VALUE_PATTERN = re.compile(r"^\[([^\]]*)\]$")
# Matches scalar values: key: value, key: "value", key: 'value'
_SCALAR_PATTERN = re.compile(
    r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(?:"([^"]*)"|\'([^\']*)\'|(.+?))?\s*$'
)


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter (--- delimited block) from markdown text.

    Returns (frontmatter_dict, body_text).
    Handles: simple scalars (str, int, float, bool), inline lists [a, b, c],
    and multi-line lists (key on one line, `- items` on subsequent lines).
    Does NOT handle full YAML — just the subset used in wiki pages.
    """
    m = _FM_PATTERN.match(text)
    if not m:
        return {}, text

    fm_block = m.group(1)
    body = text[m.end() :]

    result: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    current_list: List[str] = []

    def _flush_list():
        nonlocal current_list_key, current_list
        if current_list_key is not None and current_list:
            result[current_list_key] = current_list
            current_list = []
            current_list_key = None

    for line in fm_block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List-item continuation: "  - value" or "- value" under a key
        list_item_match = re.match(r"^\s*-\s+(.+)$", stripped)
        if list_item_match:
            item_val = _parse_scalar(list_item_match.group(1))
            current_list.append(item_val)
            continue

        # Starting a new key — flush any in-progress list
        _flush_list()

        scalar_match = _SCALAR_PATTERN.match(stripped)
        if not scalar_match:
            continue

        key = scalar_match.group(1)
        raw_value = scalar_match.group(2) or scalar_match.group(3) or scalar_match.group(4)

        # If no value (just "key:"), this might start a multi-line list
        if raw_value is None or raw_value == "":
            current_list_key = key
            current_list = []
            continue

        # Check for inline list [a, b, c]
        raw_value = raw_value.strip()
        list_match = _LIST_VALUE_PATTERN.match(raw_value)
        if list_match:
            items = [item.strip().strip("'\"") for item in list_match.group(1).split(",")]
            result[key] = [i for i in items if i]
            continue

        # Scalar value
        result[key] = _coerce_scalar(raw_value) if raw_value else raw_value

    _flush_list()
    return result, body


def _parse_scalar(raw: str) -> str:
    """Strip surrounding quotes and whitespace from a scalar value."""
    val = raw.strip()
    if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
        val = val[1:-1]
    return val


def _coerce_scalar(val: str) -> Any:
    """Coerce a YAML scalar string to the appropriate Python type."""
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if val.lower() in ("null", "none", "~"):
        return None
    # Try int, then float
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


# ── Wikilink extraction ─────────────────────────────────────────────────────

_WIKILINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]")


def extract_wikilinks(text: str) -> List[str]:
    """Extract [[target]] links from markdown text.

    Returns list of link targets (the name before any | alias or # anchor).
    Handles: [[Page]], [[Page|alias]], [[Page#section]], [[Page#section|alias]].
    """
    return [m.group(1).strip() for m in _WIKILINK_PATTERN.finditer(text)]


# ── Taxonomy loading ────────────────────────────────────────────────────────

_TAXONOMY_HEADING = re.compile(r"^#{1,6}[ \t]*Tag Taxonomy[ \t]*$", re.IGNORECASE | re.MULTILINE)
_ANY_HEADING = re.compile(r"^#{1,6}[ \t]+\S", re.MULTILINE)
_BACKTICK_TOKEN = re.compile(r"`([A-Za-z0-9][A-Za-z0-9_-]*)`")
_BARE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def load_taxonomy(schema_path: Path) -> Set[str]:
    """Extract the valid tag set declared by SCHEMA.md.

    Resolution order:
      1. The body section headed ``Tag Taxonomy`` — the format the skill's
         SCHEMA.md template actually documents. Collects every backticked
         token (``- `competitor` — ...``) and every comma-separated item
         following a colon (``- Models: model, architecture, benchmark``).
      2. The frontmatter ``tags`` key (compact alternative).

    Returns an EMPTY set when SCHEMA.md is missing or declares no taxonomy.
    Callers must treat empty as "taxonomy unknown" and skip the tag-membership
    check entirely — flagging every tag when the taxonomy is unknown would make
    the check useless noise on day one.
    """
    if not schema_path.is_file():
        return set()

    text = schema_path.read_text(encoding="utf-8")

    # ── 1. Body "Tag Taxonomy" section ──────────────────────────────────
    heading = _TAXONOMY_HEADING.search(text)
    if heading:
        rest = text[heading.end():]
        nxt = _ANY_HEADING.search(rest)
        body = rest[: nxt.start()] if nxt else rest

        tags: Set[str] = set()
        # Backticked tokens anywhere in the section.
        tags.update(_BACKTICK_TOKEN.findall(body))
        # "<Label>: a, b, c" lines.
        for line in body.splitlines():
            line = line.strip()
            if not line[:1] in ("-", "*") or ":" not in line:
                continue
            for part in line.split(":", 1)[1].split(","):
                # Drop trailing prose after an em/en dash or hyphen.
                token = re.split(r"\s+[\u2014\u2013-]\s+", part.strip())[0].strip()
                if _BARE_TAG.match(token):
                    tags.add(token)
        if tags:
            return tags

    # ── 2. Frontmatter fallback ─────────────────────────────────────────
    fm, _ = parse_frontmatter(text)
    tags = fm.get("tags", [])
    if isinstance(tags, list):
        return {str(t) for t in tags}
    return set()


# ── Page-type loading ───────────────────────────────────────────────────────

_PAGE_TYPES_HEADING = re.compile(r"^#{1,6}[ \t]*Page Types[ \t]*$", re.IGNORECASE | re.MULTILINE)
# Matches: - `entities/` → `entity` — prose   (also accepts -> and :)
_PAGE_TYPE_ROW = re.compile(
    r"^[-*]\s+`([a-z0-9][a-z0-9_-]*)/?`\s*(?:\u2192|->|:)\s*`?([a-z][a-z0-9_-]*)`?",
    re.IGNORECASE | re.MULTILINE,
)


def load_page_types(schema_path: Optional[Path]) -> Tuple[Set[str], Dict[str, str]]:
    """Parse the ``## Page Types`` table declared by SCHEMA.md.

    Returns ``(directories, {directory: declared_type})``. Falls back to
    ``DEFAULT_PAGE_DIRS`` with an empty mapping when SCHEMA.md is absent or
    declares no page types — in that case directory/type consistency simply
    isn't checked, rather than being checked against the wrong model.
    """
    if schema_path is None or not schema_path.is_file():
        return set(DEFAULT_PAGE_DIRS), {}

    text = schema_path.read_text(encoding="utf-8")
    heading = _PAGE_TYPES_HEADING.search(text)
    if not heading:
        return set(DEFAULT_PAGE_DIRS), {}

    rest = text[heading.end():]
    nxt = _ANY_HEADING.search(rest)
    body = rest[: nxt.start()] if nxt else rest

    dirs: Set[str] = set()
    types: Dict[str, str] = {}
    for m in _PAGE_TYPE_ROW.finditer(body):
        directory = m.group(1).lower()
        declared = m.group(2).lower()
        dirs.add(directory)
        types[directory] = declared

    if not dirs:
        return set(DEFAULT_PAGE_DIRS), {}
    return dirs, types


# ── File discovery ──────────────────────────────────────────────────────────

def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in (".md", ".markdown")


def discover_wiki(base: Path) -> Tuple[
    Dict[str, Dict[str, Any]],  # wiki pages: rel_path -> metadata
    Dict[str, Dict[str, Any]],  # raw files: rel_path -> metadata
    Optional[Path],             # index.md path
    Optional[Path],             # log.md path
    Optional[Path],             # SCHEMA.md path
]:
    """Walk a wiki directory and collect all pages.

    Returns:
      wiki_pages: {relative_path: {fm, body, path, links, line_count, type_dir}}
      raw_files:  {relative_path: {fm, body, path, line_count}}
      index_path, log_path, schema_path
    """
    wiki_pages: Dict[str, Dict[str, Any]] = {}
    raw_files: Dict[str, Dict[str, Any]] = {}
    index_path: Optional[Path] = None
    log_path: Optional[Path] = None
    schema_path: Optional[Path] = None

    # Root-level special files
    for name in ("SCHEMA.md", "index.md", "log.md"):
        candidate = base / name
        if candidate.is_file():
            if name == "SCHEMA.md":
                schema_path = candidate
            elif name == "index.md":
                index_path = candidate
            elif name == "log.md":
                log_path = candidate

    for dirpath_str, dirnames, filenames in os.walk(base):
        dirpath = Path(dirpath_str)
        rel_dir = dirpath.relative_to(base)

        # Skip _archive entirely for linting purposes
        parts = rel_dir.parts
        if parts and parts[0] == "_archive":
            continue

        for fname in filenames:
            if not _is_markdown(Path(fname)):
                continue

            filepath = dirpath / fname
            rel_path = str(filepath.relative_to(base))

            try:
                text = filepath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                # Record unreadable files so they show up as errors
                err_key = rel_path
                if rel_dir.parts and rel_dir.parts[0] in WIKI_PAGE_DIRS:
                    wiki_pages[err_key] = {
                        "fm": {},
                        "body": "",
                        "path": filepath,
                        "links": [],
                        "line_count": 0,
                        "type_dir": rel_dir.parts[0],
                        "read_error": str(exc),
                    }
                continue

            fm, body = parse_frontmatter(text)
            line_count = len(text.splitlines())
            links = extract_wikilinks(text)

            # Determine category
            if rel_dir.parts and rel_dir.parts[0] in WIKI_PAGE_DIRS:
                wiki_pages[rel_path] = {
                    "fm": fm,
                    "body": body,
                    "path": filepath,
                    "links": links,
                    "line_count": line_count,
                    "type_dir": rel_dir.parts[0],
                }
            elif rel_dir.parts and rel_dir.parts[0] == "raw":
                # Only raw subdirectories or root raw/ level for .md files
                raw_files[rel_path] = {
                    "fm": fm,
                    "body": body,
                    "path": filepath,
                    "line_count": line_count,
                }
            # Root-level .md files (index, log, schema, others) are ignored
            # for wiki page tracking but may be checked separately.

    return wiki_pages, raw_files, index_path, log_path, schema_path


# ── Individual checks ───────────────────────────────────────────────────────

def _wiki_page_name(rel_path: str) -> str:
    """Derive a page name from its path: strip dir prefix and .md."""
    # e.g. entities/MyTopic.md -> MyTopic
    name = os.path.splitext(Path(rel_path).name)[0]
    return name


def _make_issue(severity: str, check: str, message: str, path: str = "") -> Dict[str, str]:
    return {"severity": severity, "check": check, "message": message, "path": path}


def check_orphans(wiki_pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Check 1: Pages with zero inbound [[wikilinks]]."""
    issues: List[Dict[str, str]] = []
    # Build reverse index: target_name -> set of referring page paths
    incoming: Dict[str, Set[str]] = defaultdict(set)
    for rel, meta in wiki_pages.items():
        for link in meta["links"]:
            incoming[link].add(rel)

    for rel, meta in wiki_pages.items():
        page_name = _wiki_page_name(rel)
        if not incoming.get(page_name):
            issues.append(
                _make_issue(
                    "INFO",
                    "orphan-pages",
                    f"Orphan page (no inbound links): {page_name}",
                    rel,
                )
            )
    return issues


def check_broken_wikilinks(wiki_pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Check 2: [[links]] that don't resolve to any wiki page."""
    issues: List[Dict[str, str]] = []
    all_names = {_wiki_page_name(p) for p in wiki_pages}

    for rel, meta in wiki_pages.items():
        for link in meta["links"]:
            if link not in all_names:
                issues.append(
                    _make_issue(
                        "CRITICAL",
                        "broken-wikilinks",
                        f"Broken wikilink: [[{link}]] in {_wiki_page_name(rel)}",
                        rel,
                    )
                )
    return issues


def check_index_completeness(
    wiki_pages: Dict[str, Dict[str, Any]], index_path: Optional[Path]
) -> List[Dict[str, str]]:
    """Check 3: Every wiki page should appear in index.md."""
    issues: List[Dict[str, str]] = []
    if not index_path:
        issues.append(
            _make_issue("CRITICAL", "index-completeness", "index.md not found at wiki root")
        )
        return issues

    index_text = index_path.read_text(encoding="utf-8")
    for rel, meta in wiki_pages.items():
        page_name = _wiki_page_name(rel)
        # Check if page name or relative path appears in index
        if page_name not in index_text and rel not in index_text:
            issues.append(
                _make_issue(
                    "WARNING",
                    "index-completeness",
                    f"Page not listed in index.md: {page_name}",
                    rel,
                )
            )
    return issues


def check_frontmatter(
    wiki_pages: Dict[str, Dict[str, Any]],
    raw_files: Dict[str, Dict[str, Any]],
    taxonomy: Set[str],
    page_types: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """Check 4: Required frontmatter fields, tags in taxonomy, dir/type agreement."""
    issues: List[Dict[str, str]] = []
    page_types = page_types or {}

    for rel, meta in wiki_pages.items():
        fm = meta.get("fm", {})
        read_err = meta.get("read_error")
        if read_err:
            issues.append(
                _make_issue("CRITICAL", "frontmatter", f"Cannot read file: {read_err}", rel)
            )
            continue

        # Required fields
        for field in WIKI_REQUIRED_FIELDS:
            if field not in fm:
                issues.append(
                    _make_issue(
                        "CRITICAL",
                        "frontmatter",
                        f"Missing required field '{field}'",
                        rel,
                    )
                )

        # Tags validation
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if taxonomy and isinstance(tags, list):
            for tag in tags:
                if str(tag) not in taxonomy:
                    issues.append(
                        _make_issue(
                            "WARNING",
                            "frontmatter",
                            f"Tag '{tag}' not in taxonomy",
                            rel,
                        )
                    )

        # Directory / type agreement (only when SCHEMA.md declares page types)
        type_dir = meta.get("type_dir", "")
        declared = page_types.get(type_dir)
        actual = str(fm.get("type", "")).strip().lower()
        if declared and actual and actual != declared:
            issues.append(
                _make_issue(
                    "WARNING",
                    "page-types",
                    f"type '{actual}' does not match {type_dir}/ (declared '{declared}')",
                    rel,
                )
            )

    # Raw file frontmatter
    for rel, meta in raw_files.items():
        fm = meta.get("fm", {})
        for field in RAW_REQUIRED_FIELDS:
            if field not in fm:
                issues.append(
                    _make_issue(
                        "CRITICAL",
                        "frontmatter",
                        f"Missing required field '{field}' in raw source",
                        rel,
                    )
                )

    return issues


def check_stale(wiki_pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Check 5: Pages with 'updated' date > 90 days old."""
    issues: List[Dict[str, str]] = []
    now = datetime.now(timezone.utc)

    for rel, meta in wiki_pages.items():
        updated_str = meta.get("fm", {}).get("updated", "")
        if not updated_str:
            continue
        try:
            # Try ISO-format dates: 2024-01-15 or 2024-01-15T10:30:00Z etc.
            dt = _parse_date(str(updated_str))
            if dt is None:
                issues.append(
                    _make_issue(
                        "WARNING",
                        "stale-content",
                        f"Unparseable 'updated' date: '{updated_str}'",
                        rel,
                    )
                )
                continue
            age_days = (now - dt).days
            if age_days > STALE_DAYS:
                issues.append(
                    _make_issue(
                        "INFO",
                        "stale-content",
                        f"Stale content (last updated {age_days} days ago)",
                        rel,
                    )
                )
        except (ValueError, OverflowError):
            issues.append(
                _make_issue(
                    "WARNING",
                    "stale-content",
                    f"Invalid 'updated' date: '{updated_str}'",
                    rel,
                )
            )
    return issues


def _parse_date(s: str) -> Optional[datetime]:
    """Parse an ISO-ish date string. Returns UTC datetime or None."""
    s = s.strip()
    # Try full ISO
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    # Just date
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


def check_contradictions(wiki_pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Check 6: Pages with 'contested: true' or 'contradictions:' frontmatter."""
    issues: List[Dict[str, str]] = []
    for rel, meta in wiki_pages.items():
        fm = meta.get("fm", {})
        if fm.get("contested") in (True, "true"):
            issues.append(
                _make_issue(
                    "WARNING",
                    "contradictions",
                    "Page marked as contested",
                    rel,
                )
            )
        if "contradictions" in fm:
            issues.append(
                _make_issue(
                    "WARNING",
                    "contradictions",
                    "Page has recorded contradictions",
                    rel,
                )
            )
    return issues


def check_quality_signals(wiki_pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Check 7: confidence: low + single-source pages with no confidence field."""
    issues: List[Dict[str, str]] = []
    for rel, meta in wiki_pages.items():
        fm = meta.get("fm", {})
        confidence = fm.get("confidence", "")

        if str(confidence).lower() == "low":
            issues.append(
                _make_issue(
                    "WARNING",
                    "quality-signals",
                    "Page has confidence: low",
                    rel,
                )
            )

        # Single-source check: sources is a list with exactly 1 entry
        sources = fm.get("sources", [])
        if isinstance(sources, str):
            sources = [sources]
        if isinstance(sources, list) and len(sources) == 1 and not confidence:
            issues.append(
                _make_issue(
                    "INFO",
                    "quality-signals",
                    "Single-source page with no confidence rating",
                    rel,
                )
            )
    return issues


def check_source_drift(raw_files: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Check 8: Recompute sha256 of raw/ file bodies, flag mismatches."""
    issues: List[Dict[str, str]] = []
    for rel, meta in raw_files.items():
        expected_hash = meta.get("fm", {}).get("sha256", "")
        if not expected_hash:
            continue

        actual_hash = hashlib.sha256(meta["body"].encode("utf-8")).hexdigest()
        if actual_hash != str(expected_hash):
            issues.append(
                _make_issue(
                    "CRITICAL",
                    "source-drift",
                    f"sha256 mismatch: stored={str(expected_hash)[:12]}... "
                    f"computed={actual_hash[:12]}...",
                    rel,
                )
            )
    return issues


def check_page_size(wiki_pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Check 9: Flag pages over 200 lines."""
    issues: List[Dict[str, str]] = []
    for rel, meta in wiki_pages.items():
        lc = meta.get("line_count", 0)
        if lc > PAGE_MAX_LINES:
            issues.append(
                _make_issue(
                    "INFO",
                    "page-size",
                    f"Large page: {lc} lines (limit: {PAGE_MAX_LINES})",
                    rel,
                )
            )
    return issues


def check_tag_audit(
    wiki_pages: Dict[str, Dict[str, Any]], taxonomy: Set[str]
) -> List[Dict[str, str]]:
    """Check 10: Find tags in use that aren't in the taxonomy."""
    if not taxonomy:
        return []

    all_tags: Set[str] = set()
    for rel, meta in wiki_pages.items():
        tags = meta.get("fm", {}).get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if isinstance(tags, list):
            all_tags.update(str(t) for t in tags)

    rogue = all_tags - taxonomy
    issues: List[Dict[str, str]] = []
    for tag in sorted(rogue):
        # Find which pages use this tag
        pages_using = [
            _wiki_page_name(rel)
            for rel, meta in wiki_pages.items()
            if tag in (
                meta.get("fm", {}).get("tags", [])
                if isinstance(meta.get("fm", {}).get("tags", []), list)
                else []
            )
        ]
        issues.append(
            _make_issue(
                "WARNING",
                "tag-audit",
                f"Undefined tag '{tag}' used in: {', '.join(pages_using[:5])}",
                "",
            )
        )
    return issues


def check_log_rotation(log_path: Optional[Path]) -> List[Dict[str, str]]:
    """Check 11: Warn if log.md exceeds 500 entries."""
    issues: List[Dict[str, str]] = []
    if not log_path:
        return issues

    try:
        text = log_path.read_text(encoding="utf-8")
        # Count log entries — each entry typically starts with "## " or "- **date**"
        # Use a heuristic: count Markdown headings or date-prefixed lines
        entry_count = len(re.findall(r"^##\s", text, re.MULTILINE))
        # Also count bullet-based log entries
        bullet_entries = len(re.findall(r"^-\s+\*\*\d{4}-\d{2}-\d{2}\*\*", text, re.MULTILINE))
        total = max(entry_count, bullet_entries)
        if total > LOG_MAX_ENTRIES:
            issues.append(
                _make_issue(
                    "WARNING",
                    "log-rotation",
                    f"log.md has ~{total} entries (limit: {LOG_MAX_ENTRIES})",
                    "log.md",
                )
            )
    except (OSError, UnicodeDecodeError):
        pass

    return issues


# ── Summary stats ───────────────────────────────────────────────────────────

def compute_stats(
    wiki_pages: Dict[str, Dict[str, Any]], raw_files: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Compute summary statistics (Check 13)."""
    total = len(wiki_pages)
    by_type: Dict[str, int] = defaultdict(int)
    total_links = 0
    total_lines = 0

    for rel, meta in wiki_pages.items():
        by_type[meta.get("type_dir", "unknown")] += 1
        total_links += len(meta.get("links", []))
        total_lines += meta.get("line_count", 0)

    avg_links = round(total_links / total, 1) if total > 0 else 0
    avg_lines = round(total_lines / total, 1) if total > 0 else 0

    return {
        "total_wiki_pages": total,
        "total_raw_files": len(raw_files),
        "pages_by_type": dict(by_type),
        "avg_wikilinks_per_page": avg_links,
        "avg_lines_per_page": avg_lines,
    }


# ── Main lint runner ────────────────────────────────────────────────────────


def lint_wiki(wiki_dir: Path) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Run all checks and return (issues, stats)."""
    if not wiki_dir.is_dir():
        print(f"Error: {wiki_dir} is not a directory or doesn't exist.", file=sys.stderr)
        sys.exit(2)

    # The page-type model comes from SCHEMA.md and must be resolved BEFORE
    # discovery, which classifies each file by its top-level directory.
    global WIKI_PAGE_DIRS
    page_dirs, page_types = load_page_types(wiki_dir / "SCHEMA.md")
    WIKI_PAGE_DIRS = set(page_dirs)

    # Discover
    wiki_pages, raw_files, index_path, log_path, schema_path = discover_wiki(wiki_dir)
    taxonomy = load_taxonomy(schema_path) if schema_path else set()

    # Run all checks
    all_issues: List[Dict[str, str]] = []
    all_issues.extend(check_orphans(wiki_pages))
    all_issues.extend(check_broken_wikilinks(wiki_pages))
    all_issues.extend(check_index_completeness(wiki_pages, index_path))
    all_issues.extend(check_frontmatter(wiki_pages, raw_files, taxonomy, page_types))
    all_issues.extend(check_stale(wiki_pages))
    all_issues.extend(check_contradictions(wiki_pages))
    all_issues.extend(check_quality_signals(wiki_pages))
    all_issues.extend(check_source_drift(raw_files))
    all_issues.extend(check_page_size(wiki_pages))
    all_issues.extend(check_tag_audit(wiki_pages, taxonomy))
    all_issues.extend(check_log_rotation(log_path))

    stats = compute_stats(wiki_pages, raw_files)
    return all_issues, stats


# ── Output formatters ───────────────────────────────────────────────────────


def format_terminal(issues: List[Dict[str, str]], stats: Dict[str, Any]) -> str:
    """Format results for human-readable terminal output."""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("  Wiki Lint Report")
    lines.append("=" * 60)
    lines.append("")

    # Group by severity
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for issue in issues:
        grouped[issue["severity"]].append(issue)

    for severity in ("CRITICAL", "WARNING", "INFO"):
        group = grouped.get(severity, [])
        if not group:
            continue

        icon = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(severity, "⚪")
        lines.append(f"{icon} {severity} ({len(group)} issues)")
        lines.append("-" * 40)

        # Sort within severity by check name then path
        group.sort(key=lambda i: (i["check"], i["path"]))

        for issue in group:
            path_label = f" [{issue['path']}]" if issue["path"] else ""
            lines.append(f"  [{issue['check']}]{path_label} {issue['message']}")

        lines.append("")

    # Summary stats
    lines.append("-" * 60)
    lines.append("📊 Summary Statistics")
    lines.append("-" * 60)
    lines.append(f"  Total wiki pages:    {stats['total_wiki_pages']}")
    lines.append(f"  Total raw files:     {stats['total_raw_files']}")
    lines.append(f"  Pages by type:       {stats['pages_by_type']}")
    lines.append(f"  Avg wikilinks/page:  {stats['avg_wikilinks_per_page']}")
    lines.append(f"  Avg lines/page:      {stats['avg_lines_per_page']}")
    lines.append("")

    # Totals
    critical_count = len(grouped.get("CRITICAL", []))
    warning_count = len(grouped.get("WARNING", []))
    info_count = len(grouped.get("INFO", []))
    lines.append("=" * 60)
    lines.append(
        f"  Total: {critical_count} critical, {warning_count} warnings, "
        f"{info_count} info  ({len(issues)} issues)"
    )
    lines.append("=" * 60)

    return "\n".join(lines)


def format_json(issues: List[Dict[str, str]], stats: Dict[str, Any]) -> str:
    """Format results as JSON."""
    return json.dumps({"issues": issues, "stats": stats}, indent=2, sort_keys=True)


def format_summary(stats: Dict[str, Any]) -> str:
    """Quick overview: just the summary stats."""
    lines: List[str] = []
    lines.append("Wiki Lint Summary")
    lines.append("=" * 40)
    lines.append(f"  Wiki pages:   {stats['total_wiki_pages']}")
    lines.append(f"  Raw files:    {stats['total_raw_files']}")
    lines.append(f"  By type:      {stats['pages_by_type']}")
    lines.append(f"  Avg links:    {stats['avg_wikilinks_per_page']}")
    lines.append(f"  Avg lines:    {stats['avg_lines_per_page']}")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="wiki_lint.py — Health check for a Hermes LLM Wiki directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "wiki_dir",
        nargs="?",
        default=None,
        help="Path to wiki directory (default: $WIKI_PATH or ~/wiki)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (machine-readable)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only print summary statistics, no issue details",
    )
    args = parser.parse_args()

    # Determine wiki directory
    if args.wiki_dir:
        wiki_path = Path(args.wiki_dir)
    else:
        env_path = os.environ.get("WIKI_PATH")
        if env_path:
            wiki_path = Path(env_path)
        else:
            wiki_path = Path.home() / "wiki"

    wiki_path = wiki_path.expanduser().resolve()

    # Run lint
    issues, stats = lint_wiki(wiki_path)

    # Output
    if args.summary_only:
        print(format_summary(stats))
    elif args.json:
        print(format_json(issues, stats))
    else:
        print(format_terminal(issues, stats))

    # Exit code
    has_critical = any(i["severity"] == "CRITICAL" for i in issues)
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()