#!/usr/bin/env python3
"""avengers — convene.py (WP-2). The resolver / fail-closed pre-spend gate.

Charter (design §3/§4/§8): resolve a composition profile + roster into a FROZEN
flat JSON session-plan, refusing to spend a single seat call unless the structure
is sound. It:
  - runs the fail-closed STRUCTURAL validate (design §4 LOW_QUORUM case (a)):
      * < 3 member seats                                  -> sub-quorum, no run
      * < 2 provider families AND no declared fallback    -> sub-quorum, no run
      * zero `adversarial_role: true` seats (design §6)   -> no run
  - resolves the EXTERNAL, SEATLESS, cold-context arbiter (design §4, WP-2): a
    fresh persona-free CALL that did NOT file a position, argue, or ballot. Its
    provider MUST differ from EVERY deliberation seat's provider (widened from
    adversarial-only). CLEAN path = a provider used by no deliberation seat (total
    exclusion). FALLBACK path = all providers deliberated (coding-ratification
    always lands here) -> the strongest-adjudication-prior NON-adversarial
    provider, cold-context, with the ACCEPTED style-recognition residual RECORDED
    as `fallback_arbiter_residual` in run-record.json. An ALL-ADVERSARIAL profile
    is arbiter-unsatisfiable -> fails CLOSED (ConveneError), never hangs.
  - REJECTS retired effort tiers (notably 'high') and un-pinned codex effort
  - performs a TWO-LAYER config merge ONLY: shipped defaults <- profile. It reads
    NO repo-local override file (a drive-by injection vector, design §3/§14).
  - injects the resolver-owned guard stacks (codex `--ephemeral -s read-only`
    per-call pins; agy `--sandbox`, flags-before `-p`)
  - stamps profile-sha256 provenance
  - materializes a flat JSON session-plan that validates against
    schemas/session-plan.v2.schema.json (a bundled stdlib mini-validator; no
    third-party jsonschema dependency). v1 is NOT mutated in place, so a resumed
    mid-flight v1 plan can't silently misvalidate.
  - writes the §6a run-record.json instrumentation sink (staffing populated;
    outcome fields null until the run grades them)
  - `--dry-run` prints a pre-spend review and stops (no session dir, no spend)

No LLM, no network, no semantic decisions. Dependencies: stdlib + PyYAML (for the
human-authored profile/roster YAML). Machine state (the session-plan) is JSON.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # PyYAML — explicitly owned dependency (design §2/§6)
except ImportError:  # pragma: no cover
    sys.stderr.write("convene.py requires PyYAML (import yaml).\n")
    raise

_HERE = Path(__file__).resolve().parent
_SKILL_ROOT = _HERE.parent
DEFAULT_PROFILES_DIR = _SKILL_ROOT / "profiles"
DEFAULT_ROSTER_DIR = _SKILL_ROOT / "roster"
# WP-2: point at the v2 schema (external seatless arbiter). v1 stays on disk,
# unmutated, so a resumed mid-flight v1 plan can't silently misvalidate.
SCHEMA_PATH = _SKILL_ROOT / "schemas" / "session-plan.v2.schema.json"
RUN_RECORD_SCHEMA_PATH = _SKILL_ROOT / "schemas" / "run-record.v1.schema.json"
CAPABILITY_PRIORS_PATH = _SKILL_ROOT / "capability-priors.yaml"
SESSION_PLAN_SCHEMA = "session-plan.v2"

# --------------------------------------------------------------------------- #
# Locked policy constants (design §2/§4/§6)
# --------------------------------------------------------------------------- #
KNOWN_PROVIDERS = frozenset({"codex", "claude", "agy"})
RETIRED_EFFORT_TIERS = frozenset({"high"})          # 'high' is RETIRED and rejected
CODEX_EFFORT_TIERS = frozenset({"minimal", "low", "medium", "xhigh", "max"})  # no 'high', no 'default'
NON_CODEX_EFFORTS = frozenset({"default"})          # claude/agy use smart-config 'default'
KNOWN_OUTCOMES = frozenset({"decision", "deliverable", "forge_brief", "auto"})

# --------------------------------------------------------------------------- #
# Seat-class effort layer (WP-1, design §2a). Effort pins are SEAT-CLASS
# semantics resolved per (provider, seat-class) through SEAT_CLASS_TABLE, NOT a
# raw tier welded onto a seat. A raw concrete tier is still accepted (it is its
# own literal seat-class); when it has no native equivalent on the resolved
# provider it resolves DOWN to that provider's advisory tier WITH a recorded
# note, instead of crashing the resolver — replacing the old seat⇒provider
# fail-closed (former validate_effort non-codex+non-'default' raise) that
# crashed any challenger provider-swap (design §1.3, success criterion #2).
# --------------------------------------------------------------------------- #
KNOWN_CONCRETE_TIERS = frozenset(
    {"minimal", "low", "medium", "xhigh", "max", "default"}
)
# Each provider's NATIVE-legal concrete tiers (what may pass through untouched).
PROVIDER_LEGAL_TIERS: Dict[str, frozenset] = {
    "codex": CODEX_EFFORT_TIERS,            # must be pinned; 'default' is NOT legal
    "claude": NON_CODEX_EFFORTS,            # smart-config advisory 'default' only
    "agy": NON_CODEX_EFFORTS,
}
# Advisory tier a foreign raw tier / seat-class resolves down to (codex: none —
# codex MUST be explicitly pinned, so it never resolves down).
PROVIDER_ADVISORY_TIER: Dict[str, Optional[str]] = {
    "codex": None, "claude": "default", "agy": "default",
}

# Semantic seat-class names (the design §2a abstraction).
CHALLENGER_FLOOR = "challenger_floor"
RATIFICATION_ARBITER = "ratification_arbiter"
_ANTI_SYCOPHANCY_NOTE = "no codex-equivalent anti-sycophancy floor for this provider"

# Semantic seat-class -> per-provider (concrete_effort, advisory_note). A present
# note is destined for the run record (§6a instrumentation; wired in WP-2).
SEAT_CLASS_TABLE: Dict[str, Dict[str, Tuple[str, Optional[str]]]] = {
    # The anti-sycophancy / ballot floor for adversarial critics.
    CHALLENGER_FLOOR: {
        "codex": ("xhigh", None),
        "claude": ("default", f"{_ANTI_SYCOPHANCY_NOTE} (claude); using smart-config advisory tier 'default'"),
        "agy": ("default", f"{_ANTI_SYCOPHANCY_NOTE} (agy); using default advisory tier"),
    },
    # Ratification-arbiter ceiling: re-keys the old effort_on_codex:max/1200 pin
    # onto (provider, seat-class). codex -> 'max' (timeout 1200). MOOT for
    # coding-ratification (its arbiter is claude/agy); the max-vs-2026-07-11-sol
    # re-derivation is DEFERRED to the backlog (design §4).
    RATIFICATION_ARBITER: {
        "codex": ("max", None),
        "claude": ("default", None),
        "agy": ("default", None),
    },
}
PROFILE_SCHEMA = "avengers-profile.v1"

# --------------------------------------------------------------------------- #
# D2 divergence-overlay lint (WP-3, design §3). A role card MAY carry an optional
# `divergence_overlay` (a persona-free CORE incentive + an overlay injected ONLY in
# blind-diverge/ideation, stripped for converge/verify/arbiter — the phase gate lives
# in seat_prompt.py). The LINT is schema-enforced HERE at card resolution: every
# overlay MUST declare `type` ∈ OVERLAY_TYPES; a decorative/demographic overlay (any
# other type, or a missing type) is REJECTED fail-closed — the empirically-observed
# ~30-70% reasoning-drop failure mode. A profile may set `no_overlays: true` for
# verification-heavy factual tasks (injection is then suppressed regardless).
# --------------------------------------------------------------------------- #
OVERLAY_TYPES = frozenset({"expertise-cue", "divergence-direction"})

# --------------------------------------------------------------------------- #
# Capability priors (design §2 / §2a). DESIGNER BELIEFS, not measured capability
# — inputs to the resolver, never reported as evidence. Loaded from the editable
# capability-priors.yaml DATA file; these BUILTIN copies are the fail-OPEN
# fallback if that file is missing/unparseable (a DATA edit must never crash the
# fail-closed gate). Higher adjudication_prior = a stronger belief that the
# provider is a strong NEUTRAL synthesizer for the external arbiter (design §4);
# claude carries the strongest prior (why the coding-ratification fallback arbiter
# lands on claude). Ties break alphabetically for determinism.
BUILTIN_ADJUDICATION_PRIOR: Dict[str, int] = {"claude": 3, "agy": 2, "codex": 1}
BUILTIN_SEAT_AFFINITY: Dict[str, Dict[str, int]] = {
    "claude": {"integration": 3, "calibration": 3, "coding_depth": 2},
    "codex": {"edge_catching": 3, "evidence_discipline": 3, "unsticking": 2},
    "agy": {"research_breadth": 2, "operations": 2},
}

MIN_MEMBER_SEATS = 3
MIN_PROVIDER_FAMILIES = 2

# Guard-stack timeouts (design §2/§9 cold-start seeds).
CODEX_TIMEOUTS = {"minimal": 120, "low": 120, "medium": 180, "xhigh": 300, "max": 300}
CODEX_RATIFICATION_ARBITER_TIMEOUT = 1200  # ratification arbiter calls pin max, timeout 1200
AGY_TIMEOUT = 600

# Estimator cold-start latency seeds, seconds (design §9).
SEED_LATENCY_S = {
    ("codex", "minimal"): 30, ("codex", "low"): 40, ("codex", "medium"): 60,
    ("codex", "xhigh"): 60, ("codex", "max"): 300,
    ("agy", "default"): 45, ("claude", "default"): 60,
}
_SEED_FALLBACK = 60

# TWO-LAYER merge: this is the ONLY config baseline under the profile. There is no
# third repo-local layer by design (§3/§14).
SHIPPED_DEFAULTS: Dict[str, Any] = {
    "depth": "default",
    "budgets": {"max_seat_calls": 10, "wall_clock_s": 900, "max_cycles": 1},
    "docket": {"max_issues": 6},
}

# --------------------------------------------------------------------------- #
# evidence_run REQUEST path (D5, design §6, WP-4). Any seat may REQUEST a read-only,
# sandboxed, time-boxed probe (an EXISTING test suite / benchmark); results enter the
# docket as fenced UNTRUSTED DATA (rendered by seat_prompt.render_evidence_runs). The
# actual runner is scripts/evidence_run.py — this module exposes the REQUEST path (the
# phase gate + the trusted probe registry declared in the plan). Avengers stays
# NON-MUTATING: the runner NEVER writes, NEVER spawns bob (enforced in evidence_run).
# Requests are legal ONLY in these phases — never in a blind-diverge turn (a seat must
# form its blind position before it can lean on shared evidence).
EVIDENCE_REQUEST_PHASES = ("DOCKET", "CROSS_EXAM")
EVIDENCE_DEFAULT_TIMEOUT_S = 300
EVIDENCE_OUTPUT_BYTE_BUDGET = 4000
_EVIDENCE_SEAT_REQUEST_CONTRACT = (
    "A seat may reference a probe_id ONLY (never a raw command); results enter the "
    "docket as fenced UNTRUSTED DATA; the runner is read-only, sandboxed, time-boxed "
    "and NEVER writes to the tree / commits / spawns bob (the non-mutating HARD-RULE)."
)


def _load_evidence_run_module():
    """Path-import the sibling evidence_run.py (this module is loaded by path in
    tests, so a package import is not available). Returns the module, or None if it
    cannot be loaded — plan-building fails OPEN to an unavailable evidence policy
    rather than crashing the fail-closed resolver over an optional primitive."""
    import importlib.util as _ilu
    try:
        path = _HERE / "evidence_run.py"
        spec = _ilu.spec_from_file_location("avengers_evidence_run", path)
        if spec is None or spec.loader is None:
            return None
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except (OSError, ImportError, SyntaxError):  # pragma: no cover - defensive
        return None


def _evidence_probe_registry(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the profile-declared trusted probe registry over the shipped default.
    A profile MAY declare `evidence: {probes: {<id>: {description, argv}}}` — TRUSTED
    config (only a probe_id from this registry is runnable by a seat)."""
    ev = _load_evidence_run_module()
    base: Dict[str, Any] = dict(getattr(ev, "DEFAULT_PROBE_REGISTRY", {}) or {}) if ev else {}
    prof_ev = (profile.get("evidence", {}) or {}).get("probes", {}) or {}
    if isinstance(prof_ev, dict):
        base.update(prof_ev)
    return base


def build_evidence_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    """The plan's `evidence_policy` block: DECLARES the evidence_run REQUEST path — the
    trusted probe registry, the phase gate, the sandbox/time-box defaults, and the
    seat-request contract. `available` is False only when the primitive can't be
    loaded (fail-open; the deliberation still runs, just without execution-grounding)."""
    ev = _load_evidence_run_module()
    hard_rule = getattr(ev, "HARD_RULE", _EVIDENCE_SEAT_REQUEST_CONTRACT) if ev else _EVIDENCE_SEAT_REQUEST_CONTRACT
    return {
        "available": ev is not None,
        "runner": "scripts/evidence_run.py",
        "hard_rule": hard_rule,
        "request_phases": list(EVIDENCE_REQUEST_PHASES),
        "sandbox_tier_preference": "auto",   # bwrap -> firejail -> snapshot (resolved at run time)
        "default_timeout_s": EVIDENCE_DEFAULT_TIMEOUT_S,
        "output_byte_budget": EVIDENCE_OUTPUT_BYTE_BUDGET,
        "seat_request_contract": _EVIDENCE_SEAT_REQUEST_CONTRACT,
        "probe_registry": _evidence_probe_registry(profile),
    }


def resolve_evidence_request(
    request: Dict[str, Any],
    plan: Dict[str, Any],
    project_root: Any,
    *,
    phase: Optional[str] = None,
) -> Dict[str, Any]:
    """The phase-machine-facing entry point for an evidence_run REQUEST (design §6).

    Reads the trusted probe registry + phase gate from the plan's `evidence_policy`,
    then delegates to evidence_run.run_requested_evidence (probe_id ONLY — a seat can
    never supply a raw command). Returns the evidence DATA record (a refusal is itself
    a record, so the chair can docket it). Raises ConveneError only when the primitive
    is unavailable or the plan carries no evidence policy (a plan-level misconfig)."""
    policy = (plan or {}).get("evidence_policy")
    if not policy or not policy.get("available"):
        raise ConveneError("evidence_run is not available for this plan (no evidence_policy)")
    ev = _load_evidence_run_module()
    if ev is None:  # pragma: no cover - defensive; available implies loadable
        raise ConveneError("evidence_run primitive could not be loaded")
    return ev.run_requested_evidence(
        request,
        registry=policy.get("probe_registry", {}),
        project_root=project_root,
        phase=phase,
        allowed_phases=policy.get("request_phases", EVIDENCE_REQUEST_PHASES),
        timeout_s=policy.get("default_timeout_s", EVIDENCE_DEFAULT_TIMEOUT_S),
        output_byte_budget=policy.get("output_byte_budget", EVIDENCE_OUTPUT_BYTE_BUDGET),
    )


class ConveneError(Exception):
    """A fail-closed structural validation error. No run, no spend."""


# --------------------------------------------------------------------------- #
# Atomic write (temp + rename)
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
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _load_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConveneError(f"{path} did not parse to a mapping")
    return data


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_profile(profiles_dir: Path, family_or_path: str) -> Tuple[Dict[str, Any], Path, str]:
    """Resolve a profile by family name (in profiles_dir) or by explicit path.
    Returns (profile_dict, profile_path, sha256)."""
    cand = Path(family_or_path)
    if cand.suffix in (".yaml", ".yml") and cand.exists():
        path = cand
    else:
        path = Path(profiles_dir) / f"{family_or_path}.yaml"
    if not path.exists():
        raise ConveneError(f"profile not found: {family_or_path} (looked at {path})")
    prof = _load_yaml(path)
    if prof.get("schema") != PROFILE_SCHEMA:
        raise ConveneError(
            f"profile {path} has schema {prof.get('schema')!r}; expected {PROFILE_SCHEMA!r}"
        )
    return prof, path, sha256_file(path)


def load_roster_card(roster_dir: Path, seat_id: str) -> Dict[str, Any]:
    path = Path(roster_dir) / f"{seat_id}.yaml"
    if not path.exists():
        raise ConveneError(f"roster card not found: {seat_id} (looked at {path})")
    card = _load_yaml(path)
    if card.get("seat_id") != seat_id:
        raise ConveneError(f"roster card {path} seat_id mismatch: {card.get('seat_id')!r} != {seat_id!r}")
    return card


def load_capability_priors(path: Path = CAPABILITY_PRIORS_PATH) -> Dict[str, Any]:
    """Load the capability-priors DATA (design §2/§2a). FAIL-OPEN: a missing or
    unparseable file (or a missing key) falls back to the BUILTIN_* defaults, so
    a DATA edit can never crash the fail-closed pre-spend gate. Returns a dict
    with `adjudication_prior`, `seat_affinity`, and `sha256` (empty string when
    the file is absent)."""
    adjudication = dict(BUILTIN_ADJUDICATION_PRIOR)
    affinity = {k: dict(v) for k, v in BUILTIN_SEAT_AFFINITY.items()}
    sha = ""
    try:
        p = Path(path)
        if p.is_file():
            sha = sha256_file(p)
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ap = data.get("adjudication_prior")
                if isinstance(ap, dict) and ap:
                    adjudication = {str(k): int(v) for k, v in ap.items()
                                    if k in KNOWN_PROVIDERS and isinstance(v, (int, float))}
                    # Backfill any provider the DATA omitted from the builtin.
                    for prov, w in BUILTIN_ADJUDICATION_PRIOR.items():
                        adjudication.setdefault(prov, w)
                sa = data.get("seat_affinity")
                if isinstance(sa, dict) and sa:
                    affinity = {k: v for k, v in sa.items() if isinstance(v, dict)}
    except (OSError, ValueError, yaml.YAMLError):
        # fail-OPEN — priors are DATA, never a hard dependency of the gate.
        adjudication = dict(BUILTIN_ADJUDICATION_PRIOR)
        affinity = {k: dict(v) for k, v in BUILTIN_SEAT_AFFINITY.items()}
        sha = ""
    return {"adjudication_prior": adjudication, "seat_affinity": affinity, "sha256": sha}


def _best_adjudication_provider(candidates: List[str], priors: Dict[str, Any]) -> str:
    """Pick the provider with the strongest adjudication prior among `candidates`
    (design §4). Deterministic: higher prior wins, alphabetical tie-break."""
    adjudication = priors.get("adjudication_prior", BUILTIN_ADJUDICATION_PRIOR)
    return sorted(candidates, key=lambda p: (-int(adjudication.get(p, 0)), p))[0]


# --------------------------------------------------------------------------- #
# Merge (two layers only)
# --------------------------------------------------------------------------- #
def _merge_two_layer(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-then-nested merge of exactly two layers: base (shipped) <- over
    (profile). Nested dicts merge one level; scalars/lists in `over` win."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# Effort validation
# --------------------------------------------------------------------------- #
def resolve_effort(seat_id: str, provider: str, effort_pin: str) -> Tuple[str, str, Optional[str]]:
    """Resolve an effort pin (a SEAT-CLASS semantic name OR a raw concrete tier)
    to a concrete tier for `provider`, per the (provider, seat-class) table
    (design §2a). This REPLACES the old seat⇒provider validate_effort that
    fail-closed on any non-codex + non-'default' effort.

    Returns (concrete_effort, seat_class, note):
      * concrete_effort — a KNOWN_CONCRETE_TIERS value legal for `provider`
        (goes into the plan + guard stack; stays inside the v1 schema enum).
      * seat_class — the semantic seat-class name if one was used, else the raw
        tier itself. guard_stack_for + the ratification-arbiter max/1200 special
        case re-key on THIS (design §2a/§4), not on the literal effort tier.
      * note — an advisory string destined for the run record (§6a), or None.

    Fail-closed (ConveneError): retired tier 'high' (ANY provider); un-pinned /
    illegal codex; an unknown token that is neither a seat-class nor a known
    tier; a seat-class with no row for `provider`.
    """
    if provider not in KNOWN_PROVIDERS:
        raise ConveneError(
            f"seat '{seat_id}': unknown provider {provider!r} (known: {sorted(KNOWN_PROVIDERS)})"
        )
    # 'high' is RETIRED regardless of provider or how it was pinned.
    if effort_pin in RETIRED_EFFORT_TIERS:
        raise ConveneError(
            f"seat '{seat_id}': effort tier '{effort_pin}' is RETIRED and rejected "
            f"(use xhigh or max)"
        )
    # 1) Semantic seat-class -> per-(provider, seat-class) resolution.
    if effort_pin in SEAT_CLASS_TABLE:
        row = SEAT_CLASS_TABLE[effort_pin]
        if provider not in row:
            raise ConveneError(
                f"seat '{seat_id}': seat-class '{effort_pin}' has no resolution "
                f"for provider {provider!r}"
            )
        concrete, note = row[provider]
        return concrete, effort_pin, note
    # 2) Literal concrete tier (its own seat-class).
    if effort_pin not in KNOWN_CONCRETE_TIERS:
        raise ConveneError(
            f"seat '{seat_id}': unknown effort/seat-class {effort_pin!r} "
            f"(seat-classes: {sorted(SEAT_CLASS_TABLE)}; tiers: {sorted(KNOWN_CONCRETE_TIERS)})"
        )
    if effort_pin in PROVIDER_LEGAL_TIERS[provider]:
        return effort_pin, effort_pin, None                 # native — pass through
    if provider == "codex":
        # codex 'default' (or any non-native tier) = un-pinned / illegal codex.
        raise ConveneError(
            f"seat '{seat_id}': codex effort must be one of "
            f"{sorted(CODEX_EFFORT_TIERS)} (got {effort_pin!r}); "
            f"un-pinned codex calls are forbidden (success criterion #4)"
        )
    # claude/agy: a foreign raw tier (e.g. a codex-band 'xhigh') has no native
    # equivalent -> resolve DOWN to the advisory tier + a recorded note (no crash;
    # this is the challenger-provider-swap fix, design §2a / success criterion #2).
    advisory = PROVIDER_ADVISORY_TIER[provider]
    note = (
        f"raw effort tier {effort_pin!r} has no {provider}-native equivalent; "
        f"resolved to smart-config advisory {advisory!r}"
    )
    return advisory, effort_pin, note


def validate_effort(seat_id: str, provider: str, effort: str) -> str:
    """Back-compat shim (design §2a): now RESOLVES a seat-class / tier pin per
    (provider, seat-class). Returns the concrete resolved effort; raises
    ConveneError fail-closed on bad input (retired 'high', un-pinned codex,
    unknown token). Prefer resolve_effort() for the full (effort, seat_class,
    note) tuple."""
    concrete, _seat_class, _note = resolve_effort(seat_id, provider, effort)
    return concrete


# --------------------------------------------------------------------------- #
# Guard stacks (resolver-owned invariants, design §2/§4)
# --------------------------------------------------------------------------- #
_PROMPT_SLOT = "…"  # placeholder for the assembled seat prompt (see seat_prompt.py)


def codex_guard_stack(effort: str, *, timeout: int) -> str:
    return (
        f'timeout {timeout} codex exec --ephemeral -s read-only '
        f'-c model_reasoning_effort={effort} "{_PROMPT_SLOT}" < /dev/null'
    )


def agy_guard_stack(*, timeout: int = AGY_TIMEOUT) -> str:
    return f'timeout {timeout} agy --sandbox -p "{_PROMPT_SLOT}" < /dev/null'


def claude_guard_stack(effort: str) -> str:
    # Claude seats are host-native spawns, not a shell CLI — smart-config advisory tier.
    return f"(claude host seat · smart-config advisory tier={effort} · non-CLI spawn)"


def guard_stack_for(provider: str, effort: str, *, seat_class: Optional[str] = None,
                    is_arbiter: bool = False, is_ratification: bool = False) -> str:
    if provider == "codex":
        # Ratification-arbiter max/1200 special case re-keyed on (provider,
        # seat-class) — the RATIFICATION_ARBITER class resolves to 'max' on codex
        # — instead of matching the literal effort tier 'max' (design §2a/§4).
        if is_arbiter and is_ratification and seat_class == RATIFICATION_ARBITER:
            return codex_guard_stack(effort, timeout=CODEX_RATIFICATION_ARBITER_TIMEOUT)
        return codex_guard_stack(effort, timeout=CODEX_TIMEOUTS.get(effort, 300))
    if provider == "agy":
        return agy_guard_stack()
    if provider == "claude":
        return claude_guard_stack(effort)
    raise ConveneError(f"no guard stack for unknown provider {provider!r}")


# --------------------------------------------------------------------------- #
# Seat / arbiter resolution
# --------------------------------------------------------------------------- #
def lint_overlay(seat_id: str, card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fail-closed D2 overlay lint (design §3, WP-3). An optional
    `divergence_overlay` on a role card MUST be a mapping declaring a `type` ∈
    {expertise-cue, divergence-direction}. A decorative/demographic overlay — any
    other `type`, or a missing/blank one — is REJECTED (ConveneError, no run): that
    is precisely the ~30-70% reasoning-drop failure mode the split guards against.

    Returns the validated overlay dict (untouched) or None when the card carries no
    overlay. Runs at card resolution so a bad overlay fails the pre-spend gate; the
    INJECT/STRIP phase gate itself lives in seat_prompt.py."""
    ov = card.get("divergence_overlay")
    if ov is None:
        return None
    if not isinstance(ov, dict):
        raise ConveneError(
            f"seat '{seat_id}': divergence_overlay must be a mapping, got "
            f"{type(ov).__name__} (design §3)"
        )
    t = ov.get("type")
    if t not in OVERLAY_TYPES:
        raise ConveneError(
            f"seat '{seat_id}': divergence_overlay type {t!r} not in "
            f"{sorted(OVERLAY_TYPES)} — decorative/demographic overlays are REJECTED "
            "at validate (design §3, success criterion #6)"
        )
    return ov


def resolve_seats(
    profile: Dict[str, Any], roster_dir: Path, roster_override: Optional[List[Any]] = None
) -> List[Dict[str, Any]]:
    seat_entries = roster_override if roster_override else profile.get("seats", [])
    if not seat_entries:
        raise ConveneError("profile resolves zero seats")
    resolved: List[Dict[str, Any]] = []
    for entry in seat_entries:
        if isinstance(entry, str):
            entry = {"ref": entry}
        ref = entry.get("ref")
        if not ref:
            raise ConveneError(f"seat entry missing 'ref': {entry!r}")
        card = load_roster_card(roster_dir, ref)
        # D2 overlay lint (design §3): fail-closed at card resolution on a
        # decorative/demographic overlay. `overlay_type` is recorded for
        # instrumentation; the INJECT/STRIP phase gate lives in seat_prompt.py.
        overlay = lint_overlay(ref, card)
        card_prov = card.get("provider", {}) or {}
        provider = entry.get("provider") or card_prov.get("affinity")
        if provider not in KNOWN_PROVIDERS:
            raise ConveneError(f"seat '{ref}': unknown provider {provider!r} (known: {sorted(KNOWN_PROVIDERS)})")
        effort_pin = entry.get("effort") or card_prov.get("effort") or "default"
        # Seat-class effort resolution (design §2a): resolve per (provider,
        # seat-class) instead of the old seat⇒provider fail-closed that crashed a
        # challenger provider-swap. `seat_class` is the semantic name (or the raw
        # tier); `effort_note` is advisory instrumentation for the run record (§6a).
        effort, seat_class, effort_note = resolve_effort(ref, provider, effort_pin)
        adversarial = bool(entry.get("adversarial_role", card.get("adversarial_role", False)))
        resolved.append(
            {
                "seat_id": ref,
                "provider": provider,
                "effort": effort,
                "seat_class": seat_class,
                "effort_note": effort_note,
                "adversarial_role": adversarial,
                "can_arbitrate": bool(card.get("can_arbitrate", False)),
                "fallback_ok": bool(card_prov.get("fallback_ok", False)),
                "overlay_type": overlay.get("type") if overlay else None,
            }
        )
    return resolved


def _resolve_arbiter_effort(
    provider: str, is_ratification: bool, arb_cfg: Dict[str, Any]
) -> Tuple[str, str]:
    """Effort for the SEATLESS external arbiter (design §4). There is no seat to
    inherit effort from, so it is derived from the (provider, seat-class) table.
    Ratification arbiter -> the RATIFICATION_ARBITER seat-class ceiling (codex ->
    'max'/1200, honoring an explicit `effort_on_codex`; claude/agy -> advisory
    'default'). Non-ratification -> advisory 'default' (codex still must pin a
    native tier -> 'xhigh'). Returns (concrete_effort, seat_class)."""
    if is_ratification:
        if provider == "codex":
            pinned = arb_cfg.get("effort_on_codex", "max")
            token = RATIFICATION_ARBITER if pinned == "max" else pinned
        else:
            token = RATIFICATION_ARBITER
        effort, seat_class, _ = resolve_effort("<arbiter>", provider, token)
        return effort, seat_class
    token = "xhigh" if provider == "codex" else "default"
    effort, seat_class, _ = resolve_effort("<arbiter>", provider, token)
    return effort, seat_class


def resolve_arbiter(
    profile: Dict[str, Any], seats: List[Dict[str, Any]], *,
    is_ratification: bool, priors: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve the EXTERNAL, SEATLESS, cold-context arbiter (design §4, WP-2).

    The arbiter is a FRESH persona-free CALL — it did NOT file a position, argue,
    or ballot; it is NOT a promoted seat. Its provider is selected (never inherited
    from a seat) by precedence:
      * CLEAN path  — a provider used by NO deliberation seat: genuinely external,
        authorship-linkage total-excluded, no residual.
      * FALLBACK path — all providers deliberated (coding-ratification ALWAYS lands
        here, pinning all 3 families): the strongest-adjudication-prior
        NON-adversarial provider, cold-context. Authorship is anonymized but
        style-recognition self-preference is an ACCEPTED, DOCUMENTED residual
        (arXiv 2410.21819), RECORDED as `fallback_arbiter_residual` (§6a).
      * ALL-ADVERSARIAL — every provider deliberated AND every one is adversarial:
        no non-adversarial arbiter exists -> fail CLOSED (the only unsatisfiable
        arbiter case; never hangs).

    `can_arbitrate` is INERT under v2 — no seat is ever the adjudicator (design §5).
    The arbiter object DROPS `seat`; ADDS {is_external, cold_context, path}; KEEPS
    {provider, effort, guard_stack}.
    """
    priors = priors or load_capability_priors()
    deliberation_providers = {s["provider"] for s in seats}           # ALL seats deliberate
    adversarial_providers = {s["provider"] for s in seats if s["adversarial_role"]}

    clean_candidates = sorted(KNOWN_PROVIDERS - deliberation_providers)
    if clean_candidates:
        path = "clean"
        provider = _best_adjudication_provider(clean_candidates, priors)
    else:
        fallback_candidates = sorted(deliberation_providers - adversarial_providers)
        if not fallback_candidates:
            raise ConveneError(
                "arbiter constraint unsatisfiable: every provider deliberated AND every "
                f"deliberation provider is adversarial {sorted(adversarial_providers)} — an "
                "all-adversarial profile has no non-adversarial external arbiter (design §4 — "
                "fail CLOSED, no run, no spend)"
            )
        path = "fallback"
        provider = _best_adjudication_provider(fallback_candidates, priors)

    arb_cfg = profile.get("arbiter", {}) or {}
    effort, seat_class = _resolve_arbiter_effort(provider, is_ratification, arb_cfg)
    guard = guard_stack_for(
        provider, effort, seat_class=seat_class,
        is_arbiter=True, is_ratification=is_ratification,
    )
    if path == "clean":
        excluded = (
            f"clean path — arbiter provider {provider!r} is used by NO deliberation seat; "
            "authorship linkage total-excluded (no residual)"
        )
        constraint = (
            f"external seatless arbiter; provider {provider} != every deliberation provider "
            f"{sorted(deliberation_providers)} (clean path — total exclusion)"
        )
    else:
        excluded = (
            f"fallback path — {provider!r} deliberated (non-adversarially); its authorship is "
            "ANONYMIZED but style-recognition self-preference is an ACCEPTED residual "
            "(flagged fallback_arbiter_residual in run-record.json §6a)"
        )
        constraint = (
            f"external seatless arbiter; {provider} is the strongest-adjudication-prior "
            f"NON-adversarial provider (adversarial={sorted(adversarial_providers)}); "
            "all providers deliberated -> fallback path (accepted residual)"
        )
    return {
        "is_external": True,
        "cold_context": True,
        "path": path,
        "provider": provider,
        "effort": effort,
        "seat_class": seat_class,
        "guard_stack": guard,
        "fallback_arbiter_residual": path == "fallback",
        "excluded_authorship": excluded,
        "constraint": constraint,
    }


# --------------------------------------------------------------------------- #
# Structural validation (fail-closed; design §4 LOW_QUORUM case (a))
# --------------------------------------------------------------------------- #
def validate_structural(seats: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(seats)
    if n < MIN_MEMBER_SEATS:
        raise ConveneError(
            f"structural sub-quorum: {n} member seats < {MIN_MEMBER_SEATS} "
            "(LOW_QUORUM case (a) — no run, no spend)"
        )
    families = sorted({s["provider"] for s in seats})
    any_fallback = any(s["fallback_ok"] for s in seats)
    if len(families) < MIN_PROVIDER_FAMILIES and not any_fallback:
        raise ConveneError(
            f"structural sub-quorum: {len(families)} provider family "
            f"{families} < {MIN_PROVIDER_FAMILIES} with no declared fallback "
            "(LOW_QUORUM case (a) — no run, no spend)"
        )
    adversarial = [s["seat_id"] for s in seats if s["adversarial_role"]]
    if not adversarial:
        raise ConveneError(
            "no adversarial_role seat resolved; every profile MUST resolve >=1 "
            "adversarial seat (design §6) — no run, no spend"
        )
    return {
        "member_seats": n,
        "provider_families": families,
        "families_count": len(families),
        "floor": MIN_MEMBER_SEATS,
        "floor_met": True,
        "adversarial_seats": adversarial,
        "fallback_relaxed": len(families) < MIN_PROVIDER_FAMILIES and any_fallback,
    }


# --------------------------------------------------------------------------- #
# Mini JSON-schema validator (stdlib only; subset: type/required/properties/
# items/enum/const/additionalProperties/minItems/minimum)
# --------------------------------------------------------------------------- #
def _type_ok(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    return True


def schema_validate(instance: Any, schema: Dict[str, Any], path: str = "$",
                    errors: Optional[List[str]] = None) -> List[str]:
    if errors is None:
        errors = []
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(instance, tt) for tt in types):
            errors.append(f"{path}: expected type {t}, got {type(instance).__name__}")
            return errors
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property '{req}'")
        ap = schema.get("additionalProperties", True)
        for k, v in instance.items():
            if k in props:
                schema_validate(v, props[k], f"{path}.{k}", errors)
            elif ap is False:
                errors.append(f"{path}: additional property '{k}' not allowed")
            elif isinstance(ap, dict):
                schema_validate(v, ap, f"{path}.{k}", errors)
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: array has {len(instance)} items < minItems {schema['minItems']}")
        items = schema.get("items")
        if isinstance(items, dict):
            for i, it in enumerate(instance):
                schema_validate(it, items, f"{path}[{i}]", errors)
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
    return errors


def load_schema() -> Dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Session-plan materialization
# --------------------------------------------------------------------------- #
def _slugify(text: str, maxlen: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "session").lower()).strip("-")
    return (slug or "session")[:maxlen]


def make_session_id(task: str, *, now: Optional[_dt.datetime] = None) -> str:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return f"{now.strftime('%Y%m%d-%H%M')}-{_slugify(task)}"


def _converge_semantics(profile: Dict[str, Any]) -> str:
    return ((profile.get("phases", {}) or {}).get("converge", {}) or {}).get("semantics", "ratification")


def _resolve_outcome(profile: Dict[str, Any], contract: Dict[str, Any]) -> str:
    outcome_cfg = profile.get("outcome", {}) or {}
    allowed = outcome_cfg.get("type", []) or []
    if isinstance(allowed, str):
        allowed = [allowed]
    default = outcome_cfg.get("default") or (allowed[0] if allowed else "decision")
    requested = contract.get("outcome")
    if not requested or requested == "auto":
        return default
    if requested not in KNOWN_OUTCOMES:
        raise ConveneError(f"unknown outcome {requested!r} (known: {sorted(KNOWN_OUTCOMES)})")
    if allowed and requested not in allowed:
        raise ConveneError(
            f"outcome {requested!r} not offered by profile (offers {allowed})"
        )
    return requested


def _phases_planned(profile: Dict[str, Any], budgets: Dict[str, Any],
                    semantics: str, outcome_type: str) -> List[str]:
    converge_label = "Gate-1 ballots" if semantics == "ratification" else "dissent-schema"
    return [
        "CONVENE",
        "BLIND_DIVERGE",
        "DOCKET",
        f"CROSS_EXAM({budgets['max_cycles']} cycle)",
        f"CONVERGE({converge_label})",
        "ARBITER",
        f"ROUTE({outcome_type})",
        "WRITEBACK_PROPOSE(deferred - WP-3)",
        "CLOSED",
    ]


def build_session_plan(
    contract: Dict[str, Any],
    *,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
    roster_dir: Path = DEFAULT_ROSTER_DIR,
    session_id: Optional[str] = None,
    now: Optional[_dt.datetime] = None,
) -> Dict[str, Any]:
    """Resolve + validate + materialize the flat JSON session-plan. Raises
    ConveneError (fail-closed) on any structural problem — no spend."""
    family = contract.get("profile") or contract.get("task_family")
    if not family:
        raise ConveneError("contract must specify 'profile' or 'task_family'")
    task = contract.get("task") or contract.get("decision") or ""

    profile, profile_path, prof_sha = load_profile(profiles_dir, family)
    semantics = _converge_semantics(profile)
    is_ratification = semantics == "ratification"

    # Two-layer config merge: shipped defaults <- profile. (No repo-local layer.)
    merged = _merge_two_layer(SHIPPED_DEFAULTS, {
        "depth": profile.get("depth", SHIPPED_DEFAULTS["depth"]),
        "budgets": profile.get("budgets", {}),
        "docket": (profile.get("phases", {}) or {}).get("docket", {}),
    })
    budgets = dict(merged["budgets"])
    # Caller REQUEST (design §8 contract 'budget') — the explicit request, not a
    # config layer. Applied on top with recorded provenance.
    caller_budget = contract.get("budget") or {}
    budget_from_caller = False
    for k in ("max_seat_calls", "wall_clock_s", "max_cycles"):
        if k in caller_budget and caller_budget[k] is not None:
            budgets[k] = int(caller_budget[k])
            budget_from_caller = True

    seats = resolve_seats(profile, roster_dir, roster_override=contract.get("roster_override"))
    quorum = validate_structural(seats)
    priors = load_capability_priors()
    arbiter = resolve_arbiter(profile, seats, is_ratification=is_ratification, priors=priors)

    # Inject guard stacks into member seats (keyed on the resolved seat-class).
    for s in seats:
        s["guard_stack"] = guard_stack_for(
            s["provider"], s["effort"], seat_class=s["seat_class"],
            is_arbiter=False, is_ratification=is_ratification,
        )

    outcome_type = _resolve_outcome(profile, contract)
    sid = session_id or make_session_id(task or family, now=now)
    created = (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

    plan: Dict[str, Any] = {
        "schema": SESSION_PLAN_SCHEMA,
        "session_id": sid,
        "created_at": created,
        "profile": family if not str(family).endswith((".yaml", ".yml")) else profile.get("family", family),
        "profile_path": str(profile_path),
        "profile_sha256": prof_sha,
        "capability_priors_sha256": priors.get("sha256", ""),
        "family": profile.get("family", family),
        "task_family": semantics,
        "task": task,
        "outcome_type": outcome_type,
        "depth": merged["depth"],
        "caller": contract.get("caller", "user"),
        "interactive": bool(contract.get("interactive", True)),
        "memory": contract.get("memory", "project"),
        "budgets": {
            "max_seat_calls": budgets["max_seat_calls"],
            "wall_clock_s": budgets["wall_clock_s"],
            "max_cycles": budgets["max_cycles"],
        },
        "chair": {
            "role": "kernel-driven (WP-2)",
            "provider": "claude",
            "non_voting": True,
            "receives_member_memory": False,
        },
        "seats": seats,
        "arbiter": arbiter,
        "overlay_policy": {
            # D2 (design §3): overlays inject ONLY in blind-diverge/ideation and are
            # stripped for converge/verify/arbiter (phase gate in seat_prompt.py).
            # `no_overlays: true` on a profile suppresses injection everywhere
            # (verification-heavy factual tasks). Lint is always-on (fail-closed).
            "enabled": not bool(profile.get("no_overlays", False)),
            "types_allowed": sorted(OVERLAY_TYPES),
        },
        "evidence_policy": build_evidence_policy(profile),
        "quorum": quorum,
        "phases_planned": _phases_planned(profile, budgets, semantics, outcome_type),
        "merge_provenance": {
            "layers": ["shipped_defaults", "profile"],
            "repo_local_overrides": "none (no third layer read; design §3/§14)",
            "budget_from_caller_request": budget_from_caller,
        },
        "guard_policy": {
            "codex": "timeout <T> codex exec --ephemeral -s read-only -c model_reasoning_effort=<tier> \"…\" < /dev/null",
            "agy": "timeout 600 agy --sandbox -p \"…\" < /dev/null",
            "retired_tiers_rejected": sorted(RETIRED_EFFORT_TIERS),
        },
        "served_by_policy": "provider-REPORTED, not verified",
    }

    errs = schema_validate(plan, load_schema())
    if errs:
        raise ConveneError("materialized session-plan failed schema validation:\n  " + "\n  ".join(errs))
    return plan


# --------------------------------------------------------------------------- #
# Estimator + pre-spend review (design §9)
# --------------------------------------------------------------------------- #
def estimate(plan: Dict[str, Any]) -> Dict[str, Any]:
    seats = plan["seats"]
    n = len(seats)
    cycles = plan["budgets"]["max_cycles"]
    # Rough call plan: diverge (n) + cross-exam (~n per cycle) + converge ballots (n) + arbiter (1)
    rough_calls = n + n * cycles + n + 1
    planned_calls = min(rough_calls, plan["budgets"]["max_seat_calls"])
    per_seat = {s["seat_id"]: SEED_LATENCY_S.get((s["provider"], s["effort"]), _SEED_FALLBACK) for s in seats}
    arb = SEED_LATENCY_S.get((plan["arbiter"]["provider"], plan["arbiter"]["effort"]), _SEED_FALLBACK)
    low_s = sum(per_seat.values()) + arb          # one round of diverge + arbiter
    high_s = sum(per_seat.values()) * (2 + cycles) + arb
    return {
        "seats": n,
        "planned_calls": planned_calls,
        "call_ceiling": plan["budgets"]["max_seat_calls"],
        "est_low_min": round(low_s / 60, 1),
        "est_high_min": round(high_s / 60, 1),
    }


def render_pre_spend_review(plan: Dict[str, Any]) -> str:
    est = estimate(plan)
    lines: List[str] = []
    lines.append("avengers convene — PRE-SPEND REVIEW (--dry-run; NO session created, NO spend)")
    lines.append(f"profile : {plan['profile']}  (sha256:{plan['profile_sha256'][:12]}…)")
    lines.append(f"family  : {plan['family']}  ·  task_family: {plan['task_family']}")
    lines.append(f"task    : {plan['task'][:100] or '(none)'}")
    lines.append(f"outcome : {plan['outcome_type']}  ·  depth: {plan['depth']}  ·  caller: {plan['caller']}")
    b = plan["budgets"]
    lines.append(f"budgets : max_seat_calls={b['max_seat_calls']} · wall_clock_s={b['wall_clock_s']} · max_cycles={b['max_cycles']}")
    q = plan["quorum"]
    lines.append(
        f"quorum  : {q['member_seats']} member seats · {q['families_count']} provider families "
        f"{{{','.join(q['provider_families'])}}} · floor {'met' if q['floor_met'] else 'NOT met'}"
        + ("  (relaxed via declared fallback)" if q.get("fallback_relaxed") else "")
    )
    lines.append("seats   :")
    for s in plan["seats"]:
        # WP-2: no member seat is the arbiter anymore (the arbiter is a fresh
        # EXTERNAL seatless call), so seats carry no 'arbiter*' tag.
        tag = "  [adversarial]" if s["adversarial_role"] else ""
        lines.append(f"  - {s['seat_id']:<11} {s['provider']:<6} {s['effort']:<8}{tag}")
        note = s.get("effort_note")
        if note:
            lines.append(f"      note : {note}")
        lines.append(f"      guard: {s['guard_stack']}")
    a = plan["arbiter"]
    residual = "  · residual FLAGGED (fallback)" if a.get("fallback_arbiter_residual") else ""
    lines.append(
        f"arbiter : EXTERNAL cold-context call — {a['provider']} ({a['effort']})  ·  "
        f"path: {a['path']}{residual}"
    )
    lines.append(f"          {a['constraint']}")
    lines.append(f"          guard: {a['guard_stack']}")
    lines.append(
        f"estimate: ~{est['seats']} seats · ~{est['planned_calls']} calls (ceiling {est['call_ceiling']}) "
        f"· est {est['est_low_min']}–{est['est_high_min']} min  (§9 cold-start seeds)"
    )
    lines.append(f"phases  : {' -> '.join(plan['phases_planned'])}")
    lines.append(f"retired effort tiers rejected: {', '.join(plan['guard_policy']['retired_tiers_rejected'])}")
    lines.append("merge   : shipped_defaults <- profile (NO repo-local override layer)")
    lines.append("NO run performed. Re-run WITHOUT --dry-run to convene.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Run-record instrumentation sink (§6a — the anti-superstition insurance)
# --------------------------------------------------------------------------- #
def load_run_record_schema() -> Dict[str, Any]:
    return json.loads(RUN_RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))


def build_run_record(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Build the §6a run-record from a materialized session-plan. Records the
    RESOLVED staffing (provider + effort per seat WITH the seat-class name), the
    external-arbiter path + `fallback_arbiter_residual` flag, and the collected
    §2a advisory notes (e.g. the 'no anti-sycophancy floor for this provider'
    note — success criterion #2). The POST-RUN outcome fields (dissent margin +
    the crude arbiter-scored 1-5 grade) are written null with `graded: false`;
    the kernel/arbiter fills them after deliberation. Validates against
    run-record.v1.schema.json (fail-closed on a malformed record)."""
    arb = plan["arbiter"]
    seats = []
    advisory_notes: List[str] = []
    for s in plan["seats"]:
        note = s.get("effort_note")
        seats.append({
            "seat_id": s["seat_id"],
            "provider": s["provider"],
            "effort": s["effort"],
            "seat_class": s.get("seat_class", s["effort"]),
            "effort_note": note,
            "adversarial_role": bool(s["adversarial_role"]),
        })
        if note:
            advisory_notes.append(f"{s['seat_id']}: {note}")
    record = {
        "schema": "run-record.v1",
        "session_id": plan["session_id"],
        "created_at": plan["created_at"],
        "profile": plan["profile"],
        "family": plan["family"],
        "staffing": {
            "seats": seats,
            "provider_families": plan["quorum"]["provider_families"],
            "fallback_relaxed": bool(plan["quorum"].get("fallback_relaxed", False)),
        },
        "arbiter": {
            "provider": arb["provider"],
            "effort": arb["effort"],
            "path": arb["path"],
            "is_external": bool(arb["is_external"]),
            "cold_context": bool(arb["cold_context"]),
        },
        "fallback_arbiter_residual": bool(arb.get("fallback_arbiter_residual", arb["path"] == "fallback")),
        "advisory_notes": advisory_notes,
        "outcome": {
            # Filled POST-RUN by the kernel/arbiter (§6a). null + graded:false here.
            "dissent_margin": None,
            "outcome_grade": None,
            "graded": False,
        },
    }
    errs = schema_validate(record, load_run_record_schema())
    if errs:
        raise ConveneError("materialized run-record failed schema validation:\n  " + "\n  ".join(errs))
    return record


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_contract(args: argparse.Namespace) -> Dict[str, Any]:
    if args.contract:
        raw = Path(args.contract).read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ConveneError("contract file did not parse to a mapping")
        return data
    # Convenience inline contract.
    contract: Dict[str, Any] = {}
    if args.profile:
        contract["profile"] = args.profile
    if args.task_family:
        contract["task_family"] = args.task_family
    if args.task:
        contract["task"] = args.task
    if args.outcome:
        contract["outcome"] = args.outcome
    if args.caller:
        contract["caller"] = args.caller
    if not (contract.get("profile") or contract.get("task_family")):
        raise ConveneError("provide --contract, or --profile/--task-family (+ --task)")
    return contract


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="avengers convene resolver (WP-2): fail-closed session-plan materializer")
    ap.add_argument("--contract", type=Path, help="path to a convene contract (JSON or YAML)")
    ap.add_argument("--profile", help="profile/family name (inline convenience contract)")
    ap.add_argument("--task-family", dest="task_family", help="task family (inline convenience contract)")
    ap.add_argument("--task", help="the decision/task text (inline convenience contract)")
    ap.add_argument("--outcome", choices=sorted(KNOWN_OUTCOMES), help="requested outcome")
    ap.add_argument("--caller", help="user|pa|forge|founder|alf")
    ap.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR)
    ap.add_argument("--roster-dir", type=Path, default=DEFAULT_ROSTER_DIR)
    ap.add_argument("--project-root", type=Path, default=Path.cwd(),
                    help="root under which .avengers/sessions/<id>/ is created")
    ap.add_argument("--session-id", help="override the generated session id")
    ap.add_argument("--out", type=Path, help="explicit session-plan.json output path")
    ap.add_argument("--dry-run", action="store_true", help="print pre-spend review and stop (no spend)")
    args = ap.parse_args(argv)

    try:
        contract = _load_contract(args)
        plan = build_session_plan(
            contract,
            profiles_dir=args.profiles_dir,
            roster_dir=args.roster_dir,
            session_id=args.session_id,
        )
    except ConveneError as e:
        sys.stderr.write(f"CONVENE FAIL-CLOSED: {e}\n")
        return 2

    if args.dry_run:
        sys.stdout.write(render_pre_spend_review(plan) + "\n")
        return 0

    if args.out:
        out_path = Path(args.out)
        session_dir = out_path.parent
    else:
        session_dir = Path(args.project_root) / ".avengers" / "sessions" / plan["session_id"]
        out_path = session_dir / "session-plan.json"
    session_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(out_path, json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    # §6a instrumentation sink: run-record.json alongside the session-plan (NAMED
    # artifact; staffing populated, outcome fields null until the run grades them).
    run_record = build_run_record(plan)
    run_record_path = session_dir / "run-record.json"
    _atomic_write_text(run_record_path, json.dumps(run_record, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.write(
        f"session dir: {session_dir}\nsession-plan: {out_path}\nrun-record: {run_record_path}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
