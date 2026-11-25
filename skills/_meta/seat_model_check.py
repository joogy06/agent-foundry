#!/usr/bin/env python3
"""seat_model_check.py - `seat_model.py check`: validate the model roster, no model calls.

#291 design s3.3 (plan WP-2). The `check` subcommand of seat_model.py dispatches here. It lives
in its own module on purpose: seat_model.py is the resolver every spawner imports, and it
imports no process or network library (test_module_imports_no_network_or_process_library).
Validation, by contrast, MUST spawn - each item runs in a FRESH subprocess so it tests the
files on disk, not constants this process already imported. Keeping the spawning here keeps
the resolver process-free; the check's judgement reuses seat_model's own helpers (is_benched
is the one normaliser, never copied).

WHAT IS CHECKED. The tree the running seat_model.py lives in (the repo, or an installed
~/.claude; --root names another):
  1 roster     model_roster invariants (roster_violations, and a fresh `import seat_model`)
  2 emit       `emit --json`, unsized and at every size: every role x provider resolves, no
               Claude pin is benched, roster_rev equals the on-disk REVISION
  2b codex     (#302 design s3.4) the codex TIERS against the codex roster on disk: CODEX_STD
               and CODEX_SUPPORT are each present, listed, supported_in_api and offer every
               effort their seats ask for (std: the sized main rows plus medium, the
               codex_model cheap-path/raw-tier effort; support: the consultant_support row,
               medium), and neither is the model a codex TOP seat resolves to now (a vendor
               priority inversion onto a tier model). A deliberate home-tier FREEZE of the
               codex TOP onto a tier is a WARN (legitimate per design; the frozen TOP seats are
               billed std, and the WARN names a roster inversion the freeze hides), never a
               failure. CODEX_STD == CODEX_SUPPORT is a WARN, never a failure (#302 JC-1: a
               runbook s7 revert to a rev-1/2 row is legal), and so is a host with no codex
               roster to judge against.
  3 avengers   `convene.py --profile P --dry-run` for every shipped profile, and no seat or
               arbiter of the dry-run review is a benched Claude model
  4 smart      smart-config `resolve --tier complex|medium|light --no-log` returns no
               benched model (project layer: the checked tree)
  5 lint       no spawn literal naming a benched family (a model= / --model / value=
               assignment, or a `models` map line) in shipped non-test files of skills/,
               agents/, commands/, workflows/, CLAUDE.md and install.py while that family is
               benched. Allowed: model_roster.py, and any line carrying the marker
               `roster-lint: allow` (legacy-alias compat, served-id matching). The lint only
               READS files, so it runs in this process; its benched set comes from item 1's
               subprocess (the roster on disk).
  6 --home     items 1-2 against ~/.claude/skills/_meta and a drift comparison of
               REVISION / main / support / benched / codex std / codex support with the checked tree. A
               pre-#291 installed copy (no model_roster.py) fails roster and drift, and its
               emit is judged against the checked tree's benched set.

ISOLATION. Items 1-4 run under a TEMPORARY HOME seeded with COPIES of the home-tier read-only
inputs (codex models_cache.json, agy-models.json, seat-model-pins.json, seat-model-tops.json,
model-policy.yaml), with bytecode writing off (-B and PYTHONDONTWRITEBYTECODE): the live home
is only ever read, no live budget store or tops record is reachable, and nothing is written
into an installed tree's __pycache__. No codex, agy or claude binary is ever run (children
are sys.executable only; convene --dry-run decides admission check-only).

OUTPUT. A report on stdout: one `PASS <item>: ...`, `FAIL <item>: ...` or `WARN <item>: ...`
line per result and a summary line. Exit 0 = no item failed (a WARN never changes the exit);
exit 1 = at least one failure, each named on its own FAIL line. A roster so broken that seat_model.py itself cannot import fails before `check`
runs, with the violations on stderr (the import-time fail-closed rule of design s3.1).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import site
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

_META = Path(__file__).resolve().parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))
from seat_model import (  # noqa: E402
    CLAUDE, CLAUDE_EFFORTS, EXIT_OK, EXIT_RESOLUTION_FAILED, ROLES, ROSTER_REV, SIZES, SeatModelError, _ascii, is_benched)

#: The tree this file lives in (skills/_meta/seat_model_check.py -> the tree root).
_TREE_ROOT = _META.parent.parent

#: Per-subprocess wall clock. Every item is a local file read or a dry run (well under a
#: second each today); the cap only bounds a hung child so `check` finishes in minutes.
CHECK_ITEM_TIMEOUT_S = 120
#: The home-tier READ-ONLY inputs copied into the temporary HOME (relative to a home).
_CHECK_SEED_FILES: Tuple[Tuple[str, ...], ...] = (
    (".codex", "models_cache.json"),
    (".claude", "state", "agy-models.json"),
    (".claude", "state", "seat-model-pins.json"),
    (".claude", "state", "seat-model-tops.json"),
    (".claude", "model-policy.yaml"),
)
#: smart-config tiers whose resolution must never be a benched model.
CHECK_POLICY_TIERS: Tuple[str, ...] = ("complex", "medium", "light")
#: The roster fields compared by the --home drift check.
_CHECK_DRIFT_KEYS: Tuple[str, ...] = ("revision", "main", "support", "benched", "codex_std", "codex_support",
                                      "agy_family", "agy_harness_version", "agy_level_by_size")
#: Lint scope: the trees install.py ships (its four manifest categories plus the bundled
#: templates/ - settings.global.json, agy.md), plus the shipped top-level files (global/CLAUDE.md
#: is the source of ~/.claude/CLAUDE.md since #318).
_LINT_TREES: Tuple[str, ...] = ("skills", "agents", "commands", "workflows", "templates")
_LINT_TOP_FILES: Tuple[str, ...] = ("CLAUDE.md", "global/CLAUDE.md", "install.py")
_LINT_SUFFIXES: FrozenSet[str] = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".ps1", ".md", ".yaml", ".yml", ".json", ".toml"})
#: Directories never scanned: tests and their fixtures are not shipped code.
_LINT_SKIP_DIRS: FrozenSet[str] = frozenset({
    "tests", "test", "fixtures", "__pycache__", "node_modules", ".git"})
#: Files the lint never flags, relative to the checked root (the roster itself holds the
#: benched families and the history by design).
_LINT_ALLOW_FILES: FrozenSet[str] = frozenset({"skills/_meta/model_roster.py"})
#: A line carrying this marker is never flagged (legacy-alias compat, served-id matching).
LINT_ALLOW_MARKER = "roster-lint: allow"

#: Run in a fresh interpreter with the target _meta dir as argv[1]. Prints ONE JSON object:
#: {"roster": {...} | null, "violations": [...]}. Never raises: every failure is a violation.
_ROSTER_PROBE = r'''
import json, sys
meta = sys.argv[1]
sys.path.insert(0, meta)
out = {"roster": None, "violations": []}
try:
    import model_roster as r
except Exception as exc:
    out["violations"].append("model_roster.py does not import from %s: %s: %s" % (meta, type(exc).__name__, exc))
else:
    def _get(name):
        return getattr(r, name, None)
    benched = _get("CLAUDE_BENCHED")
    out["roster"] = {
        "revision": _get("REVISION"), "main": _get("CLAUDE_MAIN"), "support": _get("CLAUDE_SUPPORT"),
        "benched": sorted(benched) if isinstance(benched, (set, frozenset, tuple, list)) else benched,
        "codex_std": _get("CODEX_STD"),
        # #302 JC-1: a roster without CODEX_SUPPORT (rev 1/2) reads it as its CODEX_STD.
        "codex_support": getattr(r, "CODEX_SUPPORT", _get("CODEX_STD")),
        # #367 (Sol C10): the agy family is roster data from rev 6; None on an older roster.
        "agy_family": _get("AGY_FAMILY"), "agy_harness_version": _get("AGY_HARNESS_VERSION"),
        # #367 WP-C: the agy size -> level map is roster data from rev 7; None on an older roster.
        "agy_level_by_size": _get("AGY_LEVEL_BY_SIZE"),
    }
    prefix = "model_roster.py violates its invariants: "
    try:
        import seat_model
    except Exception as exc:
        text = str(exc)
        if text.startswith(prefix):
            out["violations"].extend(text[len(prefix):].split("; "))
        else:
            out["violations"].append("seat_model.py does not import: %s: %s" % (type(exc).__name__, text))
    else:
        probe = getattr(seat_model, "roster_violations", None)
        if probe is None:
            out["violations"].append("seat_model.py in %s has no roster_violations (a pre-#291 copy)" % meta)
        else:
            out["violations"].extend(probe())
try:
    # D21 fix round 2 (N1): what the roster ALONE resolves the TOP seats to (the freeze and a
    # freeze-written tops record excluded) - the set seat_model bills non-TOP rows against.
    rt = sm._codex_top_models(sm._paths(), None, include_freeze=False)
    out["roster_tops"] = None if rt is None else sorted(rt)
except Exception:
    out["roster_tops"] = None
print(json.dumps(out, default=str))
'''


#: Item 2b's probe (#302). Run in a fresh interpreter with the target _meta dir as argv[1] under
#: the temporary HOME. Prints ONE JSON object describing the codex tiers, the roster entries that
#: name them and the model each codex TOP seat resolves to now. Never raises. Resolving a TOP
#: seat writes only the temporary HOME's tops record; no model is called.
_CODEX_PROBE = r'''
import json, sys
meta = sys.argv[1]
sys.path.insert(0, meta)
out = {"error": None, "std": None, "support": None, "efforts": {}, "roster": None, "roster_error": None,
       "entries": {}, "tops": {}, "top_errors": {}, "frozen": None, "frozen_error": None,
       "roster_tops": None}
try:
    import model_roster as r, seat_model as sm, codex_model as cm
except Exception as exc:
    out["error"] = "the checked tree does not import: %s: %s" % (type(exc).__name__, exc)
    print(json.dumps(out, default=str)); raise SystemExit(0)
std = getattr(r, "CODEX_STD", None)
support = getattr(r, "CODEX_SUPPORT", std)
out["std"], out["support"] = std, support
table, codex = sm.ROLE_TABLE, sm.CODEX
sized = getattr(sm, "SIZED_ROLES", frozenset())
std_efforts = getattr(sm, "codex_std_efforts", None)
out["efforts"] = {
    # D21 fix round 1 (F2): std also serves `medium` (codex_model.DEFAULT_MODEL is CODEX_STD: the
    # cheap-path row and raw-tier convene seat classes run on it; runbook s6), which no sized row asks for.
    # The astra reserve F6: and every literal CODEX_STD row's effort (consultant_main / arbiter @ xhigh),
    # read from seat_model.codex_std_efforts; a pre-rev-4 tree derives it from the sized rows as before.
    "std": sorted(std_efforts()) if std_efforts is not None else
           sorted({str(table[role][codex].effort) for role in sized if codex in table.get(role, {})}
                  | {"medium"}),
    "support": sorted({str(table[role][codex].effort) for role in table
                       if codex in table[role] and table[role][codex].kind == sm.KIND_LITERAL
                       and table[role][codex].value == support}),
}
try:
    doc = cm.load_roster_entries(sm._paths().codex_roster)
except cm.CodexRosterInvalidError as exc:
    out["roster"], out["roster_error"] = "invalid", str(exc)
except cm.CodexModelError as exc:
    out["roster"], out["roster_error"] = "absent", str(exc)
else:
    out["roster"] = "ok"
    for slug in {std, support}:
        e = doc.entries.get(slug) if isinstance(slug, str) else None
        out["entries"][str(slug)] = None if e is None else {
            "visibility": e.visibility, "supported_in_api": bool(e.supported_in_api),
            "efforts": sorted(e.efforts), "priority": e.priority}
try:
    out["frozen"] = sm._freeze_pin(sm._paths(), codex)
except Exception as exc:
    out["frozen_error"] = "%s: %s" % (type(exc).__name__, exc)
for role in sorted(table):
    if codex in table[role] and sm.is_top(role, codex):
        try:
            out["tops"][role] = sm.resolve(role, codex).model
        except Exception as exc:
            out["top_errors"][role] = "%s: %s" % (type(exc).__name__, exc)
try:
    # D21 fix round 2 (N1): what the roster ALONE resolves the TOP seats to (the freeze and a
    # freeze-written tops record excluded) - the set seat_model bills non-TOP rows against.
    rt = sm._codex_top_models(sm._paths(), None, include_freeze=False)
    out["roster_tops"] = None if rt is None else sorted(rt)
except Exception:
    out["roster_tops"] = None
print(json.dumps(out, default=str))
'''


@dataclass
class _CheckContext:
    root: Path             # the checked tree (holds skills/, agents/, ...)
    source_home: Path      # the home the read-only inputs are copied FROM (never written)
    home: Path             # the temporary HOME every subprocess runs under
    work: Path             # the subprocess cwd and convene --project-root
    env: Dict[str, str]
    failures: List[str]
    passes: List[str]
    warnings: List[str] = field(default_factory=list)

    def fail(self, item: str, message: str) -> None:
        self.failures.append(f"{item}: {_ascii(message)}")

    def ok(self, item: str, message: str) -> None:
        self.passes.append(f"{item}: {_ascii(message)}")

    def warn(self, item: str, message: str) -> None:
        self.warnings.append(f"{item}: {_ascii(message)}")


def _check_env(home: Path) -> Dict[str, str]:
    """The subprocess environment: the temp HOME, no bytecode writes, the caller's user site."""
    env = dict(os.environ)
    # Keep user-site packages importable although HOME moves (site derives them from HOME).
    env.setdefault("PYTHONUSERBASE", site.getuserbase())
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def _seed_check_home(source_home: Path, home: Path) -> List[str]:
    """Copy the read-only home-tier inputs present under `source_home`; return what was copied."""
    copied: List[str] = []
    for parts in _CHECK_SEED_FILES:
        src = source_home.joinpath(*parts)
        if not src.is_file():
            continue
        dst = home.joinpath(*parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)   # reads the source; never touches it
        copied.append("/".join(parts))
    return copied


def _check_run(ctx: _CheckContext, argv: List[str]) -> Tuple[Optional[int], str, str]:
    """Run one item's child. (returncode | None on timeout or launch failure, stdout, stderr)."""
    try:
        done = subprocess.run(argv, cwd=str(ctx.work), env=ctx.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=CHECK_ITEM_TIMEOUT_S,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {CHECK_ITEM_TIMEOUT_S}s"
    except OSError as exc:
        return None, "", f"could not start: {exc}"
    return done.returncode, done.stdout or "", done.stderr or ""


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "(no output)"


def _check_roster(ctx: _CheckContext, meta: Path, label: str) -> Optional[Dict[str, Any]]:
    """Item 1: the roster invariants, from the files on disk. Returns the roster values or None."""
    item = f"roster[{label}]"
    code, out, err = _check_run(ctx, [sys.executable, "-B", "-c", _ROSTER_PROBE, str(meta)])
    try:
        doc = json.loads(out)
    except ValueError:
        ctx.fail(item, f"the roster probe printed no JSON (exit {code}): {_last_line(err)}")
        return None
    violations = [v for v in doc.get("violations") or [] if v]
    for violation in violations:
        ctx.fail(item, violation)
    roster = doc.get("roster")
    if not violations:
        ctx.ok(item, f"rev {roster.get('revision')}: main {roster.get('main')}, support "
                     f"{roster.get('support')}, benched {roster.get('benched')}, codex std "
                     f"{roster.get('codex_std')}, codex support {roster.get('codex_support')}, agy family "
                     f"{roster.get('agy_family')} (harness literal gemini-{roster.get('agy_harness_version')}-"
                     f"{roster.get('agy_family')}-<level>), agy level by size "
                     f"{roster.get('agy_level_by_size')}")
    return roster if isinstance(roster, dict) else None


def _benched_of(roster: Optional[Dict[str, Any]]) -> FrozenSet[str]:
    benched = (roster or {}).get("benched")
    if isinstance(benched, list):
        return frozenset(b for b in benched if isinstance(b, str) and b)
    return frozenset()


def _check_emit(ctx: _CheckContext, meta: Path, label: str, roster: Optional[Dict[str, Any]],
                fallback_benched: FrozenSet[str] = frozenset()) -> None:
    """Item 2: `emit --json` resolves every role x provider, unsized and at every size.

    With an unreadable roster (a pre-#291 copy) the Claude pins are still judged, against
    `fallback_benched` (the checked tree's set), and the missing roster_rev is a failure.
    """
    benched = _benched_of(roster) if roster is not None else fallback_benched
    script = meta / "seat_model.py"
    for size in (None,) + tuple(SIZES):
        item = f"emit[{label}{'' if size is None else ' --size ' + size}]"
        argv = [sys.executable, "-B", str(script), "emit", "--json"]
        if size is not None:
            argv += ["--size", size]
        code, out, err = _check_run(ctx, argv)
        if code != 0:
            ctx.fail(item, f"exit {code}: {_last_line(err)}")
            continue
        try:
            doc = json.loads(out)
            pins = doc["pins"]
        except (ValueError, KeyError, TypeError):
            ctx.fail(item, "stdout is not an emit document")
            continue
        problems: List[str] = []
        for role in ROLES:
            cells = pins.get(role) if isinstance(pins, dict) else None
            if not isinstance(cells, dict) or not cells:
                problems.append(f"role {role} missing")
                continue
            for provider, pin in sorted(cells.items()):
                model = pin.get("model") if isinstance(pin, dict) else None
                if not isinstance(model, str) or not model:
                    problems.append(f"{role} x {provider} has no model")
                elif provider == CLAUDE and is_benched(model, benched):
                    problems.append(f"{role} x claude serves benched {model!r}")
                if provider == CLAUDE and roster is not None and \
                        (not isinstance(pin, dict) or pin.get("effort") not in CLAUDE_EFFORTS):
                    # #311 U3: every Claude seat is dispatched at an explicit effort.
                    problems.append(f"{role} x claude has no explicit effort "
                                    f"({(pin or {}).get('effort') if isinstance(pin, dict) else None!r})")
        if roster is None:
            if not isinstance(doc.get(ROSTER_REV), int):
                problems.append("no roster_rev in the emit document (a pre-#291 copy)")
        elif doc.get(ROSTER_REV) != roster.get("revision"):
            problems.append(f"roster_rev {doc.get(ROSTER_REV)!r} != model_roster.REVISION "
                            f"{roster.get('revision')!r}")
        if size is not None and doc.get("size") != size:
            problems.append(f"sized emit reports size {doc.get('size')!r}")
        by_size = (roster or {}).get("agy_level_by_size")
        if isinstance(by_size, dict):
            # #367 WP-C: every emit shows the map, and a sized emit serves its level on every agy seat.
            if doc.get("agy_level_by_size") != by_size:
                problems.append(f"emit agy_level_by_size {doc.get('agy_level_by_size')!r} != the roster's "
                                f"{by_size!r}")
            if size is not None and doc.get("size") == size:
                for role in ROLES:
                    pin = (pins.get(role) or {}).get("agy") if isinstance(pins, dict) else None
                    model = pin.get("model") if isinstance(pin, dict) else None
                    if isinstance(model, str) and not model.endswith("-" + str(by_size.get(size))):
                        problems.append(f"{role} x agy at --size {size} serves {model!r}, not level "
                                        f"{by_size.get(size)!r}")
        for problem in problems:
            ctx.fail(item, problem)
        if not problems:
            ctx.ok(item, "every role x provider resolved")


def _check_codex_tiers(ctx: _CheckContext, meta: Path, label: str) -> None:
    """Item 2b (#302 design s3.4): the codex std and support tiers against the roster on disk."""
    item = f"codex[{label}]"
    code, out, err = _check_run(ctx, [sys.executable, "-B", "-c", _CODEX_PROBE, str(meta)])
    try:
        doc = json.loads(out)
    except ValueError:
        ctx.fail(item, f"the codex probe printed no JSON (exit {code}): {_last_line(err)}")
        return
    if doc.get("error"):
        ctx.fail(item, doc["error"])
        return
    std, support = doc.get("std"), doc.get("support")
    if std == support:
        ctx.warn(item, f"CODEX_STD == CODEX_SUPPORT ({std!r}): one codex model serves both tiers "
                       f"(legal - a rev-1/2 roster or a runbook revert - but the support tier is not split)")
    if doc.get("roster") == "absent":
        ctx.warn(item, f"no codex roster to judge the tiers against ({doc.get('roster_error')})")
        return
    if doc.get("roster") != "ok":
        ctx.fail(item, f"the codex roster is invalid: {doc.get('roster_error')}")
        return
    problems: List[str] = []
    efforts = doc.get("efforts") or {}
    entries = doc.get("entries") or {}
    tops = doc.get("tops") or {}
    for tier, slug in (("std", std), ("support", support)):
        what = f"codex {tier} {slug!r}"
        entry = entries.get(str(slug))
        if entry is None:
            problems.append(f"{what} is not in the codex roster")
            continue
        if entry.get("visibility") != "list":
            problems.append(f"{what} is not listed (visibility {entry.get('visibility')!r})")
        if not entry.get("supported_in_api"):
            problems.append(f"{what} is not supported_in_api")
        offered = set(entry.get("efforts") or ())
        for effort in efforts.get(tier) or ():
            if effort not in offered:
                problems.append(f"{what} does not offer effort {effort!r} (roster: {sorted(offered)})")
        on_top = sorted(role for role, model in tops.items() if model == slug)
        if on_top and doc.get("frozen") == slug:
            # D21 fix round 1 (m5b): a deliberate home-tier FREEZE onto a tier model is legitimate
            # per design (R1 bills it std) - named, never a failure.
            # D21 fix round 2 (N1): say exactly what is billed std. R1 bills the frozen TOP seats std
            # (seat_model.pin_model_class skips F1b for a TOP pin serving the active freeze); a
            # non-TOP seat serving the same model is billed top only when the ROSTER ALONE also
            # resolves the TOP onto it (a vendor inversion the freeze is hiding), which is named.
            roster_tops = doc.get("roster_tops")
            if roster_tops is None:
                also = ("; the roster-alone TOP could not be determined, so a non-TOP seat serving it is "
                        "billed by its row")
            elif slug in roster_tops:
                also = ("; the roster itself also ranks it TOP (a vendor inversion under the freeze), so "
                        "a non-TOP seat serving it is billed top")
            else:
                also = ""
            ctx.warn(item, f"{what} is the current codex TOP (served to {', '.join(on_top)}) because the "
                           f"codex TOP is frozen onto it (seat-model-pins.json): deliberate - the frozen TOP "
                           f"seats are billed std (R1){also}")
        elif on_top:
            problems.append(f"{what} is the current codex TOP (served to {', '.join(on_top)}): a TOP "
                            f"resolution onto a tier model - a vendor priority inversion (no freeze); the "
                            f"TOP reserve (model_roster.CODEX_TOP_ROLES) would silently vanish")
    for role, why in sorted((doc.get("top_errors") or {}).items()):
        problems.append(f"the codex TOP for {role} did not resolve, so it was not compared: {why}")
    for problem in problems:
        ctx.fail(item, problem)
    if not problems:
        served = sorted(set(tops.values()))
        if doc.get("frozen") in (std, support):
            # D21 fix round 2: under a freeze onto a tier the WARN above said so; never claim "not the TOP".
            ctx.ok(item, f"std {std} and support {support} are listed, API-supported and offer their "
                         f"efforts (codex TOP frozen onto {doc.get('frozen')})")
        else:
            ctx.ok(item, f"std {std} and support {support} are listed, API-supported, offer their efforts "
                         f"and are not the codex TOP ({', '.join(served) or 'none'})")


#: A `claude <model>` pair in a convene dry-run review (seats and the arbiter line).
_REVIEW_CLAUDE_MODEL = re.compile(r"\bclaude\s+([A-Za-z0-9][A-Za-z0-9.\[\]-]*)")


def _check_avengers(ctx: _CheckContext, benched: FrozenSet[str]) -> None:
    """Item 3: every shipped avengers profile passes `convene.py --profile P --dry-run`."""
    convene = ctx.root / "skills" / "avengers" / "scripts" / "convene.py"
    profiles = sorted((ctx.root / "skills" / "avengers" / "profiles").glob("*.yaml"))
    if not convene.is_file() or not profiles:
        ctx.fail("avengers", f"no convene.py or no shipped profile under {ctx.root / 'skills' / 'avengers'}")
        return
    for profile in profiles:
        item = f"avengers[{profile.stem}]"
        code, out, err = _check_run(ctx, [sys.executable, "-B", str(convene), "--profile", profile.stem,
                                          "--dry-run", "--project-root", str(ctx.work)])
        if code != 0:
            ctx.fail(item, f"--dry-run exit {code}: {_last_line(err)}")
            continue
        served = sorted({m for m in _REVIEW_CLAUDE_MODEL.findall(out) if is_benched(m, benched)})
        if served:
            ctx.fail(item, f"the dry run seats benched Claude model(s) {served}")
        else:
            ctx.ok(item, "dry run passed")


def _check_smart_config(ctx: _CheckContext, benched: FrozenSet[str]) -> None:
    """Item 4: smart-config never resolves a tier to a benched model."""
    script = ctx.root / "skills" / "smart-config" / "scripts" / "model_policy.py"
    if not script.is_file():
        ctx.fail("smart-config", f"no resolver at {script}")
        return
    for tier in CHECK_POLICY_TIERS:
        item = f"smart-config[{tier}]"
        code, out, err = _check_run(ctx, [sys.executable, "-B", str(script), "resolve", "--tier", tier,
                                          "--no-log", "--project-root", str(ctx.root)])
        try:
            doc = json.loads(out)
        except ValueError:
            ctx.fail(item, f"resolve printed no JSON (exit {code}): {_last_line(err)}")
            continue
        model = doc.get("model") if isinstance(doc, dict) else None
        if isinstance(model, str) and is_benched(model, benched):
            ctx.fail(item, f"resolves to benched {model!r} (source {doc.get('source')})")
        else:
            ctx.ok(item, f"resolves to {model!r}")


def _lint_patterns(benched: FrozenSet[str]) -> List[Tuple[str, "re.Pattern[str]"]]:
    """One compiled set per benched family: the spawn-literal shapes of design s3.3, widened
    in #291 fix round 1 (D) to the argv-list (`"--model", "<family>"`), dict / JSON key
    (`{"model": "<family>"}`), *_MODEL constant (`DEFAULT_MODEL = '<family>'`) and push()
    (`args.push('--model','<family>')`) spellings that used to lint clean."""
    out: List[Tuple[str, "re.Pattern[str]"]] = []
    quote = r"[\"'`]?"
    for family in sorted(benched):
        # The family as a model id, spelled the way model_ids.is_benched normalises it: bare,
        # vendor-prefixed with any separator ("claude-", "claude_", "Claude "), with a version
        # glued on as digits ("fable5") or following a separator, or a [1m] suffix - but not
        # glued to a longer word (so --<family>-touches-tests, <family>x and <family>5x are
        # not hits).
        # #291 fix round 2 N3: an optional vendor prefix before that - a path-style one
        # ("anthropic/", "vendor/") or a dotted one that leads into "claude" ("us.anthropic.").
        # A dotted attribute that does not lead into "claude" (self.fable_rung) stays clean.
        # Final re-review F2: any number of path segments, and a path segment may precede a
        # dotted one ("openrouter/anthropic/", "bedrock/us.anthropic.").
        vendor = r"(?:[\w.-]+/)*(?:(?:[\w-]+\.)+(?=claude))?"
        token = (r"(?<![\w-])" + vendor + r"(?:claude[-_.\s/@:]+)?" + re.escape(family)
                 + r"(?:\d+(?![A-Za-z0-9])|(?![A-Za-z0-9]))")
        # key, optional closing quote, separator, optional opening quote, value. No leading
        # \b on the key, so DEFAULT_MODEL / CLAUDE_MODEL constants are keys too; a letter
        # before it (e.g. "submodel") is still not.
        key_value = quote + r"\s*(?:=>|[=:])\s*" + quote
        # The key shapes match any case (an id is case-insensitive, as in is_benched); the
        # `models` map shape matches the lowercase id only, so a prose paragraph that
        # mentions models and names the family capitalised is not a hit.
        for shape, regex, flags in (
                # model / model_id / model_name / modelId / modelName (N3 widened the keys)
                ("model assignment", r"(?<![A-Za-z])model(?:_?id|_?name)?" + key_value + token,
                 re.IGNORECASE),
                ("--model flag", r"--model" + quote + r"\s*(?:[=,]\s*|\s+)" + quote + token, re.IGNORECASE),
                ("value assignment", r"(?<![A-Za-z])value" + key_value + token, re.IGNORECASE),
                ("models map", r"\bmodels\b.*" + token, 0)):
            out.append((f"{shape} naming benched {family!r}", re.compile(regex, flags)))
    return out


def _lint_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for tree in _LINT_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _LINT_SKIP_DIRS)
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.suffix.lower() not in _LINT_SUFFIXES:
                    continue
                if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
                    continue
                files.append(path)
    files.extend(root / name for name in _LINT_TOP_FILES if (root / name).is_file())
    return files


def lint_benched_literals(root: Path, benched: FrozenSet[str]) -> List[str]:
    """Item 5: every `path:line: shape` where shipped non-test text names a benched family."""
    patterns = _lint_patterns(benched)
    if not patterns:
        return []
    hits: List[str] = []
    for path in _lint_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in _LINT_ALLOW_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if LINT_ALLOW_MARKER in line:
                continue
            for label, pattern in patterns:
                if pattern.search(line):
                    hits.append(f"{rel}:{number}: {label}: {line.strip()[:160]}")
                    break
    return hits


def _check_lint(ctx: _CheckContext, roster: Optional[Dict[str, Any]]) -> None:
    if roster is None:
        ctx.fail("lint", "not run: the checked roster could not be read (see roster)")
        return
    hits = lint_benched_literals(ctx.root, _benched_of(roster))
    for hit in hits:
        ctx.fail("lint", hit)
    if not hits:
        ctx.ok("lint", f"no spawn literal names a benched family {sorted(_benched_of(roster))}")


def _check_drift(ctx: _CheckContext, repo: Optional[Dict[str, Any]], home: Optional[Dict[str, Any]]) -> None:
    """Item 6 (drift half): the installed roster must equal the checked tree's."""
    if repo is None or home is None:
        ctx.fail("drift", "not compared: " + ("the checked roster" if repo is None else "the home roster")
                 + " could not be read - run install.py")
        return
    differ = [key for key in _CHECK_DRIFT_KEYS if repo.get(key) != home.get(key)]
    if differ:
        ctx.fail("drift", "repo rev {} ({}) vs home rev {} ({}) - run install.py".format(
            repo.get("revision"), ", ".join(f"{k} {repo.get(k)!r}" for k in differ),
            home.get("revision"), ", ".join(f"{k} {home.get(k)!r}" for k in differ)))
    else:
        ctx.ok("drift", f"home and checked tree both at roster rev {repo.get('revision')}")


def run_check(root: Optional[Path] = None, *, home_too: bool = False) -> Tuple[int, str]:
    """`seat_model.py check`: (exit code, report). Never raises for a failed item."""
    root = Path(root).resolve() if root is not None else _TREE_ROOT
    source_home = Path.home()
    scratch = Path(tempfile.mkdtemp(prefix="seat-model-check-"))
    try:
        home, work = scratch / "home", scratch / "work"
        (home / ".claude" / "state").mkdir(parents=True)
        (home / ".codex").mkdir(parents=True)
        work.mkdir()
        if home.resolve() == source_home.resolve():   # cannot happen; refuse rather than write a live home
            raise SeatModelError("check: the temporary HOME resolved to the live home")
        seeded = _seed_check_home(source_home, home)
        ctx = _CheckContext(root=root, source_home=source_home, home=home, work=work,
                            env=_check_env(home), failures=[], passes=[])
        meta = root / "skills" / "_meta"
        roster = _check_roster(ctx, meta, "tree")
        _check_emit(ctx, meta, "tree", roster)
        _check_codex_tiers(ctx, meta, "tree")
        benched = _benched_of(roster)
        _check_avengers(ctx, benched)
        _check_smart_config(ctx, benched)
        _check_lint(ctx, roster)
        if home_too:
            home_meta = source_home / ".claude" / "skills" / "_meta"
            home_roster = _check_roster(ctx, home_meta, "home")
            _check_emit(ctx, home_meta, "home", home_roster, fallback_benched=benched)
            _check_drift(ctx, roster, home_roster)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    lines = [f"seat_model.py check: tree {_ascii(root)}{' + home' if home_too else ''}; temp HOME seeded "
             f"with {', '.join(seeded) if seeded else 'nothing (no home-tier inputs found)'}"]
    lines += [f"PASS {line}" for line in ctx.passes]
    lines += [f"WARN {line}" for line in ctx.warnings]
    lines += [f"FAIL {line}" for line in ctx.failures]
    lines.append(f"seat_model.py check: {len(ctx.failures)} failure(s), {len(ctx.passes)} pass(es)"
                 + (f", {len(ctx.warnings)} warning(s)" if ctx.warnings else ""))
    return (EXIT_OK if not ctx.failures else EXIT_RESOLUTION_FAILED), "\n".join(lines)
