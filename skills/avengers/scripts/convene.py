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
    fresh persona-free CALL that did NOT file a position, argue, or ballot. Unless the
    profile DECLARES its arbiter (D23, below), its
    provider MUST differ from EVERY deliberation seat's provider (widened from
    adversarial-only). CLEAN path = an eligible provider used by no deliberation seat
    (total exclusion). FALLBACK path = no eligible provider is free of deliberation
    -> the strongest-adjudication-prior NON-adversarial provider, cold-context, with
    the ACCEPTED style-recognition residual RECORDED as `fallback_arbiter_residual`
    in run-record.json. In a healthy session coding-ratification lands on the
    FALLBACK path: its seats hold all three provider families (codex, claude, and
    agy again since #368), and agy is not eligible there
    (ARBITER_INELIGIBLE_PROVIDERS, scoped by D29 — see _select_arbiter_provider);
    under any codex refusal its arbiter is agy on the fallback path (agy holds a
    seat since #368; it was the clean path while agy held none). An ALL-ADVERSARIAL
    profile is arbiter-unsatisfiable -> fails CLOSED (ConveneError), never hangs.
  - honours a DECLARED arbiter (S081 revision 4, WP-D3; design §3.4 D23, plan L6): a profile with
    `arbiter: {provider, role}` AND the top-level `arbiter_independence: separate-session` names its
    arbiter instead of letting the selection choose one. For that profile the provider-exclusion rule
    is RELAXED to: the arbiter's MODEL differs from every member seat's model (a shared model fails
    CLOSED) and it runs in its OWN SESSION (the Claude label says so). The member seats are therefore
    materialised BEFORE a declared arbiter resolves. The arbiter block is a closed vocabulary, and half
    a declaration fails closed rather than being silently ignored. The plan's arbiter object carries
    the arbiter's obligations (cite evidence for each ruling, may abstain, send unresolved material
    disputes to the user). A profile that declares nothing resolves exactly as before.
  - REJECTS un-pinned codex effort and unknown effort tokens. No tier is retired:
    `high` resolves (S081 WP-102, S080 §4.4/§11.1); whether a legal (model, tier)
    pair is RECOMMENDED is an advisory note from MEASURED_EFFORT_FINDINGS, never a
    rejection (legality belongs to skills/_meta/codex_model.py, S080 §11.2)
  - performs a TWO-LAYER config merge ONLY: shipped defaults <- profile. It reads
    NO repo-local override file (a drive-by injection vector, design §3/§14).
  - injects the resolver-owned guard stacks (codex `-s read-only -m <slug>` with a
    per-call effort pin, never `--ephemeral` (#302: every codex seat is metered), run UNDER THE D24
    ACTIVITY WATCHDOG — `codex_watch.py --hard-cap <T> -- codex exec …` rather than
    `timeout <T> codex exec …`, so a seat call is stopped by SILENCE and only capped
    by T; agy `--sandbox --mode plan --model <slug>` from an empty cwd, flags-before `-p`, still on `timeout <T>`
    because L13 deliberately left the agy seat timeout and its 900 s watchdog cap
    un-reconciled until revision 5 wires the agy call sites; Claude seats a host-spawn
    label naming the model). EVERY seat's MODEL comes from skills/_meta/seat_model.py by role —
    EVERY member SEAT by `seat_weight` (main -> consultant_main, else consultant_support;
    amendment 3 D25/D26 ended codex seats' exemption, so one profile may hold a codex main
    seat and a codex support-tier seat; since the astra reserve, roster rev 4, the main seat
    and the codex arbiter are the codex STD literal, never astra), the arbiter `arbiter` — and the codex
    ceiling from codex_model.timeout_for, all FAIL-CLOSED: a seat that cannot be
    pinned is a ConveneError (S081 WP-R07 wiring, WP-102 seat models)
  - substitutes an UNAVAILABLE codex member seat at PLAN BUILD (S081 amendment 1 D6,
    item 4; plan J12, J16): one availability evaluation per build
    (codex_quota.unavailable() + an in-process `shutil.which("codex")`) plus each codex
    seat's own "no eligible model for this effort" (the std literal unlisted or without the
    effort, since the astra reserve). Such a seat becomes a Claude
    seat pinned to seat_model `consultant_main` (the Claude main tier) whatever its seat_weight, keeps
    its adversarial_role, declares fallback_ok and records substitute_for /
    substitution_reason / requested_model — BEFORE the structural validate and the
    arbiter, which then excludes codex. Never a codex std/support model (same plan quota). A broken resolver (e.g. an
    invalid freeze pin) is still a ConveneError, never a substitution. Only main()'s
    persisted path records one `deliberation` substitution row per substituted seat, keyed
    on the SESSION id (plan L9)
  - ADMITS the codex member seats AT PLAN TIME (S081 revision 4, WP-D2; design §3.4, §2.2 —
    closing I11). The session id is minted BEFORE the substitution, so each build makes ONE
    in-process codex_quota.admit("deliberation", <session id>, size=…, model_class=…) per
    model class per session — a single decision in each shipped profile since the astra reserve, because
    every shipped codex seat is std-class (a custom profile seating TOP and std would take two) — after the pin and the plan-wide checks (seat_model's
    `argv --use` order, J10). A REFUSAL (threshold,
    budget_spent, budget_store_unavailable, an unavailable token) re-seats the seat through the
    SAME substitution with the decision's reason; the decision's `admission_id` is stored on
    the seat beside substitute_for / substitution_reason / requested_model (seat provenance —
    NOT inside the r14 `provenance` object, which holds seat_model pin keys only). Only a
    persisted convene RECORDS; --dry-run and a bare build_session_plan decide CHECK-ONLY
    (admission_id null, no row, no store, no .lock). The budget is the session's, not a turn's:
    no guard stack carries an admission step
  - `--size light|medium|complex` (D17): absent is complex, recorded as size_source `default`
    and resolved WITHOUT reading .forge/size (sizing is opt-in, as in seat_model); a given
    size resolves through seat_model's L7 under --project-root (light/medium -> the codex std tier)
  - handles the codex roster's THREE states distinctly (#282 R4 + R8, plan K14, K15): an
    ABSENT ~/.codex/models_cache.json gives harness-literal codex seats (sanctioned; the
    seat_model pin's provenance says so); an INVALID one is a ConveneError naming
    roster_invalid for member seats and the arbiter alike (never a substitution, never a
    recompute) — EXCEPT for a codex FREEZE, which is honoured UNVALIDATED because it is the
    operator's emergency override (#282 fix round 1 F15, plan K47; accepted K14 behaviour,
    unchanged) and whose plan then records `roster_invalid`; NO ELIGIBLE model substitutes a
    member seat as above, and for the ARBITER excludes codex and recomputes the selection
    ONCE (resolve_arbiter)
  - persists every materialised member seat's and the arbiter's seat_model pin provenance as
    `provenance` = {requested_selector, resolved_model, source, roster_fetched_at} (+ `frozen_slug`,
    the pins-file top as written, when source is freeze; + `roster_invalid: true` when the pin
    carries it, i.e. a freeze honoured against an unreadable roster), in the session plan and the
    run record (#282 r14, plan K16; #282 fix round 1 F15, plan K47; persisted_provenance)
  - derives the wall-clock budget FLOOR from the resolved timeouts (arbiter timeout
    + 2 x the slowest external member seat); a lower requested value is raised to
    it with a recorded note, never silently truncating a legal call (S081 I12)
  - stamps profile-sha256 provenance
  - materializes a flat JSON session-plan that validates against
    schemas/session-plan.v2.schema.json (a bundled stdlib mini-validator; no
    third-party jsonschema dependency). v1 is NOT mutated in place, so a resumed
    mid-flight v1 plan can't silently misvalidate.
  - writes the §6a run-record.json instrumentation sink (staffing populated;
    outcome fields null until the run grades them)
  - `--dry-run` prints a pre-spend review and stops (no session dir, no spend, and a CHECK-ONLY
    admission decision that records nothing)

No LLM, no network, no semantic decisions. Dependencies: stdlib + PyYAML (for the
human-authored profile/roster YAML) + the sibling harness modules
skills/_meta/{seat_model,codex_model}.py (home-tier file reads only). Machine state
(the session-plan) is JSON.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import yaml  # PyYAML — explicitly owned dependency (design §2/§6)
except ImportError:  # pragma: no cover
    sys.stderr.write("convene.py requires PyYAML (import yaml).\n")
    raise

_HERE = Path(__file__).resolve().parent
_SKILL_ROOT = _HERE.parent

# Seat models (S081 design §4.2, §4.8 convene row). seat_model is the ONE place review /
# consultancy / arbiter seats are resolved; it reads only home-tier files, never the working
# directory or a project file. The import is DEFERRED to resolution on failure: a missing or
# broken harness module must surface as a fail-closed ConveneError at plan build (exit 2, no
# spend), not as a traceback that also takes down convene's pure helpers.
_META_DIR = _SKILL_ROOT.parent / "_meta"
try:
    if str(_META_DIR) not in sys.path:
        sys.path.insert(0, str(_META_DIR))
    import codex_model as _codex_model  # noqa: E402
    import codex_quota as _codex_quota  # noqa: E402  (seat_model imports it too)
    import seat_model as _seat_model  # noqa: E402
    _SEAT_MODEL_IMPORT_ERROR: Optional[str] = None
except Exception as _exc:  # noqa: BLE001 - recorded, then re-raised as ConveneError on use
    _codex_model = None  # type: ignore[assignment]
    _codex_quota = None  # type: ignore[assignment]
    _seat_model = None  # type: ignore[assignment]
    _SEAT_MODEL_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
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
# No tier is retired (S081 WP-102; S080 §4.4, §11.1 reading (a)). The set and its check stay so
# a future POLICY retirement has one place to land; the plan still reports it (now empty).
RETIRED_EFFORT_TIERS: frozenset = frozenset()
# Codex tiers convene accepts. `high` is legal (every listed model supports it, S080 D2);
# `minimal` is gone (no listed model supports it, S080 D1); `default` is never legal for codex.
# Each tier here must have a codex_model._TIMEOUT_FLOOR_S row — codex_guard_stack's strict
# timeout_for lookup turns a missing one into a ConveneError, so the pair cannot drift silently.
CODEX_EFFORT_TIERS = frozenset({"low", "medium", "high", "xhigh", "max"})
NON_CODEX_EFFORTS = frozenset({"default"})          # claude/agy: no effort pin ('default')
KNOWN_OUTCOMES = frozenset({"decision", "deliverable", "forge_brief", "auto"})

# Advisory notes keyed on (MODEL, tier) — S080 §4.4 / §11.2. LEGALITY ("does this model support
# this tier?") is codex_model's, read from the roster; RECOMMENDATION ("did this legal pair
# measure well?") is this table's. A hit resolves the tier and records the note; it never rejects.
MEASURED_EFFORT_FINDINGS: Dict[Tuple[str, str], str] = {
    ("gpt-5.6-sol", "high"): "never beat medium — benchmark 2026-07-11, 14 scored runs",
}
# The model every SEAT_CLASS_TABLE codex tier was measured on (the 2026-07-11 benchmark).
SEAT_CLASS_MEASURED_ON = "gpt-5.6-sol"

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
    {"low", "medium", "high", "xhigh", "max", "default"}
)
# Each provider's NATIVE-legal concrete tiers (what may pass through untouched).
PROVIDER_LEGAL_TIERS: Dict[str, frozenset] = {
    "codex": CODEX_EFFORT_TIERS,            # must be pinned; 'default' is NOT legal
    "claude": NON_CODEX_EFFORTS,            # no effort pin ('default'); the MODEL comes from seat_model
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
# `measured_on` (S080 §4.4): the model the row's codex tier was measured on. The xhigh floor and
# the max ceiling are PROVISIONAL for any other codex model — resolve_effort(model=...) records
# that as a note instead of letting an unmeasured model silently inherit the benchmark. A row's
# keys are therefore the providers plus `measured_on`; look a provider up only after checking it
# is in KNOWN_PROVIDERS (resolve_effort does).
SEAT_CLASS_TABLE: Dict[str, Dict[str, Any]] = {
    # The anti-sycophancy / ballot floor for adversarial critics.
    CHALLENGER_FLOOR: {
        "measured_on": SEAT_CLASS_MEASURED_ON,
        "codex": ("xhigh", None),
        "claude": ("default", f"{_ANTI_SYCOPHANCY_NOTE} (claude); no effort pin, tier 'default'"),
        "agy": ("default", f"{_ANTI_SYCOPHANCY_NOTE} (agy); using default advisory tier"),
    },
    # Ratification-arbiter ceiling: re-keys the old effort_on_codex:max/1200 pin
    # onto (provider, seat-class). codex -> 'max' (timeout 1200). MOOT for
    # coding-ratification (its arbiter is claude/agy); the max-vs-2026-07-11-sol
    # re-derivation is DEFERRED to the backlog (design §4).
    RATIFICATION_ARBITER: {
        "measured_on": SEAT_CLASS_MEASURED_ON,
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

# S081 revision 4, amendment 3 (D25) + D23 ("never agy as arbiter" - D23 named the agy family of its day; the
# agy family is now roster data, model_roster.AGY_FAMILY, and the rule applies to whichever family agy serves). agy is not
# an arbiter CANDIDATE for a profile's own composition. Its `adjudication_prior` of 2 stays: that is a statement
# about adjudication belief, and rewriting it would bury the rule in a weight table instead of saying it.
#
# WHY IT EXISTS: D25 removed agy's SEATS from four profiles, and holding no seat is exactly what
# qualifies a provider for the CLEAN arbiter path. The seat removal therefore SILENTLY PROMOTED agy
# from member to arbiter in the one profile that still selects rather than declares —
# coding-ratification resolved agy (the agy family of the day), path clean, MEASURED, where amendment 3's
# table (dated S081) says "the Claude main tier, selected, fallback path". The decision that took agy out
# would have put it in charge. #368 seated agy again in every profile, so agy is no longer a clean-path
# candidate anywhere; the bar now keeps agy (a non-adversarial seat) off a healthy session's fallback path.
#
# WHY IT IS SCOPED TO A HEALTHY SESSION, which is the whole of the rule and was paid for: barring agy
# unconditionally made 32 substitution paths FAIL CLOSED, because a session whose codex seat is
# re-seated on Claude can be left with only an adversarial Claude and no eligible judge. That would
# have made coding-ratification UNRUNNABLE whenever codex is unavailable, and deleted the named R8
# behaviour that puts a substituted session's arbiter on agy. jc10 says such a session BECOMES
# CLAUDE-ONLY — not that it stops running. D25's own words are scoped the same way ("no longer a
# deliberation seat or an arbiter IN THE OTHER FOUR PROFILES"): it governs composition, not the
# degraded-mode fallback. So agy stays the last-resort arbiter for a session that has ALREADY lost a
# provider, and is barred from every session that has not.
ARBITER_INELIGIBLE_PROVIDERS = frozenset({"agy"})
BUILTIN_SEAT_AFFINITY: Dict[str, Dict[str, int]] = {
    "claude": {"integration": 3, "calibration": 3, "coding_depth": 2},
    "codex": {"edge_catching": 3, "evidence_discipline": 3, "unsticking": 2},
    "agy": {"research_breadth": 2, "operations": 2},
}

MIN_MEMBER_SEATS = 3
MIN_PROVIDER_FAMILIES = 2

# Guard-stack ceilings: ONE timeout owner per provider (S081 design §4.2, L5; I20). Codex
# ceilings come only from codex_model.timeout_for(model, effort) (its tier floor table); the
# local codex table and the separate 1200s ratification-arbiter constant are deleted, which
# moves member seats to the floor: medium 180->600, xhigh 300->600, max 300->1200, low 120
# (a timeout is a ceiling, raising it does not change cost). agy and Claude ceilings come from
# the seat_model role row (agy 600; Claude members 600, a Claude arbiter 1200). SEED_LATENCY_S
# below is an ESTIMATE, not a ceiling.

# Seat -> seat_model role (S081 design §4.8 convene row, §4.9; replaces WP-R07's interim I7
# mapping). Every provider resolves through seat_model now, Claude included:
#   every member SEAT       -> consultant_main when seat_weight == main, else consultant_support
#                              (amendment 3 D25/D26 brought codex seats under this rule; a BARE
#                               codex call with no seat -> consultant_main, as before; the codex std
#                               literal since the astra reserve, roster rev 4)
#   the external arbiter    -> arbiter (codex, agy or claude)
# `seat_weight` is an OPTIONAL top-level roster-card field (a profile seat entry may override it),
# one of SEAT_WEIGHTS, default support. These are module globals read at call time.
SEAT_WEIGHT_MAIN = "main"
SEAT_WEIGHT_SUPPORT = "support"
SEAT_WEIGHTS = frozenset({SEAT_WEIGHT_MAIN, SEAT_WEIGHT_SUPPORT})
DEFAULT_SEAT_WEIGHT = SEAT_WEIGHT_SUPPORT
WEIGHTED_MEMBER_ROLES: Dict[str, str] = {  # EVERY member seat, keyed on seat_weight (see below)
    SEAT_WEIGHT_MAIN: "consultant_main",
    SEAT_WEIGHT_SUPPORT: "consultant_support",
}
#: The role a codex call that names NO seat takes (see seat_role_for). Before amendment 3 this was
#: every codex member seat's role, weight or not; it now covers the seatless call only.
CODEX_MEMBER_ROLE = "consultant_main"
# S081 revision 4, amendment 3 (D25/D26, user-approved 2026-09-19): a codex member seat is now
# weight-keyed like every other member seat, so ONE profile can hold TWO codex seats of DIFFERENT
# model classes — a `main` card on consultant_main (codex TOP, astra: the visionary lead — SUPERSEDED by the
# astra reserve, roster rev 4: consultant_main is the codex std literal, so both seats are now std-class) and a
# `support` card on consultant_support (the codex support-tier literal @ medium: the seat agy vacated).
# It REPLACES the constant `CODEX_MEMBER_ROLE = "consultant_main"` ("every codex member seat,
# regardless of seat_weight"), which made a second codex seat resolve astra as well.
#
# MEASURED, and recorded because amendment 3 asserts the opposite: the amendment says "the
# size-to-model-class rule already routes a supporting codex seat to sol (D16)". IT DOES NOT.
# `size` (WP-D2, D17) is a per-CONVENE decision — a light/medium convene sizes EVERY codex member
# seat down through seat_model's L7 — so it cannot separate two seats inside one session. Without
# this change both of amendment 3's codex seats resolve consultant_main. The premise was false;
# the composition it derives is unaffected, because this routing delivers exactly that table.
#
# NO SHIPPED SEAT MOVES: every codex seat shipped today sits on a `main` card (architect,
# skeptic, wordsmith), and every seat amendment 3 moves to codex (operator, user-advocate) is a
# default-`support` card. Verified across all five profiles by test.
#
# THE RULE IS SCOPED TO SEATS, and that scoping is load-bearing rather than cosmetic. A SEAT always
# carries a concrete weight (resolve_seats resolves entry -> card -> DEFAULT_SEAT_WEIGHT), so seats
# are weight-routed; a BARE call that names no seat keeps CODEX_MEMBER_ROLE. Measured when the rule
# was first written unscoped: 86 tests failed, and the cause was not test churn — every weightless
# codex call had moved to the support-tier LITERAL, which is not a TOP selector. At the time that also
# added `--ephemeral` (unmetered); since #302 (design §3.4b, JC-3) no codex seat is ephemeral, so what
# the scoping still protects is the MODEL CLASS: a bare call must not silently drop from TOP to the
# support tier. Amendment 3 changed composition, and a composition change must not quietly rewrite it.
ARBITER_ROLE = "arbiter"                # the external arbiter call, any provider

# D23 DECLARED arbiter (S081 revision 4, WP-D3; design §3.4 "D23 arbiter rule", plan L6). A profile MAY
# declare its arbiter — `arbiter: {provider: <p>, role: <seat_model role>}` WITH the TOP-LEVEL key
# `arbiter_independence: separate-session` — instead of letting resolve_arbiter select the provider. Such a
# profile trades the provider-exclusion rule for the RELAXED rule: the arbiter's MODEL differs from every
# member seat's model, and it runs in its OWN SESSION. Context independence stands in for provider
# independence. Only a profile that declares it is affected; every other profile resolves as before.
#
# The ARBITER BLOCK is a CLOSED vocabulary. `prefer` and `provider_must_not_equal_adversarial` are INERT
# labelled history (never read); `effort_on_codex` is consumed by a codex ratification arbiter; `provider`
# and `role` declare a D23 arbiter. Any other key fails CLOSED, and so does HALF a declaration: a provider /
# role with no arbiter_independence would otherwise be silently IGNORED, and the selection algorithm would
# quietly seat a different arbiter from the one the profile names.
ARBITER_INDEPENDENCE_KEY = "arbiter_independence"
ARBITER_INDEPENDENCE_SEPARATE_SESSION = "separate-session"
ARBITER_INDEPENDENCE_VALUES = frozenset({ARBITER_INDEPENDENCE_SEPARATE_SESSION})
ARBITER_DECLARATION_KEYS: Tuple[str, ...] = ("provider", "role")
ARBITER_BLOCK_KEYS = frozenset({"prefer", "provider_must_not_equal_adversarial", "effort_on_codex",
                                *ARBITER_DECLARATION_KEYS})
#: The seat_model roles a declared arbiter may name: exactly the roles convene already resolves for its calls.
DECLARED_ARBITER_ROLES = frozenset({"consultant_main", "consultant_support", ARBITER_ROLE})
DECLARED_ARBITER_SELECTION = "declared"
#: What a declared (D23) arbiter owes the session. Carried on the plan's arbiter object, so the chair that
#: spawns the arbiter reads them from the frozen plan. An arbiter that cannot abstain is not D23's arbiter.
DECLARED_ARBITER_OBLIGATIONS: Tuple[str, ...] = (
    "cite evidence for each ruling",
    "may abstain",
    "send unresolved material disputes to the user",
)
#: A Claude arbiter is a HOST spawn, not a CLI process, so its label must say the session is its own.
SEPARATE_SESSION_LABEL = "separate session: a fresh context that never held a member seat's turns"
#: agy slugs carry the reasoning LEVEL (`gemini-<v>-<family>-high`, e.g. `gemini-4-argon-high`; the family is
#: model_roster.AGY_FAMILY); the relaxed rule compares the MODEL, so the `-high` and `-medium` of one agy
#: family version are ONE model.
_AGY_LEVEL_SUFFIX = re.compile(r"-(high|medium|low)$")

# Codex unavailable (amendment 1's "astra unavailable") -> plan-time Claude-main-tier substitution (S081 amendment 1 D6 + item 4; plan J12, J16).
# A codex member seat codex cannot serve is re-seated on Claude BEFORE the structural validate and
# the arbiter. The Claude seat is pinned to CODEX_SUBSTITUTE_ROLE whatever the card's seat_weight
# (a support weight would otherwise land on opus): it stands in for a TOP seat, so it gets the TOP
# Claude row. The reasons are codex_quota.SUBSTITUTION_REASONS members: the four plan-time checks
# below, plus — since S081 revision 4 WP-D2 admits the seat at plan time — whatever reason an
# admission refusal carries (budget_spent, budget_store_unavailable, a token; `threshold` until #322).
CODEX_CLI = "codex"                      # the binary the plan-time check looks up (seat_model.CODEX_CLI)
CODEX_SUBSTITUTE_FOR = "codex"
CODEX_SUBSTITUTE_PROVIDER = "claude"
CODEX_SUBSTITUTE_ROLE = "consultant_main"
CODEX_SUBSTITUTION_USE = "deliberation"  # the budget-row use for an avengers codex member seat
CODEX_PROVIDER_GAP = "openai"
UNAVAILABLE_CLI_MISSING = "cli_missing"
UNAVAILABLE_NO_ELIGIBLE = "no_eligible_model"

# Plan-time admission (S081 revision 4, WP-D2; design §3.4, §2.2, D17; plan L9). ONE use for the seat's
# admission AND its substitution row, keyed on the SESSION id: `deliberation` is the avengers codex seat
# (J16), one seat per session. The decision's id rides on the seat under ADMISSION_ID_KEY — seat
# provenance beside the substitution fields, never inside the r14 `provenance` object (pin keys only).
CODEX_ADMISSION_USE = CODEX_SUBSTITUTION_USE
ADMISSION_ID_KEY = "admission_id"
#: The `--size` vocabulary, taken from its owner (codex_quota re-exports review_risk's) rather than
#: restated. Empty when the harness failed to import: every size is then refused, and plan build fails
#: closed anyway. An ABSENT size is D17's complex, recorded as size_source `default`.
SIZES: Tuple[str, ...] = tuple(_codex_quota.SIZES) if _codex_quota is not None else ()

# Persisted seat provenance (#282 r14, plan K16). Every materialised member seat and the arbiter carry
# `provenance`: EXACTLY these seat_model pin provenance keys, plus PROVENANCE_FROZEN_SLUG (the pins-file
# `top` as written; seat_model.FROZEN_SLUG) when source is "freeze". The pin's live / event keys
# (quota_state, fallback_reason, roster_stale, roster_entries_skipped, ...) are not persisted: a frozen
# plan records what was resolved, not a meter reading.
#
# ONE EXCEPTION (#282 fix round 1 F15, plan K47): PROVENANCE_ROSTER_INVALID. In a fail-closed convene
# the ONLY pin that can carry it is a FROZEN codex seat — every other codex path raises ConveneError on
# an invalid roster — so the key marks precisely the case F15 is about: a freeze honoured UNVALIDATED
# because the roster could not be read. It is not a meter reading; it is the reason the plan's
# `roster_fetched_at` is null, and without it a plan frozen under an INVALID roster is
# indistinguishable from one frozen under an ABSENT one.
PERSISTED_PROVENANCE_KEYS: Tuple[str, ...] = ("requested_selector", "resolved_model", "source", "roster_fetched_at")
#: #291: the model roster revision (seat_model.ROSTER_REV). Persisted WHEN THE PIN CARRIES IT - every
#: Claude pin and every codex-std pin; codex TOP and agy pins do not - and OPTIONAL on read, so a
#: plan or run record frozen before #291 still validates and resumes (the schemas do not require it).
PERSISTED_OPTIONAL_PROVENANCE_KEYS: Tuple[str, ...] = ("roster_rev",)
PROVENANCE_FROZEN_SLUG = "frozen_slug"
PROVENANCE_ROSTER_INVALID = "roster_invalid"
PROVENANCE_SOURCE_FREEZE = "freeze"

# Wall-clock floor (S081 I12, the S080 H2 formula): a session budget must hold the arbiter call it
# authorises plus two turns of its slowest external (codex/agy) member seat.
WALL_CLOCK_FLOOR_MEMBER_TURNS = 2

# Estimator cold-start latency seeds, seconds (design §9). ESTIMATES, not ceilings; a
# (provider, tier) without a seed uses _SEED_FALLBACK.
SEED_LATENCY_S = {
    ("codex", "low"): 40, ("codex", "medium"): 60,
    ("codex", "xhigh"): 60, ("codex", "max"): 300,
    ("agy", "default"): 45, ("claude", "default"): 60,
}
_SEED_FALLBACK = 60

# TWO-LAYER merge: this is the ONLY config baseline under the profile. There is no
# third repo-local layer by design (§3/§14). `wall_clock_s` has no shipped default: it is the
# floor derived at plan build from the resolved timeouts (wall_clock_budget, S081 I12).
SHIPPED_DEFAULTS: Dict[str, Any] = {
    "depth": "default",
    "budgets": {"max_seat_calls": 10, "max_cycles": 1},
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


class NoEligibleCodexModelError(ConveneError):
    """A codex seat's roster lists NO eligible TOP model for its effort (seat_model's
    NoEligibleModelError). Still a ConveneError, so every fail-closed caller is unchanged;
    plan build tells it apart because it means "astra unavailable" (substitute the seat),
    not a broken resolver (fail closed)."""

    unavailable_reason = UNAVAILABLE_NO_ELIGIBLE


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
def measured_effort_note(model: Optional[str], effort: str) -> Optional[str]:
    """The MEASURED_EFFORT_FINDINGS note for a legal (model, tier) pair, or None (S080 §4.4)."""
    if not model:
        return None
    finding = MEASURED_EFFORT_FINDINGS.get((model, effort))
    if finding is None:
        return None
    return f"measured finding for {model} @ {effort}: {finding} (advisory; the tier still resolves)"


def _join_notes(*notes: Optional[str]) -> Optional[str]:
    kept = [n for n in notes if n]
    return "; ".join(kept) if kept else None


def resolve_effort(seat_id: str, provider: str, effort_pin: str, *,
                   model: Optional[str] = None) -> Tuple[str, str, Optional[str]]:
    """Resolve an effort pin (a SEAT-CLASS semantic name OR a raw concrete tier)
    to a concrete tier for `provider`, per the (provider, seat-class) table
    (design §2a). This REPLACES the old seat⇒provider validate_effort that
    fail-closed on any non-codex + non-'default' effort.

    `model` (keyword, default None — S080 M6/§11.2) is the seat's RESOLVED model when the
    caller knows it. It only adds advisory notes; it never changes the tier or legality:
      * a MEASURED_EFFORT_FINDINGS hit for (model, concrete tier) -> recorded note
        (e.g. the 2026-07-11 benchmark's sol @ high "never beat medium");
      * a codex seat-class whose row was `measured_on` a different model -> a
        PROVISIONAL note (the benchmark is not inherited silently).
    model=None means no note lookup, so every pre-M6 positional call keeps its result.

    Returns (concrete_effort, seat_class, note):
      * concrete_effort — a KNOWN_CONCRETE_TIERS value legal for `provider`
        (goes into the plan + guard stack).
      * seat_class — the semantic seat-class name if one was used, else the raw
        tier itself. The ratification arbiter's `max` is derived from THIS (design
        §2a/§4), not from the literal effort tier; its 1200s ceiling is simply
        codex_model.timeout_for(model, 'max') (S081 I20).
      * note — an advisory string destined for the run record (§6a), or None.

    Fail-closed (ConveneError): a policy-retired tier (RETIRED_EFFORT_TIERS — empty
    today); un-pinned / illegal codex; an unknown token that is neither a seat-class
    nor a known tier; a seat-class with no row for `provider`. Whether the resolved
    MODEL supports the tier is checked by seat_model / codex_model at pin resolution.
    """
    if provider not in KNOWN_PROVIDERS:
        raise ConveneError(
            f"seat '{seat_id}': unknown provider {provider!r} (known: {sorted(KNOWN_PROVIDERS)})"
        )
    # A policy retirement applies regardless of provider or how the tier was pinned.
    if effort_pin in RETIRED_EFFORT_TIERS:
        raise ConveneError(
            f"seat '{seat_id}': effort tier '{effort_pin}' is RETIRED and rejected"
        )
    # 1) Semantic seat-class -> per-(provider, seat-class) resolution.
    if effort_pin in SEAT_CLASS_TABLE:
        row = SEAT_CLASS_TABLE[effort_pin]
        if provider not in row:  # provider is a KNOWN_PROVIDERS value, never `measured_on`
            raise ConveneError(
                f"seat '{seat_id}': seat-class '{effort_pin}' has no resolution "
                f"for provider {provider!r}"
            )
        concrete, note = row[provider]
        provisional = None
        measured_on = row.get("measured_on")
        if provider == "codex" and model and measured_on and model != measured_on:
            provisional = (
                f"seat-class {effort_pin!r} tier {concrete!r} was measured on {measured_on}; "
                f"PROVISIONAL for {model}"
            )
        return concrete, effort_pin, _join_notes(note, measured_effort_note(model, concrete), provisional)
    # 2) Literal concrete tier (its own seat-class).
    if effort_pin not in KNOWN_CONCRETE_TIERS:
        raise ConveneError(
            f"seat '{seat_id}': unknown effort/seat-class {effort_pin!r} "
            f"(seat-classes: {sorted(SEAT_CLASS_TABLE)}; tiers: {sorted(KNOWN_CONCRETE_TIERS)})"
        )
    if effort_pin in PROVIDER_LEGAL_TIERS[provider]:
        # native — pass through (with the measured note when the model is known)
        return effort_pin, effort_pin, measured_effort_note(model, effort_pin)
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
        f"resolved to the unpinned tier {advisory!r}"
    )
    return advisory, effort_pin, note


def validate_effort(seat_id: str, provider: str, effort: str) -> str:
    """Back-compat shim (design §2a): RESOLVES a seat-class / tier pin per
    (provider, seat-class) and returns only the concrete effort. Raises
    ConveneError fail-closed on bad input (un-pinned or illegal codex, an unknown
    token, a policy-retired tier — none today). No model is passed, so no advisory
    note is looked up. Prefer resolve_effort() for the (effort, seat_class, note) tuple."""
    concrete, _seat_class, _note = resolve_effort(seat_id, provider, effort)
    return concrete


# --------------------------------------------------------------------------- #
# Guard stacks (resolver-owned invariants, design §2/§4)
# --------------------------------------------------------------------------- #
_PROMPT_SLOT = "…"  # placeholder for the assembled seat prompt (see seat_prompt.py)

# D24 stream slots. The watchdog streams the call to FILES (that growth is one of the three
# heartbeats), so the chair substitutes a run-scoped path for each, exactly as it already
# substitutes the prompt for _PROMPT_SLOT. Placeholders, not defaults: a guard stack that
# shipped a real path would have every seat of every session write to the same two files.
#
# BRACES, NOT ANGLE BRACKETS. A guard stack is run VERBATIM by the chair (and by the
# stub-launch tests, through `bash -c`), so `<stdout-file>` would not be a placeholder at
# all — the shell would read it as a REDIRECT and the stack would silently do something
# else entirely. A single braced word has no brace expansion, so bash passes it through
# unchanged and an unsubstituted slot stays visible instead of becoming a redirection.
_STDOUT_SLOT = "{stdout-file}"
_STDERR_SLOT = "{stderr-file}"

#: The watchdog script the codex guard stack invokes. Resolved from _META_DIR so the stack
#: names the SAME tree convene imported codex_model from -- a repo checkout and the live
#: ~/.claude copy each name their own, and neither can silently run the other's watchdog.
_CODEX_WATCH = _META_DIR / "codex_watch.py"

# HONEST LIMITS of a guard stack. It is a STRING that the chair runs verbatim; kernel.py
# does not dispatch it, so nothing here can observe the call. The model is resolved at PLAN
# BUILD and frozen into the plan (a resumed session keeps the plan-time pin). The stack has
# no call-time hook, so the codex seat is admit-gated ONCE, AT PLAN BUILD (S081 revision 4,
# WP-D2 — I11 closed): the session's `deliberation` admissions (one per model class) cover every
# turn, and a trip-wire that trips mid-session is not seen by a frozen plan (the same no-re-seating
# limit as below).
# PLAN-TIME SUBSTITUTION EXISTS (S081 amendment 1 D6, plan J16): a codex member
# seat codex cannot serve when the plan is built (a fresh rate_limit_reached / quota_exhausted
# reading, no codex binary, no eligible TOP model for its effort) is re-seated on Claude
# (the Claude main tier) before the arbiter is chosen — see apply_codex_substitution. MID-SESSION RE-SEATING
# DOES NOT EXIST: a codex stack that fails after the plan is frozen keeps today's no-show
# handling, because the plan froze arbiter != adversarial provider and re-seating a live
# session could break that invariant. That failure is a recorded gap, not a substitution.


def validate_seat_weight(seat_id: str, seat_weight: Any) -> str:
    """None -> DEFAULT_SEAT_WEIGHT; one of SEAT_WEIGHTS passes; anything else fails CLOSED."""
    if seat_weight is None:
        return DEFAULT_SEAT_WEIGHT
    if not isinstance(seat_weight, str) or seat_weight not in SEAT_WEIGHTS:
        raise ConveneError(
            f"seat '{seat_id}': unknown seat_weight {seat_weight!r} (known: {sorted(SEAT_WEIGHTS)}) "
            "— fail-closed, no run, no spend"
        )
    return seat_weight


def seat_role_for(provider: str, *, is_arbiter: bool, seat_weight: Optional[str] = None,
                  substitute_for: Optional[str] = None) -> str:
    """The seat_model role one seat or arbiter call resolves (S081 §4.8, §4.9). Strict.

    arbiter -> ARBITER_ROLE for every provider; EVERY member SEAT, codex included ->
    WEIGHTED_MEMBER_ROLES[seat_weight]. Amendment 3 (D25/D26) removed codex's exemption from the
    weight rule, which is what lets ONE profile hold a `main` codex seat on consultant_main
    (the codex std tier since the astra reserve) and a `support` codex seat on consultant_support (the codex
    support tier). A codex call passing
    NO weight is not a seat and keeps CODEX_MEMBER_ROLE (see the branch below).
    A Claude member seat substituting codex (`substitute_for="codex"`, amendment 1 D6, J16) ->
    CODEX_SUBSTITUTE_ROLE whatever its weight: it stands in for a TOP codex seat, so a refused
    support-tier seat still falls back to the Claude main tier (D18), not to the support tier.
    An unknown provider or seat_weight, or a substitution that is not a Claude member seat
    standing in for codex, raises ConveneError.
    """
    if provider not in KNOWN_PROVIDERS:
        raise ConveneError(f"no seat_model role for unknown provider {provider!r} (known: {sorted(KNOWN_PROVIDERS)})")
    weight = validate_seat_weight("<call>", seat_weight)
    if substitute_for is not None:
        if substitute_for != CODEX_SUBSTITUTE_FOR or provider != CODEX_SUBSTITUTE_PROVIDER or is_arbiter:
            raise ConveneError(
                f"illegal substitution: substitute_for={substitute_for!r} on a {provider} "
                f"{'arbiter' if is_arbiter else 'member'} call (only a {CODEX_SUBSTITUTE_PROVIDER} member "
                f"seat stands in for {CODEX_SUBSTITUTE_FOR}) — fail-closed, no run, no spend")
        return CODEX_SUBSTITUTE_ROLE
    if is_arbiter:
        return ARBITER_ROLE
    if provider == "codex" and seat_weight is None:
        # A BARE codex call is a TOP call. Only a SEAT is weight-routed, and resolve_seats always
        # gives a seat a concrete weight (its entry's, else its card's, else DEFAULT_SEAT_WEIGHT),
        # so this branch is never the path a profile takes — it keeps `guard_stack_for`-style
        # callers, which name no seat, on consultant_main exactly as before amendment 3. Without
        # it every weightless codex call would silently move to the support-tier literal — a
        # different MODEL CLASS for calls this amendment never meant to touch (before #302 JC-3 it
        # also turned them `--ephemeral`; no codex seat is ephemeral now).
        return CODEX_MEMBER_ROLE
    return WEIGHTED_MEMBER_ROLES[weight]


def resolve_seat_pin(provider: str, effort: str, *, is_arbiter: bool = False,
                     seat_weight: Optional[str] = None,
                     substitute_for: Optional[str] = None,
                     size: Optional[str] = None, project_root: Any = None,
                     declared_role: Optional[str] = None) -> Tuple[str, Any]:
    """Resolve (role, seat_model.SeatPin) for one seat or arbiter call, FAIL-CLOSED.

    Codex passes convene's resolved effort (I5: convene owns effort, seat_model supplies the
    model and checks the effort is legal for it); agy takes its level from the role row; Claude
    gets the role's vendor alias (its roster tier: main or support) and its role-row timeout. `size` (S081 revision 4,
    WP-D2, D17) applies to a codex or agy MEMBER seat only and only when given: it resolves through
    seat_model's L7 with `project_root` naming the forge cycle whose .forge/size applies, so a
    light/medium codex seat serves the codex std tier and an agy seat serves the AGY_LEVEL_BY_SIZE
    level (#368). None is the unsized back-compat path (complex, no .forge/size read); the arbiter
    and Claude seats are never sized. Any resolution failure
    — no eligible model, an invalid freeze, an invalid codex roster (seat_model's message names
    roster_invalid, #282 R4), an agy family-rule violation, an effort the model lacks, an
    untabulated timeout, an unavailable seat_model — raises ConveneError. There is no
    fail-open path here: an unresolvable seat is never materialised as an unpinned call.
    "No eligible TOP model" raises the NoEligibleCodexModelError subclass, so plan build can
    substitute that seat (J16) while every other failure stays a plain fail-closed error.
    `declared_role` (S081 revision 4, WP-D3, D23) is a DECLARED arbiter's seat_model role, used in
    place of `arbiter`; it is legal on the arbiter call only and only from DECLARED_ARBITER_ROLES.
    """
    if declared_role is None:
        role = seat_role_for(provider, is_arbiter=is_arbiter, seat_weight=seat_weight,
                             substitute_for=substitute_for)
    elif not is_arbiter or substitute_for is not None or declared_role not in DECLARED_ARBITER_ROLES:
        raise ConveneError(
            f"illegal declared role {declared_role!r} on a {provider} {'arbiter' if is_arbiter else 'member'} "
            f"call (a declared role names the arbiter only, one of {sorted(DECLARED_ARBITER_ROLES)}) — "
            "fail-closed, no run, no spend")
    else:
        if provider not in KNOWN_PROVIDERS:
            raise ConveneError(f"no seat_model role for unknown provider {provider!r} (known: {sorted(KNOWN_PROVIDERS)})")
        role = declared_role
    if _seat_model is None or _codex_model is None:
        raise ConveneError(
            f"cannot pin {role} x {provider}: skills/_meta/seat_model.py is unavailable "
            f"({_SEAT_MODEL_IMPORT_ERROR}) — fail-closed, no run, no spend")
    try:
        if provider == "codex":
            sized: Dict[str, Any] = ({} if size is None or is_arbiter
                                     else {"size": size, "project_root": project_root})
            pin = _seat_model.resolve(role, provider, fail_open=False, effort=effort, **sized)
        elif provider == "agy" and size is not None and not is_arbiter:
            # #368: a sized convene serves an agy MEMBER seat the level model_roster.AGY_LEVEL_BY_SIZE
            # maps its size to (light -low, medium -medium, complex -high; seat_model #367 WP-C). Unsized,
            # the role row's level stands (consultant_main -high, consultant_support -medium). The arbiter
            # is never sized, and a size on a Claude seat is a seat_model caller bug, so neither gets one.
            pin = _seat_model.resolve(role, provider, fail_open=False, size=size, project_root=project_root)
        else:
            pin = _seat_model.resolve(role, provider, fail_open=False)
    except (_seat_model.SeatModelError, _codex_model.CodexModelError) as exc:
        error_type = (NoEligibleCodexModelError if isinstance(exc, _seat_model.NoEligibleModelError)
                      else ConveneError)
        raise error_type(
            f"cannot pin {role} x {provider} (effort {effort!r}): {exc} — fail-closed, no run, no spend"
        ) from None
    return role, pin


def codex_guard_stack(pin: Any, *, ephemeral: bool) -> str:
    """The watched codex seat call (S081 revision 4, D24):

    `python3 codex_watch.py --mode codex --model <slug> --hard-cap <T> --stdout-file <OUT>
     --stderr-file <ERR> -- codex exec [--ephemeral] -s read-only -m <slug>
     (convene passes ephemeral=False for every seat since #302 JC-3; the parameter stays for callers)
     -c model_reasoning_effort=<e> "…"`

    THE `timeout <T>` PREFIX IS GONE ON PURPOSE. A fixed wall clock stops a call for being
    SLOW; the watchdog stops it for being SILENT (no stdout / stderr / rollout heartbeat for
    the idle timeout), and keeps T only as a runaway cap. The evidence D24 was raised on is
    exactly this difference: completed astra calls ran 172-521 s, while two sol sessions
    (896 s and 538 s) were killed with no completion event while still emitting reasoning
    events to the last second — longest silences 183 s and 19 s. Under `timeout T` those
    calls die; under the watchdog they finish.

    T is codex_model.timeout_for(model, effort) — the single codex timeout owner (design
    §4.2, I20/L5); a miss raises. It is passed as `--hard-cap`, NOT as `--effort`: `--effort`
    would make codex_watch's own HARD_CAP_S table the owner, and a second owner is free to
    drift from the registry every other seat resolves against. The idle timeout is left to
    the watchdog's default, which is the one number no registry has an opinion about.
    """
    try:
        timeout = _codex_model.timeout_for(pin.model, pin.effort)
    except _codex_model.CodexModelError as exc:
        raise ConveneError(f"no codex ceiling for {pin.model} @ {pin.effort}: {exc}") from None
    ephemeral_flag = "--ephemeral " if ephemeral else ""
    return (
        f'python3 {_CODEX_WATCH} --mode codex --model {pin.model} --hard-cap {timeout} '
        f'--stdout-file {_STDOUT_SLOT} --stderr-file {_STDERR_SLOT} '
        f'-- codex exec {ephemeral_flag}-s read-only '
        f'{" ".join(pin.argv_fragment)} "{_PROMPT_SLOT}"'
    )


class _PolicyPin:
    """The placeholders guard_policy documents, so the policy text cannot drift from the real stack."""
    timeout = "<T>"
    argv_fragment = ("--model", "<slug>")


def agy_guard_stack(pin: Any) -> str:
    """`(d="$(mktemp -d)" && cd "$d" && timeout <T> agy --sandbox --mode plan --model <slug> -p "…" < /dev/null)`.

    Flags before -p, prompt last. `--mode plan` removes native writes and the empty cwd keeps a
    repo out of the workspace (#366, measured on agy 1.4.12): a seat's brief carries its content
    inline, so the seat needs neither. The directory is allocated and checked before the `cd`,
    because a `cd` on an empty mktemp result succeeds and would leave agy in a live repo. The subshell leaves the caller's cwd alone, so a chair's
    redirect after the stack still resolves against its own directory.
    """
    return (f'(d="$(mktemp -d)" && cd "$d" && timeout {pin.timeout} agy --sandbox --mode plan '
            f'{" ".join(pin.argv_fragment)} -p "{_PROMPT_SLOT}" < /dev/null)')


def claude_guard_stack(pin: Any, *, role: str, effort: str = "default") -> str:
    """The Claude seat label. Claude seats are host-native spawns, not a shell CLI, so this is
    a label the chair reads, naming the seat_model MODEL to spawn with (S081 §4.8) — not a
    command. `pin` is the seat_model.SeatPin for the seat's role."""
    return (f"(claude host seat · model={pin.model} via seat_model {role} · "
            f"effort={effort} · non-CLI spawn, timeout {pin.timeout}s)")


def materialise_call(provider: str, effort: str, *, is_arbiter: bool = False,
                     seat_weight: Optional[str] = None,
                     substitute_for: Optional[str] = None,
                     size: Optional[str] = None, project_root: Any = None,
                     declared_role: Optional[str] = None) -> Tuple[str, Any, str]:
    """(role, SeatPin, guard_stack) for one seat or arbiter call — ONE seat_model resolution.

    No codex seat runs `--ephemeral` (#302 design §3.4b, JC-3): TOP seats were already metered
    (I6), and from roster rev 3 the support-tier seats are too, so every codex call leaves a rollout
    and terra's drain can be read. Fail-closed.
    `substitute_for="codex"` pins a Claude member seat to CODEX_SUBSTITUTE_ROLE (J16).
    `size` / `project_root` size a codex or agy member seat (resolve_seat_pin; WP-D2, D17; agy #368).
    `declared_role` resolves a DECLARED arbiter on its declared role (resolve_seat_pin; WP-D3, D23).
    """
    if provider not in KNOWN_PROVIDERS:
        raise ConveneError(f"no guard stack for unknown provider {provider!r}")
    role, pin = resolve_seat_pin(provider, effort, is_arbiter=is_arbiter, seat_weight=seat_weight,
                                 substitute_for=substitute_for, size=size, project_root=project_root,
                                 declared_role=declared_role)
    if provider == "codex":
        stack = codex_guard_stack(pin, ephemeral=False)
    elif provider == "agy":
        stack = agy_guard_stack(pin)
    else:
        stack = claude_guard_stack(pin, role=role, effort=effort)
    return role, pin, stack


def persisted_provenance(pin: Any) -> Dict[str, Any]:
    """The `provenance` a materialised seat or arbiter carries (#282 r14, plan K16): a copy of the
    seat_model pin's PERSISTED_PROVENANCE_KEYS, plus PROVENANCE_FROZEN_SLUG when the pin's source is
    "freeze", plus each PERSISTED_OPTIONAL_PROVENANCE_KEYS key (#291 roster_rev) the pin carries. A substituted seat passes its CLAUDE pin, so it records the model that serves it.

    A copy, never a validation: a pin missing requested_selector, resolved_model or source (or a
    freeze pin without its slug) yields a null that the session-plan schema rejects, so
    build_session_plan fails CLOSED rather than freezing a plan that cannot say where its model came
    from. roster_fetched_at is the exception: null is its legal "no roster was read" value, and
    seat_model always sets the key.

    THE FREEZE RULE (#282 fix round 1 F15, plan K47; behaviour UNCHANGED, K14). A codex freeze is
    honoured UNVALIDATED when the roster is invalid: seat_model cannot check the frozen slug against
    a document it could not read, and it does not refuse on that account, because the freeze is the
    operator's EMERGENCY OVERRIDE — it is what restored gpt-6-astra during the 2026-09-15 priority
    tie, and a freeze that stopped working exactly when the roster broke would be useless at the one
    moment it is needed. Every NON-frozen codex path still fails closed on an invalid roster
    (ConveneError naming roster_invalid), so the exception is the freeze and nothing else. What
    changes here is only the RECORD: when the pin carries `roster_invalid`, the persisted provenance
    carries `roster_invalid: true`, so the plan says the freeze was honoured unvalidated instead of
    leaving a bare null `roster_fetched_at` to be guessed at. Absent otherwise (an event key).
    """
    source = pin.provenance.get("source")
    out: Dict[str, Any] = {key: pin.provenance.get(key) for key in PERSISTED_PROVENANCE_KEYS}
    for key in PERSISTED_OPTIONAL_PROVENANCE_KEYS:
        if key in pin.provenance:
            out[key] = pin.provenance[key]
    if source == PROVENANCE_SOURCE_FREEZE:
        out[PROVENANCE_FROZEN_SLUG] = pin.provenance.get(PROVENANCE_FROZEN_SLUG)
    if pin.provenance.get(PROVENANCE_ROSTER_INVALID):
        out[PROVENANCE_ROSTER_INVALID] = True
    return out


def call_timeout_s(provider: str, pin: Any) -> int:
    """The ceiling a materialised call carries: codex from codex_model.timeout_for (the single
    codex owner, as codex_guard_stack uses), agy and claude from the seat_model role row."""
    if provider == "codex":
        try:
            return int(_codex_model.timeout_for(pin.model, pin.effort))
        except _codex_model.CodexModelError as exc:
            raise ConveneError(f"no codex ceiling for {pin.model} @ {pin.effort}: {exc}") from None
    return int(pin.timeout)


def guard_stack_for(provider: str, effort: str, *, seat_class: Optional[str] = None,
                    is_arbiter: bool = False, is_ratification: bool = False,
                    seat_weight: Optional[str] = None) -> str:
    """The pinned guard stack for one seat or arbiter call (fail-closed).

    The ROLE is keyed on `is_arbiter` and, for every member SEAT, `seat_weight` (§4.8;
    amendment 3 D25/D26 brought codex seats under the weight rule). This helper names no seat, so
    a codex call made through it keeps CODEX_MEMBER_ROLE whatever weight it passes as None.
    `seat_class` and `is_ratification` do not change the stack: the seat-class already chose the
    EFFORT upstream (resolve_effort / _resolve_arbiter_effort — that is where the ratification
    arbiter's `max` comes from), and the ceiling follows from (model, effort) alone. They stay
    in the signature for callers.
    """
    return materialise_call(provider, effort, is_arbiter=is_arbiter, seat_weight=seat_weight)[2]


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
        # seat_weight (S081 §4.8): a top-level card field, overridable per profile seat entry.
        # A copy nested under `provider:` would be silently ignored, so it fails closed instead.
        if "seat_weight" in card_prov:
            raise ConveneError(
                f"seat '{ref}': seat_weight must be a top-level roster-card field, not under provider:"
            )
        declared_weight = entry["seat_weight"] if "seat_weight" in entry else card.get("seat_weight")
        if declared_weight is None and provider == "codex":
            # A CODEX seat defaults to the MAIN row (consultant_main: the codex TOP selector when amendment 3
            # wrote this, the codex std literal since the astra reserve), not to DEFAULT_SEAT_WEIGHT (D25/D26).
            # A codex seat that should take the SUPPORTING model class says so — `seat_weight: support`
            # on its profile entry or card — and every such seat in the shipped profiles does.
            # WHY THE DEFAULT IS NOT SHARED WITH agy/claude: defaulting codex to `support` moved EVERY
            # weightless codex seat onto the support-tier LITERAL, which is not a TOP selector — a
            # silent drop from TOP to the support model class (and, before #302 JC-3, to an unmetered
            # `--ephemeral` call). Amendment 3 changes COMPOSITION; it must not silently rewrite which
            # model a seat buys.
            declared_weight = SEAT_WEIGHT_MAIN
        seat_weight = validate_seat_weight(ref, declared_weight)
        resolved.append(
            {
                "seat_id": ref,
                "provider": provider,
                "effort": effort,
                "seat_class": seat_class,
                "effort_note": effort_note,
                "seat_weight": seat_weight,
                "adversarial_role": adversarial,
                "can_arbitrate": bool(card.get("can_arbitrate", False)),
                "fallback_ok": bool(card_prov.get("fallback_ok", False)),
                "overlay_type": overlay.get("type") if overlay else None,
            }
        )
    return resolved


# --------------------------------------------------------------------------- #
# Codex unavailable (amendment 1's "astra unavailable") -> plan-time Claude-main-tier substitution (S081 amendment 1 D6, item 4; J12, J16)
# --------------------------------------------------------------------------- #
def _codex_cli_missing() -> bool:
    """True when no `codex` binary is on PATH. shutil.which is an in-process PATH lookup (plan
    J12): no subprocess, and never the up-to-24h-stale inventory.json."""
    return shutil.which(CODEX_CLI) is None


def codex_unavailable_reason() -> Optional[str]:
    """The ONE plan-wide availability evaluation a plan build makes (J16), or None.

    Both checks run once: the binary (`cli_missing`, which outranks a quota token because no call
    could start at all — seat_model's `argv --use` order, J10) and codex_quota.unavailable()
    ("rate_limit_reached" / "quota_exhausted" from a FRESH rollout reading; stale or unknown is
    None). A threshold or a spent budget is NOT unavailability: the codex seat is admit-gated ONCE,
    at plan build, against the session id (S081 revision 4, WP-D2 — codex_admission), and such a
    refusal substitutes through that admission, never through this function. Never raises; no
    model call, socket or process.
    """
    missing = _codex_cli_missing()
    token = None
    if _codex_quota is not None:
        try:
            token = _codex_quota.unavailable()
        except Exception:  # noqa: BLE001 - unavailable() never raises; belt and braces
            token = None
    if missing:
        return UNAVAILABLE_CLI_MISSING
    return token


def _reseat_on_claude(seat: Dict[str, Any], reason: str, requested: Optional[str]) -> None:
    """The ONE substitution (J16), IN PLACE: see apply_codex_substitution for the contract."""
    effort, seat_class, note = resolve_effort(seat["seat_id"], CODEX_SUBSTITUTE_PROVIDER, seat["seat_class"])
    seat.update({
        "provider": CODEX_SUBSTITUTE_PROVIDER,
        "effort": effort,
        "seat_class": seat_class,
        "effort_note": note,
        "fallback_ok": True,
        "substitute_for": CODEX_SUBSTITUTE_FOR,
        "substitution_reason": reason,
        "requested_model": requested,
    })


#: The plan-time admission a build hands to apply_codex_substitution: (model_class, requested_model)
#: -> a codex_quota.admit() decision dict for this session. See codex_admission().
CodexAdmission = Callable[..., Dict[str, Any]]   # (model_class, requested_model, role, *, models, roles) -> decision


def apply_codex_substitution(
    seats: List[Dict[str, Any]], plan_reason: Optional[str], *,
    admission: Optional[CodexAdmission] = None, size: Optional[str] = None, project_root: Any = None,
) -> Tuple[Dict[int, Tuple[str, Any, str]], frozenset]:
    """Re-seat every codex member seat codex cannot serve on Claude, IN PLACE (J16).

    Runs on the resolved seats BEFORE validate_structural and resolve_arbiter. For each codex
    seat, in seat_model's `argv --use` order (J10):
      1. its codex pin, fail-closed. "No eligible TOP model for this effort"
         (NoEligibleCodexModelError) -> reason `no_eligible_model`, requested_model null. Any
         OTHER failure (an invalid freeze pin, an invalid codex roster — roster_invalid, #282
         R4 — an untabulated timeout, seat_model missing) is a broken resolver: the seat is left
         untouched and build_session_plan raises that same ConveneError later, at the point it
         always did — never a substitution;
      2. otherwise the plan-wide `plan_reason` (codex_unavailable_reason()), requested_model =
         the codex model the pin resolved;
      3. otherwise — S081 revision 4, WP-D2 — the PLAN-TIME ADMISSION, when `admission` is given:
         ONE decision per model class across the seats still standing (codex_quota budgets the two
         classes separately, D16): a single decision in each shipped profile since the astra reserve
         (every shipped codex seat is std-class), and ONE shared by every seat of a class
         (jc6), billed by the pin's resolving row (seat_model.pin_model_class, #302 R1) and naming
         every covered seat's model and role on the row (`models` / `roles`, #302). Every seat the
         decision covers carries its `admission_id`
         (null for a check-only decision). ADMITTED -> the seat stays codex. REFUSED -> the SAME
         substitution as 1-2, with the decision's reason (budget_spent,
         budget_store_unavailable, an unavailable token) and requested_model = the pin's model.
         A reason outside codex_quota.SUBSTITUTION_REASONS fails CLOSED (vocabulary drift).
    A substituted seat becomes provider claude, keeps its seat_id / seat_weight /
    adversarial_role / can_arbitrate / overlay_type, declares fallback_ok (the declared fallback
    that lets validate_structural pass a one-family plan), re-resolves its effort for claude
    through resolve_effort (an adversarial challenger_floor seat keeps the anti-sycophancy
    note), and records substitute_for / substitution_reason / requested_model. Its role is
    CODEX_SUBSTITUTE_ROLE whatever its seat_weight (materialise_call(substitute_for=...)).
    `size` / `project_root` size each codex member pin (D17; None = unsized).

    Returns (pre_resolved, unavailable_providers): the (role, pin, guard_stack) of every codex
    seat that stays codex (so the member loop does not resolve it twice), and the providers the
    arbiter must exclude — {"codex"} when a plan-wide reason exists or any seat was substituted
    (an admission refusal included, so the arbiter is recomputed exactly as amendment 1 describes).
    No budget row and no subprocess of its own: the only write it can cause is the one
    `admission` makes when the build records (and seat_model's usual seat-model-tops.json write).
    """
    pre_resolved: Dict[int, Tuple[str, Any, str]] = {}
    substituted = False
    for index, seat in enumerate(seats):
        if seat["provider"] != "codex":
            continue
        reason: Optional[str] = None
        requested: Optional[str] = None
        try:
            role, pin, stack = materialise_call(
                "codex", seat["effort"], is_arbiter=False, seat_weight=seat["seat_weight"],
                size=size, project_root=project_root)
        except NoEligibleCodexModelError:
            reason = UNAVAILABLE_NO_ELIGIBLE
        except ConveneError:
            continue  # broken resolver: fail closed later, never substitute (J10)
        else:
            if plan_reason is None:
                pre_resolved[index] = (role, pin, stack)
                continue
            reason, requested = plan_reason, pin.model
        _reseat_on_claude(seat, reason, requested)
        substituted = True
    if admission is not None and pre_resolved:
        # #302 (design §3.5, challenger #2; ruling R1): the class is billed by the pin's RESOLVING ROW
        # (seat_model.pin_model_class), and EVERY seat of a class is collected BEFORE its one admission
        # is decided, so the row names every model and role it covers — from roster rev 3 one std
        # admission can cover a sized std main seat AND a support-tier seat, two different models.
        # D21 fix round 2 (N3): the class is read ONCE per seat. pin_model_class reads the roster,
        # tops and pins files, so a concurrent rewrite between two reads could flip it: the seat
        # would then be gated by the OTHER class's admission, or index a class never decided.
        seat_class: Dict[int, str] = {index: _seat_model.pin_model_class(pre_resolved[index][1])
                                      for index in sorted(pre_resolved)}
        by_class: Dict[str, List[int]] = {}
        for index in sorted(pre_resolved):
            by_class.setdefault(seat_class[index], []).append(index)
        decisions: Dict[str, Dict[str, Any]] = {}
        for model_class, indices in by_class.items():
            # ONE admission per MODEL CLASS per session (jc6; codex_quota.BUDGET_LIMITS
            # {"top": 1, "std": 1}). Amendment 3 makes two classes reachable in one profile, so the
            # role recorded on the row is the class's FIRST seat's role, not a constant; `models`
            # (distinct, seat order) and `roles` (one per seat, seat order) attribute the rest.
            first_role, first_pin, _stack = pre_resolved[indices[0]]
            models = list(dict.fromkeys(pre_resolved[i][1].model for i in indices))
            roles = [pre_resolved[i][0] for i in indices]
            decisions[model_class] = admission(model_class, first_pin.model, first_role,
                                               models=models, roles=roles)
        for index in sorted(pre_resolved):
            _role, pin, _stack = pre_resolved[index]
            decision = decisions[seat_class[index]]
            seats[index][ADMISSION_ID_KEY] = decision.get("admission_id")
            if decision.get("admitted") is True:
                continue
            refusal = admission_refusal_reason(decision)
            del pre_resolved[index]
            _reseat_on_claude(seats[index], refusal, pin.model)
            substituted = True
    unavailable = frozenset({CODEX_SUBSTITUTE_FOR}) if (plan_reason is not None or substituted) else frozenset()
    return pre_resolved, unavailable


def admission_refusal_reason(decision: Dict[str, Any]) -> str:
    """The substitution reason a REFUSED admission carries — its own `reason`, which must be a
    codex_quota.SUBSTITUTION_REASONS member. Anything else is vocabulary drift between convene and
    codex_quota and fails CLOSED rather than recording a substitution nobody can read."""
    reason = decision.get("reason")
    if _codex_quota is None or reason not in _codex_quota.SUBSTITUTION_REASONS:
        raise ConveneError(
            f"the plan-time admission refused the codex seat with reason {reason!r}, which is not a "
            "substitution reason (codex_quota.SUBSTITUTION_REASONS) — fail-closed, no run, no spend")
    return str(reason)


def resolve_convene_size(size: Any, project_root: Any) -> Optional[Any]:
    """The size decision for this convene (S081 revision 4, WP-D2, D17), or None.

    None when the caller passed no size: D17's complex, which codex_quota records as size_source
    `default`, with NO .forge/size read (sizing is opt-in, exactly as in seat_model). A given size
    must be one of SIZES — an unknown value is a caller error, never a silent default — and then
    resolves through seat_model.resolve_size (L7, in its one place) under `project_root`, so inside
    a forge cycle forge's own size wins and a conflict takes the larger.
    """
    if size is None:
        return None
    if not isinstance(size, str) or size not in SIZES:
        raise ConveneError(f"unknown size {size!r} (known: {', '.join(SIZES) or 'none — the harness failed to import'}) "
                           "— a usage error, never a silent default; no run, no spend")
    if _seat_model is None:
        raise ConveneError(f"cannot resolve size {size!r}: skills/_meta/seat_model.py is unavailable "
                           f"({_SEAT_MODEL_IMPORT_ERROR}) — fail-closed, no run, no spend")
    try:
        return _seat_model.resolve_size(size, project_root=project_root)
    except _seat_model.SeatModelError as exc:
        raise ConveneError(f"cannot resolve size {size!r}: {exc} — fail-closed, no run, no spend") from None


def codex_admission(session_id: str, *, project_root: Any, size_decision: Optional[Any],
                    record: bool) -> CodexAdmission:
    """The plan-time admission for ONE session (S081 revision 4, WP-D2; design §3.4, §2.2).

    Returns the callable apply_codex_substitution calls with (model_class, requested_model, role,
    models=, roles=) — `models` / `roles` (#302) name every seat the class's one admission covers. It runs
    codex_quota.admit IN-PROCESS — the CLI is check-only by design and cannot record — with use
    `deliberation`, the SESSION id as the key (plan L9), the member seat's role, the size the caller
    resolved (None = the back-compat complex / `default`) and `record`: True only on main()'s persisted
    path, False (CHECK-ONLY: no row, no store, no .lock, admission_id null) for --dry-run and for a
    bare build. A caller bug (ValueError) is a fail-closed ConveneError; environment failures never
    raise — codex_quota turns an unwritable store into the refusal `budget_store_unavailable`.
    """
    def decide(model_class: str, requested_model: str,
               role: str = WEIGHTED_MEMBER_ROLES[SEAT_WEIGHT_MAIN], *,
               models: Optional[List[str]] = None, roles: Optional[List[str]] = None) -> Dict[str, Any]:
        if _codex_quota is None:
            raise ConveneError(f"cannot admit the codex seat: skills/_meta/codex_quota.py is unavailable "
                               f"({_SEAT_MODEL_IMPORT_ERROR}) — fail-closed, no run, no spend")
        try:
            return _codex_quota.admit(
                CODEX_ADMISSION_USE, session_id, project_root=project_root,
                size=None if size_decision is None else size_decision.size,
                size_source=None if size_decision is None else size_decision.size_source,
                requested_by=None if size_decision is None else size_decision.requested_by,
                model_class=model_class, requested_model=requested_model, role=role,
                models=models, roles=roles, record=record)
        except ValueError as exc:
            raise ConveneError(f"the plan-time admission rejected its own call: {exc} — fail-closed, "
                               "no run, no spend") from None
    return decide


def codex_substitution_review_line(plan: Dict[str, Any]) -> Optional[str]:
    """The ONE pre-spend review line for a plan with substituted seats, else None.

    `codex unavailable (<reason>): <seats> served by claude/<model> — provider gap: openai; arbiter recomputed`
    Distinct reasons and models are listed in seat order.
    """
    subs = [s for s in plan.get("seats", []) if s.get("substitute_for") == CODEX_SUBSTITUTE_FOR]
    if not subs:
        return None
    reasons = list(dict.fromkeys(str(s.get("substitution_reason")) for s in subs))
    models = list(dict.fromkeys(str(s.get("model")) for s in subs))
    seat_ids = ", ".join(str(s["seat_id"]) for s in subs)
    served = ", ".join(f"{CODEX_SUBSTITUTE_PROVIDER}/{m}" for m in models)
    return (f"codex unavailable ({', '.join(reasons)}): {seat_ids} served by {served} "
            f"— provider gap: {CODEX_PROVIDER_GAP}; arbiter recomputed")


def codex_quota_wait_line(plan: Dict[str, Any], wait: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """#322 fix round 1 (item 11): the ONE pre-spend review line that turns a QUOTA substitution into the
    #322 rule -- notify, wait up to 30 minutes, then stand in -- instead of an instant stand-in. None when
    no codex seat was substituted for quota (rate_limit_reached / quota_exhausted).

    `wait` is codex_quota.quota_wait_now() (the reset fields); None -> read now. A meter that no longer
    names a reset prints `resets_in_s unknown` and `wait_advice notify`. The lead acts on it BEFORE the
    persisted convene: with `notify`, `codex_quota.py notify-claim` and on its exit 0 push the notification;
    then `codex_quota.py await-reset --cycle-id <session id>` in a BACKGROUND call; exit 0 -> re-run the
    --dry-run once (codex seats back on codex); any other exit -> convene as planned (the Claude stand-in)."""
    quota = getattr(_codex_quota, "QUOTA_REFUSAL_REASONS", frozenset({"rate_limit_reached", "quota_exhausted"}))
    subs = [s for s in plan.get("seats", [])
            if s.get("substitute_for") == CODEX_SUBSTITUTE_FOR and s.get("substitution_reason") in quota]
    if not subs:
        return None
    if wait is None and _codex_quota is not None:
        try:
            wait = _codex_quota.quota_wait_now()
        except Exception:  # noqa: BLE001 - quota_wait_now never raises; belt and braces
            wait = None
    wait = wait or {}
    reasons = ", ".join(dict.fromkeys(str(s.get("substitution_reason")) for s in subs))
    resets_in = wait.get("resets_in_s")
    return (f"CODEX_QUOTA_WAIT: avengers {plan.get('session_id')} (reason {reasons}; "
            f"wait_advice {wait.get('wait_advice') or 'notify'}; "
            f"resets_in_s {'unknown' if resets_in is None else resets_in}; "
            f"seats {', '.join(str(s['seat_id']) for s in subs)}) — before spending: notify-claim + notify "
            f"(when notify), await-reset --cycle-id {plan.get('session_id')} in the background, re-run this "
            f"--dry-run once on exit 0; otherwise convene with the stand-in")


def record_codex_substitutions(plan: Dict[str, Any], *, project_root: Path,
                               size: Optional[str] = None) -> List[Dict[str, Any]]:
    """Write one `deliberation` substitution row per substituted seat (main()'s persisted path ONLY).

    Each row goes through seat_model.substitute(CODEX_SUBSTITUTE_ROLE, "deliberation", reason,
    project_root, requested_model) — the single owner of the substitution contract (TOP role,
    never a gpt model) — into ~/.claude/projects/<slug>/astra-budget.jsonl. A substitution row
    never spends a budget. Never raises: a failure is returned per seat (the seat is still served
    by Claude, as frozen).

    S081 revision 4, WP-D2 (plan L9, design §2.2): the row is keyed on the plan's SESSION id — the
    key the seat's own admission uses — not on project_root/.forge/cycle-id, so a substitution and
    the admission it followed share (key, use) and the seat's `admission_id` names that admission.
    The row itself names no admission (`admission_id` None): a refusal replaces none, per
    codex_quota.record_substitution's contract. `size` is the caller's `--size` (None = the
    back-compat complex / `default`), so the row records WHICH SIZE of seat was substituted.
    """
    results: List[Dict[str, Any]] = []
    for seat in plan.get("seats", []):
        if seat.get("substitute_for") != CODEX_SUBSTITUTE_FOR:
            continue
        result: Dict[str, Any] = {"seat_id": seat["seat_id"], "row_written": False, "error": None}
        try:
            if _seat_model is None:
                raise ConveneError(f"skills/_meta/seat_model.py is unavailable ({_SEAT_MODEL_IMPORT_ERROR})")
            size_decision = resolve_convene_size(size, Path(project_root))
            pin = _seat_model.substitute(
                CODEX_SUBSTITUTE_ROLE, CODEX_SUBSTITUTION_USE, seat["substitution_reason"],
                project_root=Path(project_root), requested_model=seat.get("requested_model"),
                cycle_id=plan["session_id"],
                size=None if size_decision is None else size_decision.size,
                size_source=None if size_decision is None else size_decision.size_source,
                requested_by=None if size_decision is None else size_decision.requested_by)
            result["row_written"] = bool(pin.provenance.get("row_written"))
            if not result["row_written"]:
                result["error"] = str(pin.provenance.get("row_error") or "the substitution row was not written")
        except Exception as exc:  # noqa: BLE001 - reported per seat, never blocks the session
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


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


def _select_arbiter_provider(
    deliberation_providers: Any, adversarial_providers: Any, excluded: frozenset, priors: Dict[str, Any],
) -> Tuple[str, str]:
    """(path, provider) for the external arbiter — the CLEAN path, else the FALLBACK path — with
    `excluded` providers removed from both. Raises ConveneError when nothing remains.

    ARBITER_INELIGIBLE_PROVIDERS (agy) are barred too, but ONLY in a HEALTHY session — one where
    nothing is `excluded`. A session that has already lost a provider keeps them as the last-resort
    arbiter rather than failing closed; see the constant's note for the measurement behind that.
    """
    barred = excluded if excluded else (excluded | ARBITER_INELIGIBLE_PROVIDERS)
    clean_candidates = sorted(KNOWN_PROVIDERS - set(deliberation_providers) - barred)
    if clean_candidates:
        return "clean", _best_adjudication_provider(clean_candidates, priors)
    fallback_candidates = sorted(set(deliberation_providers) - set(adversarial_providers) - barred)
    if not fallback_candidates:
        if excluded:
            raise ConveneError(
                "arbiter constraint unsatisfiable: no available provider is free of deliberation "
                f"(unavailable {sorted(excluded)}) AND every available deliberation provider is "
                f"adversarial {sorted(adversarial_providers)} — no non-adversarial external arbiter "
                "remains (design §4, S081 amendment 1 D6 — fail CLOSED, no run, no spend)"
            )
        raise ConveneError(
            "arbiter constraint unsatisfiable: every provider deliberated AND every "
            f"deliberation provider is adversarial {sorted(adversarial_providers)} — an "
            "all-adversarial profile has no non-adversarial external arbiter (design §4 — "
            "fail CLOSED, no run, no spend)"
        )
    return "fallback", _best_adjudication_provider(fallback_candidates, priors)


def _no_eligible_arbiter_exclusion(provider: str, effort: str, exc: NoEligibleCodexModelError) -> str:
    """#282 R8 (plan K15): the constraint note for excluding an arbiter provider whose roster lists no
    eligible model for the arbiter's effort, before the ONE recompute. `exc` is the pin's error."""
    return (f"{provider} excluded after the arbiter pin found no eligible {provider} model for effort "
            f"{effort!r} ({exc.unavailable_reason}); arbiter selection recomputed once")


def declared_arbiter(profile: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The profile's DECLARED (D23) arbiter as {provider, role, independence}, or None. FAIL-CLOSED.

    Validates the arbiter block against the closed ARBITER_BLOCK_KEYS vocabulary and the declaration as a
    whole: `arbiter_independence` is a TOP-LEVEL key whose only value is `separate-session`, and it comes with
    BOTH `arbiter.provider` (a known provider) and `arbiter.role` (one of DECLARED_ARBITER_ROLES) or not at
    all. Anything else raises ConveneError before a single seat resolves — in particular a provider / role
    without arbiter_independence, which would otherwise be silently ignored. Pure: no seat_model call.
    """
    arb_cfg = profile.get("arbiter")
    if arb_cfg is None:
        arb_cfg = {}
    if not isinstance(arb_cfg, dict):
        raise ConveneError(f"profile arbiter block must be a mapping, got {type(arb_cfg).__name__} "
                           "— fail-closed, no run, no spend")
    unknown = sorted(str(key) for key in arb_cfg if key not in ARBITER_BLOCK_KEYS)
    if unknown:
        hint = (f" ({ARBITER_INDEPENDENCE_KEY} is a TOP-LEVEL profile key, not an arbiter-block key)"
                if ARBITER_INDEPENDENCE_KEY in unknown else "")
        raise ConveneError(f"profile arbiter block has unknown key(s) {unknown} (known: {sorted(ARBITER_BLOCK_KEYS)})"
                           f"{hint} — fail-closed, no run, no spend")
    independence = profile.get(ARBITER_INDEPENDENCE_KEY)
    named = [key for key in ARBITER_DECLARATION_KEYS if key in arb_cfg]
    if independence is None and not named:
        return None
    if independence is None:
        raise ConveneError(
            f"profile declares arbiter {named} without {ARBITER_INDEPENDENCE_KEY}: the declaration would be "
            "silently IGNORED and the selection algorithm would seat the arbiter instead (design §3.4, D23) "
            "— fail-closed, no run, no spend")
    if not isinstance(independence, str) or independence not in ARBITER_INDEPENDENCE_VALUES:
        raise ConveneError(f"unknown {ARBITER_INDEPENDENCE_KEY} {independence!r} "
                           f"(known: {sorted(ARBITER_INDEPENDENCE_VALUES)}) — fail-closed, no run, no spend")
    if len(named) != len(ARBITER_DECLARATION_KEYS):
        raise ConveneError(f"{ARBITER_INDEPENDENCE_KEY}: {independence} needs BOTH arbiter.provider and "
                           f"arbiter.role (got {named}) — fail-closed, no run, no spend")
    provider, role = arb_cfg["provider"], arb_cfg["role"]
    if not isinstance(provider, str) or provider not in KNOWN_PROVIDERS:
        raise ConveneError(f"declared arbiter provider {provider!r} is not a known provider "
                           f"(known: {sorted(KNOWN_PROVIDERS)}) — fail-closed, no run, no spend")
    if not isinstance(role, str) or role not in DECLARED_ARBITER_ROLES:
        raise ConveneError(f"declared arbiter role {role!r} is not one convene resolves "
                           f"(known: {sorted(DECLARED_ARBITER_ROLES)}) — fail-closed, no run, no spend")
    return {"provider": provider, "role": role, "independence": independence}


def model_identity(provider: str, model: Any) -> str:
    """The MODEL a resolved slug names, for the D23 relaxed rule: lower-cased, and for agy with the reasoning
    level stripped (`gemini-4-argon-high` and `gemini-4-argon-medium` are one model at two levels, whatever
    family model_roster.AGY_FAMILY names)."""
    text = str(model).strip().lower()
    return _AGY_LEVEL_SUFFIX.sub("", text) if provider == "agy" else text


def _resolve_declared_arbiter(
    declared: Dict[str, str], profile: Dict[str, Any], seats: List[Dict[str, Any]], *,
    is_ratification: bool, unavailable: frozenset, deliberation_providers: Any, adversarial_providers: Any,
) -> Dict[str, Any]:
    """Resolve a DECLARED (D23) arbiter and enforce the RELAXED rule. See resolve_arbiter."""
    provider, role, independence = declared["provider"], declared["role"], declared["independence"]
    if provider in unavailable:
        raise ConveneError(
            f"declared arbiter provider {provider!r} is unavailable at plan build (unavailable {sorted(unavailable)}); "
            "a declared arbiter is never silently replaced by the selection algorithm (design §3.4, D23) "
            "— fail-closed, no run, no spend")
    unpinned = sorted(str(s.get("seat_id")) for s in seats if not s.get("model"))
    if unpinned:
        raise ConveneError(
            f"{ARBITER_INDEPENDENCE_KEY}: {independence} compares MODELS, but member seat(s) {unpinned} carry no "
            "resolved model — the member seats must be materialised before a declared arbiter "
            "— fail-closed, no run, no spend")
    arb_cfg = profile.get("arbiter", {}) or {}
    effort, seat_class = _resolve_arbiter_effort(provider, is_ratification, arb_cfg)
    try:
        role, pin, guard = materialise_call(provider, effort, is_arbiter=True, declared_role=role)
    except NoEligibleCodexModelError as exc:
        raise ConveneError(f"declared arbiter {provider} via seat_model {role} has no eligible model ({exc}); a "
                           "declared arbiter is never recomputed — fail-closed, no run, no spend") from None
    arbiter_model = model_identity(provider, pin.model)
    shared = sorted(str(s["seat_id"]) for s in seats if model_identity(s["provider"], s["model"]) == arbiter_model)
    if shared:
        raise ConveneError(
            f"declared arbiter {provider} via seat_model {role} resolves {pin.model!r}, the same model as member "
            f"seat(s) {shared}: {ARBITER_INDEPENDENCE_KEY}: {independence} requires the arbiter's MODEL to differ "
            "from every seat's model (design §3.4, D23 — the relaxed rule) — fail-closed, no run, no spend")
    if provider == "claude":
        if not guard.endswith(")"):
            raise ConveneError(f"unexpected claude arbiter label shape: {guard!r}")
        guard = f"{guard[:-1]} · {SEPARATE_SESSION_LABEL})"
    _eff, _cls, effort_note = resolve_effort("<arbiter>", provider, seat_class, model=pin.model)
    seat_models = sorted({str(s["model"]) for s in seats})
    path = "fallback" if provider in set(deliberation_providers) else "clean"
    if path == "clean":
        excluded = (f"declared arbiter — {provider!r} is used by NO deliberation seat; authorship linkage "
                    "total-excluded (no residual)")
    else:
        excluded = (f"declared arbiter — {provider!r} deliberated, so its authorship is ANONYMIZED and "
                    "style-recognition self-preference stays an ACCEPTED residual (flagged fallback_arbiter_residual "
                    f"in run-record.json §6a); its model {pin.model!r} is no seat's model and it runs in its own session")
    constraint = (
        f"declared external arbiter ({ARBITER_INDEPENDENCE_KEY}: {independence}; design §3.4 D23): {provider} via "
        f"seat_model {role} -> {pin.model}, in a SEPARATE SESSION; model {pin.model} != every deliberation seat's "
        f"model {seat_models}; the provider-exclusion rule is relaxed for this profile "
        f"(adversarial={sorted(adversarial_providers)})")
    if unavailable:
        constraint += f"; unavailable at plan build: {sorted(unavailable)}"
    return {
        "is_external": True,
        "cold_context": True,
        "path": path,
        "provider": provider,
        "effort": effort,
        "seat_class": seat_class,
        "effort_note": effort_note,
        "model": pin.model,
        "seat_model_role": role,
        "timeout_s": call_timeout_s(provider, pin),
        "guard_stack": guard,
        "fallback_arbiter_residual": path == "fallback",
        "excluded_authorship": excluded,
        "constraint": constraint,
        "provenance": persisted_provenance(pin),
        "selection": DECLARED_ARBITER_SELECTION,
        "independence": independence,
        "obligations": list(DECLARED_ARBITER_OBLIGATIONS),
    }


def resolve_arbiter(
    profile: Dict[str, Any], seats: List[Dict[str, Any]], *,
    is_ratification: bool, priors: Optional[Dict[str, Any]] = None,
    unavailable_providers: Optional[Any] = None,
) -> Dict[str, Any]:
    """Resolve the EXTERNAL, SEATLESS, cold-context arbiter (design §4, WP-2).

    The arbiter is a FRESH persona-free CALL — it did NOT file a position, argue,
    or ballot; it is NOT a promoted seat. Its provider is selected (never inherited
    from a seat) by precedence:
      * CLEAN path  — an ELIGIBLE provider (neither excluded, below, nor barred by
        ARBITER_INELIGIBLE_PROVIDERS — see _select_arbiter_provider) used by NO
        deliberation seat: genuinely external, authorship-linkage total-excluded, no residual.
      * FALLBACK path — no eligible provider is free of deliberation: the
        strongest-adjudication-prior NON-adversarial provider, cold-context.
        Authorship is anonymized but style-recognition self-preference is an
        ACCEPTED, DOCUMENTED residual (arXiv 2410.21819), RECORDED as
        `fallback_arbiter_residual` (§6a). In a healthy session coding-ratification
        lands here (all three provider families deliberate since #368, and agy is
        barred); under any codex refusal its arbiter is agy on the fallback path
        (agy deliberates since #368; the clean path while it held no seat).
      * ALL-ADVERSARIAL — every eligible provider deliberated AND every one is adversarial:
        no non-adversarial arbiter exists -> fail CLOSED (the only unsatisfiable
        arbiter case; never hangs).

    `can_arbitrate` is INERT under v2 — no seat is ever the adjudicator (design §5).
    The arbiter object DROPS `seat`; ADDS {is_external, cold_context, path}; KEEPS
    {provider, effort, guard_stack}. S081 WP-102 adds the resolved {model, seat_model_role,
    timeout_s, effort_note}: the arbiter resolves the seat_model `arbiter` role for every
    provider (a Claude arbiter is the Claude main tier, 1200s). #282 r14 adds `provenance`
    (persisted_provenance of the pin that serves the arbiter, after any recompute).

    `unavailable_providers` (S081 amendment 1 D6, plan J16; default none) names providers that
    cannot serve a call when the plan is built — today only codex, when codex is unavailable. They
    are excluded from BOTH paths; if nothing remains the arbiter fails CLOSED (ConveneError).

    NO ELIGIBLE ARBITER MODEL (#282 R8, plan K15). When the chosen provider's pin raises
    NoEligibleCodexModelError (codex, whose roster lists no eligible TOP for the arbiter's
    effort — reachable when no codex member seat was evaluated at plan build, or when the
    arbiter's `max` differs from the members' effort), that provider joins the excluded set and
    the selection is recomputed ONCE, clean then fallback; the `constraint` text names the
    exclusion. Nothing left -> ConveneError, as above. A broken resolver or an invalid codex
    roster (roster_invalid) is a plain ConveneError and is never recomputed. No budget row.

    A DECLARED ARBITER (S081 revision 4, WP-D3; design §3.4 D23, plan L6). When the profile declares
    `arbiter: {provider, role}` with `arbiter_independence: separate-session` (declared_arbiter), NOTHING
    above selects: the declared provider is pinned on its declared seat_model role, and the provider-exclusion
    rule is replaced by the RELAXED rule — the arbiter's MODEL (model_identity) differs from every member
    seat's model, and it runs in its OWN SESSION (the Claude label carries SEPARATE_SESSION_LABEL). The seats
    must therefore carry `model` (build_session_plan materialises them first for such a profile). A shared
    model, an unmaterialised seat, a declared provider in `unavailable_providers` or a declared codex arbiter
    with no eligible model fails CLOSED: a declared arbiter is never recomputed and never silently replaced
    by the selection. `path` still says whether the provider deliberated (clean / fallback, with the residual
    flagged), and the object adds {selection: declared, independence, obligations}.
    Without a declaration the object is byte-for-byte what it was before WP-D3.
    """
    priors = priors or load_capability_priors()
    unavailable = frozenset(unavailable_providers or ())
    unknown = sorted(str(p) for p in unavailable - KNOWN_PROVIDERS)
    if unknown:
        raise ConveneError(f"unavailable_providers names unknown provider(s) {unknown} (known: {sorted(KNOWN_PROVIDERS)})")
    deliberation_providers = {s["provider"] for s in seats}           # ALL seats deliberate
    adversarial_providers = {s["provider"] for s in seats if s["adversarial_role"]}
    declared = declared_arbiter(profile)
    if declared is not None:
        return _resolve_declared_arbiter(declared, profile, seats, is_ratification=is_ratification,
                                         unavailable=unavailable, deliberation_providers=deliberation_providers,
                                         adversarial_providers=adversarial_providers)

    excluded_providers = unavailable
    path, provider = _select_arbiter_provider(deliberation_providers, adversarial_providers, excluded_providers, priors)
    arb_cfg = profile.get("arbiter", {}) or {}
    effort, seat_class = _resolve_arbiter_effort(provider, is_ratification, arb_cfg)
    recompute_note: Optional[str] = None
    try:
        role, pin, guard = materialise_call(provider, effort, is_arbiter=True)
    except NoEligibleCodexModelError as exc:
        # #282 R8 (plan K15): the chosen provider has no eligible model for the arbiter's effort
        # (only codex raises this). Exclude it and recompute the selection ONCE — clean, then
        # fallback. Nothing left -> the ConveneError above. No budget row: no seat was substituted.
        # Any other resolution failure (a broken resolver, an invalid roster) is never recomputed.
        recompute_note = _no_eligible_arbiter_exclusion(provider, effort, exc)
        excluded_providers = excluded_providers | {provider}
        path, provider = _select_arbiter_provider(deliberation_providers, adversarial_providers, excluded_providers,
                                                  priors)
        effort, seat_class = _resolve_arbiter_effort(provider, is_ratification, arb_cfg)
        role, pin, guard = materialise_call(provider, effort, is_arbiter=True)
    # M6 call site: the model is known now, so the advisory note can be looked up (a codex
    # ratification arbiter off the measured model records its `max` ceiling as PROVISIONAL).
    _eff, _cls, effort_note = resolve_effort("<arbiter>", provider, seat_class, model=pin.model)
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
            f"all {'available ' if excluded_providers else ''}providers deliberated -> fallback path (accepted residual)"
        )
    if unavailable:
        constraint += f"; unavailable at plan build, excluded from both paths: {sorted(unavailable)}"
    if recompute_note is not None:
        constraint += f"; {recompute_note}"
    return {
        "is_external": True,
        "cold_context": True,
        "path": path,
        "provider": provider,
        "effort": effort,
        "seat_class": seat_class,
        "effort_note": effort_note,
        "model": pin.model,
        "seat_model_role": role,
        "timeout_s": call_timeout_s(provider, pin),
        "guard_stack": guard,
        "fallback_arbiter_residual": path == "fallback",
        "excluded_authorship": excluded,
        "constraint": constraint,
        "provenance": persisted_provenance(pin),   # #282 r14: the arbiter pin's, recompute included
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


def wall_clock_budget(
    seats: List[Dict[str, Any]], arbiter: Dict[str, Any], *,
    requested: Any, requested_from: str,
) -> Tuple[int, Dict[str, Any]]:
    """The session wall-clock budget and its derivation (S081 I12; the S080 H2 formula).

    floor = the arbiter call's timeout + WALL_CLOCK_FLOOR_MEMBER_TURNS x the slowest EXTERNAL
    (codex / agy) member seat's timeout — the budget must hold the arbiter call it authorises and
    two turns of its slowest CLI seat. A plan with no external member seat uses its slowest
    Claude member seat instead, so it still budgets two turns. Every timeout is the resolved
    ceiling (`timeout_s`, set at materialisation).

    A requested value (caller request, else profile) below the floor is RAISED to it and the
    returned record carries a note naming both values; a value at or above the floor is kept
    unchanged; no requested value -> the floor. A non-integer request fails CLOSED.
    Returns (effective_wall_clock_s, record).
    """
    arbiter_timeout = int(arbiter["timeout_s"])
    external = [int(s["timeout_s"]) for s in seats if s["provider"] in ("codex", "agy")]
    if external:
        member_timeout, member_basis = max(external), "slowest external (codex/agy) member seat"
    else:
        member_timeout = max(int(s["timeout_s"]) for s in seats)
        member_basis = "slowest member seat (no external member seat in this plan)"
    floor = arbiter_timeout + WALL_CLOCK_FLOOR_MEMBER_TURNS * member_timeout
    formula = (f"arbiter timeout {arbiter_timeout}s + {WALL_CLOCK_FLOOR_MEMBER_TURNS} x "
               f"{member_basis} {member_timeout}s = {floor}s")
    note = None
    if requested is None:
        effective = floor
    else:
        if isinstance(requested, bool) or not isinstance(requested, int):
            raise ConveneError(
                f"budgets.wall_clock_s must be an integer number of seconds, got {requested!r} "
                f"(from {requested_from}) — fail-closed, no run, no spend"
            )
        if requested < floor:
            effective = floor
            note = (f"wall_clock_s {requested} (from {requested_from}) is below the derived floor "
                    f"{floor} ({formula}); raised to {floor}")
        else:
            effective = requested
    record = {
        "floor_s": floor,
        "arbiter_timeout_s": arbiter_timeout,
        "member_seat_timeout_s": member_timeout,
        "member_turns": WALL_CLOCK_FLOOR_MEMBER_TURNS,
        "member_basis": member_basis,
        "formula": formula,
        "requested_s": requested,
        "requested_from": requested_from,
        "effective_s": effective,
        "raised": note is not None,
        "note": note,
    }
    return effective, record


def build_session_plan(
    contract: Dict[str, Any],
    *,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
    roster_dir: Path = DEFAULT_ROSTER_DIR,
    session_id: Optional[str] = None,
    now: Optional[_dt.datetime] = None,
    size: Optional[str] = None,
    project_root: Any = None,
    record_admission: bool = False,
) -> Dict[str, Any]:
    """Resolve + validate + materialize the flat JSON session-plan. Raises
    ConveneError (fail-closed) on any structural problem — no spend.

    S081 revision 4, WP-D2: the codex member seat is ADMITTED here, against the session id, before
    the structural validate and the arbiter (see apply_codex_substitution / codex_admission).
    `record_admission` is False by default — a bare build and --dry-run decide CHECK-ONLY and write
    nothing; only main()'s persisted path passes True. That path records HERE, before the build's
    later fail-closed checks, so a build that fails after the admission keeps its row and a retry
    with the SAME session id is refused budget_spent (convene-contract.md, Honest limits; recording
    only after the last check is filed for revision 5, D21 f4). `project_root` names the budget
    store (and, with a `size`, the forge cycle whose .forge/size applies); None means the working
    directory, exactly as main()'s --project-root default. `size` is D17's (None = complex, `default`)."""
    family = contract.get("profile") or contract.get("task_family")
    if not family:
        raise ConveneError("contract must specify 'profile' or 'task_family'")
    task = contract.get("task") or contract.get("decision") or ""
    root = Path(project_root) if project_root is not None else Path.cwd()
    size_decision = resolve_convene_size(size, root)

    profile, profile_path, prof_sha = load_profile(profiles_dir, family)
    # S081 revision 4, WP-D3 (D23): the arbiter vocabulary and any declaration are validated here, before a
    # seat resolves or the codex seat is admitted, so a malformed declaration spends and records nothing.
    declared = declared_arbiter(profile)
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
    # wall_clock_s is settled after the seats resolve (it depends on their timeouts).

    seats = resolve_seats(profile, roster_dir, roster_override=contract.get("roster_override"))
    # S081 revision 4, WP-D2: the session id is minted HERE, before the substitution, because the codex
    # seat is admitted against it. The expression is moved verbatim — same inputs, same value.
    sid = session_id or make_session_id(task or family, now=now)
    # Codex unavailable (amendment 1's "astra unavailable") -> plan-time Claude-main-tier substitution (S081 amendment 1 D6, J16): ONE availability
    # evaluation for the whole build, then every codex seat codex cannot serve — or that the session's
    # plan-time admission refuses (WP-D2) — is re-seated on Claude BEFORE the structural validate and
    # the arbiter (which then excludes codex).
    pre_resolved, unavailable_providers = apply_codex_substitution(
        seats, codex_unavailable_reason(),
        admission=codex_admission(sid, project_root=root, size_decision=size_decision, record=record_admission),
        size=size, project_root=root)
    quorum = validate_structural(seats)
    priors = load_capability_priors()
    # A DECLARED arbiter (WP-D3, D23) is checked against the member seats' MODELS, so for that profile the
    # arbiter resolves AFTER the seats are materialised below; every other profile keeps this order.
    arbiter = (None if declared is not None else
               resolve_arbiter(profile, seats, is_ratification=is_ratification, priors=priors,
                               unavailable_providers=unavailable_providers))

    # Materialise every member seat through seat_model (one resolution each): its role by
    # provider + seat_weight (a substituted seat: CODEX_SUBSTITUTE_ROLE), the MODEL, the ceiling and
    # the guard stack. A codex seat already resolved by apply_codex_substitution is reused, not
    # resolved again. M6 call site: with the model known, the effort note is re-derived so a
    # measured / provisional note is recorded.
    for index, s in enumerate(seats):
        if index in pre_resolved:
            role, pin, stack = pre_resolved[index]
        else:
            # the SAME size as apply_codex_substitution used, so a codex seat it could not pin re-raises
            # the sized error rather than quietly resolving unsized here (non-codex seats ignore it)
            role, pin, stack = materialise_call(
                s["provider"], s["effort"], is_arbiter=False, seat_weight=s["seat_weight"],
                substitute_for=s.get("substitute_for"), size=size, project_root=root)
        if s.get("substitute_for") is not None and str(pin.model).lower().startswith("gpt-"):
            raise ConveneError(
                f"seat '{s['seat_id']}': refusing to substitute codex with {pin.model!r} — a gpt model "
                "draws the same quota (S081 amendment 1 D6) — fail-closed, no run, no spend")
        _eff, _cls, s["effort_note"] = resolve_effort(
            s["seat_id"], s["provider"], s["seat_class"], model=pin.model)
        s["model"] = pin.model
        s["seat_model_role"] = role
        s["timeout_s"] = call_timeout_s(s["provider"], pin)
        s["guard_stack"] = stack
        # #282 r14: the pin's persisted provenance; a substituted seat's is its Claude pin's.
        s["provenance"] = persisted_provenance(pin)
    if arbiter is None:
        arbiter = resolve_arbiter(profile, seats, is_ratification=is_ratification, priors=priors,
                                  unavailable_providers=unavailable_providers)

    if caller_budget.get("wall_clock_s") is not None:
        requested_from = "caller_request"
    elif "wall_clock_s" in budgets:
        requested_from = "profile"
    else:
        requested_from = "none"
    budgets["wall_clock_s"], wall_clock_floor = wall_clock_budget(
        seats, arbiter, requested=budgets.get("wall_clock_s"), requested_from=requested_from)

    outcome_type = _resolve_outcome(profile, contract)
    created =(now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        "wall_clock_floor": wall_clock_floor,
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
            "codex": (
                "timeout <T> codex exec -s read-only -m <slug> (metered: no codex seat runs ephemeral, #302) "
                "-c model_reasoning_effort=<tier> \"…\" < /dev/null  "
                "(slug: seat_model.py; T: codex_model.timeout_for(slug, tier))"
            ),
            "agy": (
                agy_guard_stack(_PolicyPin) +
                "  (slug: seat_model.py, the agy family rule; T: the seat_model role row)"
            ),
            "claude": (
                "(claude host seat · model=<alias> via seat_model <role> · effort=<tier> · non-CLI spawn, "
                "timeout <T>s)  (alias and T: the seat_model role row; the chair spawns with that model)"
            ),
            "model_resolution": (
                "skills/_meta/seat_model.py, fail-closed: every member seat consultant_main when "
                "seat_weight is main, else consultant_support; "
                "the arbiter `arbiter` (any provider)"
            ),
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
    wc = plan.get("wall_clock_floor") or {}
    if wc:
        lines.append(f"          wall-clock floor: {wc['formula']}")
        if wc.get("note"):
            lines.append(f"          note : {wc['note']}")
    q = plan["quorum"]
    lines.append(
        f"quorum  : {q['member_seats']} member seats · {q['families_count']} provider families "
        f"{{{','.join(q['provider_families'])}}} · floor {'met' if q['floor_met'] else 'NOT met'}"
        + ("  (relaxed via declared fallback)" if q.get("fallback_relaxed") else "")
    )
    substitution = codex_substitution_review_line(plan)
    if substitution:
        lines.append(substitution)
    quota_wait = codex_quota_wait_line(plan)          # #322 fix round 1: notify / wait before a quota stand-in
    if quota_wait:
        lines.append(quota_wait)
    lines.append("seats   :")
    for s in plan["seats"]:
        # WP-2: no member seat is the arbiter anymore (the arbiter is a fresh
        # EXTERNAL seatless call), so seats carry no 'arbiter*' tag.
        tag = "  [adversarial]" if s["adversarial_role"] else ""
        lines.append(
            f"  - {s['seat_id']:<13} {s['provider']:<6} {s.get('model') or '?':<24} {s['effort']:<8} "
            f"weight={s.get('seat_weight') or '?'}{tag}"
        )
        note = s.get("effort_note")
        if note:
            lines.append(f"      note : {note}")
        lines.append(f"      guard: {s['guard_stack']}")
    a = plan["arbiter"]
    residual = "  · residual FLAGGED (fallback)" if a.get("fallback_arbiter_residual") else ""
    lines.append(
        f"arbiter : EXTERNAL cold-context call — {a['provider']} {a.get('model') or '?'} ({a['effort']})  ·  "
        f"path: {a['path']}{residual}"
    )
    lines.append(f"          {a['constraint']}")
    if a.get("independence"):                           # WP-D3 (D23): only a DECLARED arbiter carries it
        lines.append(f"          independence: {a['independence']} · obligations: {'; '.join(a.get('obligations') or [])}")
    if a.get("effort_note"):
        lines.append(f"          note : {a['effort_note']}")
    lines.append(f"          guard: {a['guard_stack']}")
    lines.append(
        f"estimate: ~{est['seats']} seats · ~{est['planned_calls']} calls (ceiling {est['call_ceiling']}) "
        f"· est {est['est_low_min']}–{est['est_high_min']} min  (§9 cold-start seeds)"
    )
    lines.append(f"phases  : {' -> '.join(plan['phases_planned'])}")
    retired = plan["guard_policy"]["retired_tiers_rejected"]
    lines.append(f"retired effort tiers rejected: {', '.join(retired) if retired else 'none'}")
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
    RESOLVED staffing (provider + plan-time model + effort per seat WITH the seat-class
    name; the arbiter's model too — S081 WP-102; each seat's and the arbiter's `provenance` when the
    plan carries it — #282 r14), the
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
        staffed = {
            "seat_id": s["seat_id"],
            "provider": s["provider"],
            "effort": s["effort"],
            "seat_class": s.get("seat_class", s["effort"]),
            "effort_note": note,
            "model": s.get("model"),                    # the plan-time resolved model (S081 WP-102)
            "adversarial_role": bool(s["adversarial_role"]),
        }
        # S081 amendment 1 D6 (J16): a substituted seat carries its provenance; others keep their key set.
        if s.get("substitute_for") is not None:
            for key in ("substitute_for", "substitution_reason", "requested_model"):
                staffed[key] = s.get(key)
        # S081 revision 4, WP-D2: the plan-time admission the seat went through, when it went through one.
        if ADMISSION_ID_KEY in s:
            staffed[ADMISSION_ID_KEY] = s[ADMISSION_ID_KEY]
        # #282 r14: the seat's pin provenance, copied as planned (absent from a pre-r14 plan, so absent here).
        if "provenance" in s:
            staffed["provenance"] = dict(s["provenance"])
        seats.append(staffed)
        if note:
            advisory_notes.append(f"{s['seat_id']}: {note}")
    if arb.get("effort_note"):
        advisory_notes.append(f"<arbiter>: {arb['effort_note']}")
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
            "model": arb.get("model"),
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
    if "provenance" in arb:                             # #282 r14, as for the seats above
        record["arbiter"]["provenance"] = dict(arb["provenance"])
    for key in ("selection", "independence"):           # WP-D3 (D23): a DECLARED arbiter only
        if key in arb:
            record["arbiter"][key] = arb[key]
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
    ap.add_argument("--dry-run", action="store_true",
                    help="print pre-spend review and stop (no spend; the codex admission is decided check-only)")
    ap.add_argument("--size", choices=SIZES, default=None,
                    help="the task size (S081 D17): light|medium serve the codex seat the std tier; "
                         "absent = complex, recorded as the default")
    args = ap.parse_args(argv)

    try:
        contract = _load_contract(args)
        plan = build_session_plan(
            contract,
            profiles_dir=args.profiles_dir,
            roster_dir=args.roster_dir,
            session_id=args.session_id,
            size=args.size,
            project_root=args.project_root,
            # S081 revision 4, WP-D2: ONLY the persisted path records the plan-time admission.
            record_admission=not args.dry_run,
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
    # S081 amendment 1 D6 (J16): the persisted path — and ONLY this path; never --dry-run, never
    # build_session_plan — records one `deliberation` substitution row per substituted seat. The
    # plan is written first, so a failure can under-count a substitution but never invent one.
    rows = record_codex_substitutions(plan, project_root=Path(args.project_root), size=args.size)
    if rows:
        written = sum(1 for r in rows if r["row_written"])
        sys.stdout.write(
            f"astra substitutions recorded: {written} of {len(rows)} "
            f"(use {CODEX_SUBSTITUTION_USE}; provider gap: {CODEX_PROVIDER_GAP})\n")
        for r in rows:
            if not r["row_written"]:
                sys.stderr.write(
                    f"CONVENE: substitution row NOT recorded for seat {r['seat_id']}: {r['error']} "
                    "(the seat is still served by claude as planned)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
