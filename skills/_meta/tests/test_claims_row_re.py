"""S030-quickwins #34 — _ROW_RE accepts dotted WP IDs.

Discovered in the DLP pilot (2026-04-09) where `claims.issue_claim("WP-2.A", ...)`
failed because the previous `[A-Za-z0-9_-]+` regex rejected the dot. The fix
extends the WP and component cell character class to include `.` so dotted IDs
like "WP-2.A" and "WP-3.foo.bar" parse cleanly.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Resolve _meta/claims.py from either production or shadow checkout.
_HERE = Path(__file__).resolve()
_META = _HERE.parent.parent
sys.path.insert(0, str(_META))

import claims  # noqa: E402


def _row(line: str):
    return claims._ROW_RE.match(line)


def test_row_re_accepts_dotted_wp_id() -> None:
    """Rows with dotted WP IDs (e.g. WP-2.A, WP-3.foo.bar) match cleanly."""
    line_a = "| WP-2.A | auth-svc | PLANNED | 0 | — |"
    m = _row(line_a)
    assert m is not None, "WP-2.A row should match"
    assert m.group("wp") == "WP-2.A"
    assert m.group("component") == "auth-svc"
    assert m.group("stage") == "PLANNED"
    assert m.group("gen") == "0"

    line_b = "| WP-3.foo.bar | a.b.c | INTEGRATED | 5 | WP-1, WP-2 |"
    m = _row(line_b)
    assert m is not None, "WP-3.foo.bar row should match"
    assert m.group("wp") == "WP-3.foo.bar"
    assert m.group("component") == "a.b.c"

    line_c = "| WP-1 | x | UNIT_TESTED | 2 | — |"
    m = _row(line_c)
    assert m is not None, "Plain WP-1 still matches"
    assert m.group("wp") == "WP-1"


def test_row_re_still_rejects_invalid() -> None:
    """Rows with invalid WP/component characters do NOT match."""
    # Whitespace inside WP id
    assert _row("| WP 2 | comp | PLANNED | 0 | — |") is None
    # Special character
    assert _row("| WP-2! | comp | PLANNED | 0 | — |") is None
    # Empty WP cell -> the `+` quantifier requires at least one char.
    assert _row("|  | comp | PLANNED | 0 | — |") is None
    # Header / separator rows do not match the data shape (no integer gen).
    assert _row("|------|------|------|------|------|") is None
