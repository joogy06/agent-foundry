#!/usr/bin/env python3
"""session_prime.py — S074. The mechanical half of VS Code session startup.

VS Code has no SessionStart hook that injects into chat context. What it does have is a
`folderOpen` task, which can run this. So this does the part a task CAN do — probe the
environment and write a state file — and makes no claim about the part it cannot: whether
anyone reads it.

The output therefore carries a GRADE, and the grade is the point:

    primed (task)    written automatically on folder open
    primed (manual)  someone ran /prime deliberately
    unprimed         no state, or the state is stale

Reporting a stale digest as though the session were primed is the exact failure the harness
was built against, so this refuses to imply freshness it cannot support.

Stdlib only, and it must run on Windows and macOS as well as Linux — no bash, no POSIX
path assumptions. Exit: 0 written · 2 written with gaps worth reporting · 3 cannot write.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CONTEXT_FILES = ("PROJECT.md", "history.md", "tasks.md", "session_control.md",
                 "index.md", "CLAUDE.md", "AGENTS.md", ".project-profile.json")


def probe_tools() -> Dict[str, bool]:
    return {t: bool(shutil.which(t)) for t in
            ("git", "python3", "node", "copilot", "code", "claude", "codex", "agy")}


def detect_models(repo_root: Path) -> Dict[str, Any]:
    """Delegate to the detector — never duplicate its logic, and never assume a roster."""
    script = repo_root / "vs-code" / "scripts" / "detect_models.py"
    if not script.is_file():
        return {"models": [], "note": "detector not found"}
    try:
        p = subprocess.run([sys.executable, str(script), "--json"],
                           capture_output=True, text=True, timeout=30)
        if p.returncode in (0, 2) and p.stdout.strip():
            d = json.loads(p.stdout)
            return {"models": d.get("models", []),
                    "vendors": d.get("vendors_available", []),
                    "note": d.get("note", "")}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"models": [], "note": f"detection failed: {exc}"}
    return {"models": [], "note": "no models detected"}


def stale_markers(repo_root: Path) -> List[Dict[str, str]]:
    """Any REVIEW_BY that has passed. Cheap, and it catches rotted references."""
    today = datetime.now(timezone.utc).date().isoformat()
    out: List[Dict[str, str]] = []
    for md in list(repo_root.glob("vs-code/**/*.md")) + list(repo_root.glob("skills/*/references/*.md")):
        try:
            head = md.read_text(errors="ignore")[:2000]
        except OSError:
            continue
        for line in head.splitlines():
            if "REVIEW_BY:" in line:
                date = line.split("REVIEW_BY:")[1].strip().strip("-> *#<!")[:10]
                if len(date) == 10 and date < today:
                    out.append({"file": str(md.relative_to(repo_root)), "review_by": date})
                break
    return out


def build(repo_root: Path, grade: str) -> Dict[str, Any]:
    present = [f for f in CONTEXT_FILES if (repo_root / f).exists()]
    missing = [f for f in CONTEXT_FILES if f not in present]
    stale = stale_markers(repo_root)
    return {
        "schema": "vscode-session-state.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "grade": grade,
        "platform": platform.system(),
        "repo_root": str(repo_root),
        "context_present": present,
        "context_absent": missing,
        "tools": probe_tools(),
        "models": detect_models(repo_root),
        "stale_reviews": stale,
        "note": (
            "This file is the MECHANICAL half of startup. Its existence proves the probes ran; it "
            "proves nothing about whether the model read it. Report the grade honestly and never "
            "imply a primed session from a stale file."
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Write VS Code session state for foundry-lab.")
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--grade", default="primed (task)",
                    choices=["primed (task)", "primed (manual)"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    state = build(root, args.grade)
    out_dir = root / ".foundry"
    try:
        out_dir.mkdir(exist_ok=True)
        (out_dir / "session-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"PRIME_ENV_ERROR: cannot write state: {exc}\n")
        return 3

    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(f"{state['grade'].upper()} — {state['generated_at']}  [{state['platform']}]")
        print(f"  context:  {', '.join(state['context_present']) or 'none found'}")
        if state["context_absent"]:
            print(f"  NOT found: {', '.join(state['context_absent'])}")
        tools = [t for t, ok in state["tools"].items() if ok]
        print(f"  tools:    {', '.join(tools) or 'none'}")
        m = state["models"]
        print(f"  models:   {', '.join(m['models']) if m['models'] else 'none detectable — check the picker'}")
        if state["stale_reviews"]:
            print(f"  STALE:    {len(state['stale_reviews'])} reference(s) past REVIEW_BY")
            for s in state["stale_reviews"][:3]:
                print(f"              {s['file']} (due {s['review_by']})")
        print(f"\n  {state['note']}")

    return 2 if (state["stale_reviews"] or not state["models"]["models"]) else 0


if __name__ == "__main__":
    sys.exit(main())
