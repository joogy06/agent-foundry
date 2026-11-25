#!/usr/bin/env python3
"""effort_policy.py -- first-attempt Claude reasoning effort, and the dispatch rows that record it.

#311 phase 1 (design docs/plans/2026-09-24-adaptive-effort-design.md, sections 3.1, 3.4, 3.5).

WHAT IT DECIDES
---------------
The reasoning effort a Claude EXECUTION dispatch runs at on its FIRST attempt, from the
work package's structural grade:

    complexity S -> low      (medium when a sensitive category is touched)
    complexity M -> medium   (high   when a sensitive category is touched)
    complexity L -> high     (never promoted: the grade never reaches xhigh)

* The grade is the work-packages.v1 field `complexity` ONLY. It already IS size (S 1-2
  files, M 3-5, L 6+), so file count is never counted a second time. No task text is read.
* "Sensitive category" = the WP's declared `files` fire at least one of the EXISTING
  review_risk.FAMILIES. review_risk's own matchers are reused as-is; this module adds none.
  A glob or directory entry (`*`, `?`, `[`, or a trailing `/`) is expanded against the
  project root and every matched file is tagged; when its coverage cannot be decided (no
  root, nothing matches yet, a pattern leaving the root, too many matches) it PROMOTES and
  the reason is recorded -- the decision fails toward the raise (#311 fix round 1 M1).
* The requested effort must be the table's value for its grade and source; xhigh and max
  belong to protected seats and explicit overrides only (check_consistency, fix round 1 M2).
* A WP without `complexity` is a PLAN VALIDATION ERROR (EffortPolicyError), never a default.
* A spawn OUTSIDE the plan schema (no grade at all) gets `high`, source `default-ungraded`:
  a short, hard task must not be starved.
* xhigh and max are not reachable from here. They belong to the protected seats
  (seat_model.ROLE_TABLE) and, in phase 2, to verified retries.

WHAT IT RECORDS
---------------
One structural row per Claude dispatch, and one per outcome, joined by `dispatch_id`, appended
to `<project_root>/.process-observations/spawn-runs.jsonl` with `tool: "claude_dispatch"`.
The DISPATCHER writes them -- the main loop, which chose the effort -- never the spawned agent
and never a hook. Rows are structural only: every string is one bounded token, and there is no
prompt, no free-text `detail`, no `reason`, and a `needs_kind` outside the closed NEEDS_KINDS set
is recorded as `invalid`, never copied (fix round 1 F2). `effort_applied` is `unknown` unless the host can
confirm the level; an inherited effort is recorded as `inherit` with no requested level, so it
can never be read as xhigh. effort_rollup.py reads these rows; nothing else consumes them yet.

CLI
---
    effort_policy.py resolve --grade S|M|L [--file PATH ...]
    effort_policy.py resolve --ungraded
    effort_policy.py wp --plan PATH --wp WP-ID          # + a fresh dispatch_id and the task key
    effort_policy.py record-dispatch --project-root R --dispatch-id D --task-key K
                     --effort-source SRC [--effort-requested LVL] [--grade G] [--attempt N]
                     [--surface workflow|headless|agent] [--agent-type bob] [--model M] [--role R]
    effort_policy.py record-outcome --project-root R --dispatch-id D --task-key K
                     --status COMPLETE|PARTIAL|FAILED|NO_REPORT [--attempt N] [--needs-kind K]
                     [--effort-applied LVL|unknown]
    effort_policy.py policy-hash
    effort_policy.py review-id  --project-root R --design-doc DOC [--issue N | --plan-id P]
    effort_policy.py record-d21-review --project-root R --design-doc DOC [--issue N | --plan-id P]
                     [--initial] --verdict V --disposition D [--raised critical=N,major=N,...]
                     [--verified ...] [--coverage full|truncated] [--user-directed --user-ref REF]
    effort_policy.py admit-fix-round --project-root R --design-doc DOC [--issue N | --plan-id P]
                     [--user-directed --user-ref REF]
    effort_policy.py admit-clarification --project-root R --plan-id P
    effort_policy.py record-exhausted-review --project-root R --design-doc DOC [--issue N | --plan-id P]
                     --outcome ran|unavailable [--raised ...] [--verified ...] [--unavailable-reason TOKEN]

D21 REVIEW ROWS (#313, design section 8; fix round 1 A, B, m3)
--------------------------------------------------------------
One `tool: "d21_review"` row per review ROUND, plus one `kind: "admitted"` row per fix round the
loop CONSUMES, in the same store and row style. They are keyed on a stable REVIEW identity: the
existing design doc's toplevel-relative path, lowercased (review_id_for; an issue or plan id is
metadata only), never on a budget cycle id that rolls over. A fix-round dispatch row binds its
admission (`--fix-admission-id`), refused under the lock when unknown or already bound elsewhere.
The rows are agent-writable JSONL: deleting them resets the loop (a stated trust-model limit). The
round number is DERIVED, never supplied: round 0 is the initial review (a second one is refused),
and every later review needs a fix round admitted before it. `admit-fix-round` refuses a second
admission for one review and a third automatic fix round (the bound is a STOP, never a pass). A
user-directed round after the loop stopped is labelled `"user"` and never re-enables automatic ones.
`admit-clarification` derives a plan's one clarification allowance from the outcome rows.

THE EXHAUSTED-BOUND REVIEW (the astra reserve U3/F5). When fix round 2's re-review still has a verified
critical or major, ONE review on the codex `escalation` seat (budget use `exhausted_review`, keyed on the
cycle id + this review id) runs on the whole cycle diff before the loop goes to the user.
`record-exhausted-review` appends its `kind: "exhausted_review"` row, linked to the review id: refused
unless both automatic rounds were admitted and the review after them is still blocking, and refused a
second time. It writes no `admitted` row and never enables one: its findings are presented to the user
with the loop's record, and a further round is user-directed or nothing.

Exit codes: 0 ok (one JSON object on stdout), 1 refused (bad input, plan validation error,
unwritable store), 2 usage. Stdlib + review_risk (+ PyYAML for a YAML plan, when present).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

_META = Path(__file__).resolve().parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import review_risk  # noqa: E402

try:  # a YAML plan needs PyYAML; a JSON plan does not
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

SCHEMA = "effort-policy.v1"
ROW_SCHEMA = "claude-dispatch.v1"

#: Every level Claude Code accepts, low to high.
LEVELS: Tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
#: What `effort_applied` says when the host cannot confirm the level it ran at.
APPLIED_UNKNOWN = "unknown"

GRADES: Tuple[str, ...] = ("S", "M", "L")
GRADE_EFFORT: Mapping[str, str] = {"S": "low", "M": "medium", "L": "high"}
#: One step up when a sensitive category is touched. L is absent on purpose (design s3.1).
PROMOTED_EFFORT: Mapping[str, str] = {"S": "medium", "M": "high"}
#: A spawn outside the plan schema, with no grade at all.
UNGRADED_EFFORT = "high"

SOURCE_GRADE = "grade"
SOURCE_PROMOTION = "promotion"
SOURCE_PROTECTED = "protected"
SOURCE_DEFAULT_UNGRADED = "default-ungraded"
SOURCE_INHERIT = "inherit"
SOURCE_OVERRIDE = "override"
#: #311 fix round 2 item 4: a level a smart-config policy file set on a tier. NOT reserved: a
#: policy file is repo/user content, so it may never reach xhigh or max.
SOURCE_POLICY = "policy"
SOURCES: Tuple[str, ...] = (SOURCE_GRADE, SOURCE_PROMOTION, SOURCE_PROTECTED,
                            SOURCE_DEFAULT_UNGRADED, SOURCE_INHERIT, SOURCE_OVERRIDE, SOURCE_POLICY)

TOOL = "claude_dispatch"
PHASE_DISPATCH = "dispatch"
PHASE_OUTCOME = "outcome"
SURFACES: Tuple[str, ...] = ("workflow", "headless", "agent")
#: execution-report.v1 statuses, plus NO_REPORT for a stage that returned nothing and (#311
#: fix round 1 m2) REFUSED for a dispatch bob-stage refused before any stage ran.
OUTCOMES: Tuple[str, ...] = ("COMPLETE", "PARTIAL", "FAILED", "NO_REPORT", "REFUSED")
#: Levels only a protected seat or an explicit override may request (#311 fix round 1 M2).
RESERVED_LEVELS = frozenset({"xhigh", "max"})
RESERVED_SOURCES = frozenset({"protected", "override"})

#: #311 fix round 1 F2: the CLOSED set of needs kinds a row may carry -- the execution-report.v1
#: `needs.kind` enum plus escalation.NEVER_ESCALATES (the gate verdicts arrive as needs kinds).
#: Anything else is recorded as NEEDS_KIND_INVALID and never copied: a report's needs.kind is
#: producer text, and a row value is later interpolated into a stage prompt.
NEEDS_KIND_INVALID = "invalid"


def _needs_kinds() -> Tuple[str, ...]:
    import escalation
    schema = json.loads((_META / "schemas" / "execution-report.v1.json").read_text(encoding="utf-8"))
    kinds = set(schema["properties"]["needs"]["properties"]["kind"]["enum"]) | set(escalation.NEVER_ESCALATES)
    return tuple(sorted(kinds))


NEEDS_KINDS: Tuple[str, ...] = _needs_kinds()

SPAWN_RUNS = Path(".process-observations") / "spawn-runs.jsonl"

#: One bounded token: ids, task keys, model aliases, needs kinds. Free text cannot pass.
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]+-]{0,199}", re.ASCII)

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2


class EffortPolicyError(ValueError):
    """An input this module refuses: a missing or unknown grade, a malformed row."""


# --------------------------------------------------------------------------- #
# #313 -- the D21 review loop's persisted round counter
# --------------------------------------------------------------------------- #
D21_TOOL = "d21_review"
D21_ROW_SCHEMA = "d21-review.v1"
#: An initial review, then at most this many fix rounds, each followed by a re-review; then the
#: user decides. workflows/bob-stage.js carries the twin (a parity test holds them equal).
MAX_FIX_ROUNDS = 2
SEVERITIES: Tuple[str, ...] = ("critical", "major", "minor", "nit")
COVERAGES: Tuple[str, ...] = ("full", "truncated")
D21_VERDICTS: Tuple[str, ...] = ("APPROVED", "NEEDS_FIXES", "BLOCKED", "UNVERIFIED")
#: `fixing` is the one non-terminal disposition: a fix round follows this review.
DISPOSITION_FIXING = "fixing"
DISPOSITIONS: Tuple[str, ...] = (DISPOSITION_FIXING, "converged", "blocked", "exhausted", "awaiting-user")
#: Terminal dispositions after which only a user-directed round may be recorded.
TERMINAL_DISPOSITIONS = frozenset(DISPOSITIONS) - {DISPOSITION_FIXING}
KIND_REVIEW, KIND_ADMITTED = "review", "admitted"
#: The astra reserve U3/F5: the one review a loop gets when it exhausts its bound. Never an admission.
KIND_EXHAUSTED_REVIEW = "exhausted_review"
EXHAUSTED_OUTCOMES: Tuple[str, ...] = ("ran", "unavailable")
#: fix round 2 item 9: the verdicts each disposition may carry.
DISPOSITION_VERDICTS: Mapping[str, frozenset] = {
    DISPOSITION_FIXING: frozenset({"NEEDS_FIXES"}),
    "converged": frozenset({"APPROVED"}),
    "blocked": frozenset({"BLOCKED", "UNVERIFIED"}),
    "exhausted": frozenset({"NEEDS_FIXES", "BLOCKED", "UNVERIFIED"}),
    "awaiting-user": frozenset({"NEEDS_FIXES", "BLOCKED", "UNVERIFIED"}),
}
#: fix round 2 item 4: what a Claude dispatch IS (bob-stage's DISPATCH_KINDS twin).
DISPATCH_KINDS: Tuple[str, ...] = ("work-package", "fix-round")
_ID32 = re.compile(r"[0-9a-f]{32}", re.ASCII)
#: The fix_round label of a round the user directed after the automatic loop stopped.
USER_ROUND = "user"


class LoopBoundError(EffortPolicyError):
    """The loop bound refuses this round: a stop, never a pass."""


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EffortDecision:
    effort: str
    source: str
    grade: Optional[str]
    families: Tuple[str, ...] = field(default_factory=tuple)
    policy_hash: str = ""
    #: Why a glob or directory entry promoted (#311 fix round 1 M1); structural, never task text.
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {"effort": self.effort, "effort_source": self.source, "grade": self.grade,
                "families": list(self.families), "policy_hash": self.policy_hash,
                "reasons": list(self.reasons)}


def policy_hash() -> str:
    """sha256 of the tables this module decides from, so a row names the policy that chose it."""
    doc = {"schema": SCHEMA, "grade_effort": dict(GRADE_EFFORT),
           "promoted_effort": dict(PROMOTED_EFFORT), "ungraded_effort": UNGRADED_EFFORT,
           "families": list(review_risk.FAMILIES)}
    blob = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


#: A WP `files` entry that is a pattern, not a path (#311 fix round 1 M1).
_GLOB_CHARS = ("*", "?", "[")
#: How many matches a glob may expand to before its coverage counts as undecidable.
GLOB_EXPANSION_CAP = 5000
REASON_UNDECIDABLE = "undecidable"


#: Brace expansion is not something pathlib's glob does, so a `{` entry is never decidable here
#: (#311 fix round 2 item 1): it is always treated as a pattern whose coverage is undecidable.
_BRACE = "{"


def _is_pattern(entry: str, root: Optional[Path] = None) -> bool:
    """A glob, a trailing-slash directory, a brace pattern, or (fix round 2 item 1) a bare
    path that names an existing DIRECTORY under `root`."""
    if any(c in entry for c in _GLOB_CHARS + (_BRACE,)) or entry.endswith(("/", "\\")):
        return True
    if root is not None:
        try:
            return (Path(root) / entry).is_dir()
        except (OSError, ValueError):
            return False
    return False


def _expand(entry: str, root: Optional[Path]) -> Tuple[Optional[list], str]:
    """(matched relative paths, why) for a glob/directory entry; None paths = undecidable."""
    text = entry.replace("\\", "/")
    if _BRACE in text:
        return None, "brace patterns are not expanded"
    if root is None:
        return None, "no project root to expand against"
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text) or ".." in text.split("/"):
        return None, "the pattern leaves the project root"
    if not any(c in text for c in _GLOB_CHARS) and not text.endswith("/"):
        text += "/"                                   # a bare directory name (item 1)
    pattern = text.rstrip("/") + "/**/*" if text.endswith("/") else text
    base = Path(root)
    try:
        matches = []
        for hit in base.glob(pattern):
            if hit.is_file():
                matches.append(hit.relative_to(base).as_posix())
                if len(matches) > GLOB_EXPANSION_CAP:
                    return None, f"more than {GLOB_EXPANSION_CAP} matches"
    except (OSError, ValueError, NotImplementedError) as exc:
        return None, f"the pattern could not be expanded ({type(exc).__name__})"
    if not matches:
        return None, "the pattern matches no file yet"
    return matches, "expanded"


def _families(files: Iterable[Any], root: Optional[Path] = None) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """(families, reasons). A plain path is tagged as-is. A glob or directory entry is expanded
    against `root` and every matched file is tagged; when coverage cannot be decided (no root,
    no match yet, a pattern outside the root, too many matches) the entry counts as touching a
    sensitive category -- the decision fails toward the raise -- and the reason is recorded."""
    paths, reasons = [], []
    undecidable = False
    for f in files or ():
        if not isinstance(f, str):
            raise EffortPolicyError(f"a declared file must be a string, got {f!r}")
        if not _is_pattern(f, root):
            paths.append(f)
            continue
        matched, why = _expand(f, root)
        if matched is None:
            undecidable = True
            reasons.append(f"{REASON_UNDECIDABLE}: {f!r} ({why}) -- promoted")
            continue
        fams = sorted({tag.family for tag in review_risk.tag_paths(matched)})
        if fams:
            reasons.append(f"{f!r} covers {', '.join(fams)} paths")
        paths.extend(matched)
    families = {tag.family for tag in review_risk.tag_paths(paths)}
    if undecidable:
        families.add(REASON_UNDECIDABLE)
    return tuple(sorted(families)), tuple(reasons)


def first_attempt_effort(grade: Optional[str], files: Iterable[Any] = (), *,
                         root: Optional[Any] = None) -> EffortDecision:
    """The first-attempt effort for one grade. `grade=None` is the outside-schema path. `root`
    is the project root glob/directory entries are expanded against (#311 fix round 1 M1)."""
    ph = policy_hash()
    if grade is None:
        return EffortDecision(UNGRADED_EFFORT, SOURCE_DEFAULT_UNGRADED, None, (), ph)
    if grade not in GRADES:
        raise EffortPolicyError(f"unknown grade {grade!r}; work-packages.v1 complexity is one of {list(GRADES)}")
    families, reasons = _families(files, Path(root) if root is not None else None)
    if families and grade in PROMOTED_EFFORT:
        return EffortDecision(PROMOTED_EFFORT[grade], SOURCE_PROMOTION, grade, families, ph, reasons)
    return EffortDecision(GRADE_EFFORT[grade], SOURCE_GRADE, grade, families, ph, reasons)


def _protected_effort(role: Any) -> str:
    """The pinned effort of a PROTECTED Claude seat, from seat_model (the only authority)."""
    import seat_model
    if role not in seat_model.PROTECTED:
        raise EffortPolicyError(f"effort_source 'protected' needs a protected role "
                                f"{sorted(seat_model.PROTECTED)}, got {role!r}")
    return seat_model.resolve(role, seat_model.CLAUDE).effort


def check_consistency(effort: Optional[str], source: str, grade: Optional[str],
                      role: Optional[str] = None) -> None:
    """The requested effort must be the one the policy gives for this grade and source.

    Fix round 1 M2: grade/promotion/default-ungraded must match the table; xhigh only for a
    protected seat or an explicit override. Fix round 2 item 2: `protected` is never
    self-declared -- it needs a role in seat_model.PROTECTED and exactly that seat's pinned
    effort; `max` is refused for every other source, so until phase 2 adds a verified
    escalation retry (seat_model pins escalation at xhigh) max is unreachable. A grade, when
    present, is S/M/L on every source (item 5)."""
    if grade is not None and grade not in GRADES:
        raise EffortPolicyError(f"grade must be one of {list(GRADES)} or absent, got {grade!r}")
    if source == SOURCE_PROTECTED:
        pinned = _protected_effort(role)
        if effort != pinned:
            raise EffortPolicyError(f"protected seat {role} is pinned at {pinned!r}, not {effort!r}")
        return
    if effort == "max":
        raise EffortPolicyError("effort 'max' is refused for every source but a verified protected escalation")
    if effort in RESERVED_LEVELS and source not in RESERVED_SOURCES:
        raise EffortPolicyError(f"effort {effort!r} is reserved for {sorted(RESERVED_SOURCES)}, not {source!r}")
    if source in (SOURCE_GRADE, SOURCE_PROMOTION):
        if grade not in GRADES:
            raise EffortPolicyError(f"effort_source {source!r} needs a grade in {list(GRADES)}, got {grade!r}")
        table = GRADE_EFFORT if source == SOURCE_GRADE else PROMOTED_EFFORT
        if grade not in table:
            raise EffortPolicyError(f"grade {grade!r} is never promoted")
        if effort != table[grade]:
            raise EffortPolicyError(f"{source} for grade {grade} is {table[grade]!r}, not {effort!r}")
    elif source == SOURCE_DEFAULT_UNGRADED:
        if grade is not None:
            raise EffortPolicyError("a default-ungraded dispatch carries no grade")
        if effort != UNGRADED_EFFORT:
            raise EffortPolicyError(f"default-ungraded is {UNGRADED_EFFORT!r}, not {effort!r}")


def for_work_package(wp: Mapping[str, Any], root: Optional[Any] = None) -> EffortDecision:
    """The first-attempt effort for one work-packages.v1 WP. No `complexity` is refused."""
    if not isinstance(wp, Mapping):
        raise EffortPolicyError(f"a work package must be a mapping, got {type(wp).__name__}")
    wp_id = wp.get("id", "<no id>")
    complexity = wp.get("complexity")
    if complexity is None:
        raise EffortPolicyError(
            f"plan validation error: work package {wp_id!r} has no `complexity` "
            f"(required by work-packages.v1; never defaulted)")
    files = wp.get("files") or []
    if not isinstance(files, list):
        raise EffortPolicyError(f"work package {wp_id!r}: `files` must be a list")
    return first_attempt_effort(complexity, files, root=root)


def load_plan(plan_path: Any) -> Dict[str, Any]:
    path = Path(plan_path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        doc = json.loads(text)
    elif yaml is not None:
        doc = yaml.safe_load(text)
    else:  # pragma: no cover
        raise EffortPolicyError("PyYAML is not installed; pass a JSON plan")
    if not isinstance(doc, dict) or not isinstance(doc.get("work_packages"), list):
        raise EffortPolicyError(f"{path} is not a work-packages.v1 plan (no work_packages list)")
    return doc


def plan_work_package(plan: Mapping[str, Any], wp_id: str) -> Mapping[str, Any]:
    for wp in plan.get("work_packages") or []:
        if isinstance(wp, Mapping) and wp.get("id") == wp_id:
            return wp
    raise EffortPolicyError(f"no work package {wp_id!r} in plan {plan.get('plan_id')!r}")


def task_key_for(plan_id: Any, wp_id: str) -> str:
    """`plan_id:wp_id` -- escalation.py's rule, imported, never restated. A missing or empty
    plan_id is refused (#311 fix round 1 m4): "None:WP-1" would join unrelated plans."""
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise EffortPolicyError(f"the plan has no plan_id (got {plan_id!r}); a task key needs one")
    import escalation
    return escalation.task_key_for(plan_id, wp_id)


def new_dispatch_id() -> str:
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _token(value: Any, what: str, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise EffortPolicyError(f"{what} must be one bounded token (no free text), got {value!r}")
    return value


def _choice(value: Any, allowed: Tuple[str, ...], what: str, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if value not in allowed:
        raise EffortPolicyError(f"{what} must be one of {list(allowed)}, got {value!r}")
    return value


def _attempt(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EffortPolicyError(f"attempt must be a positive integer, got {value!r}")
    return value


def _base(phase: str, dispatch_id: str, task_key: str, attempt: int) -> Dict[str, Any]:
    # The spawn-runs base keys, so every existing reader (rollup.py spawn_cost) tolerates the row.
    return {
        "ts": _now(), "tool": TOOL, "row_schema": ROW_SCHEMA, "phase": phase,
        "invocation_id": dispatch_id, "dispatch_id": dispatch_id, "task_key": task_key,
        "attempt": attempt, "cycle_id": None, "component_id": None, "bundle_hash": None,
        "request_id": None, "cost_usd": None, "duration_ms": None, "num_turns": None,
        "wall_clock_s": None,
    }


def dispatch_row(*, dispatch_id: str, task_key: str, effort_source: str,
                 effort_requested: Optional[str] = None, grade: Optional[str] = None,
                 policy_hash_value: Optional[str] = None, attempt: int = 1,
                 surface: str = "workflow", agent_type: Optional[str] = None,
                 model: Optional[str] = None, role: Optional[str] = None,
                 effort_applied: str = APPLIED_UNKNOWN, dispatch_kind: Optional[str] = None,
                 fix_admission_id: Optional[str] = None,
                 review_id: Optional[str] = None) -> Dict[str, Any]:
    """The row a dispatcher writes BEFORE it launches the stage. Validated, never free text."""
    _token(dispatch_id, "dispatch_id")
    _token(task_key, "task_key")
    _choice(effort_source, SOURCES, "effort_source")
    _choice(effort_requested, LEVELS, "effort_requested", optional=True)
    _choice(effort_applied, LEVELS + (APPLIED_UNKNOWN,), "effort_applied")
    _choice(surface, SURFACES, "surface")
    _token(grade, "grade", optional=True)
    _token(agent_type, "agent_type", optional=True)
    _token(model, "model", optional=True)
    _token(role, "role", optional=True)
    if effort_source == SOURCE_INHERIT:
        # An inherited level is unknowable here: it must never be labelled xhigh (or anything).
        if effort_requested is not None or effort_applied != APPLIED_UNKNOWN:
            raise EffortPolicyError("an inherited effort records no requested level and effort_applied=unknown")
    elif effort_requested is None:
        raise EffortPolicyError(f"effort_source {effort_source!r} requires effort_requested")
    if effort_source in (SOURCE_GRADE, SOURCE_PROMOTION) and grade is None:
        raise EffortPolicyError(f"effort_source {effort_source!r} requires the grade it came from")
    if effort_source != SOURCE_INHERIT:
        check_consistency(effort_requested, effort_source, grade, role)
    row = _base(PHASE_DISPATCH, dispatch_id, task_key, _attempt(attempt))
    row.update({
        "grade": grade, "effort_requested": effort_requested, "effort_applied": effort_applied,
        "effort_source": effort_source,
        "policy_hash": policy_hash_value if policy_hash_value is not None else policy_hash(),
        "surface": surface, "agent_type": agent_type, "model": model, "role": role,
        "status": "dispatched", **_binding(dispatch_kind, fix_admission_id, review_id),
    })
    _token(row["policy_hash"], "policy_hash")
    return row


def _binding(dispatch_kind: Optional[str], fix_admission_id: Optional[str],
             review_id: Optional[str]) -> Dict[str, Any]:
    """The fix-admission binding a dispatch/outcome row carries (fix round 2 item 4)."""
    _choice(dispatch_kind, DISPATCH_KINDS, "dispatch_kind", optional=True)
    if fix_admission_id is not None and _ID32.fullmatch(str(fix_admission_id)) is None:
        raise EffortPolicyError(f"fix_admission_id must be 32 hex, got {fix_admission_id!r}")
    if dispatch_kind == "fix-round" and fix_admission_id is None:
        raise EffortPolicyError("a fix-round dispatch needs its fix_admission_id (effort_policy.py admit-fix-round)")
    if dispatch_kind != "fix-round" and fix_admission_id is not None:
        raise EffortPolicyError("fix_admission_id belongs on a fix-round dispatch only")
    return {"dispatch_kind": dispatch_kind, "fix_admission_id": fix_admission_id,
            "review_id": _review_id(review_id) if review_id is not None else None}


def outcome_row(*, dispatch_id: str, task_key: str, status: str, attempt: int = 1,
                needs_kind: Optional[str] = None,
                effort_applied: str = APPLIED_UNKNOWN,
                clarification_asked: bool = False, dispatch_kind: Optional[str] = None,
                fix_admission_id: Optional[str] = None, review_id: Optional[str] = None) -> Dict[str, Any]:
    """The row a dispatcher writes AFTER the stage returns, joined to its dispatch row."""
    _token(dispatch_id, "dispatch_id")
    _token(task_key, "task_key")
    _choice(status, OUTCOMES, "status")
    if needs_kind is not None and needs_kind not in NEEDS_KINDS:
        needs_kind = NEEDS_KIND_INVALID   # F2: a structural code, never the producer's text
    _choice(effort_applied, LEVELS + (APPLIED_UNKNOWN,), "effort_applied")
    row = _base(PHASE_OUTCOME, dispatch_id, task_key, _attempt(attempt))
    row.update({"status": status, "needs_kind": needs_kind, "effort_applied": effort_applied,
                "model": None, "clarification_asked": clarification_asked is True,
                **_binding(dispatch_kind, fix_admission_id, review_id)})
    return row


def store_path(project_root: Any) -> Path:
    return project_root_of(project_root) / SPAWN_RUNS


def record(project_root: Any, row: Mapping[str, Any]) -> Path:
    """Append one row (canonical JSON, O_APPEND) and return the store path. Raises on failure:
    the dispatcher decides whether a lost row blocks it (bob.md: it does not)."""
    if row.get("tool") != TOOL or row.get("phase") not in (PHASE_DISPATCH, PHASE_OUTCOME):
        raise EffortPolicyError("only rows built by dispatch_row() / outcome_row() are recorded")
    with _file_lock(project_root):
        _store_rows(project_root)          # round 3 item 8: a corrupt store refuses every write
        return _append(project_root, row)


def record_dispatch(project_root: Any, row: Mapping[str, Any]) -> Dict[str, Any]:
    """Append a dispatch row, checked UNDER THE LOCK against a store that must read cleanly. A
    fix-round row's admission must be the LIVE one (#313 round 2 item 4, round 3 items 5-6): an
    `admitted` row of the same review that is still that review's last row -- no re-review has
    followed it, so the round it admitted is the round in progress -- and it may not be bound to
    another dispatch. A retry of the same dispatch_id re-binds only with the same task_key and
    review. bob-stage cannot see the store, so this is where a forged, stale or replayed admission
    is refused."""
    if row.get("tool") != TOOL or row.get("phase") != PHASE_DISPATCH:
        raise EffortPolicyError("only rows built by dispatch_row() are recorded here")
    adm = row.get("fix_admission_id")
    with _file_lock(project_root):
        rows = _store_rows(project_root)
        if adm is not None:
            rid = _canon_rid(row.get("review_id"))
            known = next((o for o in rows if o.get("tool") == D21_TOOL and o.get("kind") == KIND_ADMITTED
                          and o.get("admission_id") == adm), None)
            if known is None:
                raise EffortPolicyError(f"fix admission {adm} is unknown: no admit-fix-round issued it")
            if rid != _canon_rid(known.get("review_id")):
                raise EffortPolicyError(f"fix admission {adm} is for review {known.get('review_id')!r}, "
                                        f"not {row.get('review_id')!r}")
            loop = [o for o in rows if o.get("tool") == D21_TOOL and _canon_rid(o.get("review_id")) == rid]
            if not loop or loop[-1].get("admission_id") != adm:
                raise EffortPolicyError(f"fix admission {adm} is stale: a later review or admission follows it")
            for o in rows:
                if o.get("tool") == TOOL and o.get("phase") == PHASE_DISPATCH and o.get("fix_admission_id") == adm:
                    same = (o.get("dispatch_id") == row.get("dispatch_id") and o.get("task_key") == row.get("task_key")
                            and _canon_rid(o.get("review_id")) == rid)
                    if not same:
                        raise EffortPolicyError(f"fix admission {adm} is already bound to dispatch "
                                                f"{o.get('dispatch_id')} ({o.get('task_key')})")
        _append(project_root, row)
    return dict(row)


def _store_rows(project_root: Any) -> list:
    """Every row of the store, FAIL CLOSED (#313 fix round 2 item 10): a non-blank line that is not
    UTF-8 JSON (a corrupted or truncated row) raises, naming its line number, because a silently
    skipped `admitted`, review or clarification row would under-count and grant what it should
    refuse. Only the read-only effort_rollup skips such lines, and it reports how many."""
    path = store_path(project_root)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    rows = []
    for n, raw in enumerate(data.split(b"\n"), 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise EffortPolicyError(f"{path}: line {n} is not a JSON row (corrupt or truncated); refusing "
                                    f"rather than under-counting -- stop and ask the user") from None
        if not isinstance(obj, dict):
            raise EffortPolicyError(f"{path}: line {n} is not a JSON object; refusing -- stop and ask the user")
        rows.append(obj)
    return rows


def _append(project_root: Any, row: Mapping[str, Any]) -> Path:
    path = store_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)
    return path


def _counts(value: Any, what: str) -> Dict[str, int]:
    """{severity: n} over SEVERITIES; every severity present, absent ones 0."""
    out = {s: 0 for s in SEVERITIES}
    for key, n in (value or {}).items():
        if key not in SEVERITIES:
            raise EffortPolicyError(f"{what}: severity must be one of {list(SEVERITIES)}, got {key!r}")
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise EffortPolicyError(f"{what}: {key} must be a non-negative integer, got {n!r}")
        out[key] = n
    return out


def _git(base: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", "-C", str(base), *args], capture_output=True, text=True,
                              encoding="utf-8", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def worktree_root_of(path: Any) -> Path:
    """The git toplevel of the worktree containing `path`, else `path` resolved. Design doc paths
    are relative to this."""
    base = Path(path).resolve()
    top = _git(base, "rev-parse", "--show-toplevel")
    return Path(top).resolve() if top else base


def project_root_of(path: Any) -> Path:
    """Where the store lives: the MAIN worktree (the parent of `--git-common-dir`), so a subdirectory,
    an absolute root and every linked worktree name ONE ledger (#313 fix round 1 A, round 3 item 7).
    Outside git: `path` resolved."""
    base = Path(path).resolve()
    common = _git(base, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common and Path(common).name == ".git":
        return Path(common).resolve().parent
    return worktree_root_of(base)


def review_id_for(project_root: Any, design_doc: Any, *, issue: Any = None, plan_id: Any = None) -> str:
    """The stable D21 REVIEW identity: the design doc's path relative to the git toplevel,
    lowercased, and the doc must EXIST (fix round 2 item 3). A relative path resolves against the
    toplevel, never the cwd. `issue` / `plan_id` are accepted as metadata only and never change
    the key, so no anchor spelling, cwd, case or new cycle can mint a fresh counter."""
    top = worktree_root_of(project_root)
    doc = Path(design_doc)
    doc = (doc if doc.is_absolute() else top / doc).resolve()
    try:
        rel = doc.relative_to(top).as_posix()
    except ValueError:
        raise EffortPolicyError(f"design doc {design_doc!r} is outside the project {top}") from None
    if not doc.is_file():
        raise EffortPolicyError(f"design doc {rel!r} does not exist under {top}; the review is keyed on it")
    rid = rel.lower()
    _token(rid, "review_id")
    return rid


def _canon_rid(value: Any) -> Optional[str]:
    """A stored review_id in its canonical form: a pre-round-2 row stored `<anchor>:<path>`; the
    path part is the key (#313 round 3 item 3). Paths carry no colon, so the split is exact."""
    if not isinstance(value, str):
        return None
    return value.split(":", 1)[1].lower() if ":" in value else value.lower()


def _review_id(value: Any) -> str:
    if not isinstance(value, str):
        raise EffortPolicyError(f"review_id must be a string, got {value!r}")
    rid = value.lower()
    _token(rid, "review_id")
    return rid


def _lock_path(project_root: Any) -> Path:
    return store_path(project_root).parent / ".write.lock"


def _file_lock(project_root: Any):
    import portable_lock
    return portable_lock.file_lock(_lock_path(project_root), timeout=10)


def read_d21_rows(project_root: Any, review_id: str) -> list:
    """Every d21_review row (review and admitted) of one review identity, in file order. STRICT:
    an unparseable line refuses (fix round 2 item 10) -- skipping it would under-count rounds."""
    rid = _canon_rid(_review_id(review_id))
    return [r for r in _store_rows(project_root)
            if r.get("tool") == D21_TOOL and _canon_rid(r.get("review_id")) == rid]


def _is_user(row: Mapping[str, Any]) -> bool:
    return row.get("user_directed") is True          # a truthy non-True value is NOT user-directed


def _reviews(rows: Iterable[Mapping[str, Any]]) -> list:
    return [r for r in rows if r.get("kind") == KIND_REVIEW]


def _automatic_admissions(rows: Iterable[Mapping[str, Any]]) -> int:
    return sum(1 for r in rows if r.get("kind") == KIND_ADMITTED and not _is_user(r))


def _loop_stopped(rows: Iterable[Mapping[str, Any]]) -> bool:
    """True once any review stopped the automatic loop or any user round ran."""
    return any((r.get("kind") == KIND_REVIEW and r.get("disposition") in TERMINAL_DISPOSITIONS) or _is_user(r)
               for r in rows)


def _user_ref(user_directed: bool, user_ref: Any) -> Optional[str]:
    """A user-directed round names the user's own message (a quote or a timestamp). PROVENANCE,
    not authentication: it records who is claimed to have asked (fix round 2 item 5)."""
    if user_directed is not True:
        return None
    if not isinstance(user_ref, str) or not user_ref.strip() or len(user_ref) > 200 or "\n" in user_ref:
        raise EffortPolicyError("a user-directed round needs --user-ref: one line (<= 200 chars) quoting or "
                                "timestamping the user's own message")
    return user_ref.strip()


def admit_fix_round(project_root: Any, review_id: str, *, user_directed: bool = False,
                    user_ref: Optional[str] = None) -> Dict[str, Any]:
    """CONSUME the next fix round: append an `admitted` row and return the admission a bob-stage fix
    dispatch carries. Refused (LoopBoundError) before a review, twice for one review, after the loop
    stopped (automatic), before it stopped (user-directed), and past MAX_FIX_ROUNDS."""
    rid = _review_id(review_id)
    ref = _user_ref(user_directed, user_ref)
    with _file_lock(project_root):
        rows = read_d21_rows(project_root, rid)
        if not _reviews(rows):
            raise LoopBoundError(f"review {rid}: no review is recorded yet; a fix round follows a review")
        if rows[-1].get("kind") == KIND_ADMITTED:
            raise LoopBoundError(f"review {rid}: a fix round is already admitted; record its re-review first")
        last = _reviews(rows)[-1]
        if user_directed:
            if not _loop_stopped(rows):
                raise LoopBoundError(f"review {rid}: the automatic loop is still running; a user round follows it")
            fix_round: Any = USER_ROUND
        else:
            if _loop_stopped(rows) or last.get("disposition") != DISPOSITION_FIXING:
                raise LoopBoundError(f"review {rid}: the last review's disposition is {last.get('disposition')!r}; "
                                     f"no automatic fix round follows it")
            fix_round = _automatic_admissions(rows) + 1
            if fix_round > MAX_FIX_ROUNDS:
                raise LoopBoundError(f"review {rid}: fix round {fix_round} exceeds the bound of {MAX_FIX_ROUNDS}")
        row = {"ts": _now(), "tool": D21_TOOL, "row_schema": D21_ROW_SCHEMA, "kind": KIND_ADMITTED,
               "review_id": rid, "fix_round": fix_round, "admission_id": new_dispatch_id(),
               "user_directed": user_directed is True, "user_ref": ref}
        _append(project_root, row)
    return {"review_id": rid, "fix_round": fix_round, "admission_id": row["admission_id"],
            "max_fix_rounds": MAX_FIX_ROUNDS, "user_ref": ref}


def d21_review_row(*, review_id: str, round_: int, raised: Any = None, verified: Any = None,
                   coverage: str = "full", verdict: str, disposition: str, bound_hit: bool = False,
                   user_directed: bool = False, design_doc: Optional[str] = None,
                   user_ref: Optional[str] = None) -> Dict[str, Any]:
    """One D21 review round, structural only (counts and closed enums; no finding text)."""
    rid = _review_id(review_id)
    if isinstance(round_, bool) or not isinstance(round_, int) or round_ < 0:
        raise EffortPolicyError(f"round must be a non-negative integer, got {round_!r}")
    _choice(coverage, COVERAGES, "coverage")
    _choice(verdict, D21_VERDICTS, "verdict")
    _choice(disposition, DISPOSITIONS, "disposition")
    raised_c, verified_c = _counts(raised, "raised"), _counts(verified, "verified")
    for s in SEVERITIES:
        if verified_c[s] > raised_c[s]:
            raise EffortPolicyError(f"verified {s} ({verified_c[s]}) exceeds raised ({raised_c[s]})")
    blocking = verified_c["critical"] + verified_c["major"]
    if disposition == "converged" and (verdict != "APPROVED" or blocking):
        raise EffortPolicyError("converged needs verdict APPROVED and no verified critical or major finding")
    if disposition == DISPOSITION_FIXING and (verdict != "NEEDS_FIXES" or not blocking):
        raise EffortPolicyError("fixing needs verdict NEEDS_FIXES and at least one verified critical or major finding")
    # fix round 2 item 9: every disposition has its verdicts; `exhausted` only once the bound is hit.
    if verdict not in DISPOSITION_VERDICTS[disposition]:
        raise EffortPolicyError(f"{disposition} needs a verdict in {sorted(DISPOSITION_VERDICTS[disposition])}, not {verdict}")
    if disposition == "exhausted" and not bound_hit:
        raise EffortPolicyError("exhausted means the fix-round bound was hit; it was not")
    return {
        "ts": _now(), "tool": D21_TOOL, "row_schema": D21_ROW_SCHEMA, "kind": KIND_REVIEW,
        "review_id": rid, "design_doc": design_doc, "round": round_,
        "findings_raised": raised_c, "findings_verified": verified_c, "coverage": coverage,
        "verdict": verdict, "bound_hit": bool(bound_hit), "disposition": disposition,
        "user_directed": user_directed is True, "user_ref": user_ref,
        "invocation_id": None, "cost_usd": None, "duration_ms": None, "num_turns": None,
        "wall_clock_s": None,
    }


def record_d21_review(project_root: Any, *, review_id: str, initial: bool, raised: Any = None,
                      verified: Any = None, coverage: str = "full", verdict: str, disposition: str,
                      user_directed: bool = False, design_doc: Optional[str] = None,
                      user_ref: Optional[str] = None) -> Dict[str, Any]:
    """Append the next review row of ONE round sequence (round = reviews so far; 0 = initial).

    The first row is `initial` and a second initial for the same identity is refused. Every later
    row needs the round admitted before it (automatic, or user-directed after the loop stopped), so
    re-reviews and admissions alternate. `fixing` once the automatic fix rounds are spent is refused:
    a third automatic fix round never starts. The read and the append hold the store's write lock."""
    rid = _review_id(review_id)
    ref = _user_ref(user_directed, user_ref)
    with _file_lock(project_root):
        rows = read_d21_rows(project_root, rid)
        if initial:
            if rows:
                raise LoopBoundError(f"review {rid} already has rows; a second round-0 review is refused")
            if user_directed:
                raise EffortPolicyError("the initial review is never user-directed")
        else:
            if not rows:
                raise LoopBoundError(f"review {rid} has no initial review; record it with --initial")
            last = rows[-1]
            if last.get("kind") != KIND_ADMITTED:
                raise LoopBoundError(f"review {rid}: no fix round was admitted since the last review")
            if _is_user(last) != (user_directed is True):
                raise LoopBoundError(f"review {rid}: the admitted round is "
                                     f"{'user-directed' if _is_user(last) else 'automatic'}; record it as such")
        used = _automatic_admissions(rows)
        if (disposition == DISPOSITION_FIXING and user_directed is not True and used >= MAX_FIX_ROUNDS):
            raise LoopBoundError(f"review {rid}: {used} fix rounds are spent; a third automatic fix round is "
                                 f"refused -- record exhausted, awaiting-user, blocked or converged")
        row = d21_review_row(review_id=rid, round_=len(_reviews(rows)), raised=raised, verified=verified,
                             coverage=coverage, verdict=verdict, disposition=disposition,
                             bound_hit=used >= MAX_FIX_ROUNDS, user_directed=user_directed is True,
                             design_doc=design_doc if design_doc is not None else rid, user_ref=ref)
        _append(project_root, row)
    return row


def record_exhausted_review(project_root: Any, review_id: str, *, outcome: str, raised: Any = None,
                            verified: Any = None, unavailable_reason: Optional[str] = None) -> Dict[str, Any]:
    """Append the ONE exhausted-bound review row of a review identity (the astra reserve U3/F5).

    Refused (LoopBoundError) unless the loop is exhausted - both automatic fix rounds admitted, the last row
    the review after them, bound_hit and still carrying a verified critical or major - and refused for a
    second exhausted review of the same identity. `outcome` is `ran` (the escalation-seat review ran; its
    counts are recorded) or `unavailable` (codex could not serve it: `unavailable_reason` names the token,
    and the loop goes to the user without it). The row is never an admission: the loop's bound is a STOP.
    """
    rid = _review_id(review_id)
    _choice(outcome, EXHAUSTED_OUTCOMES, "outcome")
    if outcome == "unavailable":
        _token(unavailable_reason, "unavailable_reason")
    elif unavailable_reason is not None:
        raise EffortPolicyError("unavailable_reason applies to outcome 'unavailable' only")
    raised_c, verified_c = _counts(raised, "raised"), _counts(verified, "verified")
    for s in SEVERITIES:
        if verified_c[s] > raised_c[s]:
            raise EffortPolicyError(f"verified {s} ({verified_c[s]}) exceeds raised ({raised_c[s]})")
    with _file_lock(project_root):
        rows = read_d21_rows(project_root, rid)
        if any(r.get("kind") == KIND_EXHAUSTED_REVIEW for r in rows):
            raise LoopBoundError(f"review {rid}: its one exhausted-bound review is already recorded")
        if _automatic_admissions(rows) < MAX_FIX_ROUNDS or not rows or rows[-1].get("kind") != KIND_REVIEW:
            raise LoopBoundError(f"review {rid}: the loop has not exhausted its {MAX_FIX_ROUNDS} fix rounds with a "
                                 f"re-review after the last; the exhausted-bound review follows that re-review")
        last = rows[-1]
        blocking = sum(int((last.get("findings_verified") or {}).get(k, 0)) for k in ("critical", "major"))
        if _is_user(last) or last.get("bound_hit") is not True or not blocking:
            raise LoopBoundError(f"review {rid}: the last review ({last.get('disposition')!r}) leaves no verified "
                                 f"critical or major open at the bound; there is nothing to escalate")
        row = {"ts": _now(), "tool": D21_TOOL, "row_schema": D21_ROW_SCHEMA, "kind": KIND_EXHAUSTED_REVIEW,
               "review_id": rid, "after_round": last.get("round"), "outcome": outcome,
               "unavailable_reason": unavailable_reason, "codex_use": "exhausted_review", "role": "escalation",
               "findings_raised": raised_c, "findings_verified": verified_c, "admits_fix_round": False}
        _append(project_root, row)
    return row


def admit_clarification(project_root: Any, plan_id: str) -> Dict[str, Any]:
    """The plan's clarification allowance, DERIVED from the persisted rows (#313 fix rounds 1 D, 2
    item 6, round 3 item 8), keyed on plan_id (case-insensitively) so later WPs inherit it. `used`
    once any dispatch of the plan returned a clarification or asked one bob-stage demoted
    (`clarification_asked`). A dispatch attempt with no outcome row yet -- matched on (dispatch_id,
    attempt) -- is UNKNOWN, and unknown FAILS CLOSED (clarification_used true, state unknown): it may
    have asked. Run this BEFORE record-dispatch of the dispatch it admits. Reads under the lock and
    writes nothing -- the outcome row the dispatcher records IS the spend. The admission is
    caller-supplied to bob-stage and enforced at record time; bob-stage checks only its shape."""
    _token(plan_id, "plan_id")
    prefix = plan_id.lower() + ":"
    prior = None
    dispatched, finished = [], set()
    with _file_lock(project_root):
        rows = _store_rows(project_root)
    for obj in rows:
        if obj.get("tool") != TOOL or not str(obj.get("task_key", "")).lower().startswith(prefix):
            continue
        key = (obj.get("dispatch_id"), obj.get("attempt"))
        if obj.get("phase") == PHASE_DISPATCH:
            dispatched.append(key)
        elif obj.get("phase") == PHASE_OUTCOME:
            finished.add(key)
            if obj.get("needs_kind") == "clarification" or obj.get("clarification_asked") is True:
                prior = obj.get("dispatch_id")
    open_ = sorted({d for d, att in dispatched if (d, att) not in finished})
    state = "used" if prior is not None else ("unknown" if open_ else "clear")
    return {"plan_id": plan_id, "clarification_used": state != "clear", "prior_dispatch_id": prior,
            "state": state, "open_dispatches": open_}


def _parse_counts(text: Optional[str]) -> Dict[str, int]:
    """`major=2,minor=1` -> {major: 2, minor: 1}."""
    out: Dict[str, int] = {}
    for part in (text or "").split(","):
        if not part.strip():
            continue
        key, sep, val = part.partition("=")
        if not sep or not val.strip().isdigit():
            raise EffortPolicyError(f"a count is severity=N, got {part!r}")
        out[key.strip()] = int(val)
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def exit(self, status=0, message=None):
        if status == 0:
            raise SystemExit(0)
        raise _UsageError(message.strip() if message else "usage error")

    def error(self, message):
        self.print_usage(sys.stderr)
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="effort_policy.py", description="First-attempt Claude effort and its dispatch rows (#311).")
    sub = p.add_subparsers(dest="command")
    r = sub.add_parser("resolve", help="the first-attempt effort for a grade")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--grade", choices=GRADES)
    g.add_argument("--ungraded", action="store_true", help="a spawn outside the plan schema")
    r.add_argument("--file", action="append", default=[], help="a declared file (repeatable)")
    w = sub.add_parser("wp", help="the first-attempt effort for one WP of a work-packages.v1 plan")
    w.add_argument("--plan", required=True)
    w.add_argument("--wp", required=True)
    d = sub.add_parser("record-dispatch", help="append the dispatch row (before launching the stage)")
    o = sub.add_parser("record-outcome", help="append the outcome row (after the stage returns)")
    for cmd in (d, o):
        cmd.add_argument("--project-root", required=True)
        cmd.add_argument("--dispatch-id", required=True)
        cmd.add_argument("--task-key", required=True)
        cmd.add_argument("--attempt", type=int, default=1)
        cmd.add_argument("--effort-applied", default=APPLIED_UNKNOWN)
        cmd.add_argument("--dispatch-kind", choices=DISPATCH_KINDS, required=True)
        cmd.add_argument("--fix-admission-id", help="a fix-round dispatch's admission_id (refused if unknown or reused)")
        cmd.add_argument("--review-id", help="the admission's review_id")
    d.add_argument("--effort-source", required=True, choices=SOURCES)
    d.add_argument("--effort-requested", choices=LEVELS)
    d.add_argument("--grade")
    d.add_argument("--policy-hash")
    d.add_argument("--surface", default="workflow", choices=SURFACES)
    d.add_argument("--agent-type")
    d.add_argument("--model")
    d.add_argument("--role")
    o.add_argument("--status", required=True, choices=OUTCOMES)
    o.add_argument("--needs-kind")
    sub.add_parser("policy-hash", help="print the policy hash")
    o.add_argument("--clarification-asked", action="store_true",
                   help="the stage asked a clarification (bob-stage dispatch.clarification_asked)")
    ri = sub.add_parser("review-id", help="print the derived D21 review identity (#313)")
    rv = sub.add_parser("record-d21-review", help="append one D21 review round's row (#313)")
    ad = sub.add_parser("admit-fix-round", help="consume the next fix round, or exit 1 (#313)")
    for cmd in (ri, rv, ad):
        cmd.add_argument("--project-root", required=True)
        cmd.add_argument("--design-doc", required=True)
        anchor = cmd.add_mutually_exclusive_group()          # metadata only; never part of the key
        anchor.add_argument("--issue")
        anchor.add_argument("--plan-id")
    for cmd in (rv, ad):
        cmd.add_argument("--user-ref", help="with --user-directed: the user's own message, quoted or timestamped")
    ad.add_argument("--user-directed", action="store_true")
    rv.add_argument("--initial", action="store_true", help="the round-0 review (refused if one exists)")
    ex = sub.add_parser("record-exhausted-review",
                        help="record the one exhausted-bound review of a D21 loop (the astra reserve U3)")
    ex.add_argument("--project-root", required=True)
    ex.add_argument("--design-doc", required=True)
    ex_anchor = ex.add_mutually_exclusive_group()
    ex_anchor.add_argument("--issue")
    ex_anchor.add_argument("--plan-id")
    ex.add_argument("--outcome", required=True, choices=EXHAUSTED_OUTCOMES)
    ex.add_argument("--raised", default="")
    ex.add_argument("--verified", default="")
    ex.add_argument("--unavailable-reason")
    ac = sub.add_parser("admit-clarification", help="a plan's derived clarification allowance (#313)")
    ac.add_argument("--project-root", required=True)
    ac.add_argument("--plan-id", required=True)
    rv.add_argument("--raised", default="")
    rv.add_argument("--verified", default="")
    rv.add_argument("--coverage", default="full", choices=COVERAGES)
    rv.add_argument("--verdict", required=True, choices=D21_VERDICTS)
    rv.add_argument("--disposition", required=True, choices=DISPOSITIONS)
    rv.add_argument("--user-directed", action="store_true")
    return p


def main(argv: Optional[list] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None:
            raise _UsageError("a subcommand is required: resolve | wp | record-dispatch | record-outcome | "
                              "policy-hash | review-id | record-d21-review | admit-fix-round | "
                              "admit-clarification | record-exhausted-review")
    except _UsageError as exc:
        print(f"effort_policy.py: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        if args.command == "resolve":
            out: Dict[str, Any] = first_attempt_effort(None if args.ungraded else args.grade, args.file).to_dict()
        elif args.command == "wp":
            plan = load_plan(args.plan)
            task_key = task_key_for(plan.get("plan_id"), args.wp)
            root = plan.get("project_root")
            if not isinstance(root, str) or not root:
                root = str(Path(args.plan).resolve().parent)
            decision = for_work_package(plan_work_package(plan, args.wp), root=root)
            out = decision.to_dict()
            out.update({"wp_id": args.wp, "task_key": task_key, "dispatch_id": new_dispatch_id()})
        elif args.command == "record-dispatch":
            row = dispatch_row(dispatch_id=args.dispatch_id, task_key=args.task_key,
                               effort_source=args.effort_source, effort_requested=args.effort_requested,
                               grade=args.grade, policy_hash_value=args.policy_hash, attempt=args.attempt,
                               surface=args.surface, agent_type=args.agent_type, model=args.model,
                               role=args.role, effort_applied=args.effort_applied,
                               dispatch_kind=args.dispatch_kind, fix_admission_id=args.fix_admission_id,
                               review_id=args.review_id)
            out = {"recorded": str(store_path(args.project_root)), "row": record_dispatch(args.project_root, row)}
        elif args.command == "record-outcome":
            row = outcome_row(dispatch_id=args.dispatch_id, task_key=args.task_key, status=args.status,
                              attempt=args.attempt, needs_kind=args.needs_kind,
                              effort_applied=args.effort_applied,
                              clarification_asked=args.clarification_asked,
                              dispatch_kind=args.dispatch_kind, fix_admission_id=args.fix_admission_id,
                              review_id=args.review_id)
            out = {"recorded": str(record(args.project_root, row)), "row": row}
        elif args.command in ("review-id", "record-d21-review", "admit-fix-round"):
            rid = review_id_for(args.project_root, args.design_doc, issue=args.issue, plan_id=args.plan_id)
            if args.command == "review-id":
                out = {"review_id": rid}
            elif args.command == "record-d21-review":
                row = record_d21_review(args.project_root, review_id=rid, initial=args.initial,
                                        raised=_parse_counts(args.raised), verified=_parse_counts(args.verified),
                                        coverage=args.coverage, verdict=args.verdict,
                                        disposition=args.disposition, user_directed=args.user_directed,
                                        design_doc=rid, user_ref=args.user_ref)
                out = {"recorded": str(store_path(args.project_root)), "row": row}
            else:
                out = admit_fix_round(args.project_root, rid, user_directed=args.user_directed,
                                      user_ref=args.user_ref)
        elif args.command == "record-exhausted-review":
            rid = review_id_for(args.project_root, args.design_doc, issue=args.issue, plan_id=args.plan_id)
            row = record_exhausted_review(args.project_root, rid, outcome=args.outcome,
                                          raised=_parse_counts(args.raised), verified=_parse_counts(args.verified),
                                          unavailable_reason=args.unavailable_reason)
            out = {"recorded": str(store_path(args.project_root)), "row": row}
        elif args.command == "admit-clarification":
            out = admit_clarification(args.project_root, args.plan_id)
        else:
            out = {"policy_hash": policy_hash()}
    except (EffortPolicyError, OSError, ValueError) as exc:
        print(f"effort_policy.py: refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(json.dumps(out, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
