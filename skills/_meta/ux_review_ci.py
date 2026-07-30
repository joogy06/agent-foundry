#!/usr/bin/env python3
"""ux_review_ci.py — S074. The CI/pre-deploy adapter: the only HARD enforcement edge
available to a standalone review.

Ranked first by the S073 enforcement analysis for two reasons. It is HARD — the model does
not run CI, so it cannot be skipped by an agent that decided the review was unnecessary —
and it is portable, working on Codex and agy hosts where no verified lifecycle-hook
contract exists at all. It is also aimed at the incident's most expensive event: a
regression reaching production, where a cart shipped with no visible prices for months.

    changed files -> is this UI-relevant? -> is there evidence? -> does it bind? ->
    is it FRESH? -> does it PASS?

Any "no" fails the build. `not applicable` is a distinct, explicit outcome — a repo whose
change set never touched UI is not the same as one that passed a review, and collapsing
those two is how a gate becomes decorative.

FRESHNESS IS THE POINT
----------------------
A valid evidence artifact for a PREVIOUS build is exactly as misleading as no artifact:
it is a true statement about a page that no longer exists. So the adapter recomputes a
content hash over the UI-relevant files at the current commit and requires the evidence to
carry the same `product_hash`. Evidence that does not is reported STALE, never PASS.

This is deliberately stricter than "the artifact validates". `ux_evidence.validate()`
answers "was this review complete?"; this adapter answers "was it a review of THIS build?"
Both must hold.

Exit codes (house convention):
    0 — PASS, or NOT_APPLICABLE (no UI-relevant change in the diff)
    2 — BLOCKED (missing / stale / non-binding / non-passing evidence)
    3 — environment failure (no git, unreadable plan)
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ux_evidence  # noqa: E402

# Deliberately broad. A false "UI-relevant" costs one review; a false "not relevant" is the
# incident. Projects narrow this via --ui-glob rather than the default being permissive.
DEFAULT_UI_GLOBS = [
    "*.html", "*.htm", "*.css", "*.scss", "*.sass", "*.less",
    "*.jsx", "*.tsx", "*.vue", "*.svelte",
    "*.php", "*.twig", "*.erb", "*.hbs", "*.mustache",
    "**/templates/**", "**/components/**", "**/views/**", "**/theme/**", "**/layouts/**",
]


def env_error(message: str) -> int:
    sys.stderr.write(f"UX_CI_ENV_ERROR: {message}\n")
    return 3


def blocked(message: str, detail: Optional[List[str]] = None) -> int:
    sys.stderr.write(f"UX_CI_BLOCKED: {message}\n")
    for line in detail or []:
        sys.stderr.write(f"  - {line}\n")
    return 2


def changed_files(root: Path, base: str) -> List[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git diff failed: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {(proc.stderr or '').strip()[:200]}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def is_ui_relevant(path: str, globs: List[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(f"/{path}", g) for g in globs)


def product_hash(root: Path, paths: List[str]) -> str:
    """Content hash over the UI-relevant files at the current commit.

    Sorted for determinism, and the path is hashed alongside the bytes so that moving
    identical content between files still changes the hash — a moved template is a
    different page.
    """
    h = hashlib.sha256()
    for rel in sorted(paths):
        fp = root / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        if fp.is_file():
            h.update(fp.read_bytes())
        else:
            h.update(b"<deleted>")
        h.update(b"\0")
    return h.hexdigest()


def evaluate(
    *,
    root: Path,
    plan: Dict[str, Any],
    evidence_path: Optional[Path],
    changed: List[str],
    ui_globs: List[str],
    severity_floor: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure decision function — no I/O beyond reading the evidence. Unit-testable."""
    relevant = [p for p in changed if is_ui_relevant(p, ui_globs)]
    if not relevant:
        return {"outcome": "NOT_APPLICABLE", "ui_files": [], "reasons": ["no UI-relevant file in the diff"]}

    expected_product = product_hash(root, relevant)

    if evidence_path is None or not evidence_path.is_file():
        return {
            "outcome": "BLOCKED", "ui_files": relevant, "expected_product_hash": expected_product,
            "reasons": [
                f"{len(relevant)} UI-relevant file(s) changed but no evidence artifact was supplied",
                "a UI change with no measured review is the shipping path this gate exists to close",
            ],
        }

    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"outcome": "BLOCKED", "ui_files": relevant, "reasons": [f"evidence unreadable: {exc}"]}

    declared = (evidence.get("product_hash") or "").replace("sha256:", "")
    if not declared:
        return {
            "outcome": "BLOCKED", "ui_files": relevant, "expected_product_hash": expected_product,
            "reasons": ["evidence carries no product_hash, so it cannot be tied to any build"],
        }
    if declared != expected_product:
        return {
            "outcome": "STALE", "ui_files": relevant, "expected_product_hash": expected_product,
            "declared_product_hash": declared,
            "reasons": [
                "evidence was produced against a different build of the UI-relevant files",
                "a valid review of a previous build is a true statement about a page that no longer exists",
            ],
        }

    verdict = ux_evidence.validate(evidence, plan, severity_floor=severity_floor)
    return {
        "outcome": "PASS" if verdict["outcome"] == "PASS" else "BLOCKED",
        "ui_files": relevant,
        "expected_product_hash": expected_product,
        "evidence_outcome": verdict["outcome"],
        "reasons": verdict["outcome_reasons"],
        "verdict": verdict,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CI gate: UI changes require fresh, passing UX evidence.")
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--evidence", type=Path)
    ap.add_argument("--project-root", type=Path, default=Path.cwd())
    ap.add_argument("--base", default="origin/main", help="merge base to diff against")
    ap.add_argument("--changed-file", action="append", default=[],
                    help="bypass git and supply the diff explicitly; repeatable")
    ap.add_argument("--ui-glob", action="append", default=[],
                    help="override the default UI-relevance globs; repeatable")
    ap.add_argument("--severity-floor", choices=list(ux_evidence.SEVERITY_ORDER))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = args.project_root.resolve()
    try:
        plan = ux_evidence.load_plan(args.plan)
    except Exception as exc:
        return env_error(f"plan unreadable: {exc}")

    if args.changed_file:
        changed = list(args.changed_file)
    else:
        try:
            changed = changed_files(root, args.base)
        except RuntimeError as exc:
            return env_error(str(exc))

    result = evaluate(
        root=root, plan=plan, evidence_path=args.evidence, changed=changed,
        ui_globs=args.ui_glob or DEFAULT_UI_GLOBS, severity_floor=args.severity_floor,
    )

    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "verdict"}, indent=2, sort_keys=True))

    outcome = result["outcome"]
    if outcome == "NOT_APPLICABLE":
        if not args.json:
            print("UX_CI_NOT_APPLICABLE: no UI-relevant file changed in this diff")
        return 0
    if outcome == "PASS":
        if not args.json:
            print(f"UX_CI_PASS: {len(result['ui_files'])} UI file(s) changed; "
                  f"evidence is fresh and validates PASS")
        return 0
    if not args.json:
        blocked(f"{outcome} — {len(result['ui_files'])} UI-relevant file(s) changed", result["reasons"])
    return 2


if __name__ == "__main__":
    sys.exit(main())
