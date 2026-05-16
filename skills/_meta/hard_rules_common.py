#!/usr/bin/env python3
"""hard_rules_common.py — Canonical identity & text for hard-rule directives.

Single source of truth for:

  - `canonical_project_id()`  — resolved absolute path of the project root
    that contains CLAUDE.md (or .claude/CLAUDE.md). The ONE identifier used
    in the suppression file and the scanner's '[project:...]' label.
  - `canonical_directive_text()` — strips source labels, bullet markers,
    markdown emphasis, HTML comments; collapses whitespace; lowercases.
    Used for duplicate-detection AND hashing.
  - `directive_hash()` — sha256-hex of the canonical text.

Used by `scan_hard_rules.py` and `apply_project_hard_rules.py` to prevent
the bypass classes flagged by Codex review (#4 path ambiguity, #9 inline
normalization drift).

Stdlib only.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Source label produced by the scanner: "[global]" or "[project:<abs path>]".
_SOURCE_LABEL_RE = re.compile(r"^\s*\[(?:global|project:[^\]]*)\]\s*")

# Bullet markers and ordered-list markers at the start of a line.
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")

# HTML comments: <!-- ... -->
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Markdown emphasis we want to neutralise: *x*, **x**, _x_, `x`, ~~x~~.
# Strip only the delimiters; keep the content. We do this token-by-token.
_EMPHASIS_RE = re.compile(r"(\*\*|\*|__|_|`+|~~)")

# Final whitespace collapse.
_WS_RE = re.compile(r"\s+")


def canonical_project_id(start: Path | None = None) -> str:
    """Resolve project root (directory containing CLAUDE.md or .claude/CLAUDE.md).

    Returns the resolved absolute path as a str. Pinning this prevents
    path / symlink / CLAUDE.md-vs-root ambiguity (Codex #4).

    Search order, starting from `start` (default: cwd), walking up:
      1. <dir>/CLAUDE.md
      2. <dir>/.claude/CLAUDE.md

    If nothing is found anywhere up to the filesystem root, returns the
    resolved absolute path of `start`. Callers that need a present-CLAUDE.md
    invariant should check separately; canonical_project_id() is just an
    identifier.
    """
    base = (start if start is not None else Path.cwd()).resolve()
    current = base
    while True:
        if (current / "CLAUDE.md").is_file():
            return str(current)
        if (current / ".claude" / "CLAUDE.md").is_file():
            return str(current)
        if current.parent == current:
            # Hit filesystem root with no match — fall back to start.
            return str(base)
        current = current.parent


def canonical_directive_text(raw: str) -> str:
    """Strip source labels, bullet markers, markdown emphasis, HTML comments,
    then collapse internal whitespace and lowercase. Returns canonical form.

    ONE function — scanner, helper, and tests all import this (Codex #9).
    Never inline an ad-hoc equivalent.
    """
    if not raw:
        return ""
    s = raw

    # 1. Strip source label prefix if present.
    s = _SOURCE_LABEL_RE.sub("", s)

    # 2. Strip bullet/list markers (once, at line start after label strip).
    s = _BULLET_RE.sub("", s)

    # 3. Remove HTML comments entirely.
    s = _HTML_COMMENT_RE.sub("", s)

    # 4. Neutralise markdown emphasis delimiters (keep inner text).
    s = _EMPHASIS_RE.sub("", s)

    # 5. Collapse whitespace and lowercase.
    s = _WS_RE.sub(" ", s).strip().lower()

    return s


def directive_hash(raw: str) -> str:
    """sha256-hex of canonical_directive_text(raw)."""
    canon = canonical_directive_text(raw)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def display_directive_text(raw: str) -> str:
    """Strip source labels, bullet markers, markdown emphasis, HTML
    comments — same set of strippers as canonical_directive_text — but
    preserve casing and collapse whitespace only (no lowercasing).

    Used by the scanner to emit clean `--rule` values in the proposed
    apply/suppress commands and in the preview bullets. The directive
    written into project CLAUDE.md ends up as `- <display_directive_text>`.
    """
    if not raw:
        return ""
    s = raw
    s = _SOURCE_LABEL_RE.sub("", s)
    s = _BULLET_RE.sub("", s)
    s = _HTML_COMMENT_RE.sub("", s)
    s = _EMPHASIS_RE.sub("", s)
    s = _WS_RE.sub(" ", s).strip()
    return s
