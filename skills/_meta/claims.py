#!/usr/bin/env python3
"""
claims.py — Bob-owned leased claim subsystem.

Implements the per-component generation, leased-claim protocol from spec section 8.4.
The CB1 fix (per-component generation counters, not global revision) and the CB4 fix
(bob is the sole claim issuer) live here.

Public API:
    issue_claim(wp_id, invoking_skill, project_root) -> dict
    verify_claim_on_transition(request, ledger_path) -> bool
    heartbeat_claim(claim_uuid, project_root) -> str  ('ok'|'stale'|'expired'|'revoked')
    recover_claims(project_root) -> None
    purge_claims_for_wp(claims_dir, wp_id) -> int
    find_active_claims_for_wp(claims_dir, wp_id, skill) -> list[dict]
    classify_claim(claim, ledger_path) -> str  ('ok'|'stale'|'expired'|'revoked')

Phase 1 additions (tester-split design §5.4):
    open_verification_request(project_root, ...) -> dict
    mark_verification_request_status(project_root, request_id, status) -> dict
    consume_verdict(project_root, request_id, verdict) -> tuple[str, dict]

CLI:
    python -m claims issue <wp_id> <skill> [--project-root <dir>]
    python -m claims heartbeat <claim_uuid> [--project-root <dir>]
    python -m claims recover [--project-root <dir>]
    python -m claims status <claim_uuid> [--project-root <dir>]

Concurrency model: bob is the sole writer. Skills only READ claim files, and only
echo back the claim_uuid token in transition requests. The lease_until + heartbeat
protocol ensures crashed claimants do not block forward progress.

Provenance: spec section 8.4. Critical invariants enforced: CB1, CB4.
Phase 1 additions live alongside the existing claim subsystem; see
tester-split design §5.4–§5.7. Rollback per design §8 = remove the new
helpers; existing call sites are untouched (signatures preserved).
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed. claims.py requires pyyaml.\n")
    sys.exit(3)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LEASE_SECONDS = 600  # 10 minutes
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60

# Required minimum stage by skill — gates G3 enforces dependencies are at >= this stage.
REQUIRED_STAGES_BY_SKILL: Dict[str, str] = {
    "sample-data-scaffolding": "PLANNED",
    "integration-flow-testing": "UNIT_TESTED",
    "component-contract-mapping": "PLANNED",
}

STAGE_ORDER = [
    "PLANNED", "SCAFFOLDED", "UNIT_TESTED",
    "INTEGRATED", "VERIFIED", "DOCUMENTED",
]


def stage_order(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso_plus(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Atomic file write
# ---------------------------------------------------------------------------


def atomic_write(path: Path, content: str) -> None:
    """Atomic write via tmp + rename. Caller holds the lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{int(datetime.now().timestamp() * 1e6)}")
    tmp.write_text(content)
    os.replace(str(tmp), str(path))


# ---------------------------------------------------------------------------
# Minimal ledger reader for per-component generations
# ---------------------------------------------------------------------------


class LedgerRow:
    def __init__(self, wp: str, component: str, stage: str, generation: int, deps: List[str]) -> None:
        self.wp = wp
        self.component = component
        self.stage = stage
        self.generation = generation
        self.deps = deps


class Ledger:
    """Minimal ledger projection — header + projection table rows."""
    def __init__(self, header: Dict[str, Any], rows: List[LedgerRow]) -> None:
        self.header = header
        self.rows = rows
        self._by_wp: Dict[str, LedgerRow] = {r.wp: r for r in rows}
        self._by_component: Dict[str, LedgerRow] = {r.component: r for r in rows}

    def row(self, key: str) -> Optional[LedgerRow]:
        if key in self._by_wp:
            return self._by_wp[key]
        if key in self._by_component:
            return self._by_component[key]
        return None


_ROW_RE = re.compile(
    r"^\|\s*(?P<wp>[A-Za-z0-9_-]+)\s*\|"
    r"\s*(?P<component>[A-Za-z0-9_-]+)\s*\|"
    r"\s*(?P<stage>[A-Z_]+)\s*\|"
    r"\s*(?P<gen>\d+)\s*\|"
    r"\s*(?P<deps>[^|]*)\|"
)


def read_ledger(ledger_path: Path) -> Ledger:
    if not ledger_path.is_file():
        return Ledger({}, [])
    text = ledger_path.read_text()
    header: Dict[str, Any] = {}
    if text.startswith("---"):
        end = text.find("\n---", 4)
        if end != -1:
            try:
                header = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                header = {}
    rows: List[LedgerRow] = []
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if m and m.group("wp") not in ("WP", "----"):
            deps_raw = m.group("deps").strip()
            deps = [d.strip() for d in deps_raw.split(",") if d.strip() and d.strip() != "—"]
            rows.append(LedgerRow(
                wp=m.group("wp"),
                component=m.group("component"),
                stage=m.group("stage"),
                generation=int(m.group("gen")),
                deps=deps,
            ))
    return Ledger(header, rows)


# ---------------------------------------------------------------------------
# File-locked claim issuance
# ---------------------------------------------------------------------------


def _bob_claim_lock(project_root: Path):
    """Context manager: acquire fcntl lock on .ledger/claims/.lock for serialization."""
    class _Lock:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.fh = None

        def __enter__(self) -> "_Lock":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(self.path, "w")
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
            return self

        def __exit__(self, *exc) -> None:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()

    return _Lock(project_root / ".ledger" / "claims" / ".lock")


def find_active_claims_for_wp(claims_dir: Path, wp_id: str, skill: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all claim records for the given WP (and optionally skill)."""
    out: List[Dict[str, Any]] = []
    if not claims_dir.is_dir():
        return out
    for f in claims_dir.glob("*.claim.yaml"):
        try:
            claim = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        if claim.get("wp") != wp_id:
            continue
        if skill is not None and claim.get("skill") != skill:
            continue
        if claim.get("revoked"):
            continue
        out.append(claim)
    return out


def purge_claims_for_wp(claims_dir: Path, wp_id: str) -> int:
    """Delete all claim files for the given WP. Returns count purged."""
    n = 0
    if not claims_dir.is_dir():
        return 0
    for f in claims_dir.glob("*.claim.yaml"):
        try:
            claim = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        if claim.get("wp") == wp_id:
            f.unlink(missing_ok=True)
            n += 1
    return n


def classify_claim(claim: Dict[str, Any], ledger_path: Path) -> str:
    """Return one of 'ok' | 'stale' | 'expired' | 'revoked'."""
    if claim.get("revoked"):
        return "revoked"
    if claim.get("stale"):
        return "stale"
    lease_until = claim.get("lease_until")
    if not lease_until or now_iso() > lease_until:
        return "expired"
    # Check pinned generations against ledger
    expected = claim.get("expected_generations") or {}
    if expected:
        ledger = read_ledger(ledger_path)
        for dep_id, expected_gen in expected.items():
            row = ledger.row(dep_id)
            if row is None or row.generation != expected_gen:
                return "stale"
    return "ok"


def issue_claim(
    wp_id: str,
    invoking_skill: str,
    project_root: Path,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Dict[str, Any]:
    """Bob issues a new claim for the WP+skill combination.

    Bob is the sole writer; this function MUST only be called from bob.
    Returns the claim record dict including the opaque claim_uuid that the
    skill echoes back on its transition request.
    """
    project_root = project_root.resolve()
    claims_dir = project_root / ".ledger" / "claims"
    ledger_path = project_root / "progress" / "integration-ledger.md"

    with _bob_claim_lock(project_root):
        # Purge any pre-existing claim for this WP — bob serializes per-WP issuance.
        purge_claims_for_wp(claims_dir, wp_id)

        ledger = read_ledger(ledger_path)
        row = ledger.row(wp_id)
        if row is None:
            raise RuntimeError(f"WP {wp_id!r} not in ledger")

        required_min = REQUIRED_STAGES_BY_SKILL.get(invoking_skill, "PLANNED")
        expected_generations: Dict[str, int] = {}
        for dep in row.deps:
            dep_row = ledger.row(dep)
            if dep_row is None:
                raise RuntimeError(f"dep {dep!r} not in ledger")
            if stage_order(dep_row.stage) < stage_order(required_min):
                raise RuntimeError(
                    f"dep {dep!r} at {dep_row.stage}, need >= {required_min}"
                )
            expected_generations[dep] = dep_row.generation

        claim = {
            "claim_uuid": str(uuid.uuid4()),
            "wp": wp_id,
            "skill": invoking_skill,
            "issued_by": "bob",
            "issued_at": now_iso(),
            "lease_until": now_iso_plus(lease_seconds),
            "last_heartbeat": now_iso(),
            "expected_generations": expected_generations,
            "stale": False,
            "revoked": False,
        }
        claim_path = claims_dir / f"{claim['claim_uuid']}.claim.yaml"
        atomic_write(claim_path, yaml.safe_dump(claim, sort_keys=True))
        return claim


def verify_claim_on_transition(request: Dict[str, Any], ledger_path: Path) -> bool:
    """Bob calls this when a skill submits a transition request.

    Looks up the claim by UUID, checks lease/staleness/generation pins,
    returns True only if all checks pass.
    """
    uuid_str = request.get("claim_uuid")
    if not uuid_str:
        return False
    project_root = ledger_path.parent.parent
    claim_path = project_root / ".ledger" / "claims" / f"{uuid_str}.claim.yaml"
    if not claim_path.is_file():
        return False
    try:
        claim = yaml.safe_load(claim_path.read_text()) or {}
    except yaml.YAMLError:
        return False
    return classify_claim(claim, ledger_path) == "ok"


def heartbeat_claim(claim_uuid: str, project_root: Path) -> str:
    """Skill calls this periodically. Returns 'ok'|'stale'|'expired'|'revoked'.

    On 'ok', the lease is extended. On any other state, the skill MUST stop
    work and report back to bob — bob will issue a fresh claim if appropriate.
    """
    project_root = project_root.resolve()
    claim_path = project_root / ".ledger" / "claims" / f"{claim_uuid}.claim.yaml"
    if not claim_path.is_file():
        return "expired"
    with _bob_claim_lock(project_root):
        try:
            claim = yaml.safe_load(claim_path.read_text()) or {}
        except yaml.YAMLError:
            return "expired"
        ledger_path = project_root / "progress" / "integration-ledger.md"
        state = classify_claim(claim, ledger_path)
        if state == "ok":
            claim["last_heartbeat"] = now_iso()
            claim["lease_until"] = now_iso_plus(DEFAULT_LEASE_SECONDS)
            atomic_write(claim_path, yaml.safe_dump(claim, sort_keys=True))
        elif state == "stale":
            # Persist the stale flag so subsequent reads see it
            claim["stale"] = True
            atomic_write(claim_path, yaml.safe_dump(claim, sort_keys=True))
        return state


def mark_stale_claims(project_root: Path) -> int:
    """Walk all claims and mark those whose pinned generations no longer match.

    Called by bob after applying a transition that bumps a component generation.
    Returns count marked stale.
    """
    project_root = project_root.resolve()
    claims_dir = project_root / ".ledger" / "claims"
    ledger_path = project_root / "progress" / "integration-ledger.md"
    if not claims_dir.is_dir():
        return 0
    ledger = read_ledger(ledger_path)
    n = 0
    with _bob_claim_lock(project_root):
        for f in claims_dir.glob("*.claim.yaml"):
            try:
                claim = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError:
                continue
            if claim.get("revoked") or claim.get("stale"):
                continue
            for dep_id, expected_gen in (claim.get("expected_generations") or {}).items():
                row = ledger.row(dep_id)
                if row is None or row.generation != expected_gen:
                    claim["stale"] = True
                    atomic_write(f, yaml.safe_dump(claim, sort_keys=True))
                    n += 1
                    break
    return n


def recover_claims(project_root: Path) -> Tuple[int, int]:
    """On bob startup: purge expired/revoked claims; mark stale those with pinned gens that no longer match.

    Returns (purged_count, stale_count).
    """
    project_root = project_root.resolve()
    claims_dir = project_root / ".ledger" / "claims"
    ledger_path = project_root / "progress" / "integration-ledger.md"
    purged = 0
    stale = 0
    if not claims_dir.is_dir():
        return (0, 0)
    ledger = read_ledger(ledger_path)
    with _bob_claim_lock(project_root):
        for f in claims_dir.glob("*.claim.yaml"):
            try:
                claim = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError:
                f.unlink(missing_ok=True)
                purged += 1
                continue
            if claim.get("revoked"):
                f.unlink(missing_ok=True)
                purged += 1
                continue
            lease_until = claim.get("lease_until")
            if not lease_until or now_iso() > lease_until:
                f.unlink(missing_ok=True)
                purged += 1
                continue
            for dep_id, expected_gen in (claim.get("expected_generations") or {}).items():
                row = ledger.row(dep_id)
                if row is None or row.generation != expected_gen:
                    claim["stale"] = True
                    atomic_write(f, yaml.safe_dump(claim, sort_keys=True))
                    stale += 1
                    break
    return (purged, stale)


# ---------------------------------------------------------------------------
# S029 thin wrapper — request_scope_pause
# ---------------------------------------------------------------------------
#
# Provides a stable claims-module entrypoint for bob's Step 4.6 (S029 design
# §10). Delegates to scope_reaction.handle, which is the FIRST and ONLY
# production caller of pause_state.request_pause (CB4 preserved — only bob
# orchestrates the freeze-the-world cycle).
#
# WP-7 (spawn 4) bob.md will invoke `claims.request_scope_pause(project_root)`
# whenever G_CONTRACT_SCOPE exits non-zero with critical undecided records.


def request_scope_pause(project_root: Path) -> Dict[str, Any]:
    """Thin shim over scope_reaction.handle. Bob-only caller.

    Returns the structured summary from scope_reaction (epoch, counts,
    delta_ids). Triggers pause_state.request_pause once per critical
    undecided record; advisory records are NOT acted upon.
    """
    # Lazy import: keep the claims module import-time cost low.
    from importlib import import_module
    scope_reaction = import_module("scope_reaction")
    return scope_reaction.handle(project_root)


# ---------------------------------------------------------------------------
# Phase 1 additions — verification request lifecycle (tester-split §5.4)
# ---------------------------------------------------------------------------
#
# Verification requests are bob-owned coordination records that pin a single
# attempt at having an external verifier (audit_spawn.py today; the new
# verification-arbiter in Phase 2) review a sanitized evidence bundle.
#
# Per design §5.3 a verdict is only honored when the full 8-tuple of
# request_id, attempt_id, prior_state_version, bundle_hash, plan_hash,
# inventory_hash, runner_version, rubric_version is echoed back unchanged.
# This module owns persistence + state machine; bob owns spawn/consume.
#
# State machine (design §5.4):
#
#       open ──consume──▶ consumed   (verdict accepted; final)
#       open ──supersede─▶ superseded (a newer bundle obsoletes this)
#       open ──stale─────▶ stale      (verdict tuple mismatch; will retry)
#       open ──abandon───▶ abandoned  (freshness window blew past; escalate)
#
# Terminal states (consumed | superseded | stale | abandoned) cannot
# transition further. Re-opening = caller creates a new request_id.
#
# Idempotent open: open_verification_request(...) takes the full tuple as
# input and is keyed by SHA-256 of the canonicalized tuple. Two calls with
# byte-identical tuples return the same request_id and do NOT create a
# duplicate file. This protects bob restart mid-flight (design §5.4).
#
# CB4 preservation: every write here uses atomic_write (temp + rename) into
# .ledger/requests/verification/<request_id>.request.yaml — no other agent
# writes here, no skill writes here. Bob is the sole writer.

VERIFICATION_REQUESTS_SUBDIR = ".ledger/requests/verification"

# State constants — exported names so tests do not stringify magic literals.
VR_STATUS_OPEN = "open"
VR_STATUS_CONSUMED = "consumed"
VR_STATUS_SUPERSEDED = "superseded"
VR_STATUS_STALE = "stale"
VR_STATUS_ABANDONED = "abandoned"

VR_TERMINAL_STATES = frozenset({
    VR_STATUS_CONSUMED, VR_STATUS_SUPERSEDED,
    VR_STATUS_STALE, VR_STATUS_ABANDONED,
})

# The 8 fields whose match is required for a verdict to be honored
# (tester-split design §5.3).
VERDICT_TUPLE_FIELDS: Tuple[str, ...] = (
    "request_id",
    "attempt_id",
    "prior_state_version",
    "bundle_hash",
    "plan_hash",
    "inventory_hash",
    "runner_version",
    "rubric_version",
)


def _canonical_request_payload(payload: Dict[str, Any]) -> str:
    """Deterministic byte-form of a request payload, used for idempotent IDs.

    Keys are sorted; only the 7 input fields below participate in the digest
    (request_id is DERIVED from this digest, so it cannot be an input).
    """
    keys = (
        "component_id", "attempt_id", "prior_state_version",
        "bundle_hash", "plan_hash", "inventory_hash",
        "runner_version", "rubric_version",
    )
    canonical = {k: payload[k] for k in keys if k in payload}
    return _yaml_safe_dump_canonical(canonical)


def _yaml_safe_dump_canonical(obj: Any) -> str:
    """yaml dump with sort_keys=True and default_flow_style=False.

    Equivalent to canonical_json for our purposes — only ASCII-safe values
    appear in the request payload (UUIDs, hex hashes, integer revisions,
    short version strings). We keep YAML to match the rest of the file
    format; the digest is taken over the YAML bytes themselves.
    """
    return yaml.safe_dump(obj, sort_keys=True, default_flow_style=False)


def _request_path(project_root: Path, request_id: str) -> Path:
    return (
        project_root.resolve()
        / VERIFICATION_REQUESTS_SUBDIR
        / f"{request_id}.request.yaml"
    )


def _read_request(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def open_verification_request(
    project_root: Path,
    *,
    component_id: str,
    attempt_id: str,
    prior_state_version: str,
    bundle_hash: str,
    plan_hash: str,
    inventory_hash: str,
    runner_version: str,
    rubric_version: str,
    opened_by: str = "bob",
) -> Dict[str, Any]:
    """Open (or return the existing) verification request for this tuple.

    Bob calls this BEFORE spawning the arbiter subprocess so that the
    on-disk record exists if bob crashes between spawn and consume (design
    §5.4, "Bob restart mid-flight").

    The request_id is deterministic over the input tuple (sha256 truncated
    to a 32-char hex prefix). Two calls with byte-identical inputs:
      - return the same request_id
      - do NOT create a second file
      - do NOT mutate the existing file's status, opened_at, or opened_by

    Returns the request record (including request_id and status). The caller
    should expect status == 'open' on first call and may see a terminal
    state on a re-open if a prior verdict already consumed the request.
    """
    project_root = project_root.resolve()
    payload_for_digest = {
        "component_id": component_id,
        "attempt_id": attempt_id,
        "prior_state_version": prior_state_version,
        "bundle_hash": bundle_hash,
        "plan_hash": plan_hash,
        "inventory_hash": inventory_hash,
        "runner_version": runner_version,
        "rubric_version": rubric_version,
    }
    canonical = _canonical_request_payload(payload_for_digest)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    request_id = digest[:32]

    request_dir = project_root / VERIFICATION_REQUESTS_SUBDIR
    request_dir.mkdir(parents=True, exist_ok=True)
    path = _request_path(project_root, request_id)

    # Serialize bob's own writes via the existing claim lock — verification
    # requests live under .ledger/, so the same writer-discipline applies.
    with _bob_claim_lock(project_root):
        existing = _read_request(path)
        if existing is not None:
            # Idempotent: do not rewrite or mutate the existing record.
            return existing
        record: Dict[str, Any] = {
            "request_id": request_id,
            "component_id": component_id,
            "attempt_id": attempt_id,
            "prior_state_version": prior_state_version,
            "bundle_hash": bundle_hash,
            "plan_hash": plan_hash,
            "inventory_hash": inventory_hash,
            "runner_version": runner_version,
            "rubric_version": rubric_version,
            "status": VR_STATUS_OPEN,
            "opened_at": now_iso(),
            "opened_by": opened_by,
        }
        atomic_write(path, _yaml_safe_dump_canonical(record))
        return record


def mark_verification_request_status(
    project_root: Path,
    request_id: str,
    status: str,
    *,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Transition an open verification request to a terminal state.

    Allowed transitions: open -> {consumed, superseded, stale, abandoned}.
    Any other transition (terminal -> anything, missing record) raises
    RuntimeError so bob escalates rather than silently no-op'ing.

    Records `closed_at`, `closed_status`, and (optionally) `reason`.
    Atomic write under the claim lock.
    """
    if status not in VR_TERMINAL_STATES:
        raise ValueError(
            f"status {status!r} not a terminal state; "
            f"allowed: {sorted(VR_TERMINAL_STATES)}"
        )
    project_root = project_root.resolve()
    path = _request_path(project_root, request_id)
    with _bob_claim_lock(project_root):
        record = _read_request(path)
        if record is None:
            raise RuntimeError(
                f"verification request {request_id!r} not found at {path}"
            )
        if record.get("status") != VR_STATUS_OPEN:
            raise RuntimeError(
                f"verification request {request_id!r} is not open "
                f"(current status={record.get('status')!r}); "
                f"cannot transition to {status!r}"
            )
        record["status"] = status
        record["closed_at"] = now_iso()
        record["closed_status"] = status
        if reason is not None:
            record["reason"] = reason
        atomic_write(path, _yaml_safe_dump_canonical(record))
        return record


def consume_verdict(
    project_root: Path,
    request_id: str,
    verdict: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Validate `verdict` against the open request and mark it consumed (or stale).

    Per design §5.3, a verdict is honored only if all 8 fields in
    VERDICT_TUPLE_FIELDS echo back unchanged. On match: the request is
    transitioned open -> consumed. On mismatch: the request is transitioned
    open -> stale, the caller is expected to open a fresh request and retry.

    Returns (outcome, request_after) where outcome is one of:
        'accepted'              — tuple matched; request now consumed
        'rejected_mismatch'     — tuple mismatch; request now stale; caller retries
        'rejected_not_open'     — request was already terminal; verdict discarded

    Never raises on validation failure — bob needs the structured outcome
    to drive its retry / escalation logic. Raises only on missing request
    file (which is an environmental error and should escalate).
    """
    project_root = project_root.resolve()
    path = _request_path(project_root, request_id)
    record = _read_request(path)
    if record is None:
        raise RuntimeError(
            f"verification request {request_id!r} not found at {path}"
        )
    if record.get("status") != VR_STATUS_OPEN:
        return ("rejected_not_open", record)

    # Full 8-field tuple match (design §5.3).
    mismatches: List[str] = []
    for field in VERDICT_TUPLE_FIELDS:
        expected = record.get(field) if field != "request_id" else request_id
        actual = verdict.get(field)
        if actual != expected:
            mismatches.append(field)

    if mismatches:
        updated = mark_verification_request_status(
            project_root,
            request_id,
            VR_STATUS_STALE,
            reason=f"verdict tuple mismatch on fields: {sorted(mismatches)}",
        )
        return ("rejected_mismatch", updated)

    updated = mark_verification_request_status(
        project_root, request_id, VR_STATUS_CONSUMED,
        reason="verdict accepted; full tuple match",
    )
    return ("accepted", updated)


def recover_verification_requests(project_root: Path) -> Tuple[int, int]:
    """Sweep stale open verification requests to `abandoned` (design §5.4, §9.5).

    Per design §5.4: an open verification request older than the freshness
    window is considered abandoned — the arbiter subprocess likely crashed,
    was killed, or never wrote back. Bob marks such requests abandoned and
    escalates; the caller can re-open a fresh request if retry is desired.

    Per design §9.5 (resolution): freshness window defaults to 1800 seconds
    and is configurable via the `ARBITER_FRESHNESS_WINDOW_S` environment
    variable so tests and operational tuning can override it without a code
    change.

    Scope: only `status == "open"` requests are considered. Terminal states
    (consumed / superseded / stale / abandoned) are left alone. Malformed
    YAML files are skipped without crashing (mirrors `recover_claims`).
    Missing `.ledger/requests/verification/` directory returns (0, 0).

    Returns:
        (swept_count, skipped_open_count) where
            swept_count         = open -> abandoned transitions applied
            skipped_open_count  = open requests still within the window
    """
    project_root = project_root.resolve()
    requests_dir = project_root / VERIFICATION_REQUESTS_SUBDIR
    swept = 0
    skipped_open = 0
    if not requests_dir.is_dir():
        return (0, 0)
    try:
        freshness_window_s = int(os.environ.get("ARBITER_FRESHNESS_WINDOW_S", "1800"))
    except ValueError:
        freshness_window_s = 1800
    now = datetime.now(timezone.utc)
    # NOTE on lock discipline: `mark_verification_request_status` acquires
    # `_bob_claim_lock` itself, and that lock is implemented as an
    # `fcntl.flock(LOCK_EX)` on a fresh fd — it is NOT reentrant within
    # the same process. We therefore write the terminal transition in
    # place under the single lock we hold here, mirroring exactly what
    # `mark_verification_request_status` would have written.
    with _bob_claim_lock(project_root):
        for f in requests_dir.glob("*.request.yaml"):
            try:
                record = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("status") != VR_STATUS_OPEN:
                continue
            opened_at_raw = record.get("opened_at")
            if not isinstance(opened_at_raw, str):
                continue
            try:
                opened_at = parse_iso(opened_at_raw)
            except (ValueError, TypeError):
                continue
            age_s = (now - opened_at).total_seconds()
            if age_s > freshness_window_s:
                record["status"] = VR_STATUS_ABANDONED
                record["closed_at"] = now_iso()
                record["closed_status"] = VR_STATUS_ABANDONED
                record["reason"] = "freshness_window_elapsed"
                atomic_write(f, _yaml_safe_dump_canonical(record))
                swept += 1
            else:
                skipped_open += 1
    return (swept, skipped_open)


# ---------------------------------------------------------------------------
# Phase 2b additions — ecosystem-keystone §5.5 + §5.2 + §2.8
# ---------------------------------------------------------------------------
# These extensions mirror the S027 8-field tuple state machine for a new
# domain: visual verification. They also add the D17 entity-lifecycle event
# recorder and the challenge-lifecycle state machine from design §2.8.
#
# Scope discipline (additive only):
#   - All existing S027 functions above are untouched.
#   - New functions live under the shared `_bob_claim_lock(project_root)`;
#     no new lock class is introduced.
#   - Cross-ledger atomic writes go through `trusted_runner.bundle_write`;
#     hand-rolled tmp+rename is not used for multi-file transactions.
#   - `claude_observe` auto-emission is fail-open (ImportError/Exception
#     swallowed; business logic continues).
#
# Persistence (all under `<project_root>/.design-ledger/`):
#   - verification-requests/<request_id>.yaml
#   - challenges/<challenge_id>.yaml
#   - entity-lifecycle/<entity_uuid>.history.yaml


# Module constants -----------------------------------------------------------

VISUAL_VERIFICATION_REQUESTS_SUBDIR = ".design-ledger/verification-requests"
CHALLENGES_SUBDIR = ".design-ledger/challenges"
ENTITY_LIFECYCLE_SUBDIR = ".design-ledger/entity-lifecycle"

_CHALLENGE_REASONS: Tuple[str, ...] = (
    "implementation_blocked",
    "mockup_ambiguous",
    "functional_requirement_conflict",
    "accessibility_violation",
)

_CHALLENGE_REASON_TO_OBS_CATEGORY: Dict[str, str] = {
    "implementation_blocked": "flow_gap",
    "functional_requirement_conflict": "schema_mismatch",
    "mockup_ambiguous": "skill_bug",
    "accessibility_violation": "skill_bug",
}

_CHALLENGE_RESOLUTION_TYPES: Tuple[str, ...] = (
    "approve",
    "reject",
    "accept_with_tradeoff",
)

_LIFECYCLE_EVENT_TYPES: Tuple[str, ...] = (
    "created",
    "renamed",
    "split",
    "merged",
    "retired",
)

# 8-field tuple for visual verdicts (design §5.5 + §2.9). Mirrors S027 shape
# with skeleton_hash replacing bundle_hash and impl_hash replacing plan_hash.
VISUAL_VERDICT_TUPLE_FIELDS: Tuple[str, ...] = (
    "request_id",
    "attempt_id",
    "prior_state_version",
    "skeleton_hash",
    "impl_hash",
    "inventory_hash",
    "runner_version",
    "rubric_version",
)

VVR_STATUS_OPEN = "open"
VVR_STATUS_CONSUMED = "consumed"


# Fail-open claude_observe loader (Contract 3) -------------------------------
# The write.py module lives at
#   ~/.claude/skills/process-observation/scripts/write.py
# The hyphenated directory name is not a valid Python package, so we try
# the canonical import first then a path-based fallback then a no-op stub.

def _load_claude_observe():
    try:
        from process_observation.scripts.write import claude_observe as _co  # type: ignore
        return _co
    except ImportError:
        pass
    try:
        _scripts_dir = (
            Path(__file__).resolve().parent.parent
            / "process-observation" / "scripts"
        )
        if _scripts_dir.is_dir():
            _scripts_str = str(_scripts_dir)
            if _scripts_str not in sys.path:
                sys.path.insert(0, _scripts_str)
            from write import claude_observe as _co  # type: ignore
            return _co
    except Exception:
        pass
    return lambda *args, **kwargs: None


claude_observe = _load_claude_observe()


# Helpers --------------------------------------------------------------------

def _canonical_visual_payload(payload: Dict[str, Any]) -> str:
    keys = (
        "attempt_id", "prior_state_version",
        "skeleton_hash", "impl_hash", "inventory_hash",
        "runner_version", "rubric_version",
        "breakpoints",
    )
    canonical = {k: payload[k] for k in keys if k in payload}
    return _yaml_safe_dump_canonical(canonical)


def _visual_request_path(project_root: Path, request_id: str) -> Path:
    return (
        project_root.resolve()
        / VISUAL_VERIFICATION_REQUESTS_SUBDIR
        / f"{request_id}.yaml"
    )


def _challenge_path(project_root: Path, challenge_id: str) -> Path:
    return (
        project_root.resolve()
        / CHALLENGES_SUBDIR
        / f"{challenge_id}.yaml"
    )


def _lifecycle_path(project_root: Path, entity_uuid: str) -> Path:
    return (
        project_root.resolve()
        / ENTITY_LIFECYCLE_SUBDIR
        / f"{entity_uuid}.history.yaml"
    )


def _read_yaml_dict(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _safe_observe(**kwargs: Any) -> None:
    """Fail-open wrapper around claude_observe — never raises."""
    try:
        claude_observe(**kwargs)
    except Exception:
        pass


# 1. open_visual_verification_request ----------------------------------------

def open_visual_verification_request(
    project_root: Path,
    *,
    skeleton_hash: str,
    impl_hash: str,
    breakpoints: List[str],
    attempt_id: str,
    prior_state_version: str,
    plan_hash: str,
    inventory_hash: str,
    runner_version: str,
    rubric_version: str,
    opened_by: str = "bob",
) -> Dict[str, Any]:
    """Open (or return) a visual-verification request; mirrors S027.

    request_id = sha256(canonical(7-field tuple + breakpoints))[:32].
    Idempotent: second call with byte-identical inputs returns the same
    request_id and does not rewrite the file; `created` flips True->False.
    `plan_hash` is accepted for parity with S027 callers (stored but not
    part of the visual tuple hash).
    """
    project_root = project_root.resolve()
    payload_for_digest = {
        "attempt_id": attempt_id,
        "prior_state_version": prior_state_version,
        "skeleton_hash": skeleton_hash,
        "impl_hash": impl_hash,
        "inventory_hash": inventory_hash,
        "runner_version": runner_version,
        "rubric_version": rubric_version,
        "breakpoints": list(breakpoints or []),
    }
    canonical = _canonical_visual_payload(payload_for_digest)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    request_id = digest[:32]

    request_dir = project_root / VISUAL_VERIFICATION_REQUESTS_SUBDIR
    path = _visual_request_path(project_root, request_id)

    with _bob_claim_lock(project_root):
        request_dir.mkdir(parents=True, exist_ok=True)
        existing = _read_yaml_dict(path)
        if existing is not None:
            out = dict(existing)
            out["created"] = False
            return out
        record: Dict[str, Any] = {
            "request_id": request_id,
            "attempt_id": attempt_id,
            "prior_state_version": prior_state_version,
            "skeleton_hash": skeleton_hash,
            "impl_hash": impl_hash,
            "plan_hash": plan_hash,
            "inventory_hash": inventory_hash,
            "runner_version": runner_version,
            "rubric_version": rubric_version,
            "breakpoints": list(breakpoints or []),
            "status": VVR_STATUS_OPEN,
            "opened_at": now_iso(),
            "opened_by": opened_by,
        }
        atomic_write(path, _yaml_safe_dump_canonical(record))
        out = dict(record)
        out["created"] = True
        return out


# 2. consume_visual_verdict --------------------------------------------------

def consume_visual_verdict(
    project_root: Path,
    request_id: str,
    verdict: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Validate verdict against open request; mirrors S027 consume_verdict.

    Four outcomes:
        'accepted'                — 8-field tuple matched + status=open;
                                    request transitioned open -> consumed.
        'rejected_not_open'       — request already terminal; no writes.
        'rejected_tuple_mismatch' — one or more tuple fields differ;
                                    NO state change (request stays open).
        'rejected_mismatch'       — generic mismatch (parity with S027).

    Raises RuntimeError if the request file is missing.
    """
    project_root = project_root.resolve()
    path = _visual_request_path(project_root, request_id)
    record = _read_yaml_dict(path)
    if record is None:
        raise RuntimeError(
            f"visual verification request {request_id!r} not found at {path}"
        )
    if record.get("status") != VVR_STATUS_OPEN:
        return ("rejected_not_open", record)

    mismatches: List[str] = []
    for field in VISUAL_VERDICT_TUPLE_FIELDS:
        expected = record.get(field) if field != "request_id" else request_id
        actual = verdict.get(field)
        if actual != expected:
            mismatches.append(field)
    if mismatches:
        return ("rejected_tuple_mismatch", record)

    with _bob_claim_lock(project_root):
        locked = _read_yaml_dict(path)
        if locked is None:
            raise RuntimeError(
                f"visual verification request {request_id!r} vanished at {path}"
            )
        if locked.get("status") != VVR_STATUS_OPEN:
            return ("rejected_not_open", locked)
        locked["status"] = VVR_STATUS_CONSUMED
        locked["closed_at"] = now_iso()
        locked["closed_status"] = VVR_STATUS_CONSUMED
        locked["verdict"] = verdict
        atomic_write(path, _yaml_safe_dump_canonical(locked))
        return ("accepted", locked)


# 3. file_challenge ----------------------------------------------------------

def _canonical_challenge_id(
    skeleton_ref: str, reason: str, details: Any,
) -> str:
    payload = {
        "skeleton_ref": skeleton_ref,
        "reason": reason,
        "details": details,
    }
    canonical = _yaml_safe_dump_canonical(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def file_challenge(
    project_root: Path,
    *,
    skeleton_ref: str,
    reason: str,
    details: Any,
    proposed_resolution: Optional[Dict[str, Any]] = None,
    filed_by: str = "bob",
) -> Dict[str, Any]:
    """File a skeleton-challenge.v1 record; auto-emit observation.

    `reason` MUST be one of 4 closed-set values (design §2.8).
    Atomic write; idempotent by (skeleton_ref, reason, details) digest.
    Observation category: flow_gap / schema_mismatch / skill_bug per reason.
    """
    if reason not in _CHALLENGE_REASONS:
        raise ValueError(
            f"file_challenge: reason {reason!r} not in closed set "
            f"{list(_CHALLENGE_REASONS)}"
        )

    project_root = project_root.resolve()
    challenge_id = _canonical_challenge_id(skeleton_ref, reason, details)
    path = _challenge_path(project_root, challenge_id)

    with _bob_claim_lock(project_root):
        existing = _read_yaml_dict(path)
        if existing is not None:
            return existing
        record: Dict[str, Any] = {
            "schema": "skeleton-challenge.v1",
            "challenge_id": challenge_id,
            "skeleton_ref": skeleton_ref,
            "reason": reason,
            "details": details,
            "proposed_resolution": proposed_resolution,
            "filed_by": filed_by,
            "filed_at": now_iso(),
            "state": "FILED",
            "resolution": None,
        }
        (project_root / CHALLENGES_SUBDIR).mkdir(parents=True, exist_ok=True)
        atomic_write(path, _yaml_safe_dump_canonical(record))

    obs_category = _CHALLENGE_REASON_TO_OBS_CATEGORY.get(reason)
    if obs_category is not None:
        _safe_observe(
            category=obs_category,
            subject_id=skeleton_ref,
            what_happened=(
                f"challenge filed for {skeleton_ref} "
                f"(reason={reason}, challenge_id={challenge_id})"
            ),
            fingerprint=f"challenge-{reason}-{challenge_id}",
            subject_type="skill",
            severity="degraded",
            observed_by=filed_by,
        )
    return record


# 4. resolve_challenge -------------------------------------------------------

def resolve_challenge(
    project_root: Path,
    challenge_id: str,
    *,
    resolution_type: str,
    new_skeleton_version: Optional[str] = None,
    contract_map_delta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve a filed challenge (design §2.8 state machine).

    resolution_type in {approve, reject, accept_with_tradeoff}. When
    resolution_type == 'approve' AND contract_map_delta is not None, the
    skeleton and contract-map are updated in ONE atomic transaction via
    trusted_runner.bundle_write (pre-image rollback on any failure).
    contract_map_delta keys consumed:
        skeleton_path       (str, optional, relative to project_root)
        contract_map_path   (str, optional, relative to project_root)
        skeleton_bytes      (bytes or str)
        contract_map_bytes  (bytes or str)
    """
    if resolution_type not in _CHALLENGE_RESOLUTION_TYPES:
        raise ValueError(
            f"resolve_challenge: resolution_type {resolution_type!r} not in "
            f"closed set {list(_CHALLENGE_RESOLUTION_TYPES)}"
        )

    project_root = project_root.resolve()
    path = _challenge_path(project_root, challenge_id)

    try:
        from trusted_runner import bundle_write  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            f"resolve_challenge: trusted_runner.bundle_write unavailable: {e}"
        ) from e

    with _bob_claim_lock(project_root):
        record = _read_yaml_dict(path)
        if record is None:
            raise RuntimeError(
                f"challenge {challenge_id!r} not found at {path}"
            )
        if record.get("resolution") is not None:
            raise RuntimeError(
                f"challenge {challenge_id!r} already resolved "
                f"(state={record.get('state')!r})"
            )

        resolution: Dict[str, Any] = {
            "resolution_type": resolution_type,
            "resolved_at": now_iso(),
        }
        if new_skeleton_version is not None:
            resolution["new_skeleton_version"] = new_skeleton_version
        if contract_map_delta is not None:
            resolution["contract_map_delta"] = contract_map_delta

        if resolution_type == "approve":
            if contract_map_delta is not None:
                skeleton_rel = contract_map_delta.get(
                    "skeleton_path",
                    ".design-ledger/skeletons/_default.yaml",
                )
                contract_rel = contract_map_delta.get(
                    "contract_map_path", "progress/contract-map.yaml",
                )
                skeleton_bytes = contract_map_delta.get("skeleton_bytes", b"")
                contract_bytes = contract_map_delta.get(
                    "contract_map_bytes", b""
                )
                if isinstance(skeleton_bytes, str):
                    skeleton_bytes = skeleton_bytes.encode("utf-8")
                if isinstance(contract_bytes, str):
                    contract_bytes = contract_bytes.encode("utf-8")
                skeleton_target = project_root / skeleton_rel
                contract_target = project_root / contract_rel
                rollback_dir = project_root / ".tmp" / "rollback"
                txn_id = bundle_write(
                    [
                        (skeleton_target, skeleton_bytes),
                        (contract_target, contract_bytes),
                    ],
                    rollback_dir=rollback_dir,
                )
                resolution["txn_id"] = txn_id
                resolution["skeleton_path"] = str(skeleton_rel)
                resolution["contract_map_path"] = str(contract_rel)
            record["state"] = "RESOLVED_APPROVED"
        elif resolution_type == "reject":
            record["state"] = "RESOLVED_REJECTED"
        elif resolution_type == "accept_with_tradeoff":
            if new_skeleton_version is not None:
                record["accepted_deviation"] = {
                    "new_skeleton_version": new_skeleton_version,
                    "noted_at": now_iso(),
                }
            record["state"] = "RESOLVED_TRADEOFF"

        record["resolution"] = resolution
        atomic_write(path, _yaml_safe_dump_canonical(record))
        return record


# 5. file_lifecycle_event ----------------------------------------------------

def file_lifecycle_event(
    project_root: Path,
    entity_uuid: str,
    event_type: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    """Append a D17 lifecycle event to entity-lifecycle/<uuid>.history.yaml.

    event_type in {created, renamed, split, merged, retired}. When
    event_type in {split, merged, retired} AND details['affects_source_ledger']
    is truthy, the history + source-ledger file are committed in ONE atomic
    transaction via trusted_runner.bundle_write. Source-ledger target comes
    from details['source_ledger_path'] + ['source_ledger_bytes'].

    Updates the `current: {status, final_uris, successors}` projection per
    §5.2. Returns the full updated history record.
    """
    if event_type not in _LIFECYCLE_EVENT_TYPES:
        raise ValueError(
            f"file_lifecycle_event: event_type {event_type!r} not in closed "
            f"set {list(_LIFECYCLE_EVENT_TYPES)}"
        )
    if not isinstance(details, dict):
        raise ValueError("file_lifecycle_event: details must be a dict")

    project_root = project_root.resolve()
    path = _lifecycle_path(project_root, entity_uuid)

    affects_source = bool(details.get("affects_source_ledger")) and event_type in {
        "split", "merged", "retired",
    }

    with _bob_claim_lock(project_root):
        existing = _read_yaml_dict(path)
        if existing is None:
            history: Dict[str, Any] = {
                "schema": "entity-lifecycle.v1",
                "entity_uuid": entity_uuid,
                "kind": details.get("kind", "capability"),
                "created_at": now_iso(),
                "events": [],
                "current": {
                    "status": "active",
                    "final_uris": [],
                    "successors": [],
                },
            }
        else:
            history = existing
            history.setdefault("events", [])
            history.setdefault("current", {
                "status": "active", "final_uris": [], "successors": [],
            })

        event: Dict[str, Any] = {"event": event_type, "at": now_iso()}
        for k, v in details.items():
            if k in (
                "affects_source_ledger", "source_ledger_path",
                "source_ledger_bytes", "kind",
            ):
                continue
            event[k] = v
        history["events"].append(event)

        current = history["current"]
        if event_type == "created":
            current["status"] = "active"
            initial_uri = details.get("initial_uri")
            if initial_uri:
                current["final_uris"] = [initial_uri]
        elif event_type == "renamed":
            current["status"] = "active"
            to_uri = details.get("to_uri")
            if to_uri:
                current["final_uris"] = [to_uri]
        elif event_type in ("split", "merged"):
            current["status"] = "retired"
            successors = details.get("successor_uuids") or []
            current["successors"] = list(successors)
            from_uri = details.get("from_uri")
            if from_uri and not current.get("final_uris"):
                current["final_uris"] = [from_uri]
        elif event_type == "retired":
            current["status"] = "retired"
            final_uri = details.get("final_uri")
            if final_uri:
                current["final_uris"] = [final_uri]
            current["successors"] = list(details.get("successor_uuids") or [])

        (project_root / ENTITY_LIFECYCLE_SUBDIR).mkdir(
            parents=True, exist_ok=True,
        )
        history_bytes = _yaml_safe_dump_canonical(history).encode("utf-8")

        if affects_source:
            try:
                from trusted_runner import bundle_write  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    f"file_lifecycle_event: trusted_runner.bundle_write "
                    f"unavailable: {e}"
                ) from e
            source_rel = details.get("source_ledger_path")
            if source_rel is None:
                raise ValueError(
                    "file_lifecycle_event: affects_source_ledger=True "
                    "requires details['source_ledger_path']"
                )
            source_bytes = details.get("source_ledger_bytes", b"")
            if isinstance(source_bytes, str):
                source_bytes = source_bytes.encode("utf-8")
            source_target = project_root / source_rel
            rollback_dir = project_root / ".tmp" / "rollback"
            txn_id = bundle_write(
                [
                    (path, history_bytes),
                    (source_target, source_bytes),
                ],
                rollback_dir=rollback_dir,
            )
            event["txn_id"] = txn_id
        else:
            atomic_write(path, _yaml_safe_dump_canonical(history))

        return history


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        sys.stderr.write("usage: claims.py issue|heartbeat|recover|status ...\n")
        sys.exit(2)
    cmd = argv[1]
    flags: Dict[str, str] = {}
    positional: List[str] = []
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--project-root":
            flags["project_root"] = argv[i + 1]
            i += 2
        else:
            positional.append(a)
            i += 1
    project_root = Path(flags.get("project_root", os.getcwd()))

    if cmd == "issue":
        if len(positional) < 2:
            sys.stderr.write("issue <wp_id> <skill>\n")
            sys.exit(2)
        try:
            claim = issue_claim(positional[0], positional[1], project_root)
        except RuntimeError as e:
            sys.stderr.write(f"ISSUE_FAIL: {e}\n")
            sys.exit(2)
        sys.stdout.write(claim["claim_uuid"] + "\n")
    elif cmd == "heartbeat":
        if len(positional) < 1:
            sys.stderr.write("heartbeat <claim_uuid>\n")
            sys.exit(2)
        state = heartbeat_claim(positional[0], project_root)
        sys.stdout.write(state + "\n")
        sys.exit(0 if state == "ok" else 2)
    elif cmd == "recover":
        purged, stale = recover_claims(project_root)
        sys.stdout.write(f"recovered: purged={purged} stale={stale}\n")
    elif cmd == "status":
        if len(positional) < 1:
            sys.stderr.write("status <claim_uuid>\n")
            sys.exit(2)
        claim_path = project_root / ".ledger" / "claims" / f"{positional[0]}.claim.yaml"
        if not claim_path.is_file():
            sys.stdout.write("missing\n")
            sys.exit(2)
        try:
            claim = yaml.safe_load(claim_path.read_text()) or {}
        except yaml.YAMLError:
            sys.stdout.write("corrupt\n")
            sys.exit(2)
        ledger_path = project_root / "progress" / "integration-ledger.md"
        state = classify_claim(claim, ledger_path)
        sys.stdout.write(state + "\n")
        sys.exit(0 if state == "ok" else 2)
    else:
        sys.stderr.write(f"unknown command: {cmd}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
