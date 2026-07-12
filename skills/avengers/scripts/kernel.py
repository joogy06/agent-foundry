#!/usr/bin/env python3
"""avengers — kernel.py (WP-2). The deterministic process kernel.

Charter (design §3): "code where determinism is load-bearing AND semantics-free."
The kernel makes the deliberation PROCESS legible, bounded, and auditable. It does
NOT judge the merits — deliberation *quality* rests on the LLM chair and seats.

The kernel owns:
  - phase legality + transitions (design §4 phase machine)
  - obligation-ledger BOOKKEEPING: it creates/tracks ids and counters. Statuses
    (answered / conceded) are SET BY THE CHAIR, never inferred by the kernel — a
    seat cannot self-declare that it won (that is gameable). The ONE status the
    kernel sets on its own is `stalemate`, and only via the deterministic
    termination guarantee below.
  - budgets: max_seat_calls, wall_clock_s, max_cycles (the canonical cross-exam
    cycle-budget name everywhere)
  - the stalemate detector: an INTERNAL "2 unchanged exchanges" counter, DISTINCT
    from max_cycles. When an obligation reaches the threshold it is marked
    `stalemate` and flows to the arbiter as unresolved dissent. Together with the
    max_cycles ceiling this is the TERMINATION GUARANTEE — cross-exam cannot loop
    forever.
  - quorum (design §4 LOW_QUORUM runtime-collapse semantics)
  - atomic transcript append (temp+rename) with a per-turn sha256 digest. There is
    NO chain walk in v1: the digest catches CORRUPTION, not adversaries (a tamperer
    who edits a turn can recompute its digest). Stated honestly, not oversold.
  - a JSON event log and a session projection/status.

It makes NO semantic decisions, calls NO LLM, and makes NO network calls.
Dependencies: Python stdlib ONLY (all machine/runtime state is stdlib JSON).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Phase machine (design §4)
# --------------------------------------------------------------------------- #
CONVENE = "CONVENE"
BLIND_DIVERGE = "BLIND_DIVERGE"
DOCKET = "DOCKET"
CROSS_EXAM = "CROSS_EXAM"
CONVERGE = "CONVERGE"
ARBITER = "ARBITER"
ROUTE = "ROUTE"
WRITEBACK_PROPOSE = "WRITEBACK_PROPOSE"
CLOSED = "CLOSED"
ABORTED = "ABORTED"

# The happy-path linear order (for reference / projection).
PHASE_SEQUENCE = (
    CONVENE, BLIND_DIVERGE, DOCKET, CROSS_EXAM, CONVERGE,
    ARBITER, ROUTE, WRITEBACK_PROPOSE, CLOSED,
)

# Terminal phases have NO outgoing transitions.
TERMINAL_PHASES = frozenset({CLOSED, ABORTED})

# Legal adjacency. ABORTED is reachable from every non-terminal phase (a hard
# budget exhaustion / unrecoverable IO error). CROSS_EXAM self-loops into the next
# cross-exam cycle (budgeted by max_cycles); that is the ONLY self-loop.
LEGAL_TRANSITIONS: Dict[str, frozenset] = {
    CONVENE: frozenset({BLIND_DIVERGE, ABORTED}),
    BLIND_DIVERGE: frozenset({DOCKET, ABORTED}),
    DOCKET: frozenset({CROSS_EXAM, ABORTED}),
    CROSS_EXAM: frozenset({CROSS_EXAM, CONVERGE, ABORTED}),
    CONVERGE: frozenset({ARBITER, ABORTED}),
    ARBITER: frozenset({ROUTE, ABORTED}),
    ROUTE: frozenset({WRITEBACK_PROPOSE, ABORTED}),
    WRITEBACK_PROPOSE: frozenset({CLOSED, ABORTED}),
    CLOSED: frozenset(),
    ABORTED: frozenset(),
}

# Obligation statuses. `open` is the kernel default at creation. `answered` /
# `conceded` are CHAIR-set (semantic judgment). `stalemate` is kernel-set via the
# termination guarantee (a purely mechanical "no progress" ceiling).
OBLIGATION_OPEN = "open"
OBLIGATION_ANSWERED = "answered"
OBLIGATION_CONCEDED = "conceded"
OBLIGATION_STALEMATE = "stalemate"
CHAIR_SETTABLE_STATUSES = frozenset({OBLIGATION_ANSWERED, OBLIGATION_CONCEDED})
ALL_OBLIGATION_STATUSES = frozenset(
    {OBLIGATION_OPEN, OBLIGATION_ANSWERED, OBLIGATION_CONCEDED, OBLIGATION_STALEMATE}
)
# Statuses that flow to the arbiter as unresolved dissent (design §4 ARBITER).
UNRESOLVED_STATUSES = frozenset({OBLIGATION_OPEN, OBLIGATION_STALEMATE})

# Quorum floors (design §4 LOW_QUORUM). Below MIN_MEMBER_SEATS but >= ABORT_FLOOR
# => run continues with status LOW_QUORUM (confidence capped low). < ABORT_FLOOR
# => ABORTED. Neither is ever silently converted to success.
MIN_MEMBER_SEATS = 3
ABORT_FLOOR = 2
QUORUM_OK = "OK"
QUORUM_LOW = "LOW_QUORUM"
QUORUM_ABORTED = "ABORTED"

DEFAULT_STALEMATE_THRESHOLD = 2  # "2 unchanged exchanges" (design §4)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class KernelError(Exception):
    """Base class for all kernel violations."""


class PhaseError(KernelError):
    """An illegal phase transition was attempted."""


class BudgetExceeded(KernelError):
    """A hard budget (seat calls, wall clock, or cross-exam cycles) was hit."""


class ObligationError(KernelError):
    """An obligation bookkeeping violation (unknown id, illegal status set)."""


# --------------------------------------------------------------------------- #
# Atomic IO (temp + rename) — no reader ever sees a partial write.
# Single-writer assumption: the chair is the sole writer of a session dir.
# --------------------------------------------------------------------------- #
def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on POSIX
        if hasattr(os, "O_DIRECTORY"):
            dfd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _atomic_append_text(path: Path, text: str) -> None:
    """Append by full read + rewrite through a temp file (design §3: temp+rename).

    O(n) per append; transcripts are small and safety beats speed here. The rename
    is atomic, so a crash mid-write leaves the previous complete file intact.
    """
    path = Path(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    _atomic_write_text(path, existing + text)


# --------------------------------------------------------------------------- #
# Per-turn digest (corruption detector; NOT a chain, NOT an adversary defense)
# --------------------------------------------------------------------------- #
def turn_digest(
    *, turn_no: int, phase: str, seat: str, provider: str, served_by: str, ts: str, body: str
) -> str:
    canonical = json.dumps(
        {
            "turn_no": turn_no,
            "phase": phase,
            "seat": seat,
            "provider": provider,
            "served_by": served_by,
            "ts": ts,
            "body": body,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
@dataclass
class Budgets:
    max_seat_calls: int
    wall_clock_s: int
    max_cycles: int  # canonical cross-exam cycle-budget name

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Budgets":
        return cls(
            max_seat_calls=int(d["max_seat_calls"]),
            wall_clock_s=int(d["wall_clock_s"]),
            max_cycles=int(d["max_cycles"]),
        )


@dataclass
class Obligation:
    id: str
    challenger: str
    respondent: str
    topic: str
    status: str = OBLIGATION_OPEN
    unchanged_exchanges: int = 0  # the INTERNAL stalemate counter (distinct from max_cycles)
    exchanges: int = 0
    resolution: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "challenger": self.challenger,
            "respondent": self.respondent,
            "topic": self.topic,
            "status": self.status,
            "unchanged_exchanges": self.unchanged_exchanges,
            "exchanges": self.exchanges,
            "resolution": self.resolution,
        }


@dataclass
class SessionState:
    session_id: str
    budgets: Budgets
    phase: str = CONVENE
    cross_exam_cycle: int = 0
    seat_calls_used: int = 0
    turn_no: int = 0
    started_at: Optional[float] = None  # epoch seconds; set by start_session
    stalemate_threshold: int = DEFAULT_STALEMATE_THRESHOLD
    quorum_status: str = QUORUM_OK
    obligations: List[Obligation] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    # optional disk sinks (kernel works entirely in-memory when these are None)
    transcript_path: Optional[Path] = None
    event_log_path: Optional[Path] = None
    _next_ob: int = 1

    # -- event log -------------------------------------------------------- #
    def _emit(self, kind: str, **fields: Any) -> None:
        event = {"event": kind, **fields}
        self.events.append(event)
        if self.event_log_path is not None:
            _atomic_append_text(
                Path(self.event_log_path),
                json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n",
            )

    def _find_obligation(self, ob_id: str) -> Obligation:
        for ob in self.obligations:
            if ob.id == ob_id:
                return ob
        raise ObligationError(f"unknown obligation id: {ob_id}")


def new_session(
    session_id: str,
    budgets: Dict[str, Any] | Budgets,
    *,
    stalemate_threshold: int = DEFAULT_STALEMATE_THRESHOLD,
    transcript_path: Optional[Path | str] = None,
    event_log_path: Optional[Path | str] = None,
) -> SessionState:
    b = budgets if isinstance(budgets, Budgets) else Budgets.from_dict(budgets)
    return SessionState(
        session_id=session_id,
        budgets=b,
        stalemate_threshold=int(stalemate_threshold),
        transcript_path=Path(transcript_path) if transcript_path else None,
        event_log_path=Path(event_log_path) if event_log_path else None,
    )


def start_session(state: SessionState, *, now: Optional[float] = None) -> None:
    state.started_at = time.time() if now is None else now
    state._emit("session_start", session_id=state.session_id, phase=state.phase, at=state.started_at)


# --------------------------------------------------------------------------- #
# Transitions
# --------------------------------------------------------------------------- #
def is_legal_transition(from_phase: str, to_phase: str) -> bool:
    return to_phase in LEGAL_TRANSITIONS.get(from_phase, frozenset())


def transition(state: SessionState, to_phase: str, *, reason: str = "") -> None:
    """Advance the phase machine. Raises PhaseError on an illegal move and
    BudgetExceeded when a CROSS_EXAM re-entry would exceed max_cycles."""
    frm = state.phase
    if frm in TERMINAL_PHASES:
        raise PhaseError(f"cannot transition out of terminal phase {frm}")
    if not is_legal_transition(frm, to_phase):
        raise PhaseError(f"illegal transition {frm} -> {to_phase}")
    if to_phase == CROSS_EXAM:
        new_cycle = state.cross_exam_cycle + 1
        if new_cycle > state.budgets.max_cycles:
            raise BudgetExceeded(
                f"cross-exam cycle {new_cycle} exceeds max_cycles={state.budgets.max_cycles}; "
                "must proceed to CONVERGE (termination guarantee)"
            )
        state.cross_exam_cycle = new_cycle
    state.phase = to_phase
    state._emit("phase_transition", **{"from": frm, "to": to_phase, "reason": reason,
                                       "cross_exam_cycle": state.cross_exam_cycle})


def abort(state: SessionState, reason: str) -> None:
    """Force ABORTED from any non-terminal phase. Never dressed up as success."""
    if state.phase in TERMINAL_PHASES:
        raise PhaseError(f"cannot abort from terminal phase {state.phase}")
    frm = state.phase
    state.phase = ABORTED
    state.quorum_status = state.quorum_status  # preserved
    state._emit("aborted", **{"from": frm, "reason": reason})


def can_open_next_cycle(state: SessionState) -> bool:
    """True iff another CROSS_EXAM cycle is within the max_cycles budget."""
    return (state.cross_exam_cycle + 1) <= state.budgets.max_cycles


# --------------------------------------------------------------------------- #
# Budgets
# --------------------------------------------------------------------------- #
def record_seat_call(state: SessionState, n: int = 1) -> int:
    """Charge n seat calls. Raises BudgetExceeded if the ceiling is crossed.
    Returns the remaining budget."""
    if n < 0:
        raise ValueError("seat-call count must be non-negative")
    state.seat_calls_used += n
    if state.seat_calls_used > state.budgets.max_seat_calls:
        raise BudgetExceeded(
            f"seat calls {state.seat_calls_used} exceed max_seat_calls={state.budgets.max_seat_calls}"
        )
    state._emit("seat_call", used=state.seat_calls_used, max=state.budgets.max_seat_calls, charged=n)
    return state.budgets.max_seat_calls - state.seat_calls_used


def wall_clock_elapsed(state: SessionState, *, now: Optional[float] = None) -> float:
    if state.started_at is None:
        return 0.0
    return (time.time() if now is None else now) - state.started_at


def wall_clock_remaining(state: SessionState, *, now: Optional[float] = None) -> float:
    return max(0.0, state.budgets.wall_clock_s - wall_clock_elapsed(state, now=now))


def wall_clock_exhausted(state: SessionState, *, now: Optional[float] = None) -> bool:
    return wall_clock_elapsed(state, now=now) >= state.budgets.wall_clock_s


def check_wall_clock(state: SessionState, *, now: Optional[float] = None) -> None:
    """Raise BudgetExceeded if the wall-clock budget is spent."""
    if wall_clock_exhausted(state, now=now):
        raise BudgetExceeded(
            f"wall clock {wall_clock_elapsed(state, now=now):.0f}s >= "
            f"wall_clock_s={state.budgets.wall_clock_s}"
        )


# --------------------------------------------------------------------------- #
# Quorum (runtime collapse; design §4 LOW_QUORUM case (b))
# --------------------------------------------------------------------------- #
def classify_runtime_quorum(
    live_member_seats: int,
    *,
    floor: int = MIN_MEMBER_SEATS,
    abort_floor: int = ABORT_FLOOR,
) -> str:
    """OK if >= floor live member seats; LOW_QUORUM if below floor but >= abort_floor;
    ABORTED if below abort_floor. Pure function (no state mutation)."""
    if live_member_seats < abort_floor:
        return QUORUM_ABORTED
    if live_member_seats < floor:
        return QUORUM_LOW
    return QUORUM_OK


def apply_runtime_quorum(
    state: SessionState,
    live_member_seats: int,
    *,
    floor: int = MIN_MEMBER_SEATS,
    reason: str = "",
) -> str:
    """Classify + record the runtime quorum. On ABORTED, drives the phase machine
    to ABORTED (unless already terminal). Returns the quorum status."""
    status = classify_runtime_quorum(live_member_seats, floor=floor)
    state.quorum_status = status
    state._emit("quorum", live_member_seats=live_member_seats, floor=floor,
                status=status, reason=reason)
    if status == QUORUM_ABORTED and state.phase not in TERMINAL_PHASES:
        abort(state, reason=f"runtime quorum collapse: {live_member_seats} live member seats < {ABORT_FLOOR}")
    return status


# --------------------------------------------------------------------------- #
# Obligation ledger BOOKKEEPING
# --------------------------------------------------------------------------- #
def create_obligation(state: SessionState, challenger: str, respondent: str, topic: str) -> str:
    """Create an obligation at status `open`. Returns its id (OB-n)."""
    ob_id = f"OB-{state._next_ob}"
    state._next_ob += 1
    ob = Obligation(id=ob_id, challenger=challenger, respondent=respondent, topic=topic)
    state.obligations.append(ob)
    state._emit("obligation_created", id=ob_id, challenger=challenger,
                respondent=respondent, topic=topic)
    return ob_id


def set_obligation_status(state: SessionState, ob_id: str, status: str, *, resolution: str = "") -> None:
    """CHAIR-only status setter. The chair may set `answered` or `conceded`
    (semantic judgments). It may NOT set `stalemate` (that is the kernel's
    termination guarantee) or `open` (creation-only) — attempts raise."""
    ob = state._find_obligation(ob_id)
    if status not in CHAIR_SETTABLE_STATUSES:
        raise ObligationError(
            f"status '{status}' is not chair-settable "
            f"(allowed: {sorted(CHAIR_SETTABLE_STATUSES)}; 'stalemate' is kernel-set)"
        )
    ob.status = status
    if resolution:
        ob.resolution = resolution
    state._emit("obligation_status", id=ob_id, status=status, resolution=resolution)


def record_exchange(state: SessionState, ob_id: str, *, changed: bool, note: str = "") -> Dict[str, Any]:
    """Record one cross-exam exchange on an obligation.

    The CHAIR supplies the semantic bit `changed` (did the turn add evidence,
    expose a contradiction, or concede?). The KERNEL counts unchanged exchanges;
    when the counter reaches stalemate_threshold on a still-open obligation, the
    kernel marks it `stalemate` (flows to arbiter as unresolved dissent). This is
    the deterministic, semantics-free half of the termination guarantee.

    Returns {"unchanged_exchanges", "stalemate": bool, "status"}.
    """
    ob = state._find_obligation(ob_id)
    ob.exchanges += 1
    became_stalemate = False
    if changed:
        ob.unchanged_exchanges = 0
    else:
        ob.unchanged_exchanges += 1
        if (
            ob.status == OBLIGATION_OPEN
            and ob.unchanged_exchanges >= state.stalemate_threshold
        ):
            ob.status = OBLIGATION_STALEMATE
            if not ob.resolution:
                ob.resolution = f"stalemate after {ob.unchanged_exchanges} unchanged exchanges"
            became_stalemate = True
    state._emit("exchange", id=ob_id, changed=changed, note=note,
                unchanged_exchanges=ob.unchanged_exchanges, status=ob.status,
                stalemate=became_stalemate)
    return {"unchanged_exchanges": ob.unchanged_exchanges, "stalemate": became_stalemate,
            "status": ob.status}


def unresolved_for_arbiter(state: SessionState) -> List[Obligation]:
    """Obligations that flow to the arbiter as unresolved dissent (open/stalemate)."""
    return [ob for ob in state.obligations if ob.status in UNRESOLVED_STATUSES]


# --------------------------------------------------------------------------- #
# Transcript
# --------------------------------------------------------------------------- #
def append_turn(
    state: SessionState,
    *,
    seat: str,
    provider: str,
    body: str,
    served_by: str = "unknown",
    ts: str,
    phase: Optional[str] = None,
    meta_extra: Optional[Dict[str, Any]] = None,
    charge_seat_call: bool = True,
) -> Dict[str, Any]:
    """Append one turn to the transcript ATOMICALLY with a per-turn sha256 digest.

    Writes the grep-able header + a `meta:` JSON line (carrying the digest) + a
    fenced body (design §5). If `state.transcript_path` is None the turn is not
    written to disk but the digest + meta are still returned/recorded.
    Charges one seat call by default (a turn is a seat call).
    """
    if state.phase in TERMINAL_PHASES:
        raise PhaseError(f"cannot append a turn in terminal phase {state.phase}")
    if charge_seat_call:
        record_seat_call(state, 1)
    state.turn_no += 1
    turn_no = state.turn_no
    ph = phase if phase is not None else state.phase
    digest = turn_digest(turn_no=turn_no, phase=ph, seat=seat, provider=provider,
                         served_by=served_by, ts=ts, body=body)
    meta: Dict[str, Any] = {
        "turn_id": f"T{turn_no:04d}",
        "digest": f"sha256:{digest}",
        "phase": ph,
        "seat": seat,
        "provider": provider,
        "served_by": served_by,
        "ts": ts,
    }
    if meta_extra:
        meta.update(meta_extra)
    header = f"### TURN {turn_no:04d} · {ph} · {seat} · {provider} · {served_by} · {ts}"
    block = (
        header
        + "\n"
        + "meta: "
        + json.dumps(meta, sort_keys=True, ensure_ascii=False)
        + "\n```\n"
        + body.rstrip("\n")
        + "\n```\n\n"
    )
    if state.transcript_path is not None:
        _atomic_append_text(Path(state.transcript_path), block)
    state._emit("turn_appended", turn_no=turn_no, seat=seat, phase=ph,
                digest=f"sha256:{digest}")
    return {"turn_no": turn_no, "digest": digest, "meta": meta, "block": block}


# --------------------------------------------------------------------------- #
# Projection / status
# --------------------------------------------------------------------------- #
def session_projection(state: SessionState, *, now: Optional[float] = None) -> Dict[str, Any]:
    by_status: Dict[str, int] = {}
    for ob in state.obligations:
        by_status[ob.status] = by_status.get(ob.status, 0) + 1
    return {
        "session_id": state.session_id,
        "phase": state.phase,
        "terminal": state.phase in TERMINAL_PHASES,
        "cross_exam_cycle": state.cross_exam_cycle,
        "max_cycles": state.budgets.max_cycles,
        "can_open_next_cycle": can_open_next_cycle(state),
        "seat_calls_used": state.seat_calls_used,
        "max_seat_calls": state.budgets.max_seat_calls,
        "seat_calls_remaining": state.budgets.max_seat_calls - state.seat_calls_used,
        "wall_clock_s": state.budgets.wall_clock_s,
        "wall_clock_elapsed": round(wall_clock_elapsed(state, now=now), 3),
        "wall_clock_remaining": round(wall_clock_remaining(state, now=now), 3),
        "quorum_status": state.quorum_status,
        "turns": state.turn_no,
        "obligations_total": len(state.obligations),
        "obligations_by_status": by_status,
        "unresolved_for_arbiter": [ob.id for ob in unresolved_for_arbiter(state)],
    }


def write_ledger(state: SessionState, ledger_path: Path | str) -> None:
    """Persist the obligation ledger as JSON (ledger.json shape, design §5)."""
    payload = {
        "session_id": state.session_id,
        "obligations": [ob.to_dict() for ob in state.obligations],
        "projection": session_projection(state),
    }
    _atomic_write_text(Path(ledger_path), json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
