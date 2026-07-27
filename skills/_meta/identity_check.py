#!/usr/bin/env python3
"""identity_check.py — 3-tree byte-identity check for safety-critical _meta files.

Part of Ecosystem Evergreening v1 (S041); DETECTION half shipped S041, the
ENFORCEMENT (remediation) half is S043 / #119 (review G5). The security-relevant
_meta engines (gates.py, claims.py, trusted_runner.py, classify.py, …) exist in
three trees — production, the foundry-lab shadow, and the agent-foundry publish
mirror — with NO gate asserting they are byte-identical. Task #62 already
reconciled a prod-vs-shadow drift once.

S043 / §9 (Codex resolutions, BINDING) fixes a CRITICAL checker-core bug:

  C1 — a MISSING safety file used to report `match`.
       The old comparison only looked at "trees where the file exists"
       (`present_digests`, ≥2 present + identical -> match). A completely ABSENT
       safety file (the most severe drift — exactly the live agent-foundry state
       for classify.py / classify_emit.py) was invisible, and `main()` hardcoded
       `exit 0`, so there was no usable gate exit code. Now there is a `--strict`
       mode: for the selected pair, EVERY selected file MUST exist in EVERY
       selected tree; a missing file OR a missing tree = `mismatch` and `main()`
       returns non-zero (2). The lenient legacy behaviour is preserved under
       `--advisory` (the SessionStart nudge keeps using it).

  C5 — the checker itself + other unwatched safety files were not in
       CRITICAL_FILES; a weakened checker would pass while watched files looked
       clean. CRITICAL_FILES now self-includes identity_check.py and the other
       enforcement / nudge engines, governed by an explicit inclusion policy.

  C6 — strict --pair prod-foundry must FAIL with setup guidance (or accept an
       explicit --foundry-root / PUBLIC_REPO_ROOT) when the published clone is
       absent — never silently pass. --pair prod-shadow is unaffected.

Pairs (design §2 — trees have DIFFERENT freshness contracts):
  prod-shadow   : ~/.claude  vs  foundry-lab  — MUST match at every commit
                  boundary (a drift here is a real bug).
  prod-foundry  : ~/.claude  vs  agent-foundry  — match at PUBLISH time only;
                  lag between publishes is benign. The publish SCRIPT reconciles
                  before commit (C2); this gate is the assertion.
  all           : all three trees.

stdlib-only, deterministic. The advisory path writes ONLY
~/.claude/state/freshness/identity-report.json. The strict path writes nothing
to disk (gate semantics; --no-write also honoured) so it can ride telemetry
under a forced ImportError without a write side effect.

CLI:
  identity_check.py [--trees t1,t2,t3] [--files a,b] [--json] [--no-write]
                    [--advisory | --strict]
                    [--pair prod-shadow|prod-foundry|all]
                    [--foundry-root <path>]

Exit codes:
  0  match (or advisory mode — always 0)
  2  strict mismatch (drifted file, missing file, or missing required tree)
  3  environmental (strict --pair prod-foundry with no agent-foundry clone and
     no --foundry-root / PUBLIC_REPO_ROOT)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPORT_SCHEMA = "identity-report.v1"
CHECKER_VERSION = "1.1.0"  # S043: +strict/+pair/+foundry-root; presence-required

HOME = Path(os.environ.get("HOME", str(Path.home())))
STATE_FRESH = HOME / ".claude" / "state" / "freshness"
REPORT_FILE = STATE_FRESH / "identity-report.json"

# ---------------------------------------------------------------------------
# The three trees that hold _meta copies. Tree roles are NAMED (C6/§2) so the
# --pair filter can select the right subset and so missing-clone guidance can
# name which tree is absent.
#
# S054: shadow/foundry paths come from env vars or a config file OUTSIDE the
# published tree (~/.claude/state/identity-trees.json) — never hardcoded here.
# Private path literals in this file were path-scrubbed by the publish
# pipeline, making the published copy of THIS CHECKER hash-differ from
# prod/shadow and trip its own self-check (the 2026-06-08 "3-tree MISMATCH"
# false positive). With paths externalized, all three copies stay
# byte-identical.
# ---------------------------------------------------------------------------
PROD_TREE = HOME / ".claude" / "skills" / "_meta"

_TREES_CONFIG = HOME / ".claude" / "state" / "identity-trees.json"


def _configured_tree(env_var: str, config_key: str, role: str) -> Path:
    """Resolve a tree path from env var, then config file, else a sentinel.

    The sentinel is a path that never exists on disk, so the existing
    missing-tree machinery applies unchanged (advisory -> partial,
    strict -> mismatch / ENV_ERROR guidance).
    """
    val = os.environ.get(env_var)
    if val:
        return Path(val)
    try:
        cfg = json.loads(_TREES_CONFIG.read_text(encoding="utf-8"))
        if cfg.get(config_key):
            return Path(cfg[config_key])
    except (OSError, ValueError):
        pass
    return Path(f"<unconfigured:{role}>")


SHADOW_TREE = _configured_tree(
    "CLAUDE_IDENTITY_SHADOW_TREE", "shadow_tree", "shadow-tree")
FOUNDRY_TREE_DEFAULT = _configured_tree(
    "CLAUDE_IDENTITY_FOUNDRY_TREE", "foundry_tree", "foundry-tree")

# S055: repo-ROOT trees (for the --watchlist coverage that spans workflows/,
# agents/, skills/_meta/...). PROD repo root is ~/.claude; SHADOW/FOUNDRY repo
# roots come from identity-trees.json shadow_root/foundry_root.
PROD_ROOT = HOME / ".claude"
SHADOW_ROOT = _configured_tree(
    "CLAUDE_IDENTITY_SHADOW_ROOT", "shadow_root", "shadow-root")
FOUNDRY_ROOT_DEFAULT = _configured_tree(
    "CLAUDE_IDENTITY_FOUNDRY_ROOT", "foundry_root", "foundry-root")

# Backwards-compatible ordered default (prod, shadow, agent-foundry).
DEFAULT_TREES = [PROD_TREE, SHADOW_TREE, FOUNDRY_TREE_DEFAULT]

GOVERNANCE_WATCHLIST = HOME / ".claude" / "skills" / "_meta" / "governance_watchlist.json"
SCHEMAS_DIR = HOME / ".claude" / "skills" / "_meta" / "schemas"
REGISTRY_FILE = SCHEMAS_DIR / "registry.v1.json"

# ---------------------------------------------------------------------------
# CRITICAL_FILES — the safety-critical subset (NOT the whole _meta dir).
#
# INCLUSION POLICY (C5, §9): a file belongs here if its drift across trees can
# silently weaken a GATE, an ENFORCEMENT decision, or a SessionStart SAFETY
# NUDGE. Concretely:
#   - gate engines (gates.py and the modules it dispatches into / depends on:
#     claims.py, trusted_runner.py, pause_state.py, scope_delta.py,
#     classify.py, classify_emit.py),
#   - cold-context verifier spawners (audit_spawn.py, *_arbiter_spawn.py),
#   - the HARD-RULE scan / apply machinery (hard_rules_common.py,
#     apply_project_hard_rules.py, scan_hard_rules.py),
#   - the SessionStart freshness nudge (freshness_nudge.py),
#   - and THIS checker itself (identity_check.py) — a weakened checker that
#     drifted in one tree would otherwise pass while everything else "looked
#     clean" (the bootstrap hole C5 closes).
#
# A test (test_identity_check.py::test_critical_subset_full_coverage) asserts
# that EVERY *.py in the prod _meta tree matching this policy is listed, so the
# list cannot silently drift behind reality (full coverage, not spot-check).
# ---------------------------------------------------------------------------
CRITICAL_FILES = [
    # --- gate + ledger + execution engines ---
    "gates.py",
    "claims.py",
    "trusted_runner.py",
    "pause_state.py",
    "scope_delta.py",
    # scope_reaction.py is the SOLE production caller of
    # pause_state.request_pause (HARD-RULE 6 / CB4) — its drift could silently
    # break scope-pause enforcement. (Caught by the C5 full-coverage test.)
    "scope_reaction.py",
    # scope_delta_compact_nudge.py is the SessionStart surface for scope-delta
    # state. Drift here silences the nudge without any other signal, so it is a
    # safety file by the same argument as scope_reaction.py. It shipped into
    # prod _meta without being added here — exactly the omission C5 exists to
    # catch, and C5 did catch it.
    "scope_delta_compact_nudge.py",
    # --- cold-context verifier spawners ---
    "audit_spawn.py",
    "verification_arbiter_spawn.py",
    "visual_arbiter_spawn.py",
    "design_drift_arbiter_spawn.py",
    # --- component-classification front door (S042 / #115) ---
    # Its drift would silently re-open the bare-N/A skip hole.
    "classify.py",
    "classify_emit.py",
    # --- HARD-RULE scan / apply machinery + SessionStart safety nudge +
    #     the checker itself (S043 / #119 C5) ---
    "identity_check.py",
    "hard_rules_common.py",
    "apply_project_hard_rules.py",
    "scan_hard_rules.py",
    "freshness_nudge.py",
]


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Pair resolution (C6/§2)
# ---------------------------------------------------------------------------
def resolve_pair(pair: str, foundry_root: Path | None = None) -> list[Path]:
    """Map a pair name to its ordered tree list.

    `foundry_root`, when given, overrides the default agent-foundry path (and
    may also come from the PUBLIC_REPO_ROOT env var, resolved by the caller).
    The returned path points at the `_meta` subdir of the foundry clone.
    """
    foundry = foundry_root if foundry_root is not None else FOUNDRY_TREE_DEFAULT
    if pair == "prod-shadow":
        return [PROD_TREE, SHADOW_TREE]
    if pair == "prod-foundry":
        return [PROD_TREE, foundry]
    if pair == "all":
        return [PROD_TREE, SHADOW_TREE, foundry]
    raise ValueError(f"unknown pair: {pair!r} (expected prod-shadow|prod-foundry|all)")


def _resolve_foundry_root(explicit: str | None) -> Path | None:
    """Resolve the foundry _meta dir from --foundry-root or PUBLIC_REPO_ROOT.

    Accepts either a path to the repo root (…/agent-foundry) or directly to its
    skills/_meta. Returns None if neither source is set.
    """
    raw = explicit if explicit else os.environ.get("PUBLIC_REPO_ROOT")
    if not raw:
        return None
    p = Path(raw)
    # If they pointed at the repo root, descend into skills/_meta.
    if (p / "skills" / "_meta").is_dir():
        return p / "skills" / "_meta"
    return p


# ---------------------------------------------------------------------------
# Core comparison. `strict` toggles presence-required semantics (C1).
# ---------------------------------------------------------------------------
def run_check(trees: list[Path], files: list[str], strict: bool = False) -> dict:
    """Hash `files` across `trees`.

    Lenient (strict=False, the legacy/advisory path): a file is `match` when the
    trees that HAVE it agree; <2 copies -> `partial`; a missing TREE -> overall
    `partial` (coverage). Backwards compatible with S041 callers/tests.

    Strict (strict=True, the gate path — C1): EVERY selected file MUST exist in
    EVERY selected tree AND be byte-identical. A missing file -> `mismatch`. A
    missing tree -> every file is `mismatch` (the tree cannot satisfy presence)
    and the overall status is `mismatch`, NOT `partial`. This is what makes the
    most-severe drift (a deleted/never-published safety file) visible.
    """
    t0 = time.time()
    tree_labels = [str(t) for t in trees]
    present = [t for t in trees if t.is_dir()]
    missing = [str(t) for t in trees if not t.is_dir()]

    per_file = {}
    mismatch_count = 0
    missing_file_count = 0
    for fname in files:
        digests = {}
        for t in trees:
            fp = t / fname
            digests[str(t)] = _sha256(fp)  # None when absent / unreadable
        present_digests = {k: v for k, v in digests.items() if v is not None}
        distinct = set(present_digests.values())
        absent_in = [k for k, v in digests.items() if v is None]

        if strict:
            # Presence-required: every selected tree must have the file AND all
            # digests must agree.
            if absent_in:
                status = "mismatch"
                mismatch_count += 1
                missing_file_count += 1
            elif len(distinct) > 1:
                status = "mismatch"
                mismatch_count += 1
            else:
                status = "match"
        else:
            # Legacy/advisory: compare only where present.
            if len(present_digests) < 2:
                status = "partial"  # not enough copies to compare
            elif len(distinct) > 1:
                status = "mismatch"
                mismatch_count += 1
            else:
                status = "match"

        per_file[fname] = {
            "status": status,
            "digests": {k: (v[:16] if v else None) for k, v in digests.items()},
            "distinct_count": len(distinct),
            "absent_in": absent_in,
        }

    if strict:
        # In strict mode a missing TREE means presence cannot be satisfied ->
        # already reflected as per-file mismatches above; overall is mismatch
        # whenever ANY file mismatched (incl. missing-file/missing-tree).
        overall = "mismatch" if mismatch_count > 0 else "match"
    else:
        if mismatch_count > 0:
            overall = "mismatch"
        elif len(present) < len(trees):
            overall = "partial"
        else:
            overall = "match"

    coverage = "full" if not missing else "partial"
    runtime_ms = int((time.time() - t0) * 1000)
    return {
        "schema_version": REPORT_SCHEMA,
        "checker_version": CHECKER_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "strict" if strict else "advisory",
        "status": overall,
        "coverage": coverage,
        "trees": tree_labels,
        "trees_present": [str(t) for t in present],
        "trees_missing": missing,
        "files_checked": files,
        "mismatch_count": mismatch_count,
        "missing_file_count": missing_file_count,
        "last_success": True,
        "last_error": None,
        "runtime_ms": runtime_ms,
        "per_file": per_file,
    }


def write_report(report: dict) -> None:
    try:
        STATE_FRESH.mkdir(parents=True, exist_ok=True)
        tmp = REPORT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(REPORT_FILE))
    except OSError:
        pass


def _print_human(report: dict) -> None:
    print(f"identity_check v{CHECKER_VERSION}: mode={report['mode']} "
          f"status={report['status']} coverage={report['coverage']} "
          f"mismatches={report['mismatch_count']} "
          f"({len(report['trees_present'])}/{len(report['trees'])} trees) "
          f"in {report['runtime_ms']}ms")
    for fname, info in report["per_file"].items():
        if info["status"] == "mismatch":
            if info["absent_in"]:
                print(f"  MISMATCH {fname}: ABSENT in:")
                for tree in info["absent_in"]:
                    print(f"    (missing)         {tree}")
                # Also show the digests of trees that DO have it.
                for tree, dig in info["digests"].items():
                    if dig is not None:
                        print(f"    {dig}  {tree}")
            else:
                print(f"  MISMATCH {fname}:")
                for tree, dig in info["digests"].items():
                    print(f"    {dig}  {tree}")
    if report["trees_missing"]:
        for t in report["trees_missing"]:
            tag = "(tree missing — MISMATCH in strict)" if report["mode"] == "strict" \
                else "(tree missing — partial)"
            print(f"  {tag} {t}")


def _registry_paths() -> dict:
    # Registry `path` values are relative to the skills/ dir (e.g.
    # "_meta/schemas/work-packages.v1.json", "forge/schemas/...").
    skills_dir = HOME / ".claude" / "skills"
    try:
        rows = json.loads(REGISTRY_FILE.read_text())["schemas"]
    except (OSError, ValueError, KeyError):
        return {}
    return {r["name"]: skills_dir / r["path"] for r in rows}


_TWIN_RE = re.compile(r"//\s*SCHEMA-TWIN:\s*(\S+)\s+sha256:([0-9a-f]{16})")


def run_watchlist(strict: bool = False, shadow_root: Path | None = None) -> dict:
    """S055 §10 — walk governance_watchlist.json: for every entry's file, compare
    PROD_ROOT/<rel> against SHADOW_ROOT/<rel> byte-for-byte AND verify any
    SCHEMA-TWIN annotation hash inside a workflow file matches its canonical
    schema. Returns a structured report. Advisory by default (exit 0 with
    findings); strict makes drift non-zero.

    Self-watched: identity_check.py is itself in the meta-docs class only via the
    critical-subset; the watchlist's meta-docs entry covers the orchestration
    docs. Deploy-order (lab edit -> test -> byte-copy to prod -> publish) keeps
    the two trees aligned within one cycle."""
    shadow = shadow_root if shadow_root is not None else SHADOW_ROOT
    report = {"mode": "watchlist", "entries": [], "drift": [], "twin_mismatch": [], "missing": []}
    try:
        wl = json.loads(GOVERNANCE_WATCHLIST.read_text())
    except (OSError, ValueError) as e:
        report["error"] = f"cannot read governance_watchlist.json: {e}"
        return report

    reg = _registry_paths()
    for entry in wl.get("entries", []):
        eid = entry.get("id")
        entry_rec = {"id": eid, "role": entry.get("role"), "files_checked": 0, "drift": [], "missing": []}
        for rel in entry.get("files", []):
            prod_f = PROD_ROOT / rel
            shadow_f = shadow / rel
            if not prod_f.is_file():
                entry_rec["missing"].append(f"prod:{rel}")
                report["missing"].append(f"prod:{rel}")
                continue
            if not shadow_f.is_file():
                entry_rec["missing"].append(f"shadow:{rel}")
                report["missing"].append(f"shadow:{rel}")
                continue
            entry_rec["files_checked"] += 1
            if prod_f.read_bytes() != shadow_f.read_bytes():
                entry_rec["drift"].append(rel)
                report["drift"].append(rel)
            # SCHEMA-TWIN annotation hash check (workflow .js files only).
            if rel.endswith(".js"):
                text = prod_f.read_text()
                for m in _TWIN_RE.finditer(text):
                    name, hash16 = m.group(1), m.group(2)
                    canon = reg.get(name)
                    if canon is None or not canon.is_file():
                        report["twin_mismatch"].append(f"{rel}: {name} not in registry / canonical missing")
                        continue
                    full = hashlib.sha256(canon.read_bytes()).hexdigest()
                    if not full.startswith(hash16):
                        report["twin_mismatch"].append(f"{rel}: {name} twin {hash16} != canonical {full[:16]}")
        report["entries"].append(entry_rec)
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="identity_check.py",
        description="3-tree byte-identity check (#119: detection S041, enforcement S043)")
    p.add_argument("--trees", default=None,
                   help="comma-separated tree paths (overrides --pair)")
    p.add_argument("--files", default=None,
                   help="comma-separated filenames (default: the critical subset)")
    p.add_argument("--pair", default=None,
                   choices=["prod-shadow", "prod-foundry", "all"],
                   help="tree pair to compare (ignored if --trees given)")
    p.add_argument("--foundry-root", default=None,
                   help="path to the agent-foundry clone (repo root or its "
                        "skills/_meta); also read from PUBLIC_REPO_ROOT env")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--watchlist", action="store_true",
                   help="S055: walk governance_watchlist.json (workflows + agents "
                        "+ meta-docs prod<->shadow parity + SCHEMA-TWIN hashes)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--strict", action="store_true",
                      help="presence-required + match-required; non-zero on drift")
    mode.add_argument("--advisory", action="store_true",
                      help="legacy lenient detection; always exit 0 (default)")
    args = p.parse_args(argv)

    strict = bool(args.strict)  # advisory is the default when neither is given

    # S055 --watchlist mode: governance coverage spanning repo-root trees.
    if args.watchlist:
        report = run_watchlist(strict=strict)
        if args.json:
            sys.stdout.write(json.dumps(report, indent=2) + "\n")
        else:
            n_checked = sum(e["files_checked"] for e in report.get("entries", []))
            sys.stdout.write(f"[watchlist] files checked: {n_checked}\n")
            for d in report.get("drift", []):
                sys.stdout.write(f"  DRIFT: {d}\n")
            for m in report.get("missing", []):
                sys.stdout.write(f"  MISSING: {m}\n")
            for tm in report.get("twin_mismatch", []):
                sys.stdout.write(f"  TWIN-MISMATCH: {tm}\n")
            if "error" in report:
                sys.stdout.write(f"  ERROR: {report['error']}\n")
            if not (report.get("drift") or report.get("missing") or report.get("twin_mismatch") or report.get("error")):
                sys.stdout.write("  clean — all watchlist entries parity-matched, all twins valid\n")
        has_issue = bool(report.get("drift") or report.get("missing") or report.get("twin_mismatch") or report.get("error"))
        if strict and has_issue:
            return 1
        return 0

    # Resolve the tree set.
    foundry_root = _resolve_foundry_root(args.foundry_root)
    if args.trees:
        trees = [Path(x) for x in args.trees.split(",")]
    elif args.pair:
        # C6: strict --pair prod-foundry with no clone -> environmental fail w/
        # setup guidance, NOT a silent pass and NOT a misleading "mismatch".
        if args.pair in ("prod-foundry", "all"):
            foundry = foundry_root if foundry_root is not None else FOUNDRY_TREE_DEFAULT
            if not foundry.is_dir():
                if strict:
                    sys.stderr.write(
                        "ENV_ERROR: agent-foundry clone not found at "
                        f"{foundry}.\n"
                        "  The prod-foundry identity check needs the published "
                        "repo present.\n"
                        "  Fix one of:\n"
                        "    - clone it:  gh repo clone your-gh-user/agent-foundry "
                        "<dest>\n"
                        "    - point at an existing clone:  "
                        "--foundry-root /path/to/agent-foundry\n"
                        "    - set PUBLIC_REPO_ROOT=/path/to/agent-foundry\n"
                        "    - or set foundry_tree in "
                        "~/.claude/state/identity-trees.json\n"
                        "  (prod-shadow is unaffected and can be checked "
                        "standalone.)\n")
                    return 3
                # advisory: fall through; missing tree -> partial (legacy).
        trees = resolve_pair(args.pair, foundry_root)
    else:
        trees = DEFAULT_TREES

    files = args.files.split(",") if args.files else CRITICAL_FILES

    report = run_check(trees, files, strict=strict)

    # Strict is a gate: do NOT write the freshness report (no side effect, so it
    # stays byte-invariant under a forced telemetry ImportError). Advisory keeps
    # writing unless --no-write.
    if not strict and not args.no_write:
        write_report(report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)

    # Exit code contract:
    #   advisory -> always 0 (detection nudge; CRITICAL surfaced elsewhere)
    #   strict   -> 2 on any mismatch (drift / missing file / missing tree), else 0
    if strict:
        return 2 if report["status"] == "mismatch" else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
