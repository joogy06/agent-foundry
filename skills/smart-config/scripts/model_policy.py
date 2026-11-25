#!/usr/bin/env python3
"""model_policy.py — smart-config resolver (S059 design §4, host-neutral).

"The AI grades; the resolver maps." Grading (tier + reason) is the orchestrating
agent's judgment (A1). THIS script is the deterministic downstream: merge global +
project policy, translate tier -> host-native model id in the right SURFACE dialect,
guarantee fail-open, and write the decisions log. A model the harness roster benches
(skills/_meta/model_roster.py) is replaced by the roster's Claude main tier on every layer,
with a warning (#291 design s3.4).

Contract (design §4):
  resolve  --tier T [--surface agent|workflow|headless] [--agent NAME] [--host H]
           [--project-root PATH] [--task STR] [--reason STR] [--escalate] [--no-log]
           [--grade S|M|L [--file PATH ...]] [--effort-step N]
  validate [--project-root PATH] [--strict]
  show     [--project-root PATH] [--effective | --rubric | --sources]
  init     [--global | --project PATH] [--force]
  log      [--tail N] [--project-root PATH]

Exit codes (design §4):
  resolve : 0 ALWAYS (every fail-open path is ok:true). 2 usage error only.
            A broken policy can NEVER break a spawn.
  validate: 0 valid (warnings allowed), 3 schema error, 2 usage.
  show/log: 0 ok, 3 unreadable state, 2 usage.
  init    : 0 written, 3 target exists w/o --force, 2 usage.

stdlib + PyYAML (fail-open if missing). Fresh read per call — NO caching (AP-3).
Hard ceiling 400 LOC.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML 6.0.3 verified; de-facto ecosystem dep via _meta/claims.py
    _HAVE_YAML = True
except Exception:  # pragma: no cover - fail-open: missing PyYAML must not break a spawn
    yaml = None  # type: ignore
    _HAVE_YAML = False

# <!-- FRESHNESS:v1
# anchors:
#   - kind: model_alias_table
#     subject: claude-code-model-alias-keys
#     verified_against: "claude -p --model {fable,opus,sonnet,haiku} (V-1 positive 2026-06-12)"
#     verified_on: "2026-06-12"
#     volatility: high
# -->
# Alias KEY SET (S081 WP-301 / S080 design section 5). Headless ACCEPTS bare aliases +
# alias[1m] natively (V-1 positive), so no surface ever expands an alias. The old
# alias -> full-id VALUES are deliberately gone: their only consumer was the passthrough
# warning below, and a family alias pinned to a versioned id rots on the next release
# (it had by S080). Membership is the only claim this set makes. UNKNOWN values --
# including any full id -- pass through with a warning, never an error. Membership is
# not permission: a family the harness roster benches is replaced before shaping (below).
ALIASES = frozenset({"fable", "opus", "sonnet", "haiku"})
# A v1 `agents` pin is a claude-code-scoped scalar (policy-schema section 3). On any
# other --host it is skipped with a warning (S080 D9) rather than handing a Claude alias
# to a non-Claude host.
PIN_HOST = "claude-code"
SURFACES = ("agent", "workflow", "headless")
# Canonical ordered tier chain for --escalate (design §4). User-defined tiers are
# off-chain: --escalate on them is a no-op + warning.
TIER_CHAIN = ("trivial", "light", "medium", "complex")
# model-value hygiene (Codex #18): values reach argv, never shell strings.
MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9.\[\]-]+$")
TRUNCATE = 200
# V-2 conservative default (NOT testable from bob's context — no Workflow tool):
# strip [1m] + warn on the workflow surface, same as agent. Documented pending V-2.
WORKFLOW_ACCEPTS_1M = False

# #291 design s3.4 -- BENCHED MODELS. The harness roster (skills/_meta/model_roster.py)
# names the Claude families refused on every Claude path. A benched value on ANY layer
# (global, project; a tier's claude-code leaf or an `agents:` pin; alias, alias[1m] or a
# full id) is REPLACED by model_roster.CLAUDE_MAIN with a warning: not a hard fail, so
# unrelated projects keep working, and not inherit, which would silently hand the spawn
# whatever the session runs. Both modules are imported from the harness `_meta` beside
# this skill (an absolute path from __file__, never cwd), and the benched test is
# seat_model.is_benched itself, imported, never copied: one normaliser for every path.
# If that import fails the resolver behaves exactly as before the roster existed and says
# so in a warning (fail-open; the protected seats never route through smart-config).
_HARNESS_META = Path(__file__).resolve().parents[2] / "_meta"

# #311 phase 1 -- REASONING EFFORT beside the model (design 2026-09-24 s3.2). A tier may carry a
# host-keyed `effort` mapping next to its host keys: `light: { claude-code: sonnet, effort:
# { claude-code: low } }`. Same fail-open semantics as the model: a missing, null or malformed
# effort leaf means the effort is OMITTED and the spawn inherits the session's. The EXECUTION
# tier (`medium`) takes its effort per work package from `--grade` (skills/_meta/effort_policy.py,
# imported from the harness, never copied); an ungraded execution spawn gets that module's
# ungraded default (`high`, source default-ungraded). `--effort-step N` is the phase-2 retry
# carrier and is deliberately NOT `--escalate` (which moves the MODEL tier); it raises the level
# N steps, capped at xhigh -- `max` is never reached from smart-config. The protected seats'
# effort lives only in seat_model.ROLE_TABLE: no layer of this file can reach it.
EFFORT_KEY = "effort"
EXECUTION_TIER = "medium"
_FLOOR_EFFORTS = ("low", "medium", "high", "xhigh", "max")
#: #311 fix round 2 item 4: the highest level a POLICY FILE may set (effort_source `policy`).
#: xhigh and max are reserved for protected seats and explicit overrides, and a policy file is
#: repo/user content, so smart-config never emits more than `high` from a tier leaf or a step.
EFFORT_CEILING = "high"
EFFORT_STEP_CAP = EFFORT_CEILING

# Builtin layer (design §4 normative): defaults.tier medium + EMPTY tiers (every tier
# resolves to model:null = inherit) + no agents pins. With no readable config anywhere,
# degradation is ALWAYS inheritance — the builtin layer never routes models on its own.
BUILTIN = {"version": 1, "defaults": {"tier": "medium"}, "tiers": {}, "agents": {}, "rubric": ""}


def _w(warnings, msg):
    warnings.append(msg)


def _rate_limited_stderr(msg):
    sys.stderr.write(f"[model_policy] {msg}\n")


# --------------------------------------------------------------------------- IO

def _global_path():
    return Path(os.path.expanduser("~/.claude/model-policy.yaml"))


def _project_path(project_root):
    return Path(project_root) / ".claude" / "model-policy.yaml"


def _load_layer(path, warnings, label):
    """Load one YAML layer. Returns (dict_or_None, ok). Malformed -> skip + warn (fail-open)."""
    if not path.is_file():
        return None, True
    if not _HAVE_YAML:
        _w(warnings, f"{label}: PyYAML missing — layer skipped (fail-open)")
        return None, True
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # malformed YAML -> skip layer, use others + builtins
        _w(warnings, f"{label}: malformed YAML skipped ({type(e).__name__})")
        _rate_limited_stderr(f"malformed {label} policy at {path}: fail-open to inherit")
        _observe_failopen("malformed_yaml", str(path))
        return None, False
    if data is None:
        return {}, True
    if not isinstance(data, dict):
        _w(warnings, f"{label}: top-level is not a mapping — layer skipped (fail-open)")
        _rate_limited_stderr(f"non-mapping {label} policy at {path}: fail-open to inherit")
        _observe_failopen("non_mapping_policy", str(path))
        return None, False
    return data, True


def _deep_merge(base, over):
    """design §3 normative: mappings recurse, scalars replace, project wins per leaf.
    An explicit null leaf in `over` REPLACES (means inherit = omit param)."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v  # scalar (incl. explicit None) replaces
    return out


#: The benched floor used ONLY when model_roster itself cannot be read (#291 fix round 1,
#: finding A). It equals DEFAULT_BENCHED in workflows/bob-serial-exec.js and, while the
#: roster benches that family, model_roster.CLAUDE_BENCHED (a parity test holds all three).
_FLOOR_BENCHED = frozenset({"fable"})


def _harness_import(name):
    """Import one module from _HARNESS_META; a copy resolving from anywhere else (a shadowing
    module already imported under the same name) is refused, never trusted."""
    meta = str(_HARNESS_META)
    if meta not in sys.path:
        sys.path.insert(0, meta)
    mod = __import__(name)
    where = Path(getattr(mod, "__file__", "") or "").resolve().parent
    if where != _HARNESS_META:
        raise ImportError(f"{name} resolved outside the harness ({where})")
    return mod


def _roster_fault(warnings, reason, detail, msg):
    _w(warnings, msg)
    _rate_limited_stderr(msg.encode("ascii", "backslashreplace").decode("ascii"))
    _observe_failopen(reason, detail)


def _history_benched(roster):
    """The last HISTORY row's benched families when readable, else an empty set. Tolerant by
    design: it only ever ADDS to the refused set, so an unreadable row costs nothing."""
    try:
        history = getattr(roster, "HISTORY", None)
        last = history[-1] if isinstance(history, (tuple, list)) and history else None
        benched = last.get("benched") if isinstance(last, dict) else None
        if isinstance(benched, (tuple, list, set, frozenset)):
            return {f for f in benched if isinstance(f, str) and f}
    except Exception:
        pass
    return set()


def _load_roster(warnings):
    """(replacement, is_benched): the value a benched leaf becomes, and the predicate. Never None.

    A benched value NEVER passes through (#291 fix round 1, finding A). Three tiers, each a
    strict fallback of the one above; every fallback is warned about:

      1. model_roster, model_ids and seat_model all import: replacement CLAUDE_MAIN,
         predicate seat_model.is_benched (the roster's benched set, read at call time).
      2. seat_model does NOT import (e.g. a roster that breaks its import-time invariants,
         which makes seat_model fail closed): the refusal still runs through the pure
         model_ids normaliser, over the UNION of model_roster.CLAUDE_BENCHED, HISTORY[-1]
         ["benched"] and _FLOOR_BENCHED -- the broken edit may be the bench itself, so a
         broken roster can only refuse MORE (#291 fix round 2, N1).
      3. model_roster does not import: the hard floor _FLOOR_BENCHED. If model_ids is also missing the floor is matched as a plain
         case-insensitive substring -- cruder than the one normaliser, and deliberately so:
         it can only refuse MORE, never less.

    The replacement is model_roster.CLAUDE_MAIN when that is a well-formed value the
    predicate does not itself refuse; otherwise None, which means inherit (the parameter is
    omitted). Imported per call (after the first call a module-cache lookup): no roster
    state is held here, so a roster edit reaches the next spawn like a policy edit does.
    """
    roster = ids = None
    try:
        ids = _harness_import("model_ids")
    except Exception as e:
        _roster_fault(warnings, "model_ids_unavailable", f"{type(e).__name__}: {e}",
                      f"model_ids unavailable ({type(e).__name__}: {e}) -- benched families are "
                      f"matched as a plain substring (floor, refuses more, never less)")
    try:
        roster = _harness_import("model_roster")
    except Exception as e:
        _roster_fault(warnings, "roster_unavailable", f"{type(e).__name__}: {e}",
                      f"model roster unavailable ({type(e).__name__}: {e}) -- benched-model refusal "
                      f"falls back to the hard floor {sorted(_FLOOR_BENCHED)}; a benched value is "
                      f"dropped to inherit (the spawn will inherit the interactive session model)")

    predicate = None
    if roster is not None and ids is not None:
        try:
            sm = _harness_import("seat_model")
            predicate = sm.is_benched
        except Exception as e:
            _roster_fault(warnings, "seat_model_unavailable", f"{type(e).__name__}: {e}",
                          f"seat_model unavailable ({type(e).__name__}: {e}) -- benched-model refusal "
                          f"continues from the union of model_roster.CLAUDE_BENCHED, HISTORY[-1] and the "
                          f"hard floor, via model_ids")
    if predicate is None:
        # Tier 2/3 run BECAUSE the roster may be broken, so no single roster value is trusted
        # on its own (#291 fix round 2, N1): the refused set is the UNION of the live
        # CLAUDE_BENCHED, the last HISTORY row's benched tuple and the hard floor. A broken
        # roster can therefore only refuse MORE. A legit revert (roster + HISTORY + floor
        # edited together, runbook s7) keeps seat_model importable and never reaches here.
        families = set(_FLOOR_BENCHED)
        if roster is not None:
            live = getattr(roster, "CLAUDE_BENCHED", None)
            if isinstance(live, frozenset) and all(isinstance(f, str) and f for f in live):
                families |= live
            else:
                _roster_fault(warnings, "roster_benched_unusable", repr(live),
                              f"model_roster.CLAUDE_BENCHED {live!r} is unusable -- benched-model "
                              f"refusal continues from HISTORY[-1] and the hard floor "
                              f"{sorted(_FLOOR_BENCHED)}")
            families |= _history_benched(roster)
        families = frozenset(families)
        if ids is not None:
            predicate = lambda value, _f=families, _ids=ids: _ids.is_benched(value, _f)  # noqa: E731
        else:
            predicate = lambda value, _f=families: (  # noqa: E731
                isinstance(value, str) and any(f.lower() in value.lower() for f in _f))

    main = getattr(roster, "CLAUDE_MAIN", None) if roster is not None else None
    if not isinstance(main, str) or not MODEL_VALUE_RE.match(main) or predicate(main):
        if roster is not None:
            _roster_fault(warnings, "roster_main_unusable", repr(main),
                          f"model_roster.CLAUDE_MAIN {main!r} is not a usable, unbenched model value "
                          f"-- a benched value is dropped to inherit (the spawn will inherit the "
                          f"interactive session model)")
        main = None
    return main, predicate


def _refuse_benched(layer, label, roster, warnings):
    """Replace every benched Claude value in one loaded layer by CLAUDE_MAIN, with a warning.

    Scope: tiers.<tier>.claude-code leaves and `agents:` pins (both claude-code-scoped;
    other host keys carry that host's ids and are left alone). Shapes the resolver already
    tolerates as broken (a non-mapping tiers / agents / host map) are passed through
    untouched for _mapping() to warn about. The layer is copied, never mutated.
    """
    if not isinstance(layer, dict):
        return layer
    main, benched = roster

    def swap(where, value):
        if isinstance(value, str) and benched(value):
            what = (f"replaced by the Claude main tier {main!r}" if main is not None
                    else "dropped to inherit -- no usable main tier, so the spawn will inherit the interactive session model")
            msg = f"{label} {where} = {value!r} is a benched model (model_roster) -- {what}"
            _w(warnings, msg)
            _rate_limited_stderr(msg.encode("ascii", "backslashreplace").decode("ascii"))
            return main
        return value

    out = dict(layer)
    tiers = layer.get("tiers")
    if isinstance(tiers, dict):
        new_tiers = {}
        for tier, host_map in tiers.items():
            if isinstance(host_map, dict) and PIN_HOST in host_map:
                host_map = dict(host_map)
                host_map[PIN_HOST] = swap(f"tiers.{tier}.{PIN_HOST}", host_map[PIN_HOST])
            new_tiers[tier] = host_map
        out["tiers"] = new_tiers
    agents = layer.get("agents")
    if isinstance(agents, dict):
        out["agents"] = {name: swap(f"agents.{name}", val) for name, val in agents.items()}
    return out


def _merged_policy(project_root, warnings, roster_out=None):
    """Merge builtin <- global <- project. Returns (merged, sources) where sources maps
    a few top leaves to 'builtin'|'global'|'project' for provenance. Each layer has its
    benched values replaced (#291) BEFORE the merge, so no layer can route a benched model.
    `roster_out`, a list, receives the loaded (replacement, is_benched) pair so a caller can
    re-check its FINAL value without loading (and warning about) the roster twice."""
    g, _ = _load_layer(_global_path(), warnings, "global")
    p, _ = _load_layer(_project_path(project_root), warnings, "project")
    if isinstance(g, dict) or isinstance(p, dict):
        roster = _load_roster(warnings)
        if roster_out is not None:
            roster_out.append(roster)
        g = _refuse_benched(g, "global", roster, warnings)
        p = _refuse_benched(p, "project", roster, warnings)
    merged = _deep_merge(BUILTIN, g or {})
    merged = _deep_merge(merged, p or {})
    # version mismatch between layers (design §3): warn; resolve uses merged anyway.
    versions = {lbl: lay.get("version") for lbl, lay in (("global", g), ("project", p)) if isinstance(lay, dict) and "version" in lay}
    # repr, not the raw value: `version: [1]` is unhashable and set() raised (S080 D8 class).
    if len({repr(v) for v in versions.values()}) > 1:
        _w(warnings, f"version mismatch across layers {versions} — using merged")
    sources = {"global": bool(g), "project": bool(p)}
    return merged, sources


# ---------------------------------------------------------------- surface shaping

def _shape_for_surface(value, surface, warnings):
    """Translate a raw model value (alias|full-id, optional [1m]) into the surface
    dialect. value None -> None (inherit). Returns the surface-shaped string or None."""
    if value is None:
        return None
    value = str(value)
    has_1m = value.endswith("[1m]")
    bare = value[:-4] if has_1m else value

    if not MODEL_VALUE_RE.match(value):
        _w(warnings, f"model value {value!r} fails hygiene pattern — dropped (inherit)")
        _rate_limited_stderr(f"rejected model value {value!r}: fail-open to inherit")
        return None
    if bare not in ALIASES:
        _w(warnings, f"unknown model id {bare!r} — passthrough")

    if surface in ("agent", "workflow"):
        # agent: aliases only, [1m] unexpressable -> strip + warn (warn-on-loss).
        # workflow: V-2 conservative -> strip + warn identical to agent (pending V-2).
        if has_1m and not (surface == "workflow" and WORKFLOW_ACCEPTS_1M):
            _w(warnings, f"[1m] not expressable on {surface} surface — stripped from {value!r}")
        if surface == "workflow" and WORKFLOW_ACCEPTS_1M and has_1m:
            return f"{bare}[1m]"
        return bare
    # headless: V-1 positive — native alias acceptance, emit alias[1m] as-is (no expansion).
    return value


# ------------------------------------------------------------------- escalate

def _escalate(tier, warnings):
    """Bump one tier on the canonical chain, capped at complex. Off-chain -> no-op + warn."""
    if tier not in TIER_CHAIN:
        _w(warnings, f"--escalate no-op: {tier!r} not on canonical chain {TIER_CHAIN}")
        return tier, False
    i = TIER_CHAIN.index(tier)
    if i >= len(TIER_CHAIN) - 1:
        _w(warnings, "--escalate capped at complex")
        return tier, False
    return TIER_CHAIN[i + 1], True


# ----------------------------------------------------------------- decisions log

def _project_slug(project_root):
    """Slug rule (design §5 normative): every char of the abs path not in [A-Za-z0-9] -> '-'."""
    ap = os.path.abspath(project_root)
    return re.sub(r"[^A-Za-z0-9]", "-", ap)


def _log_path(project_root):
    if project_root:
        slug = _project_slug(project_root)
        return Path(os.path.expanduser(f"~/.claude/projects/{slug}/model-decisions.jsonl"))
    return Path(os.path.expanduser("~/.claude/state/model-decisions.jsonl"))


def _policy_sha256(merged):
    import hashlib
    blob = json.dumps(merged, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _append_log(project_root, record, warnings):
    """O_APPEND single-line, never-raise, never blocks resolve. Rotate at 1MB under
    non-blocking flock (skip if not acquired). os.replace, one generation kept."""
    try:
        path = _log_path(project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.is_file() and path.stat().st_size >= 1_000_000:
                _rotate_log(path)
        except OSError:
            pass
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as e:  # never blocks resolve (design §5)
        _w(warnings, f"decisions log unwritable: {type(e).__name__} — continuing")


def _rotate_log(path):
    # The 1 latent case of #249, as distinct from the 9 import-fatal ones: the
    # import was INSIDE this function, so the module loaded fine on Windows and
    # only raised when rotation actually ran -- next to an `except Exception`
    # that would have swallowed it. Same fix, different severity.
    _meta = str(Path(__file__).resolve().parents[2] / "_meta")
    if _meta not in sys.path:
        sys.path.insert(0, _meta)
    from portable_lock import lock_exclusive
    try:
        fd = os.open(str(path), os.O_RDWR)
    except OSError:
        return
    try:
        try:
            lock_exclusive(fd, blocking=False)  # skip if not acquired (no race)
        except OSError:
            return
        os.replace(str(path), str(path) + ".1")  # Windows-safe; one generation kept
    finally:
        os.close(fd)


def _observe_failopen(kind, detail):
    """claude-observe friction event on fail-open (design §6.2). Best-effort, never-raise."""
    try:
        sys.path.insert(0, os.path.expanduser("~/.claude/skills/process-observation/scripts"))
        # The module is write.py, not observe.py. This read `from observe import`
        # and therefore ALWAYS raised ImportError, swallowed by the bare `except`
        # below — so this fail-open telemetry never emitted one event since S059.
        # Found by wiring_sweep's deps arm (#248, 2026-07-30). The working form is
        # the one skeleton-extractor/scripts/extract.py has always used.
        from write import claude_observe  # type: ignore
        claude_observe(category="config_drift", summary=f"model-policy fail-open: {kind}", detail=detail)
    except Exception:
        pass  # observation is best-effort; never perturb resolve


# ---------------------------------------------------------------- schema validate

KNOWN_TOP = {"version", "defaults", "tiers", "agents", "rubric", "fallbacks", "escalation"}


def _validate_policy(merged, strict, warnings, errors):
    if merged.get("version") != 1:
        _w(warnings, f"version {merged.get('version')!r} != 1")
    for k in merged:
        if k not in KNOWN_TOP:
            _w(warnings, f"unknown top-level key {k!r} (forward-compat)")
    tiers = merged.get("tiers")
    if tiers is not None and not isinstance(tiers, dict):
        errors.append("tiers must be a mapping")
    if isinstance(tiers, dict):
        for tier, host_map in tiers.items():
            leaf = host_map.get(EFFORT_KEY) if isinstance(host_map, dict) else None
            if leaf is None:
                continue
            if not isinstance(leaf, dict):
                errors.append(f"tiers.{tier}.{EFFORT_KEY} must be a host-keyed mapping")
                continue
            if tier == EXECUTION_TIER:
                errors.append(f"tiers.{tier}.{EFFORT_KEY} is not allowed: the execution tier takes its "
                              f"effort per WP from --grade (#311)")
            allowed = _FLOOR_EFFORTS[:_FLOOR_EFFORTS.index(EFFORT_CEILING) + 1]
            for host, val in leaf.items():
                if val is not None and val not in allowed:
                    errors.append(f"tiers.{tier}.{EFFORT_KEY}.{host} = {val!r} is not one of {list(allowed)} "
                                  f"(xhigh and max are reserved for protected seats)")
    agents = merged.get("agents") or {}
    if not isinstance(agents, dict):
        errors.append("agents must be a mapping")
    else:
        for name, val in agents.items():
            if isinstance(val, str) and val in TIER_CHAIN:
                errors.append(f"agents.{name} = {val!r} is a TIER name; pins are model values only")
            if isinstance(val, str) and val and not MODEL_VALUE_RE.match(val):
                errors.append(f"agents.{name} value {val!r} fails hygiene pattern")
    if strict:
        errors.extend(f"(strict) {w}" for w in warnings)


# --------------------------------------------------------------------- commands

def _mapping(merged, key, warnings):
    """S080 D8: resolve reads `defaults`/`tiers`/`agents` as mappings. Any other shape
    (e.g. `tiers: [complex]`) raised AttributeError -> exit 1 with empty stdout, breaking
    the exit-0 contract. Warn and treat it as empty, so resolution falls through (fail-open)."""
    val = merged.get(key)
    if val is None or isinstance(val, dict):
        return val or {}
    _w(warnings, f"{key} is not a mapping ({type(val).__name__}) -- ignored (fail-open)")
    return {}


def _default_tier(defaults, warnings):
    dt = defaults.get("tier", "medium")
    if isinstance(dt, str):
        return dt
    _w(warnings, f"defaults.tier is not a string ({type(dt).__name__}) -- using 'medium'")
    return "medium"


def _effort_policy(warnings):
    """skills/_meta/effort_policy.py from the harness, or None with a warning (fail-open: omit)."""
    try:
        return _harness_import("effort_policy")
    except Exception as e:
        _w(warnings, f"effort_policy unavailable ({type(e).__name__}: {e}) -- effort omitted (inherit)")
        _observe_failopen("effort_policy_unavailable", f"{type(e).__name__}: {e}")
        return None


def _resolve_effort(a, tiers, tier_used, warnings):
    """#311: the effort for one resolve, and where it came from. Never raises (fail-open = inherit).

    Order: --grade (the execution grade, effort_policy) > the tier's host-keyed `effort` leaf >
    the ungraded-execution default (tier `medium`, a configured policy only) > inherit. The
    Agent-tool surface has no effort parameter, so there the effort is reported as inherit
    with a warning (the agent file's static frontmatter applies)."""
    # getattr: in-process callers build their own argument objects without the #311 flags.
    grade = getattr(a, "grade", None)
    files = getattr(a, "file", None) or []
    res = {"effort": None, "effort_source": "inherit", "grade": None, "effort_step": 0, "policy_hash": None}
    ep = None
    levels = _FLOOR_EFFORTS
    if grade is not None or (tier_used == EXECUTION_TIER and tiers):
        ep = _effort_policy(warnings)
        if ep is not None:
            levels = tuple(ep.LEVELS)
    if grade is not None:
        if a.host != PIN_HOST:
            _w(warnings, f"--grade effort is {PIN_HOST}-scoped; host {a.host!r} -- effort omitted (inherit)")
        elif ep is not None:
            try:
                d = ep.first_attempt_effort(grade, files, root=getattr(a, "project_root", None))
                res.update(effort=d.effort, effort_source=d.source, grade=d.grade, policy_hash=d.policy_hash)
            except Exception as e:
                _w(warnings, f"--grade {grade!r} not resolvable ({type(e).__name__}: {e}) -- effort omitted (inherit)")
    else:
        host_map = tiers.get(tier_used) if isinstance(tiers, dict) else None
        leaf = host_map.get(EFFORT_KEY) if isinstance(host_map, dict) else None
        if leaf is not None and tier_used == EXECUTION_TIER:
            # F3: the execution tier's effort comes from the WP grade; a leaf would starve (or
            # inflate) ungraded execution work, so it is ignored and validate reports it.
            _w(warnings, f"tiers.{tier_used}.{EFFORT_KEY} is ignored: the execution tier takes its effort "
                         f"from --grade (ungraded -> the ungraded default)")
            leaf = None
        if leaf is not None and not isinstance(leaf, dict):
            _w(warnings, f"tiers.{tier_used}.{EFFORT_KEY} is not a host-keyed mapping -- effort omitted (inherit)")
        elif isinstance(leaf, dict) and a.host in leaf:
            val = leaf.get(a.host)
            if val is None:
                pass  # explicit null = inherit
            elif isinstance(val, str) and val in levels:
                # A policy-file level is source `policy` (fix round 2 item 4): not reserved, no grade.
                if levels.index(val) > levels.index(EFFORT_CEILING):
                    _w(warnings, f"tiers.{tier_used}.{EFFORT_KEY}.{a.host} = {val!r} capped at "
                                 f"{EFFORT_CEILING} (xhigh and max are reserved for protected seats)")
                    val = EFFORT_CEILING
                res.update(effort=val, effort_source="policy", grade=None)
            else:
                _w(warnings, f"tiers.{tier_used}.{EFFORT_KEY}.{a.host} = {val!r} is not an effort level "
                             f"{list(levels)} -- effort omitted (inherit)")
        if res["effort"] is None and tier_used == EXECUTION_TIER and tiers and a.host == PIN_HOST \
                and ep is not None:
            d = ep.first_attempt_effort(None)
            res.update(effort=d.effort, effort_source=d.source, grade=None, policy_hash=d.policy_hash)
    step = getattr(a, "effort_step", 0) or 0
    if step < 0:
        _w(warnings, f"--effort-step {step} ignored: a step only raises the effort")
    elif step:
        if res["effort"] is None:
            _w(warnings, "--effort-step no-op: no effort to step (inherit)")
        elif res["effort_source"] != "policy":
            # Fix round 2 item 3: a stepped grade or ungraded default is not the table's value, so
            # no checker would accept it. The step is phase-2 retry machinery; until then it only
            # moves a policy-file level, and never past the policy ceiling.
            _w(warnings, f"--effort-step is refused with --grade and with the ungraded default "
                         f"(source {res['effort_source']!r}) until phase 2 -- ignored")
        else:
            i = levels.index(res["effort"])
            cap = levels.index(EFFORT_STEP_CAP) if EFFORT_STEP_CAP in levels else len(levels) - 1
            target = max(i, min(i + step, cap))   # never lowers; never passes the cap
            if target < i + step:
                _w(warnings, f"--effort-step capped at {EFFORT_STEP_CAP} (the policy ceiling)")
            res.update(effort=levels[target], effort_step=step)
    if a.surface == "agent" and res["effort"] is not None:
        _w(warnings, f"effort {res['effort']!r} is not expressible on the agent surface (the Agent tool has no "
                     f"effort parameter; the agent file's frontmatter applies) -- reported as inherit")
        res.update(effort=None, effort_source="inherit")
    return res


def cmd_resolve(a):
    warnings = []
    if a.surface not in SURFACES:
        sys.stderr.write(f"usage: --surface one of {SURFACES}\n")
        return 2
    roster_out = []
    merged, _ = _merged_policy(a.project_root, warnings, roster_out)
    dt = _default_tier(_mapping(merged, "defaults", warnings), warnings)
    tier_req = a.tier or dt
    tier_used = tier_req
    escalated = False
    if a.escalate:
        tier_used, escalated = _escalate(tier_req, warnings)
    source = "tier"
    model = None
    tiers_map = _mapping(merged, "tiers", warnings)
    pin = _mapping(merged, "agents", warnings).get(a.agent) if a.agent else None
    if pin is not None and a.host != PIN_HOST:
        # S080 D9, option (c)+warn: skip the pin, resolve via tiers.<tier>.<host>, and say so.
        # `source` below then records the tier path that actually served, not "agent-pin".
        msg = (f"agents.{a.agent} pin {pin!r} skipped: v1 agent pins are {PIN_HOST}-scoped, "
               f"host is {a.host!r} -- resolved via tiers instead")
        _w(warnings, msg)
        _rate_limited_stderr(msg.encode("ascii", "backslashreplace").decode("ascii"))  # argv/YAML text; cp1252-safe
        pin = None
    if pin is not None:
        model = _shape_for_surface(pin, a.surface, warnings)
        source = "agent-pin"
    else:
        tiers = tiers_map
        if tier_used not in tiers:
            # Empty-tiers builtin (no readable config) resolves every tier to inherit;
            # warn about a genuinely unknown tier, NOT when tiers is simply unpopulated
            # or the requested tier already equals the default.
            if tier_used and tiers and tier_used != dt:
                _w(warnings, f"unknown tier {tier_used!r} -> defaults.tier {dt!r}")
            tier_used = dt
        host_map = tiers.get(tier_used) or {}
        raw = host_map.get(a.host) if isinstance(host_map, dict) else None
        model = _shape_for_surface(raw, a.surface, warnings)
        source = "project" if _project_path(a.project_root).is_file() else ("global" if _global_path().is_file() else "builtin")
    if model is not None and roster_out:
        # #291 fix round 1, finding F: the layers were checked BEFORE shaping; check the
        # FINAL shaped value too, so no spelling the shaper produces can carry a benched
        # family out (defence in depth behind the layer check).
        main, benched = roster_out[0]
        if benched(model):
            repl = _shape_for_surface(main, a.surface, []) if main is not None else None
            if repl is not None and benched(repl):
                repl = None
            msg = (f"resolved value {model!r} is a benched model (model_roster) -- "
                   + (f"replaced by the Claude main tier {repl!r}" if repl is not None
                      else "dropped to inherit -- no usable main tier, so the spawn will inherit the interactive session model"))
            _w(warnings, msg)
            _rate_limited_stderr(msg.encode("ascii", "backslashreplace").decode("ascii"))
            model = repl
    eff = _resolve_effort(a, tiers_map, tier_used if tier_used in tiers_map else dt, warnings)
    out = {
        "ok": True, "model": model, "tier": tier_used, "tier_requested": tier_req,
        "escalated": escalated, "surface": a.surface, "agent": a.agent,
        "source": source, "warnings": warnings,
        "effort": eff["effort"], "effort_source": eff["effort_source"], "grade": eff["grade"],
        "effort_step": eff["effort_step"], "policy_hash": eff["policy_hash"],
    }
    if not a.no_log:
        rec = {
            "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task": (a.task or "")[:TRUNCATE], "tier_requested": tier_req, "tier": tier_used,
            "escalated": escalated, "surface": a.surface, "agent": a.agent, "model": model,
            "source": source, "reason": (a.reason or "")[:TRUNCATE], "policy_sha256": _policy_sha256(merged),
            "effort": eff["effort"], "effort_source": eff["effort_source"], "grade": eff["grade"],
            "effort_step": eff["effort_step"],
        }
        _append_log(a.project_root, rec, warnings)
    sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
    return 0  # ALWAYS 0 on the resolve path (design §4)


def cmd_validate(a):
    warnings, errors = [], []
    merged, _ = _merged_policy(a.project_root, warnings)
    _validate_policy(merged, a.strict, warnings, errors)
    sys.stdout.write(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings}, sort_keys=True) + "\n")
    return 3 if errors else 0


def cmd_show(a):
    warnings = []
    try:
        merged, sources = _merged_policy(a.project_root, warnings)
    except Exception as e:
        sys.stderr.write(f"show: unreadable state: {e}\n")
        return 3
    if a.rubric:
        sys.stdout.write((merged.get("rubric") or "") + "\n")
        return 0
    if a.sources:
        out = {"effective": merged, "sources": sources, "warnings": warnings}
    else:
        out = {"effective": merged, "warnings": warnings}
    sys.stdout.write(json.dumps(out, sort_keys=True, indent=2) + "\n")
    return 0


def cmd_init(a):
    if a.is_global:
        target = _global_path()
    elif a.project:
        target = _project_path(a.project)
    else:
        sys.stderr.write("usage: init --global | --project PATH\n")
        return 2
    if target.is_file() and not a.force:
        sys.stderr.write(f"init: {target} exists (use --force)\n")
        return 3
    tmpl = Path(__file__).resolve().parent.parent / "templates" / "model-policy.yaml"
    try:
        body = tmpl.read_text(encoding="utf-8")
    except OSError as e:
        sys.stderr.write(f"init: template unreadable: {e}\n")
        return 3
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    sys.stdout.write(json.dumps({"ok": True, "written": str(target)}, sort_keys=True) + "\n")
    return 0


def cmd_log(a):
    path = _log_path(a.project_root)
    if not path.is_file():
        sys.stdout.write(json.dumps({"ok": True, "lines": []}, sort_keys=True) + "\n")
        return 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        sys.stderr.write(f"log: unreadable: {e}\n")
        return 3
    tail = lines[-a.tail:] if a.tail else lines
    for ln in tail:
        sys.stdout.write(ln + "\n")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="model_policy.py", description="smart-config resolver (S059)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve")
    r.add_argument("--tier")
    r.add_argument("--surface", default="agent")
    r.add_argument("--agent")
    r.add_argument("--host", default="claude-code")
    r.add_argument("--project-root", dest="project_root", default=os.getcwd())
    r.add_argument("--task")
    r.add_argument("--reason")
    r.add_argument("--escalate", action="store_true")
    r.add_argument("--no-log", dest="no_log", action="store_true")
    r.add_argument("--grade", choices=("S", "M", "L"),
                   help="#311: the WP's work-packages.v1 complexity; sets the first-attempt effort")
    r.add_argument("--file", action="append", default=[],
                   help="#311: a file the WP declares (repeatable); a sensitive one promotes S/M one step")
    r.add_argument("--effort-step", dest="effort_step", type=int, default=0,
                   help="#311 phase-2 retry carrier: raise the effort N levels, capped at xhigh "
                        "(NOT --escalate, which moves the model tier)")
    r.set_defaults(func=cmd_resolve)

    v = sub.add_parser("validate")
    v.add_argument("--project-root", dest="project_root", default=os.getcwd())
    v.add_argument("--strict", action="store_true")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("show")
    s.add_argument("--project-root", dest="project_root", default=os.getcwd())
    s.add_argument("--effective", action="store_true")
    s.add_argument("--rubric", action="store_true")
    s.add_argument("--sources", action="store_true")
    s.set_defaults(func=cmd_show)

    i = sub.add_parser("init")
    i.add_argument("--global", dest="is_global", action="store_true")
    i.add_argument("--project")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_init)

    lg = sub.add_parser("log")
    lg.add_argument("--tail", type=int, default=0)
    lg.add_argument("--project-root", dest="project_root", default=os.getcwd())
    lg.set_defaults(func=cmd_log)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
