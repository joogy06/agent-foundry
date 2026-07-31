#!/usr/bin/env python3
"""
write.py - process-observation writer + claude-observe CLI one-liner.

Public API (both importable + CLI):
    claude_observe(category, subject_id, what_happened, *, ...) -> None
        BEST-EFFORT; never raises; returns None.

    python3 write.py <category> "<what_happened>" [flags...]
        POSIX exit 0 always (even on swallowed failure).

Persistence layout (per project_root discovery):
    <project_root>/.process-observations/
        active.yaml                # aggregate keyed by dedup_key
        events.jsonl               # append-only truth log
        stale.yaml                 # demoted observations (compressed, indefinite)
        summaries/<YYYY-MM>.jsonl  # hashed monthly summaries (180d retained)
        .write.lock                # flock for active.yaml upsert
        .sweep.lock                # flock for sweep/rotation path
        .last_sweep                # 24h sentinel
    ~/.claude/state/observations.jsonl     # anonymized cross-project rollup

Design refs:
    docs/plans/2026-04-23-ecosystem-keystone-design.md section 4 (all subsections)
    Decisions D12-D16.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Cross-platform advisory locking (#249). `import fcntl` at module level made
# this module unimportable on Windows -- it died at IMPORT, not at use.
_META_DIR = Path(__file__).resolve().parents[2] / "_meta"
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))
from portable_lock import lock_exclusive, unlock  # noqa: E402


# Package-local import of trusted_runner.atomic_write_bytes. The skill is
# installed at ~/.claude/skills/process-observation/scripts/write.py; the
# shared _meta package lives at ~/.claude/skills/_meta/. We add _meta to
# sys.path at import time so `from trusted_runner import atomic_write_bytes`
# resolves without requiring a project-level PYTHONPATH tweak.
_META_DIR = Path(__file__).resolve().parent.parent.parent / "_meta"
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

try:
    from trusted_runner import atomic_write_bytes
except Exception:  # pragma: no cover - trusted_runner must exist in all envs
    # Last-resort fallback so tests can still import write.py when _meta is
    # unavailable. Implements the same semantic (tmp + fsync + replace).
    def atomic_write_bytes(path: Path, data: bytes) -> None:
        import tempfile
        path = Path(path)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, str(path))
        except BaseException:
            try:
                Path(tmp_name).unlink()
            except FileNotFoundError:
                pass
            raise

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_AGGREGATE = "process-observation.v1"
SCHEMA_EVENT = "observation-event.v1"

CLOSED_SET_CATEGORIES: Tuple[str, ...] = (
    "gate_false_block",
    "gate_false_pass",
    "skill_bug",
    "skill_incomplete",
    "agent_drift",
    "flow_gap",
    "schema_mismatch",
    "external_tool_fail",
    "external_tool_slow",
    "environment_limit",
    "context_overflow",
    "recursive_loop",
    "deprecation_surfaced",
)

CLOSED_SET_SEVERITIES: Tuple[str, ...] = ("blocking", "degraded", "slow", "noisy")

CLOSED_SET_SUBJECT_TYPES: Tuple[str, ...] = (
    "agent", "skill", "gate", "external_tool", "schema", "env",
)

EVIDENCE_TAIL_MAX = 10      # ring buffer length
SESSIONS_MAX = 20           # ring buffer length
WINDOW_7D_SECONDS = 7 * 24 * 3600
MAX_DEDUP_KEY_LEN = 120

GLOBAL_ROLLUP_PATH = Path.home() / ".claude" / "state" / "observations.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_dedup_key(category: str, subject_id: str,
                      fingerprint: Optional[str], what_happened: str) -> str:
    """Canonical dedup_key per design section 4.3."""
    if fingerprint is None:
        fingerprint = hashlib.sha256(what_happened.encode("utf-8")).hexdigest()[:8]
    key = f"{category}:{subject_id}:{fingerprint}"
    key = re.sub(r"[^a-z0-9:_-]", "-", key.lower())
    return key[:MAX_DEDUP_KEY_LEN]


def shape_only(text: str) -> str:
    """Anonymize free-form text for global rollup (design section 4.9).

    Ordering matters: canonicalize known URI schemes BEFORE the generic path
    regex so `task://43` becomes `task://<N>` and is not swallowed as
    an absolute path.
    """
    t = text
    # URI schemes first so their `//` prefix is consumed atomically.
    t = re.sub(r"task://\d+", "<T>task-N<T>", t)
    t = re.sub(r"uri://[^\s\"\']+", "<T>uri-R<T>", t)
    t = re.sub(r"file://[^\s\"\']+", "<T>file-R<T>", t)
    # Filesystem paths (leading slash, no scheme context preserved).
    t = re.sub(r"/[\w./-]+", "<path>", t)
    # Restore the placeholders in their canonical display form.
    t = t.replace("<T>task-N<T>", "task://<N>")
    t = t.replace("<T>uri-R<T>", "uri://<R>")
    t = t.replace("<T>file-R<T>", "file://<R>")
    # Long hex runs (UUIDs, git sha, sha256 prefix).
    t = re.sub(r"[0-9a-f]{8,}", "<hash>", t)
    # Quoted strings.
    t = re.sub(r'"[^"]*"', "<str>", t)
    return t[:160]


def anonymize_for_global(event: Dict[str, Any], project_root_abs: str) -> Dict[str, Any]:
    """Write-time anonymization per design section 4.9 (D15)."""
    subject = event.get("subject") or {}
    # Pre-scrub subject.id from the free-form what_happened so it cannot
    # leak into the shape-only signature.
    what = event.get("what_happened") or ""
    sid = subject.get("id") or ""
    if sid:
        # Word-boundary substitution so we do not accidentally rewrite
        # unrelated substrings. Escaped because ids are arbitrary strings.
        what = re.sub(r"\b" + re.escape(sid) + r"\b", "<subject>", what)
    return {
        "ts": event.get("ts"),
        "project_hash": hashlib.sha256(project_root_abs.encode("utf-8")).hexdigest()[:16],
        "session_hash": hashlib.sha256((event.get("session_id") or "").encode("utf-8")).hexdigest()[:12],
        "category": event.get("category"),
        "severity": event.get("severity"),
        "subject_type": subject.get("type"),
        "subject_version": subject.get("version_hash"),
        "what_shape": shape_only(what),
    }


# ---------------------------------------------------------------------------
# Project-root discovery + session id resolution
# ---------------------------------------------------------------------------

def discover_project_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from start (or cwd) looking for markers. Returns None on miss."""
    p = (start or Path.cwd()).resolve()
    while True:
        if (p / ".process-observations").is_dir():
            return p
        if (p / "PROJECT.md").is_file():
            return p
        if (p / ".git").is_dir():
            return p
        if p.parent == p:
            return None
        p = p.parent


def resolve_session_id(explicit: Optional[str] = None) -> str:
    """Session id resolution chain per design section 4.8."""
    if explicit:
        return explicit
    env_sid = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("FORGE_SESSION_ID")
    if env_sid:
        return env_sid
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        cache_dir = Path(runtime_dir) / "claude"
        cache_file = cache_dir / "session"
        try:
            if cache_file.is_file():
                cached = cache_file.read_text().strip()
                if cached:
                    return cached
            cache_dir.mkdir(parents=True, exist_ok=True)
            new_sid = f"session-{uuid.uuid4().hex[:12]}"
            cache_file.write_text(new_sid)
            return new_sid
        except Exception:
            pass
    return f"ppid-{os.getppid()}"


# ---------------------------------------------------------------------------
# Lock helpers (mirror claims.py._bob_claim_lock)
# ---------------------------------------------------------------------------

class _FlockCtx:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self) -> "_FlockCtx":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")  # never "w" -- truncates before locking
        lock_exclusive(self.fh)
        return self

    def __exit__(self, *exc):
        try:
            if self.fh is not None:
                unlock(self.fh)
        finally:
            if self.fh is not None:
                self.fh.close()


def write_lock(obs_dir: Path) -> _FlockCtx:
    return _FlockCtx(obs_dir / ".write.lock")


def sweep_lock(obs_dir: Path) -> _FlockCtx:
    return _FlockCtx(obs_dir / ".sweep.lock")


# ---------------------------------------------------------------------------
# active.yaml read / write helpers
# ---------------------------------------------------------------------------

def _empty_active_doc(project_id: str) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_AGGREGATE,
        "project_id": project_id,
        "generated_at": now_iso(),
        "observations": {},
    }


def load_active(obs_dir: Path, project_id: str) -> Dict[str, Any]:
    path = obs_dir / "active.yaml"
    if not path.is_file():
        return _empty_active_doc(project_id)
    try:
        if yaml is None:
            raise RuntimeError("pyyaml not installed")
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            return _empty_active_doc(project_id)
        doc.setdefault("schema", SCHEMA_AGGREGATE)
        doc.setdefault("project_id", project_id)
        doc.setdefault("observations", {})
        if not isinstance(doc["observations"], dict):
            doc["observations"] = {}
        return doc
    except Exception as e:
        sys.stderr.write(f"OBSERVATION_ACTIVE_LOAD_FAIL: {e}\n")
        return _empty_active_doc(project_id)


def dump_active(obs_dir: Path, doc: Dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("pyyaml not installed")
    doc["generated_at"] = now_iso()
    # Canonicalize key ordering (sort by dedup_key) so re-writes are stable.
    # pyyaml safe_dump cannot represent OrderedDict by default; build a plain
    # dict in sorted order (py3.7+ preserves insertion order).
    obs = doc.get("observations") or {}
    doc["observations"] = {k: obs[k] for k in sorted(obs.keys())}
    payload = yaml.safe_dump(doc, sort_keys=True, allow_unicode=True, default_flow_style=False)
    atomic_write_bytes(obs_dir / "active.yaml", payload.encode("utf-8"))


# ---------------------------------------------------------------------------
# Event append (lock-free O_APPEND)
# ---------------------------------------------------------------------------

def append_event_line(path: Path, record: Dict[str, Any]) -> None:
    """POSIX O_APPEND write of a single JSON line (<4KB -> atomic per POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (_canonical_json(record) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def append_global_rollup(event: Dict[str, Any], project_root_abs: str) -> None:
    try:
        GLOBAL_ROLLUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        anon = anonymize_for_global(event, project_root_abs)
        append_event_line(GLOBAL_ROLLUP_PATH, anon)
    except Exception as e:
        sys.stderr.write(f"OBSERVATION_ROLLUP_FAIL: {e}\n")


# ---------------------------------------------------------------------------
# Core upsert
# ---------------------------------------------------------------------------

def _build_event(
    *,
    dedup_key: str,
    category: str,
    severity: str,
    subject_type: str,
    subject_id: str,
    subject_version: Optional[str],
    session_id: str,
    observed_by: Optional[str],
    what_happened: str,
    related: Optional[List[str]],
    root_cause_hypothesis: Optional[str],
    suggested_fix: Optional[str],
) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_EVENT,
        "event_id": f"ev-{uuid.uuid4().hex[:10]}",
        "ts": now_iso(),
        "dedup_key": dedup_key,
        "session_id": session_id,
        "observed_by": observed_by or "claude-observe",
        "category": category,
        "severity": severity,
        "subject": {
            "type": subject_type,
            "id": subject_id,
            "version_hash": subject_version,
        },
        "what_happened": what_happened,
        "related": list(related or []),
        "root_cause_hypothesis": root_cause_hypothesis,
        "suggested_fix": suggested_fix,
    }


def _ring_append(lst: List[Any], item: Any, maxlen: int) -> List[Any]:
    lst = list(lst or [])
    lst.append(item)
    if len(lst) > maxlen:
        lst = lst[-maxlen:]
    return lst


def _recompute_count_last_7d(entry: Dict[str, Any], now_s: float) -> None:
    """Refresh count_last_7d from evidence_tail timestamps (best effort)."""
    tail = entry.get("evidence_tail") or []
    recent = 0
    for ev in tail:
        try:
            ts = parse_iso(ev["ts"]).timestamp()
            if now_s - ts <= WINDOW_7D_SECONDS:
                recent += 1
        except Exception:
            continue
    # count_last_7d cannot exceed count and should reflect recent fires even
    # when tail is thinner than 7d (rough approximation for query hot).
    entry["count_last_7d"] = min(entry.get("count", 0), max(recent, entry.get("count_last_7d", 0)))
    # Additionally increment when this call is within window (it always is —
    # we're recording a now-event). Capture the current event separately.


def upsert_active(doc: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Apply event to the aggregate. Returns the modified doc in place."""
    observations = doc.setdefault("observations", {})
    key = event["dedup_key"]
    now_s = parse_iso(event["ts"]).timestamp()
    entry = observations.get(key)
    evidence_event = {
        "event_id": event["event_id"],
        "ts": event["ts"],
        "session_id": event["session_id"],
        "observed_by": event["observed_by"],
        "severity": event["severity"],
    }
    if entry is None:
        entry = {
            "dedup_key": key,
            "category": event["category"],
            "severity": event["severity"],
            "subject": event["subject"],
            "first_seen": event["ts"],
            "last_seen": event["ts"],
            "count": 1,
            "count_last_7d": 1,
            "sessions": [event["session_id"]] if event["session_id"] else [],
            "what_happened": event["what_happened"],
            "root_cause_hypothesis": event.get("root_cause_hypothesis"),
            "suggested_fix": event.get("suggested_fix"),
            "status": "open",
            "resolution": None,
            "evidence_tail": [evidence_event],
            "related": list(event.get("related") or []),
            "promoted_to_task": None,
        }
    else:
        entry["last_seen"] = event["ts"]
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["sessions"] = _ring_append(entry.get("sessions", []), event["session_id"], SESSIONS_MAX)
        entry["evidence_tail"] = _ring_append(entry.get("evidence_tail", []), evidence_event, EVIDENCE_TAIL_MAX)
        # Refresh descriptive fields from latest non-empty event
        if event.get("what_happened"):
            entry["what_happened"] = event["what_happened"]
        if event.get("root_cause_hypothesis") is not None:
            entry["root_cause_hypothesis"] = event["root_cause_hypothesis"]
        if event.get("suggested_fix") is not None:
            entry["suggested_fix"] = event["suggested_fix"]
        # Severity: escalate to the worst seen in the cluster
        sev_order = {"noisy": 0, "slow": 1, "degraded": 2, "blocking": 3}
        cur_rank = sev_order.get(entry.get("severity"), 1)
        new_rank = sev_order.get(event["severity"], 1)
        if new_rank > cur_rank:
            entry["severity"] = event["severity"]
        # Merge related (deduped, preserves order)
        merged = list(entry.get("related") or [])
        for r in (event.get("related") or []):
            if r not in merged:
                merged.append(r)
        entry["related"] = merged
        # Refresh count_last_7d
        _recompute_count_last_7d(entry, now_s)
    # Always include the just-recorded event in count_last_7d
    entry["count_last_7d"] = max(entry.get("count_last_7d", 0), 1)
    observations[key] = entry
    return doc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def claude_observe(
    category: str,
    subject_id: str,
    what_happened: str,
    *,
    fingerprint: Optional[str] = None,
    subject_type: str = "agent",
    subject_version: Optional[str] = None,
    severity: str = "degraded",
    session_id: Optional[str] = None,
    related: Optional[List[str]] = None,
    root_cause_hypothesis: Optional[str] = None,
    suggested_fix: Optional[str] = None,
    observed_by: Optional[str] = None,
    dedup_key_override: Optional[str] = None,
    project_root_override: Optional[Path] = None,
) -> None:
    """BEST-EFFORT write of a single observation.

    Never raises. All failure modes log to stderr and return None.
    """
    try:
        # Self-referential guard: observation about process-observation itself
        # is logged to stderr only (prevents infinite loops during sweep/compact).
        if subject_id == "process-observation":
            sys.stderr.write(
                f"OBSERVATION_SELF_REFERENTIAL: category={category} "
                f"what={what_happened[:120]}\n"
            )
            return

        if category not in CLOSED_SET_CATEGORIES:
            sys.stderr.write(
                f"OBSERVATION_INVALID_CATEGORY: {category!r} "
                f"(expected one of {CLOSED_SET_CATEGORIES})\n"
            )
            return
        if severity not in CLOSED_SET_SEVERITIES:
            sys.stderr.write(f"OBSERVATION_INVALID_SEVERITY: {severity!r}\n")
            severity = "degraded"
        if subject_type not in CLOSED_SET_SUBJECT_TYPES:
            sys.stderr.write(f"OBSERVATION_INVALID_SUBJECT_TYPE: {subject_type!r}\n")
            subject_type = "agent"

        dedup_key = dedup_key_override or compute_dedup_key(
            category, subject_id, fingerprint, what_happened
        )
        sid = resolve_session_id(session_id)
        project_root = project_root_override or discover_project_root()
        if project_root is None:
            sys.stderr.write(
                "OBSERVATION_NO_PROJECT_ROOT: writing to global rollup only "
                f"(cwd={Path.cwd()})\n"
            )

        event = _build_event(
            dedup_key=dedup_key,
            category=category,
            severity=severity,
            subject_type=subject_type,
            subject_id=subject_id,
            subject_version=subject_version,
            session_id=sid,
            observed_by=observed_by,
            what_happened=what_happened,
            related=related,
            root_cause_hypothesis=root_cause_hypothesis,
            suggested_fix=suggested_fix,
        )

        if project_root is not None:
            obs_dir = project_root / ".process-observations"
            obs_dir.mkdir(parents=True, exist_ok=True)
            project_id = project_root.name

            # 1. Append event to events.jsonl (lock-free O_APPEND).
            try:
                append_event_line(obs_dir / "events.jsonl", event)
            except Exception as e:
                sys.stderr.write(f"OBSERVATION_EVENT_APPEND_FAIL: {e}\n")

            # 2. Upsert active.yaml under .write.lock.
            try:
                with write_lock(obs_dir):
                    doc = load_active(obs_dir, project_id)
                    doc = upsert_active(doc, event)
                    dump_active(obs_dir, doc)
            except Exception as e:
                sys.stderr.write(f"OBSERVATION_ACTIVE_UPSERT_FAIL: {e}\n")

            # 3. Global rollup (anonymized).
            append_global_rollup(event, str(project_root))
        else:
            # No project root -> rollup only.
            append_global_rollup(event, str(Path.cwd()))
    except BaseException as e:  # noqa: BLE001
        # Swallow EVERYTHING including KeyboardInterrupt propagating through.
        sys.stderr.write(f"OBSERVATION_WRITE_FAIL: {type(e).__name__}: {e}\n")
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_related(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-observe",
        description=(
            "Emit one BEST-EFFORT process-observation record. Never raises; "
            "exit 0 even on swallowed failure (stderr carries diagnostics)."
        ),
    )
    p.add_argument("category", help="one of 13 closed-set categories")
    p.add_argument("what_happened", help="free-form description of the friction")
    p.add_argument("--subject", default="unknown", help="subject.id (default: unknown)")
    p.add_argument(
        "--subject-type",
        default="agent",
        choices=CLOSED_SET_SUBJECT_TYPES,
        help="subject.type (default: agent)",
    )
    p.add_argument("--subject-version", default=None, help="subject.version_hash")
    p.add_argument(
        "--severity",
        default="degraded",
        choices=CLOSED_SET_SEVERITIES,
        help="severity (default: degraded)",
    )
    p.add_argument("--dedup-key", default=None, help="explicit dedup_key (bypass algorithm)")
    p.add_argument("--fingerprint", default=None, help="explicit fingerprint (else auto)")
    p.add_argument("--session", default=None, help="session_id (else from env)")
    p.add_argument("--root-cause", dest="root_cause", default=None)
    p.add_argument("--suggested-fix", dest="suggested_fix", default=None)
    p.add_argument("--related", default=None, help="comma-separated URIs")
    p.add_argument("--observed-by", default=None, help="source label (skill/gate/tool)")
    p.add_argument("--project-root", default=None, help="override project root discovery")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    claude_observe(
        category=ns.category,
        subject_id=ns.subject,
        what_happened=ns.what_happened,
        fingerprint=ns.fingerprint,
        subject_type=ns.subject_type,
        subject_version=ns.subject_version,
        severity=ns.severity,
        session_id=ns.session,
        related=_parse_related(ns.related),
        root_cause_hypothesis=ns.root_cause,
        suggested_fix=ns.suggested_fix,
        observed_by=ns.observed_by,
        dedup_key_override=ns.dedup_key,
        project_root_override=Path(ns.project_root) if ns.project_root else None,
    )
    # BEST-EFFORT: exit 0 regardless (failures are in stderr).
    return 0


if __name__ == "__main__":
    sys.exit(main())
