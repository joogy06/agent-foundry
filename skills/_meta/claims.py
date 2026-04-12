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

CLI:
    python -m claims issue <wp_id> <skill> [--project-root <dir>]
    python -m claims heartbeat <claim_uuid> [--project-root <dir>]
    python -m claims recover [--project-root <dir>]
    python -m claims status <claim_uuid> [--project-root <dir>]

Concurrency model: bob is the sole writer. Skills only READ claim files, and only
echo back the claim_uuid token in transition requests. The lease_until + heartbeat
protocol ensures crashed claimants do not block forward progress.

Provenance: spec section 8.4. Critical invariants enforced: CB1, CB4.
"""
from __future__ import annotations

import fcntl
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
