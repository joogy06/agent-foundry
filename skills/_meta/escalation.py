#!/usr/bin/env python3
"""escalation.py -- the model-escalation ladder and the attempt history under it.

S081 revision 4, stream B (design 2026-09-15 section 3.1; parent design section
4.5; decisions D3, D18, D19). When a work package fails, something has to decide
whether to try again with a stronger model or to stop and ask the user. That
decision is worth exactly as much as the history it is made from, so this module
owns the history first and the ladder second.

THE STORE
---------
`~/.claude/projects/<slug>/model-attempts.jsonl` -- append-only JSONL, one row
per attempt, written under `portable_lock`, beside `astra-budget.jsonl` and by
the same slug rule (this module imports `codex_quota.project_slug` rather than
restating it: two spellings of one rule is how the two diverge).

HOME-TIER ON PURPOSE. A repo cannot pre-seed it, so a work package cannot arrive
carrying a history that says it has already failed twice and should be handed
straight to a stronger model.

FAIL-SOFT IN ONE DIRECTION ONLY. A store that cannot be read, or that has even
one unparseable row, degrades the ladder to "escalate to the user" -- never to a
silent success and never to a fresh start. An ABSENT store is not a broken one:
it is a first attempt, and it begins at the bottom of the ladder.

THE THREE PROPERTIES THAT MAKE IT TRUSTWORTHY
---------------------------------------------
1. ATTEMPT IDENTITY IS DERIVED, NEVER SUPPLIED. `record()` computes the attempt
   id from the task key and the history already on disk. A caller-supplied id is
   REFUSED as usage, not ignored: a caller that passes one has a wrong model of
   who owns the counter, and silently dropping it hides that instead of fixing
   it. This is what stops a confused or adversarial caller resetting its own
   history to buy itself more attempts.

2. REVISION LINEAGE. `task_key = plan_id + ":" + wp_id` -- the plan HASH is
   recorded on every row but is NOT part of the key, so a new `plan_hash` for the
   same `plan_id` CONTINUES the history. Re-planning is not a reset. The parent
   design keyed on `plan_hash`; the revision-4 design supersedes it, and this is
   why: a failing WP that gets re-planned would otherwise return to attempt 1
   with every earlier failure invisible, which is the exact loop the cap exists
   to close.

3. USER DECISIONS AND GATE VERDICTS ARE STICKY. A standing `user-decision` or
   gate verdict (RED, REJECTED, AUDIT_UNAVAILABLE, INDETERMINATE) cannot be
   rewritten by a later classification into something that buys a stronger
   model. A stronger model must never launder a failed gate or decide a question
   the user owns.

   A sticky row STANDS until it is superseded, and it is superseded ONLY by an
   `ok` or an ADVANCING failure that carries FRESH evidence: a trusted-runner
   hash that appears on NO earlier row of that key -- any row, not only the
   sticky one. The standing row is found by scanning the key's whole history,
   never by reading its last row, so:
     * while it stands, an advancing failure AND an `ok` are both refused unless
       they carry fresh evidence (fresh against every row of the key);
     * a non-advancing routing fact (budget-floor, quota-exhausted, ...) may
       still be recorded while it stands, and it NEVER supersedes, whatever hash
       it carries -- the hash joins the seen set all the same, so it can never
       be re-cited later as fresh (review finding N2);
     * `next_rung()` consults the standing row BEFORE any success, and an `ok` is
       terminal only while no failed row follows it.
   Neither an intervening row, nor a historical `ok`, nor a reused hash can
   launder it, and a newer sticky row becomes the standing one itself.

   An `ok` must cite fresh evidence whether or not a verdict stands: `record()`
   REFUSES an `ok` whose hash ANY earlier row of the key carried -- an `ok`, a
   failure or a routing row, superseded or not -- and writes nothing (reason
   `ok-cites-seen-evidence`; while a verdict stands the sticky refusal comes
   first). Re-certifying a re-run on a bundle the key has already seen is not a
   new result (review finding R2-01). On READ such an `ok` row, like one with no
   valid hash, is DISCOUNTED: it is not a success, and it is TRANSPARENT to
   `next_rung()`'s success and latest-row checks, so it cannot hide the row
   before it.

THE LADDER
----------
    opus #1 -> opus #2 -> takeover -> codex diagnosis (read-only) -> user

The third rung is `takeover`: a fresh-context attempt on the escalation seat's
Claude model (seat_model role `escalation`, the Claude main tier in
model_roster), carrying the attempt history. It was spelled `fable` until #291,
when the rung was renamed after the ROLE instead of a model. `fable` is still
ACCEPTED ON READ as a legacy alias of `takeover` (a history row, a report or a
reason written before the rename keeps its meaning) and is never written again.
While the Claude main tier equals the execution tier (opus/opus since roster
rev 2), a takeover is a fresh-context attempt by the same model with the
history, not a model step-up.

with a cap of 6 failed attempts per `plan_id`, summed over every WP and rung, so
a renamed or re-planned WP cannot loop. `next_rung()` returns the rung the NEXT
attempt should use; it does NOT resolve a model. Resolving a protected seat is
`seat_model`'s job and duplicating that path here would put a second resolver
inside the trust boundary.

An `ok` outcome REQUIRES a trusted-runner evidence hash, and a FRESH one: a hash
no earlier row of its task key carried (property 3). A model saying "done" is
not a result.
RECORDED LIMIT, because the distinction matters: this module checks the hash's
SHAPE (64 lowercase hex, the trusted-runner bundle hash), and a shape is a
property of a string, not proof that a bundle exists or that it corresponds to
this attempt. Binding the hash to a real bundle belongs to the trusted runner,
which is the only component holding the bundle.

Stdlib only. No import-time side effects.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_META = Path(__file__).resolve().parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))
import review_risk  # noqa: E402  (the size vocabulary's owner; pure, stdlib-only)
from codex_quota import project_slug  # noqa: E402  (ONE slug rule, not a second spelling)
from portable_lock import file_lock  # noqa: E402

# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
STORE_FILENAME = "model-attempts.jsonl"
SCHEMA_VERSION = "model-attempt.v1"
LOCK_TIMEOUT_S = 5.0

# --------------------------------------------------------------------------- #
# Rungs
# --------------------------------------------------------------------------- #
RUNG_OPUS = "opus"
#: The escalation seat's fresh-context attempt. Written from #291 on.
RUNG_TAKEOVER = "takeover"
#: The rung's pre-#291 spelling. READ-ONLY: accepted wherever a stored rung is
#: read (canonical_rung) and never written -- record() refuses it and the CLI
#: does not offer it.
RUNG_LEGACY_FABLE = "fable"
RUNG_DIAGNOSIS = "diagnosis"
RUNG_USER = "user"
#: Terminal and distinct from `user`: the task key already has a success that
#: carries trusted-runner evidence and no failure after it, so there is nothing
#: to attempt.
RUNG_NONE = "none"
#: The rungs this module WRITES and returns.
RUNGS: Tuple[str, ...] = (RUNG_OPUS, RUNG_TAKEOVER, RUNG_DIAGNOSIS, RUNG_USER, RUNG_NONE)
#: Legacy spelling -> the rung it means. Read side only.
LEGACY_RUNG_ALIASES: Dict[str, str] = {RUNG_LEGACY_FABLE: RUNG_TAKEOVER}
#: Every rung a stored row or report may carry: RUNGS plus the legacy aliases.
#: This (not RUNGS) is the execution-report.v1 `next_rung` enum.
READABLE_RUNGS: Tuple[str, ...] = RUNGS + tuple(LEGACY_RUNG_ALIASES)

#: The ladder, indexed by the number of failed attempts already on THIS task key.
#: Two opus attempts, then the takeover, then the read-only diagnosis.
#: Anything past the end is the user.
LADDER: Tuple[str, ...] = (RUNG_OPUS, RUNG_OPUS, RUNG_TAKEOVER, RUNG_DIAGNOSIS)

#: Failed attempts per `plan_id` -- summed over every WP and every rung. The 7th
#: goes to the user. "A cap of 6" means six are allowed, not that a seventh is.
MAX_FAILED_ATTEMPTS_PER_PLAN = 6

#: `needs.kind` for each terminal rung (the values WP-B2 adds to
#: `execution-report.v1.json`). `opus` and `takeover` are ordinary retries and
#: carry none.
NEEDS_KIND_BY_RUNG: Dict[str, Optional[str]] = {
    RUNG_OPUS: None,
    RUNG_TAKEOVER: None,
    RUNG_DIAGNOSIS: "escalation-diagnosis",
    RUNG_USER: "user-decision",
    RUNG_NONE: None,
}

# --------------------------------------------------------------------------- #
# Outcomes and failure classes
# --------------------------------------------------------------------------- #
OUTCOME_OK = "ok"
OUTCOME_FAILED = "failed"
OUTCOMES = frozenset({OUTCOME_OK, OUTCOME_FAILED})

#: Failure classes that ADVANCE the ladder -- a stronger model might genuinely
#: do better (design section 4.5, "counts as a failed attempt").
ESCALATING_CLASSES = frozenset({
    "implementation-failure",   # the plain case: the code is wrong
    "trusted-runner-red",       # RED on the WP's OWN acceptance tests
    "wp-timeout",               # bob.md's S/M/L wall clock
    "capability-failure",       # BLOCKED, needs.kind capability-failure
    "malformed-report",         # null or schema-invalid, after one same-model retry
})

#: Failure classes that NEVER buy a stronger model -- they go to the user
#: unchanged (design section 3.1, a CLOSED set). Gate verdicts are spelled the
#: way the gates themselves spell them, so the member-by-member test is literal.
NEVER_ESCALATES = frozenset({
    "user-decision",
    "forge-amendment-mode",
    "plan-recompile",
    "budget-floor",
    "RED",                      # gate verdicts
    "REJECTED",
    "AUDIT_UNAVAILABLE",
    "INDETERMINATE",
    "reviewer-disagreement",
    "quota-exhausted",
    "auth-or-missing-tool",
    "clarification",            # #313: a preflight question, answered by the user
})

#: #313 section 5: a `clarification` is a QUESTION, not an attempt. It never
#: advances the ladder (it is in NEVER_ESCALATES) and it never counts toward the
#: WP's failed count or the per-plan cap, so asking cannot spend a retry. It is
#: not sticky either: the answer supersedes it.
NOT_AN_ATTEMPT = frozenset({"clarification"})

#: The subset that is also STICKY: once one of these stands, no later
#: classification may rewrite it into something that advances the ladder.
#: A `budget-floor` or a `plan-recompile` is a routing fact and may legitimately
#: be superseded; a user's decision and a gate's verdict may not.
STICKY_CLASSES = frozenset({
    "user-decision", "RED", "REJECTED", "AUDIT_UNAVAILABLE", "INDETERMINATE",
})

FAILURE_CLASSES = ESCALATING_CLASSES | NEVER_ESCALATES

SOURCE_BOB = "bob"
SOURCE_WORKFLOW = "workflow"
SOURCE_MAIN_LOOP = "main-loop"
SOURCES = frozenset({SOURCE_BOB, SOURCE_WORKFLOW, SOURCE_MAIN_LOOP})

#: A trusted-runner bundle hash: 64 lowercase hex. SHAPE only -- see the module
#: docstring's recorded limit.
EVIDENCE_HASH_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)

#: Neither half of a task key may contain the separator, so splitting it back is
#: exact rather than a guess about which colon was the one that mattered.
KEY_SEPARATOR = ":"

# Reasons (stable strings; a report prints them).
REASON_LADDER = "ladder"
REASON_STICKY = "sticky-record-stands"
REASON_NEVER_ESCALATES = "class-never-escalates"
REASON_PLAN_CAP = "plan-cap-reached"
REASON_LADDER_EXHAUSTED = "ladder-exhausted"
REASON_TAKEOVER_WOULD_EDIT_TESTS = "takeover-would-edit-tests"
#: The pre-#291 spelling of the reason above. READ-ONLY: canonical_reason maps it.
REASON_LEGACY_FABLE_WOULD_EDIT_TESTS = "fable-takeover-would-edit-tests"
LEGACY_REASON_ALIASES: Dict[str, str] = {
    REASON_LEGACY_FABLE_WOULD_EDIT_TESTS: REASON_TAKEOVER_WOULD_EDIT_TESTS,
}
REASON_STORE_DEGRADED = "store-degraded"
REASON_ALREADY_OK = "already-ok-with-evidence"
REASON_RECORDED = "recorded"
REASON_STORE_UNWRITABLE = "store-unwritable"
#: An `ok` whose evidence hash an earlier row of its task key already carried,
#: refused while no sticky verdict stands (property 3; review finding R2-01).
REASON_OK_CITES_SEEN = "ok-cites-seen-evidence"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 10


def canonical_rung(value: Any) -> Any:
    """The rung a STORED value means: a legacy alias maps to its current rung,
    anything else is returned unchanged. For reading rows and reports written
    before #291; nothing in this module writes a legacy spelling."""
    if isinstance(value, str):
        return LEGACY_RUNG_ALIASES.get(value, value)
    return value


def is_readable_rung(value: Any) -> bool:
    """A rung a stored row or report may legitimately carry (legacy included)."""
    return isinstance(value, str) and value in READABLE_RUNGS


def canonical_reason(value: Any) -> Any:
    """The reason a STORED reason string means (legacy spellings mapped)."""
    if isinstance(value, str):
        return LEGACY_REASON_ALIASES.get(value, value)
    return value


class EscalationError(Exception):
    """Base class."""


class EscalationUsageError(EscalationError, ValueError):
    """An input this module refuses to guess about."""


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _home(home) -> Path:
    """The home directory to resolve the store under.

    `home=` is an explicit parameter and not merely `Path.home()` so a test can
    be structurally unable to reach the real store -- the WP's rule is that no
    test touches it, and an env var is a weaker guarantee than an argument.
    """
    return Path.home() if home is None else Path(home)


def store_path_for(project_root, *, home=None) -> Path:
    return _home(home) / ".claude" / "projects" / project_slug(project_root) / STORE_FILENAME


def lock_path_for(store_path) -> Path:
    store_path = Path(store_path)
    return store_path.with_name(store_path.name + ".lock")


# --------------------------------------------------------------------------- #
# Task keys
# --------------------------------------------------------------------------- #
def task_key_for(plan_id: str, wp_id: str) -> str:
    """`plan_id:wp_id`. The plan HASH is deliberately absent (property 2)."""
    for label, value in (("plan_id", plan_id), ("wp_id", wp_id)):
        if not isinstance(value, str) or not value.strip():
            raise EscalationUsageError("{0} must be a non-empty string, got {1!r}".format(
                label, value))
        if KEY_SEPARATOR in value:
            raise EscalationUsageError(
                "{0} must not contain {1!r} ({2!r}); the separator has to stay "
                "unambiguous or the plan id cannot be read back out".format(
                    label, KEY_SEPARATOR, value))
    return plan_id.strip() + KEY_SEPARATOR + wp_id.strip()


def split_task_key(task_key: str) -> Tuple[str, str]:
    """`plan_id:wp_id` -> (plan_id, wp_id). Exact, because neither half may
    contain the separator."""
    if not isinstance(task_key, str) or task_key.count(KEY_SEPARATOR) != 1:
        raise EscalationUsageError(
            "task_key must be exactly 'plan_id{0}wp_id', got {1!r}".format(
                KEY_SEPARATOR, task_key))
    plan_id, wp_id = task_key.split(KEY_SEPARATOR)
    if not plan_id or not wp_id:
        raise EscalationUsageError("task_key has an empty half: {0!r}".format(task_key))
    return plan_id, wp_id


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def _now_epoch(now) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.timestamp()
    if isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now):
        return float(now)
    raise EscalationUsageError(
        "now must be None, a datetime or epoch seconds, got {0!r}".format(now))


def _iso_z(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
class History:
    """Every row in the store, plus whether reading it was clean.

    `degraded` is the whole point of the class. A caller that only got a list of
    rows cannot tell "no failures yet" from "the failures were unreadable", and
    those two must not produce the same rung.
    """

    __slots__ = ("rows", "degraded", "degraded_reason", "path")

    def __init__(self, rows: Sequence[Dict[str, Any]], degraded: bool,
                 degraded_reason: Optional[str], path: Optional[Path]) -> None:
        self.rows = list(rows)
        self.degraded = degraded
        self.degraded_reason = degraded_reason
        self.path = path

    def for_key(self, task_key: str) -> List[Dict[str, Any]]:
        return [r for r in self.rows if r.get("task_key") == task_key]

    def for_plan(self, plan_id: str) -> List[Dict[str, Any]]:
        return [r for r in self.rows if r.get("plan_id") == plan_id]


def read_history(path) -> History:
    """Read the store. An ABSENT store is empty and clean; an unreadable one, or
    one with any unparseable row, is DEGRADED."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return History([], False, None, path)
    except OSError as exc:
        return History([], True, "unreadable: {0}".format(exc), path)

    rows: List[Dict[str, Any]] = []
    bad = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    if bad:
        # An incomplete history UNDER-counts failures, which would under-escalate.
        # Degrading is the only direction that cannot invent a success.
        return History(rows, True, "{0} unparseable row(s)".format(bad), path)
    return History(rows, False, None, path)


def is_evidence_hash(value: Any) -> bool:
    return isinstance(value, str) and EVIDENCE_HASH_RE.match(value) is not None


def _is_failed(row: Dict[str, Any]) -> bool:
    return row.get("outcome") == OUTCOME_FAILED


def _is_ok(row: Dict[str, Any]) -> bool:
    """An `ok` row only counts when it carries evidence. A row that claims
    success without it is not a success -- see `record()`, which refuses to
    write one, so this also guards a store edited by hand. Carrying evidence is
    necessary, not sufficient: the evidence must also be FRESH, which is a
    property of the row's place in its key's history (`_counted_rows()`)."""
    return row.get("outcome") == OUTCOME_OK and is_evidence_hash(row.get("evidence_hash"))


def _is_sticky(row: Dict[str, Any]) -> bool:
    return bool(row.get("sticky")) or row.get("failure_class") in STICKY_CLASSES


def _advances(failure_class: Any) -> bool:
    """Does this class buy another attempt?

    STRICT ON WRITE, CONSERVATIVE ON READ: `record()` refuses a class outside the
    closed vocabulary, but here -- reading rows that some later version may have
    written -- anything not known to escalate does NOT escalate. An unrecognised
    failure must never be the one that buys a stronger model.
    """
    return failure_class in ESCALATING_CLASSES


def _seen_hashes(rows: Sequence[Dict[str, Any]]) -> set:
    """Every evidence hash these rows carry -- the set FRESH is measured against.

    Every row, not only the standing one: a bundle the key has already seen
    under any outcome is not new evidence (property 3; review finding f8)."""
    return {r.get("evidence_hash") for r in rows if is_evidence_hash(r.get("evidence_hash"))}


def _supersedes(row: Dict[str, Any], seen: set) -> bool:
    """Can `row` supersede a standing sticky row? Only an evidence-bearing gate
    outcome can -- an `ok` or an ADVANCING failure -- and only when its hash is
    FRESH: on none of the rows before it, whose hashes are `seen`."""
    evidence = row.get("evidence_hash")
    if not is_evidence_hash(evidence) or evidence in seen:
        return False
    return _is_ok(row) or (_is_failed(row) and _advances(row.get("failure_class")))


def _standing_sticky(rows: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The sticky row that STANDS over one task key's rows, or None.

    One forward scan. A sticky row becomes the standing row (a newer verdict
    replaces an older one). The standing row is superseded ONLY by an `ok` or an
    ADVANCING failure that carries FRESH evidence -- a hash on no earlier row of
    the key -- and nothing then stands until a newer sticky row. Any other row
    (a non-advancing routing fact such as budget-floor or quota-exhausted, a
    failure of unknown class, a row of unknown outcome) NEVER supersedes,
    whatever hash it carries (review finding N2), and its hash still joins the
    seen set, so it can never be re-cited later as fresh. So an intervening
    routing fact cannot unshield a verdict (F1, N2) and a reused bundle cannot
    supersede one (f8). An `ok` whose hash ANY earlier row of the key carried is
    refused on write and discounted on read (R2-01); it could not supersede here
    either, because its hash is by definition already seen.
    """
    seen: set = set()
    standing: Optional[Dict[str, Any]] = None
    for row in rows:
        evidence = row.get("evidence_hash")
        if _is_sticky(row):
            standing = row
        elif _supersedes(row, seen):
            standing = None
        if is_evidence_hash(evidence):
            seen.add(evidence)
    return standing


def _counted_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One task key's rows WITHOUT a DISCOUNTED `ok` -- the view next_rung()'s
    success check and latest-row check read.

    An `ok` row is a success only if `record()` would have accepted it: it
    carries a valid evidence hash that NO earlier row of the key carried (any
    row -- ok, failed or routing, superseded or not; review finding R2-01).
    Any other `ok` row -- a store edited by hand, or written before this rule
    -- is DISCOUNTED and TRANSPARENT: left out of the view, so it neither
    answers `none` nor hides the row before it from the never-escalates check.
    The failed count, the plan cap, the attempt id and the sticky scan still
    read every row."""
    seen: set = set()
    counted: List[Dict[str, Any]] = []
    for row in rows:
        evidence = row.get("evidence_hash")
        if row.get("outcome") != OUTCOME_OK or (_is_ok(row) and evidence not in seen):
            counted.append(row)
        if is_evidence_hash(evidence):
            seen.add(evidence)
    return counted


def _ok_is_terminal(rows: Sequence[Dict[str, Any]]) -> bool:
    """True when an `ok` with evidence has NO failed row after it.

    A success is terminal only until something fails after it: a later failure
    re-enters the ladder at its failure count (review finding F2). `next_rung()`
    passes `_counted_rows()`, so a discounted `ok` is never the success this
    finds (R2-01)."""
    for row in reversed(rows):
        if _is_failed(row):
            return False
        if _is_ok(row):
            return True
    return False


# --------------------------------------------------------------------------- #
# record()
# --------------------------------------------------------------------------- #
class RecordResult:
    """What `record()` did, and if it refused, what stood in the way."""

    __slots__ = ("recorded", "reason", "row", "attempt_id", "standing", "error", "path")

    def __init__(self, recorded: bool, reason: str, row: Optional[Dict[str, Any]] = None,
                 attempt_id: Optional[int] = None,
                 standing: Optional[Dict[str, Any]] = None,
                 error: Optional[str] = None, path: Optional[Path] = None) -> None:
        self.recorded = recorded
        self.reason = reason
        self.row = row
        self.attempt_id = attempt_id
        self.standing = standing
        self.error = error
        self.path = path

    def __repr__(self) -> str:
        return "RecordResult(recorded={0!r}, reason={1!r}, attempt_id={2!r})".format(
            self.recorded, self.reason, self.attempt_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recorded": self.recorded,
            "reason": self.reason,
            "attempt_id": self.attempt_id,
            "row": self.row,
            "standing": self.standing,
            "error": self.error,
        }


def _append_row(path: Path, row: Dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass


def record(plan_id: str, wp_id: str, *, outcome: str, project_root,
           failure_class: Optional[str] = None, rung: Optional[str] = None,
           model: Optional[str] = None, evidence_hash: Optional[str] = None,
           plan_hash: Optional[str] = None, source: str = SOURCE_BOB,
           detail: Optional[str] = None, home=None, now=None,
           attempt_id: Any = None) -> RecordResult:
    """Append one attempt to the store and return what happened.

    `attempt_id` exists ONLY to be refused: identity is derived here, from the
    task key and the history already on disk (property 1).
    """
    if attempt_id is not None:
        raise EscalationUsageError(
            "attempt identity is DERIVED, never supplied: record() computes the "
            "attempt id from the task key and the history on disk. Passing "
            "attempt_id={0!r} would let a caller reset its own history.".format(attempt_id))

    task_key = task_key_for(plan_id, wp_id)
    plan_id, wp_id = split_task_key(task_key)

    if outcome not in OUTCOMES:
        raise EscalationUsageError("outcome must be one of {0}, got {1!r}".format(
            sorted(OUTCOMES), outcome))
    if source not in SOURCES:
        raise EscalationUsageError("source must be one of {0}, got {1!r}".format(
            sorted(SOURCES), source))
    if rung is not None and rung in LEGACY_RUNG_ALIASES:
        raise EscalationUsageError(
            "rung {0!r} is a legacy spelling, accepted on read only; write {1!r}".format(
                rung, LEGACY_RUNG_ALIASES[rung]))
    if rung is not None and rung not in RUNGS:
        raise EscalationUsageError("rung must be one of {0}, got {1!r}".format(
            sorted(RUNGS), rung))

    if outcome == OUTCOME_OK:
        # "A model saying done is not a result." Refusing is the only safe
        # direction: recording it as a failure would invent a verdict, and
        # recording it as a success would be the silent success this module
        # exists to prevent.
        if not is_evidence_hash(evidence_hash):
            raise EscalationUsageError(
                "an `ok` outcome requires a trusted-runner evidence hash "
                "(64 lowercase hex); got {0!r}".format(evidence_hash))
        if failure_class is not None:
            raise EscalationUsageError(
                "an `ok` outcome carries no failure_class, got {0!r}".format(failure_class))
    else:
        if failure_class not in FAILURE_CLASSES:
            raise EscalationUsageError(
                "failure_class must be one of the closed set {0}, got {1!r}".format(
                    sorted(FAILURE_CLASSES), failure_class))
        if evidence_hash is not None and not is_evidence_hash(evidence_hash):
            raise EscalationUsageError(
                "evidence_hash must be 64 lowercase hex or None, got {0!r}".format(
                    evidence_hash))

    path = store_path_for(project_root, home=home)
    now_epoch = _now_epoch(now)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
            history = read_history(path)
            mine = history.for_key(task_key)

            # ---- property 3: a standing sticky record refuses a downgrade ----
            # The standing row comes from a SCAN of the key's history, never
            # from its last row: an intervening non-advancing row (budget-floor,
            # plan-recompile, ...) is recordable, and it does not unshield it,
            # whatever hash it carries -- only an `ok` or an ADVANCING failure
            # with fresh evidence supersedes (review finding N2).
            standing = _standing_sticky(mine)
            if standing is not None and (
                    outcome == OUTCOME_OK
                    or (outcome == OUTCOME_FAILED and _advances(failure_class))):
                # The escape is the design's own words: "a later PASS never
                # erases an earlier RED/REJECTED WITHOUT FRESH EVIDENCE through
                # the same gates" -- applied to a later PASS and to a later
                # advancing failure alike. Fresh evidence is a hash this key has
                # not seen on ANY row; without one, the sticky record stands.
                fresh = (is_evidence_hash(evidence_hash)
                         and evidence_hash not in _seen_hashes(mine))
                if not fresh:
                    return RecordResult(
                        False, REASON_STICKY, None,
                        attempt_id=standing.get("attempt_id"),
                        standing=standing, path=path)

            # ---- property 3: an `ok` always cites FRESH evidence (R2-01) ----
            # Whether or not a verdict stands. An `ok` whose hash ANY earlier
            # row of the key carried -- an ok, a failure or a routing row,
            # superseded or not -- would re-certify a bundle the key has already
            # seen, so it is refused and writes nothing. `standing` names the
            # latest row that carried the hash. (While a verdict stands, the
            # refusal above has already fired, with its own reason.)
            if outcome == OUTCOME_OK and evidence_hash in _seen_hashes(mine):
                carrier = [r for r in mine if r.get("evidence_hash") == evidence_hash][-1]
                return RecordResult(
                    False, REASON_OK_CITES_SEEN, None,
                    attempt_id=carrier.get("attempt_id"),
                    standing=carrier, path=path)

            # ---- property 1: the id is derived here and nowhere else ----
            derived_id = len(mine) + 1
            row: Dict[str, Any] = {
                "schema": SCHEMA_VERSION,
                "at": _iso_z(now_epoch),
                "task_key": task_key,
                "plan_id": plan_id,
                "wp_id": wp_id,
                "attempt_id": derived_id,
                "outcome": outcome,
                "source": source,
                "sticky": failure_class in STICKY_CLASSES,
            }
            # LINEAGE: recorded so an auditor can see which revision an attempt
            # ran under, and deliberately NOT part of the key (property 2).
            if plan_hash is not None:
                row["plan_hash"] = plan_hash
            if failure_class is not None:
                row["failure_class"] = failure_class
            if rung is not None:
                row["rung"] = rung
            if model is not None:
                row["model"] = model
            if evidence_hash is not None:
                row["evidence_hash"] = evidence_hash
            if detail is not None:
                row["detail"] = detail
            _append_row(path, row)
    except EscalationUsageError:
        raise
    except Exception as exc:                       # fail-soft: never crash a caller
        return RecordResult(False, REASON_STORE_UNWRITABLE, None,
                            error="{0}: {1}".format(type(exc).__name__, exc), path=path)
    return RecordResult(True, REASON_RECORDED, row, attempt_id=derived_id, path=path)


# --------------------------------------------------------------------------- #
# next_rung()
# --------------------------------------------------------------------------- #
class NextRung:
    """The rung the NEXT attempt should use, and why."""

    __slots__ = ("rung", "task_key", "plan_id", "wp_id", "attempt_id", "reason",
                 "needs_kind", "failed_attempts", "plan_failed_attempts",
                 "size", "size_source", "risk_families", "standing", "degraded")

    def __init__(self, rung: str, task_key: str, plan_id: str, wp_id: str,
                 attempt_id: int, reason: str, failed_attempts: int,
                 plan_failed_attempts: int, size: Optional[str] = None,
                 size_source: Optional[str] = None,
                 risk_families: Sequence[str] = (),
                 standing: Optional[Dict[str, Any]] = None,
                 degraded: Optional[str] = None) -> None:
        self.rung = rung
        self.task_key = task_key
        self.plan_id = plan_id
        self.wp_id = wp_id
        self.attempt_id = attempt_id
        self.reason = reason
        self.needs_kind = NEEDS_KIND_BY_RUNG[rung]
        self.failed_attempts = failed_attempts
        self.plan_failed_attempts = plan_failed_attempts
        self.size = size
        self.size_source = size_source
        self.risk_families = tuple(risk_families)
        self.standing = standing
        self.degraded = degraded

    def __repr__(self) -> str:
        return "NextRung(rung={0!r}, reason={1!r}, attempt_id={2!r})".format(
            self.rung, self.reason, self.attempt_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rung": self.rung,
            "needs_kind": self.needs_kind,
            "task_key": self.task_key,
            "plan_id": self.plan_id,
            "wp_id": self.wp_id,
            "attempt_id": self.attempt_id,
            "reason": self.reason,
            "failed_attempts": self.failed_attempts,
            "plan_failed_attempts": self.plan_failed_attempts,
            "size": self.size,
            "size_source": self.size_source,
            "risk_families": list(self.risk_families),
            "standing": self.standing,
            "degraded": self.degraded,
        }


def next_rung(task_key: str, *, project_root, home=None,
              paths: Iterable[str] = (), symbols: Iterable[str] = (),
              size: Optional[str] = None, size_source: Optional[str] = None,
              user_request: bool = False,
              takeover_touches_tests: bool = False,
              fable_touches_tests: bool = False,
              history: Optional[History] = None) -> NextRung:
    """The rung the next attempt should use for `task_key`.

    `takeover_touches_tests` is supplied by the caller from the ACTUAL diff: a
    takeover that would edit a test file cannot complete on that attempt alone
    (design section 4.5), so it becomes a question for the user instead.
    `fable_touches_tests` is its pre-#291 spelling, kept as an alias: either one
    set means the same thing.

    `paths` / `symbols` / `size` feed `review_risk` and matter only on the
    `diagnosis` rung, where the design takes the size from section 2.1
    risk-promoted. Consultancy seats use their declared size and are not
    promoted; the diagnosis is not a consultancy seat.
    """
    plan_id, wp_id = split_task_key(task_key)
    if history is None:
        history = read_history(store_path_for(project_root, home=home))

    mine = history.for_key(task_key)
    failed = sum(1 for r in mine if _is_failed(r) and r.get("failure_class") not in NOT_AN_ATTEMPT)
    plan_failed = sum(1 for r in history.for_plan(plan_id)
                      if _is_failed(r) and r.get("failure_class") not in NOT_AN_ATTEMPT)
    next_id = len(mine) + 1

    def build(rung: str, reason: str, standing=None) -> NextRung:
        size_out = size_source_out = None
        families: Tuple[str, ...] = ()
        if rung == RUNG_DIAGNOSIS:
            assessment = review_risk.assess(paths, symbols, size=size,
                                            size_source=size_source,
                                            user_request=user_request)
            size_out = assessment.size
            size_source_out = assessment.size_source
            families = assessment.families
        return NextRung(rung, task_key, plan_id, wp_id, next_id, reason, failed,
                        plan_failed, size_out, size_source_out, families, standing,
                        history.degraded_reason if history.degraded else None)

    # A store that could not be read in full cannot answer this question, and
    # the only answer that cannot invent a success is "ask the user".
    if history.degraded:
        return build(RUNG_USER, REASON_STORE_DEGRADED)

    # A standing sticky row goes to the user unchanged -- never a retry. Checked
    # BEFORE any success: a historical `ok`, or an `ok` on the verdict's own
    # hash in a store written by hand or before this rule, must not answer
    # `none` over it. An `ok` that carried FRESH evidence has already
    # superseded the sticky row, so this order costs a genuine success nothing.
    sticky = _standing_sticky(mine)
    if sticky is not None:
        return build(RUNG_USER, REASON_STICKY, standing=sticky)

    # The success check and the latest-row check read the key's rows WITHOUT a
    # DISCOUNTED `ok` -- one record() would refuse: no valid hash, or a hash an
    # earlier row of the key carried (review finding R2-01). Transparent, not
    # merely "not a success": a stale `ok` sitting last would otherwise hide a
    # never-escalating row before it and buy a rung (F1's shape, on read). The
    # failed count, the cap and the attempt id still read every row.
    counted = _counted_rows(mine)

    # An `ok` with evidence is terminal while no failure follows it. Checked
    # before the ladder so a success is never re-attempted.
    if _ok_is_terminal(counted):
        return build(RUNG_NONE, REASON_ALREADY_OK)

    # A latest never-escalating class goes to the user unchanged -- never a retry.
    standing = counted[-1] if counted else None
    if standing is not None and _is_failed(standing) and not _advances(
            standing.get("failure_class")):
        return build(RUNG_USER, REASON_NEVER_ESCALATES, standing=standing)

    # The cap is per plan_id, summed over every WP and rung, so a renamed or
    # re-planned WP cannot loop.
    if plan_failed >= MAX_FAILED_ATTEMPTS_PER_PLAN:
        return build(RUNG_USER, REASON_PLAN_CAP, standing=standing)

    if failed >= len(LADDER):
        return build(RUNG_USER, REASON_LADDER_EXHAUSTED, standing=standing)

    rung = LADDER[failed]
    if rung == RUNG_TAKEOVER and (takeover_touches_tests or fable_touches_tests):
        return build(RUNG_USER, REASON_TAKEOVER_WOULD_EDIT_TESTS, standing=standing)
    return build(rung, REASON_LADDER, standing=standing)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="escalation.py",
        description=("The model-escalation ladder and its attempt history. "
                     "Attempt identity is derived here, never supplied."))
    parser.add_argument("--project-root", default=".",
                        help="the project whose store to use (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="append one attempt")
    rec.add_argument("--plan-id", required=True)
    rec.add_argument("--wp-id", required=True)
    rec.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    rec.add_argument("--failure-class", default=None, choices=sorted(FAILURE_CLASSES))
    rec.add_argument("--rung", default=None, choices=sorted(RUNGS))
    rec.add_argument("--model", default=None)
    rec.add_argument("--evidence-hash", default=None,
                     help="the trusted-runner bundle hash; REQUIRED for --outcome ok")
    rec.add_argument("--plan-hash", default=None,
                     help="recorded for lineage; NOT part of the task key")
    rec.add_argument("--source", default=SOURCE_BOB, choices=sorted(SOURCES))
    rec.add_argument("--detail", default=None)

    nxt = sub.add_parser("next", help="the rung the next attempt should use")
    nxt.add_argument("--task-key", required=True, metavar="PLAN_ID:WP_ID")
    nxt.add_argument("--path", action="append", default=[], metavar="PATH",
                     help="a changed path, for the diagnosis size (repeatable)")
    nxt.add_argument("--symbol", action="append", default=[], metavar="NAME")
    nxt.add_argument("--size", default=None, choices=list(review_risk.SIZES))
    nxt.add_argument("--size-source", default=None)
    nxt.add_argument("--user-request", action="store_true")
    nxt.add_argument("--takeover-touches-tests", action="store_true",
                     help="the pending takeover would edit a test file")
    # The pre-#291 spelling, kept working and hidden from --help.
    nxt.add_argument("--fable-touches-tests", dest="fable_touches_tests",
                     action="store_true", help=argparse.SUPPRESS)

    for p in (rec, nxt):
        p.add_argument("--json", action="store_true", help="emit canonical JSON")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "record":
            result = record(args.plan_id, args.wp_id, outcome=args.outcome,
                            project_root=args.project_root,
                            failure_class=args.failure_class, rung=args.rung,
                            model=args.model, evidence_hash=args.evidence_hash,
                            plan_hash=args.plan_hash, source=args.source,
                            detail=args.detail)
            if args.json:
                print(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")))
            else:
                print("recorded={0} reason={1} attempt_id={2}".format(
                    result.recorded, result.reason, result.attempt_id))
            return EXIT_OK if result.recorded else EXIT_REFUSED

        verdict = next_rung(args.task_key, project_root=args.project_root,
                            paths=args.path, symbols=args.symbol, size=args.size,
                            size_source=args.size_source,
                            user_request=args.user_request,
                            takeover_touches_tests=args.takeover_touches_tests,
                            fable_touches_tests=args.fable_touches_tests)
        if args.json:
            print(json.dumps(verdict.to_dict(), sort_keys=True, separators=(",", ":")))
        else:
            print("rung={0} needs_kind={1} attempt_id={2} reason={3}".format(
                verdict.rung, verdict.needs_kind, verdict.attempt_id, verdict.reason))
            if verdict.rung == RUNG_DIAGNOSIS:
                print("  size={0} size_source={1}".format(verdict.size, verdict.size_source))
        return EXIT_OK
    except (EscalationUsageError, review_risk.ReviewRiskError) as exc:
        print("escalation.py: error: {0}".format(exc), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
