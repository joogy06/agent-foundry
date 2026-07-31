"""migrate.py -- Optional power-user CLI wrapper over first_touch.

Thin shim: parses CLI flags, resolves the target path to a project root
(directory containing history.md), and delegates to
`first_touch.check_and_prompt(project_root, user_choice="E1")` with the
`--apply` preset (auto-confirm bucket-by-date plan).

Default mode is `--dry-run`: shows what E1 would do without writing.
`--apply` actually executes.

Single-file scope. No batch/fleet discovery (per design decision: no bulk
migration tool; rotation attaches per-project on natural session entry).

Exit codes:
   0 = success (or dry-run plan printed)
   1 = first_touch failure propagated
   2 = invalid args / target path
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import first_touch  # noqa: E402


def _resolve_project_root(target: str) -> Path:
    """Find the project root for `target`. If `target` is a directory
    containing history.md, that's the root. If it's a file path to a
    history.md, use its parent."""
    p = Path(target).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"target path does not exist: {p}")
    if p.is_file() and p.name == "history.md":
        return p.parent
    if p.is_dir() and (p / "history.md").exists():
        return p
    raise FileNotFoundError(
        f"no history.md at {p} (pass a project root that contains one, or a path to history.md)"
    )


def parse_cli_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="migrate.py",
        description="Power-user proactive migration of a single project's history.md.",
    )
    p.add_argument("target", help="Project root (containing history.md) or path to history.md")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true", default=True, help="Print E1 plan without writing (default)")
    grp.add_argument("--apply", action="store_true", help="Execute E1 (bucket-by-date) migration")
    p.add_argument("--bulk", action="store_true", help="Use E2 (bulk-archive) instead of E1")
    return p.parse_args(argv)


def run_migration_cli(argv: List[str]) -> int:
    try:
        args = parse_cli_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 2

    try:
        project_root = _resolve_project_root(args.target)
    except FileNotFoundError as e:
        sys.stderr.write(f"migrate: {e}\n")
        return 2

    if not first_touch.is_first_touch_eligible(project_root):
        sys.stdout.write(
            f"migrate: {project_root}/history.md is not eligible for first-touch "
            "(already stamped, under threshold, or mode=never).\n"
        )
        return 0

    if args.dry_run and not args.apply:
        sys.stdout.write(first_touch.render_prompt_body(project_root) + "\n")
        sys.stdout.write("\n(dry-run; pass --apply to execute, or --apply --bulk for E2)\n")
        return 0

    choice = "E2" if args.bulk else "E1"
    result = first_touch.check_and_prompt(project_root, user_choice=choice, actor="migrate")
    sys.stdout.write(
        f"migrate: action={result.chosen_action} outcome={result.outcome} exit={result.exit_code}\n"
    )
    if result.diagnostic:
        sys.stdout.write(f"  diagnostic: {result.diagnostic}\n")
    if result.restore_command_string:
        sys.stdout.write(f"  undo: {result.restore_command_string}\n")
    if result.outcome == "success":
        return 0
    return 1 if result.exit_code != 0 else 0


if __name__ == "__main__":
    sys.exit(run_migration_cli(sys.argv[1:]))
