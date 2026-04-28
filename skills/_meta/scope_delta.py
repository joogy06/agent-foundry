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
    r"^scope-delta-\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z-[0-9a-f]{6}$"
)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA256_PREFIXED_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso(now: Optional[datetime] = None) -> str:
    n = now or datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_delta_id(now: Optional[datetime] = None) -> str:
    """Mint a fresh delta_id. Deterministic only when ``now`` is supplied."""
    return f"scope-delta-{_now_iso(now)}-{secrets.token_hex(3)}"


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
    path = out_dir / f"{record['delta_id']}.yaml"
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
    path = _scope_deltas_dir(project_root) / f"{delta_id}.yaml"
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
# CLI (small status helper; bob/forge call functions directly)
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        sys.stderr.write(
            "usage: scope_delta.py status|list [--project-root <dir>] [--status <s>]\n"
        )
        sys.exit(2)
    cmd = argv[1]
    project_root = Path(os.getcwd())
    status_filter: Optional[str] = None
    i = 2
    while i < len(argv):
        if argv[i] == "--project-root":
            project_root = Path(argv[i + 1]); i += 2
        elif argv[i] == "--status":
            status_filter = argv[i + 1]; i += 2
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
    else:
        sys.stderr.write(f"unknown command: {cmd}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
