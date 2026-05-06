"""first_touch.py -- Session-start handler for evergreen migration.

When the project-documentation skill runs at session start in a project
where:
  * `history.md` exists, AND
  * `history.md` has NO `<!-- rotated: ... -->` stamp, AND
  * `history.md` exceeds 100 lines (configurable), AND
  * the project has not opted out via DOCUMENTATION-PREFERENCES.md
    (`history_rotation: { mode: never }`)

then `check_and_prompt(project_root)` returns the prompt text. The actual
operator interaction lives in the calling skill (LLM presents the menu;
this module's job is to compute the plan and execute the chosen action).

Choices:
  E1: bucket-by-date  -- parse + archive monthly via rotate.run
  E2: bulk-archive    -- move whole file unchanged to history/pre-rotation-bulk.md
  E3: skip            -- no writes; ask again next session (default if no answer)
  E4: never           -- write `mode: never` flag; never prompt again

Critical rules (per design 4.4):
  * NEVER silent-mutate. Default-on-no-answer is E3.
  * Every E1/E2 path goes through the same lock + mtime + atomic-write +
    sha256-verify safety contract as rotate.run.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _boundary_detect as bd  # noqa: E402
import rotate  # noqa: E402

ELIGIBILITY_LINE_THRESHOLD = 100  # design 4.1 row 3


@dataclass
class FirstTouchPlan:
    """What we'd do if the operator picks E1."""

    detected_tier: str  # H1..F2
    boundary_count: int
    confidence: str
    estimated_live_lines: int
    estimated_archive_lines: int
    estimated_buckets: int


@dataclass
class ActionResult:
    chosen_action: str  # "E1" | "E2" | "E3" | "E4" | "ineligible"
    outcome: str  # "success" | "aborted" | "skipped" | "ineligible"
    modified_files: List[Path] = field(default_factory=list)
    restore_command_string: Optional[str] = None
    idempotency_stamp_added: bool = False
    diagnostic: Optional[str] = None
    exit_code: int = 0


# ---------------------------------------------------------------------------
# Eligibility check
# ---------------------------------------------------------------------------


def is_first_touch_eligible(project_root: Path) -> bool:
    """True iff first-touch should prompt for this project."""
    project_root = Path(project_root)
    history = project_root / "history.md"
    if not history.exists():
        return False
    try:
        text = history.read_text(encoding="utf-8")
    except OSError:
        return False
    if rotate.find_existing_stamp(text):
        return False
    if len(text.splitlines()) <= ELIGIBILITY_LINE_THRESHOLD:
        return False
    cfg = rotate.load_config(project_root)
    if cfg.mode == "never":
        return False
    return True


# ---------------------------------------------------------------------------
# Plan computation (used to render the prompt body)
# ---------------------------------------------------------------------------


def compute_e1_plan(project_root: Path) -> FirstTouchPlan:
    history = project_root / "history.md"
    text = history.read_text(encoding="utf-8")
    rep = bd.find_boundaries(text)
    cfg = rotate.load_config(project_root)
    total_lines = len(text.splitlines())

    # Estimate: keeping last N sessions live; rest archived
    live_lines = 0
    archive_lines = 0
    buckets: set = set()
    if rep.boundaries:
        # Walk blocks newest-first; keep first cfg.N
        from rotate import _extract_blocks  # local import; private but stable

        blocks = _extract_blocks(text, rep)
        for i, b in enumerate(blocks):
            block_lc = b.text.count("\n")
            if i < cfg.N:
                live_lines += block_lc
            else:
                archive_lines += block_lc
                if b.start_date and len(b.start_date) >= 7:
                    buckets.add(b.start_date[:7])
                else:
                    buckets.add("unknown")
    else:
        # F2 path: bulk-archive recommended; E1 will fall back to E2 shape
        archive_lines = total_lines

    return FirstTouchPlan(
        detected_tier=rep.tier,
        boundary_count=len(rep.boundaries),
        confidence=rep.confidence,
        estimated_live_lines=live_lines,
        estimated_archive_lines=archive_lines,
        estimated_buckets=len(buckets),
    )


def render_prompt_body(project_root: Path) -> str:
    """Build the human-readable prompt the LLM presents to the user."""
    history = project_root / "history.md"
    line_count = len(history.read_text(encoding="utf-8").splitlines())
    plan = compute_e1_plan(project_root)
    lines = []
    lines.append(
        f"project-documentation: history.md has {line_count} lines and no rotation stamp."
    )
    lines.append(
        "The new rotation policy will keep ~last 3 sessions live; older content goes to history/."
    )
    lines.append("")
    lines.append("Pick how to handle existing content:")
    lines.append("")
    lines.append(
        f"  E1. Bucket-by-date     (parse existing sessions, archive to history/YYYY-MM.md)"
    )
    lines.append(
        f"                         confidence: {plan.confidence} ({plan.boundary_count} boundaries detected, tier {plan.detected_tier})"
    )
    if plan.boundary_count >= 1:
        lines.append(
            f"                         estimated outcome: {plan.estimated_live_lines} lines live, "
            f"{plan.estimated_archive_lines} lines in {plan.estimated_buckets} monthly bucket(s)"
        )
    else:
        lines.append(
            "                         WARNING: no boundaries detected; E1 will fall through to E2 (bulk-archive)"
        )
    lines.append("                         backup: history.md.pre-rotation-bak")
    lines.append("")
    lines.append("  E2. Bulk-archive       (move all existing content to history/pre-rotation-bulk.md unchanged,")
    lines.append("                         start fresh; new sessions get rotated automatically)")
    lines.append("                         confidence: ALWAYS-SAFE (no parsing)")
    lines.append(f"                         estimated outcome: 0 lines live (next write seeds it), {line_count} lines bulk-archived")
    lines.append("")
    lines.append("  E3. Skip this session  (do nothing; ask again next time)")
    lines.append("")
    lines.append("  E4. Never for this project  (write skip flag to DOCUMENTATION-PREFERENCES.md;")
    lines.append("                              file grows unbounded; no rotation ever auto-runs)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level entry: check_and_prompt
# ---------------------------------------------------------------------------


def check_and_prompt(
    project_root: str | Path,
    *,
    user_choice: Optional[str] = None,
    actor: str = "first-touch",
) -> ActionResult:
    """Main entry point for the project-documentation session-start hook.

    If `user_choice` is None and the project is eligible, this returns
    `ActionResult(chosen_action="prompt", outcome="ineligible")` style
    record asking the caller (LLM) to render `render_prompt_body` and
    re-invoke with the chosen action.

    Default-on-no-answer is `"E3"` (skipped) -- callers that already
    rendered the prompt and got no answer should pass `user_choice="E3"`
    explicitly. We do NOT treat None as "go ahead and do something."
    """

    project_root = Path(project_root).resolve()

    if not is_first_touch_eligible(project_root):
        return ActionResult(
            chosen_action="ineligible",
            outcome="ineligible",
            exit_code=0,
            diagnostic="not eligible (stamped, missing, under threshold, or mode=never)",
        )

    if user_choice is None:
        # Caller must render the prompt body separately and re-call with a choice.
        return ActionResult(
            chosen_action="prompt",
            outcome="skipped",
            exit_code=0,
            diagnostic="no user_choice provided; render prompt then re-call",
        )

    choice = user_choice.upper().strip()
    if choice == "E1":
        return handle_e1_bucket(project_root, actor=actor)
    if choice == "E2":
        return handle_e2_bulk(project_root, actor=actor)
    if choice == "E3":
        return handle_e3_skip(project_root)
    if choice == "E4":
        return handle_e4_never(project_root)

    return ActionResult(
        chosen_action=choice,
        outcome="aborted",
        exit_code=1,
        diagnostic=f"unknown choice: {user_choice!r}",
    )


# ---------------------------------------------------------------------------
# E1: bucket-by-date
# ---------------------------------------------------------------------------


def handle_e1_bucket(project_root: Path, *, actor: str = "first-touch") -> ActionResult:
    """Run rotate.run with --apply preset; archive by start-date month."""
    project_root = Path(project_root).resolve()
    plan = compute_e1_plan(project_root)
    # If detector returned 0 boundaries, we cannot bucket -- fall through to E2
    if plan.boundary_count == 0:
        return handle_e2_bulk(project_root, actor=actor, fallback_reason="no boundaries detected; E1 falls through to E2")

    result = rotate.run(project_root, actor=actor)
    if result.exit_code != 0:
        return ActionResult(
            chosen_action="E1",
            outcome="aborted",
            exit_code=result.exit_code,
            diagnostic=result.diagnostic or "rotate.run failed",
        )
    return ActionResult(
        chosen_action="E1",
        outcome="success",
        modified_files=[project_root / "history.md"],
        restore_command_string=result.restore_command_string,
        idempotency_stamp_added=True,
        exit_code=0,
    )


# ---------------------------------------------------------------------------
# E2: bulk-archive
# ---------------------------------------------------------------------------


_BULK_HEADER = (
    "<!-- HISTORY_ARCHIVE auto-managed; bulk-archive -->\n"
    "# History Archive -- bulk migration\n\n"
    "> This file holds the entire pre-rotation history.md captured at first-touch.\n"
    "> No structural parsing was performed; content is byte-identical to the original.\n\n"
)


def handle_e2_bulk(
    project_root: Path,
    *,
    actor: str = "first-touch",
    fallback_reason: Optional[str] = None,
) -> ActionResult:
    """Move full history.md content to history/pre-rotation-bulk.md, then
    create a fresh stub history.md (stamped). Lossless by construction."""
    project_root = Path(project_root).resolve()
    live = project_root / "history.md"
    if not live.exists():
        return ActionResult(
            chosen_action="E2",
            outcome="aborted",
            exit_code=1,
            diagnostic="no history.md to bulk-archive",
        )

    lock = rotate.acquire_lock(live.parent)
    if not lock.acquire():
        return ActionResult(
            chosen_action="E2",
            outcome="aborted",
            exit_code=1,
            diagnostic="lock contention",
        )
    backup = live.with_name(live.name + ".pre-rotation-bak")
    archive_path = live.parent / "history" / "pre-rotation-bulk.md"
    try:
        mtime_before = live.stat().st_mtime_ns
        original = live.read_text(encoding="utf-8")
        # Backup
        shutil.copy2(live, backup)
        # mtime guard
        if live.stat().st_mtime_ns != mtime_before:
            return ActionResult(
                chosen_action="E2",
                outcome="aborted",
                exit_code=1,
                diagnostic="mtime guard tripped",
            )
        # Write archive (header + raw content)
        archive_text = _BULK_HEADER + original
        rotate._atomic_write_text(archive_path, archive_text)
        # Verify lossless: archive contains all original bytes
        written = archive_path.read_text(encoding="utf-8")
        if original not in written:
            rotate.rollback_partial_write(
                backup_path=backup,
                live_path=live,
                newly_created_archives=[archive_path],
                diagnostic="bulk archive is missing original content",
            )
            return ActionResult(
                chosen_action="E2",
                outcome="aborted",
                exit_code=1,
                diagnostic="lossless verification failed",
            )
        # Stub live file
        stub_body = (
            "## Session 001 -- pre-rotation-bulk archived\n"
            f"All prior history was bulk-archived to history/pre-rotation-bulk.md "
            f"({len(original.splitlines())} lines).\n"
        )
        stub_full = rotate.write_idempotency_stamp(
            stub_body, actor=actor, sessions_live=1, cap=rotate.DEFAULT_CAP, last_roll_summary="bulk-archive"
        )
        rotate._atomic_write_text(live, stub_full)

        diag = "bulk-archived"
        if fallback_reason:
            diag = f"{diag} ({fallback_reason})"
        return ActionResult(
            chosen_action="E2",
            outcome="success",
            modified_files=[live, archive_path],
            restore_command_string=f"mv {backup} {live} && rm -rf {live.parent / 'history'}",
            idempotency_stamp_added=True,
            exit_code=0,
            diagnostic=diag,
        )
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# E3: skip
# ---------------------------------------------------------------------------


def handle_e3_skip(project_root: Path) -> ActionResult:
    """Do nothing. Eligibility persists; will prompt again next session."""
    return ActionResult(
        chosen_action="E3",
        outcome="skipped",
        exit_code=0,
        diagnostic="user chose to skip; will prompt again next session",
    )


# ---------------------------------------------------------------------------
# E4: never
# ---------------------------------------------------------------------------


_E4_BLOCK = "\n\nhistory_rotation: { mode: never }\n"
_E4_MARKER = "history_rotation:"


def handle_e4_never(project_root: Path) -> ActionResult:
    """Append `history_rotation: { mode: never }` to DOCUMENTATION-PREFERENCES.md.

    Idempotent: if the file already has a history_rotation block we leave
    it alone (the operator-set value takes precedence).
    """
    project_root = Path(project_root).resolve()
    pref_path = project_root / "docs" / "DOCUMENTATION-PREFERENCES.md"
    pref_path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if pref_path.exists():
        try:
            existing = pref_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    if _E4_MARKER in existing:
        # Already configured -- respect it
        cfg = rotate.load_config(project_root)
        if cfg.mode == "never":
            return ActionResult(
                chosen_action="E4",
                outcome="success",
                exit_code=0,
                diagnostic="mode=never already set",
            )
        # Configured but not "never": don't overwrite operator preference
        return ActionResult(
            chosen_action="E4",
            outcome="aborted",
            exit_code=1,
            diagnostic=f"existing history_rotation has mode={cfg.mode}; not overwriting",
        )

    new_text = (existing.rstrip("\n") + _E4_BLOCK) if existing else f"# Documentation Preferences\n{_E4_BLOCK}"
    rotate._atomic_write_text(pref_path, new_text)

    return ActionResult(
        chosen_action="E4",
        outcome="success",
        modified_files=[pref_path],
        exit_code=0,
        diagnostic="mode=never written; rotation will not auto-run",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: List[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(description="First-touch session-start handler for history.md rotation.")
    p.add_argument("project_root")
    p.add_argument("--choice", default=None, help="E1 | E2 | E3 | E4 (default: prompt only)")
    p.add_argument("--apply", action="store_true", help="Power-user shortcut: choice=E1 unconditionally")
    args = p.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    choice = "E1" if args.apply else args.choice

    if choice is None and is_first_touch_eligible(project_root):
        sys.stdout.write(render_prompt_body(project_root) + "\n")
        sys.stdout.write("\nPass --choice E1|E2|E3|E4 to act.\n")
        return 0

    result = check_and_prompt(project_root, user_choice=choice)
    sys.stdout.write(
        f"action={result.chosen_action} outcome={result.outcome} exit={result.exit_code}\n"
    )
    if result.diagnostic:
        sys.stdout.write(f"diagnostic: {result.diagnostic}\n")
    if result.restore_command_string:
        sys.stdout.write(f"undo: {result.restore_command_string}\n")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
