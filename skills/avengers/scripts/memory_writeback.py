#!/usr/bin/env python3
"""avengers — memory_writeback.py (WP-3).

The project-tier member-memory subsystem: admissibility, the HOME-TIER-ONLY
standing-memory loader, and the gated persist-for-later write-back (propose then
commit). Design §5/§6/§14.

Security spine (honest posture — see references/trust-boundary.md):
  * Member memory + ALL trusted state live under ~/.claude/ — NEVER repo-local.
    A repo-carried memory file is a pre-poisoned-clone vector that bypasses the
    write-back approval gate (the gate covers WRITES, not pre-existing files).
    The loader computes paths from the HOME tier only and REFUSES any member
    path that resolves outside ~/.claude/projects/<slug>/ (design §14).
  * Admissibility: a standing record is admissible ONLY from the four
    Codex-class source types, and NEVER when its kind is episodic (seat opinion,
    refuted position, single-session conclusion). Those anchor/tame contention.
  * Write-back is DEFAULT-REJECT, PER-ITEM. Proposals PERSIST home-tier for a
    later batch review; unattended runs never block and never silently discard.
    Commit = per-project lock + hash-snapshot + backup + re-check + atomic
    rename (wiki §5.0/§5.9 discipline). A record with no traceable source turn
    is refused — at draft time and re-checked at commit time.

OUT OF SCOPE for v1 (design §14 — enforced by ABSENCE, not by a flag): there is
NO global-memory-tier loader branch anywhere in this module. Only the project
tier exists. Global/cross-project memory is designed-for, not built.

Dependencies: Python stdlib only (json, os, fcntl, hashlib, shutil, tempfile).
PyYAML is NOT used here — all memory state is machine JSON. No network, executes
nothing from inputs.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_SKILL_ROOT = _HERE.parent
SCHEMA_PATH = _SKILL_ROOT / "schemas" / "memory-record.v1.schema.json"

# The four Codex-class admissible source types (design §6). A record whose
# provenance.source_type is not one of these is NOT standing memory.
ADMISSIBLE_SOURCE_TYPES = frozenset({
    "user_confirmed_constraint",
    "verified_project_artifact",
    "user_selected_decision",
    "observed_outcome",
})

# Explicit blocklist (defense in depth over the schema's kind enum). These are
# EPISODIC content — they anchor/tame contention and must never become standing
# memory (design §6). Named here so the refusal reason is human-legible even if a
# caller bypasses the JSON schema.
INADMISSIBLE_KINDS = frozenset({
    "seat_opinion",
    "refuted_position",
    "single_session_conclusion",
})

# Per-session write-back caps (design §6). PII profiles are throttled to 0-1.
MAX_CANDIDATES = 3
MAX_CANDIDATES_PII = 1


# --------------------------------------------------------------------------- #
# time / io helpers
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, text: str) -> None:
    """temp + fsync + rename in the SAME directory (design §5/§6 durability)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Mini JSON-schema validator (stdlib subset, mirrors convene.py so both modules
# validate identically without a third-party dependency):
# type/required/properties/items/enum/const/additionalProperties/minItems/minimum
# --------------------------------------------------------------------------- #
def _type_ok(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    return True


def schema_validate(instance: Any, schema: Dict[str, Any], path: str = "$",
                    errors: Optional[List[str]] = None) -> List[str]:
    if errors is None:
        errors = []
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(instance, tt) for tt in types):
            errors.append(f"{path}: expected type {t}, got {type(instance).__name__}")
            return errors
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property '{req}'")
        ap = schema.get("additionalProperties", True)
        for k, v in instance.items():
            if k in props:
                schema_validate(v, props[k], f"{path}.{k}", errors)
            elif ap is False:
                errors.append(f"{path}: additional property '{k}' not allowed")
            elif isinstance(ap, dict):
                schema_validate(v, ap, f"{path}.{k}", errors)
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: array has {len(instance)} items < minItems {schema['minItems']}")
        items = schema.get("items")
        if isinstance(items, dict):
            for i, it in enumerate(instance):
                schema_validate(it, items, f"{path}[{i}]", errors)
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
    return errors


def load_schema() -> Dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Admissibility (design §6)
# --------------------------------------------------------------------------- #
def check_admissible(record: Any) -> Tuple[bool, str]:
    """Return (ok, reason). A record is admissible as STANDING memory iff:
      1. it validates against memory-record.v1, AND
      2. provenance.source_type is one of the four Codex-class sources, AND
      3. its kind is NOT an episodic kind (seat opinion / refuted position /
         single-session conclusion).
    Fail-closed: any structural problem is a rejection, not a pass-through.
    """
    if not isinstance(record, dict):
        return False, f"record must be an object, got {type(record).__name__}"
    # Episodic-kind blocklist FIRST, so the three named inadmissible kinds get a
    # human-legible reason even though the schema's kind enum would also reject.
    kind = record.get("kind")
    if kind in INADMISSIBLE_KINDS:
        return False, (
            f"kind {kind!r} is EPISODIC (seat opinion / refuted position / "
            f"single-session conclusion) — not admissible as standing memory (§6)"
        )
    errs = schema_validate(record, load_schema())
    if errs:
        return False, "schema: " + "; ".join(errs)
    source_type = record.get("provenance", {}).get("source_type")
    if source_type not in ADMISSIBLE_SOURCE_TYPES:
        return False, (
            f"provenance.source_type {source_type!r} not in the four Codex-class "
            f"admissible sources {sorted(ADMISSIBLE_SOURCE_TYPES)}"
        )
    return True, "admissible"


# --------------------------------------------------------------------------- #
# Home-tier path resolution + the OUT-OF-SCOPE §14 guard
# --------------------------------------------------------------------------- #
def projects_root() -> Path:
    """The project-tier root: ~/.claude/projects (overridable ONLY via
    AVENGERS_PROJECTS_ROOT, a hermetic-test seam). There is NO global-tier
    branch — this is the sole memory tier (design §14)."""
    override = os.environ.get("AVENGERS_PROJECTS_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".claude" / "projects").resolve()


def project_slug(project_root: Path) -> str:
    """Claude Code path-to-slug convention: absolute path with '/' -> '-'."""
    return str(Path(project_root).resolve()).replace("/", "-")


def project_tier_dir(project_root: Path) -> Path:
    return projects_root() / project_slug(project_root) / "avengers"


def member_dir(project_root: Path, seat_id: str) -> Path:
    return project_tier_dir(project_root) / "members" / seat_id


def standing_path(project_root: Path, seat_id: str) -> Path:
    return member_dir(project_root, seat_id) / "standing.json"


def proposals_path(project_root: Path, session_id: str) -> Path:
    return project_tier_dir(project_root) / "proposals" / f"{session_id}.json"


def assert_home_tier_path(path: Path, project_root: Path) -> Path:
    """REFUSE any member-memory path that does not resolve strictly under
    ~/.claude/projects/<slug>/ (design §14). This catches, with one guard:
      * repo-local memory (a pre-poisoned-clone vector),
      * a global-tier path (~/.claude/memory/... — no such loader exists),
      * seat_id path-traversal (../../etc).
    Returns the resolved path on success; raises ValueError on refusal.
    """
    tier = (projects_root() / project_slug(project_root)).resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(tier)
    except ValueError:
        raise ValueError(
            f"REFUSED member-memory path {resolved} — outside the project tier "
            f"{tier}. Member memory is home-tier only; repo-local and global-tier "
            f"paths are never loaded (design §14)."
        )
    return resolved


# --------------------------------------------------------------------------- #
# Standing-memory loader (HOME-TIER ONLY)
# --------------------------------------------------------------------------- #
def load_standing_memory(project_root: Path, seat_id: str) -> List[Dict[str, Any]]:
    """Load a seat's ACTIVE, ADMISSIBLE standing records from the HOME tier only.

    Never reads a repo-local file: the path is derived from projects_root(), and
    assert_home_tier_path re-verifies it before any read. Inadmissible or
    non-active records that somehow reached the file are skipped (defense in
    depth), so a pre-poisoned file cannot smuggle episodic content into a prompt.
    Returns [] when the seat has no home-tier standing.json.
    """
    path = standing_path(project_root, seat_id)
    assert_home_tier_path(path, project_root)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("records", raw) if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise ValueError(f"standing.json at {path} must be a list (or {{records:[...]}})")
    out: List[Dict[str, Any]] = []
    for rec in records:
        ok, _reason = check_admissible(rec)
        if ok and rec.get("status") == "active":
            out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# Gated write-back — propose (persist-for-later) then commit (approved-only)
# --------------------------------------------------------------------------- #
def _candidate_eligible(cand: Any) -> Tuple[bool, str]:
    """A proposal candidate is eligible iff it names its member, carries a
    traceable source_turn, and its record is admissible. Fail-closed."""
    if not isinstance(cand, dict):
        return False, f"candidate must be an object, got {type(cand).__name__}"
    member = cand.get("member")
    if not member or not isinstance(member, str):
        return False, "candidate missing 'member' (seat_id)"
    source_turn = cand.get("source_turn")
    if not source_turn or not isinstance(source_turn, str):
        return False, "candidate has no traceable source_turn — refused (§6)"
    ok, reason = check_admissible(cand.get("record"))
    if not ok:
        return False, reason
    return True, "eligible"


def persist_proposals(
    project_root: Path,
    session_id: str,
    candidates: List[Dict[str, Any]],
    *,
    pii: bool = False,
    drafted_by: str = "chair",
) -> Dict[str, Any]:
    """Persist per-item DEFAULT-REJECT write-back proposals to the HOME tier at
    ~/.claude/projects/<slug>/avengers/proposals/<session-id>.json.

    Caps candidates (3, or 1 for PII profiles). Eligible candidates are recorded
    with decision 'rejected' (default-reject; a later review flips specific items
    to 'approved'). Ineligible candidates (untraceable source turn, inadmissible
    record) are NOT approvable — they land in 'refused' with a reason. Never
    writes repo-local. Returns the persisted proposal document.
    """
    cap = MAX_CANDIDATES_PII if pii else MAX_CANDIDATES
    if len(candidates) > cap:
        raise ValueError(
            f"{len(candidates)} candidates exceeds the per-session cap {cap} "
            f"({'PII profile' if pii else 'default'}) — the chair drafts <= cap (§6)"
        )
    proposed: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    for cand in candidates:
        ok, reason = _candidate_eligible(cand)
        if not ok:
            refused.append({"candidate": cand, "reason": reason})
            continue
        rec = dict(cand["record"])
        # Self-document origin: the committed record's provenance carries the
        # source turn so the review tool can print the source-turn excerpt (§5).
        prov = dict(rec.get("provenance", {}))
        refs = list(prov.get("source_refs", []))
        if cand["source_turn"] not in refs:
            refs.append(cand["source_turn"])
        prov["source_refs"] = refs
        rec["provenance"] = prov
        proposed.append({
            "member": cand["member"],
            "source_turn": cand["source_turn"],
            "decision": "rejected",          # default-reject, per-item
            "record": rec,
        })
    doc = {
        "schema": "memory-proposals.v1",
        "session_id": session_id,
        "drafted_by": drafted_by,
        "drafted_at": now_iso(),
        "pii_profile": pii,
        "cap": cap,
        "proposals": proposed,
        "refused": refused,
    }
    out = proposals_path(project_root, session_id)
    assert_home_tier_path(out, project_root)
    _atomic_write(out, json.dumps(doc, indent=2, sort_keys=False) + "\n")
    return doc


def _lock_dir(project_root: Path):
    """Per-project advisory lock (fcntl.flock) held for the commit critical
    section. Returns an open fd; caller closes it (which releases the lock)."""
    tier = project_tier_dir(project_root)
    tier.mkdir(parents=True, exist_ok=True)
    lock_path = tier / ".memory.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def commit_approved(
    project_root: Path,
    session_id: str,
    approvals: Dict[str, bool],
    *,
    approved_by: str,
    traceable_turns: Optional[set] = None,
) -> Dict[str, Any]:
    """Commit ONLY the explicitly-approved proposals into each member's home-tier
    standing.json. `approvals` maps a record id -> True to approve (default-reject:
    ids absent or mapped falsey are NOT committed).

    Commit discipline (design §6; wiki §5.0/§5.9): per-project lock -> hash
    snapshot -> backup -> re-check (admissibility + source-turn traceability) ->
    atomic rename. A record whose source_turn is not in `traceable_turns` is
    refused at commit even if approved. Returns {committed, refused, snapshots}.
    """
    prop_path = proposals_path(project_root, session_id)
    assert_home_tier_path(prop_path, project_root)
    if not prop_path.is_file():
        raise FileNotFoundError(f"no proposals persisted for session {session_id} at {prop_path}")
    doc = json.loads(prop_path.read_text(encoding="utf-8"))

    committed: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    snapshots: Dict[str, str] = {}
    lock_fd = _lock_dir(project_root)
    try:
        # Group approved-and-re-checked records by member.
        by_member: Dict[str, List[Dict[str, Any]]] = {}
        for prop in doc.get("proposals", []):
            rec = prop["record"]
            rid = rec.get("id")
            if not approvals.get(rid, False):
                continue  # default-reject: only explicit True commits
            ok, reason = check_admissible(rec)  # re-check (TOCTOU)
            if not ok:
                refused.append({"id": rid, "reason": f"re-check failed: {reason}"})
                continue
            st = prop.get("source_turn")
            if traceable_turns is not None and st not in traceable_turns:
                refused.append({"id": rid, "reason": f"source_turn {st!r} not traceable in transcript — refused (§6)"})
                continue
            rec = dict(rec)
            rec["approval"] = {"status": "approved", "by": approved_by, "at": now_iso()}
            rec["status"] = "active"
            by_member.setdefault(prop["member"], []).append(rec)

        for member, new_recs in by_member.items():
            path = standing_path(project_root, member)
            assert_home_tier_path(path, project_root)
            existing_text = path.read_text(encoding="utf-8") if path.is_file() else ""
            snapshots[member] = sha256_text(existing_text)          # hash snapshot
            if existing_text:
                shutil.copy2(str(path), str(path) + ".bak")         # backup
            existing = json.loads(existing_text) if existing_text else []
            if isinstance(existing, dict):
                existing = existing.get("records", [])
            have = {r.get("id") for r in existing}
            merged = list(existing)
            for rec in new_recs:
                if rec["id"] in have:
                    refused.append({"id": rec["id"], "reason": "id already present in standing.json"})
                    continue
                merged.append(rec)
                committed.append({"id": rec["id"], "member": member})
            _atomic_write(path, json.dumps(merged, indent=2, sort_keys=False) + "\n")  # atomic rename
    finally:
        os.close(lock_fd)  # releases the flock

    return {"committed": committed, "refused": refused, "snapshots": snapshots}


# --------------------------------------------------------------------------- #
# CLI (thin — inspection + review scaffolding)
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="avengers member-memory write-back (propose/commit)")
    ap.add_argument("--project-root", required=True, type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_load = sub.add_parser("show", help="print a seat's home-tier standing memory")
    p_load.add_argument("--seat", required=True)

    p_prop = sub.add_parser("propose", help="persist write-back proposals (home-tier)")
    p_prop.add_argument("--session-id", required=True)
    p_prop.add_argument("--candidates", required=True, type=Path, help="JSON file: [{member,source_turn,record}]")
    p_prop.add_argument("--pii", action="store_true")

    p_com = sub.add_parser("commit", help="commit approved proposals into standing.json")
    p_com.add_argument("--session-id", required=True)
    p_com.add_argument("--approvals", required=True, type=Path, help="JSON file: {record_id: true, ...}")
    p_com.add_argument("--by", required=True, help="approver identity")

    args = ap.parse_args(argv)
    if args.cmd == "show":
        recs = load_standing_memory(args.project_root, args.seat)
        sys.stdout.write(json.dumps(recs, indent=2) + "\n")
        return 0
    if args.cmd == "propose":
        cands = json.loads(args.candidates.read_text(encoding="utf-8"))
        doc = persist_proposals(args.project_root, args.session_id, cands, pii=args.pii)
        sys.stdout.write(f"persisted {len(doc['proposals'])} proposal(s), "
                         f"{len(doc['refused'])} refused -> {proposals_path(args.project_root, args.session_id)}\n")
        return 0
    if args.cmd == "commit":
        approvals = json.loads(args.approvals.read_text(encoding="utf-8"))
        res = commit_approved(args.project_root, args.session_id, approvals, approved_by=args.by)
        sys.stdout.write(f"committed {len(res['committed'])}, refused {len(res['refused'])}\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
