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
import json
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


# NOTE (S030-quickwins #34): `wp` and `component` cells accept `.` so dotted
# WP IDs (e.g. "WP-2.A", "WP-3.foo.bar") parse cleanly. Discovered in the
# 2026-04-09 DLP pilot where `claims.issue_claim("WP-2.A", ...)` failed because
# the previous `[A-Za-z0-9_-]+` regex rejected the dot. Tests in
# tests/test_claims_row_re.py.
_ROW_RE = re.compile(
    r"^\|\s*(?P<wp>[A-Za-z0-9_.-]+)\s*\|"
    r"\s*(?P<component>[A-Za-z0-9_.-]+)\s*\|"
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


# ---------------------------------------------------------------------------
# Persistent run lease (S055 §6.5 / R16)
#
# flock CANNOT span workflow stage processes — each Bash call is a fresh
# process and the lock dies on exit, so the original "flock on
# .bob-checkpoint.md" mechanism is NONFUNCTIONAL across stages. Replacement: a
# DURABLE lease file in the claims engine. Exactly one live bob per project_root
# (CB4) is enforced by validating the lease on EVERY bob-owned mutation. All
# critical sections are single-python-call flock regions (the proven
# _bob_claim_lock shape — NOT a cross-process lock lifetime).
# ---------------------------------------------------------------------------

RUN_LEASE_EXPIRY_SECONDS = 900  # 15 minutes — a heartbeat older than this is stale


def _run_lease_path(project_root: Path) -> Path:
    return project_root / ".ledger" / "run-lease.json"


def _read_run_lease(project_root: Path) -> Optional[Dict[str, Any]]:
    p = _run_lease_path(project_root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _run_lease_is_live(lease: Dict[str, Any]) -> bool:
    """A lease is live iff its heartbeat is within RUN_LEASE_EXPIRY_SECONDS."""
    hb = lease.get("heartbeat_at")
    if not hb:
        return False
    try:
        age = (datetime.now(timezone.utc) - parse_iso(hb)).total_seconds()
    except ValueError:
        return False
    return age <= RUN_LEASE_EXPIRY_SECONDS


def acquire_run_lease(
    project_root: Path,
    plan_hash: str,
    run_label: str,
    plan_revision: int = 0,
) -> Dict[str, Any]:
    """Acquire the run lease for this (plan_hash, run_label). Called by the FIRST
    bob stage of a run (or bob standalone at Step 1 for M/L cycles).

    Returns one of:
      {"status": "acquired", "token": <uuid>, ...}            — lease is ours
      {"status": "needs_user_decision", "reason": "...", "holder": {...}}
            — a LIVE lease with a DIFFERENT run_label exists (concurrent run)
      {"status": "takeover", "token": <uuid>, "previous": {...}}
            — a STALE lease was taken over (recorded takeover event)
    Idempotent: re-acquiring with the SAME run_label refreshes our own lease.
    """
    with _bob_claim_lock(project_root):
        existing = _read_run_lease(project_root)
        if existing and _run_lease_is_live(existing):
            if existing.get("run_label") == run_label and existing.get("plan_hash") == plan_hash:
                # Our own live lease — refresh heartbeat, keep token.
                existing["heartbeat_at"] = now_iso()
                atomic_write(_run_lease_path(project_root), json.dumps(existing, indent=2, sort_keys=True))
                return {"status": "acquired", "token": existing["token"], **existing}
            # A live lease held by a DIFFERENT run — refuse. CB4: one live bob.
            return {
                "status": "needs_user_decision",
                "reason": "a live run lease with a different run_label exists",
                "holder": {
                    "run_label": existing.get("run_label"),
                    "plan_hash": existing.get("plan_hash"),
                    "heartbeat_at": existing.get("heartbeat_at"),
                },
            }
        # No lease, or a stale one — acquire (record takeover if we displaced one).
        token = str(uuid.uuid4())
        now = now_iso()
        lease = {
            "plan_hash": plan_hash,
            "plan_revision": plan_revision,
            "run_label": run_label,
            "token": token,
            "acquired_at": now,
            "heartbeat_at": now,
        }
        result_status = "acquired"
        if existing:
            lease["takeover_of"] = {
                "run_label": existing.get("run_label"),
                "token": existing.get("token"),
                "last_heartbeat_at": existing.get("heartbeat_at"),
                "taken_over_at": now,
            }
            result_status = "takeover"
        atomic_write(_run_lease_path(project_root), json.dumps(lease, indent=2, sort_keys=True))
        out = {"status": result_status, "token": token, **lease}
        if result_status == "takeover":
            out["previous"] = lease["takeover_of"]
        return out


def heartbeat_run_lease(project_root: Path, token: str) -> bool:
    """Refresh the lease heartbeat. Called by every bob stage on entry.

    Returns True if the heartbeat landed (token matches the live lease), False
    if the lease is missing or the token does not match (do NOT proceed)."""
    with _bob_claim_lock(project_root):
        lease = _read_run_lease(project_root)
        if not lease or lease.get("token") != token:
            return False
        lease["heartbeat_at"] = now_iso()
        atomic_write(_run_lease_path(project_root), json.dumps(lease, indent=2, sort_keys=True))
        return True


def validate_run_lease(
    project_root: Path,
    run_label: str,
    plan_hash: Optional[str] = None,
    token: Optional[str] = None,
) -> bool:
    """Validate the lease on EVERY bob-owned mutation (ledger transition,
    checkpoint write, claim issue). The lease MUST exist, match run_label
    (and plan_hash/token when supplied), and be live. Mismatch => the caller
    aborts PARTIAL and touches nothing (CB4 single-writer enforcement)."""
    lease = _read_run_lease(project_root)
    if not lease:
        return False
    if not _run_lease_is_live(lease):
        return False
    if lease.get("run_label") != run_label:
        return False
    if plan_hash is not None and lease.get("plan_hash") != plan_hash:
        return False
    if token is not None and lease.get("token") != token:
        return False
    return True


def release_run_lease(project_root: Path, token: str) -> bool:
    """Release the lease (finalize stage). Only the token-holder may release.
    Returns True if released, False if the token did not match / no lease."""
    with _bob_claim_lock(project_root):
        lease = _read_run_lease(project_root)
        if not lease or lease.get("token") != token:
            return False
        _run_lease_path(project_root).unlink(missing_ok=True)
        return True


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


# ===========================================================================
# S044 / #118 — the SOLE-WRITER transition engine (B1) + R6 precondition (B2)
# ===========================================================================
#
# Closes task #47 (the missing `apply_request_idempotent` symbol bob.md cites
# 4x) AND converts bob's prose dual-arm VERIFIED rule into a structural
# precondition on the transition path (design §10 B1/B2/B4/B5/B6).
#
# Honesty (design §10 B2, §9-A1 C1): this is STRONG PROTOCOL ENFORCEMENT, not
# literally-unskippable. Bob retains filesystem write access; a truly
# "cannot bypass" engine needs a host-owned broker / separate-UID trust
# boundary (explicit v2 non-goal). The win is: ONE chokepoint, all stage
# preconditions dispatched under ONE lock, no inline-append drift. R6 reads
# bob's persisted dual-verdict archive — it catches rationalized/accidental
# skips (the observed #43-dev3 drift class), NOT a bob that maliciously
# fabricates a complete archive (that needs the deferred spawner provenance).
#
# Scope discipline (additive only): every existing function above is
# untouched. The engine reuses `_bob_claim_lock`, `atomic_write`,
# `read_ledger`, `verify_claim_on_transition`. CB4 preserved — bob is the
# sole writer of progress/integration-ledger.md.


class VerifiedPreconditionError(RuntimeError):
    """Raised by `assert_verified_preconditions` when the persisted dual-verdict
    archive for an INTEGRATED -> VERIFIED transition does not satisfy R6
    (both arms present + both passing + closed pass-set + neither
    AUDIT_UNAVAILABLE/REJECTED + complete versioned cross-binding).

    A subclass of RuntimeError so existing `except RuntimeError` call sites in
    bob's flow still trap it, while tests can assert the precise type.
    """


class IllegalTransitionError(RuntimeError):
    """Raised by `apply_request_idempotent` when a requested from->to pair is
    not in `LEGAL_TRANSITIONS`. Subclass of RuntimeError for the same reason
    as VerifiedPreconditionError."""


# ---------------------------------------------------------------------------
# B1 — the LEGAL_TRANSITIONS locked table (design §10 B1, git-reviewable
# constant — NOT config-driven, mirrors CONTRACT_SCOPE_CRITICAL_GLOBS rationale:
# configs are mutable + rubber-stampable; constants are reviewable in history).
#
# Rules:
#   - a `to` not in LEGAL_TRANSITIONS[from] -> reject (IllegalTransitionError).
#   - any `->PLANNED` is a DEMOTE/restart and MUST bump the component
#     generation (CB1 — the live S029 freeze-the-world / amendment path).
#   - DOCUMENTED is terminal (empty set).
#   - BLOCKED unblocks only by demote-to-PLANNED.
#
# The UI lane (UI-INTEGRATED -> UI-VERIFIED) is OUT this cycle (A5 deferred,
# design §10 B3). UI transitions keep their current path; this table covers
# only the core lane.
# ---------------------------------------------------------------------------

LEGAL_TRANSITIONS: Dict[str, frozenset] = {
    "PLANNED":     frozenset({"SCAFFOLDED", "BLOCKED"}),
    "SCAFFOLDED":  frozenset({"UNIT_TESTED", "BLOCKED", "PLANNED"}),   # PLANNED = demote
    "UNIT_TESTED": frozenset({"INTEGRATED", "BLOCKED", "PLANNED"}),
    "INTEGRATED":  frozenset({"VERIFIED", "BLOCKED", "PLANNED"}),
    "VERIFIED":    frozenset({"DOCUMENTED", "BLOCKED", "PLANNED"}),
    "DOCUMENTED":  frozenset(),                                        # terminal
    "BLOCKED":     frozenset({"PLANNED"}),                             # unblock = demote
}


def check_transition_legal(from_stage: str, to_stage: str) -> bool:
    """Return True iff `to_stage` is a legal successor of `from_stage` per the
    locked LEGAL_TRANSITIONS table (design §10 B1). The engine's step-3 calls
    this; bob.md's prose legality narration is now a backstop only.

    Unknown `from_stage` -> False (fail closed: an unrecognized current stage
    cannot legally transition anywhere)."""
    return to_stage in LEGAL_TRANSITIONS.get(from_stage, frozenset())


def is_demote_to_planned(to_stage: str) -> bool:
    """A `->PLANNED` transition is a demote/restart that bumps the component
    generation (CB1). Centralized so the engine and tests agree."""
    return to_stage == "PLANNED"


# ---------------------------------------------------------------------------
# Ledger event + projection structured read/write (B1 step 5 + step 6).
#
# The ledger is a markdown file with three load-bearing regions:
#   1. YAML frontmatter header (--- ... ---) carrying consumed_request_ids
#   2. a "## Projection" table:  | WP | component | stage | generation | deps |
#   3. a "## Transition log" table: | # | WP | component | from -> to | generation | evidence |
#
# To preserve the hand-authored header byte-for-byte (quotes, amendments
# block, skill_checksums ordering), we do a SURGICAL text rewrite: regenerate
# only the projection rows, the transition-log rows, and the
# consumed_request_ids header line. Everything else passes through verbatim.
# This is the engine's atomic rewrite (design §10 B1 step 6) — it is the ONLY
# code that appends transition events (design §10 B6).
# ---------------------------------------------------------------------------

# Accepts either ASCII "->" or unicode "→" in the from->to cell (S029 archive
# used "→"; the production ledger template uses "->"). We WRITE with the same
# arrow the file already uses (sniffed per-file) so round-trips stay clean.
_EVENT_ROW_RE = re.compile(
    r"^\|\s*(?P<num>\d+)\s*\|"
    r"\s*(?P<wp>[A-Za-z0-9_.-]+)\s*\|"
    r"\s*(?P<component>[A-Za-z0-9_.-]+)\s*\|"
    r"\s*(?P<from>[A-Z_]+)\s*(?:->|→)\s*(?P<to>[A-Z_]+)\s*\|"
    r"\s*(?P<gen>\d+)\s*\|"
    r"\s*(?P<evidence>.*?)\s*\|\s*$"
)


def _ledger_arrow(text: str) -> str:
    """Sniff which from->to arrow this ledger file uses. Default ASCII '->'."""
    if "from → to" in text or "→" in text:
        return "→"
    return "->"


def _split_header(text: str) -> Tuple[str, Dict[str, Any], str]:
    """Return (header_block_including_fences, header_dict, body_after_header).

    header_block_including_fences is the verbatim '---\\n...\\n---' region so
    it can be rewritten surgically. body_after_header is everything after the
    closing fence (including the leading newline)."""
    if not text.startswith("---"):
        return ("", {}, text)
    end = text.find("\n---", 4)
    if end == -1:
        return ("", {}, text)
    # closing fence line ends at the newline after '---'
    close_line_end = text.find("\n", end + 1)
    if close_line_end == -1:
        close_line_end = len(text)
    header_block = text[:close_line_end + 1]
    body = text[close_line_end + 1:]
    inner = text[4:end]
    try:
        header_dict = yaml.safe_load(inner) or {}
    except yaml.YAMLError:
        header_dict = {}
    if not isinstance(header_dict, dict):
        header_dict = {}
    return (header_block, header_dict, body)


def _rewrite_consumed_request_ids(header_block: str, consumed: List[str]) -> str:
    """Surgically replace the `consumed_request_ids:` line in the header.

    Renders an inline flow list `[a, b, c]` (matches the existing
    `consumed_request_ids: []` template). Preserves every other header line."""
    rendered = "[" + ", ".join(consumed) + "]"
    lines = header_block.splitlines(keepends=True)
    out: List[str] = []
    replaced = False
    in_block_list = False
    for line in lines:
        if in_block_list:
            # consume any block-list members ('  - xxx') belonging to the
            # previous consumed_request_ids: key, then stop.
            if re.match(r"^\s*-\s+", line):
                continue
            in_block_list = False
        m = re.match(r"^(\s*)consumed_request_ids\s*:(.*)$", line)
        if m and not replaced:
            indent = m.group(1)
            out.append(f"{indent}consumed_request_ids: {rendered}\n")
            replaced = True
            # if the original used a block list (value empty / pipe), skip its
            # following '  - ' members
            tail = m.group(2).strip()
            if tail == "" or tail == "[]":
                in_block_list = tail == ""
            continue
        out.append(line)
    if not replaced:
        # No consumed_request_ids key present — insert before the closing fence.
        # header_block ends with '---\n'; insert just before it.
        joined = "".join(out)
        idx = joined.rfind("\n---")
        if idx != -1:
            insertion = f"consumed_request_ids: {rendered}\n"
            joined = joined[:idx + 1] + insertion + joined[idx + 1:]
            return joined
        return joined + f"consumed_request_ids: {rendered}\n"
    return "".join(out)


def _render_projection_table(rows: List["LedgerRow"], arrow: str) -> str:
    """Render the '## Projection' table body (header + separator + rows)."""
    out = [
        "| WP | component | stage | generation | deps |",
        "|----|-----------|-------|------------|------|",
    ]
    for r in rows:
        deps = ", ".join(r.deps) if r.deps else "—"
        out.append(f"| {r.wp} | {r.component} | {r.stage} | {r.generation} | {deps} |")
    return "\n".join(out)


def _replace_section_table(body: str, section_header: str, new_table: str) -> str:
    """Replace the markdown table immediately following `section_header`.

    Finds the section, then replaces the run of consecutive table lines (lines
    starting with '|') after it with `new_table`. Non-table content (blank
    lines, prose) before the first '|' is preserved; content after the table
    block is preserved verbatim."""
    idx = body.find(section_header)
    if idx == -1:
        return body  # section absent — leave body untouched (defensive)
    after = idx + len(section_header)
    lines = body[after:].splitlines(keepends=True)
    # Walk forward to the first table line, preserving intervening lines.
    pre: List[str] = []
    i = 0
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        pre.append(lines[i])
        i += 1
    # Consume the contiguous table block.
    j = i
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        j += 1
    rest = lines[j:]
    # Ensure exactly one trailing newline after the new table, then the rest.
    new_block = new_table.rstrip("\n") + "\n"
    rebuilt = body[:after] + "".join(pre) + new_block + "".join(rest)
    return rebuilt


def _parse_event_rows(body: str) -> List[Dict[str, Any]]:
    """Parse existing transition-log rows into dicts (for max-num + replay)."""
    out: List[Dict[str, Any]] = []
    for line in body.splitlines():
        m = _EVENT_ROW_RE.match(line)
        if not m:
            continue
        out.append({
            "num": int(m.group("num")),
            "wp": m.group("wp"),
            "component": m.group("component"),
            "from": m.group("from"),
            "to": m.group("to"),
            "gen": int(m.group("gen")),
            "evidence": m.group("evidence"),
        })
    return out


def _append_event_row(
    body: str, event: Dict[str, Any], arrow: str,
) -> str:
    """Append one event row to the '## Transition log' table."""
    existing = _parse_event_rows(body)
    next_num = (max((e["num"] for e in existing), default=0) + 1)
    evidence = str(event.get("evidence", "")).replace("|", "\\|").replace("\n", " ")
    row = (
        f"| {next_num} | {event['wp']} | {event['component']} | "
        f"{event['from']} {arrow} {event['to']} | {event['generation']} | "
        f"{evidence} |"
    )
    idx = body.find("## Transition log")
    if idx == -1:
        # No transition-log section — append one at the end.
        block = (
            "\n## Transition log\n\n"
            "| # | WP | component | from " + arrow + " to | generation | evidence |\n"
            "|---|----|-----------|-----------|------------|----------|\n"
            + row + "\n"
        )
        return body.rstrip("\n") + "\n" + block
    after = idx + len("## Transition log")
    lines = body[after:].splitlines(keepends=True)
    # Find the end of the contiguous table block (header+sep+rows).
    i = 0
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        i += 1
    j = i
    last_table_line = i
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        last_table_line = j
        j += 1
    # Insert the new row right after the last table line.
    insert_at = last_table_line + 1
    new_lines = lines[:insert_at] + [row + "\n"] + lines[insert_at:]
    return body[:after] + "".join(new_lines)


# ---------------------------------------------------------------------------
# B2 / B4 — R6: dual-arm VERIFIED precondition (reads dual-verdict.v1 archive)
# ---------------------------------------------------------------------------

VERDICTS_SUBDIR = ".ledger/verdicts"

# B4: the frozen dual-verdict.v1 envelope. R6 rejects archives missing
# schema_version or any cross-binding field. The closed pass-set is the ONLY
# vocabulary that allows the transition; anything else (REJECTED,
# AUDIT_UNAVAILABLE, missing, malformed) FAILS CLOSED.
DUAL_VERDICT_SCHEMA_VERSION = "dual-verdict.v1"
VERIFIED_PASS_SET: frozenset = frozenset({"VERIFIED", "VERIFIED_WITH_CONCERNS"})
VERIFIED_FAIL_VALUES: frozenset = frozenset({"REJECTED", "AUDIT_UNAVAILABLE"})

# The cross-binding fields validated TOGETHER (design §10 B2). A bundle_hash
# alone is insufficient (C6). These bind the archive to ONE component, ONE
# bundle, ONE verification request, ONE prior state version, ONE generation.
_R6_CROSS_BINDING_FIELDS: Tuple[str, ...] = (
    "component_id",
    "bundle_hash",
    "verification_request_id",
    "prior_state_version",
    "generation",
)

# S048 / #116 — the deterministic (non-LLM) verification arm. R6's VERIFIED
# condition becomes a flat CONJUNCTION (NOT a quorum):
#     audit_arm passes ∧ arbiter_arm passes ∧ deterministic_evidence == GREEN
#       ∧ citations_corroborated
# The deterministic conjunct is DERIVED IN R6 from the hash-addressed bundle
# itself (deterministic_arm.classify_bundle_evidence) — NEVER from a producer-
# written boolean in the archive (forgeable), NEVER from gate-runs.jsonl
# (fail-open telemetry with no component/bundle/state binding). It is a pure
# VETO: it can only subtract VERIFIEDs, so it cannot introduce a false-pass.
#
# Citation-corroboration is gated on the verdict's rubric_version (the R-B2
# cutover key). Older verdicts (produced under a pre-cutover rubric that did NOT
# require an evidence_map) skip corroboration DETERMINISTICALLY — keyed to the
# rubric the verdict was produced under, so there is no silent-disable gap. New
# verdicts all carry the new rubric -> all corroborated.
#
# bundle_hash is NOT touched here — R6 READS the bundle; it never writes it (the
# #124 load-bearing invariant).
R6_CITATION_RUBRIC_MIN: Tuple[int, int, int] = (1, 2, 0)


def _parse_semver(value: Any) -> Optional[Tuple[int, int, int]]:
    """Parse a 'MAJOR.MINOR.PATCH' string into a comparable tuple. Returns None
    on any non-conforming value (a verdict whose rubric_version is unparseable
    is treated as PRE-cutover -> corroboration not required, fail-safe: we never
    fabricate a 'new rubric' that would demand corroboration the producer could
    not have emitted)."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (TypeError, ValueError):
        return None


def _import_deterministic_arm():
    """Lazy, path-safe import of deterministic_arm (mirrors the gates.py
    `_load_classify_module` pattern). Keeps claims.py module-load unperturbed."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import deterministic_arm  # type: ignore
    return deterministic_arm


def _verdict_path(project_root: Path, bundle_hash: str) -> Path:
    return project_root.resolve() / VERDICTS_SUBDIR / f"{bundle_hash}.verdict.yaml"


def _read_verdict_archive(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def assert_verified_preconditions(
    bundle_hash: str,
    project_root: Path,
    *,
    expected: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """R6 (design §10 B2). READ bob's persisted dual-verdict archive at
    `.ledger/verdicts/<bundle_hash>.verdict.yaml` and enforce, for an
    INTEGRATED -> VERIFIED transition:

      1. archive EXISTS + parses;
      2. it is a versioned `dual-verdict.v1` envelope (reject unversioned /
         wrong-version — C6 schema-drift);
      3. ALL cross-binding fields present (component_id, bundle_hash,
         verification_request_id, prior_state_version, generation);
      4. if `expected` is given, every overlapping cross-binding field matches
         (validated TOGETHER — a bundle_hash alone is insufficient, C6);
      5. BOTH arms present at the asymmetric canonical keys:
           audit axis   = audit_arm.result
           arbiter axis = arbiter_arm.verdict
         (mirrors the S039 mis-bucketing fixture; do NOT substring-grep the
         file for AUDIT_UNAVAILABLE — it can appear in a free-text
         rerun-history field while the canonical key is REJECTED);
      6. BOTH arms in the closed pass-set {VERIFIED, VERIFIED_WITH_CONCERNS};
      7. NEITHER arm AUDIT_UNAVAILABLE or REJECTED (forecloses the invented
         "not attempted" 3rd branch, #43-dev3).
      8. (S048 / #116) DETERMINISTIC EVIDENCE == GREEN — derived IN R6 from the
         hash-addressed bundle (deterministic_arm.classify_bundle_evidence),
         NOT from any producer-written boolean and NOT from gate-runs.jsonl.
         RED (a failed/error result) -> veto (a VERIFIED contradicting failing
         evidence is impossible). INDETERMINATE (empty / all-skipped-without-
         sanction / timeout / hash-or-provenance mismatch) -> veto with a
         "bounded clean rerun then escalate; do NOT VERIFY this bundle" message.
      9. (S048 / #116) CITATION CORROBORATION — when the arbiter arm's
         rubric_version >= R6_CITATION_RUBRIC_MIN, every nodeid the arbiter cited
         in `arbiter_arm.evidence_map` MUST exist in the bundle's
         results[].tests[] AND have outcome == "passed". A cited nodeid that is
         absent/non-passing -> veto (invented/misattributed evidence). On older
         (pre-cutover) verdicts, or degraded/jest bundles with no per-test
         records, corroboration is skipped/unavailable (no veto).

    Returns the parsed archive on success. Raises VerifiedPreconditionError on
    ANY failure (refuse the transition). Honest scope (design §10 B2 + §5/#151):
    this catches rationalized/accidental skips + arbiter-only archives +
    AUDIT_UNAVAILABLE-ignored + unversioned envelopes + RED/empty/mismatched
    evidence + invented citations; it does NOT defend against a bob that
    fabricates a complete archive (deferred spawner provenance, #141) NOR against
    the semantic-test-adequacy residual (tests that pass but encode the wrong
    oracle — deferred to #151 changed-line mutation).
    """
    project_root = project_root.resolve()
    path = _verdict_path(project_root, bundle_hash)
    archive = _read_verdict_archive(path)
    if archive is None:
        raise VerifiedPreconditionError(
            f"R6: dual-verdict archive missing/unparseable at {path} "
            f"(bundle_hash={bundle_hash!r}) — refuse INTEGRATED->VERIFIED "
            f"(forecloses the 'not attempted' skip, #43-dev3)"
        )

    # (2) versioned envelope.
    sv = archive.get("schema_version")
    if sv != DUAL_VERDICT_SCHEMA_VERSION:
        raise VerifiedPreconditionError(
            f"R6: archive at {path} has schema_version={sv!r}, "
            f"require {DUAL_VERDICT_SCHEMA_VERSION!r} (reject unversioned / "
            f"ambiguous — C6 schema-drift)"
        )

    # (3) cross-binding fields present.
    missing = [f for f in _R6_CROSS_BINDING_FIELDS if archive.get(f) is None]
    if missing:
        raise VerifiedPreconditionError(
            f"R6: archive at {path} missing cross-binding field(s) "
            f"{missing} — a bundle_hash alone is insufficient (C6)"
        )

    # bundle_hash inside the archive MUST equal the lookup key (self-binding).
    if str(archive.get("bundle_hash")) != str(bundle_hash):
        raise VerifiedPreconditionError(
            f"R6: archive bundle_hash {archive.get('bundle_hash')!r} != "
            f"lookup key {bundle_hash!r} (self-binding mismatch)"
        )

    # (4) cross-binding match against caller's expected values (TOGETHER).
    if expected:
        mismatched: List[str] = []
        for field in _R6_CROSS_BINDING_FIELDS:
            if field in expected:
                if str(archive.get(field)) != str(expected.get(field)):
                    mismatched.append(field)
        if mismatched:
            raise VerifiedPreconditionError(
                f"R6: archive at {path} cross-binding mismatch on "
                f"{mismatched} (expected {{"
                + ", ".join(f"{k}={expected.get(k)!r}" for k in mismatched)
                + "}}) — validated together, refuse transition"
            )

    # (5) both arms present at the ASYMMETRIC canonical keys.
    audit_arm = archive.get("audit_arm")
    arbiter_arm = archive.get("arbiter_arm")
    if not isinstance(audit_arm, dict) or "result" not in audit_arm:
        raise VerifiedPreconditionError(
            f"R6: archive at {path} missing audit_arm.result "
            f"(audit arm not present/passing — arbiter-only archive does not "
            f"prove the audit subprocess ran, #43-dev3)"
        )
    if not isinstance(arbiter_arm, dict) or "verdict" not in arbiter_arm:
        raise VerifiedPreconditionError(
            f"R6: archive at {path} missing arbiter_arm.verdict "
            f"(arbiter arm not present/passing)"
        )

    audit_result = audit_arm.get("result")
    arbiter_verdict = arbiter_arm.get("verdict")

    # (6)+(7) closed pass-set + neither fail-value. Order matters for clarity:
    # an explicit fail-value (AUDIT_UNAVAILABLE/REJECTED) gets a precise error.
    for axis_name, value in (("audit_arm.result", audit_result),
                             ("arbiter_arm.verdict", arbiter_verdict)):
        if value in VERIFIED_FAIL_VALUES:
            raise VerifiedPreconditionError(
                f"R6: {axis_name}={value!r} is an explicit non-pass — "
                f"stay at INTEGRATED, escalate (AUDIT_UNAVAILABLE/REJECTED are "
                f"NEVER auto-approved)"
            )
        if value not in VERIFIED_PASS_SET:
            raise VerifiedPreconditionError(
                f"R6: {axis_name}={value!r} not in closed pass-set "
                f"{sorted(VERIFIED_PASS_SET)} — fail closed"
            )

    # -----------------------------------------------------------------------
    # (8) DETERMINISTIC EVIDENCE (S048 / #116) — the 4th necessary conjunct,
    # derived IN R6 from the hash-addressed bundle (never a producer boolean,
    # never gate-runs.jsonl). component_id + bundle_hash come from the archive's
    # already-validated cross-binding. A flat conjunction (NOT a quorum): the
    # deterministic arm can only VETO.
    # -----------------------------------------------------------------------
    component_id = str(archive.get("component_id"))
    try:
        det = _import_deterministic_arm()
    except Exception as e:  # pragma: no cover - import failure is env, fail safe
        raise VerifiedPreconditionError(
            f"R6: could not load the deterministic verification arm "
            f"({type(e).__name__}: {e}) — refuse INTEGRATED->VERIFIED rather "
            f"than skip the on-disk evidence check"
        )

    det_verdict = det.classify_bundle_evidence(component_id, bundle_hash, project_root)
    det_state = det_verdict.get("state")
    if det_state == det.RED:
        raise VerifiedPreconditionError(
            f"R6: deterministic evidence arm is RED for component={component_id!r} "
            f"bundle_hash={bundle_hash} — {det_verdict.get('reason')}. A VERIFIED "
            f"contradicting failing on-disk evidence is impossible -> veto "
            f"(derived from the bundle, NOT from any archive boolean)"
        )
    if det_state != det.GREEN:  # INDETERMINATE or anything non-GREEN
        raise VerifiedPreconditionError(
            f"R6: deterministic evidence arm is {det_state!r} (not GREEN) for "
            f"component={component_id!r} bundle_hash={bundle_hash} — "
            f"{det_verdict.get('reason')}. Bounded clean rerun then escalate; do "
            f"NOT VERIFY this bundle (never auto-pass on an evidence gap)"
        )

    # -----------------------------------------------------------------------
    # (9) CITATION CORROBORATION (S048 / #116, R-B2/R-I3) — gated on the
    # arbiter arm's rubric_version. Pre-cutover verdicts skip this
    # deterministically (keyed to the rubric the verdict was produced under —
    # no silent-disable gap). The evidence_map rides the arbiter arm (the
    # dual-verdict envelope is additionalProperties:true, so bob stores the full
    # arbiter verdict — incl. evidence_map — under arbiter_arm).
    # -----------------------------------------------------------------------
    rubric = _parse_semver(arbiter_arm.get("rubric_version"))
    if rubric is not None and rubric >= R6_CITATION_RUBRIC_MIN:
        evidence_map = arbiter_arm.get("evidence_map")
        if evidence_map is None:
            raise VerifiedPreconditionError(
                f"R6: arbiter rubric_version={arbiter_arm.get('rubric_version')!r} "
                f">= {'.'.join(map(str, R6_CITATION_RUBRIC_MIN))} REQUIRES an "
                f"evidence_map under arbiter_arm, but none is present — refuse "
                f"(the post-cutover arbiter MUST cite passing test nodeids)"
            )
        # Re-load the bundle dict to walk results[].tests[] for corroboration.
        # (classify_bundle_evidence already proved hash/provenance/component;
        # here we only need the test records to match cited nodeids.)
        bundle_path = det.bundle_path_for(component_id, bundle_hash, project_root)
        bundle_doc = det._read_bundle(bundle_path)
        if bundle_doc is None:  # pragma: no cover - already proven readable in (8)
            raise VerifiedPreconditionError(
                f"R6: bundle vanished between deterministic classify and citation "
                f"corroboration at {bundle_path} — refuse"
            )
        cit = det.corroborate_citations(bundle_doc, evidence_map)
        if cit.get("status") == det.CIT_VETO:
            raise VerifiedPreconditionError(
                f"R6: citation corroboration VETO — {cit.get('reason')}; invalid="
                f"{cit.get('invalid')}. The arbiter cited test nodeid(s) that are "
                f"absent or non-passing in the bundle (invented/misattributed "
                f"evidence — a correlated-hallucination tell) -> refuse"
            )
        # CIT_OK or CIT_UNAVAILABLE (degraded/jest) -> no veto.

    return archive


# ---------------------------------------------------------------------------
# B1 — apply_request_idempotent: the ONE general transition writer (#47).
# ---------------------------------------------------------------------------

# Stage-specific precondition dispatch (B1 step 4). Keyed by (from, to). Each
# hook takes (request, ledger_state_dict, project_root) and raises on failure.
# Only the INTEGRATED->VERIFIED R6 hook is wired this cycle; the UI lane is
# deferred (A5). Adding a hook here is the extension point for future stages.


def _precondition_integrated_to_verified(
    request: Dict[str, Any],
    row: "LedgerRow",
    project_root: Path,
) -> None:
    """R6 hook dispatched on INTEGRATED -> VERIFIED (B1 step 4, B2)."""
    bundle_hash = request.get("bundle_hash")
    if not bundle_hash:
        raise VerifiedPreconditionError(
            "R6: INTEGRATED->VERIFIED request carries no bundle_hash; "
            "cannot locate the dual-verdict archive — refuse"
        )
    expected = {
        "component_id": request.get("component_id", row.component),
        "bundle_hash": bundle_hash,
        "generation": request.get("generation", row.generation),
    }
    if request.get("verification_request_id") is not None:
        expected["verification_request_id"] = request.get("verification_request_id")
    if request.get("prior_state_version") is not None:
        expected["prior_state_version"] = request.get("prior_state_version")
    assert_verified_preconditions(bundle_hash, project_root, expected=expected)


_TRANSITION_PRECONDITIONS: Dict[Tuple[str, str], Any] = {
    ("INTEGRATED", "VERIFIED"): _precondition_integrated_to_verified,
}


def apply_request_idempotent(
    request: Dict[str, Any],
    project_root: Path,
) -> Dict[str, Any]:
    """The SOLE-WRITER transition engine (design §10 B1, closes #47).

    All work happens under `_bob_claim_lock`. Steps (B1):
      1. read current ledger state;
      2. dedup by transition `request_id` ONLY (NOT request_id+attempt_id —
         attempt_id belongs to the 8-field verification tuple; conflating them
         would break PLANNED->SCAFFOLDED / SCAFFOLDED->UNIT_TESTED /
         demote-to-PLANNED callers, design §9-A1 step 2);
      3. validate the claim (`verify_claim_on_transition`) + legal from->to
         (`check_transition_legal` over the B1 table);
      4. dispatch the stage-specific precondition (R6 on INTEGRATED->VERIFIED);
      5. append the event + update the projection + consumed_request_ids;
      6. atomic rewrite.

    `request` keys consumed:
      request_id   (str, REQUIRED) — idempotency + dedup key
      wp           (str) — WP id (falls back to component lookup)
      component_id (str) — component name (falls back to wp's row component)
      to_stage     (str, REQUIRED) — target stage
      from_stage   (str, optional) — asserted current stage; if given and it
                   disagrees with the ledger, the engine trusts the LEDGER
                   (the request is a proposal; the ledger is truth)
      evidence     (str, optional) — transition-log evidence cell
      bundle_hash  (str) — required for INTEGRATED->VERIFIED (R6)
      claim_uuid   (str, optional) — when present, verify_claim_on_transition
                   is enforced; when absent, the claim check is skipped (bob's
                   own engine-driven demotes / force-restarts carry no claim)

    Returns a result dict:
      {applied: bool, outcome: str, request_id, from, to, generation,
       reason: str|None}
      outcome in {applied, duplicate_ignored, illegal_transition,
                  invalid_claim, precondition_failed, unknown_wp}.

    Idempotency: a request whose request_id is already in the ledger header's
    consumed_request_ids is a no-op returning outcome='duplicate_ignored'
    (design §10 B1 step 2 + §10 B5 crash-recovery: the VERIFIED event
    re-applies idempotently via this dedup).

    Raises:
      - KeyError if request_id or to_stage is missing (a malformed request is
        a programming error, not a recoverable runtime state).
    Failure MODES that are part of normal flow (illegal transition, invalid
    claim, precondition failure) are returned as structured outcomes AND also
    surface the underlying exception type for callers that prefer to raise —
    EXCEPT the engine itself never half-writes: on any pre-write failure the
    ledger is left untouched.
    """
    if "request_id" not in request:
        raise KeyError("apply_request_idempotent: request missing 'request_id'")
    if "to_stage" not in request:
        raise KeyError("apply_request_idempotent: request missing 'to_stage'")

    project_root = project_root.resolve()
    ledger_path = project_root / "progress" / "integration-ledger.md"
    request_id = str(request["request_id"])
    to_stage = str(request["to_stage"])
    wp_id = request.get("wp") or request.get("wp_id")
    component_id = request.get("component_id")

    with _bob_claim_lock(project_root):
        if not ledger_path.is_file():
            return {
                "applied": False, "outcome": "unknown_wp",
                "request_id": request_id, "from": None, "to": to_stage,
                "generation": None,
                "reason": f"ledger not found at {ledger_path}",
            }
        text = ledger_path.read_text()
        header_block, header, body = _split_header(text)
        arrow = _ledger_arrow(text)

        # (2) dedup by request_id ONLY.
        consumed: List[str] = list(header.get("consumed_request_ids") or [])
        if request_id in consumed:
            return {
                "applied": False, "outcome": "duplicate_ignored",
                "request_id": request_id, "from": None, "to": to_stage,
                "generation": None,
                "reason": "request_id already in consumed_request_ids",
            }

        ledger = read_ledger(ledger_path)
        # Resolve the row by wp first, then component.
        row: Optional[LedgerRow] = None
        if wp_id is not None:
            row = ledger.row(str(wp_id))
        if row is None and component_id is not None:
            row = ledger.row(str(component_id))
        if row is None:
            return {
                "applied": False, "outcome": "unknown_wp",
                "request_id": request_id,
                "from": None, "to": to_stage, "generation": None,
                "reason": f"no projection row for wp={wp_id!r} "
                          f"component={component_id!r}",
            }

        from_stage = row.stage  # ledger is truth (request from_stage is advisory)

        # (3a) legal from->to.
        if not check_transition_legal(from_stage, to_stage):
            return {
                "applied": False, "outcome": "illegal_transition",
                "request_id": request_id,
                "from": from_stage, "to": to_stage, "generation": row.generation,
                "reason": f"{from_stage}->{to_stage} not in LEGAL_TRANSITIONS",
            }

        # (3b) claim validity — only when the request carries a claim_uuid.
        if request.get("claim_uuid"):
            if not verify_claim_on_transition(request, ledger_path):
                return {
                    "applied": False, "outcome": "invalid_claim",
                    "request_id": request_id,
                    "from": from_stage, "to": to_stage,
                    "generation": row.generation,
                    "reason": "verify_claim_on_transition returned False "
                              "(lease expired / stale generation / revoked / "
                              "missing)",
                }

        # (4) stage-specific precondition dispatch (R6 on INTEGRATED->VERIFIED).
        hook = _TRANSITION_PRECONDITIONS.get((from_stage, to_stage))
        if hook is not None:
            try:
                hook(request, row, project_root)
            except VerifiedPreconditionError as e:
                return {
                    "applied": False, "outcome": "precondition_failed",
                    "request_id": request_id,
                    "from": from_stage, "to": to_stage,
                    "generation": row.generation,
                    "reason": str(e),
                }

        # (5) compute new generation (any ->PLANNED demote bumps it, CB1).
        new_generation = row.generation
        if is_demote_to_planned(to_stage):
            new_generation = row.generation + 1

        # (5a) update the in-memory projection row.
        row.stage = to_stage
        row.generation = new_generation

        # (5b) append the event row.
        event = {
            "wp": row.wp,
            "component": row.component,
            "from": from_stage,
            "to": to_stage,
            "generation": new_generation,
            "evidence": request.get("evidence", ""),
        }
        body2 = _append_event_row(body, event, arrow)

        # (5c) regenerate the projection table from the (mutated) rows.
        proj_table = _render_projection_table(ledger.rows, arrow)
        body3 = _replace_section_table(
            body2, "## Projection (current state — one row per WP/component)",
            proj_table,
        )
        if body3 == body2:
            # Header text may differ; try the bare "## Projection" anchor.
            body3 = _replace_section_table(body2, "## Projection", proj_table)

        # (5d) record consumed_request_id in the header.
        consumed.append(request_id)
        new_header = _rewrite_consumed_request_ids(header_block, consumed)

        # (6) atomic rewrite of the whole ledger.
        atomic_write(ledger_path, new_header + body3)

        return {
            "applied": True, "outcome": "applied",
            "request_id": request_id,
            "from": from_stage, "to": to_stage,
            "generation": new_generation,
            "reason": None,
        }


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
