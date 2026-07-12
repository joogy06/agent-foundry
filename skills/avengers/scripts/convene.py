#!/usr/bin/env python3
"""avengers — convene.py (WP-2). The resolver / fail-closed pre-spend gate.

Charter (design §3/§8): resolve a composition profile + roster into a FROZEN flat
JSON session-plan, refusing to spend a single seat call unless the structure is
sound. It:
  - runs the fail-closed STRUCTURAL validate (design §4 LOW_QUORUM case (a)):
      * < 3 member seats                                  -> sub-quorum, no run
      * < 2 provider families AND no declared fallback    -> sub-quorum, no run
      * no `can_arbitrate` seat whose provider differs from every adversarial
        seat's provider (arbiter constraint)              -> no run
      * zero `adversarial_role: true` seats (design §6)   -> no run
  - REJECTS retired effort tiers (notably 'high') and un-pinned codex effort
  - performs a TWO-LAYER config merge ONLY: shipped defaults <- profile. It reads
    NO repo-local override file (a drive-by injection vector, design §3/§14).
  - injects the resolver-owned guard stacks (codex `--ephemeral -s read-only`
    per-call pins; agy `--sandbox`, flags-before `-p`)
  - stamps profile-sha256 provenance
  - materializes a flat JSON session-plan that validates against
    schemas/session-plan.v1.schema.json (a bundled stdlib mini-validator; no
    third-party jsonschema dependency)
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
SCHEMA_PATH = _SKILL_ROOT / "schemas" / "session-plan.v1.schema.json"

# --------------------------------------------------------------------------- #
# Locked policy constants (design §2/§4/§6)
# --------------------------------------------------------------------------- #
KNOWN_PROVIDERS = frozenset({"codex", "claude", "agy"})
RETIRED_EFFORT_TIERS = frozenset({"high"})          # 'high' is RETIRED and rejected
CODEX_EFFORT_TIERS = frozenset({"minimal", "low", "medium", "xhigh", "max"})  # no 'high', no 'default'
NON_CODEX_EFFORTS = frozenset({"default"})          # claude/agy use smart-config 'default'
KNOWN_OUTCOMES = frozenset({"decision", "deliverable", "forge_brief", "auto"})
PROFILE_SCHEMA = "avengers-profile.v1"

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
def validate_effort(seat_id: str, provider: str, effort: str) -> None:
    if effort in RETIRED_EFFORT_TIERS:
        raise ConveneError(
            f"seat '{seat_id}': effort tier '{effort}' is RETIRED and rejected "
            f"(use xhigh or max)"
        )
    if provider == "codex":
        if effort not in CODEX_EFFORT_TIERS:
            raise ConveneError(
                f"seat '{seat_id}': codex effort must be one of "
                f"{sorted(CODEX_EFFORT_TIERS)} (got {effort!r}); "
                f"un-pinned codex calls are forbidden (success criterion #4)"
            )
    else:
        if effort not in NON_CODEX_EFFORTS:
            raise ConveneError(
                f"seat '{seat_id}': {provider} effort must be 'default' "
                f"(smart-config advisory tier); got {effort!r}"
            )


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


def guard_stack_for(provider: str, effort: str, *, is_arbiter: bool, is_ratification: bool) -> str:
    if provider == "codex":
        if is_arbiter and is_ratification and effort == "max":
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
        card_prov = card.get("provider", {}) or {}
        provider = entry.get("provider") or card_prov.get("affinity")
        if provider not in KNOWN_PROVIDERS:
            raise ConveneError(f"seat '{ref}': unknown provider {provider!r} (known: {sorted(KNOWN_PROVIDERS)})")
        effort = entry.get("effort") or card_prov.get("effort") or "default"
        validate_effort(ref, provider, effort)
        adversarial = bool(entry.get("adversarial_role", card.get("adversarial_role", False)))
        resolved.append(
            {
                "seat_id": ref,
                "provider": provider,
                "effort": effort,
                "adversarial_role": adversarial,
                "can_arbitrate": bool(card.get("can_arbitrate", False)),
                "fallback_ok": bool(card_prov.get("fallback_ok", False)),
            }
        )
    return resolved


def resolve_arbiter(
    profile: Dict[str, Any], seats: List[Dict[str, Any]], *, is_ratification: bool
) -> Dict[str, Any]:
    adversarial_providers = {s["provider"] for s in seats if s["adversarial_role"]}
    eligible = [
        s for s in seats
        if s["can_arbitrate"] and s["provider"] not in adversarial_providers
    ]
    if not eligible:
        raise ConveneError(
            "arbiter constraint unsatisfiable: no can_arbitrate seat has a provider "
            f"different from every adversarial provider {sorted(adversarial_providers)} "
            "(LOW_QUORUM case (a) — no run, no spend)"
        )
    arb_cfg = profile.get("arbiter", {}) or {}
    prefer = arb_cfg.get("prefer")
    chosen = next((s for s in eligible if s["seat_id"] == prefer), None) or eligible[0]
    effort = chosen["effort"]
    # Ratification arbiter on codex pins 'max' (design §4/§7).
    if chosen["provider"] == "codex" and is_ratification:
        effort = arb_cfg.get("effort_on_codex", "max")
        validate_effort(chosen["seat_id"], "codex", effort)
    guard = guard_stack_for(chosen["provider"], effort, is_arbiter=True, is_ratification=is_ratification)
    return {
        "seat": chosen["seat_id"],
        "provider": chosen["provider"],
        "effort": effort,
        "constraint": (
            f"provider != every adversarial provider {sorted(adversarial_providers)}; "
            f"chosen {chosen['seat_id']}={chosen['provider']} (satisfied)"
        ),
        "guard_stack": guard,
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
    arbiter = resolve_arbiter(profile, seats, is_ratification=is_ratification)

    # Inject guard stacks into member seats.
    for s in seats:
        s["guard_stack"] = guard_stack_for(
            s["provider"], s["effort"], is_arbiter=False, is_ratification=is_ratification
        )

    outcome_type = _resolve_outcome(profile, contract)
    sid = session_id or make_session_id(task or family, now=now)
    created = (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

    plan: Dict[str, Any] = {
        "schema": "session-plan.v1",
        "session_id": sid,
        "created_at": created,
        "profile": family if not str(family).endswith((".yaml", ".yml")) else profile.get("family", family),
        "profile_path": str(profile_path),
        "profile_sha256": prof_sha,
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
        tags = []
        if s["adversarial_role"]:
            tags.append("adversarial")
        if s["seat_id"] == plan["arbiter"]["seat"]:
            tags.append("arbiter*")
        tag = ("  [" + ",".join(tags) + "]") if tags else ""
        lines.append(f"  - {s['seat_id']:<11} {s['provider']:<6} {s['effort']:<8}{tag}")
        lines.append(f"      guard: {s['guard_stack']}")
    a = plan["arbiter"]
    lines.append(f"arbiter : {a['seat']} ({a['provider']}, {a['effort']})  ·  {a['constraint']}")
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
    sys.stdout.write(f"session dir: {session_dir}\nsession-plan: {out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
