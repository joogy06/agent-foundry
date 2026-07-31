#!/usr/bin/env python3
"""drift_runner.py — event-gated normalized-command drift probe (Evergreening v1, S041).

The library version of the manual `test_drift_probe.py` logic. Sweeps call this ONLY
for CLIs whose version just changed (`drift_probe_recommended`), to detect when a CLI's
command set has drifted from what its affordance registry claims. Closes #105.

The test (tests/test_drift_probe.py) stays `@pytest.mark.manual` and print-only; this
runner imports the SAME extraction helpers from drift_extract.py (never the test's
private symbols — spec-review Issue 2) and applies the BINDING flap rules:

  - compare NORMALIZED command tokens only (sorted set; no descriptions/order/prose)
  - REMOVALS require 2 CONSECUTIVE observations (state in drift-state.json) OR
    executable-failure evidence before being reported as real drift
  - ADDITIONS are reported immediately (a new command is low-risk to surface)
  - extractor failure (the regex got nothing from --help) is reported as
    `extractor_error`, NEVER as product drift (the original manual-probe rationale)

Output is written into the freshness feed as `latest.json.drift` (merged by the caller)
and a standalone drift-report; the 2-consecutive state lives in
~/.claude/state/freshness/drift-state.json.

CLI:
  drift_runner.py [--targets claude-code.yaml,codex.yaml] [--json] [--no-state]

stdlib + drift_extract only. Deterministic given the same --help output + prior state.
Writes ONLY under ~/.claude/state/freshness/. (D1: no skill-write path.)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import drift_extract  # noqa: E402

REPORT_SCHEMA = "drift-report.v1"
RUNNER_VERSION = "1.0.0"

HOME = Path(os.environ.get("HOME", str(Path.home())))
STATE_FRESH = HOME / ".claude" / "state" / "freshness"
STATE_FILE = STATE_FRESH / "drift-state.json"
REPORT_FILE = STATE_FRESH / "drift-report.json"

HELP_TIMEOUT_S = 10


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FRESH.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(STATE_FILE))
    except OSError:
        pass


def probe_one(registry_name: str) -> dict:
    """Probe one CLI-backed registry. Returns a per-target result dict (no flap logic
    yet — that needs the prior state, applied in run_drift)."""
    binary, args, pattern = drift_extract.DRIFT_TARGETS[registry_name]
    reg_path = drift_extract.registry_dir() / registry_name
    try:
        reg_cmds = drift_extract.registry_commands(reg_path)
    except Exception as e:  # noqa: BLE001
        return {"registry": registry_name, "binary": binary,
                "status": "registry_error", "detail": str(e)}

    if not shutil.which(binary):
        return {"registry": registry_name, "binary": binary,
                "status": "binary_absent",
                "registry_commands": sorted(reg_cmds)}

    try:
        proc = subprocess.run([binary, *args], capture_output=True, text=True,
                              timeout=HELP_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"registry": registry_name, "binary": binary,
                "status": "help_failed", "detail": str(e),
                "registry_commands": sorted(reg_cmds)}

    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    help_cmds = drift_extract.extract_commands(text, pattern)

    # extractor failure (#139): empty extraction OR a missing known-floor token means
    # the --help parse broke -> NOT product drift. This prevents a consistently-failing
    # extractor from satisfying the 2-consecutive-removal rule and "confirming" a
    # non-removal (the live #139 symptom: agy's real -p/--add-dir flagged as removed).
    floor = drift_extract.KNOWN_FLOORS.get(registry_name, frozenset())
    if _extraction_status(help_cmds, floor) == "extractor_error":
        missing = sorted(set(floor) - help_cmds) if floor else []
        detail = ("no commands extracted from --help (probe/regex issue, not drift)"
                  if not help_cmds else
                  f"known-floor tokens missing {missing} — --help parse broke, not drift")
        return {"registry": registry_name, "binary": binary,
                "status": "extractor_error", "detail": detail,
                "registry_commands": sorted(reg_cmds)}

    added = sorted(help_cmds - reg_cmds)
    removed = sorted(reg_cmds - help_cmds)
    return {"registry": registry_name, "binary": binary, "status": "probed",
            "registry_commands": sorted(reg_cmds),
            "help_commands": sorted(help_cmds),
            "added_in_help": added,
            "removed_from_help": removed}


def _extraction_status(help_cmds: set, floor) -> str:
    """Pure classifier (#139): 'ok' or 'extractor_error'.

    Empty extraction OR a known-floor token missing => the --help parse broke, which
    is NOT product drift. Floored CLIs (agy, codex) carry bedrock tokens that a healthy
    parse always yields; their absence is the signature of a broken extractor."""
    if not help_cmds:
        return "extractor_error"
    if floor and not set(floor) <= set(help_cmds):
        return "extractor_error"
    return "ok"


def apply_flap_rules(result: dict, state: dict) -> dict:
    """Apply the binding flap rules using the prior 2-consecutive state.

    Mutates `state` for the registry; returns the result enriched with a
    `reportable` block describing what (if anything) is real drift."""
    reg = result["registry"]
    reportable = {"additions": [], "removals_confirmed": [], "removals_pending": []}

    if result.get("status") != "probed":
        # extractor_error / help_failed / binary_absent / registry_error: clear any
        # pending-removal state (we cannot confirm), report nothing as drift.
        state.pop(reg, None)
        result["reportable"] = reportable
        return result

    added = result.get("added_in_help", [])
    removed = result.get("removed_from_help", [])

    # additions reported immediately
    reportable["additions"] = list(added)

    # removals: require 2 consecutive observations of the SAME removed-set.
    prev = state.get(reg, {})
    prev_removed = set(prev.get("removed_from_help", []))
    cur_removed = set(removed)
    confirmed = sorted(cur_removed & prev_removed)  # seen this run AND last run
    pending = sorted(cur_removed - prev_removed)    # newly observed this run
    reportable["removals_confirmed"] = confirmed
    reportable["removals_pending"] = pending

    # persist this run's observation for the next comparison
    state[reg] = {
        "removed_from_help": removed,
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    result["reportable"] = reportable
    return result


def run_drift(targets: list[str], use_state: bool = True) -> dict:
    t0 = time.time()
    state = _load_state() if use_state else {}
    results = []
    any_drift = False
    for reg in targets:
        if reg not in drift_extract.DRIFT_TARGETS:
            results.append({"registry": reg, "status": "not_a_drift_target"})
            continue
        res = probe_one(reg)
        res = apply_flap_rules(res, state)
        rp = res.get("reportable", {})
        if rp.get("additions") or rp.get("removals_confirmed"):
            any_drift = True
        results.append(res)
    if use_state:
        _save_state(state)
    runtime_ms = int((time.time() - t0) * 1000)
    return {
        "schema_version": REPORT_SCHEMA,
        "runner_version": RUNNER_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "any_drift": any_drift,
        "last_success": True,
        "last_error": None,
        "runtime_ms": runtime_ms,
        "results": results,
    }


def write_report(report: dict) -> None:
    try:
        STATE_FRESH.mkdir(parents=True, exist_ok=True)
        tmp = REPORT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(REPORT_FILE))
    except OSError:
        pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="drift_runner.py",
                                description="event-gated normalized-command drift probe")
    p.add_argument("--targets", default=None,
                   help="comma-separated registry filenames (default: all 5 CLI targets)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-state", action="store_true",
                   help="do not read/write the 2-consecutive state file (one-shot)")
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args(argv)

    targets = args.targets.split(",") if args.targets else list(drift_extract.DRIFT_TARGETS)
    report = run_drift(targets, use_state=not args.no_state)
    if not args.no_write:
        write_report(report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"drift_runner v{RUNNER_VERSION}: any_drift={report['any_drift']} "
              f"in {report['runtime_ms']}ms")
        for r in report["results"]:
            rp = r.get("reportable", {})
            line = f"  {r['registry']}: {r['status']}"
            if rp.get("additions"):
                line += f" +{rp['additions']}"
            if rp.get("removals_confirmed"):
                line += f" -CONFIRMED{rp['removals_confirmed']}"
            if rp.get("removals_pending"):
                line += f" -pending{rp['removals_pending']}"
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
