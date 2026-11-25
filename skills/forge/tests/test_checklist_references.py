#!/usr/bin/env python3
"""The forge checklist names every reference a step needs (#344 fix round 1: F1, m2, m3, m4).

Forge's entry file sends the reader to one or more files under `references/` on each
step's own line ("Read references/... before this step."). After the split a step could
name a reference whose text tells the reader to RUN a procedure that lives in a third
file the step never named. Two rules catch that:

  index      the reference index says which steps each file serves; a step the index
             names for a file reads that file, and a file a step reads is indexed for
             that step. (This caught `external-finding-verification.md`, indexed for
             the step 11 fix loop and absent from step 11's line.)
  procedure  a file that tells the reader to run a procedure held elsewhere ("verify
             per Stage 1.5") is only read together with the holder. (This caught
             `08-spec-review.md`, missing from steps 6 and 11.)

Also pinned here: which of the three fail-silent blocks starts inside the part of the
entry file that is re-attached after a compaction (m2), what a missing seat script means
for the seats of a call (m3), and the wording of the sourced call sites (m4).

Reads the repo tree only; writes nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FORGE = Path(__file__).resolve().parents[1]
SKILLS = FORGE.parent
ENTRY = FORGE / "SKILL.md"
REFERENCES = FORGE / "references"

_STEP_LINE = re.compile(r"^(\d+[a-z]?)\. \*\*")
_READ_LINE = re.compile(r"^\s+Read references/")
_REF = re.compile(r"references/([A-Za-z0-9_.-]+\.md)")
_INDEX_LINE = re.compile(r"^- `references/([A-Za-z0-9_.-]+\.md)` — (.*)$")
_STEP_LIST = re.compile(r"\bsteps?\s+(\d+[a-z]?(?:(?:,\s*|\s+and\s+)\d+[a-z]?)*)")
_STEP_ID = re.compile(r"\d+[a-z]?")

#: The byte count re-attached after a compaction (skill_audit.HARD_BLOCK_BYTE_LIMIT).
REATTACHED_BYTES = 20_000

#: A term that means "run this procedure now" -> the reference that holds the procedure.
#: A file using the term is only ever read together with the holder.
PROCEDURES = {
    "Stage 1.5": (re.compile(r"Stage[- ]1\.5"), "08-spec-review.md"),
}

STUCK_LINE = "At any step where Claude is stuck"


def entry_lines() -> list[str]:
    return ENTRY.read_text(encoding="utf-8").splitlines()


def checklist(lines: list[str] | None = None) -> dict[str, set[str]]:
    """step id -> the references its `Read references/...` line names."""
    lines = entry_lines() if lines is None else lines
    start = lines.index("## Checklist")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    out: dict[str, set[str]] = {}
    step = None
    for line in lines[start:end]:
        m = _STEP_LINE.match(line)
        if m:
            step = m.group(1)
            out.setdefault(step, set())
        elif step and _READ_LINE.match(line):
            out[step].update(_REF.findall(line))
        elif line.startswith(STUCK_LINE):
            out["stuck"] = set(_REF.findall(line))
            step = None
    return out


def index(lines: list[str] | None = None) -> dict[str, tuple[set[str], str]]:
    """reference -> (the step ids its index line names before the colon, the line)."""
    lines = entry_lines() if lines is None else lines
    out: dict[str, tuple[set[str], str]] = {}
    for line in lines:
        m = _INDEX_LINE.match(line)
        if not m:
            continue
        scope = m.group(2).split(":", 1)[0]
        steps: set[str] = set()
        for group in _STEP_LIST.findall(scope):
            steps.update(_STEP_ID.findall(group))
        out[m.group(1)] = (steps, line)
    return out


def index_problems(lines: list[str] | None = None) -> list[str]:
    steps, idx = checklist(lines), index(lines)
    problems = []
    for ref, (named, _line) in sorted(idx.items()):
        for step in sorted(named):
            if ref not in steps.get(step, set()):
                problems.append(f"the index names step {step} for {ref}, but step {step}'s "
                                "line does not read it")
    for step, refs in sorted(steps.items()):
        if step == "stuck":
            continue
        for ref in sorted(refs):
            if ref in idx and step not in idx[ref][0]:
                problems.append(f"step {step} reads {ref}, but the index does not name "
                                f"step {step} for it")
    return problems


def procedure_problems(lines: list[str] | None = None, texts: dict[str, str] | None = None
                       ) -> list[str]:
    steps = checklist(lines)
    if texts is None:
        texts = {p.name: p.read_text(encoding="utf-8") for p in REFERENCES.glob("*.md")}
    problems = []
    for step, refs in sorted(steps.items()):
        for ref in sorted(refs):
            for term, (pattern, holder) in PROCEDURES.items():
                if ref != holder and pattern.search(texts.get(ref, "")) and holder not in refs:
                    problems.append(f"step {step} reads {ref}, which uses {term!r}, "
                                    f"without {holder}")
    return problems


# ---------------------------------------------------------------------------- F1

def test_the_parsers_see_the_whole_checklist_and_the_whole_index():
    steps, idx = checklist(), index()
    assert {"1", "2", "3", "5", "6", "7", "7b", "8", "8a", "8b", "8c", "9", "11", "stuck"} \
        <= set(steps)
    on_disk = {p.name for p in REFERENCES.glob("*.md")}
    assert set(idx) == on_disk, "every reference has exactly one index line"
    named = set().union(*steps.values())
    assert named <= on_disk, f"the checklist names a file that does not exist: {named - on_disk}"
    assert idx["06-present-and-doc.md"][0] == {"2", "7", "7b", "8"}
    assert idx["03-codex-seats.md"][0] == {"6", "11"}


def test_the_index_and_the_checklist_agree_on_which_step_reads_which_reference():
    assert index_problems() == []


def test_a_reference_that_runs_a_procedure_is_read_with_the_file_that_holds_it():
    assert procedure_problems() == []


def test_step_6_and_step_11_name_the_stage_1_5_holder_and_step_11_the_protocol():
    """The two lines the review found short, pinned by name."""
    steps = checklist()
    assert "08-spec-review.md" in steps["6"]
    assert {"08-spec-review.md", "external-finding-verification.md",
            "10-close-out.md", "03-codex-seats.md"} <= steps["11"]


def test_NEGATIVE_CONTROL_both_rules_fail_on_the_lines_as_they_were():
    """The step 6 and step 11 lines as they stood before the fix: each rule reports."""
    lines = entry_lines()
    before = []
    for line in lines:
        if _READ_LINE.match(line) and "references/04-agy-and-converge.md" in line:
            line = ("   Read references/02-design-team.md, references/03-codex-seats.md, "
                    "references/04-agy-and-converge.md and references/principles.md before "
                    "this step.")
        elif _READ_LINE.match(line) and "references/10-close-out.md" in line:
            line = ("   Read references/10-close-out.md and references/03-codex-seats.md "
                    "before this step.")
        before.append(line)
    assert before != lines
    procedures = procedure_problems(before)
    assert any("step 6 reads 04-agy-and-converge.md" in p for p in procedures), procedures
    assert any("step 11 reads 10-close-out.md" in p for p in procedures), procedures
    indexed = index_problems(before)
    assert any("step 11 for external-finding-verification.md" in p for p in indexed), indexed


# ---------------------------------------------------------------------------- m2

def block_start(heading: str) -> int:
    """Byte offset of the first fenced block under `heading` in the entry file."""
    text = ENTRY.read_text(encoding="utf-8")
    at = text.index("\n" + heading + "\n")
    return len(text[:text.index("\n```bash\n", at) + 1].encode("utf-8"))


FAIL_SILENT = ("### Step 1: Understanding (Lead Only)", "### Step 4: Write Design Doc",
               "### Step 6: Collect Results")


def block_end(heading: str) -> int:
    """Byte offset just past the closing fence of the first fenced block under `heading`."""
    text = ENTRY.read_text(encoding="utf-8")
    opened = text.index("\n```bash\n", text.index("\n" + heading + "\n")) + 1
    closing = text.index("\n```\n", opened) + 1
    return len(text[:closing + len("```\n")].encode("utf-8"))


#: Fix round 2 (R3): room kept under the limit, so that one more sentence above the block
#: does not push its last lines out of the re-attached part unnoticed.
STEP_1_BLOCK_ENDS_BY = 19_700


def test_the_step_1_cycle_start_block_starts_inside_the_reattached_part():
    assert block_start(FAIL_SILENT[0]) < REATTACHED_BYTES


def test_the_step_1_cycle_start_block_ENDS_inside_the_reattached_part():
    """A block cut off before its closing fence is a block that fails silently: the
    start alone being inside proves nothing about its last `fi`."""
    end = block_end(FAIL_SILENT[0])
    assert block_start(FAIL_SILENT[0]) < end < REATTACHED_BYTES
    assert end <= STEP_1_BLOCK_ENDS_BY, (
        f"the Step 1 block ends at byte {end}; keep it at or under {STEP_1_BLOCK_ENDS_BY} "
        "(shorten text this cycle added above it; kept text is not reworded)")


def test_the_entry_file_says_which_fail_silent_blocks_sit_after_the_reattached_part():
    """All three cannot start under byte 20,000 (the Step 1 block and its two lifecycle
    paragraphs are 3.3 KB on their own), so the file says which do and which do not --
    and this test fails if a later edit makes that sentence untrue in either direction."""
    inside = [h for h in FAIL_SILENT if block_start(h) < REATTACHED_BYTES]
    assert inside == [FAIL_SILENT[0]]
    text = ENTRY.read_text(encoding="utf-8")
    how_to = text[text.index("## How to use this skill"):text.index("### Reference index")]
    assert "the three fail-silent blocks sit after it" not in how_to
    assert "the Step 1 block starts inside it" in how_to
    assert "the Step 4 and Step 6 blocks sit after it" in how_to
    starts = [block_start(h) for h in FAIL_SILENT]
    assert starts == sorted(starts), "the blocks stay in step order"


# ---------------------------------------------------------------------------- m3, m4

SEAT_SITES = (REFERENCES / "03-codex-seats.md", REFERENCES / "05-escalation.md",
              SKILLS / "codex-orchestration" / "SKILL.md")
MISSING_SCRIPT_RULE = ("exits non-zero with the stderr line `CODEX_GAP: codex_top_seat.sh "
                       "missing or unreadable")


@pytest.mark.parametrize("doc", SEAT_SITES, ids=lambda p: p.parent.name + "/" + p.name)
def test_each_seat_site_says_what_a_missing_seat_script_means(doc):
    """The guard writes its gap line to STDERR and no seat output file exists, while the
    convergence and escalation rules key on a `CODEX_GAP:` first line in each seat's
    file. Each site therefore says: that exit means every seat of the call is a gap."""
    text = doc.read_text(encoding="utf-8")
    assert text.count(MISSING_SCRIPT_RULE) == 1, doc
    line = next(l for l in text.splitlines() if MISSING_SCRIPT_RULE in l)
    assert "every seat" in line and "is a gap" in line
    assert "no seat output file" in line


@pytest.mark.parametrize("doc", SEAT_SITES, ids=lambda p: p.parent.name + "/" + p.name)
def test_the_sourced_sites_say_sources_not_defines(doc):
    text = doc.read_text(encoding="utf-8")
    assert "THAT SOURCES AND RUNS THIS IN THE BACKGROUND" in text
    assert "DEFINES AND RUNS" not in text, "the function is sourced here, no longer defined"


def test_the_two_sites_that_still_paste_the_function_keep_defines():
    for skill in ("adversarial-team-brainstorm", "cross-cli-deliberation"):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "codex_top_seat() {" in text and "DEFINES AND RUNS" in text, skill
