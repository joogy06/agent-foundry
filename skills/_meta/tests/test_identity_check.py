#!/usr/bin/env python3
"""Tests for identity_check.py (Evergreening v1, S041, #119 detection).

§9.1: identity 3-tree fixtures — match, mismatch, missing-tree -> partial.

stdlib unittest. Run:
  python3 -m unittest discover -s ~/.claude/skills/_meta/tests -p 'test_identity_check.py' -v
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("identity_check", _META / "identity_check.py")
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)


def _tree(base: Path, name: str, files: dict) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    for fn, content in files.items():
        (d / fn).write_text(content)
    return d


class TestIdentityCheck(unittest.TestCase):
    def test_all_match(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "t1", {"gates.py": "X", "claims.py": "Y"})
            t2 = _tree(base, "t2", {"gates.py": "X", "claims.py": "Y"})
            t3 = _tree(base, "t3", {"gates.py": "X", "claims.py": "Y"})
            r = ic.run_check([t1, t2, t3], ["gates.py", "claims.py"])
            self.assertEqual(r["status"], "match")
            self.assertEqual(r["mismatch_count"], 0)
            self.assertEqual(r["coverage"], "full")

    def test_mismatch_detected(self):
        # The live #119 shape: prod==shadow != agent-foundry.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "prod", {"gates.py": "SAME"})
            t2 = _tree(base, "shadow", {"gates.py": "SAME"})
            t3 = _tree(base, "agent-foundry", {"gates.py": "DIFFERENT"})
            r = ic.run_check([t1, t2, t3], ["gates.py"])
            self.assertEqual(r["status"], "mismatch")
            self.assertEqual(r["mismatch_count"], 1)
            self.assertEqual(r["per_file"]["gates.py"]["status"], "mismatch")
            self.assertEqual(r["per_file"]["gates.py"]["distinct_count"], 2)

    def test_missing_tree_is_partial_not_error(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "t1", {"gates.py": "X"})
            t2 = _tree(base, "t2", {"gates.py": "X"})
            t3_missing = base / "does-not-exist"
            r = ic.run_check([t1, t2, t3_missing], ["gates.py"])
            # two present copies match -> file status match; overall partial (a tree absent)
            self.assertEqual(r["per_file"]["gates.py"]["status"], "match")
            self.assertEqual(r["status"], "partial")
            self.assertEqual(r["coverage"], "partial")
            self.assertIn(str(t3_missing), r["trees_missing"])

    def test_single_copy_is_partial(self):
        # Only one tree has the file -> cannot compare -> partial (not mismatch).
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "t1", {"gates.py": "X"})
            t2 = _tree(base, "t2", {})  # no gates.py
            t3 = _tree(base, "t3", {})
            r = ic.run_check([t1, t2, t3], ["gates.py"])
            self.assertEqual(r["per_file"]["gates.py"]["status"], "partial")

    def test_self_rot_fields(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "t1", {"gates.py": "X"})
            r = ic.run_check([t1], ["gates.py"])
            for k in ("schema_version", "checker_version", "last_success",
                      "last_error", "runtime_ms"):
                self.assertIn(k, r)
            self.assertEqual(r["schema_version"], "identity-report.v1")

    def test_critical_subset_includes_safety_files(self):
        # The hard-coded critical subset must include the security-relevant engines.
        for f in ("gates.py", "claims.py", "trusted_runner.py", "pause_state.py",
                  "scope_delta.py"):
            self.assertIn(f, ic.CRITICAL_FILES)


# ---------------------------------------------------------------------------
# S043 / #119 (Codex resolutions C1/C5/C6) — strict mode, pair semantics,
# presence-required, full CRITICAL coverage, telemetry byte-invariance.
# ---------------------------------------------------------------------------
class TestStrictModeC1(unittest.TestCase):
    """C1: a MISSING safety file is the most severe drift and must be a
    `mismatch` in strict mode (it was invisible before — reported `match`)."""

    def test_strict_missing_file_is_mismatch(self):
        # The EXACT live agent-foundry shape: a selected file absent from one
        # tree. Lenient -> would have said match/partial; strict -> mismatch.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "prod", {"gates.py": "SAME", "classify.py": "C"})
            t2 = _tree(base, "foundry", {"gates.py": "SAME"})  # classify.py ABSENT
            r = ic.run_check([t1, t2], ["gates.py", "classify.py"], strict=True)
            self.assertEqual(r["status"], "mismatch")
            self.assertEqual(r["per_file"]["classify.py"]["status"], "mismatch")
            self.assertIn(str(t2), r["per_file"]["classify.py"]["absent_in"])
            self.assertEqual(r["per_file"]["gates.py"]["status"], "match")
            self.assertEqual(r["missing_file_count"], 1)

    def test_strict_missing_file_was_match_in_lenient(self):
        # Regression guard for the exact C1 bug: prove lenient (the old default)
        # reports `partial` (single copy) NOT mismatch, while strict catches it.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "prod", {"classify.py": "C"})
            t2 = _tree(base, "foundry", {})  # classify.py absent
            lenient = ic.run_check([t1, t2], ["classify.py"], strict=False)
            self.assertEqual(lenient["per_file"]["classify.py"]["status"], "partial")
            strict = ic.run_check([t1, t2], ["classify.py"], strict=True)
            self.assertEqual(strict["per_file"]["classify.py"]["status"], "mismatch")

    def test_strict_missing_tree_is_mismatch_not_partial(self):
        # A missing TREE in strict mode -> presence cannot be satisfied ->
        # mismatch (lenient would have called it partial).
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "prod", {"gates.py": "X"})
            t2_missing = base / "does-not-exist"
            r = ic.run_check([t1, t2_missing], ["gates.py"], strict=True)
            self.assertEqual(r["status"], "mismatch")
            self.assertEqual(r["per_file"]["gates.py"]["status"], "mismatch")

    def test_strict_all_present_and_identical_is_match(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "prod", {"gates.py": "X", "claims.py": "Y"})
            t2 = _tree(base, "shadow", {"gates.py": "X", "claims.py": "Y"})
            r = ic.run_check([t1, t2], ["gates.py", "claims.py"], strict=True)
            self.assertEqual(r["status"], "match")
            self.assertEqual(r["mismatch_count"], 0)

    def test_strict_content_drift_is_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            t1 = _tree(base, "prod", {"gates.py": "AAA"})
            t2 = _tree(base, "shadow", {"gates.py": "BBB"})
            r = ic.run_check([t1, t2], ["gates.py"], strict=True)
            self.assertEqual(r["status"], "mismatch")
            self.assertEqual(r["per_file"]["gates.py"]["status"], "mismatch")
            self.assertEqual(r["per_file"]["gates.py"]["absent_in"], [])


class TestPairSemanticsC6(unittest.TestCase):
    """resolve_pair + foundry-root override (C6)."""

    def test_resolve_pair_prod_shadow(self):
        trees = ic.resolve_pair("prod-shadow")
        self.assertEqual(trees, [ic.PROD_TREE, ic.SHADOW_TREE])

    def test_resolve_pair_prod_foundry_default(self):
        trees = ic.resolve_pair("prod-foundry")
        self.assertEqual(trees, [ic.PROD_TREE, ic.FOUNDRY_TREE_DEFAULT])

    def test_resolve_pair_foundry_root_override(self):
        custom = Path("/tmp/custom-foundry/skills/_meta")
        trees = ic.resolve_pair("prod-foundry", foundry_root=custom)
        self.assertEqual(trees, [ic.PROD_TREE, custom])

    def test_resolve_pair_all(self):
        trees = ic.resolve_pair("all")
        self.assertEqual(len(trees), 3)
        self.assertIn(ic.PROD_TREE, trees)
        self.assertIn(ic.SHADOW_TREE, trees)

    def test_resolve_pair_unknown_raises(self):
        with self.assertRaises(ValueError):
            ic.resolve_pair("prod-bogus")

    def test_main_prod_foundry_missing_clone_strict_exits_3(self):
        # C6: strict prod-foundry with a nonexistent foundry-root -> env exit 3
        # (NOT a silent 0, NOT a misleading mismatch).
        rc = ic.main(["--pair", "prod-foundry", "--strict",
                      "--foundry-root", "/nonexistent/agent-foundry-xyz"])
        self.assertEqual(rc, 3)

    def test_main_prod_shadow_unaffected_by_missing_foundry(self):
        # prod-shadow must be runnable standalone regardless of foundry presence.
        # (Exit may be 0 or 2 depending on the live tree state; the contract is
        # that it does NOT raise and does NOT return the env code 3.)
        rc = ic.main(["--pair", "prod-shadow", "--strict", "--no-write"])
        self.assertIn(rc, (0, 2))


class TestCriticalFilesFullCoverageC5(unittest.TestCase):
    """C5: CRITICAL_FILES must list ALL safety files (full coverage, not
    spot-check) so the list cannot silently drift behind reality."""

    def test_checker_watches_itself_and_hardrule_machinery(self):
        # The specific C5 additions.
        for f in ("identity_check.py", "hard_rules_common.py",
                  "apply_project_hard_rules.py", "scan_hard_rules.py",
                  "freshness_nudge.py"):
            self.assertIn(f, ic.CRITICAL_FILES, f"{f} missing from CRITICAL_FILES")

    def test_classify_front_door_present(self):
        for f in ("classify.py", "classify_emit.py", "gates.py"):
            self.assertIn(f, ic.CRITICAL_FILES)

    def test_full_coverage_against_prod_tree(self):
        # Full-coverage gate: every *.py in the PROD _meta tree that matches the
        # inclusion policy (gate/enforcement/nudge engine) MUST be in
        # CRITICAL_FILES. We approximate the policy with an explicit allow-set of
        # known safety-file basenames; if a NEW safety file appears in prod and
        # is not listed, this fails -> forces the author to classify it.
        #
        # Policy proxy: any _meta/*.py whose name contains a safety keyword
        # (gate, claim, ledger, audit, arbiter, classify, hard_rule, scope,
        # pause, trusted, identity, freshness, scan_hard) is safety-relevant.
        prod = ic.PROD_TREE
        if not prod.is_dir():
            self.skipTest(f"prod tree absent: {prod}")
        # NOTE (S055): the scope keyword is anchored to `scope_` so it matches the
        # safety files scope_delta.py / scope_reaction.py but NOT the alf helper
        # sweep_scope.py (a pure tier-resolution helper, not a gate/enforcement
        # file). worktree_merge.py and workflow_dispatch.py are likewise pure
        # helpers (their safety comes from bob/main-loop callers, not the file).
        SAFETY_KEYWORDS = (
            "gates", "claims", "trusted_runner", "pause", "scope_",
            "audit_spawn", "arbiter_spawn", "classify", "identity_check",
            "hard_rules", "scan_hard", "freshness_nudge",
        )
        expected = set()
        for py in prod.glob("*.py"):
            name = py.name
            if any(kw in name for kw in SAFETY_KEYWORDS):
                expected.add(name)
        listed = set(ic.CRITICAL_FILES)
        missing = expected - listed
        self.assertEqual(
            missing, set(),
            f"safety files present in prod _meta but NOT in CRITICAL_FILES "
            f"(C5 full-coverage violation): {sorted(missing)}")

    def test_no_phantom_files_in_critical_list(self):
        # Every CRITICAL file should actually exist in prod (else the list cites
        # a file that no longer exists -> stale list). Skip if prod absent.
        prod = ic.PROD_TREE
        if not prod.is_dir():
            self.skipTest(f"prod tree absent: {prod}")
        for f in ic.CRITICAL_FILES:
            self.assertTrue((prod / f).is_file(),
                            f"CRITICAL_FILES lists {f} but it is absent from prod")


class TestStrictNoWriteSideEffect(unittest.TestCase):
    """Strict is a gate: it must not write the freshness report (so it stays
    byte-invariant under a forced telemetry ImportError — §6.4/§9)."""

    def test_strict_does_not_write_report(self):
        before = ic.REPORT_FILE.stat().st_mtime if ic.REPORT_FILE.exists() else None
        ic.main(["--pair", "prod-shadow", "--strict"])
        after = ic.REPORT_FILE.stat().st_mtime if ic.REPORT_FILE.exists() else None
        # Either the file never existed (still doesn't) or its mtime is unchanged.
        self.assertEqual(before, after)


class TestWatchlistS055(unittest.TestCase):
    """S055 §10 — identity_check.py --watchlist (workflows + agents + meta-docs
    prod<->shadow parity + SCHEMA-TWIN hash verification). Extends (not parallels)
    the existing suite per the deploy-order rule."""

    def test_run_watchlist_clean_on_live_tree(self):
        # The live prod/shadow trees were just synced by WP-18; the watchlist
        # advisory run must be clean (no drift, no missing, no twin mismatch).
        report = ic.run_watchlist(strict=False)
        self.assertNotIn("error", report, report.get("error"))
        self.assertEqual(report.get("drift"), [], f"unexpected drift: {report.get('drift')}")
        self.assertEqual(report.get("missing"), [], f"unexpected missing: {report.get('missing')}")
        self.assertEqual(report.get("twin_mismatch"), [],
                         f"unexpected twin mismatch: {report.get('twin_mismatch')}")

    def test_watchlist_covers_workflows_agents_metadocs(self):
        report = ic.run_watchlist(strict=False)
        ids = {e["id"] for e in report["entries"]}
        self.assertEqual(ids, {"workflows", "agents", "meta-docs"})
        # The workflows entry must check all 9 files (README + 8 .js).
        wf = next(e for e in report["entries"] if e["id"] == "workflows")
        self.assertGreaterEqual(wf["files_checked"], 9)

    def test_watchlist_detects_injected_drift(self):
        # Inject a drift into a temp shadow root and confirm it is flagged.
        with tempfile.TemporaryDirectory() as d:
            shadow = Path(d)
            # Mirror the prod workflows/README.md but with a byte changed.
            (shadow / "workflows").mkdir(parents=True)
            prod_readme = ic.PROD_ROOT / "workflows" / "README.md"
            if prod_readme.is_file():
                (shadow / "workflows" / "README.md").write_text(prod_readme.read_text() + "\nDRIFT\n")
                report = ic.run_watchlist(strict=False, shadow_root=shadow)
                # README drift OR missing for the other files — both prove the
                # comparison is live (not a no-op).
                self.assertTrue(report.get("drift") or report.get("missing"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

# ---------------------------------------------------------------------------
# S081 revision 4 / WP-B2 -- the escalation ladder made visible to the machinery.
#
# Three surfaces, each verified DIRECTLY: the canonical execution-report.v1
# schema, the two SCHEMA-TWIN annotations plus bob-serial-exec's hand-maintained
# literal, and the rung re-run behaviour of the workflow body itself.
#
# These deliberately do NOT lean on TestWatchlistS055 above. That class cannot
# fire under the mandated fresh-temp-HOME test recipe -- identity_check binds
# PROD_ROOT and GOVERNANCE_WATCHLIST from Path.home() at import, so it errors on
# a missing watchlist before it checks anything. Its red says nothing about the
# twins, and its green would say nothing either. The assertions below do the work.
# ---------------------------------------------------------------------------

_TREE = _META.parent.parent                      # the tree holding skills/ and workflows/
_SCHEMA_PATH = _META / "schemas" / "execution-report.v1.json"
_WORKFLOWS = _TREE / "workflows"
_BOB_SERIAL_EXEC = _WORKFLOWS / "bob-serial-exec.js"
_EVO_APPLY = _WORKFLOWS / "evo-apply.js"
_TWIN_RE = re.compile(r"//\s*SCHEMA-TWIN:\s*(\S+)\s+sha256:([0-9a-f]{16})")

try:
    import jsonschema as _jsonschema
except ImportError:                              # pragma: no cover - env-dependent
    _jsonschema = None

_NODE = shutil.which("node")

# A report written BEFORE this cycle: no escalation block, an old needs.kind.
# The backward-compatibility control -- it must still validate afterwards.
_OLD_SHAPE_REPORT = {
    "status": "PARTIAL",
    "wp_id": "WP-3",
    "built": ["the demo endpoint", "its unit tests"],
    "files_changed": [{"path": "src/demo/api.py", "change": "added /health route"}],
    "verification": {"tests": "pytest -> 5 passed", "lint": "ruff -> clean"},
    "needs": {"kind": "plan-execution", "payload": {"plan_path": "progress/work-packages.yaml"}},
    "known_issues": ["edge case for empty payload deferred"],
    "how_to_verify": ["curl localhost:8000/health -> 200"],
}


def _schema():
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _report(**over):
    r = {
        "status": "PARTIAL",
        "built": [],
        "files_changed": [],
        "verification": {},
    }
    r.update(over)
    return r


def _twin_hash16():
    """The pin's referent: first 16 hex of the canonical schema file's sha256."""
    return hashlib.sha256(_SCHEMA_PATH.read_bytes()).hexdigest()[:16]


def _twins_in(text):
    return [(m.group(1), m.group(2)) for m in _TWIN_RE.finditer(text)]


def _execution_report_twins(text):
    return [h for (name, h) in _twins_in(text) if name == "execution-report.v1"]


# The workflow body is not importable as-is: it uses top-level `return`, which
# node rejects ("Illegal return statement"), because the Workflow harness wraps
# it. This driver reproduces that wrap -- strip `export ` and wrap the WHOLE file
# in an async function -- so the tests exercise the REAL shipped bytes under a
# stub `agent` rather than grepping them.
_DRIVER_JS = r"""
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const WF = process.argv[2];
const src = readFileSync(WF, "utf8");
const stripped = src.replace(/^export const meta/m, "const meta");
if (stripped === src) { console.log(JSON.stringify({ error: "transform did not apply" })); process.exit(3); }
const dir = mkdtempSync(join(tmpdir(), "wfdrv-"));
const p = join(dir, "wrapped.mjs");
writeFileSync(p, "export async function __run(args, agent) {\n" + stripped + "\n}\n");
const { __run } = await import("file://" + p);

const plan = JSON.parse(process.argv[3]);
const calls = [];
const agent = async (prompt, opts) => {
  calls.push({ prompt: prompt, model: opts && opts.model, agentType: opts && opts.agentType });
  if (plan.script.length) return plan.script.shift();
  return plan.repeat === undefined ? null : plan.repeat;
};
const result = await __run(JSON.parse(process.argv[4]), agent);
console.log(JSON.stringify({ result: result === undefined ? null : result, calls: calls }));
"""


def _run_workflow(script, args, repeat=None, workflow=None):
    """Execute the real workflow body under a stub agent; return {result, calls}."""
    wf = workflow or _BOB_SERIAL_EXEC
    plan = {"script": script}
    if repeat is not None:
        plan["repeat"] = repeat
    with tempfile.TemporaryDirectory() as td:
        drv = Path(td) / "driver.mjs"
        drv.write_text(_DRIVER_JS, encoding="utf-8")
        proc = subprocess.run(
            [_NODE, str(drv), str(wf), json.dumps(plan), json.dumps(args)],
            capture_output=True, text=True, timeout=120,
        )
    if proc.returncode != 0:
        raise AssertionError(
            "workflow driver exit {0}: {1}".format(proc.returncode, proc.stderr[:800]))
    return json.loads(proc.stdout)


# The escalation seat's model in these fixtures: DISTINCT from the executor's
# ("opus") so a test can tell which key served a stage, and NOT benched -- since
# #291 the workflow refuses a benched family (fable) rather than dispatching it,
# which the takeover tests in test_workflow_dispatch.py cover.
_ESC_MODEL = "claude-opus-5-5"

_ARGS = {
    "project_root": "/r", "plan_path": "p.yaml", "plan_hash": "h", "plan_revision": 28,
    "ledger_state_version": "N/A", "map_sig_sha256": "N/A", "run_label": "s081-rev4",
    "run_started_at": "T0", "models": {"bob": "opus", "escalation": _ESC_MODEL},
}


def _load_ok(order):
    return {"schema_version": "plan-load.v1", "plan_id": "P", "plan_hash": "h",
            "hash_ok": True, "wp_order": order}


def _wp_calls(out, wp_id):
    return [c for c in out["calls"] if "wp_id: {0}".format(wp_id) in c["prompt"]]


@unittest.skipIf(_jsonschema is None, "jsonschema not installed")
class TestExecutionReportEscalationBlockS081(unittest.TestCase):
    """WP-B2 criterion [1]: an OPTIONAL top-level `escalation` object and two new
    `needs.kind` values, ADDITIVE ONLY."""

    def _validate(self, instance):
        _jsonschema.validate(instance=instance, schema=_schema())

    def _rejects(self, instance):
        with self.assertRaises(_jsonschema.ValidationError):
            self._validate(instance)

    def test_escalation_block_validates(self):
        self._validate(_report(escalation={
            "next_rung": "opus", "task_key": "S081:WP-B2", "attempt_id": 2}))

    def test_escalation_is_optional(self):
        # Absent is the overwhelmingly common case and must stay legal.
        self._validate(_report())

    def test_every_ladder_rung_validates(self):
        # The rungs escalation.py can emit (LADDER + the terminal rungs).
        # `fable` is the legacy spelling of `takeover` (#291), still valid on read.
        for rung in ("opus", "takeover", "fable", "diagnosis", "user", "none"):
            self._validate(_report(escalation={
                "next_rung": rung, "task_key": "S081:WP-B2", "attempt_id": 1}))

    def test_invented_rung_rejected(self):
        # CONTROL: the rung vocabulary is closed (escalation.RUNGS).
        self._rejects(_report(escalation={
            "next_rung": "gpt-9-omega", "task_key": "S081:WP-B2", "attempt_id": 1}))

    def test_escalation_requires_all_three_members(self):
        for partial in ({"next_rung": "opus"},
                        {"next_rung": "opus", "task_key": "S081:WP-B2"},
                        {"task_key": "S081:WP-B2", "attempt_id": 1}):
            self._rejects(_report(escalation=partial))

    def test_escalation_rejects_the_to_dict_spelling(self):
        # THE DRIFT GUARD. escalation.NextRung.to_dict() spells the key `rung`;
        # the schema (and bob-serial-exec) read `next_rung`. A producer that
        # dumps to_dict() wholesale must FAIL LOUDLY here rather than hand the
        # workflow an escalation block whose rung it can never see.
        self._rejects(_report(escalation={
            "rung": "opus", "task_key": "S081:WP-B2", "attempt_id": 1}))

    def test_undeclared_top_level_key_still_rejected(self):
        # CONTROL for `additionalProperties: false` at the top level -- the whole
        # reason the new field had to be DECLARED rather than merely conventional.
        self._rejects(_report(invented_key="anything"))

    def test_both_new_needs_kinds_validate(self):
        for kind in ("capability-failure", "escalation-diagnosis"):
            self._validate(_report(needs={"kind": kind}))

    def test_preexisting_needs_kinds_still_validate(self):
        for kind in ("plan-execution", "forge-amendment-mode", "plan-recompile",
                     "budget-floor", "user-decision", "needs_inline_verification"):
            self._validate(_report(needs={"kind": kind}))

    def test_invented_needs_kind_rejected(self):
        # CONTROL: the enum is still closed after being extended.
        self._rejects(_report(needs={"kind": "make-me-a-sandwich"}))

    def test_old_shape_report_still_validates(self):
        # Backward-compatibility control, inline (runs in BOTH trees).
        self._validate(_OLD_SHAPE_REPORT)

    def test_stored_old_shape_fixture_still_validates(self):
        # The STORED control: a fixture committed long before this cycle.
        fixture = _TREE / "tests" / "schemas" / "fixtures" / "execution-report.v1.json"
        if not fixture.is_file():
            self.skipTest("stored fixture not present in this tree")
        self._validate(json.loads(fixture.read_text(encoding="utf-8")))

    def test_change_is_additive_only(self):
        s = _schema()
        # The required list must NOT have grown.
        self.assertEqual(s["required"], ["status", "built", "files_changed", "verification"])
        # No pre-existing property changed type.
        self.assertEqual(s["properties"]["status"]["enum"], ["COMPLETE", "PARTIAL", "FAILED"])
        self.assertEqual(s["properties"]["wp_id"]["type"], ["string", "null"])
        self.assertEqual(s["properties"]["needs"]["type"], ["object", "null"])
        self.assertIs(s["additionalProperties"], False)

    def test_escalation_additionalproperties_posture_is_explicit(self):
        # The criterion requires the posture be STATED, not left to chance.
        esc = _schema()["properties"]["escalation"]
        self.assertIn("additionalProperties", esc)
        self.assertIs(esc["additionalProperties"], False)


class TestSchemaTwinPinsS081(unittest.TestCase):
    """WP-B2 criterion [2]: the SCHEMA-TWIN pins, verified by RECOMPUTATION."""

    def test_both_workflow_annotations_match_the_recomputed_hash(self):
        want = _twin_hash16()
        for wf in (_BOB_SERIAL_EXEC, _EVO_APPLY):
            found = _execution_report_twins(wf.read_text(encoding="utf-8"))
            self.assertEqual(len(found), 1, "{0}: expected exactly one execution-report.v1 twin".format(wf.name))
            self.assertEqual(found[0], want, "{0}: stale SCHEMA-TWIN pin".format(wf.name))

    def test_the_two_annotations_agree_with_each_other(self):
        a = _execution_report_twins(_BOB_SERIAL_EXEC.read_text(encoding="utf-8"))
        b = _execution_report_twins(_EVO_APPLY.read_text(encoding="utf-8"))
        self.assertEqual(a, b)

    def test_a_stale_annotation_is_detected(self):
        # CONTROL: corrupt the annotation in a COPY and confirm the same
        # comparison fails. Without this the check could be vacuous.
        text = _BOB_SERIAL_EXEC.read_text(encoding="utf-8")
        stale = text.replace("sha256:" + _twin_hash16(), "sha256:" + "0" * 16)
        self.assertNotEqual(stale, text, "the replacement did not apply -- test is vacuous")
        self.assertNotEqual(_execution_report_twins(stale), [_twin_hash16()])

    def test_bob_serial_exec_literal_twin_declares_escalation(self):
        # The THIRD twin: the hand-maintained EXECUTION_REPORT_SCHEMA object.
        text = _BOB_SERIAL_EXEC.read_text(encoding="utf-8")
        start = text.index("const EXECUTION_REPORT_SCHEMA")
        block = text[start:text.index("\n};", start)]
        self.assertIn("escalation:", block,
                      "the literal twin must declare `escalation` or the loop can never read a rung")
        for key in ("status:", "wp_id:", "built:", "files_changed:", "verification:", "needs:"):
            self.assertIn(key, block)


@unittest.skipIf(_NODE is None, "node not installed")
class TestBobSerialExecRungRerunS081(unittest.TestCase):
    """WP-B2 criterion [4]: rung re-runs, executed against the REAL script body."""

    def test_opus_rung_reruns_the_same_wp(self):
        out = _run_workflow([
            _load_ok(["WP-1"]),
            _report(escalation={"next_rung": "opus", "task_key": "P:WP-1", "attempt_id": 1}),
            _report(status="COMPLETE"),
            _report(status="COMPLETE"),          # finalize
        ], _ARGS)
        self.assertEqual(len(_wp_calls(out, "WP-1")), 2, "the opus rung must RE-RUN the WP")
        self.assertEqual(out["result"]["status"], "COMPLETE")

    def test_takeover_rung_reruns_with_the_escalation_model(self):
        # #291: the rung is `takeover`; its legacy spelling `fable` routes the same.
        for rung in ("takeover", "fable"):
            with self.subTest(rung=rung):
                out = _run_workflow([
                    _load_ok(["WP-1"]),
                    _report(escalation={"next_rung": rung, "task_key": "P:WP-1", "attempt_id": 1}),
                    _report(status="COMPLETE"),
                    _report(status="COMPLETE"),
                ], _ARGS)
                calls = _wp_calls(out, "WP-1")
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0]["model"], "opus", "first attempt uses args.models.bob")
                self.assertEqual(calls[1]["model"], _ESC_MODEL,
                                 "the takeover rung uses args.models.escalation")

    def test_diagnosis_rung_surfaces_escalation_diagnosis(self):
        out = _run_workflow([
            _load_ok(["WP-1", "WP-2"]),
            _report(escalation={"next_rung": "diagnosis", "task_key": "P:WP-1", "attempt_id": 3}),
        ], _ARGS)
        self.assertEqual(out["result"]["needs"]["kind"], "escalation-diagnosis")
        self.assertEqual(len(_wp_calls(out, "WP-1")), 1, "diagnosis does not re-run")
        self.assertEqual(_wp_calls(out, "WP-2"), [], "the loop must stop at the failed WP")

    def test_unrelated_non_complete_still_breaks_the_loop(self):
        # CONTROL: today's behaviour is UNCHANGED when no rung is present.
        out = _run_workflow([
            _load_ok(["WP-1", "WP-2"]),
            _report(needs={"kind": "user-decision", "payload": {"why": "unrelated"}}),
        ], _ARGS)
        self.assertEqual(out["result"]["needs"]["kind"], "user-decision")
        self.assertEqual(len(_wp_calls(out, "WP-1")), 1, "no rung means no re-run")
        self.assertEqual(_wp_calls(out, "WP-2"), [])

    def test_user_rung_does_not_rerun(self):
        out = _run_workflow([
            _load_ok(["WP-1"]),
            _report(needs={"kind": "user-decision"},
                    escalation={"next_rung": "user", "task_key": "P:WP-1", "attempt_id": 4}),
        ], _ARGS)
        self.assertEqual(len(_wp_calls(out, "WP-1")), 1)
        self.assertEqual(out["result"]["needs"]["kind"], "user-decision")

    def test_prior_attempts_accumulates_and_never_drops_an_entry(self):
        out = _run_workflow([
            _load_ok(["WP-1"]),
            _report(escalation={"next_rung": "opus", "task_key": "P:WP-1", "attempt_id": 1}),
            _report(escalation={"next_rung": "takeover", "task_key": "P:WP-1", "attempt_id": 2}),
            _report(status="COMPLETE"),
            _report(status="COMPLETE"),
        ], _ARGS)
        calls = _wp_calls(out, "WP-1")
        self.assertEqual(len(calls), 3)
        self.assertNotIn("prior_attempts:", calls[0]["prompt"], "the first attempt has no history")
        first = json.loads(calls[1]["prompt"].split("prior_attempts: ")[1].split("\n")[0])
        second = json.loads(calls[2]["prompt"].split("prior_attempts: ")[1].split("\n")[0])
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 2, "append-only: the second attempt keeps the first")
        self.assertEqual(second[0], first[0], "an earlier failure is NEVER erased or rewritten")
        for entry in second:
            self.assertEqual(entry["source"], "workflow")

    def test_rerun_loop_is_bounded(self):
        # A report that forever asks for `opus` must not spin. The LOOP bound is
        # bob-serial-exec's own MAX_ATTEMPTS_PER_WP; escalation.py's 6-per-plan
        # cap bounds the LADDER, not this loop, and the workflow must not depend
        # on the producer being well-behaved.
        forever = _report(escalation={"next_rung": "opus", "task_key": "P:WP-1", "attempt_id": 1})
        out = _run_workflow([_load_ok(["WP-1"])], _ARGS, repeat=forever)
        n = len(_wp_calls(out, "WP-1"))
        self.assertGreaterEqual(n, 2, "it must re-run at least once")
        self.assertLessEqual(n, 4, "it must not spin: the loop is capped per WP")

    def test_serial_and_never_parallel_or_worktree(self):
        # CB4 single-writer: the re-run must not have introduced concurrency.
        # Strip `//` comments AND the meta block -- meta.description legitimately
        # contains the prose "parallel()/worktree PROHIBITED", and matching that
        # would be a decidable check firing on correct text.
        text = _BOB_SERIAL_EXEC.read_text(encoding="utf-8")
        code = "\n".join(l for l in text.split("\n") if not l.strip().startswith("//"))
        start = code.index("const meta =")
        code = code[:start] + code[code.index("\n};", start):]
        self.assertNotIn("parallel(", code, "parallel() over bob stages is PROHIBITED (CB4)")
        for form in ('isolation: "worktree"', "isolation:'worktree'", 'isolation: \'worktree\''):
            self.assertNotIn(form, code, "bob stages are NEVER worktree-isolated")
        # And the retry must be awaited one-at-a-time inside the serial loop.
        self.assertIn("await agent(", code)


# ---------------------------------------------------------------------------
# S081 revision 4 fix round 1 / WP-X2 -- F3 and f13 of the revision-4 review
# (docs/reviews/2026-09-22-S081-rev4-review.md).
#
# F3: the workflow bought the next rung from escalation.next_rung ALONE, so a
# report saying needs.kind user-decision with next_rung fable dispatched Fable.
# The rung and the kind are two fields one producer writes, and nothing made
# them agree. The workflow now consults NEVER_ESCALATES -- a module-level mirror
# of escalation.NEVER_ESCALATES -- BEFORE any rung: such a report is never re-run
# and never sent to diagnosis; it surfaces with its own needs block.
# f13: verification.attempts was priorAttempts.length + 1, one more than the
# number of executions.
#
# Every behaviour assertion below runs the REAL shipped bytes under node.
# ---------------------------------------------------------------------------

if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))
import escalation as _esc  # noqa: E402  (the Python half of the NEVER_ESCALATES twin)

# Anchored on the const name, at the start of a line (so a comment that merely
# names it cannot match), up to the array's closing bracket.
_NEVER_ESC_JS_RE = re.compile(r"^const\s+NEVER_ESCALATES\s*=\s*\[([^\]]*)\]", re.MULTILINE)
_JS_STRING_RE = re.compile(r'"([^"\\]*)"')

# needs kinds in BOTH escalation.NEVER_ESCALATES and the execution-report.v1
# needs.kind enum -- the four the plan's RED criterion names.
# #313 added `clarification` to both the schema enum and NEVER_ESCALATES: five now.
_SCHEMA_FOUR = ("budget-floor", "clarification", "forge-amendment-mode", "plan-recompile", "user-decision")


def _js_never_escalates(text):
    """bob-serial-exec.js's NEVER_ESCALATES array, as a list in source order.

    EXACTLY ONE declaration or this fails loudly, and an empty array fails loudly
    too: an extraction that finds nothing must never compare equal to anything.
    """
    found = _NEVER_ESC_JS_RE.findall(text)
    if len(found) != 1:
        raise AssertionError(
            "expected exactly one `const NEVER_ESCALATES = [...]`, found {0}".format(len(found)))
    members = _JS_STRING_RE.findall(re.sub(r"//[^\n]*", "", found[0]))
    if not members:
        raise AssertionError("NEVER_ESCALATES extracted EMPTY -- an empty extraction never passes")
    return members


def _never_escalates_parity_problems(members):
    """[] when `members` equals escalation.NEVER_ESCALATES by set AND by length."""
    want = _esc.NEVER_ESCALATES
    problems = []
    if set(members) != set(want):
        problems.append("set differs: missing {0}, extra {1}".format(
            sorted(set(want) - set(members)), sorted(set(members) - set(want))))
    if len(members) != len(want):
        problems.append("length {0} != {1}".format(len(members), len(want)))
    return problems


def _schema_never_escalating_kinds():
    enum = _schema()["properties"]["needs"]["properties"]["kind"]["enum"]
    return tuple(sorted(k for k in enum if k in _esc.NEVER_ESCALATES))


class TestNeverEscalatesTwinFR1(unittest.TestCase):
    """WP-X2 PARITY: the workflow's array IS escalation.NEVER_ESCALATES, member
    for member, extracted from the REAL shipped bytes."""

    _ANCHOR = "const NEVER_ESCALATES = [\n"

    def setUp(self):
        self.text = _BOB_SERIAL_EXEC.read_text(encoding="utf-8")

    def test_the_array_equals_escalation_never_escalates(self):
        members = _js_never_escalates(self.text)
        self.assertEqual(_never_escalates_parity_problems(members), [])

    def test_control_a_copy_missing_one_member_fails(self):
        mutated = self.text.replace('  "budget-floor",\n', "", 1)
        self.assertNotEqual(mutated, self.text, "the removal did not apply -- the control is vacuous")
        self.assertNotEqual(_never_escalates_parity_problems(_js_never_escalates(mutated)), [])

    def test_control_a_copy_with_an_extra_member_fails(self):
        mutated = self.text.replace(self._ANCHOR, self._ANCHOR + '  "capability-failure",\n', 1)
        self.assertNotEqual(mutated, self.text, "the insertion did not apply -- the control is vacuous")
        self.assertNotEqual(_never_escalates_parity_problems(_js_never_escalates(mutated)), [])

    def test_control_a_duplicated_member_fails_on_length(self):
        # Set equality alone is blind to a duplicate; the LENGTH arm catches it.
        mutated = self.text.replace(self._ANCHOR, self._ANCHOR + '  "user-decision",\n', 1)
        self.assertNotEqual(mutated, self.text, "the insertion did not apply -- the control is vacuous")
        members = _js_never_escalates(mutated)
        self.assertEqual(set(members), set(_esc.NEVER_ESCALATES), "the set arm alone would pass it")
        self.assertNotEqual(_never_escalates_parity_problems(members), [])

    def test_control_the_extraction_fails_loudly(self):
        cases = (
            ("renamed", self.text.replace("const NEVER_ESCALATES =", "const NEVER_ESCALATE =", 1)),
            ("declared twice", self.text + '\nconst NEVER_ESCALATES = ["user-decision"];\n'),
            ("emptied", _NEVER_ESC_JS_RE.sub("const NEVER_ESCALATES = []", self.text, count=1)),
        )
        for label, mutated in cases:
            with self.subTest(label=label):
                self.assertNotEqual(mutated, self.text, "the mutation did not apply -- the control is vacuous")
                with self.assertRaises(AssertionError):
                    _js_never_escalates(mutated)


@unittest.skipIf(_NODE is None, "node not installed")
class TestBobSerialExecNeverEscalatesFR1(unittest.TestCase):
    """WP-X2 behaviour: F3 (a never-escalating needs kind never buys a rung) and
    f13 (attempts counts executions), executed against the REAL script body."""

    def _assert_never_rerun(self, kind, rung):
        needs = {"kind": kind, "payload": {"why": "a question only the user can answer"}}
        out = _run_workflow([
            _load_ok(["WP-1", "WP-2"]),
            _report(needs=needs,
                    escalation={"next_rung": rung, "task_key": "P:WP-1", "attempt_id": 1}),
            # What a bought rung would get: a laundered COMPLETE, then the next WP.
            _report(status="COMPLETE"),
            _report(status="COMPLETE"),
            _report(status="COMPLETE"),          # finalize
        ], _ARGS)
        self.assertEqual(len(_wp_calls(out, "WP-1")), 1, "a never-escalating needs kind is NEVER re-run")
        self.assertEqual(
            [c for c in out["calls"] if c["model"] == _ARGS["models"]["escalation"]], [],
            "no stage may run on args.models.escalation")
        self.assertEqual(out["result"]["status"], "PARTIAL")
        self.assertEqual(out["result"]["needs"], needs, "it surfaces with its OWN needs block")
        self.assertEqual(_wp_calls(out, "WP-2"), [], "the loop stops at the failed WP")
        self.assertEqual(out["result"]["verification"]["executed_wps"], ["WP-1"])
        self.assertEqual(out["result"]["verification"]["attempts"], 1,
                         "the failure is recorded before the needs check: one execution")

    def test_f3_the_schema_never_escalating_kinds_never_buy_takeover(self):
        kinds = _schema_never_escalating_kinds()
        self.assertEqual(kinds, _SCHEMA_FOUR, "the red set must be the five, never vacuous")
        for kind in kinds:
            for rung in ("takeover", "fable"):   # fable: the legacy spelling (#291)
                with self.subTest(kind=kind, rung=rung):
                    self._assert_never_rerun(kind, rung)

    def test_f3_the_schema_never_escalating_kinds_never_buy_opus(self):
        for kind in _SCHEMA_FOUR:
            with self.subTest(kind=kind):
                self._assert_never_rerun(kind, "opus")

    def test_f3_the_other_seven_members_are_honoured_too(self):
        # The workflow's literal schema twin does not close needs.kind, so a gate
        # verdict spelled as escalation.py spells it can arrive here as well. The
        # check is the whole set, not the schema's four.
        others = sorted(_esc.NEVER_ESCALATES - set(_SCHEMA_FOUR))
        self.assertEqual(len(others), 7)
        for kind in others:
            for rung in ("takeover", "fable", "opus"):
                with self.subTest(kind=kind, rung=rung):
                    self._assert_never_rerun(kind, rung)

    def test_f3_a_never_escalating_kind_is_never_sent_to_diagnosis(self):
        # The diagnosis rung buys the escalation seat -- a stronger model as well.
        for kind in _SCHEMA_FOUR:
            with self.subTest(kind=kind):
                needs = {"kind": kind, "payload": {"why": "x"}}
                out = _run_workflow([
                    _load_ok(["WP-1", "WP-2"]),
                    _report(needs=needs,
                            escalation={"next_rung": "diagnosis", "task_key": "P:WP-1", "attempt_id": 3}),
                ], _ARGS)
                self.assertEqual(out["result"]["needs"], needs, "its own needs block, not escalation-diagnosis")
                self.assertEqual(len(_wp_calls(out, "WP-1")), 1)
                self.assertEqual(_wp_calls(out, "WP-2"), [])

    def test_f13_one_failed_execution_counts_one_attempt(self):
        out = _run_workflow([
            _load_ok(["WP-1"]),
            _report(escalation={"next_rung": "user", "task_key": "P:WP-1", "attempt_id": 1}),
        ], _ARGS)
        self.assertEqual(len(_wp_calls(out, "WP-1")), 1)
        self.assertEqual(out["result"]["verification"]["attempts"], 1)

    def test_f13_three_executions_count_three_attempts(self):
        out = _run_workflow([
            _load_ok(["WP-1"]),
            _report(escalation={"next_rung": "opus", "task_key": "P:WP-1", "attempt_id": 1}),
            _report(escalation={"next_rung": "takeover", "task_key": "P:WP-1", "attempt_id": 2}),
            _report(escalation={"next_rung": "diagnosis", "task_key": "P:WP-1", "attempt_id": 3}),
        ], _ARGS)
        self.assertEqual([c["model"] for c in _wp_calls(out, "WP-1")], ["opus", "opus", _ESC_MODEL])
        self.assertEqual(out["result"]["needs"]["kind"], "escalation-diagnosis")
        self.assertEqual(out["result"]["verification"]["attempts"], 3)
        self.assertEqual(len(out["result"]["needs"]["payload"]["prior_attempts"]), 3,
                         "attempts equals the length of the history it summarises")

    def test_control_capability_failure_with_takeover_reruns_on_the_escalation_model(self):
        out = _run_workflow([
            _load_ok(["WP-1"]),
            _report(needs={"kind": "capability-failure"},
                    escalation={"next_rung": "takeover", "task_key": "P:WP-1", "attempt_id": 1}),
            _report(status="COMPLETE"),
            _report(status="COMPLETE"),          # finalize
        ], _ARGS)
        self.assertEqual([c["model"] for c in _wp_calls(out, "WP-1")], ["opus", _ESC_MODEL])
        self.assertEqual(out["result"]["status"], "COMPLETE")

    def test_control_a_null_needs_with_opus_reruns(self):
        out = _run_workflow([
            _load_ok(["WP-1"]),
            _report(needs=None, escalation={"next_rung": "opus", "task_key": "P:WP-1", "attempt_id": 1}),
            _report(status="COMPLETE"),
            _report(status="COMPLETE"),          # finalize
        ], _ARGS)
        self.assertEqual(len(_wp_calls(out, "WP-1")), 2)
        self.assertEqual(out["result"]["status"], "COMPLETE")

    def test_control_capability_failure_still_reaches_diagnosis(self):
        out = _run_workflow([
            _load_ok(["WP-1", "WP-2"]),
            _report(needs={"kind": "capability-failure"},
                    escalation={"next_rung": "diagnosis", "task_key": "P:WP-1", "attempt_id": 3}),
        ], _ARGS)
        self.assertEqual(out["result"]["needs"]["kind"], "escalation-diagnosis")
        self.assertEqual(len(_wp_calls(out, "WP-1")), 1)
        self.assertEqual(_wp_calls(out, "WP-2"), [])
