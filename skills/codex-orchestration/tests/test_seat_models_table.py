#!/usr/bin/env python3
"""The ONE model table (#291 design s3.8): codex-orchestration "Seat Models" must match model_roster.

Every other doc names tiers ("Claude main tier"), so the "Currently (roster rev N)" column of this table is the
single place a reader sees which model serves each tier. This file keeps it honest: the header's revision, the
Claude tier per role and the model in each "Currently" cell are compared with `skills/_meta/model_roster.py`
(the data) and `seat_model.ROLE_TABLE` (which tier each role reads). A roster swap that forgets the table fails
here, exactly like the golden test — the runbook (docs/model-roster-swap.md) edits all three in one commit.

The checker is a pure function of the document text, so the negative controls below plant a wrong cell in an
in-memory copy and prove the test can see it.
"""
import re
import sys
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parents[2]
_META = _SKILLS / "_meta"
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import model_roster  # type: ignore  # noqa: E402
import seat_model  # type: ignore  # noqa: E402

SKILL_MD = _SKILLS / "codex-orchestration" / "SKILL.md"
SECTION = "## Seat Models "
HEADER_RE = re.compile(r"^\| Role \|.*\| Currently \(roster rev (\d+)\) \|")
ROLES = ("code_reviewer", "consultant_main", "consultant_support", "arbiter", "escalation")


def _expected():
    """role -> (tier word, claude model, (codex tier word, codex literal model) or None), derived from the
    DATA, not the resolver. #302: a codex LITERAL row names its own tier - consultant_support reads
    model_roster.CODEX_SUPPORT and is written as codex support, then the slug in backticks; a TOP row names no slug."""
    tier_of_value = {model_roster.CLAUDE_MAIN: "main", model_roster.CLAUDE_SUPPORT: "support"}
    out = {}
    for role in ROLES:
        rows = seat_model.ROLE_TABLE[role]
        claude = rows[seat_model.CLAUDE].value
        codex = rows[seat_model.CODEX]
        literal = None
        if codex.kind == seat_model.KIND_LITERAL:
            literal = ("support", model_roster.CODEX_SUPPORT) if role == "consultant_support" \
                else ("std", model_roster.CODEX_STD)
        out[role] = (tier_of_value[claude], claude, literal)
    return out


def _table(text):
    start = text.index(SECTION)
    body = text[start:]
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if HEADER_RE.match(line):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return int(HEADER_RE.match(line).group(1)), header, rows
    raise AssertionError("no 'Currently (roster rev N)' table in the Seat Models section")


def table_disagreements(text):
    """Every way the Seat Models table disagrees with model_roster; [] when it matches."""
    problems = []
    rev, header, rows = _table(text)
    if rev != model_roster.REVISION:
        problems.append(f"header says roster rev {rev}, model_roster.REVISION is {model_roster.REVISION}")
    tier_col = header.index("Claude tier")
    cur_col = next(i for i, h in enumerate(header) if h.startswith("Currently"))
    seen = {}
    for cells in rows:
        m = re.fullmatch(r"`([a-z_]+)`", cells[0])
        if m:
            seen[m.group(1)] = cells
    expected = _expected()
    for role in ROLES:
        if role not in seen:
            problems.append(f"{role}: no row")
            continue
        tier, claude, literal = expected[role]
        cells = seen[role]
        if cells[tier_col] != tier:
            problems.append(f"{role}: Claude tier {cells[tier_col]!r}, expected {tier!r}")
        current = cells[cur_col]
        got_claude = re.findall(r"claude `([^`]+)`", current)
        if got_claude != [claude]:
            problems.append(f"{role}: Currently names claude {got_claude}, roster says {claude!r}")
        got_codex = re.findall(r"codex (std|support) `([^`]+)`", current)
        if got_codex != ([literal] if literal else []):
            problems.append(f"{role}: Currently names codex {got_codex}, roster says {literal!r}")
    extra = sorted(set(seen) - set(ROLES))
    if extra:
        problems.append(f"rows for unknown roles {extra}")
    problems.extend(_std_note_disagreements(text))
    return problems


STD_NOTE_RE = re.compile(r"^\*\*Codex std tier\*\* — codex std `([^`]+)` \(roster rev (\d+)\)", re.M)


def _std_note_disagreements(text):
    """#302: no table row is a std LITERAL (the sized seats are TOP rows that a size moves onto the std tier), so
    the std model is named once, in the "Codex std tier" note under the table. It must name model_roster.CODEX_STD
    at model_roster.REVISION, exactly once in the Seat Models section."""
    start = text.index(SECTION)
    end = text.find("\n## ", start + 1)
    section = text[start:end if end != -1 else len(text)]
    notes = STD_NOTE_RE.findall(section)
    if len(notes) != 1:
        return [f"std note: expected one 'Codex std tier' note, found {len(notes)}"]
    model, rev = notes[0]
    out = []
    if model != model_roster.CODEX_STD:
        out.append(f"std note: names codex std {model!r}, roster says {model_roster.CODEX_STD!r}")
    if int(rev) != model_roster.REVISION:
        out.append(f"std note: says roster rev {rev}, model_roster.REVISION is {model_roster.REVISION}")
    return out


def test_the_seat_models_table_matches_the_roster():
    assert table_disagreements(SKILL_MD.read_text(encoding="utf-8")) == []


def test_the_table_names_tiers_and_no_benched_family_outside_history():
    """The Claude column is a tier word; no cell of the table names a benched family."""
    _, header, rows = _table(SKILL_MD.read_text(encoding="utf-8"))
    for cells in rows:
        for cell in cells:
            for family in model_roster.CLAUDE_BENCHED:
                assert not re.search(rf"\b{re.escape(family)}\b", cell, re.I), (family, cell)


def _plant(text, old, new):
    start = text.index(SECTION)
    i = text.index(old, start)
    return text[:i] + new + text[i + len(old):]


@pytest.mark.parametrize("old,new,needle", [
    (f"claude `{model_roster.CLAUDE_MAIN}`", "claude `planted-model`", "code_reviewer: Currently names claude"),
    (f"claude `{model_roster.CLAUDE_SUPPORT}`", "claude `planted-model`", "consultant_support: Currently names claude"),
    (f"codex support `{model_roster.CODEX_SUPPORT}`", "codex support `gpt-planted`",
     "consultant_support: Currently names codex"),
    (f"codex support `{model_roster.CODEX_SUPPORT}`", f"codex std `{model_roster.CODEX_SUPPORT}`",
     "consultant_support: Currently names codex"),
    (f"Currently (roster rev {model_roster.REVISION})", f"Currently (roster rev {model_roster.REVISION + 7})",
     "header says roster rev"),
    ("| main | claude", "| support | claude", "code_reviewer: Claude tier"),
    (f"codex std `{model_roster.CODEX_STD}` (roster rev", "codex std `gpt-planted` (roster rev",
     "std note: names codex std"),
    (f"codex std `{model_roster.CODEX_STD}` (roster rev {model_roster.REVISION})",
     f"codex std `{model_roster.CODEX_STD}` (roster rev {model_roster.REVISION + 7})", "std note: says roster rev"),
])
def test_a_planted_disagreement_is_caught(old, new, needle):
    """NEGATIVE CONTROL: the checker sees a wrong cell, a wrong revision and a wrong tier word."""
    planted = _plant(SKILL_MD.read_text(encoding="utf-8"), old, new)
    problems = table_disagreements(planted)
    assert any(needle in p for p in problems), problems


def test_a_std_swap_without_the_note_edit_is_caught(monkeypatch):
    """#302: a codex std swap that forgets the note under the table fails, like the table itself."""
    monkeypatch.setattr(model_roster, "CODEX_STD", "gpt-test-std")
    problems = table_disagreements(SKILL_MD.read_text(encoding="utf-8"))
    assert any("std note: names codex std" in p for p in problems), problems


def test_the_support_row_carries_no_ephemeral_flag():
    """#302 s3.4b / JC-3: the consultant_support row's --ephemeral cell is "no", like every TOP row."""
    _, header, rows = _table(SKILL_MD.read_text(encoding="utf-8"))
    col = header.index("`--ephemeral`")
    cells = {r[0]: r[col] for r in rows}
    assert {role: cells[f"`{role}`"] for role in ROLES} == {role: "no" for role in ROLES}


def test_a_simulated_swap_without_the_table_edit_is_caught(monkeypatch):
    """The failure a real swap produces: the roster moved, the table did not."""
    monkeypatch.setattr(model_roster, "REVISION", model_roster.REVISION + 1)
    problems = table_disagreements(SKILL_MD.read_text(encoding="utf-8"))
    assert any("header says roster rev" in p for p in problems), problems


# --------------------------------------------------------------------------- #
# #291 fix round 1 (I): the claude-code-cli alias table makes no undated "currently" claim
# --------------------------------------------------------------------------- #
_MODEL_CONFIG = _SKILLS / "claude-code-cli" / "references" / "model-config.md"


def _alias_table(text):
    start = text.index("### Model aliases")
    return text[start:text.index("\n### ", start + 1)]


def test_the_alias_table_names_no_undated_current_model():
    # "(currently Opus 4.8)" went stale while the rest of the harness moved on; an alias
    # resolves vendor-side, so the table says what the alias TRACKS, never which model it is
    # today, and points at the harness roster / emit for what serves a seat.
    table = _alias_table(_MODEL_CONFIG.read_text(encoding="utf-8"))
    assert re.findall(r"\(currently [^)]*\)", table, re.IGNORECASE) == []
    assert "model_roster.py" in table and "emit --json" in table
