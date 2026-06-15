#!/usr/bin/env python3
"""workflow_dispatch.py — S055 §4.3 / R11 dispatch+receipts helper.

The MAIN LOOP is the SOLE WRITER of progress/workflow-runs.jsonl. This helper
provides the atomic, exactly-once claim primitive plus the audit reads. Each
critical section is a SINGLE flock'd helper call (the flock spans only this
process — no cross-process lock lifetime problem). Writes are O_APPEND so they
land at EOF even under concurrent callers.

Records conform to workflow-run-record.v1 (one JSON line per state transition):
  emitted -> claimed -> executing -> complete | failed

CLI:
  workflow_dispatch.py emit     --project-root R --workflow W --plan-hash H \
                                --plan-revision N --run-label L [--at ISO]
  workflow_dispatch.py claim    --project-root R --workflow W --plan-hash H \
                                --plan-revision N --run-label L [--args-sha256 S] [--at ISO]
  workflow_dispatch.py executing --project-root R --workflow W --plan-hash H \
                                --plan-revision N --run-label L --run-id ID \
                                [--resumed-from TOKEN] [--at ISO]
  workflow_dispatch.py finish   --project-root R --workflow W --plan-hash H \
                                --plan-revision N --run-label L --state complete|failed [--at ISO]
  workflow_dispatch.py audit-resume-across-revision --project-root R

`claim` prints the new claim_token on success (exit 0); on refusal prints
REFUSED:<reason> and exits 3. `at` MUST be caller-stamped (scripts cannot read
the clock — W-A); if omitted the CLI stamps it as a convenience for human use.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LIVE_STATES = ("claimed", "executing")
TERMINAL_STATES = ("complete", "failed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_path(project_root: Path) -> Path:
    return project_root / "progress" / "workflow-runs.jsonl"


def _lock_path(project_root: Path) -> Path:
    return project_root / "progress" / ".workflow-runs.lock"


def _read_records(project_root: Path) -> List[Dict[str, Any]]:
    p = _log_path(project_root)
    if not p.is_file():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append_record(project_root: Path, rec: Dict[str, Any]) -> None:
    """O_APPEND write — lands at EOF even under concurrent writers."""
    p = _log_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


class _DispatchLock:
    """Single-call flock critical section (mirrors claims._bob_claim_lock)."""

    def __init__(self, project_root: Path) -> None:
        self.path = _lock_path(project_root)
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()


def _live_claim_exists(records: List[Dict[str, Any]], plan_hash: str, plan_revision: int) -> Optional[Dict[str, Any]]:
    """Return the most recent LIVE (claimed/executing not yet terminal) record
    for (plan_hash, plan_revision), or None. A claim is 'live' if the latest
    state line for its (plan_hash, plan_revision) is claimed/executing."""
    # Determine the latest state per (plan_hash, plan_revision).
    latest: Dict[tuple, Dict[str, Any]] = {}
    for r in records:
        key = (r.get("plan_hash"), r.get("plan_revision"))
        latest[key] = r  # records are append-order; last wins
    r = latest.get((plan_hash, plan_revision))
    if r and r.get("state") in LIVE_STATES:
        return r
    return None


def emit(project_root: Path, workflow: str, plan_hash: str, plan_revision: int,
         run_label: str, at: Optional[str] = None) -> Dict[str, Any]:
    rec = {
        "state": "emitted", "workflow": workflow, "plan_hash": plan_hash,
        "plan_revision": plan_revision, "run_label": run_label,
        "run_id": None, "args_sha256": None, "resumed_from": None,
        "claim_token": None, "at": at or _now_iso(),
    }
    with _DispatchLock(project_root):
        _append_record(project_root, rec)
    return rec


def claim(project_root: Path, workflow: str, plan_hash: str, plan_revision: int,
          run_label: str, args_sha256: Optional[str] = None,
          at: Optional[str] = None) -> Dict[str, Any]:
    """Atomic exactly-once claim. Refuses if a LIVE claim for (plan_hash,
    plan_revision) already exists (a second caller / double-resume structurally
    cannot execute the same plan twice)."""
    with _DispatchLock(project_root):
        records = _read_records(project_root)
        live = _live_claim_exists(records, plan_hash, plan_revision)
        if live is not None:
            return {
                "status": "refused",
                "reason": "live claim exists for (plan_hash, plan_revision)",
                "holder": {"run_label": live.get("run_label"), "state": live.get("state"),
                           "claim_token": live.get("claim_token")},
            }
        token = str(uuid.uuid4())
        rec = {
            "state": "claimed", "workflow": workflow, "plan_hash": plan_hash,
            "plan_revision": plan_revision, "run_label": run_label,
            "run_id": None, "args_sha256": args_sha256, "resumed_from": None,
            "claim_token": token, "at": at or _now_iso(),
        }
        _append_record(project_root, rec)
        return {"status": "claimed", "claim_token": token, "record": rec}


def executing(project_root: Path, workflow: str, plan_hash: str, plan_revision: int,
              run_label: str, run_id: str, resumed_from: Optional[str] = None,
              at: Optional[str] = None) -> Dict[str, Any]:
    rec = {
        "state": "executing", "workflow": workflow, "plan_hash": plan_hash,
        "plan_revision": plan_revision, "run_label": run_label,
        "run_id": run_id, "args_sha256": None, "resumed_from": resumed_from,
        "claim_token": None, "at": at or _now_iso(),
    }
    with _DispatchLock(project_root):
        _append_record(project_root, rec)
    return rec


def finish(project_root: Path, workflow: str, plan_hash: str, plan_revision: int,
           run_label: str, state: str, at: Optional[str] = None) -> Dict[str, Any]:
    if state not in TERMINAL_STATES:
        raise ValueError(f"finish state must be one of {TERMINAL_STATES}, got {state}")
    rec = {
        "state": state, "workflow": workflow, "plan_hash": plan_hash,
        "plan_revision": plan_revision, "run_label": run_label,
        "run_id": None, "args_sha256": None, "resumed_from": None,
        "claim_token": None, "at": at or _now_iso(),
    }
    with _DispatchLock(project_root):
        _append_record(project_root, rec)
    return rec


def audit_resume_across_revision(project_root: Path) -> List[Dict[str, Any]]:
    """Mechanically detect the 'no resume across amendment' violation: an
    `executing` line carrying `resumed_from` that appears AFTER a higher
    plan_revision line for the SAME plan_hash family (same run_label). Returns
    the list of offending records (empty = clean)."""
    records = _read_records(project_root)
    offenders: List[Dict[str, Any]] = []
    # Track the max plan_revision seen per run_label as we walk in append order.
    max_rev_by_label: Dict[str, int] = {}
    for r in records:
        label = r.get("run_label")
        rev = r.get("plan_revision", 0)
        prev_max = max_rev_by_label.get(label, -1)
        if r.get("state") == "executing" and r.get("resumed_from"):
            # A resume at a revision LOWER than one already seen for this label
            # means we resumed across an amendment (the plan was revised, then a
            # stale resume fired). prev_max > rev is the violation.
            if prev_max > rev:
                offenders.append(r)
        if rev > prev_max:
            max_rev_by_label[label] = rev
    return offenders


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _common_args(p):
    p.add_argument("--project-root", required=True)
    p.add_argument("--workflow", required=True)
    p.add_argument("--plan-hash", required=True)
    p.add_argument("--plan-revision", type=int, required=True)
    p.add_argument("--run-label", required=True)
    p.add_argument("--at", default=None)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="S055 workflow dispatch/receipts (main-loop sole writer).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("emit"); _common_args(pe)
    pc = sub.add_parser("claim"); _common_args(pc); pc.add_argument("--args-sha256", default=None)
    px = sub.add_parser("executing"); _common_args(px); px.add_argument("--run-id", required=True); px.add_argument("--resumed-from", default=None)
    pf = sub.add_parser("finish"); _common_args(pf); pf.add_argument("--state", required=True, choices=list(TERMINAL_STATES))
    pa = sub.add_parser("audit-resume-across-revision"); pa.add_argument("--project-root", required=True)

    args = ap.parse_args(argv)
    if args.cmd == "audit-resume-across-revision":
        offenders = audit_resume_across_revision(Path(args.project_root))
        if offenders:
            sys.stdout.write(json.dumps({"violations": offenders}) + "\n")
            return 3
        sys.stdout.write("clean\n")
        return 0

    pr = Path(args.project_root)
    if args.cmd == "emit":
        emit(pr, args.workflow, args.plan_hash, args.plan_revision, args.run_label, args.at)
        sys.stdout.write("emitted\n")
        return 0
    if args.cmd == "claim":
        res = claim(pr, args.workflow, args.plan_hash, args.plan_revision, args.run_label, args.args_sha256, args.at)
        if res["status"] == "claimed":
            sys.stdout.write(res["claim_token"] + "\n")
            return 0
        sys.stdout.write(f"REFUSED:{res['reason']}\n")
        return 3
    if args.cmd == "executing":
        executing(pr, args.workflow, args.plan_hash, args.plan_revision, args.run_label, args.run_id, args.resumed_from, args.at)
        sys.stdout.write("executing\n")
        return 0
    if args.cmd == "finish":
        finish(pr, args.workflow, args.plan_hash, args.plan_revision, args.run_label, args.state, args.at)
        sys.stdout.write(args.state + "\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
