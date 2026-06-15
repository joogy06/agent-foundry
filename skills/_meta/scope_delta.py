#!/usr/bin/env python3
"""scope_delta.py — S029 scope_delta.v1 schema validation + ledger I/O.

Per design §7.1 / contracts.md CONTRACT-A2.

Storage: <project_root>/.ledger/scope-deltas/<delta_id>.yaml
  * Append-only audit log; records are NEVER deleted.
  * Atomic writes via .tmp+rename so a reader never sees a partial file.

Public API (stable across S029):
    new_delta_id(now: datetime | None = None) -> str
    write_record(project_root, record) -> Path
    read_records(project_root, status_filter=None) -> list[dict]
    update_status(project_root, delta_id, new_status, resolution=None) -> dict
    validate(record) -> None  (raises ValueError on failure)

The schema lives at ~/.claude/skills/_meta/schemas/scope_delta.v1.json.
We use a hand-rolled validator (no jsonschema dependency) so the module
works on minimal environments — same approach gates.py uses.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed.\n")
    sys.exit(3)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "scope_delta.v1"
ARTIFACT_KINDS = (
    "secret", "db_migration", "env_var", "public_api",
    "config_key", "generated_artifact", "file",
)
OPERATIONS = ("added", "removed", "changed")
SEVERITIES = ("critical", "advisory")
DETECTION_POINTS = ("wp_boundary", "integrated_to_verified")
STATUSES = ("undecided", "amended", "excluded")

DELTA_ID_RE = re.compile(
    r"^scope-delta-\d{4}-\d{2}-\d{2}T\d{2}(?::\d{2}:\d{2}|\d{4})Z-[0-9a-f]{6}$"
)
# Non-anchored variant for scanning arbitrary text (e.g. .ledger/deltas/ files);
# the anchored DELTA_ID_RE only matches a whole string. Same body, no ^/$.
DELTA_ID_RE_LOOSE = re.compile(
    r"scope-delta-\d{4}-\d{2}-\d{2}T\d{2}(?::\d{2}:\d{2}|\d{4})Z-[0-9a-f]{6}"
)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA256_PREFIXED_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso(now: Optional[datetime] = None) -> str:
    # ISO-8601 with colons. KEEP — used for the `created_at` record field
    # (and by gates.py), which must remain colon-bearing ISO-8601.
    n = now or datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_compact(now: Optional[datetime] = None) -> str:
    # Colon-free timestamp for minting filename-safe delta_ids: date dashes
    # are kept, only the time colons are removed (HH:MM:SS -> HHMMSS).
    n = now or datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H%M%SZ")


def _safe_filename(delta_id: str) -> str:
    """Map a logical delta_id to a colon-free physical filename stem.

    Colons are illegal in NTFS/FAT filenames; legacy delta_ids embed ISO-8601
    time colons. Stripping them is injective over valid delta_ids (fixed-position
    HH:MM:SS) and idempotent (a colon-free id maps to itself)."""
    return delta_id.replace(":", "")


def new_delta_id(now: Optional[datetime] = None) -> str:
    """Mint a fresh delta_id. Deterministic only when ``now`` is supplied.

    Colon-free by construction (uses ``_now_compact``) so the logical id can be
    used verbatim as a Windows-safe filename stem; ``_safe_filename`` is the
    idempotent identity on such ids.
    """
    return f"scope-delta-{_now_compact(now)}-{secrets.token_hex(3)}"


def _scope_deltas_dir(project_root: Path) -> Path:
    return project_root / ".ledger" / "scope-deltas"


def _atomic_write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(yaml.safe_dump(data, sort_keys=True))
    os.replace(str(tmp), str(path))


# ---------------------------------------------------------------------------
# Schema validation (hand-rolled to keep dependencies minimal)
# ---------------------------------------------------------------------------


REQUIRED_FIELDS = (
    "delta_id", "schema_version", "created_at", "created_by",
    "project_root", "contract_map_hash", "contract_map_revision",
    "artifact_kind", "operation", "path", "severity",
    "requesting_wp", "detection_point", "status",
)

ALLOWED_FIELDS = set(REQUIRED_FIELDS) | {
    "content_hash", "contract_ref", "consumer_refs",
    "critical_reason", "resolution", "extractor_meta",
}


def validate(record: Dict[str, Any]) -> None:
    """Raise ValueError if record fails scope_delta.v1 schema."""
    if not isinstance(record, dict):
        raise ValueError("record must be a dict")
    # Required fields present
    for f in REQUIRED_FIELDS:
        if f not in record:
            raise ValueError(f"missing required field: {f}")
    # Disallowed fields
    extra = set(record.keys()) - ALLOWED_FIELDS
    if extra:
        raise ValueError(f"unknown fields: {sorted(extra)}")
    # Field-level checks
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    if not DELTA_ID_RE.match(record["delta_id"]):
        raise ValueError(f"delta_id format invalid: {record['delta_id']}")
    if not ISO_RE.match(record["created_at"]):
        raise ValueError(f"created_at format invalid: {record['created_at']}")
    if not isinstance(record["created_by"], str) or not record["created_by"]:
        raise ValueError("created_by must be a non-empty string")
    if not SHA256_PREFIXED_RE.match(record["contract_map_hash"]):
        raise ValueError("contract_map_hash must be sha256:<64-hex>")
    if not isinstance(record["contract_map_revision"], int) or record["contract_map_revision"] < 0:
        raise ValueError("contract_map_revision must be non-negative int")
    if record["artifact_kind"] not in ARTIFACT_KINDS:
        raise ValueError(f"artifact_kind must be one of {ARTIFACT_KINDS}")
    if record["operation"] not in OPERATIONS:
        raise ValueError(f"operation must be one of {OPERATIONS}")
    if not isinstance(record["path"], str) or not record["path"]:
        raise ValueError("path must be non-empty string")
    if record["severity"] not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    if record["detection_point"] not in DETECTION_POINTS:
        raise ValueError(f"detection_point must be one of {DETECTION_POINTS}")
    if record["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if not isinstance(record["requesting_wp"], str) or not record["requesting_wp"]:
        raise ValueError("requesting_wp must be non-empty string")
    # Optional fields
    ch = record.get("content_hash")
    if ch is not None and not SHA256_RE.match(ch):
        raise ValueError(f"content_hash must be 64-hex or null: {ch!r}")
    if "consumer_refs" in record:
        if not isinstance(record["consumer_refs"], list):
            raise ValueError("consumer_refs must be a list")
    if "extractor_meta" in record:
        if not isinstance(record["extractor_meta"], dict):
            raise ValueError("extractor_meta must be a dict")


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def write_record(project_root: Path, record: Dict[str, Any]) -> Path:
    """Atomic .tmp+rename to .ledger/scope-deltas/<delta_id>.yaml.

    Raises:
        ValueError: if record fails schema validation.
    Returns:
        Path to the written YAML file.
    """
    validate(record)
    out_dir = _scope_deltas_dir(project_root)
    path = out_dir / f"{_safe_filename(record['delta_id'])}.yaml"
    if path.exists():
        # Append-only — never overwrite.
        raise FileExistsError(f"scope_delta already exists: {path}")
    _atomic_write_yaml(path, record)
    return path


def read_records(
    project_root: Path,
    status_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List all scope_delta records in the project's .ledger/scope-deltas dir.

    Args:
        status_filter: if provided, only records with status==status_filter.
    Returns:
        List of records, sorted by delta_id (which is timestamp-prefixed).
    """
    if status_filter is not None and status_filter not in STATUSES:
        raise ValueError(f"status_filter must be one of {STATUSES}")
    out_dir = _scope_deltas_dir(project_root)
    if not out_dir.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    # Post-migration all filenames are uniformly colon-free, so the lexical
    # sort over the glob stays chronological (the colon-stripped time still
    # sorts in the same order as the original HH:MM:SS within a given second).
    for p in sorted(out_dir.glob("scope-delta-*.yaml")):
        try:
            data = yaml.safe_load(p.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        if status_filter and data.get("status") != status_filter:
            continue
        out.append(data)
    return out


def update_status(
    project_root: Path,
    delta_id: str,
    new_status: str,
    resolution: Optional[str] = None,
) -> Dict[str, Any]:
    """Mutate a scope_delta record's status (and optional resolution).

    Idempotent: writing the same status twice is allowed (no-op).
    Atomic: rewrites the file via .tmp+rename.

    Returns the updated record.
    """
    if new_status not in STATUSES:
        raise ValueError(f"new_status must be one of {STATUSES}")
    path = _scope_deltas_dir(project_root) / f"{_safe_filename(delta_id)}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"scope_delta not found: {delta_id}")
    record = yaml.safe_load(path.read_text())
    record["status"] = new_status
    if resolution is not None:
        record["resolution"] = resolution
    validate(record)
    _atomic_write_yaml(path, record)
    return record


# ---------------------------------------------------------------------------
# Status-aware retention / compaction (Part B, design §B)
# ---------------------------------------------------------------------------


def _ledger_deltas_referenced_ids(project_root: Path) -> set:
    """Collect every delta_id referenced by any file under .ledger/deltas/.

    These are the IDs the amendment machinery (delta_event.v1) records when a
    scope-delta is resolved into the contract map. A referenced record is kept
    indefinitely even if its status string were somehow still `undecided`.

    Matches the colon-bearing logical delta_id form; `_safe_filename` maps it
    back to the physical file. Mirrors the purge script's keep-set logic so the
    two stay consistent.
    """
    deltas_dir = project_root / ".ledger" / "deltas"
    refs: set = set()
    if not deltas_dir.is_dir():
        return refs
    for f in sorted(deltas_dir.rglob("*")):
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in DELTA_ID_RE_LOOSE.finditer(text):
            refs.add(m.group(0))
    return refs


def _archive_dir(project_root: Path) -> Path:
    return project_root / ".ledger" / "scope-deltas-archive"


def compact_ledger(
    project_root: Path,
    undecided_max_age_days: int = 30,
    apply: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Status-aware retention sweep for .ledger/scope-deltas/ (design §B).

    Policy:
      * KEEP indefinitely: all `amended` / `excluded` records, plus any record
        whose delta_id is referenced by a file under .ledger/deltas/.
      * COMPACT: `undecided` records whose `created_at` is older than
        `undecided_max_age_days` — append a summary to
        .ledger/scope-deltas-archive/compact-<date>.json, then remove the file.
      * KEEP: `undecided` records younger than the threshold (live pending).

    Dry-run by default (`apply=False`): computes and returns the plan without
    mutating anything. `apply=True` writes the archive summary and removes the
    compacted files (os.remove — NOT git rm; the going-forward sweep is for
    accumulated noise and the git history is the recoverable record).

    Conservative by construction: resolved and referenced records are NEVER
    removed. Idempotent: a second run with the same clock finds nothing newly
    stale among what remains.

    Returns a plan dict:
      {compacted_count, compacted_delta_ids[], kept_count, archive_path|None,
       applied, threshold_days, cutoff_iso}
    """
    n = now or datetime.now(timezone.utc)
    cutoff = n - _timedelta_days(undecided_max_age_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    referenced = _ledger_deltas_referenced_ids(project_root)
    records = read_records(project_root)

    to_compact: List[Dict[str, Any]] = []
    kept = 0
    for rec in records:
        did = rec.get("delta_id")
        status = rec.get("status")
        if status in ("amended", "excluded") or did in referenced:
            kept += 1
            continue
        if status != "undecided":
            # Defensive: unknown status — keep (never remove what we don't model).
            kept += 1
            continue
        created_at = rec.get("created_at", "")
        if _is_older_than(created_at, cutoff):
            to_compact.append(rec)
        else:
            kept += 1

    plan: Dict[str, Any] = {
        "compacted_count": len(to_compact),
        "compacted_delta_ids": [r.get("delta_id") for r in to_compact],
        "kept_count": kept,
        "archive_path": None,
        "applied": bool(apply),
        "threshold_days": undecided_max_age_days,
        "cutoff_iso": cutoff_iso,
    }

    if not apply or not to_compact:
        return plan

    # Apply: write archive summary, then remove the compacted record files.
    archive_dir = _archive_dir(project_root)
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = n.strftime("%Y-%m-%d")
    archive_path = archive_dir / f"compact-{date_stamp}.json"

    summary = {
        "generated_at": n.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "threshold_days": undecided_max_age_days,
        "cutoff_iso": cutoff_iso,
        "compacted_count": len(to_compact),
        "compacted_delta_ids": [r.get("delta_id") for r in to_compact],
        "by_status": {"undecided": len(to_compact)},
        "compacted_paths": [r.get("path") for r in to_compact],
    }
    # Merge with an existing same-day archive (multiple sweeps in one day).
    if archive_path.exists():
        try:
            prev = json.loads(archive_path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                prev_ids = list(prev.get("compacted_delta_ids", []))
                prev_paths = list(prev.get("compacted_paths", []))
                summary["compacted_delta_ids"] = prev_ids + summary["compacted_delta_ids"]
                summary["compacted_paths"] = prev_paths + summary["compacted_paths"]
                summary["compacted_count"] = len(summary["compacted_delta_ids"])
                summary["by_status"] = {"undecided": summary["compacted_count"]}
        except (OSError, ValueError):
            pass

    tmp = archive_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(archive_path))

    out_dir = _scope_deltas_dir(project_root)
    for rec in to_compact:
        did = rec.get("delta_id")
        if not did:
            continue
        p = out_dir / f"{_safe_filename(did)}.yaml"
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    plan["archive_path"] = str(archive_path)
    return plan


def _timedelta_days(days: int):
    from datetime import timedelta
    return timedelta(days=days)


def _is_older_than(created_at: str, cutoff: datetime) -> bool:
    """True iff `created_at` (ISO-8601 with trailing Z) is strictly older than
    `cutoff`. A missing/unparseable timestamp is treated as NOT older (kept) —
    we never remove a record we cannot date."""
    if not created_at:
        return False
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return False
    return dt < cutoff


# ---------------------------------------------------------------------------
# CLI (small status helper; bob/forge call functions directly)
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        sys.stderr.write(
            "usage: scope_delta.py status|list|compact [--project-root <dir>] "
            "[--status <s>] [--max-age-days N] [--apply]\n"
        )
        sys.exit(2)
    cmd = argv[1]
    project_root = Path(os.getcwd())
    status_filter: Optional[str] = None
    max_age_days = 30
    apply_flag = False
    i = 2
    while i < len(argv):
        if argv[i] == "--project-root":
            project_root = Path(argv[i + 1]); i += 2
        elif argv[i] == "--status":
            status_filter = argv[i + 1]; i += 2
        elif argv[i] == "--max-age-days":
            max_age_days = int(argv[i + 1]); i += 2
        elif argv[i] == "--apply":
            apply_flag = True; i += 1
        else:
            i += 1
    if cmd in ("status", "list"):
        records = read_records(project_root, status_filter=status_filter)
        for rec in records:
            print(
                f"{rec['delta_id']}\t{rec['severity']}\t{rec['artifact_kind']}\t"
                f"{rec['status']}\t{rec['path']}"
            )
        if cmd == "status":
            print(f"# total={len(records)}")
    elif cmd == "compact":
        plan = compact_ledger(
            project_root,
            undecided_max_age_days=max_age_days,
            apply=apply_flag,
        )
        mode = "APPLY" if plan["applied"] else "DRY-RUN"
        print(
            f"# compact {mode}: would_compact={plan['compacted_count']} "
            f"kept={plan['kept_count']} threshold_days={plan['threshold_days']} "
            f"cutoff={plan['cutoff_iso']}"
        )
        for did in plan["compacted_delta_ids"]:
            verb = "compacted" if plan["applied"] else "would-compact"
            print(f"{verb}\t{did}")
        if plan["archive_path"]:
            print(f"# archive: {plan['archive_path']}")
    else:
        sys.stderr.write(f"unknown command: {cmd}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
