#!/usr/bin/env python3
"""model_policy.py — smart-config resolver (S059 design §4, host-neutral).

"The AI grades; the resolver maps." Grading (tier + reason) is the orchestrating
agent's judgment (A1). THIS script is the deterministic downstream: merge global +
project policy, translate tier -> host-native model id in the right SURFACE dialect,
guarantee fail-open, and write the decisions log.

Contract (design §4):
  resolve  --tier T [--surface agent|workflow|headless] [--agent NAME] [--host H]
           [--project-root PATH] [--task STR] [--reason STR] [--escalate] [--no-log]
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
#     subject: claude-code-model-aliases
#     verified_against: "claude -p --model {fable,opus,sonnet,haiku} (V-1 positive 2026-06-12)"
#     verified_on: "2026-06-12"
#     volatility: high
# -->
# Alias -> full id. Headless ACCEPTS bare aliases + alias[1m] natively (V-1 positive),
# so the headless surface emits the alias verbatim and does NOT expand. This table is
# kept for documentation + passthrough hygiene. New models ship faster than this enum:
# UNKNOWN values pass through with a warning, never an error.
ALIASES = {
    "fable": "claude-fable-5",
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}
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


def _merged_policy(project_root, warnings):
    """Merge builtin <- global <- project. Returns (merged, sources) where sources maps
    a few top leaves to 'builtin'|'global'|'project' for provenance."""
    g, _ = _load_layer(_global_path(), warnings, "global")
    p, _ = _load_layer(_project_path(project_root), warnings, "project")
    merged = _deep_merge(BUILTIN, g or {})
    merged = _deep_merge(merged, p or {})
    # version mismatch between layers (design §3): warn; resolve uses merged anyway.
    versions = {lbl: lay.get("version") for lbl, lay in (("global", g), ("project", p)) if isinstance(lay, dict) and "version" in lay}
    if len(set(versions.values())) > 1:
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
    if bare not in ALIASES and bare not in ALIASES.values():
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

def cmd_resolve(a):
    warnings = []
    if a.surface not in SURFACES:
        sys.stderr.write(f"usage: --surface one of {SURFACES}\n")
        return 2
    merged, _ = _merged_policy(a.project_root, warnings)
    tier_req = a.tier or (merged.get("defaults") or {}).get("tier", "medium")
    tier_used = tier_req
    escalated = False
    if a.escalate:
        tier_used, escalated = _escalate(tier_req, warnings)
    source = "tier"
    model = None
    pin = (merged.get("agents") or {}).get(a.agent) if a.agent else None
    if pin is not None:
        model = _shape_for_surface(pin, a.surface, warnings)
        source = "agent-pin"
    else:
        tiers = merged.get("tiers") or {}
        if tier_used not in tiers:
            dt = (merged.get("defaults") or {}).get("tier", "medium")
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
    out = {
        "ok": True, "model": model, "tier": tier_used, "tier_requested": tier_req,
        "escalated": escalated, "surface": a.surface, "agent": a.agent,
        "source": source, "warnings": warnings,
    }
    if not a.no_log:
        rec = {
            "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task": (a.task or "")[:TRUNCATE], "tier_requested": tier_req, "tier": tier_used,
            "escalated": escalated, "surface": a.surface, "agent": a.agent, "model": model,
            "source": source, "reason": (a.reason or "")[:TRUNCATE], "policy_sha256": _policy_sha256(merged),
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
