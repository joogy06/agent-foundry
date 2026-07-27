"""S030-quickwins #34 — _ROW_RE accepts dotted WP IDs.

Discovered in the DLP pilot (2026-04-09) where `claims.issue_claim("WP-2.A", ...)`
failed because the previous `[A-Za-z0-9_-]+` regex rejected the dot. The fix
extends the WP and component cell character class to include `.` so dotted IDs
like "WP-2.A" and "WP-3.foo.bar" parse cleanly.

S070 #142 (design §A1.1) — BOTH ledger parsers accept hyphenated stages.
------------------------------------------------------------------------
The UI lane's canonical stage names are hyphenated (`UI-INTEGRATED`,
`UI-VERIFIED`), and both parsers restricted the stage token to `[A-Z_]+`.
Writing is mere formatting, so the engine happily WROTE a UI row; reading it
back is where it broke, and it did not break cleanly:

  * projection (`_ROW_RE.match`)      -> no match; the row SILENTLY VANISHES
    from the projection, after which every transition for that component
    returns `unknown_wp`.
  * transition log (`_EVENT_ROW_RE`)  -> no match on the full row, so
    `_parse_event_rows` silently DROPS the event, corrupting both the `#`
    sequence (`next_num` recomputes from a short list) and replay. In
    isolation the from->to sub-pattern is worse still: it matches a SUBSTRING
    and yields the wrong-but-plausible `{'from': 'INTEGRATED', 'to': 'UI'}` —
    a transition into a nonexistent stage called `UI`.

That is silent ledger corruption reporting success, which is strictly worse
than a parse error — hence the blocking status. Both stage tokens are now
`[A-Z_-]+`, and the tests below pin the round-trip, the spaceless-arrow form
(which resolves only via backtracking), and the byte-identical behaviour of
the seven core stages.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Resolve _meta/claims.py from either production or shadow checkout.
_HERE = Path(__file__).resolve()
_META = _HERE.parent.parent
sys.path.insert(0, str(_META))

import claims  # noqa: E402

CORE_STAGES = (
    "PLANNED", "SCAFFOLDED", "UNIT_TESTED", "INTEGRATED",
    "VERIFIED", "DOCUMENTED", "BLOCKED",
)
UI_STAGES = ("UI-INTEGRATED", "UI-VERIFIED")


def _row(line: str):
    return claims._ROW_RE.match(line)


def _event(line: str):
    return claims._EVENT_ROW_RE.match(line)


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


# ---------------------------------------------------------------------------
# S070 #142 / design §A1.1 — hyphenated UI-lane stages
# ---------------------------------------------------------------------------


def test_row_re_accepts_ui_lane_stages() -> None:
    """Projection rows for the hyphenated UI stages parse (they did not before).

    This is the row that used to vanish silently, taking the whole component
    out of the projection with it.
    """
    for stage in UI_STAGES:
        line = f"| WP-7 | screen-a | {stage} | 0 | WP-1 |"
        m = _row(line)
        assert m is not None, f"{stage} projection row must match"
        assert m.group("wp") == "WP-7"
        assert m.group("component") == "screen-a"
        assert m.group("stage") == stage, (
            f"stage must parse back verbatim, got {m.group('stage')!r}"
        )
        assert m.group("gen") == "0"


def test_row_re_core_stages_parse_byte_identically() -> None:
    """Regression: widening the stage class must not perturb the core lane.

    Asserts the FULL groupdict, so a change to any captured cell (not just
    `stage`) fails here.
    """
    for stage in CORE_STAGES:
        m = _row(f"| WP-1 | comp-a | {stage} | 3 | WP-0 |")
        assert m is not None, f"core stage {stage} must still match"
        assert m.groupdict() == {
            "wp": "WP-1", "component": "comp-a", "stage": stage,
            "gen": "3", "deps": "WP-0 ",
        }, f"core stage {stage} parsed differently after the widening"


def test_row_re_separator_row_still_rejected_after_widening() -> None:
    """The one case that LOOKS endangered by allowing hyphens in `stage`.

    Once hyphens are legal in the stage cell, `------` DOES match the `stage`
    group — the row is still rejected overall only because `gen` requires
    `\\d+`. Pinned explicitly because nothing else in this file constrains
    hyphen-invalidity for stages, so the protection is load-bearing but
    non-obvious.
    """
    assert _row("|------|------|------|------|------|") is None
    # ...and the reason really is the `gen` cell, not the stage cell:
    assert _row("| WP-1 | comp | ------ | 0 | — |") is not None


def test_event_row_re_parses_ui_transition() -> None:
    """The transition-log row for the UI hop parses, both arrow forms.

    The spaceless form resolves only via backtracking (`[A-Z_-]+` is greedy and
    must give back the `-` before `->`), so it is asserted explicitly rather
    than assumed.
    """
    for arrow in ("->", "→"):
        for spacing in (f" {arrow} ", arrow):
            line = (
                f"| 4 | WP-7 | screen-a | UI-INTEGRATED{spacing}UI-VERIFIED "
                f"| 0 | G_V accepted |"
            )
            m = _event(line)
            assert m is not None, f"UI transition row must match (arrow={spacing!r})"
            assert m.group("from") == "UI-INTEGRATED", (
                f"expected from='UI-INTEGRATED', got {m.group('from')!r} "
                f"(arrow={spacing!r}) — the pre-S070 regex produced the "
                f"wrong-but-plausible 'INTEGRATED'/'UI' split here"
            )
            assert m.group("to") == "UI-VERIFIED", (
                f"expected to='UI-VERIFIED', got {m.group('to')!r}"
            )
            assert m.group("num") == "4"


def test_event_row_re_core_transitions_parse_byte_identically() -> None:
    """Regression: core-lane transition rows are unaffected by the widening."""
    for frm, to in (
        ("PLANNED", "SCAFFOLDED"),
        ("SCAFFOLDED", "UNIT_TESTED"),
        ("UNIT_TESTED", "INTEGRATED"),
        ("INTEGRATED", "VERIFIED"),
        ("VERIFIED", "DOCUMENTED"),
        ("BLOCKED", "PLANNED"),
    ):
        m = _event(f"| 1 | WP-1 | comp-a | {frm} -> {to} | 2 | ev |")
        assert m is not None, f"{frm}->{to} must still match"
        assert m.groupdict() == {
            "num": "1", "wp": "WP-1", "component": "comp-a",
            "from": frm, "to": to, "gen": "2", "evidence": "ev",
        }, f"{frm}->{to} parsed differently after the widening"


def test_ledger_round_trip_ui_lane_stages() -> None:
    """§A1.1 round-trip: WRITE a UI row + UI transition with the module's own
    renderers, then READ both back through the production parsers.

    This is the end-to-end form of the bug: the write path never complained,
    so only a round-trip catches it. Uses `_render_projection_table` /
    `_append_event_row` (the real writers) and `read_ledger` /
    `_parse_event_rows` (the real readers) rather than hand-written markdown,
    so a future change to either side is caught here.
    """
    import tempfile

    rows = [
        claims.LedgerRow("WP-1", "core-svc", "VERIFIED", 0, []),
        claims.LedgerRow("WP-7", "screen-a", "UI-INTEGRATED", 0, ["WP-1"]),
    ]
    body = (
        "## Projection\n\n"
        + _render_placeholder()
        + "\n\n## Transition log\n\n"
        "| # | WP | component | from -> to | generation | evidence |\n"
        "|---|----|-----------|-----------|------------|----------|\n"
    )
    body = claims._replace_section_table(
        body, "## Projection", claims._render_projection_table(rows, "->"),
    )
    for event in (
        {"wp": "WP-1", "component": "core-svc",
         "from": "INTEGRATED", "to": "VERIFIED", "generation": 0,
         "evidence": "R6 dual-verdict"},
        {"wp": "WP-7", "component": "screen-a",
         "from": "VERIFIED", "to": "UI-INTEGRATED", "generation": 0,
         "evidence": "flow tests"},
        {"wp": "WP-7", "component": "screen-a",
         "from": "UI-INTEGRATED", "to": "UI-VERIFIED", "generation": 0,
         "evidence": "G_V accepted"},
    ):
        body = claims._append_event_row(body, event, "->")

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "integration-ledger.md"
        path.write_text("---\nschema_version: 1\n---\n\n" + body)

        # --- projection round-trips ---
        ledger = claims.read_ledger(path)
        by_wp = {r.wp: r for r in ledger.rows}
        assert set(by_wp) == {"WP-1", "WP-7"}, (
            f"UI row must survive the round-trip; got {sorted(by_wp)}"
        )
        assert by_wp["WP-7"].stage == "UI-INTEGRATED"
        assert by_wp["WP-7"].component == "screen-a"
        assert by_wp["WP-7"].deps == ["WP-1"]
        assert by_wp["WP-1"].stage == "VERIFIED", "core lane unperturbed"

        # --- transition log round-trips ---
        events = claims._parse_event_rows(path.read_text())
        assert len(events) == 3, (
            f"all three events must parse back; got {len(events)} — a dropped "
            f"row also corrupts `next_num` and replay"
        )
        assert [(e["from"], e["to"]) for e in events] == [
            ("INTEGRATED", "VERIFIED"),
            ("VERIFIED", "UI-INTEGRATED"),
            ("UI-INTEGRATED", "UI-VERIFIED"),
        ]
        # Numbering stayed contiguous — the symptom of a silently dropped row.
        assert [e["num"] for e in events] == [1, 2, 3]


def _render_placeholder() -> str:
    """Empty projection table for `_replace_section_table` to overwrite."""
    return (
        "| WP | component | stage | generation | deps |\n"
        "|----|-----------|-------|------------|------|"
    )
