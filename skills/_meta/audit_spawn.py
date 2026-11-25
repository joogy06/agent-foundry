#!/usr/bin/env python3
"""
audit_spawn.py — Cold-context metacognitive audit helper for bob.

Spawns TWO independent auditors against a sanitized audit bundle (produced by
bob's trusted_runner.py) and returns a combined JSON verdict:

  1. Fresh Claude subagent via headless subprocess, launched FROM THE REVIEWER CWD:
       claude -p --model <pinned reviewer model> --effort <pinned effort>
                 --setting-sources user --output-format json "<prompt>"
     The model is seat_model's `code_reviewer` Claude row (S081 WP-R06) — never
     smart-config, never a project file; see the S081 block under Configuration.
     OS-level process isolation — no shared memory with the implementer, no
     shared module state, no shared environment, fresh session id. This is
     the v1 design choice (spec section 11.4 step 2a), not a workaround.

REVIEWER CONFIGURATION ISOLATION (#282 R3, plan K3/K4/K5). A `claude` process reads
CLAUDE.md, CLAUDE.local.md, .mcp.json and .claude/settings*.json from its working
directory and that directory's ancestors, so a reviewer started in the reviewed
project would load the project's own model, env, hooks and instructions — the
implementer could steer the auditor that gates its work. Every Claude reviewer call
(the Claude arm AND the codex slot's Claude substitute) therefore:
  * runs with `cwd=` a fixed empty directory, resolve_reviewer_cwd():
    $XDG_RUNTIME_DIR/foundry-reviewer-cwd, else /run/user/<uid>/foundry-reviewer-cwd
    (POSIX, when that runtime dir is the user's and mode 0700), else
    <tempdir>/foundry-reviewer-cwd-<uid or user name>; created 0700. The codex slot's
    Claude substitute runs CONCURRENTLY with the Claude arm, so since #282 fix round 2
    (G4) it gets a `-substitute` directory of its own — same rules, same body, its own
    project slug and therefore its own auto-memory dir. Before EVERY
    launch it must be a real directory (not a symlink), the user's, not
    group/world-writable, not the caller's cwd / --project-root / ~/.claude or inside
    one (a FILESYSTEM ROOT is never a containment root, #282 F8 — a caller whose cwd is
    "/" would otherwise fail every launch closed), holding no .claude / CLAUDE.md /
    CLAUDE.local.md / .mcp.json, with no ancestor holding CLAUDE.md / CLAUDE.local.md /
    .mcp.json / .claude/settings*.json. HOME ITSELF is exempt from the two
    .claude/settings*.json markers (#282 F2: the runtime/temp dir lands under HOME on
    Windows and wherever XDG_RUNTIME_DIR=$HOME/run, and the user tier loads into the
    reviewer anyway under `--setting-sources user`), while any ancestor strictly BELOW
    home holding a `.claude` entry is refused. Every ancestor of the path AND of its
    realpath is checked on POSIX (#282 F4): owned by root or this user, sticky if
    group/world-writable, and no symlinked ancestor unless it is root-owned (the macOS
    /var -> private/var carve-out).
    XDG_RUNTIME_DIR is itself an environment lever, hence the checks. Any failure
    makes that call fail closed ("reviewer cwd unavailable: <reason>" ->
    AUDIT_UNAVAILABLE); the caller's cwd is NEVER a fallback. One fixed directory
    also means one ~/.claude/projects/<slug>/ transcript dir, not one per call;
  * QUARANTINES the auto-memory that one fixed directory implies (#282 F3, plan K40).
    ~/.claude/projects/<slug>/memory/ is SHARED by every reviewer, arbiter and
    substitute call, so one reviewer's memories would reach the next reviewer's
    context and the arms of a conjunction would stop being independent. `--bare`
    would disable the memory but breaks the Max OAuth path, so before EVERY launch
    every entry is MOVED — never deleted, `memory/` itself kept — into
    memory.quarantine/<UTC stamp>/, and the count rides `reviewer_memory_quarantined`
    in the launching arm's model_provenance block plus one stderr line (both absent
    when nothing moved). A move failure, or a `memory` that is not a real directory,
    fails the arm closed down the same "reviewer cwd unavailable" path: a reviewer
    that loads unquarantined memory is exactly what F3 forbids;
  * passes `--setting-sources user` (the user tier only: no project or local
    settings even if one appeared) and NEVER `--bare` — it forces ANTHROPIC_API_KEY
    auth and breaks the Max OAuth path; `--fallback-model` is not passed either.
    `--effort` IS passed (#311 fix round 1 F1): the seat's pinned level (medium), so
    the user's global effortLevel never sets the reviewer's effort; a missing pin
    refuses the launch;
  * takes the prompt on a piped stdin that EOFs once written (#291 fix round 1 B:
    never argv, where a >128 KiB prompt is E2BIG), UTF-8 encoded whatever the
    locale (C); the prompt is self-contained — build_prompt inlines the bundle —
    so the cwd change removes no input. The codex arm takes its prompt on stdin
    too (#291 fix round 2 N2: `codex exec ... -`, fed from a regular file that EOFs).
SERVED MODEL. The JSON envelope's `modelUsage` map names what actually served the
call. Every key is kept with its outputTokens; the served model is the key with the
most output tokens (ties -> the lexicographically smallest id), "unknown" when the
envelope has no modelUsage. It is a MISMATCH when the requested alias is not a
dash-delimited token of the served id ("fable" matches "claude-fable-5-1"); a
mismatch writes one stderr WARNING and `served_model_mismatch: true` on the spawn-runs
row and changes no verdict and no exit code (K4). Where it is recorded:
model_provenance.claude `reported` / `reported_source` "claude_model_usage"; the
spawn-runs rows of audit_claude and of a substituted audit_codex arm (`served_model`,
`served_model_usage`, `served_model_mismatch`). The codex block's
`codex_arm_substituted_by` keeps naming the requested alias.

  2. Codex adversarial review:
       codex exec --skip-git-repo-check -s read-only
                  -m <pinned model> -c model_reasoning_effort=<pinned effort>
     BOTH axes come from seat_model's `code_reviewer` codex row (S081 WP-R06;
     S080 stream 4 pinned them first). An unpinned headless call inherits
     whatever the interactive TUI last persisted into ~/.codex/config.toml, so
     the adversary reviewing a gate could silently change model or effort
     between two runs of the same audit. The call is NOT `--ephemeral`: every
     codex call is metered, whatever seat it serves (#302 design §3.4b, JC-3;
     this supersedes the S081 I6 rule that only a TOP selector ran metered) —
     an ephemeral session writes no rollout, so the quota it spends is invisible.
     The pin is resolved fail-OPEN at import (#282 R4, plan K14): an INVALID
     ~/.codex/models_cache.json is a recorded harness literal (`roster_invalid:
     true` in model_provenance.codex), never an import-time exception, and it is
     not "astra unavailable" — only a valid roster with no eligible TOP is
     (no_eligible_model, substituted as before).

Both auditors receive EXACTLY the sanitized bundle + component entry from the
contract map + ledger row + a strict-JSON output contract. Nothing else.

Unavailability policy (spec sections 11.5 and 14.2 Step 4.5, as amended by S081
amendment 1 D6 — plan J9, J13, J14, J15):
    The audit needs TWO valid verdicts from two independent cold contexts. If the
    Claude arm fails to reach its model (process spawn error, timeout, malformed
    output), or if the codex slot ends without a valid verdict, the audit is
    AUDIT_UNAVAILABLE. Bob does NOT auto-approve. The WP is escalated to the user.

    ASTRA UNAVAILABLE -> A FRESH CLAUDE AUDITOR TAKES THE CODEX SLOT. When codex
    cannot serve the arm, a SECOND cold-context Claude subprocess on seat_model's
    code_reviewer Claude row runs THE SAME prompt, and its verdict fills the codex
    slot. It is never a codex std or support tier model, or any other codex
    model (every codex model draws the same plan quota). The substitution is decided:
      * pre-call, with no codex subprocess, when CODEX_PIN's fail-open provenance
        says `no_eligible_model`, when shutil.which(CODEX_BIN) finds no codex
        (`cli_missing`) — both checked BEFORE the audit admission, as the seat_model
        CLI does, because no TOP call will happen — or when the admission (never
        refused) carries `unavailable` (`rate_limit_reached` / `quota_exhausted`);
      * at call time, by codex_quota.classify_codex_failure (the ONE classifier):
        a timeout, malformed output or a model at capacity is retried ONCE on the
        same model with the same argv; a quota stop, an auth failure, a missing
        binary, or a second timeout / malformed / at-capacity answer substitutes; any
        other non-zero exit is a gap and stays AUDIT_UNAVAILABLE (substitution never
        launders a harness fault).

    A STDERR PHRASE IS NOT PROOF (#282 R2). codex copies tool output and the prompt
    onto its stderr, so a reviewed file that says "You've hit your usage limit" must
    not buy a same-provider substitute. A quota / auth / capacity signal counts only
    on a codex-owned error line, or — for a quota phrase — when the meter agrees.
    For each FAILED codex call the slot builds ONE corroboration
    (codex_quota.corroboration_for: the error lines + one post-call unavailable()
    reading) and makes ONE classify call; the quota error text and `quota_source`
    come from that result, never from a second pattern match.

    A BINARY OVERRIDE NEVER BECOMES A SUBSTITUTION (#282 R1, widened by fix round 1
    F1). CODEX_BIN_OVERRIDE is a record of the variable's PRESENCE, not of a failure:
    it is set whenever AUDIT_CODEX_BIN is in the environment, even when its value is
    literally `codex` and even when the binary resolves (F9). While it is set, the
    codex slot is a GAP — AUDIT_UNAVAILABLE (exit 4), the pre-S081 outcome, with
    codex_error naming the variable, its recorded realpath and the reason — for:

      * a binary that names nothing, decided pre-call (no admission row, no
        substitution row, no codex spawn) or met at call time as exit 127; and
      * EVERY SUBSTITUTION THE CLASSIFIER PRODUCES after a call that ran —
        malformed_twice (a stub that exits 0 with unusable output), timeout_twice (a
        hanging one), capacity_twice, quota_exhausted, auth_failure, cli_missing.

    R1 closed only the first bullet, so an AUDIT_CODEX_BIN that merely MISBEHAVED
    still bought a Claude substitute: two Claude verdicts for a conjunction that must
    have two providers. A planted AUDIT_CODEX_BIN would otherwise buy a same-provider
    audit that still reads as a clean two-verdict pass. The override-awareness lives
    here, at the call sites; codex_quota's classifier stays pure and override-blind.

    The PRE-CALL paths are deliberately NOT mapped (plan K35): `no_eligible_model`
    (the roster said nothing is eligible — not the overridden binary's doing) and a
    pre-call meter token from _admit_audit (a real meter reading) still substitute,
    override or not.

    The substitution is recorded in three places: one `kind: substitution` row in
    the budget store (seat_model.substitute; #282 r10: for a pre-call `unavailable`
    token or a call-time substitution the row names the audit admission it replaces,
    `admission_id`, so that audit is netted out of the TOP-call counts — a plan-time
    substitution had no admission, and an admission whose row was not written is never
    named: both carry null), `model_provenance.codex`
    (codex_arm_substituted_by, substitution_reason, substitute_timeout_s,
    provider_gap "openai", codex_attempts, and `substitute_bin_override` — the
    AUDIT_CLAUDE_BIN record — when the substitute ran through a swapped Claude binary)
    and the codex arm's spawn-runs row (substitute_for, substitution_reason, use). The
    codex block's `bin_override` keeps meaning AUDIT_CODEX_BIN only. The top-level
    result keys and aggregate_verdicts / merge_disagreements are unchanged: a failing
    substitute rejects, an erroring substitute is AUDIT_UNAVAILABLE naming both
    failures, and the Claude arm is never substituted. Provider diversity is lost and
    recorded.

Interface:
    python -m audit_spawn <component_id> <audit_bundle_path>

Emits exactly ONE JSON object on stdout (no prose). Exit codes:
    0 = both auditors returned a valid verdict (pass / fail / pass_with_concerns)
    4 = AUDIT_UNAVAILABLE (one or both auditors failed to respond with valid JSON)
    3 = environmental error (missing files, bad args)

Provenance: spec sections 11.2 / 11.3 / 11.4 / 11.5.
Critical invariants: CB3 (trusted provenance — the bundle MUST be tagged
`produced_by: bob-trusted-runner`).
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# POSIX ONLY (P001) — guarded, or every Windows import of this module would die at IMPORT
# and take down every caller, a strictly worse defect than the one it is here to fix.
# #282 fix round 2 G2 (plan K54): the private-group carve-out in
# _check_ancestor_owner_and_mode reads the ancestor's group membership. Absent modules mean
# "cannot verify", which FAILS CLOSED — the ancestor is refused exactly as it was before.
try:
    import grp
    import pwd
except ImportError:  # pragma: no cover - Windows has neither module
    grp = None  # type: ignore[assignment]
    pwd = None  # type: ignore[assignment]

# --- S046 / #124 observe-only cost telemetry (best-effort, never-raise) ------
# extract_usage pulls cost/duration/num_turns from the claude -p JSON envelope;
# record_spawn_run appends one line to .process-observations/spawn-runs.jsonl.
# Both are null-safe + never-raise. Loaded fail-open so a missing module / a
# broken backend can NEVER perturb this spawner's verdict-return API or exit
# code (the audit pipeline's correctness is independent of telemetry). See
# spawn_usage.py / spawn_runs.py headers and design §A/§G.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# --- S080 stream 4 / S081 WP-R06: both reviewer pins come from ONE resolver ---
# seat_model.py (the role table) and codex_quota.py (the meter it and this arm
# read) are REQUIRED siblings, NOT optional telemetry, so they are imported hard
# with no fail-open stub. A stub would silently put the codex arm back on
# whatever ~/.codex/config.toml last held while still reporting success —
# precisely the silent-substitution failure this wiring exists to end. A missing
# sibling means a broken harness, and a broken harness must not run an audit.
import codex_quota  # noqa: E402
import seat_model  # noqa: E402

# --- S081 revision 4 / D24: the activity watchdog is a REQUIRED sibling too ---
# Same reasoning as above, one step further. A fail-open stub here would put the
# codex arm back on a fixed wall clock while still reporting success — which is
# the exact failure D24 exists to remove (two sol sessions, 896s and 538s, were
# killed mid-work while still emitting). A missing watchdog means a broken
# harness, and a broken harness must not run an audit.
import codex_watch  # noqa: E402

try:
    from spawn_usage import extract_usage as _extract_usage  # noqa: E402
except Exception:  # pragma: no cover - fail-open: telemetry must never block audit
    def _extract_usage(envelope: Any) -> Dict[str, Optional[float]]:
        return {"cost_usd": None, "duration_ms": None, "num_turns": None}

# spawn_runs.py lives in the process-observation skill, not _meta. Add that
# scripts dir to sys.path; fail-open to a no-op recorder if unavailable.
_PROC_OBS_SCRIPTS = (
    _SCRIPT_DIR.parent / "process-observation" / "scripts"
)
if _PROC_OBS_SCRIPTS.is_dir() and str(_PROC_OBS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PROC_OBS_SCRIPTS))
try:
    from spawn_runs import record_spawn_run as _record_spawn_run  # noqa: E402
except Exception:  # pragma: no cover - fail-open: telemetry must never block audit
    def _record_spawn_run(**kwargs: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_DISAGREEMENTS = 3    # spec section 11.5 — forced disagreements

CLAUDE_BIN = os.environ.get("AUDIT_CLAUDE_BIN", "claude")
CODEX_BIN = os.environ.get("AUDIT_CODEX_BIN", "codex")

# --- S081 (design §4.1, §4.2, §4.4): both arms are the PROTECTED code_reviewer role ---
#
# L1 TRUST. Until S081 the Claude arm asked smart-config for its model
# (`model_policy.py resolve --tier complex`). That resolver defaults
# --project-root to os.getcwd() and its PROJECT layer wins per leaf, so any repo
# carrying `.claude/model-policy.yaml` could downgrade the reviewer that gates
# its own work. Reproduced (design §2.1 L1): `tiers.complex.claude-code: haiku`
# in a scratch cwd made this module import with CLAUDE_MODEL == "haiku",
# source "project", unlogged — and the executor under review can write that file
# mid-cycle. Stream 1 cut that layer out with an interim "fable" literal; WP-R06
# replaces the literal with seat_model, which reads ONLY home-tier inputs and
# never the working directory, a project file or smart-config.
#
# L2 ENV. seat_model owns the env rule for protected roles: an override is
# accepted only when it EQUALS the resolved model (the role declares no env
# fallback), otherwise it is refused and the refusal rides the pin's provenance
# (`env_override_refused` = {var, value, reason}). Stream 1's ad-hoc gating in
# this file is gone rather than duplicated.
#
# L4 FALLBACK. `fail_open=True` is this spawner's contract (design §4.2): resolver
# breakage returns the role's harness literal WITH provenance (source
# `harness_literal`, `fallback_reason`), never a weaker model and never "omit the
# flag and inherit". For Claude the literal is the row's vendor alias, the
# roster's Claude main tier (#291: model_roster.CLAUDE_MAIN; stream 1 hardcoded
# the value that tier held then).
REVIEWER_ROLE = seat_model.CODE_REVIEWER
_CLAUDE_ENV_VAR = "AUDIT_CLAUDE_MODEL"
_CODEX_ENV_VAR = "AUDIT_CODEX_MODEL"


def _resolve_claude_pin() -> seat_model.SeatPin:
    """The Claude arm's pin. No subprocess, no working-directory read (L1)."""
    return seat_model.resolve(
        REVIEWER_ROLE, seat_model.CLAUDE, env_var=_CLAUDE_ENV_VAR, fail_open=True,
    )


def _resolve_codex_pin() -> seat_model.SeatPin:
    """The codex arm's pin, BOTH axes. No subprocess, no working-directory read.

    Home-tier inputs only (the codex roster, the freeze pins, the tops record and
    the quota meter, all under Path.home() at call time). code_reviewer is a TOP
    seat: the roster's codex TOP @ xhigh, or a freeze pin's model (source `freeze`)
    while one holds.
    """
    return seat_model.resolve(
        REVIEWER_ROLE, seat_model.CODEX, env_var=_CODEX_ENV_VAR, fail_open=True,
    )


def _bin_override(env_var: str) -> Optional[Dict[str, str]]:
    """Record a reviewer BINARY override, or None when the variable is unset.

    AUDIT_CLAUDE_BIN / AUDIT_CODEX_BIN stay (the test suites need stub binaries),
    but a swapped binary is a swapped reviewer, so whenever one is set the
    resolved binary's realpath is recorded (shutil.which, then os.path.realpath;
    "unresolvable" when it cannot be found) and a stderr warning is emitted.

    A RECORD OF PRESENCE, NOT OF FAILURE (#282 fix round 1 F9). The record is made
    whenever the variable is PRESENT in the environment — even when its value is
    literally `codex`, and even when the binary RESOLVES (realpath is then a real
    path, not "unresolvable"). Only an ABSENT variable gives None. That is what
    makes the gap rule total: a missing OR misbehaving binary under ANY override is
    a gap (see _bin_override_gap), never `cli_missing` and never a substitution,
    because the process that set the variable chose the reviewer.

    HONEST LIMIT (design §4.1.3): whoever controls this process's environment can
    also change PATH, which swaps `claude` / `codex` with no variable set at all.
    Same-user environment compromise is out of scope. The goal is narrower: no
    repo-carried file can silently weaken a reviewer, and any override is visible
    in the verdict.
    """
    if env_var not in os.environ:
        return None
    value = os.environ[env_var]
    found = shutil.which(value) if value else None
    return {
        "var": env_var,
        "value": value,
        "realpath": os.path.realpath(found) if found else "unresolvable",
    }


CLAUDE_BIN_OVERRIDE = _bin_override("AUDIT_CLAUDE_BIN")
CODEX_BIN_OVERRIDE = _bin_override("AUDIT_CODEX_BIN")

#: #292: main()'s SIGTERM / SIGHUP latch while the arms run, else None. It is
#: record-only (the handler runs on the main thread, the codex arm on a worker), and
#: codex_watch.watch() raises the stop from its poll loop, where it reaps the child.
_STOP_LATCH: Optional[codex_watch._StopLatch] = None


def _raise_if_stopped() -> None:
    """#292 fix round 1: after a stop, start NO new codex work -- no retry and no Claude
    stand-in (which would also write a substitution budget row for a discarded audit)."""
    latch = _STOP_LATCH
    if latch is not None and latch.signum is not None:
        raise codex_watch._StopSignal(latch.signum)

# --- The Claude arm's pin, resolved ONCE at import ----------------------------
CLAUDE_PIN = _resolve_claude_pin()
CLAUDE_MODEL = CLAUDE_PIN.model
#: #311 fix round 1 F1: the code_reviewer seat's PINNED effort (seat_model ROLE_TABLE), passed as
#: `--effort` on every Claude launch. Without it the reviewer ran at the user's global
#: effortLevel, so lowering that setting silently lowered the VERIFIED gate's reviewer.
CLAUDE_EFFORT = CLAUDE_PIN.effort
#: #311 fix round 2 item 6: "use the arm's own pinned effort". A sentinel, so a caller that
#: passes an explicit None (a pin without an effort) is REFUSED instead of silently served.
_ARM_EFFORT: Any = object()
CLAUDE_MODEL_SOURCE = CLAUDE_PIN.provenance["source"]
CLAUDE_ENV_OVERRIDE_REFUSED = CLAUDE_PIN.provenance.get("env_override_refused")

# CLAUDE-arm wall time, from the role row (code_reviewer x claude = 600). History:
# 180 -> 300 (S030-quickwins #53) -> 600 (S080 stream 4, a deliberate raise when
# the arm moved opus -> fable (dated, S080), NOT a side effect of splitting the codex arm off it;
# design §11.4 M2 forbids the latter) -> owned by seat_model (S081 WP-R06, same
# value). The codex arm does not read this constant — see CODEX_TIMEOUT_S.
DEFAULT_TIMEOUT_S = CLAUDE_PIN.timeout

# --- The codex slot's Claude substitute (S081 amendment 1 D6; plan J13) --------
# Its wall time is the code_reviewer Claude ROW's (600), not `--timeout`: that flag
# bounds the Claude arm only, and the substitute is the codex slot's auditor. Read
# from the row (the Claude adapter reads nothing), the same value seat_model's
# substitute() pin carries.
SUBSTITUTE_TIMEOUT_S = seat_model.resolve(REVIEWER_ROLE, seat_model.CLAUDE).timeout
#: The provider whose verdict is missing from a substituted audit.
PROVIDER_GAP = "openai"
#: A timeout or malformed answer gets ONE same-model retry (codex_quota's classifier).
CODEX_MAX_ATTEMPTS = 2

# --- The codex arm's pin — BOTH axes — resolved ONCE at import ---------------
# Before S080 the arm pinned NEITHER axis: it inherited model AND effort from
# whatever the interactive TUI last persisted into ~/.codex/config.toml, so the
# adversarial half of a verification gate could change underneath two runs of
# the same audit with nothing in the record.
#
# The selector is TOP @ xhigh (design §4.2): the lowest-priority listed,
# API-supported roster entry that supports xhigh, auto-followed (D1), unless a
# home-tier freeze pin holds it. Resolver breakage never changes argv SHAPE — `-m`
# is emitted on every path — and `CODEX_MODEL_SOURCE` (freeze | env | roster |
# harness_literal) is what makes the path taken VISIBLE.
#
# EFFORT IS PART OF THE PIN (S080 design §11.4 M1): xhigh, from the role row.
CODEX_PIN = _resolve_codex_pin()
CODEX_MODEL = CODEX_PIN.model
CODEX_EFFORT = CODEX_PIN.effort
CODEX_MODEL_SOURCE = CODEX_PIN.provenance["source"]
CODEX_ENV_OVERRIDE_REFUSED = CODEX_PIN.provenance.get("env_override_refused")

# Model tier and wall time are a COUPLED pair (S080 design §3.1): a pinned call
# that is cut short is an AUDIT_UNAVAILABLE, not a cheaper verdict. This arm takes
# its budget FROM THE PIN — codex_model.timeout_for(model, effort), the single
# codex timeout owner (600s for xhigh) — and NOT from DEFAULT_TIMEOUT_S.
# `--timeout` bounds the Claude arm only; see main().
CODEX_TIMEOUT_S = CODEX_PIN.timeout

# No codex call this module builds is --ephemeral, for ANY role (#302 design §3.4b, JC-3).
# The S081 I6 switch (`not is_top(role)`) ran a non-TOP selector ephemeral; that would hide a
# support-tier call's drain, because an ephemeral codex session writes no rollout and the
# rollout is the only place the quota a call spent can be read (codex_quota.snapshot). The
# cost: every call's prompt persists in ~/.codex/sessions - never put a secret in a brief.


def _seat_provenance(pin: seat_model.SeatPin) -> Dict[str, Any]:
    """The seat_model provenance a verdict records, for one arm.

    Always: `source`, `requested_selector`, `roster_fetched_at`. Only when the
    event happened (absent means "did not happen", never "not checked"):
    `roster_stale`, `fallback_reason`, `upgrade_followed`, `upgrade_ignored_reason`,
    `roster_invalid` (#282 R4: the codex roster file was invalid, so the arm serves
    its recorded harness literal), `roster_rev` (#291: the model_roster REVISION;
    every Claude pin and every codex-std pin carries it, a codex TOP pin does not,
    and it is OPTIONAL on read, so verdicts written before #291 still load).
    `env_override_refused` / `bin_override` are added by _build_model_provenance.
    """
    prov = pin.provenance
    out: Dict[str, Any] = {
        "source": prov.get("source"),
        "requested_selector": prov.get("requested_selector"),
        "roster_fetched_at": prov.get("roster_fetched_at"),
    }
    for key in ("roster_stale", "fallback_reason", "upgrade_followed", "upgrade_ignored_reason",
                seat_model.ROSTER_INVALID, seat_model.ROSTER_REV):
        if key in prov:
            out[key] = prov[key]
    return out


def _override_warnings() -> List[str]:
    """One stderr line per refused model override or set reviewer binary.

    ASCII only (`!a`): these are written at IMPORT, and a non-ASCII byte on a
    cp1252 console would raise before the audit even started (portability W003).
    """
    lines = []
    for refused, pinned in (
        (CLAUDE_ENV_OVERRIDE_REFUSED, CLAUDE_MODEL),
        (CODEX_ENV_OVERRIDE_REFUSED, CODEX_MODEL),
    ):
        if refused:
            lines.append(
                f"audit_spawn: WARNING: {refused['var']}={refused['value']!a} refused - "
                f"reviewer stays pinned to {pinned!a} (recorded as env_override_refused)"
            )
    for override in (CLAUDE_BIN_OVERRIDE, CODEX_BIN_OVERRIDE):
        if override:
            lines.append(
                f"audit_spawn: WARNING: {override['var']} swaps the reviewer binary -> "
                f"{override['realpath']!a} (recorded as bin_override)"
            )
    return lines


for _line in _override_warnings():
    sys.stderr.write(_line + "\n")

#: Provenance sentinel for evidence that could not be observed (design §4.6).
#: NEVER a guess, and never the requested value quietly echoed back as reported.
MODEL_UNKNOWN = "unknown"

#: `codex exec` prints its banner on STDERR *before* the API call:
#:     model: gpt-5.6-sol
#:     reasoning effort: xhigh
#: Verified live against codex 0.153.4 on 2026-09-09. This is the ONLY sanctioned
#: source for what codex actually ran. NEVER ask the model what it is: design D7
#: records real logs where the model self-reported "GPT-5" / "OpenAI Codex
#: (GPT-5)" while the config said gpt-5.6-sol.
_CODEX_BANNER_MODEL_RE = re.compile(r"^model:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_CODEX_BANNER_EFFORT_RE = re.compile(
    r"^reasoning effort:[ \t]*(\S+)[ \t]*$", re.MULTILINE
)


def _extract_codex_banner(stderr: Optional[str]) -> Tuple[str, str]:
    """(reported_model, reported_effort) read from codex's own stderr banner.

    FIRST match only. The banner precedes codex's echo of the prompt on the same
    stream, so a prompt that itself contains a `model:` line cannot displace it.
    Anything unreadable stays MODEL_UNKNOWN — unobserved evidence is never
    backfilled from what was requested (design §4.6).
    """
    if not isinstance(stderr, str) or not stderr:
        return MODEL_UNKNOWN, MODEL_UNKNOWN
    m = _CODEX_BANNER_MODEL_RE.search(stderr)
    e = _CODEX_BANNER_EFFORT_RE.search(stderr)
    return (
        m.group(1) if m else MODEL_UNKNOWN,
        e.group(1) if e else MODEL_UNKNOWN,
    )


# ---------------------------------------------------------------------------
# Quota and token evidence for the codex arm (S081 WP-R06; design §4.7, §4.11)
# ---------------------------------------------------------------------------

#: `quota_source` on a telemetry row names the evidence its quota fields rest on.
#: METER: quota_before / quota_after are codex_quota.snapshot() readings taken
#: around the call. EXHAUSTION: the call's ONE classification was (substitute,
#: quota_exhausted) — a quota stop on a codex error line or corroborated by the meter
#: (the meter readings are still attached). codex_quota owns what counts as a quota
#: stop: S081 WP-F03 deleted this module's duplicate patterns, and #282 R2 removed the
#: second, line-agnostic exhaustion_signal() match this module used to make.
QUOTA_SOURCE_METER = "codex_rollout_meter"
QUOTA_SOURCE_EXHAUSTION = "codex_stderr_exhaustion"

#: The snapshot keys a telemetry row keeps. The rollout PATH (`source`) is left out
#: on purpose: rows land in a tracked `.process-observations/spawn-runs.jsonl`.
_QUOTA_ROW_KEYS = (
    "state", "primary_used_percent", "primary_resets_at", "secondary_used_percent",
    "secondary_resets_at", "observed_at", "limit_id", "reason",
)

#: Codex's own banner line for the session (present with and without --ephemeral;
#: observed on codex 0.154.0: `session id: 01a0a02a-bdf9-7281-b75e-d9ce6c8f591b`).
#: The charset is restricted to hex and dashes, so the id is safe inside a glob.
#: ONE definition since S081 rev 4 D21 F8: codex_watch owns the pattern -- the watchdog
#: reads the same line to find the rollout heartbeat -- and this module binds that object.
_CODEX_BANNER_SESSION_RE = codex_watch.CODEX_BANNER_SESSION_RE

#: Bounded tail read of this call's own rollout (the same bound as the meter).
_ROLLOUT_TAIL_BYTES = codex_quota.TAIL_BYTES


def _quota_reading(snapshot: Any) -> Optional[Dict[str, Any]]:
    """The row-safe subset of a codex_quota.snapshot() result. Never raises."""
    if not isinstance(snapshot, dict):
        return None
    return {key: snapshot.get(key) for key in _QUOTA_ROW_KEYS}


def _take_quota_reading() -> Optional[Dict[str, Any]]:
    """codex_quota.snapshot() is documented never to raise; this guards it anyway,
    because a meter must never change an audit's outcome."""
    try:
        return _quota_reading(codex_quota.snapshot())
    except Exception:  # noqa: BLE001
        return None


def _codex_session_id(stderr: Any) -> Optional[str]:
    if not isinstance(stderr, str) or not stderr:
        return None
    match = _CODEX_BANNER_SESSION_RE.search(stderr)
    return match.group(1) if match else None


def _token_counts(usage: Any) -> Optional[Dict[str, int]]:
    """Keep the non-negative integer `*_tokens` fields of a usage object."""
    if not isinstance(usage, dict):
        return None
    out = {
        key: value for key, value in usage.items()
        if isinstance(key, str) and key.endswith("_tokens")
        and isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }
    return out or None


def _codex_rollout_tokens(
    session_id: Optional[str],
    sessions_dir: Optional[Path] = None,
) -> Optional[Dict[str, int]]:
    """Token usage of THIS codex call, read from its own non-ephemeral rollout.

    Plan I9: audit_spawn's stdout parsing is not switched to `--json`, so the
    tokens come from the rollout codex wrote for the session its banner named:
    the last `token_count` event's `info.total_token_usage`. Local file reads only,
    bounded like the meter (codex_quota's newest day directories, a tail read).
    Anything unobservable — no session id in the banner, no rollout, no event — is
    None, never an estimate. Never raises.
    """
    try:
        if not session_id or _CODEX_BANNER_SESSION_RE.fullmatch(f"session id: {session_id}") is None:
            return None
        root = Path(sessions_dir) if sessions_dir is not None else codex_quota.default_sessions_dir()
        # ONE bounded day-directory walk rule, shared with the meter.
        for day in codex_quota._newest_day_dirs(root, codex_quota.DAY_DIR_LIMIT):
            matches = sorted(day.glob(f"rollout-*-{session_id}.jsonl"))
            if not matches:
                continue
            tokens = None
            for line in codex_quota._tail_lines(matches[-1], _ROLLOUT_TAIL_BYTES):
                if b'"token_count"' not in line:
                    continue
                try:
                    event = json.loads(line.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                payload = event.get("payload") if isinstance(event, dict) else None
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                info = payload.get("info")
                found = _token_counts(info.get("total_token_usage")) if isinstance(info, dict) else None
                if found is not None:
                    tokens = found
            return tokens
        return None
    except Exception:  # noqa: BLE001
        return None


def _claude_tokens(envelope: Any) -> Optional[Dict[str, int]]:
    """Token usage from the `claude -p --output-format json` envelope (plan I9).

    The terminal `{"type": "result"}` element (stream-array shape) or a legacy
    dict envelope carries `usage`; only its integer `*_tokens` fields are kept.
    None when unobservable. Never raises.
    """
    try:
        message: Any = None
        if isinstance(envelope, list):
            for item in reversed(envelope):
                if isinstance(item, dict) and item.get("type") == "result":
                    message = item
                    break
        elif isinstance(envelope, dict):
            message = envelope
        return _token_counts(message.get("usage")) if isinstance(message, dict) else None
    except Exception:  # noqa: BLE001
        return None


# --- #282 R3 (plan K5): the served model, from the envelope's modelUsage ------
# Shape pinned by the R3 acceptance call (tests/fixtures/reviewer/
# claude-envelope-model-usage.json): the result message carries
#     "modelUsage": {"claude-sonnet-5": {"inputTokens": 2, "outputTokens": 4, ...}}
# The rules are duplicated in verification_arbiter_spawn.py (plan K2; that module does
# not import this one, whose import resolves the codex arm) and a parity test holds
# the two copies to the same answers.

#: `reported_source` of a Claude arm whose served model came from modelUsage.
SERVED_SOURCE_MODEL_USAGE = "claude_model_usage"


def _claude_model_usage(envelope: Any) -> Optional[Dict[str, Optional[int]]]:
    """{model id: outputTokens} for EVERY modelUsage key; None when there is none.

    A key whose outputTokens is not a non-negative int is kept with None (recorded,
    ranked as 0). Same result-message lookup as _claude_tokens. Never raises.
    """
    try:
        message: Any = None
        if isinstance(envelope, list):
            for item in reversed(envelope):
                if isinstance(item, dict) and item.get("type") == "result":
                    message = item
                    break
        elif isinstance(envelope, dict):
            message = envelope
        usage = message.get("modelUsage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            return None
        out: Dict[str, Optional[int]] = {}
        for model_id, entry in usage.items():
            if not isinstance(model_id, str) or not model_id:
                continue
            tokens = entry.get("outputTokens") if isinstance(entry, dict) else None
            ok = isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0
            out[model_id] = tokens if ok else None
        return out or None
    except Exception:  # noqa: BLE001
        return None


def _served_model_mismatch(requested: Any, served: str) -> bool:
    """True when `requested` does not name `served` (plan K5).

    The requested alias must be a dash-delimited token of the served id, compared
    case-insensitively: "fable" names "claude-fable-5-1", "opus" does not. A
    requested FULL id names itself (its tokens are a contiguous run of the served
    id's), and a trailing context suffix ("opus[1m]") is ignored. An unknown served
    model is never a mismatch — there is nothing to compare.
    """
    if served == MODEL_UNKNOWN or not isinstance(requested, str):
        return False
    want = re.sub(r"\[[^\]]*\]$", "", requested.strip()).lower()
    if not want:
        return False
    have = served.lower().split("-")
    tokens = want.split("-")
    span = len(tokens)
    return not any(have[i:i + span] == tokens for i in range(len(have) - span + 1))


def _served_model_fields(envelope: Any, requested: Any) -> Dict[str, Any]:
    """served_model / served_model_usage / served_model_mismatch for one claude call.

    served_model = the modelUsage key with the most outputTokens (ties -> the
    lexicographically smallest id), MODEL_UNKNOWN without modelUsage.
    served_model_mismatch is True on a mismatch and None otherwise (spawn_runs omits
    None, so the key exists only when it happened). Never raises.
    """
    try:
        usage = _claude_model_usage(envelope)
        served = min(usage, key=lambda k: (-(usage[k] or 0), k)) if usage else MODEL_UNKNOWN
        return {
            "served_model": served,
            "served_model_usage": usage,
            "served_model_mismatch": True if _served_model_mismatch(requested, served) else None,
        }
    except Exception:  # noqa: BLE001
        return {"served_model": MODEL_UNKNOWN, "served_model_usage": None, "served_model_mismatch": None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def eprint(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def emit_result(obj: Dict[str, Any], exit_code: int) -> None:
    """Emit exactly ONE JSON object on stdout and exit."""
    sys.stdout.write(json.dumps(obj, sort_keys=True))
    sys.stdout.write("\n")
    sys.exit(exit_code)


def env_error(message: str) -> None:
    emit_result(
        {
            "result": "AUDIT_UNAVAILABLE",
            "reason": f"ENV_ERROR: {message}",
            "claude_verdict": None,
            "codex_verdict": None,
            "disagreements": [],
        },
        exit_code=3,
    )


# ---------------------------------------------------------------------------
# Race-safe directory provisioning (S030-quickwins #54)
# ---------------------------------------------------------------------------
#
# The S028 #45 spawn 6 race surfaced when two parallel processes (verdict
# writer + symlink updater) hit a `mkdir -p` against the same `.ledger/`
# subdir at the same time. POSIX `mkdir(2)` itself is atomic per directory
# component, but `pathlib.Path.mkdir(parents=True, exist_ok=True)` walks the
# parent chain and a sibling process creating an intermediate component can
# race against `os.stat` -> `os.mkdir`. The defensive pattern is: provision
# the directory ONCE in the parent process BEFORE forking / spawning any
# parallel work that will write into it. This helper bakes that contract in.
#
# Use this from any future caller that wants to spawn audit_spawn alongside
# another verdict producer (e.g. a coverage arbiter, a drift-arbiter pipeline
# stage). The helper is intentionally narrow: it ensures the directory exists
# synchronously, then yields control to the caller. It does NOT spawn
# subprocesses itself — that's the caller's responsibility — because spawn
# semantics differ across callers (subprocess.Popen vs ThreadPoolExecutor vs
# asyncio.create_subprocess_exec). Keeping the directory provisioning
# separate from the spawn keeps this file a single self-contained module.

def ensure_verdicts_dir(verdicts_dir: Path) -> Path:
    """Synchronously create `verdicts_dir` (and parents) before any spawn.

    Resolves the directory path, calls `mkdir(parents=True, exist_ok=True)`
    once in the parent process, and returns the resolved path. After this
    call returns, the caller can safely fork / Popen multiple verdict
    producers that will all write into the same directory without racing on
    the directory's creation. CB4 boundary preserved (only bob ever calls
    this; only bob ever writes into `.ledger/verdicts/`).

    See `audit_spawn_race_note` for the full back-story.
    """
    verdicts_dir = Path(verdicts_dir).resolve()
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    return verdicts_dir


# RACE NOTE (S028 #45 spawn 6, fixed in S030-quickwins #54):
# Do NOT call `mkdir -p` (or pathlib's equivalent) from inside a backgrounded
# subshell or a child Python process if a sibling process is also writing into
# the same directory tree. The parent must provision the directory first via
# `ensure_verdicts_dir()` and then spawn the parallel workers.
audit_spawn_race_note = (
    "ensure_verdicts_dir() must be called by the caller BEFORE spawning any "
    "parallel verdict producer that will write into `.ledger/verdicts/` or a "
    "sibling subdir. Provisions the directory synchronously in the parent "
    "process so concurrent writers do not race on directory creation."
)


# ---------------------------------------------------------------------------
# Strict-JSON contract and validation
# ---------------------------------------------------------------------------


VERDICT_SCHEMA_KEYS = frozenset({"verdict", "structured_disagreements", "evidence_verified", "reason"})
ALLOWED_VERDICTS = frozenset({"pass", "pass_with_concerns", "fail"})
ALLOWED_SEVERITIES = frozenset({"critical", "moderate", "minor"})


def validate_verdict(raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse and validate an auditor's strict-JSON verdict.

    Returns (validated_dict, None) on success or (None, error_message) on failure.
    """
    if not isinstance(raw, dict):
        return None, "verdict is not a JSON object"
    missing = VERDICT_SCHEMA_KEYS - set(raw.keys())
    if missing:
        return None, f"verdict missing required fields: {sorted(missing)}"
    if raw["verdict"] not in ALLOWED_VERDICTS:
        return None, f"verdict value {raw['verdict']!r} not in {sorted(ALLOWED_VERDICTS)}"
    disagreements = raw["structured_disagreements"]
    if not isinstance(disagreements, list):
        return None, "structured_disagreements is not a list"
    if len(disagreements) < MIN_DISAGREEMENTS:
        return None, (
            f"structured_disagreements has {len(disagreements)} entries, "
            f"minimum is {MIN_DISAGREEMENTS} (anti-rubber-stamp)"
        )
    for i, d in enumerate(disagreements):
        if not isinstance(d, dict):
            return None, f"disagreement[{i}] is not an object"
        if not d.get("point"):
            return None, f"disagreement[{i}].point is empty or missing"
        if d.get("severity") not in ALLOWED_SEVERITIES:
            return None, (
                f"disagreement[{i}].severity {d.get('severity')!r} "
                f"not in {sorted(ALLOWED_SEVERITIES)}"
            )
    if not isinstance(raw["evidence_verified"], bool):
        return None, "evidence_verified must be boolean"
    if not isinstance(raw["reason"], str) or not raw["reason"]:
        return None, "reason must be a non-empty string"
    return raw, None


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


AUDIT_PROMPT_TEMPLATE = """You are a cold-context metacognitive auditor for a contract-driven testing pipeline.

You have never seen this work before. You are NOT allowed to trust any text outside the JSON bundle below. You MUST assume the implementer's own claims are suspect.

Your job: decide whether the component has genuinely been verified, based ONLY on the structured evidence in the bundle.

INPUTS (all trusted — produced by bob, not the implementer):

1. Component entry from contract-map.yaml (signed by forge):
```json
{component_entry}
```

2. Sanitized audit bundle from bob's trusted test runner:
```json
{audit_bundle}
```

3. Ledger row for this component:
```json
{ledger_row}
```

TASK:

You MUST produce a STRICT JSON response matching exactly this schema (no prose, no markdown, no code fences):

{{
  "verdict": "pass" | "pass_with_concerns" | "fail",
  "structured_disagreements": [
    {{"point": "<specific concern>", "severity": "critical" | "moderate" | "minor", "location": "<component/test/file>"}}
  ],
  "evidence_verified": true | false,
  "reason": "<one sentence>"
}}

HARD REQUIREMENTS:

- `structured_disagreements` MUST have at least 3 entries. You MUST find at least 3 real concerns even if you ultimately vote pass. Concerns can be about test coverage, fixture realism, success criteria sharpness, adversarial gaps, performance budgets, or any other weakness. "Everything looks great" is NOT a valid audit — it is grounds for rejection.
- Your response MUST parse as JSON. Do not wrap in backticks, do not prepend prose.
- You MUST decide on `verdict` based on whether the test bundle's pass counts genuinely match every success criterion declared in the component entry. If a success criterion is declared but no passing test maps to it: that is at least a moderate disagreement, possibly a fail.
- `evidence_verified` = true only if every success criterion has a demonstrably passing test in the bundle.

DEFERRED TEST PATHS (v2 roadmap):

- If a `test_paths` key (`integration`, `flow`, etc.) is declared as an object with `deferred_to_v2: true`, that path is **intentionally empty at v1**. Do NOT flag it as missing evidence. Do NOT count it as a coverage gap. The `reason` field explains why. You may still surface deferred coverage as a minor concern (v2 risk), but NOT as a critical or moderate disagreement, and NOT as grounds for `evidence_verified=false`.
- `evidence_verified` = true requires every success_criterion to map to a passing test in the bundle from the NON-deferred test paths (typically `unit`). Deferred paths are out of scope for v1 verification.

OUTPUT (JSON ONLY):"""


def build_prompt(component_entry: Dict[str, Any], audit_bundle: Dict[str, Any], ledger_row: Dict[str, Any]) -> str:
    return AUDIT_PROMPT_TEMPLATE.format(
        component_entry=json.dumps(component_entry, sort_keys=True, indent=2),
        audit_bundle=json.dumps(audit_bundle, sort_keys=True, indent=2),
        ledger_row=json.dumps(ledger_row, sort_keys=True, indent=2),
    )


# ---------------------------------------------------------------------------
# Claude arm — headless subprocess
# ---------------------------------------------------------------------------


def _parse_agent_text_as_json(text: str) -> Optional[Any]:
    """Parse the agent's final assistant text as JSON.

    Handles three flavors of payload in order of preference:
      1. Clean JSON: `{"verdict": "pass", ...}`
      2. Fenced: ```json\n{...}\n``` or ```\n{...}\n```
      3. Prose + embedded JSON: use outermost `{` / `}` brace match.
    Returns None only if no parseable JSON object can be recovered.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    # Strip common markdown fences (``` or ```json)
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Prose + JSON fallback: outermost brace match
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _extract_json_from_claude_output(stdout: str) -> Optional[Any]:
    """Extract the inner verdict JSON produced by a `claude -p --output-format
    json` subprocess.

    Three envelope shapes are supported across CLI versions:

      (a) Current (claude 2.1.x) — top-level JSON **array** of stream messages:
          [
            {"type": "system", "subtype": "init", ...},
            {"type": "assistant", "message": {"content": [{"type": "text",
                "text": "<verdict JSON>"}], ...}, ...},
            {"type": "result", "subtype": "success", "result": "<verdict JSON>", ...}
          ]
          The final `{"type": "result", ...}` element carries the agent's final
          text in its `result` field. We prefer this; fall back to the last
          assistant text block if `result` is missing.

      (b) Legacy dict envelope — `{"result": "...", ...}` or `{"content": "..."}`
          or `{"text": "..."}` or `{"output": "..."}` (older CLI versions).

      (c) Raw verdict — the CLI occasionally prints the agent's JSON verbatim
          with no envelope. Parsed directly.

    For each shape, the extracted agent text is passed through
    `_parse_agent_text_as_json` which handles fences and prose-wrapped JSON.

    Returns None only when no recoverable JSON object exists, which triggers
    AUDIT_UNAVAILABLE upstream.
    """
    if not isinstance(stdout, str) or not stdout.strip():
        return None

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        # Raw-text fallback — no envelope at all
        return _parse_agent_text_as_json(stdout)

    # Shape (a): list of stream messages
    if isinstance(envelope, list):
        # Prefer the final {"type":"result", "result":"..."} element
        for msg in reversed(envelope):
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "result":
                result_text = msg.get("result")
                parsed = _parse_agent_text_as_json(result_text) if isinstance(result_text, str) else None
                if parsed is not None:
                    return parsed
                break  # result exists but unparseable — fall through to assistant text
        # Fallback: walk assistant messages in reverse, pull final text content
        for msg in reversed(envelope):
            if not isinstance(msg, dict) or msg.get("type") != "assistant":
                continue
            message = msg.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                # content is a list of blocks like [{"type":"text","text":"..."}]
                texts = [
                    block.get("text")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                for t in reversed(texts):
                    parsed = _parse_agent_text_as_json(t) if isinstance(t, str) else None
                    if parsed is not None:
                        return parsed
        return None

    # Shape (b): legacy dict envelope
    if isinstance(envelope, dict):
        for key in ("result", "content", "text", "output"):
            inner = envelope.get(key)
            if isinstance(inner, str):
                parsed = _parse_agent_text_as_json(inner)
                if parsed is not None:
                    return parsed
        # Shape (c) partial: the envelope itself might already be the verdict
        # (e.g. direct `{"verdict":"pass",...}` dump with no outer wrapper).
        if "verdict" in envelope:
            return envelope
        return None

    return None


# --- #282 R3 (plan K3): the ONE fixed directory every Claude reviewer runs from ---
# Duplicated in verification_arbiter_spawn.py (plan K2, the launchers' existing idiom);
# a parity test proves both resolve the same directory for the same environment.

#: The reviewer directory's name under the runtime / temp dir.
REVIEWER_CWD_NAME = "foundry-reviewer-cwd"
#: Entries the reviewer directory itself must not hold.
_REVIEWER_CWD_FORBIDDEN_ENTRIES = (".claude", "CLAUDE.md", "CLAUDE.local.md", ".mcp.json")
#: Files no ANCESTOR of the reviewer directory may hold (claude reads them walking up).
_REVIEWER_CWD_ANCESTOR_MARKERS = (
    "CLAUDE.md", "CLAUDE.local.md", ".mcp.json",
    os.path.join(".claude", "settings.json"), os.path.join(".claude", "settings.local.json"),
)
#: Markers the HOME DIRECTORY ITSELF is exempt from (#282 F2, plan K37). The runtime/temp
#: dir lands under HOME on every Windows host and wherever XDG_RUNTIME_DIR=$HOME/run, so
#: refusing on the user's OWN ~/.claude/settings*.json failed every reviewer arm closed.
#: The user tier loads into the reviewer anyway (`--setting-sources user`) and is trusted.
#: CLAUDE.md / CLAUDE.local.md / .mcp.json still refuse AT home, and every marker still
#: refuses at every other ancestor.
_REVIEWER_CWD_HOME_EXEMPT_MARKERS = (
    os.path.join(".claude", "settings.json"), os.path.join(".claude", "settings.local.json"),
)
#: No ancestor STRICTLY BELOW home may hold this entry (#282 F2, plan K37, H1H2 Fable m4):
#: a `.claude` below home is a project's configuration root. Refusing by the ENTRY is the
#: forward-compatible replacement for enumerating claude's discovery files, which go stale.
#: Tested with lexists, so a symlink or a plain file named `.claude` counts too.
_REVIEWER_CWD_BELOW_HOME_ENTRY = ".claude"


class ReviewerCwdError(Exception):
    """The reviewer directory failed a #282 R3 safety check; the message names why."""


def _reviewer_cwd_candidate(*, variant: Optional[str] = None) -> str:
    """Where the reviewer directory lives (plan K3), before any check.

    (1) $XDG_RUNTIME_DIR/foundry-reviewer-cwd when XDG_RUNTIME_DIR is an absolute
    existing directory; (2) else, on POSIX, /run/user/<uid>/foundry-reviewer-cwd when
    that runtime dir exists, is the user's and is mode 0700; (3) else
    <tempfile.gettempdir()>/foundry-reviewer-cwd-<uid, or the sanitized user name where
    os.getuid is absent>. On a systemd host (1) and (2) are the same path, so there is
    one directory whether or not the harness exports XDG_RUNTIME_DIR.

    #282 fix round 2 G4 (plan K56): a non-None `variant` appends `-<variant>` to the name in
    ALL THREE branches — the variant segment precedes the uid suffix, so branch (3) is
    `foundry-reviewer-cwd-substitute-<uid>` and there is one naming rule, not two. The codex
    slot's Claude substitute passes `variant="substitute"` so it does not share the Claude
    arm's directory (and therefore its auto-memory) while the two run concurrently.
    """
    name = REVIEWER_CWD_NAME if variant is None else f"{REVIEWER_CWD_NAME}-{variant}"
    xdg = os.environ.get("XDG_RUNTIME_DIR") or ""
    if xdg and os.path.isabs(xdg) and os.path.isdir(xdg):
        return os.path.join(xdg, name)
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        uid = getuid()
        runtime = os.path.join(os.sep, "run", "user", str(uid))
        try:
            st: Optional[os.stat_result] = os.lstat(runtime)
        except OSError:
            st = None
        if (st is not None and stat.S_ISDIR(st.st_mode) and st.st_uid == uid
                and stat.S_IMODE(st.st_mode) == 0o700):
            return os.path.join(runtime, name)
        suffix = str(uid)
    else:
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001 - no user name is a naming problem, not a failure
            user = ""
        suffix = re.sub(r"[^A-Za-z0-9_.-]", "_", user) or "user"
    return os.path.join(tempfile.gettempdir(), f"{name}-{suffix}")


def _same_or_under(path: str, parent: str) -> bool:
    """True when `path` IS `parent` or lies inside it.

    #282 F8 (plan K39): a FILESYSTEM ROOT is never a containment root. commonpath(["/x",
    "/"]) == "/", so a caller whose cwd or --project-root is "/" used to mark EVERY
    candidate "inside the caller's cwd" and fail every launch closed. The guard covers "/"
    and a Windows drive root alike.
    """
    path, parent = os.path.normcase(path), os.path.normcase(parent)
    if os.path.dirname(parent) == parent:
        return False
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:  # different drives (Windows): never inside
        return False


def _ancestors(path: str) -> List[str]:
    out: List[str] = []
    current = os.path.dirname(path)
    while True:
        out.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            return out
        current = parent


def _home_dir_forms() -> Tuple[str, ...]:
    """The HOME directory as abspath and as realpath, normcased (#282 F2, plan K37).

    Both forms are compared because the ancestor walk runs over the candidate's abspath
    chain AND its realpath chain. An unreadable home is not a reviewer-cwd failure: it
    simply exempts nothing, which is the pre-F2 behaviour.
    """
    try:
        home = str(Path.home())
    except Exception:  # noqa: BLE001 - no home just means no exemption
        return ()
    forms = [os.path.abspath(home)]
    try:
        forms.append(os.path.realpath(home))
    except OSError:
        pass
    return tuple(dict.fromkeys(os.path.normcase(form) for form in forms))


def _is_below_home(ancestor: str, home_forms: Tuple[str, ...]) -> bool:
    """True when `ancestor` lies STRICTLY inside the home directory (#282 F2, plan K37).

    _same_or_under's root guard also handles the degenerate HOME="/" host: nothing counts
    as below home there, so the rule refuses nothing instead of refusing everything.
    """
    normed = os.path.normcase(ancestor)
    return any(normed != home and _same_or_under(normed, home) for home in home_forms)


def _is_private_group_dir(st: os.stat_result) -> bool:
    """True only when `st`'s group is PROVABLY the current user's own private group.

    #282 fix round 2 G2 (plan K54). On a umask-002 host a user-created directory is 0775
    with the user's PRIVATE single-member group, so `XDG_RUNTIME_DIR=$HOME/run` or
    `TMPDIR=$HOME/tmp` is group-writable by a group that contains nobody else — and F4 rule
    (b) refused it, failing every reviewer arm closed on a directory only its owner can
    write. "Private" means the group IS the caller's own gid AND has no other member:
    `gr_mem` empty, or naming only the current user (some distributions list the owner in
    its own private group).

    EVERY doubt FAILS CLOSED and returns False — an unverifiable group is not a proven
    private one. That covers a missing `grp`/`pwd` (Windows), a gid the name service cannot
    resolve, and a name service that is down.
    """
    if grp is None or pwd is None:
        return False
    getgid = getattr(os, "getgid", None)
    getuid = getattr(os, "getuid", None)
    if getgid is None or getuid is None:
        return False
    try:
        if st.st_gid != getgid():
            return False
        members = list(grp.getgrgid(st.st_gid).gr_mem)
        me = pwd.getpwuid(getuid()).pw_name
    except Exception:  # noqa: BLE001 - KeyError / OSError / anything: cannot verify
        return False
    return not [member for member in members if member != me]


def _ancestor_forms(ancestor: str) -> Tuple[str, ...]:
    """The ancestor as given and as realpath, deduped (#282 fix round 2 G1, plan K53).

    `tempfile.gettempdir()` returns an abspath, which on WINDOWS keeps the 8.3 SHORT form —
    `C:\\Users\\RUNNER~1\\AppData\\Local\\Temp`, the standard GitHub-Actions shape and common
    for any user name over 8 characters. That short ancestor equals NEITHER form of HOME as
    a STRING, so the F2 home exemption missed while the marker `lexists` resolved straight
    through the alias: every reviewer arm failed closed on the user's OWN
    ~/.claude/settings.json, the exact defect F2 exists to close.

    `at_home` is an IDENTITY question — "is this directory the user's home?" — where the
    alias MUST resolve. The ancestor safety walk is a LINK-STRUCTURE question where it must
    not, so `_validate_ancestor_chain` keeps receiving the RAW chain: resolving it first
    would silently erase every symlink rule (c) exists to catch. Marker paths are likewise
    joined onto the RAW ancestor.

    An unreadable ancestor simply yields no second form. A new failure mode here would be
    worse than the one being fixed.
    """
    forms = [ancestor]
    try:
        forms.append(os.path.realpath(ancestor))
    except OSError:
        pass
    return tuple(dict.fromkeys(forms))


def _check_ancestor_owner_and_mode(ancestor: str, candidate: str,
                                   st: os.stat_result, uid: int) -> None:
    """#282 F4 (plan K38) rules (a) and (b) for one ancestor; raises naming the rule.

    #282 fix round 2 G2 (plan K54) SPLIT rule (b), which used to test `mode & 0o022` as one
    condition: WORLD-write without the sticky bit stays an unconditional refusal, while
    GROUP-write without it is refused unless the ancestor's group is provably the current
    user's own private group. The sticky escape (/tmp's 1777) is unchanged, and so is the
    reviewer directory's OWN mode rule in resolve_reviewer_cwd — this split is scoped to
    ANCESTORS.
    """
    if st.st_uid not in (0, uid):
        raise ReviewerCwdError(
            f"ancestor {ancestor!a} of {candidate!a} is owned by uid {st.st_uid}, "
            f"neither root nor the current user")
    mode = stat.S_IMODE(st.st_mode)
    sticky = bool(mode & stat.S_ISVTX)
    if mode & 0o002 and not sticky:
        raise ReviewerCwdError(
            f"ancestor {ancestor!a} of {candidate!a} is world-writable without the "
            f"sticky bit (mode {mode:o})")
    if mode & 0o020 and not sticky and not _is_private_group_dir(st):
        raise ReviewerCwdError(
            f"ancestor {ancestor!a} of {candidate!a} is group-writable without the sticky "
            f"bit and its group {st.st_gid} is not the current user's private group "
            f"(mode {mode:o})")


def _validate_ancestor_chain(candidate: str, chain: List[str]) -> None:
    """#282 F4 (H1H2 astra A1, plan K38): every ancestor must be safe, or the cwd is refused.

    Only the reviewer directory itself used to be validated, so a 0777 parent could be
    swapped under it between the check and the launch. POSIX ONLY — gated on os.getuid
    exactly like the directory's own owner/mode checks, because Windows reports uid 0 and
    mode 0o777 for every directory and would refuse every ancestor. Rules: (a) OWNER in
    {root, the current uid}; (b) a group- or world-writable ancestor must carry the STICKY
    bit, so /tmp (1777 root) passes and a 0777 non-sticky parent does not; (c) a SYMLINKED
    ancestor is refused unless it is owned by ROOT and its own parent passes (a) and (b) —
    the carve-out macOS needs for /var -> private/var and /tmp -> private/tmp, whose
    absence would take every macOS reviewer arm down the way the settings marker took
    Windows down (K38 narrows F4's literal "not a symlink" for exactly this reason).
    """
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return
    uid = getuid()
    for ancestor in chain:
        try:
            st = os.lstat(ancestor)
        except OSError as exc:
            raise ReviewerCwdError(
                f"ancestor {ancestor!a} of {candidate!a} cannot be stat'ed: {type(exc).__name__}")
        if not stat.S_ISLNK(st.st_mode):
            _check_ancestor_owner_and_mode(ancestor, candidate, st, uid)
            continue
        if st.st_uid != 0:
            raise ReviewerCwdError(
                f"ancestor {ancestor!a} of {candidate!a} is a symlink not owned by root")
        parent = os.path.dirname(ancestor)
        try:
            parent_st = os.lstat(parent)
        except OSError as exc:
            raise ReviewerCwdError(
                f"ancestor {ancestor!a} of {candidate!a} is a symlink whose parent "
                f"{parent!a} cannot be stat'ed: {type(exc).__name__}")
        _check_ancestor_owner_and_mode(parent, candidate, parent_st, uid)


def resolve_reviewer_cwd(project_root: Optional[Path] = None, *,
                         variant: Optional[str] = None) -> str:
    """Create-if-absent and CHECK the reviewer directory; return its realpath.

    Raises ReviewerCwdError naming the failed check. Run before EVERY launch (the
    directory is re-checked, never cached): a real directory (lstat, so a symlink is
    refused), owned by this user and not group/world-writable (POSIX), not equal to or
    inside the caller's cwd, `project_root` or ~/.claude, holding none of
    _REVIEWER_CWD_FORBIDDEN_ENTRIES, and with no ancestor (of the path or of its
    realpath) holding any of _REVIEWER_CWD_ANCESTOR_MARKERS. Other entries inside the
    directory are tolerated: claude writes its transcript under ~/.claude/projects, not
    its cwd.

    #282 fix round 1: HOME itself is exempt from the two `.claude/settings*.json` markers
    (F2 / K37) while an ancestor strictly below home holding a `.claude` entry is refused;
    every ancestor of both chains is owner/mode/symlink-checked on POSIX (F4 / K38); and a
    filesystem root is not a containment root (F8 / K39, in _same_or_under).

    #282 fix round 2 G4 (plan K56): `variant` selects a SECOND directory beside the first
    (`foundry-reviewer-cwd-substitute`), for the codex slot's Claude substitute, which runs
    concurrently with the Claude arm. It changes the NAME only — every check in this body
    applies to the variant directory exactly as to the primary one — and it gives the
    substitute its own project slug, hence its own auto-memory directory, with no second code
    path. Only `_substitute_codex_arm` passes one; the arbiter has no substitute and passes
    none, so its resolved directory is unchanged.
    """
    path = _reviewer_cwd_candidate(variant=variant)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ReviewerCwdError(f"cannot create {path!a}: {type(exc).__name__}: {exc}")
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise ReviewerCwdError(f"cannot stat {path!a}: {type(exc).__name__}: {exc}")
    if stat.S_ISLNK(st.st_mode):
        raise ReviewerCwdError(f"{path!a} is a symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise ReviewerCwdError(f"{path!a} is not a directory")
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        if st.st_uid != getuid():
            raise ReviewerCwdError(f"{path!a} is not owned by the current user")
        if stat.S_IMODE(st.st_mode) & 0o022:
            raise ReviewerCwdError(
                f"{path!a} is group/world-writable (mode {stat.S_IMODE(st.st_mode):o})")
    real = os.path.realpath(path)
    try:
        caller_cwd = os.getcwd()
    except OSError as exc:
        raise ReviewerCwdError(f"cannot read the caller's cwd: {type(exc).__name__}")
    for label, other in (("the caller's cwd", caller_cwd), ("the project root", project_root),
                         ("~/.claude", os.path.join(str(Path.home()), ".claude"))):
        if other is None:
            continue
        other_real = os.path.realpath(str(other))
        if _same_or_under(real, other_real):
            raise ReviewerCwdError(f"{path!a} is {label} {other_real!a} or inside it")
    for name in _REVIEWER_CWD_FORBIDDEN_ENTRIES:
        if os.path.lexists(os.path.join(real, name)):
            raise ReviewerCwdError(f"{path!a} contains {name}")
    home_forms = _home_dir_forms()
    bases = list(dict.fromkeys([real, os.path.abspath(path)]))
    for base in bases:
        for ancestor in _ancestors(base):
            # G1 / K53: both questions are answered over the RAW ancestor AND its realpath,
            # so a Windows 8.3 short name of HOME is recognised as home. The marker paths
            # below stay joined onto the RAW ancestor.
            forms = _ancestor_forms(ancestor)
            at_home = any(os.path.normcase(form) in home_forms for form in forms)
            below_home = not at_home and any(
                _is_below_home(form, home_forms) for form in forms)
            for marker in _REVIEWER_CWD_ANCESTOR_MARKERS:
                if at_home and marker in _REVIEWER_CWD_HOME_EXEMPT_MARKERS:
                    continue  # F2 / K37: the user tier is loaded and trusted anyway
                if os.path.lexists(os.path.join(ancestor, marker)):
                    raise ReviewerCwdError(f"ancestor {ancestor!a} of {path!a} holds {marker}")
            if (below_home
                    and os.path.lexists(os.path.join(ancestor, _REVIEWER_CWD_BELOW_HOME_ENTRY))):
                raise ReviewerCwdError(
                    f"ancestor {ancestor!a} of {path!a} holds "
                    f"{_REVIEWER_CWD_BELOW_HOME_ENTRY} below home")
    for base in bases:
        _validate_ancestor_chain(path, _ancestors(base))
    return real


#: The reviewer's auto-memory directory, EMPTIED before every launch (#282 F3, plan K40).
#: claude keeps `<config root>/projects/<slug of the cwd>/memory/`, and the reviewer and the
#: arbiter share ONE reviewer cwd — so one reviewer's memories would reach the next reviewer's
#: context and the arms of a conjunction would stop being independent. (#282 fix round 2 G4 /
#: plan K56: the codex slot's Claude substitute, which runs CONCURRENTLY with the Claude arm,
#: now has a variant directory of its own and therefore its own memory dir — the quarantine
#: below still runs before ITS launch too, on ITS directory.)
#: `--bare` would disable the memory but forces ANTHROPIC_API_KEY auth and breaks the Max
#: OAuth path, so the directory is emptied instead: every entry is MOVED (never deleted)
#: into a timestamped sibling, and `memory/` itself is kept.
_REVIEWER_MEMORY_DIR_NAME = "memory"
_REVIEWER_MEMORY_QUARANTINE_NAME = "memory.quarantine"
#: Every non-alphanumeric character becomes one '-' — claude's project-slug rule, shared
#: with codex_quota.project_slug and model_policy._project_slug (confirmed on this host by
#: the sibling directory `-home-USER--claude-skills-smart-config-scripts`: `/.` -> `--`).
_REVIEWER_MEMORY_SLUG_RE = re.compile(r"[^A-Za-z0-9]")
#: Bound on the same-stamp collision suffix, so a pathological directory cannot spin.
_REVIEWER_MEMORY_COLLISION_LIMIT = 1000


def _reviewer_memory_dir(reviewer_cwd: str) -> str:
    """`<config root>/projects/<slug of reviewer_cwd>/memory` (#282 F3, plan K40 / K55).

    The config root is CLAUDE_CONFIG_DIR when that variable is set to a NON-EMPTY value —
    the variable names the `.claude` directory ITSELF, so the path is
    `<root>/projects/<slug>/memory`, never `<root>/.claude/projects/...`. An empty value is
    treated as unset. Otherwise `~/.claude`, exactly as before.

    #282 fix round 2 G3 (plan K55) is that root rule. Building from `Path.home()` alone named
    a directory that does not exist under a relocated CLAUDE_CONFIG_DIR, so
    _quarantine_reviewer_memory moved nothing, returned 0 and the launch PROCEEDED over the
    memory claude would really read — a 0 that meant "not checked" rather than "nothing was
    moved", which is the reading F3 exists to forbid.

    An undeterminable home WITH THE VARIABLE UNSET stays a quarantine FAILURE, not a silent
    skip: F3 exists because a reviewer that loads another reviewer's memory is a corrupted arm.

    Scope, recorded rather than fixed: codex_quota's budget store still ignores
    CLAUDE_CONFIG_DIR. G3 is scoped to the reviewer memory (plan K55).
    """
    configured = os.environ.get("CLAUDE_CONFIG_DIR") or ""
    if configured:
        root = os.path.abspath(configured)
    else:
        try:
            root = os.path.join(str(Path.home()), ".claude")
        except Exception as exc:  # noqa: BLE001 - no home means the memory cannot be checked
            raise ReviewerCwdError(
                f"cannot locate the home directory for the reviewer memory check: "
                f"{type(exc).__name__}")
    slug = _REVIEWER_MEMORY_SLUG_RE.sub("-", os.path.abspath(reviewer_cwd))
    return os.path.join(root, "projects", slug, _REVIEWER_MEMORY_DIR_NAME)


def _quarantine_stamp() -> str:
    """UTC `%Y%m%dT%H%M%S%fZ`. Its own function so a test can pin it and prove the suffix."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _new_quarantine_dir(memory: str) -> str:
    """Create and return a fresh `<slug>/memory.quarantine/<stamp>[-n]/` at mode 0700."""
    holder = os.path.join(os.path.dirname(memory), _REVIEWER_MEMORY_QUARANTINE_NAME)
    try:
        os.mkdir(holder, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ReviewerCwdError(f"cannot create {holder!a}: {type(exc).__name__}: {exc}")
    stamp = _quarantine_stamp()
    for index in range(_REVIEWER_MEMORY_COLLISION_LIMIT):
        candidate = os.path.join(holder, stamp if index == 0 else f"{stamp}-{index}")
        try:
            os.mkdir(candidate, 0o700)
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            raise ReviewerCwdError(f"cannot create {candidate!a}: {type(exc).__name__}: {exc}")
    raise ReviewerCwdError(f"no free quarantine directory under {holder!a}")


def _quarantine_reviewer_memory(memory: str) -> int:
    """Move every entry out of `memory` before a launch; return how many moved (#282 F3).

    Nothing is ever DELETED and the `memory/` directory itself is kept (left empty), so a
    quarantined memory can always be read back. An absent or empty directory moves nothing
    and returns 0, which is why the count is recorded as an EVENT KEY: absent means
    "nothing was moved", never "not checked".

    Moves are one `os.replace` per entry, so no lock is introduced: the audit's two arms
    share a ThreadPoolExecutor and the arbiter is a separate process, and a source that has
    VANISHED (a concurrent launcher moved it first) is skipped rather than failed — it is
    already out of the way, which is all this function wants.

    FAIL CLOSED (plan K40): any OSError while quarantining, and a `memory` that exists but
    is not a real directory (a symlink counts, even to a real directory — listdir would
    follow it and the moves would escape the project), raise ReviewerCwdError, so the
    caller returns the existing "reviewer cwd unavailable: <reason>" failure WITHOUT
    launching. A reviewer that loads unquarantined memory is exactly what F3 forbids.
    """
    try:
        st = os.lstat(memory)
    except (FileNotFoundError, NotADirectoryError):
        # NotADirectoryError means a PARENT component is not a directory, so `memory`
        # cannot exist and there is definitively nothing to quarantine — the same answer
        # as FileNotFoundError, not an unknown. `memory` ITSELF not being a real directory
        # is the different case below: lstat SUCCEEDS there, and that one fails closed.
        return 0
    except OSError as exc:
        raise ReviewerCwdError(
            f"cannot stat the reviewer memory directory {memory!a}: {type(exc).__name__}")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ReviewerCwdError(
            f"the reviewer memory directory {memory!a} is not a real directory")
    try:
        entries = sorted(os.listdir(memory))
    except OSError as exc:
        raise ReviewerCwdError(
            f"cannot read the reviewer memory directory {memory!a}: {type(exc).__name__}")
    if not entries:
        return 0
    destination = _new_quarantine_dir(memory)
    moved = 0
    for name in entries:
        try:
            os.replace(os.path.join(memory, name), os.path.join(destination, name))
        except FileNotFoundError:
            continue  # a concurrent launcher moved it first; it is already out of the way
        except OSError as exc:
            raise ReviewerCwdError(
                f"cannot quarantine {name!a} out of {memory!a}: {type(exc).__name__}: {exc}")
        moved += 1
    return moved


def _record_served_model(envelope: Any, requested: str, usage_out: Optional[Dict[str, Any]]) -> None:
    """#282 R3 / K4: fill the served-model fields into `usage_out` and WARN on a mismatch.

    A mismatch is recorded (one ASCII stderr line + served_model_mismatch) and changes
    nothing else: no verdict, no exit code. Never raises.
    """
    try:
        fields = _served_model_fields(envelope, requested)
        if fields["served_model_mismatch"]:
            eprint(
                f"audit_spawn: WARNING: served model {fields['served_model']!a} does not match the "
                f"requested {requested!a} (recorded as served_model_mismatch)"
            )
        if usage_out is not None:
            usage_out.update(fields)
    except BaseException:  # noqa: BLE001 - telemetry never blocks the audit
        pass


def _claude_launch_bin() -> str:
    """CLAUDE_BIN as launched from the reviewer cwd.

    A value with a directory separator is made absolute against THIS process's cwd —
    the directory _bin_override resolved it in — because a relative path would
    otherwise be looked up from the reviewer cwd and run a different file (or none).
    A bare name is still looked up on PATH.
    """
    seps = [os.sep] + ([os.altsep] if os.altsep else [])
    if any(sep in CLAUDE_BIN for sep in seps) and not os.path.isabs(CLAUDE_BIN):
        return os.path.abspath(CLAUDE_BIN)
    return CLAUDE_BIN


def run_claude_auditor(
    prompt: str,
    timeout_s: int,
    usage_out: Optional[Dict[str, Any]] = None,
    *,
    model: Optional[str] = None,
    project_root: Optional[Path] = None,
    variant: Optional[str] = None,
    effort: Any = _ARM_EFFORT,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Spawn a fresh Claude subagent via `claude -p --effort <pin> --setting-sources user --output-format json`.

    `effort` (keyword-only, #311 fix round 1 F1) is the substitute's pinned effort; omitted, it
    is the Claude arm's own CLAUDE_EFFORT. Any value that is not a Claude effort level --
    an explicit None included (fix round 2 item 6) -- refuses the launch without spawning.

    Returns (verdict_dict, None) or (None, error_message) — the verdict-return
    API is UNCHANGED (#124 constraint). The optional `usage_out` dict is a
    side-channel: when provided, it is populated in place with the arm's
    cost/duration/num_turns (from the JSON envelope) plus `wall_clock_s`, and
    (#282 R3) `served_model` / `served_model_usage` / `served_model_mismatch`. It is
    never read by this function and its absence changes nothing — so every
    existing caller / test that calls `run_claude_auditor(prompt, timeout)`
    behaves exactly as before.

    `model` (keyword-only, S081 WP-F03) is the codex slot's Claude substitute's pin,
    from seat_model.substitute(); None means the Claude arm's own CLAUDE_MODEL. Each
    call is its own subprocess, so the substitute shares no context with the arm.

    `variant` (keyword-only, #282 fix round 2 G4 / plan K56) names a reviewer directory of
    this launch's own — `_substitute_codex_arm` passes "substitute" and NOTHING else passes
    one. The substitute is identified by this EXPLICIT parameter and never by `model is not
    None`, which would mislabel any model-pinned Claude-arm call as a substitute.

    #282 R3: the subprocess runs from resolve_reviewer_cwd(project_root, variant=variant) —
    checked before every launch; a failed check returns (None, "reviewer cwd unavailable: ...")
    without spawning, and the caller's cwd is never used instead.
    """
    requested = model if model is not None else CLAUDE_MODEL
    effort = CLAUDE_EFFORT if effort is _ARM_EFFORT else effort
    if effort not in seat_model.CLAUDE_EFFORTS:
        # #311 fix round 1 F1: refused BEFORE any spawn - an unpinned effort would inherit.
        return None, (f"reviewer effort unavailable: {effort!r} is not a pinned Claude effort "
                      f"{list(seat_model.CLAUDE_EFFORTS)}; nothing was spawned")
    cmd = [
        _claude_launch_bin(),
        "-p",
        "--model", requested,
        # #311 fix round 1 F1: the seat's PINNED effort, never the user's global effortLevel.
        "--effort", effort,
        # User tier only; NEVER --bare (it forces ANTHROPIC_API_KEY auth and breaks
        # the Max OAuth path). No --fallback-model (#282 R3).
        "--setting-sources", "user",
        "--output-format", "json",
        # The prompt travels on STDIN, never argv (#291 fix round 1 B; the sibling of the
        # arbiter's #290 fix). Linux caps a SINGLE argv string at MAX_ARG_STRLEN = 131072
        # bytes: build_prompt inlines the evidence bundle, so a well-tested component's
        # prompt died with E2BIG before the model call and surfaced as AUDIT_UNAVAILABLE.
        # Transport only - what the auditor judges is unchanged. `claude -p` reads the
        # prompt from a piped stdin, which EOFs as soon as it is written (STDIN RULE #155).
    ]
    _arm_start = time.time()

    def _stamp_usage(envelope: Any) -> None:
        # Best-effort, never-raise: fill usage_out if the caller asked for it.
        if usage_out is None:
            return
        try:
            usage = _extract_usage(envelope)
            usage_out.update(usage)
            usage_out["tokens"] = _claude_tokens(envelope)  # plan I9: the --output-format json envelope
            usage_out["wall_clock_s"] = round(time.time() - _arm_start, 3)
        except BaseException:  # noqa: BLE001
            usage_out.setdefault("wall_clock_s", round(time.time() - _arm_start, 3))

    try:
        reviewer_cwd = resolve_reviewer_cwd(project_root, variant=variant)
        # #282 F3 (plan K40): EVERY launch — the Claude arm and the codex slot's Claude
        # substitute alike — empties ITS auto-memory directory first, so no reviewer starts
        # with another reviewer's memories. Fail closed, never skip. (G4 / K56: the
        # substitute's variant cwd gives it a different slug, so the two concurrent arms
        # quarantine different directories and neither can re-create the other's memory.)
        memory_dir = _reviewer_memory_dir(reviewer_cwd)
        quarantined = _quarantine_reviewer_memory(memory_dir)
    except ReviewerCwdError as exc:
        _stamp_usage(None)
        return None, f"reviewer cwd unavailable: {exc}"
    if quarantined:
        if usage_out is not None:
            usage_out["reviewer_memory_quarantined"] = quarantined
        eprint(f"audit_spawn: quarantined {quarantined} reviewer auto-memory "
               f"{'entry' if quarantined == 1 else 'entries'} out of {memory_dir!a} "
               f"before the launch (moved, not deleted)")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            # UTF-8 both ways, never the locale codec (#291 fix round 1 C): under a non-UTF-8
            # locale a non-ASCII prompt raised an uncaught UnicodeEncodeError. Decoding
            # replaces rather than raises, so a stray byte degrades one character, not the arm.
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            # #282 R3: never the caller's cwd, so no project configuration loads.
            cwd=reviewer_cwd,
            # STDIN RULE (#155 / design D6). A headless CLI whose stdin never
            # EOFs blocks at 0 bytes BEFORE the model call, and the CLI's own
            # print-timeout does not fire because it guards only the print
            # phase. A piped stdin EOFs as soon as the prompt is written. The
            # prompt travels HERE, not in argv (see `cmd` above).
            input=prompt,
        )
    except FileNotFoundError:
        _stamp_usage(None)
        return None, f"claude binary not found ({CLAUDE_BIN})"
    except subprocess.TimeoutExpired:
        _stamp_usage(None)
        return None, f"claude subprocess timed out after {timeout_s}s"
    except OSError as e:
        _stamp_usage(None)
        return None, f"claude subprocess OS error: {e}"

    # Parse the envelope ONCE; reuse it for both the verdict and the usage.
    envelope: Any = None
    if isinstance(proc.stdout, str) and proc.stdout.strip():
        try:
            envelope = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            envelope = proc.stdout  # extract_usage will null-out on non-JSON
    _stamp_usage(envelope)
    _record_served_model(envelope, requested, usage_out)

    if proc.returncode != 0:
        return None, f"claude exited {proc.returncode}: {proc.stderr[:200]}"

    parsed = _extract_json_from_claude_output(proc.stdout)
    if parsed is None:
        return None, "claude output not parseable as JSON"

    verdict, err = validate_verdict(parsed)
    if err:
        return None, f"claude verdict invalid: {err}"
    return verdict, None


# ---------------------------------------------------------------------------
# Codex arm — adversarial review via codex exec
# ---------------------------------------------------------------------------


def _extract_json_from_codex_output(stdout: str) -> Optional[Any]:
    """codex exec emits the agent's output more or less verbatim. Reuse the
    shared prose/fence/brace-match parser used by the Claude arm.
    """
    return _parse_agent_text_as_json(stdout)


def run_codex_auditor(
    prompt: str,
    timeout_s: int,
    usage_out: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Spawn a Codex adversarial review via `codex exec` (non-ephemeral: every codex call is metered).

    Verdict-return API UNCHANGED (#124). `usage_out`, when provided, is filled
    with this arm's wall_clock_s; cost/duration/num_turns stay null because the
    Codex path is NOT a `claude -p --output-format json` envelope (this is the
    null-safe non-JSON path the design calls out — null, never error).

    S081 WP-R06, also only when `usage_out` is provided (a caller that records
    nothing pays for no extra file reads):
      * `quota_before` / `quota_after` — codex_quota.snapshot() immediately
        before and after the call, and `quota_source`;
      * `tokens` — this call's total token usage from its own rollout (plan I9);
      * a failed call (no valid verdict) is classified ONCE, exactly as main()'s
        codex slot classifies it (_classify_codex_attempt, attempt 1): when that
        classification is (substitute, quota_exhausted) the arm's error becomes
        "codex quota exhausted (quota_exhausted): <error>" and `quota_source` is
        QUOTA_SOURCE_EXHAUSTION. The corroborating meter read happens only here, with
        `usage_out`; without it the classification uses the error lines alone. The
        audit is never refused by thresholds or budget (design §4.7). A run that DID
        return a valid verdict (a retried 429, say) is not classified and reads
        nothing extra.

    This is ONE codex call. What happens after a failed call — the one same-model
    retry, the Claude substitute, or AUDIT_UNAVAILABLE — is decided by main()'s codex
    slot (_run_codex_arm) through codex_quota.classify_codex_failure (S081 WP-F03);
    it is never a retry on a cheaper or different codex model.
    """
    verdict, err, outcome = _codex_attempt(prompt, timeout_s, usage_out)
    if verdict is None:
        _action, _reason, err = _classify_codex_attempt(
            prompt, 1, verdict, err, outcome, usage_out, read_meter=usage_out is not None)
    return verdict, err


def _codex_outcome(returncode: Optional[int], stderr: Any, timed_out: bool) -> Dict[str, Any]:
    """What codex_quota.classify_codex_failure reads about one finished codex call."""
    return {"returncode": returncode, "stderr": stderr, "timed_out": timed_out}


def _outcome_from_watch(result: Any, stderr: Any) -> Dict[str, Any]:
    """Map a codex_watch stop reason onto the classifier contract (D24).

    codex_quota.classify_codex_failure decides retry / substitute / gap, and no new
    SUBSTITUTION_REASONS token is invented; the watchdog's two stop reasons are
    expressed in the outcome fields the classifier reads:

      * `idle_timeout` -> timed_out=True. The call went silent past the idle timeout,
        which is the RETRYABLE kind of stop: the classifier's rule gives
        (retry, "timeout") on attempt 1 and (substitute, "timeout_twice") on attempt 2.
      * `hard_cap`     -> timed_out=False, returncode=codex_watch.EXIT_HARD_CAP (112).
        A runaway that stayed ACTIVE to its cap is NOT the retryable kind, and the
        classifier decides 112 FIRST -- after argument validation, before cli_missing
        and before every exhaustion / auth / capacity signal -- so it is
        (gap, "codex_error") on EVERY attempt, whatever stderr says: never a retry,
        never a substitution (S081 rev 4 D21 F10, fixed in codex_quota; until then a
        codex error line in the transcript was read first and bought a retry or a
        substitute).

    `timed_out=False` on a hard cap reads oddly and is deliberate: in this contract the
    flag does not mean "ran out of wall time", it means "stopped in the retryable way".
    Both meanings coincided while one fixed timeout was the only stop; the watchdog
    splits them, and only the idle stop keeps the retry.
    """
    if result.stop_reason == codex_watch.STOP_IDLE_TIMEOUT:
        return _codex_outcome(None, stderr, True)
    if result.stop_reason == codex_watch.STOP_HARD_CAP:
        return _codex_outcome(codex_watch.EXIT_HARD_CAP, stderr, False)
    return _codex_outcome(result.child_exit_code, stderr, False)


def _read_stream_file(path: Path) -> str:
    """One of the watchdog's stream files as text. Never raises: a call stopped
    mid-write must still hand the classifier whatever transcript exists."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class _WatchedProc:
    """The `subprocess.CompletedProcess` shape the rest of this arm reads.

    D24 moved the spawn into codex_watch, which streams to files and returns a
    WatchResult. Everything downstream (`_codex_verdict_from`, the banner
    provenance, `_stamp_usage`) was written against `.stdout` / `.stderr` /
    `.returncode`, and none of it needs to know the process was watched — so the
    result is adapted here rather than rewriting those readers.
    """

    __slots__ = ("stdout", "stderr", "returncode", "watch_result")

    def __init__(self, stdout: str, stderr: str, result: Any) -> None:
        self.stdout = stdout
        self.stderr = stderr
        # The CHILD's own exit status, not the watchdog's: a normally-finished
        # call must classify exactly as it did before D24.
        self.returncode = result.child_exit_code
        self.watch_result = result


def _codex_attempt(
    prompt: str,
    timeout_s: int,
    usage_out: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    """One watched `codex exec` call: (verdict, error, outcome). See run_codex_auditor.

    D24: the call runs under codex_watch, so it is stopped by INACTIVITY (no heartbeat
    for IDLE_TIMEOUT_S) or by the seat's registry timeout as a runaway cap — never by a
    fixed wall clock that a long-but-healthy call trips.

    `outcome` = {returncode, stderr, timed_out}: the exit status (127, a shell's
    "command not found", when the binary is missing at spawn; codex_watch.EXIT_HARD_CAP
    when the runaway cap stopped it; None when the watchdog stopped it on silence),
    codex's stderr and whether the stop was the RETRYABLE kind. `_outcome_from_watch`
    documents that mapping and why a hard cap is a gap rather than a retry.
    """
    cmd = [
        CODEX_BIN,
        "exec",
        # #302 §3.4b / JC-3: never --ephemeral, whatever the seat - the session is metered.
        "--skip-git-repo-check",
        "-s", "read-only",
        # BOTH axes pinned, from the single resolver: `-m <model>` and
        # `-c model_reasoning_effort=<effort>`. `-m` is ALWAYS present — there
        # is no "omit and inherit" shape (design §4.1). Both are `codex exec`
        # options and must precede the PROMPT positional.
        *CODEX_PIN.argv_fragment,
        # #291 fix round 2, N2: the prompt travels on STDIN, never argv. Linux caps one
        # argv string at MAX_ARG_STRLEN (131072 bytes); a larger prompt died with E2BIG
        # before the call and was classified a GAP on every attempt. `-` is the documented
        # `codex exec` spelling for "read the instructions from stdin" (`codex exec --help`,
        # 0.154.0). codex_watch feeds stdin from a regular file, which EOFs (STDIN RULE).
        "-",
    ]
    _arm_start = time.time()

    if usage_out is not None:
        # Provenance defaults. REQUESTED and REPORTED are recorded SEPARATELY
        # (design §4.6); anything not observed stays MODEL_UNKNOWN rather than
        # being backfilled from the request.
        usage_out.setdefault("requested_model", CODEX_MODEL)
        usage_out.setdefault("requested_effort", CODEX_EFFORT)
        usage_out.setdefault("requested_source", CODEX_MODEL_SOURCE)
        usage_out.setdefault("reported_model", MODEL_UNKNOWN)
        usage_out.setdefault("reported_effort", MODEL_UNKNOWN)
        usage_out.setdefault("reported_source", MODEL_UNKNOWN)
        usage_out.setdefault("tokens", None)
        # The meter, immediately before the call.
        usage_out["quota_before"] = _take_quota_reading()
        usage_out["quota_source"] = QUOTA_SOURCE_METER

    def _stamp_usage(envelope: Any) -> None:
        if usage_out is None:
            return
        try:
            usage = _extract_usage(envelope)  # plain text -> all-None
            usage_out.update(usage)
            usage_out["wall_clock_s"] = round(time.time() - _arm_start, 3)
        except BaseException:  # noqa: BLE001
            usage_out.setdefault("wall_clock_s", round(time.time() - _arm_start, 3))

    def _stamp_quota_after() -> None:
        # The meter, immediately after the call (whatever way it ended).
        if usage_out is not None:
            usage_out["quota_after"] = _take_quota_reading()

    # D24: the arm is stopped by INACTIVITY, not by a wall clock. codex_watch spawns
    # the process (stdin the prompt file, both streams to files) and polls for a heartbeat —
    # stdout grew, stderr grew (codex prints its transcript there), or the session
    # rollout file's mtime advanced. A long-but-healthy call now finishes.
    #
    # THE HARD CAP IS THE SEAT'S REGISTRY TIMEOUT, NOT codex_watch.hard_cap_for().
    # `timeout_s` is CODEX_TIMEOUT_S == CODEX_PIN.timeout, resolved through
    # seat_model/codex_model — the ONE codex timeout owner (design §4.2, I20/L5).
    # The watchdog's own HARD_CAP_S table agrees with it tier-for-tier today, but
    # reading that table here would create a SECOND owner free to drift from the
    # registry the rest of the harness resolves against. The idle timeout, which no
    # registry has an opinion about, does come from the watchdog constant.
    try:
        with tempfile.TemporaryDirectory(prefix="audit-codex-arm-") as _stream_dir:
            _out_path = Path(_stream_dir) / "codex.stdout"
            _err_path = Path(_stream_dir) / "codex.stderr"
            _in_path = Path(_stream_dir) / "codex.stdin"
            # UTF-8 whatever the locale (the codex twin of #291 fix round 1 C).
            _in_path.write_bytes(prompt.encode("utf-8"))
            watched = codex_watch.watch(
                cmd,
                mode=codex_watch.MODE_CODEX,
                stdout_path=_out_path,
                stderr_path=_err_path,
                stdin_path=_in_path,
                model=CODEX_MODEL,
                hard_cap_s=timeout_s,
                idle_timeout_s=codex_watch.IDLE_TIMEOUT_S,
                # #292: a SIGTERM / SIGHUP to this process reaps the child here.
                _stop_latch=_STOP_LATCH,
                # STDIN RULE (#155 / design D6) is enforced inside the watchdog's
                # spawn: verified live on codex 0.153.4, `codex exec` prints
                # "Reading additional input from stdin..." and waits, so an
                # inherited never-EOFing stdin hangs the arm at 0 bytes before any
                # API call. The prompt travels on stdin from a REGULAR FILE, which
                # EOFs at its end (#291 fix round 2 N2; see `cmd` above).
            )
            # The watchdog streams to files rather than capturing in memory, so the
            # transcript is read back here. errors="replace": a call killed mid-write
            # can leave a partial multi-byte sequence, and the classifier must still
            # see the stderr it decides on.
            stdout_text = _read_stream_file(_out_path)
            stderr_text = _read_stream_file(_err_path)
    except FileNotFoundError:
        _stamp_quota_after()
        _stamp_usage(None)
        return (None, f"codex binary not found ({CODEX_BIN})",
                _codex_outcome(codex_quota.EXIT_COMMAND_NOT_FOUND, None, False))
    except codex_watch.CodexWatchError as exc:
        _stamp_quota_after()
        _stamp_usage(None)
        return None, f"codex watchdog refused the call: {exc}", _codex_outcome(None, None, False)
    except OSError as e:
        _stamp_quota_after()
        _stamp_usage(None)
        return None, f"codex subprocess OS error: {e}", _codex_outcome(None, None, False)
    _stamp_quota_after()

    proc = _WatchedProc(stdout_text, stderr_text, watched)
    if watched.stop_reason == codex_watch.STOP_IDLE_TIMEOUT:
        _stamp_usage(None)
        return (None,
                f"codex call went silent for {int(watched.idle_timeout_s or 0)}s "
                f"(idle timeout) after {int(watched.elapsed_s)}s",
                _outcome_from_watch(watched, stderr_text))
    if watched.stop_reason == codex_watch.STOP_HARD_CAP:
        _stamp_usage(None)
        return (None,
                f"codex call reached its {int(watched.hard_cap_s)}s hard cap while still "
                f"active (longest silence {int(watched.max_silence_s)}s)",
                _outcome_from_watch(watched, stderr_text))

    stderr = getattr(proc, "stderr", None)
    # Banner provenance (design §4.6 / D7). Read BEFORE the returncode check on
    # purpose: codex prints the banner before the API call, so a run that later
    # fails still tells us which model it was about to use — and a non-zero exit
    # is exactly when knowing that matters.
    if usage_out is not None:
        reported_model, reported_effort = _extract_codex_banner(stderr)
        usage_out["reported_model"] = reported_model
        usage_out["reported_effort"] = reported_effort
        usage_out["reported_source"] = (
            "codex_stderr_banner" if reported_model != MODEL_UNKNOWN
            else MODEL_UNKNOWN
        )
        usage_out["tokens"] = _codex_rollout_tokens(_codex_session_id(stderr))

    # codex exec emits plain prose, not a JSON envelope -> usage stays null.
    _stamp_usage(proc.stdout)

    outcome = _codex_outcome(getattr(proc, "returncode", None), stderr, False)
    verdict, err = _codex_verdict_from(proc)
    # #282 R2: no signal matching here. What a failed call means (and whether its error
    # names a quota stop) is decided by ONE classification in _classify_codex_attempt.
    return verdict, err, outcome


def _classify_codex_attempt(
    prompt: str,
    attempt: int,
    verdict: Optional[Dict[str, Any]],
    err: Optional[str],
    outcome: Dict[str, Any],
    usage_out: Optional[Dict[str, Any]],
    *,
    read_meter: bool = True,
) -> Tuple[str, Optional[str], Optional[str]]:
    """ONE classification of one finished codex call: (action, reason, error). #282 R2.

    A FAILED call (no valid verdict) gets ONE corroboration — codex_quota.corroboration_for
    (stderr, prompt): its codex-owned error lines and one post-call unavailable() reading —
    passed to the ONE codex_quota.classify_codex_failure call (with the prompt, so an echoed
    bundle cannot impersonate a stop). `read_meter=False` (a caller that records nothing)
    classifies on the error lines alone (corroboration None, no read). A call that returned
    a valid verdict builds no corroboration and reads nothing.

    The quota wording is derived from THAT result only: (substitute, quota_exhausted) turns
    `error` into "codex quota exhausted (quota_exhausted): <error>" and sets `quota_source`
    to QUOTA_SOURCE_EXHAUSTION on `usage_out`. Nothing else here matches stderr.
    """
    corroboration: Optional[Dict[str, Any]] = None
    if verdict is None and read_meter:
        corroboration = codex_quota.corroboration_for(outcome["stderr"], prompt)
    action, reason = codex_quota.classify_codex_failure(
        outcome["returncode"], outcome["stderr"], timed_out=outcome["timed_out"],
        output_ok=verdict is not None, attempt=attempt, prompt=prompt, corroboration=corroboration,
    )
    if action == codex_quota.ACTION_SUBSTITUTE and reason == codex_quota.UNAVAILABLE_QUOTA_EXHAUSTED:
        if usage_out is not None:
            usage_out["quota_source"] = QUOTA_SOURCE_EXHAUSTION
        if err is not None:
            err = f"codex quota exhausted ({reason}): {err}"
    return action, reason, err


def _codex_verdict_from(proc: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(verdict, None) or (None, error) for a completed codex process."""
    if proc.returncode != 0:
        return None, f"codex exited {proc.returncode}: {(proc.stderr or '')[:200]}"

    parsed = _extract_json_from_codex_output(proc.stdout)
    if parsed is None:
        return None, "codex output not parseable as JSON"

    verdict, err = validate_verdict(parsed)
    if err:
        return None, f"codex verdict invalid: {err}"
    return verdict, None


# ---------------------------------------------------------------------------
# The codex slot — astra unavailable -> a fresh Claude auditor (S081 amendment 1 D6)
# ---------------------------------------------------------------------------


def _codex_cli_missing() -> bool:
    """True when no codex binary can be found for CODEX_BIN (plan J12).

    shutil.which is an in-process PATH lookup (no subprocess, no stale inventory),
    and it follows CODEX_BIN, so an AUDIT_CODEX_BIN stub counts as present."""
    return not CODEX_BIN or shutil.which(CODEX_BIN) is None


#: _plan_time_unavailable()'s answer when the codex slot is a GAP, not a substitution
#: (#282 R1): AUDIT_CODEX_BIN is set and names no binary. It is never a substitution
#: reason — it never reaches seat_model.substitute or the budget store.
PRECALL_GAP_BIN_OVERRIDE = "codex_bin_override_missing"


def _bin_override_gap(cause: Optional[str] = None, reason: Optional[str] = None) -> str:
    """The codex_error of a codex slot the binary override turned into a GAP (#282 R1, F1).

    Names the variable, its value and the realpath recorded at import. `cause` is the
    call-time spawn error, when there was a spawn.

    #282 fix round 1 F1 (plan K36) generalized the middle clause. "names no codex
    binary" is the MISSING-BINARY case only (`reason` None: the plan-time gap, where
    the presence check itself failed). When the override's binary RAN and the
    classifier asked for a substitution, `reason` is that classifier substitution
    reason (malformed_twice, timeout_twice, capacity_twice, quota_exhausted,
    auth_failure, cli_missing) and the clause reads "produced <reason>" — the audit
    result is AUDIT_UNAVAILABLE either way, with no substitution row, no substitute
    spawn, and a codex provenance block that keeps `bin_override` and gains none of
    the substitution keys.
    """
    override = CODEX_BIN_OVERRIDE or {}
    middle = f"produced {reason}" if reason is not None else "names no codex binary"
    text = (
        f"codex arm unavailable: {override.get('var', 'AUDIT_CODEX_BIN')}={override.get('value')!r} "
        f"(realpath {override.get('realpath')!r}) {middle}; a binary override is "
        f"never substituted, so the codex slot is a gap"
    )
    return f"{text} ({cause})" if cause else text


def _plan_time_unavailable() -> Optional[str]:
    """The reason astra cannot serve the codex slot BEFORE any admission, else None.

    Checked in the seat_model CLI's order (plan J10): the codex pin first (the
    resolver found no eligible TOP -> `no_eligible_model`; a harness literal served
    because there is NO roster is sanctioned and is not this), then the binary
    (`cli_missing`). Neither case makes a TOP call, so neither records an audit
    admission — the budget rows count TOP calls, and this one will not happen.

    #282 R1: a missing binary while AUDIT_CODEX_BIN is set returns
    PRECALL_GAP_BIN_OVERRIDE instead of `cli_missing` — the slot is a gap, decided
    here, before any admission. An un-overridden `codex` absent from PATH keeps the
    `cli_missing` substitution; `no_eligible_model` is unaffected by the override.

    #282 fix round 1 F9: CODEX_BIN_OVERRIDE is set whenever AUDIT_CODEX_BIN is
    PRESENT in the environment — even when its value is literally `codex` and even
    when the binary resolves — so a missing binary under ANY override reaches the
    gap above, never `cli_missing` and never a substitution. K35 keeps this
    PRE-CALL path otherwise unchanged: `no_eligible_model` (the roster said nothing
    is eligible, not the overridden binary's doing) and a pre-call meter token from
    _admit_audit (a real meter reading) still substitute, override or not. What the
    override does map, totally, is every substitution the classifier produces AFTER
    a call — mapped at the call site in _run_codex_arm (F1), not here.
    """
    if CODEX_PIN.provenance.get("unavailable_reason") == seat_model.UNAVAILABLE_NO_ELIGIBLE:
        return seat_model.UNAVAILABLE_NO_ELIGIBLE
    if _codex_cli_missing():
        if CODEX_BIN_OVERRIDE is not None:
            return PRECALL_GAP_BIN_OVERRIDE
        return seat_model.UNAVAILABLE_CLI_MISSING
    return None


def _join_timeout_s(claude_timeout_s: int, codex_timeout_s: int, substitute_timeout_s: int) -> int:
    """How long main() waits on each arm's future: the LONGEST path either arm can take, + 30.

    The Claude arm is one call (`claude_timeout_s`). The codex slot's worst case (plan J13)
    is a codex call that times out, the one same-model retry timing out too, and then the
    fresh Claude substitute running to its own budget — all inside the codex worker:
    CODEX_MAX_ATTEMPTS x codex_timeout_s + substitute_timeout_s.
    Joining on anything shorter would cut a legitimately running substitute and report it
    as an outer-timeout failure.

    THE SHAPE IS UNCHANGED BY D24; ONLY ITS INPUT MOVED. The formula still reads the codex
    arm's own ceiling, which is now the raised registry timeout (code_reviewer/codex xhigh
    600 -> 2400, S081 revision 4 stream A0). With today's pins:
    max(600, 2 x 2400 + 600) + 30 = 5430s (it was max(600, 2 x 600 + 600) + 30 = 1830s
    before the raise, and max(600, 600) + 30 = 630s before WP-F03). Widening it here is
    load-bearing: leaving the join at 1830 while each codex attempt may now run to 2400
    would make the JOIN the new premature killer — the truncation would simply move from
    the arm to the pool, which is the failure D24 exists to remove.

    RECORDED LIMIT, RESTATED AT ITS NEW VALUE (plan J13, accepted by the lead; WP-A03
    criterion "J13 IS RECORDED, NOT SILENTLY WIDENED"): the freshness window is NOT widened
    to match. bob's ARBITER_FRESHNESS_WINDOW_S (claims.py, 1800s by default) stays 1800s,
    so the worst case now exceeds it by 3630s rather than by 30s. This FAILS CLOSED and is
    accepted on that basis — it is fail-closed: a verification request that goes stale yields
    no VERIFIED transition (never a false pass), only an escalation. Reaching the worst case
    still needs codex to be stopped twice and the substitute to use its whole budget, and the
    freshness sweep runs only at bob startup. What changed is the FREQUENCY with which a slow audit can
    cross 1800s, which is why codex_watch emits `elapsed_s` on every call (its telemetry row,
    persisted by spawn_runs) — so the crossing rate is measured rather than assumed.
    """
    return max(claude_timeout_s, CODEX_MAX_ATTEMPTS * codex_timeout_s + substitute_timeout_s) + 30


def _substitute_codex_arm(
    prompt: str,
    reason: str,
    codex_err: Optional[str],
    usage_out: Dict[str, Any],
    *,
    project_root: Path,
    attempts: int,
    admission_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Serve the codex slot with a fresh cold-context Claude auditor on THE SAME prompt.

    seat_model.substitute() picks the model (the code_reviewer Claude row, never a gpt-
    model) and records ONE `kind: substitution` budget row, naming `admission_id` — the
    audit admission this substitution replaces, or None (#282 r10). The auditor is its own
    `claude -p` subprocess with the SUBSTITUTE_TIMEOUT_S budget. `usage_out["substitution"]`
    carries what the provenance block and the telemetry row need. A substitution that
    cannot be made, or a substitute without a valid verdict, is (None, error) naming BOTH
    failures — never an unrecorded fallback call, never a pass.
    """
    record: Dict[str, Any] = {"reason": reason, "codex_attempts": attempts, "timeout_s": SUBSTITUTE_TIMEOUT_S}
    usage_out["substitution"] = record
    cause = codex_err if codex_err else f"codex not run ({reason})"
    # "no eligible TOP" means nothing astra-eligible was requested: the pin is a placeholder
    # literal, so the row records null rather than a model the roster ruled out (as the
    # seat_model CLI records it).
    requested = None if reason == seat_model.UNAVAILABLE_NO_ELIGIBLE else CODEX_MODEL
    record["requested_model"] = requested
    # #292 (D21 re-review N1): the last point before the budget row and the stand-in spawn.
    _raise_if_stopped()
    try:
        pin = seat_model.substitute(REVIEWER_ROLE, QUOTA_USE, reason, project_root=project_root,
                                    requested_model=requested, admission_id=admission_id)
        model = pin.model
        if not isinstance(model, str) or not model or model.lower().startswith("gpt-"):
            raise seat_model.SeatModelError(f"refusing substitute model {model!r}: never a codex model")
    except Exception as exc:  # noqa: BLE001 - a substitution that cannot be made is a failure, not a crash
        record["error"] = f"{type(exc).__name__}: {exc}"
        return None, f"codex arm unavailable ({reason}): {cause}; substitute not run: {record['error']}"
    record["served_model"] = model
    if not pin.provenance.get("row_written"):
        record["row_error"] = str(pin.provenance.get("row_error") or "the substitution row was not written")
    eprint(
        f"audit_spawn: codex arm unavailable ({reason!a}) - a fresh {model!a} auditor serves the codex "
        f"slot with the same prompt (provider gap: {PROVIDER_GAP})"
    )
    substitute_usage: Dict[str, Any] = {}
    record["usage"] = substitute_usage
    # G4 (plan K56): the substitute runs from its OWN reviewer cwd. It shares a
    # ThreadPoolExecutor with the Claude arm, so a shared directory meant the arm could
    # re-create `memory/` after the substitute had quarantined it.
    _raise_if_stopped()  # #292 re-review N1: a stop that landed while the row was written
    verdict, err = run_claude_auditor(prompt, SUBSTITUTE_TIMEOUT_S, substitute_usage, model=model,
                                      project_root=project_root, variant="substitute",
                                      effort=pin.effort)   # #311 F1: the substitute's pinned effort
    if verdict is None:
        return None, f"codex arm unavailable ({reason}): {cause}; {model} substitute failed: {err}"
    return verdict, None


def _run_codex_arm(
    prompt: str,
    codex_timeout_s: int,
    usage_out: Dict[str, Any],
    *,
    project_root: Path,
    precall_reason: Optional[str],
    admission_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The codex slot of the conjunction: (verdict, error). Never raises, except
    codex_watch._StopSignal once main()'s stop latch is set (#292): a stop starts no new work.

    `precall_reason` set -> no codex call; the substitute serves the slot at once
    (PRECALL_GAP_BIN_OVERRIDE -> the gap error instead, nothing substituted).
    Otherwise codex runs, and codex_quota.classify_codex_failure (the ONE classifier,
    given the prompt so an echoed bundle cannot impersonate a stop, and — for a failed
    call — ONE corroboration, #282 R2; see _classify_codex_attempt) decides:
    ok -> the verdict; retry (a timeout / malformed / at-capacity answer on the first
    call) -> the SAME argv again; substitute -> _substitute_codex_arm; gap -> the codex error
    (AUDIT_UNAVAILABLE, as before WP-F03). #282 R1: substitute `cli_missing` while
    AUDIT_CODEX_BIN is set is a gap too — the classifier is override-blind, so the
    mapping is made here. `usage_out` keeps the FIRST call's quota_before and the
    last call's everything else, plus `codex_attempts` and the arm's total wall_clock_s.

    #282 r10: `admission_id` is main()'s audit admission (None when there was none or its
    row was not written). A pre-call `unavailable` substitution and every call-time
    substitution name it; a plan-time reason (no_eligible_model / cli_missing) never does —
    no admission happened for it, whatever a caller passed.
    """
    arm_start = time.time()
    attempts = 0
    try:
        if precall_reason == PRECALL_GAP_BIN_OVERRIDE:
            return None, _bin_override_gap()
        if precall_reason is not None:
            _raise_if_stopped()
            plan_time = precall_reason in (seat_model.UNAVAILABLE_NO_ELIGIBLE, seat_model.UNAVAILABLE_CLI_MISSING)
            return _substitute_codex_arm(prompt, precall_reason, None, usage_out,
                                         project_root=project_root, attempts=0,
                                         admission_id=None if plan_time else admission_id)
        first_quota_before: Any = None
        while True:
            attempts += 1
            verdict, err, outcome = _codex_attempt(prompt, codex_timeout_s, usage_out)
            if attempts == 1:
                first_quota_before = usage_out.get("quota_before")
            else:
                usage_out["quota_before"] = first_quota_before
            # #282 R2: ONE corroboration per failed attempt, ONE classification per attempt.
            action, reason, err = _classify_codex_attempt(prompt, attempts, verdict, err, outcome, usage_out)
            if action == codex_quota.ACTION_OK and verdict is not None:
                return verdict, None
            _raise_if_stopped()
            if action == codex_quota.ACTION_RETRY and attempts < CODEX_MAX_ATTEMPTS:
                eprint(f"audit_spawn: codex call {attempts} failed ({reason!a}); one retry on the same model")
                continue
            # #282 fix round 1 F1 (plan K35/K36): EVERY substitution the classifier asks for
            # is the override gap while CODEX_BIN_OVERRIDE is set — not only cli_missing (R1).
            # An AUDIT_CODEX_BIN that exits 0 with unusable output reaches malformed_twice and
            # a hanging one timeout_twice, and either would otherwise buy a Claude substitute,
            # i.e. two Claude verdicts for a conjunction that must have two providers. The
            # classifier stays override-blind and pure; the mapping lives here, at the call site.
            if action == codex_quota.ACTION_SUBSTITUTE and reason is not None \
                    and CODEX_BIN_OVERRIDE is not None:
                return None, _bin_override_gap(err, reason=reason)
            if action == codex_quota.ACTION_SUBSTITUTE and reason is not None:
                return _substitute_codex_arm(prompt, reason, err, usage_out,
                                             project_root=project_root, attempts=attempts,
                                             admission_id=admission_id)
            return None, err if err is not None else f"codex call failed ({action} {reason})"
    except Exception as exc:  # noqa: BLE001 - the slot fails closed, it never crashes the audit
        return None, f"codex arm error: {type(exc).__name__}: {exc}"
    finally:
        usage_out["codex_attempts"] = attempts
        usage_out["wall_clock_s"] = round(time.time() - arm_start, 3)


# ---------------------------------------------------------------------------
# Bundle + map loading
# ---------------------------------------------------------------------------


def load_audit_bundle(path: Path) -> Dict[str, Any]:
    """Load a sanitized audit bundle and verify trusted provenance (CB3)."""
    if not path.is_file():
        env_error(f"audit bundle not found at {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        env_error(f"audit bundle is not valid JSON: {e}")
    if not isinstance(data, dict):
        env_error("audit bundle is not a JSON object")
    # CB3 — provenance check. The auditor MUST refuse bundles not produced
    # by bob's trusted runner. Skill-produced bundles are rejected.
    if data.get("produced_by") != "bob-trusted-runner":
        env_error(
            f"audit bundle provenance {data.get('produced_by')!r} != "
            f"'bob-trusted-runner' — CB3 provenance violation"
        )
    return data


def load_component_entry(project_root: Path, component_id: str) -> Dict[str, Any]:
    """Load the component entry from progress/contract-map.yaml."""
    map_path = project_root / "progress" / "contract-map.yaml"
    if not map_path.is_file():
        env_error(f"contract-map.yaml not found at {map_path}")
    try:
        import yaml  # type: ignore
    except ImportError:
        env_error("pyyaml not installed")
    try:
        data = yaml.safe_load(map_path.read_text())
    except yaml.YAMLError as e:
        env_error(f"contract-map.yaml unparseable: {e}")
    for c in (data.get("components") or []):
        if isinstance(c, dict) and c.get("id") == component_id:
            return c
    env_error(f"component {component_id!r} not in contract map")


def _parse_projection_table(text: str, component_id: str) -> Optional[Dict[str, Any]]:
    """Parse the ledger's projection table (authoritative current stage).

    The table has this shape (leading/trailing whitespace and cell padding
    are tolerated; ``—`` / ``-`` / ``—`` are all valid "empty" markers):

        | WP   | component              | stage      | generation | deps |
        |------|------------------------|------------|------------|------|
        | WP-2 | wiring-extract-static  | INTEGRATED | 3          | —    |

    Bob writes this table at the top of ``progress/integration-ledger.md``
    as the **authoritative** projection of component state. Event-log prose
    sections (``### <ts> — WP-N STAGE_A → STAGE_B ...``) are advisory
    history only; the projection table wins on conflict.

    Returns a dict with ``component_id``, ``stage``, ``generation`` (int),
    and optionally ``wp``, ``deps``. Returns None if the table is missing,
    malformed, or the component is absent.
    """
    import re

    # Locate the first markdown table that declares a "component" column and a
    # "stage" column. This tolerates extra columns in future schema revisions.
    lines = text.splitlines()
    table_start = -1
    header_cells: List[str] = []
    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
        if "component" in cells and "stage" in cells and "generation" in cells:
            table_start = i
            header_cells = cells
            break
    if table_start < 0:
        return None

    # The next line after the header must be the separator `|---|---|...`.
    sep_idx = table_start + 1
    if sep_idx >= len(lines):
        return None
    sep = lines[sep_idx].strip()
    if not re.match(r"^\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", sep):
        return None

    # Column indices
    col = {name: idx for idx, name in enumerate(header_cells)}
    comp_idx = col["component"]
    stage_idx = col["stage"]
    gen_idx = col["generation"]
    wp_idx = col.get("wp")
    deps_idx = col.get("deps")

    # Iterate data rows until a blank / non-table line.
    for row_line in lines[sep_idx + 1:]:
        stripped = row_line.strip()
        if not stripped or not stripped.startswith("|"):
            break
        cells_raw = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells_raw) <= max(comp_idx, stage_idx, gen_idx):
            continue  # malformed / short row — skip

        # Strip markdown emphasis from cells (``*smoke*``, ``**foo**``).
        def _clean(s: str) -> str:
            return s.strip().strip("*").strip("_").strip()

        component_cell = _clean(cells_raw[comp_idx])
        if component_cell != component_id:
            continue

        stage_cell = _clean(cells_raw[stage_idx])
        gen_cell = _clean(cells_raw[gen_idx])
        # Generation may be "—", "-", or missing — in those cases we emit 0.
        try:
            generation = int(gen_cell)
        except (ValueError, TypeError):
            generation = 0

        out: Dict[str, Any] = {
            "component_id": component_id,
            "stage": stage_cell or "UNKNOWN",
            "generation": generation,
        }
        if wp_idx is not None and len(cells_raw) > wp_idx:
            out["wp"] = _clean(cells_raw[wp_idx])
        if deps_idx is not None and len(cells_raw) > deps_idx:
            deps_cell = _clean(cells_raw[deps_idx])
            if deps_cell in ("", "—", "-", "–"):
                out["deps"] = []
            else:
                out["deps"] = [d.strip() for d in deps_cell.split(",") if d.strip()]
        return out

    return None


def _parse_yaml_fenced_events(text: str, component_id: str) -> Optional[Dict[str, Any]]:
    """Legacy event-log parser (spec §9.2 yaml-fenced shape).

    Kept for backward compatibility with ledgers that emit events as
    ``\\`\\`\\`yaml`` fenced blocks. Returns the row rebuilt from the most
    recent event, or None if no matching event exists.
    """
    import re

    blocks = re.findall(r"```yaml\s*\n(.*?)\n```", text, re.DOTALL)
    if not blocks:
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        return None

    row: Dict[str, Any] = {"component_id": component_id, "stage": "PLANNED", "generation": 0}
    latest_at = ""
    matched = False
    for block in blocks:
        try:
            evt = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if not isinstance(evt, dict):
            continue
        if evt.get("component_id") != component_id:
            continue
        matched = True
        at = str(evt.get("at", ""))
        if at >= latest_at:
            latest_at = at
            if "to" in evt:
                row["stage"] = evt["to"]
            if "generation" in evt:
                try:
                    row["generation"] = int(evt["generation"])
                except (ValueError, TypeError):
                    pass
    return row if matched else None


def load_ledger_row(project_root: Path, component_id: str) -> Dict[str, Any]:
    """Load a minimal ledger row projection for the component.

    Stage-resolution precedence (most authoritative first):

    1. **Projection table** — the markdown table at the top of
       ``progress/integration-ledger.md`` with columns
       ``| WP | component | stage | generation | deps |``. This is bob's
       authoritative projection and wins over everything else.
    2. **Yaml-fenced events (legacy §9.2)** — rebuilt from the most
       recent ``\\`\\`\\`yaml ... \\`\\`\\``` event that matches
       ``component_id``. Used only when no projection table exists.
    3. **Unknown** — if neither source has a row for the component,
       returns ``{stage: "UNKNOWN", ...}`` (NOT ``PLANNED``, which
       would falsely imply the component is tracked but un-started).

    Prose event sections like
    ``### 2026-04-15T00:52:00Z — WP-2 UNIT_TESTED → INTEGRATED (bob applied)``
    are advisory history. The parser intentionally does not try to derive
    stage from prose — bob's projection table is the single source of truth.
    """
    ledger_path = project_root / "progress" / "integration-ledger.md"
    if not ledger_path.is_file():
        return {"component_id": component_id, "stage": "UNKNOWN", "note": "ledger missing"}
    text = ledger_path.read_text()

    # Precedence 1: projection table wins.
    row = _parse_projection_table(text, component_id)
    if row is not None:
        return row

    # Precedence 2: legacy yaml-fenced event log.
    row = _parse_yaml_fenced_events(text, component_id)
    if row is not None:
        return row

    # Precedence 3: component is not tracked anywhere.
    return {"component_id": component_id, "stage": "UNKNOWN", "generation": 0, "note": "component not in projection table or events"}


# ---------------------------------------------------------------------------
# Verdict aggregation
# ---------------------------------------------------------------------------


def aggregate_verdicts(claude: Dict[str, Any], codex: Dict[str, Any]) -> str:
    """Spec section 11.4 step 3:
    - Both pass → VERIFIED
    - Either fail → REJECTED (stays INTEGRATED)
    - pass_with_concerns → proceed to VERIFIED but concerns logged
    """
    if claude["verdict"] == "fail" or codex["verdict"] == "fail":
        return "REJECTED"
    # Both are pass or pass_with_concerns
    if claude["verdict"] == "pass" and codex["verdict"] == "pass":
        return "VERIFIED"
    return "VERIFIED_WITH_CONCERNS"


def merge_disagreements(claude: Dict[str, Any], codex: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return combined, deduped disagreements from both auditors."""
    seen_points: set = set()
    out: List[Dict[str, Any]] = []
    for source, verdict in (("claude", claude), ("codex", codex)):
        for d in verdict.get("structured_disagreements", []):
            key = (d.get("point") or "").strip().lower()
            if not key or key in seen_points:
                continue
            seen_points.add(key)
            out.append({
                "source": source,
                "point": d["point"],
                "severity": d["severity"],
                "location": d.get("location", ""),
            })
    return out


# ---------------------------------------------------------------------------
# Observe-only spawn-run telemetry (S046 / #124)
# ---------------------------------------------------------------------------


def _emit_audit_spawn_runs(
    *,
    claude_usage: Dict[str, Any],
    codex_usage: Dict[str, Any],
    claude_verdict: Optional[Dict[str, Any]],
    claude_err: Optional[str],
    codex_verdict: Optional[Dict[str, Any]],
    codex_err: Optional[str],
    invocation_id: str,
    cycle_id: Optional[str],
    component_id: str,
    bundle_hash: Optional[str],
    project_root: Path,
) -> None:
    """Append one spawn-run record per audit arm. BEST-EFFORT; never raises.

    The audit arm is NOT request-bound (no verification request id), so
    request_id is left null; the arbiter arm (the other spawner) carries it.
    `status` is the arm's verdict string on success or an error sentinel on
    failure — observe-only context, never a gate signal.

    S081 WP-R06 (design §4.11): both rows also carry `requested_model`,
    `served_model` (codex: the stderr banner; Claude: "unknown" — it prints no
    pre-call banner), `tokens` (plan I9), `role`, and `env_override_refused` when
    an override was refused; the codex row adds `quota_before`, `quota_after` and
    `quota_source`. spawn_runs omits a key whose value is None.

    S081 WP-F03 (plan J15): when a Claude substitute served the codex slot, the row keeps
    tool "audit_codex" (the arm's identity, so rollups stay comparable); `model` names
    the substitute's alias and `requested_model` the codex model the seat asked for
    (absent for no_eligible_model); cost, duration, turns and tokens come from the
    substitute's claude envelope; wall_clock_s is the whole slot (codex calls +
    substitute); quota readings bracket the codex calls that ran (absent when none did);
    and `substitute_for` / `substitution_reason` / `use` are added. Every other row keeps
    its key set.

    #282 R3 (plan K5): `served_model` on the audit_claude row and on a substituted
    audit_codex row is the id the claude envelope's modelUsage names ("unknown"
    without modelUsage — it used to be "unknown" / the substitute's alias, i.e. the
    request echoed back); those rows add `served_model_usage` ({id: outputTokens},
    every key) when the envelope had modelUsage and `served_model_mismatch: true` only
    on a mismatch. An un-substituted codex row is unchanged (served = its banner).
    """
    def _served(usage: Dict[str, Any]) -> Tuple[Any, Any, Any]:
        served_model = usage.get("served_model")
        return (
            served_model if isinstance(served_model, str) and served_model else MODEL_UNKNOWN,
            usage.get("served_model_usage"),
            True if usage.get("served_model_mismatch") else None,
        )

    try:
        claude_status = (
            claude_verdict.get("verdict") if isinstance(claude_verdict, dict)
            else f"ERROR: {claude_err}"
        )
        claude_served, claude_served_usage, claude_mismatch = _served(claude_usage)
        _record_spawn_run(
            tool="audit_claude",
            status=claude_status,
            cost_usd=claude_usage.get("cost_usd"),
            duration_ms=claude_usage.get("duration_ms"),
            num_turns=claude_usage.get("num_turns"),
            wall_clock_s=claude_usage.get("wall_clock_s"),
            model=CLAUDE_MODEL,
            cycle_id=cycle_id,
            component_id=component_id,
            bundle_hash=bundle_hash,
            request_id=None,
            invocation_id=invocation_id,
            requested_model=CLAUDE_MODEL,
            served_model=claude_served,
            tokens=claude_usage.get("tokens"),
            role=REVIEWER_ROLE,
            env_override_refused=CLAUDE_ENV_OVERRIDE_REFUSED,
            served_model_usage=claude_served_usage,
            served_model_mismatch=claude_mismatch,
            project_root_override=project_root,
        )
    except BaseException:  # noqa: BLE001
        pass
    try:
        codex_status = (
            codex_verdict.get("verdict") if isinstance(codex_verdict, dict)
            else f"ERROR: {codex_err}"
        )
        substitution = codex_usage.get("substitution")
        substitution = substitution if isinstance(substitution, dict) else None
        served_by = substitution.get("served_model") if substitution is not None else None
        served_usage_field: Any = None
        mismatch_field: Any = None
        if served_by:
            # A Claude substitute served the slot: the row describes what really ran.
            envelope_usage = substitution.get("usage")
            envelope_usage = envelope_usage if isinstance(envelope_usage, dict) else {}
            cost_source: Dict[str, Any] = envelope_usage
            model_field: Optional[str] = served_by
            requested_field: Optional[str] = substitution.get("requested_model")
            # #282 R3: what the substitute's envelope says served it, not its alias.
            served_field, served_usage_field, mismatch_field = _served(envelope_usage)
            tokens_field: Any = envelope_usage.get("tokens")
        else:
            cost_source = codex_usage
            # The REQUESTED slug, matching the Claude arm's semantics for this
            # field. It used to be the literal "codex", which recorded the
            # provider and not the model — design D7's "provenance is wrong, not
            # merely coarse". The REPORTED slug from the stderr banner has no
            # column in spawn-runs.v1, so it travels in this spawner's stdout
            # `model_provenance` block instead; the two are never merged.
            model_field = CODEX_MODEL
            requested_field = CODEX_MODEL
            served_field = codex_usage.get("reported_model", MODEL_UNKNOWN)
            tokens_field = codex_usage.get("tokens")
        _record_spawn_run(
            tool="audit_codex",
            status=codex_status,
            cost_usd=cost_source.get("cost_usd"),
            duration_ms=cost_source.get("duration_ms"),
            num_turns=cost_source.get("num_turns"),
            wall_clock_s=codex_usage.get("wall_clock_s"),
            model=model_field,
            cycle_id=cycle_id,
            component_id=component_id,
            bundle_hash=bundle_hash,
            request_id=None,
            invocation_id=invocation_id,
            requested_model=requested_field,
            served_model=served_field,
            tokens=tokens_field,
            quota_before=codex_usage.get("quota_before"),
            quota_after=codex_usage.get("quota_after"),
            quota_source=codex_usage.get("quota_source"),
            role=REVIEWER_ROLE,
            env_override_refused=CODEX_ENV_OVERRIDE_REFUSED,
            substitute_for=seat_model.CODEX if served_by else None,
            substitution_reason=substitution.get("reason") if substitution is not None else None,
            use=QUOTA_USE if substitution is not None else None,
            served_model_usage=served_usage_field,
            served_model_mismatch=mismatch_field,
            project_root_override=project_root,
        )
    except BaseException:  # noqa: BLE001
        pass


def _build_model_provenance(
    timeout_s: int,
    codex_timeout_s: int,
    codex_usage: Dict[str, Any],
    claude_usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """The `model_provenance` block of this spawner's stdout result.

    REQUESTED vs REPORTED, recorded separately with their sources (design
    §4.6 / D7). "requested" is what this process put on the command line;
    "reported" is what the CLI itself printed. They are never merged, and an
    unobserved value stays MODEL_UNKNOWN rather than echoing the request.
    #282 R3 (plan K5): the Claude arm prints no pre-call banner, but its JSON
    envelope's `modelUsage` names what served the call, so `reported` is that id
    with `reported_source` "claude_model_usage" (from `claude_usage`, the arm's
    usage side-channel); without modelUsage both stay `unknown` — an absent
    capability, not a passing one. No new key: a served-model mismatch rides the
    spawn-runs row and stderr only.

    S081 stream 1: the Claude arm's `requested_source` is the ACTUAL source; it was
    the fixed string "env>policy>hardcoded", which described a chain rather than
    recording which link served. The optional `env_override_refused` /
    `bin_override` keys are present ONLY when that event happened, so an absent
    key means "no override", never "not checked".

    S081 WP-R06: each arm also carries its seat_model provenance (`source` —
    freeze | env | roster | harness_literal, equal to `requested_source` —
    `requested_selector`, `roster_fetched_at`, and the optional event keys; see
    _seat_provenance). `env_override_refused` is seat_model's record
    {var, value, reason}.

    S081 WP-F03 (plan J14) — substitution provenance lives ONLY here, in the codex block
    (the top-level result keys are unchanged). Event keys, present only when it happened:
      * a Claude substitute served the slot: `codex_arm_substituted_by` (its alias),
        `substitution_reason`, `substitute_timeout_s`, `provider_gap` ("openai"),
        `codex_attempts` (0 = decided before any codex call),
        `substitution_row_error` when the budget-store row could not be written, and
        `substitute_bin_override` (#282 R1: a copy of the AUDIT_CLAUDE_BIN record) when
        AUDIT_CLAUDE_BIN is set, because the substitute ran through that binary;
      * a substitution was due but could not be made: `substitution_reason`,
        `codex_attempts`, `substitution_error`;
      * no substitution but the one same-model retry ran: `codex_attempts` (2).
    #282 F3 (plan K40) — `reviewer_memory_quarantined` is an EVENT KEY in the block of the
    arm that LAUNCHED: `claude` for the Claude arm, `codex` when the slot's Claude
    substitute ran (its own launch, its own quarantine). Absent means nothing was moved,
    never "not checked", so it is never read as a zero.

    `bin_override` in the codex block is the AUDIT_CODEX_BIN record ONLY and is never
    overwritten by the substitute's binary. A codex slot that is a GAP because
    AUDIT_CODEX_BIN names no binary (#282 R1) carries `bin_override` and none of the
    substitution keys. `requested` / `reported` keep describing codex itself (what was
    asked for, what its banner printed — `unknown` when codex never ran).
    """
    served = (claude_usage or {}).get("served_model")
    served = served if isinstance(served, str) and served and served != MODEL_UNKNOWN else None
    claude: Dict[str, Any] = {
        "requested": CLAUDE_MODEL,
        "requested_source": CLAUDE_MODEL_SOURCE,
        "reported": served if served is not None else MODEL_UNKNOWN,
        "reported_source": SERVED_SOURCE_MODEL_USAGE if served is not None else MODEL_UNKNOWN,
        "timeout_s": timeout_s,
    }
    claude.update(_seat_provenance(CLAUDE_PIN))
    codex: Dict[str, Any] = {
        "requested": CODEX_MODEL,
        "requested_effort": CODEX_EFFORT,
        "requested_source": CODEX_MODEL_SOURCE,
        "reported": codex_usage.get("reported_model", MODEL_UNKNOWN),
        "reported_effort": codex_usage.get("reported_effort", MODEL_UNKNOWN),
        "reported_source": codex_usage.get("reported_source", MODEL_UNKNOWN),
        "timeout_s": codex_timeout_s,
    }
    codex.update(_seat_provenance(CODEX_PIN))
    for block, refused, override in (
        (claude, CLAUDE_ENV_OVERRIDE_REFUSED, CLAUDE_BIN_OVERRIDE),
        (codex, CODEX_ENV_OVERRIDE_REFUSED, CODEX_BIN_OVERRIDE),
    ):
        if refused:
            block["env_override_refused"] = dict(refused)
        if override:
            block["bin_override"] = dict(override)
    substitution = codex_usage.get("substitution")
    attempts = codex_usage.get("codex_attempts")
    if isinstance(substitution, dict):
        codex["substitution_reason"] = substitution.get("reason")
        codex["codex_attempts"] = substitution.get("codex_attempts")
        if substitution.get("served_model"):
            codex["codex_arm_substituted_by"] = substitution["served_model"]
            codex["substitute_timeout_s"] = substitution.get("timeout_s")
            codex["provider_gap"] = PROVIDER_GAP
            if "row_error" in substitution:
                codex["substitution_row_error"] = substitution["row_error"]
            if CLAUDE_BIN_OVERRIDE:
                codex["substitute_bin_override"] = dict(CLAUDE_BIN_OVERRIDE)
        if "error" in substitution:
            codex["substitution_error"] = substitution["error"]
    elif isinstance(attempts, int) and not isinstance(attempts, bool) and attempts > 1:
        codex["codex_attempts"] = attempts
    # #282 F3 (plan K40): `reviewer_memory_quarantined` goes in the block of the arm that
    # LAUNCHED — claude for the Claude arm, codex when the slot's Claude substitute ran its
    # own launch (and so its own quarantine). An EVENT KEY: absent means nothing moved.
    for block, usage in ((claude, claude_usage),
                         (codex, (substitution if isinstance(substitution, dict) else {}).get("usage"))):
        count = usage.get("reviewer_memory_quarantined") if isinstance(usage, dict) else None
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            block["reviewer_memory_quarantined"] = count
    return {"claude": claude, "codex": codex}


#: The codex_quota use this spawner's codex arm is admitted under (design §4.7).
QUOTA_USE = "audit"


def _admit_audit(project_root: Path) -> Optional[Dict[str, Any]]:
    """codex_quota.admit("audit", cycle_id_for(project_root)) — recorded, never refused.

    The decision is one row in ~/.claude/projects/<slug>/astra-budget.jsonl. Nothing
    here may change the audit: a caller-bug ValueError or anything else is reported
    on stderr and swallowed, and so is a row the budget store could not write.

    S081 WP-F03 (plan J7): the decision's `unavailable` token (rate_limit_reached /
    quota_exhausted), when set, is what lets main() hand the codex slot to a Claude
    substitute BEFORE spending a doomed call. The audit itself is still admitted.
    """
    try:
        # D21 fix round 1 (m3): bill the class, model and role CODEX_PIN actually resolved to
        # (code_reviewer sized onto the std tier is std, not astra). `audit` is exempt from
        # every budget cell, so naming the class never refuses the audit.
        decision = codex_quota.admit(
            QUOTA_USE, codex_quota.cycle_id_for(project_root), project_root=project_root,
            model_class=seat_model.pin_model_class(CODEX_PIN),
            requested_model=CODEX_PIN.model, role=REVIEWER_ROLE,
        )
    except Exception as exc:  # noqa: BLE001
        eprint(f"audit_spawn: WARNING: codex quota admission not recorded: {type(exc).__name__}")
        return None
    if not decision.get("row_written"):
        eprint(
            "audit_spawn: WARNING: codex quota admission not recorded "
            f"({decision.get('error', 'budget store unavailable')!a})"
        )
    return decision


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 3:
        env_error("usage: audit_spawn.py <component_id> <audit_bundle_path> [--project-root <dir>] [--timeout <s>]  (--timeout bounds the Claude arm; the codex arm takes its per-pin timeout)")
    component_id = argv[1]
    bundle_path = Path(argv[2]).resolve()

    project_root = Path(os.getcwd())
    # `--timeout` bounds the CLAUDE arm. The codex arm's budget is COUPLED to
    # its pin (design §3.1) and comes from the emitter, so it is not a shared
    # scalar any caller can shorten out from under the model it pinned.
    timeout_s = DEFAULT_TIMEOUT_S
    codex_timeout_s = CODEX_TIMEOUT_S
    i = 3
    while i < len(argv):
        a = argv[i]
        if a == "--project-root":
            if i + 1 >= len(argv):
                env_error("--project-root requires a value")
            project_root = Path(argv[i + 1]).resolve()
            i += 2
            continue
        if a == "--timeout":
            if i + 1 >= len(argv):
                env_error("--timeout requires a value")
            try:
                timeout_s = int(argv[i + 1])
            except ValueError:
                env_error(f"invalid --timeout value {argv[i + 1]!r}")
            i += 2
            continue
        env_error(f"unknown argument: {a}")

    bundle = load_audit_bundle(bundle_path)
    component_entry = load_component_entry(project_root, component_id)
    ledger_row = load_ledger_row(project_root, component_id)
    prompt = build_prompt(component_entry, bundle, ledger_row)

    # #124 observe-only telemetry: per-arm usage side-channels. The audit
    # pipeline does not read these; they feed ONLY the spawn-runs.jsonl sidecar.
    claude_usage: Dict[str, Any] = {}
    codex_usage: Dict[str, Any] = {}
    invocation_id = uuid.uuid4().hex
    cycle_id = os.environ.get("FORGE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    bundle_hash = bundle.get("bundle_hash")

    # S081 WP-F03 (amendment 1 D6, plan J10/J13): astra can be known unavailable before
    # any call — no eligible TOP in the roster, or no codex binary. Neither makes a TOP
    # call, so neither is admitted. #282 R1: an AUDIT_CODEX_BIN naming no binary is
    # PRECALL_GAP_BIN_OVERRIDE — decided here too, so it is never admitted either, and
    # _run_codex_arm turns it into the gap (AUDIT_UNAVAILABLE), never a substitution.
    precall_reason = _plan_time_unavailable()
    admission_id: Optional[str] = None
    if precall_reason is None:
        # S081 WP-R06 (design §4.7): record this TOP codex use against the cycle's astra
        # budget BEFORE the call. `audit` is never refused, so the decision cannot stop
        # the audit; it is recorded so the budget rows count every TOP call. When its
        # snapshot says codex will refuse (`unavailable`), the call is not spent: the
        # Claude substitute serves the slot instead.
        decision = _admit_audit(project_root)
        token = decision.get("unavailable") if isinstance(decision, dict) else None
        if isinstance(token, str) and token:
            precall_reason = token
        # #282 r10: keep the admission's id so a substitution of this slot names the
        # admission it replaces (netted out of the TOP-call counts). A missing decision or
        # a row the store never took leaves nothing to name: None, and the audit still runs.
        if isinstance(decision, dict) and decision.get("row_written") is True \
                and codex_quota.is_admission_id(decision.get("admission_id")):
            admission_id = decision["admission_id"]

    started_at = time.time()
    # #292: SIGTERM / SIGHUP are latched for the arms' lifetime (main thread only). The
    # codex arm's watch() raises the stop in its worker and reaps its child there; this
    # thread then exits 128+N instead of dying with the codex child still running.
    global _STOP_LATCH
    stop_latch = codex_watch._StopLatch(record_only=True)
    previous_handlers = codex_watch._install_stop_handlers(stop_latch)
    _STOP_LATCH = stop_latch
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            claude_future = pool.submit(run_claude_auditor, prompt, timeout_s, claude_usage,
                                        project_root=project_root)
            codex_future = pool.submit(
                _run_codex_arm, prompt, codex_timeout_s, codex_usage,
                project_root=project_root, precall_reason=precall_reason, admission_id=admission_id,
            )

            # The pool join must be computed from the LONGEST path an arm can take. It
            # used to be `timeout_s + 30` off ONE shared value; once the two arms carry
            # different budgets, that shape cuts the longer arm at the shorter arm's
            # ceiling and reports "future exceeded outer timeout" for a call that was
            # still legitimately running — reintroducing the truncation this split
            # exists to fix. Since WP-F03 the codex slot can also retry once and then run
            # a substitute; _join_timeout_s documents that path and its recorded limit
            # against ARBITER_FRESHNESS_WINDOW_S.
            join_timeout_s = _join_timeout_s(timeout_s, codex_timeout_s, SUBSTITUTE_TIMEOUT_S)

            try:
                claude_verdict, claude_err = claude_future.result(timeout=join_timeout_s)
            except FuturesTimeout:
                claude_verdict, claude_err = None, "claude future exceeded outer timeout"
            try:
                codex_verdict, codex_err = codex_future.result(timeout=join_timeout_s)
            except FuturesTimeout:
                codex_verdict, codex_err = None, "codex future exceeded outer timeout"
            except codex_watch._StopSignal:
                # the worker already reaped its codex child; the exit below reports the stop
                codex_verdict, codex_err = None, "codex arm stopped by signal"
    except BaseException:
        # #292 fix round 1: a recorded stop outranks whatever else unwound the pool (a
        # worker exception, say); with no stop, the exception propagates as before. The
        # handlers are restored FIRST (re-review N4), so no stop can latch after this decision.
        codex_watch._restore_stop_handlers(previous_handlers)
        previous_handlers = []
        if stop_latch.signum is None:
            raise
    finally:
        _STOP_LATCH = None
        codex_watch._restore_stop_handlers(previous_handlers)
    if stop_latch.signum is not None:
        # Re-review N2: no claim about a reap (the codex arm may have finished or never
        # spawned). N3: a dead stderr (EPIPE, a hangup's EIO) must not turn 128+N into 1.
        try:
            eprint(f"audit_spawn: stopped by signal {stop_latch.signum}; no result emitted")
        except OSError:
            pass
        sys.exit(128 + stop_latch.signum)

    elapsed = round(time.time() - started_at, 2)

    model_provenance = _build_model_provenance(timeout_s, codex_timeout_s, codex_usage, claude_usage)

    # Emit one observe-only spawn-run record per arm (best-effort, never-raise).
    # This is the ONLY new side effect; the stdout result dict below is
    # byte-for-byte the same shape it was before (#124: do not touch verdict
    # output / evidence bundle). cost/duration/num_turns are null for the Codex
    # arm (non-JSON path) and for any Claude arm whose envelope lacked them.
    _emit_audit_spawn_runs(
        claude_usage=claude_usage,
        codex_usage=codex_usage,
        claude_verdict=claude_verdict,
        claude_err=claude_err,
        codex_verdict=codex_verdict,
        codex_err=codex_err,
        invocation_id=invocation_id,
        cycle_id=cycle_id,
        component_id=component_id,
        bundle_hash=bundle_hash,
        project_root=project_root,
    )

    if claude_verdict is None or codex_verdict is None:
        emit_result(
            {
                "result": "AUDIT_UNAVAILABLE",
                "claude_verdict": claude_verdict,
                "codex_verdict": codex_verdict,
                "claude_error": claude_err,
                "codex_error": codex_err,
                "disagreements": [],
                "reason": "one or both auditors failed to return a valid JSON verdict",
                "component_id": component_id,
                "bundle_hash": bundle.get("bundle_hash"),
                "elapsed_s": elapsed,
                "model_provenance": model_provenance,
            },
            exit_code=4,
        )

    result = aggregate_verdicts(claude_verdict, codex_verdict)
    disagreements = merge_disagreements(claude_verdict, codex_verdict)

    emit_result(
        {
            "result": result,
            "component_id": component_id,
            "claude_verdict": claude_verdict,
            "codex_verdict": codex_verdict,
            "disagreements": disagreements,
            "bundle_hash": bundle.get("bundle_hash"),
            "elapsed_s": elapsed,
            "model_provenance": model_provenance,
        },
        exit_code=0,
    )


if __name__ == "__main__":
    main()
