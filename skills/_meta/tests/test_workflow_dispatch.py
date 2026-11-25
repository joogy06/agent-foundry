#!/usr/bin/env python3
"""test_workflow_dispatch.py — WP-7 (S055 §4.3 / R11).

Covers: atomic claim exactly-once under concurrent callers; double-claim of
(plan_hash, revision) refused; resume-after-revision mechanically detected;
main-loop sole-writer record shape conforms to workflow-run-record.v1.

#291 WP-4 adds the DISPATCH side of bob-serial-exec.js's escalation ladder,
executed against the REAL shipped bytes under node: the `takeover` rung (its
legacy spelling `fable` still routed), refusal of a benched model rather than
dispatching it (args.benched; absent -> any fable token refused), refusal of a
takeover with no escalation model (surfaces escalation-diagnosis, never an
inherit), the same_model_as_executor record, and the takeover report validating
against BOTH the canonical schema and the workflow's own literal schema twin.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import workflow_dispatch as wd  # noqa: E402

# Schema for record-shape validation (best-effort — skip if jsonschema absent).
try:
    import jsonschema  # noqa: E402
    _SCHEMA = json.loads((_META_DIR / "schemas" / "workflow-run-record.v1.json").read_text())
except Exception:  # pragma: no cover
    jsonschema = None
    _SCHEMA = None


PH = "sha256:" + "a" * 64


def _claim_worker(project_root_str, idx, q):
    pr = Path(project_root_str)
    res = wd.claim(pr, "bob-serial-exec", PH, 1, f"run-{idx}")
    q.put(res["status"])


class WorkflowDispatch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_emit_then_claim(self):
        wd.emit(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:00Z")
        res = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:01Z")
        self.assertEqual(res["status"], "claimed")
        self.assertTrue(res["claim_token"])

    def test_double_claim_refused(self):
        r1 = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        self.assertEqual(r1["status"], "claimed")
        r2 = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-B")
        self.assertEqual(r2["status"], "refused")
        self.assertIn("holder", r2)

    def test_claim_after_finish_allowed(self):
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        wd.finish(self.tmp, "bob-serial-exec", PH, 1, "run-A", "complete")
        # After terminal, the same (plan_hash, revision) is no longer "live" —
        # a re-claim is allowed (e.g. a fresh attempt).
        r2 = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-C")
        self.assertEqual(r2["status"], "claimed")

    def test_different_revision_not_blocked(self):
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        # A higher revision (the post-amendment plan) is a different key.
        r2 = wd.claim(self.tmp, "bob-serial-exec", PH, 2, "run-A")
        self.assertEqual(r2["status"], "claimed")

    def test_concurrent_claimers_exactly_one_wins(self):
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        procs = [ctx.Process(target=_claim_worker, args=(str(self.tmp), i, q)) for i in range(8)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        results = [q.get() for _ in range(8)]
        self.assertEqual(results.count("claimed"), 1, f"expected exactly one winner, got {results}")
        self.assertEqual(results.count("refused"), 7)

    def test_resume_after_revision_detected(self):
        # Simulate: claim+execute at rev1, then a higher rev2 appears (amendment),
        # then a STALE resume fires at rev1 again -> mechanically detectable.
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1")
        wd.emit(self.tmp, "bob-serial-exec", PH, 2, "run-A")  # amendment -> rev 2
        # stale resume back at rev 1
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1b", resumed_from="tok")
        offenders = wd.audit_resume_across_revision(self.tmp)
        self.assertEqual(len(offenders), 1)
        self.assertEqual(offenders[0]["plan_revision"], 1)
        self.assertEqual(offenders[0]["resumed_from"], "tok")

    def test_clean_resume_not_flagged(self):
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1")
        # a legit resume at the SAME revision is fine
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1", resumed_from="tok")
        self.assertEqual(wd.audit_resume_across_revision(self.tmp), [])

    @unittest.skipIf(jsonschema is None, "jsonschema not available")
    def test_records_conform_to_schema(self):
        wd.emit(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:00Z")
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:01Z")
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid", at="2026-06-11T00:00:02Z")
        wd.finish(self.tmp, "bob-serial-exec", PH, 1, "run-A", "complete", at="2026-06-11T00:00:03Z")
        for rec in wd._read_records(self.tmp):
            jsonschema.validate(instance=rec, schema=_SCHEMA)



# ---------------------------------------------------------------------------
# #291 WP-4 -- bob-serial-exec.js escalation dispatch (takeover / benched refusal).
# ---------------------------------------------------------------------------
import escalation as _esc  # noqa: E402
import seat_model as _seat_model  # noqa: E402  (THE normaliser the JS mirror copies)

_TREE = _META_DIR.parent.parent
_WF = _TREE / "workflows" / "bob-serial-exec.js"
_BOB_MD = _TREE / "agents" / "bob.md"
_CANON_SCHEMA = _META_DIR / "schemas" / "execution-report.v1.json"
_NODE = shutil.which("node")

# The same wrap the Workflow harness applies (see test_identity_check.py): strip
# `export ` from meta and run the whole file inside an async function, under a
# stub `agent` that replays a scripted list of reports and records every call.
_DRIVER_JS = r"""
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const src = readFileSync(process.argv[2], "utf8");
const stripped = src.replace(/^export const meta/m, "const meta");
if (stripped === src) { console.log(JSON.stringify({ error: "transform did not apply" })); process.exit(3); }
const dir = mkdtempSync(join(tmpdir(), "wfdrv-"));
const p = join(dir, "wrapped.mjs");
writeFileSync(p, "export async function __run(args, agent) {\n" + stripped + "\n}\n");
const { __run } = await import("file://" + p);
const plan = JSON.parse(process.argv[3]);
const calls = [];
const agent = async (prompt, opts) => {
  calls.push({ prompt: prompt, model: opts && opts.model === undefined ? null : opts.model });
  return plan.script.length ? plan.script.shift() : null;
};
const result = await __run(JSON.parse(process.argv[4]), agent);
console.log(JSON.stringify({ result: result === undefined ? null : result, calls: calls }));
"""


def _node_json(js_source, *argv):
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "x.mjs"
        f.write_text(js_source, encoding="utf-8")
        proc = subprocess.run([_NODE, str(f), *argv], capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        raise AssertionError("node exit {0}: {1}".format(proc.returncode, proc.stderr[:800]))
    return json.loads(proc.stdout)


def _run_wf(script, args, wf_path=None):
    return _node_json(_DRIVER_JS, str(wf_path or _WF), json.dumps({"script": script}), json.dumps(args))


_FIXTURE_WF_DIR = tempfile.TemporaryDirectory(prefix="wf-default-benched-")


def _wf_with_default_benched(families):
    """A copy of the workflow whose DEFAULT_BENCHED is the FIXTURE list `families`.

    #291 fix round 1 (E): the tests of the default's behaviour used to run against the
    COMMITTED default, so a runbook s7 revert (DEFAULT_BENCHED = [] together with the roster)
    broke them although nothing was wrong. The parity test (DEFAULT_BENCHED == the roster)
    is the one that reads the committed value."""
    text = _WF.read_text(encoding="utf-8")
    pinned = re.sub(r"^const DEFAULT_BENCHED = \[[^\]]*\];",
                    "const DEFAULT_BENCHED = " + json.dumps(list(families)) + ";",
                    text, count=1, flags=re.MULTILINE)
    assert pinned != text or ("const DEFAULT_BENCHED = " + json.dumps(list(families)) + ";") in text
    path = Path(_FIXTURE_WF_DIR.name) / ("bob-serial-exec-" + "-".join(families or ["none"]) + ".js")
    path.write_text(pinned, encoding="utf-8")
    return path


_WF_FABLE_DEFAULT = None


def _wf_fable():
    global _WF_FABLE_DEFAULT
    if _WF_FABLE_DEFAULT is None:
        _WF_FABLE_DEFAULT = _wf_with_default_benched(["fable"])
    return _WF_FABLE_DEFAULT


def _js_block(text, start_marker, end_marker="\n}"):
    """Source text of one top-level declaration of the workflow, extracted by marker."""
    start = text.index(start_marker)
    return text[start:text.index(end_marker, start) + len(end_marker)]


def _report(**over):
    r = {"status": "PARTIAL", "built": [], "files_changed": [], "verification": {}}
    r.update(over)
    return r


def _load_ok(order):
    return {"schema_version": "plan-load.v1", "plan_id": "P", "plan_hash": "h",
            "hash_ok": True, "wp_order": order}


def _args(models=None, benched="absent"):
    a = {"project_root": "/r", "plan_path": "p.yaml", "plan_hash": "h", "plan_revision": 0,
         "ledger_state_version": "N/A", "map_sig_sha256": "N/A", "run_label": "t291",
         "run_started_at": "T0"}
    if models is not None:
        a["models"] = models
    if benched != "absent":
        a["benched"] = benched
    return a


def _takeover_script(rung="takeover"):
    """opus fails -> asks for the takeover rung -> (if dispatched) COMPLETE -> finalize."""
    return [
        _load_ok(["WP-1", "WP-2"]),
        _report(escalation={"next_rung": rung, "task_key": "P:WP-1", "attempt_id": 3}),
        _report(status="COMPLETE"),
        _report(status="COMPLETE"),
        _report(status="COMPLETE"),
    ]


def _wp_calls(out, wp):
    return [c for c in out["calls"] if "wp_id: {0}".format(wp) in c["prompt"]]


@unittest.skipIf(_NODE is None, "node not installed")
class TakeoverDispatch291(unittest.TestCase):

    def _assert_refused(self, out, reason, forbidden_model=None):
        calls = _wp_calls(out, "WP-1")
        self.assertEqual(len(calls), 1, "the refused rung is NOT dispatched")
        if forbidden_model is not None:
            self.assertEqual([c for c in out["calls"] if c["model"] == forbidden_model], [],
                             "no stage ran on the refused model")
        self.assertEqual(_wp_calls(out, "WP-2"), [], "the loop stops at the WP")
        res = out["result"]
        self.assertEqual(res["status"], "PARTIAL")
        self.assertEqual(res["needs"]["kind"], "escalation-diagnosis")
        self.assertEqual(res["needs"]["payload"]["refused_rung"]["reason"], reason)
        self.assertEqual(res["needs"]["payload"]["failed_wp"], "WP-1")
        self.assertEqual(len(res["needs"]["payload"]["prior_attempts"]), 1)

    # -- benched families are refused, never dispatched -----------------------
    def test_a_benched_escalation_model_with_explicit_benched_is_refused(self):
        for model in ("fable", "claude-fable-5-1", "fable[1m]", "FABLE"):
            for rung in ("takeover", "fable"):
                with self.subTest(model=model, rung=rung):
                    out = _run_wf(_takeover_script(rung),
                                  _args({"bob": "opus", "escalation": model}, ["fable"]))
                    self._assert_refused(out, "benched-model", forbidden_model=model)
                    self.assertEqual(out["result"]["needs"]["payload"]["refused_rung"]["model"], model)

    def test_absent_benched_refuses_any_fable_token(self):
        for model in ("fable", "claude-fable-5-1", "Fable[1m]"):
            with self.subTest(model=model):
                out = _run_wf(_takeover_script(), _args({"bob": "opus", "escalation": model}), _wf_fable())
                self._assert_refused(out, "benched-model", forbidden_model=model)

    def test_control_an_unbenched_escalation_model_is_dispatched(self):
        out = _run_wf(_takeover_script(), _args({"bob": "opus", "escalation": "opus"}, ["fable"]))
        self.assertEqual([c["model"] for c in _wp_calls(out, "WP-1")], ["opus", "opus"])
        self.assertEqual(out["result"]["status"], "COMPLETE")

    def test_an_empty_args_benched_cannot_unbench_the_default(self):
        # #291 fix round 1, finding J: args.benched used to REPLACE DEFAULT_BENCHED, so a
        # caller passing [] dispatched fable. The effective set is now the union.
        for model in ("fable", "claude-fable-5-1", "Fable 5.1"):
            with self.subTest(model=model):
                out = _run_wf(_takeover_script(), _args({"bob": "opus", "escalation": model}, []), _wf_fable())
                self._assert_refused(out, "benched-model", forbidden_model=model)
                self.assertIn("fable", out["result"]["needs"]["payload"]["refused_rung"]["benched"])
        out = _run_wf(_takeover_script(), _args({"bob": "fable", "escalation": "opus"}, []), _wf_fable())
        self.assertEqual(out["calls"], [])
        self.assertEqual(out["result"]["needs"]["payload"]["reason"], "benched-executor-model")

    def test_control_the_caller_adds_families_on_top_of_the_default(self):
        # A roster benching another family refuses that one AND still the default.
        out = _run_wf(_takeover_script(), _args({"bob": "opus", "escalation": "sonnet"}, ["sonnet"]), _wf_fable())
        self._assert_refused(out, "benched-model", forbidden_model="sonnet")
        out = _run_wf(_takeover_script(), _args({"bob": "opus", "escalation": "fable"}, ["sonnet"]), _wf_fable())
        self._assert_refused(out, "benched-model", forbidden_model="fable")

    def test_reversibility_is_the_default_edit_the_runbook_names(self):
        # Runbook s7 revert: DEFAULT_BENCHED becomes [] together with the roster (the parity
        # test below holds them equal), and then an empty args.benched dispatches fable.
        out = _run_wf(_takeover_script(), _args({"bob": "opus", "escalation": "fable"}, []),
                      _wf_with_default_benched([]))
        self.assertEqual([c["model"] for c in _wp_calls(out, "WP-1")], ["opus", "fable"])

    def test_a_benched_executor_model_refuses_the_run_before_any_stage(self):
        out = _run_wf(_takeover_script(), _args({"bob": "claude-fable-5-1", "escalation": "opus"}), _wf_fable())
        self.assertEqual(out["calls"], [], "nothing is dispatched on a benched executor model")
        self.assertEqual(out["result"]["status"], "PARTIAL")
        self.assertEqual(out["result"]["needs"]["payload"]["reason"], "benched-executor-model")

    # -- #291 fix round 2 N7b: a malformed args.benched is never ignored silently --
    def _complete_script(self):
        return [_load_ok(["WP-1"]), _report(status="COMPLETE"), _report(status="COMPLETE")]

    def test_a_string_args_benched_is_one_family_and_warned_about(self):
        out = _run_wf(_takeover_script(), _args({"bob": "sonnet", "escalation": "opus"}, "sonnet"),
                      _wf_fable())
        self.assertEqual(out["calls"], [], "the string names a benched family: nothing dispatched")
        res = out["result"]
        self.assertEqual(res["needs"]["payload"]["reason"], "benched-executor-model")
        self.assertEqual(sorted(res["needs"]["payload"]["benched"]), ["fable", "sonnet"])
        warnings = res["verification"]["benched_warnings"]
        self.assertTrue(any("string" in w and "one-element" in w for w in warnings), warnings)

    def test_a_non_list_args_benched_is_ignored_with_a_recorded_warning(self):
        for bad in (42, {"fable": True}, None, True):
            with self.subTest(bad=bad):
                out = _run_wf(self._complete_script(), _args({"bob": "opus"}, bad), _wf_fable())
                res = out["result"]
                self.assertEqual(res["status"], "COMPLETE")
                warnings = res["verification"]["benched_warnings"]
                self.assertTrue(any("ignored" in w for w in warnings), warnings)

    def test_non_string_entries_are_dropped_with_a_recorded_warning(self):
        out = _run_wf(self._complete_script(), _args({"bob": "opus"}, ["sonnet", 7, ""]), _wf_fable())
        warnings = out["result"]["verification"]["benched_warnings"]
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("2", warnings[0])

    def test_control_a_well_formed_args_benched_records_no_warning(self):
        for good in (["sonnet"], [], "absent"):
            with self.subTest(good=good):
                out = _run_wf(self._complete_script(), _args({"bob": "opus"}, good), _wf_fable())
                self.assertNotIn("benched_warnings", out["result"]["verification"])

    # -- a missing escalation model refuses the takeover -----------------------
    def test_a_missing_escalation_model_refuses_the_takeover(self):
        for models in ({"bob": "opus"}, {"bob": "opus", "escalation": ""}, None):
            with self.subTest(models=models):
                out = _run_wf(_takeover_script(), _args(models, ["fable"]))
                self._assert_refused(out, "missing-escalation-model")

    def test_control_the_opus_rung_still_inherits_when_models_is_absent(self):
        # The S059 dormant path is unchanged for the executor: undefined => inherit.
        out = _run_wf([
            _load_ok(["WP-1"]),
            _report(escalation={"next_rung": "opus", "task_key": "P:WP-1", "attempt_id": 1}),
            _report(status="COMPLETE"),
            _report(status="COMPLETE"),
        ], _args(None))
        self.assertEqual([c["model"] for c in _wp_calls(out, "WP-1")], [None, None])
        self.assertEqual(out["result"]["status"], "COMPLETE")

    # -- same_model_as_executor ------------------------------------------------
    def _takeover_record(self, models):
        out = _run_wf([
            _load_ok(["WP-1"]),
            _report(escalation={"next_rung": "takeover", "task_key": "P:WP-1", "attempt_id": 3}),
            _report(escalation={"next_rung": "diagnosis", "task_key": "P:WP-1", "attempt_id": 4}),
        ], _args(models, ["fable"]))
        calls = _wp_calls(out, "WP-1")
        self.assertEqual(len(calls), 2)
        dispatches = out["result"]["verification"]["rung_dispatches"]
        self.assertEqual(dispatches[0], {"attempt": 1, "rung": None,
                                         "model": models.get("bob") if models else None})
        self.assertEqual(dispatches[1]["rung"], "takeover")
        return calls[1]["prompt"], dispatches[1]

    def test_same_model_as_executor_is_recorded_when_equal(self):
        prompt, rec = self._takeover_record({"bob": "opus", "escalation": "opus"})
        self.assertIs(rec["same_model_as_executor"], True)
        self.assertIn("same_model_as_executor: true", prompt)
        self.assertIn("rung: takeover", prompt)

    def test_same_model_compares_with_bobs_frontmatter_when_bob_is_undefined(self):
        # bob.md frontmatter is opus[1m]; the suffix is not part of the model.
        _, rec = self._takeover_record({"escalation": "opus"})
        self.assertIs(rec["same_model_as_executor"], True)

    def test_control_a_different_escalation_model_is_recorded_as_different(self):
        prompt, rec = self._takeover_record({"bob": "sonnet", "escalation": "opus"})
        self.assertIs(rec["same_model_as_executor"], False)
        self.assertIn("same_model_as_executor: false", prompt)

    def test_control_a_first_attempt_prompt_carries_no_rung_lines(self):
        out = _run_wf(_takeover_script(), _args({"bob": "opus", "escalation": "opus"}, ["fable"]))
        first = _wp_calls(out, "WP-1")[0]["prompt"]
        self.assertNotIn("rung:", first)
        self.assertNotIn("same_model_as_executor", first)


@unittest.skipIf(_NODE is None, "node not installed")
class TakeoverSchemaAndParity291(unittest.TestCase):

    def setUp(self):
        self.text = _WF.read_text(encoding="utf-8")

    def _workflow_schema(self):
        block = _js_block(self.text, "const EXECUTION_REPORT_SCHEMA = {", "\n};")
        return _node_json(block + "\nconsole.log(JSON.stringify(EXECUTION_REPORT_SCHEMA));\n")

    def test_the_workflow_schema_enum_is_escalations_readable_rungs(self):
        enum = self._workflow_schema()["properties"]["escalation"]["properties"]["next_rung"]["enum"]
        self.assertEqual(set(enum), set(_esc.READABLE_RUNGS))
        self.assertIn("takeover", enum)
        self.assertIn("fable", enum, "the legacy spelling still validates")

    def test_a_takeover_report_validates_against_both_schemas(self):
        try:
            import jsonschema
        except ImportError:  # pragma: no cover
            self.skipTest("jsonschema not installed")
        canon = json.loads(_CANON_SCHEMA.read_text(encoding="utf-8"))
        wf = self._workflow_schema()
        for rung in ("takeover", "fable"):
            report = _report(escalation={"next_rung": rung, "task_key": "P:WP-1", "attempt_id": 3})
            with self.subTest(rung=rung):
                jsonschema.validate(instance=report, schema=canon)
                jsonschema.validate(instance=report, schema=wf)
        bad = _report(escalation={"next_rung": "gpt-9-omega", "task_key": "P:WP-1", "attempt_id": 3})
        for schema in (canon, wf):
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(instance=bad, schema=schema)

    def test_rung_model_key_routes_takeover_and_its_legacy_spelling_to_escalation(self):
        block = _js_block(self.text, "const RUNG_MODEL_KEY = ", ";")
        got = _node_json(block + "\nconsole.log(JSON.stringify(RUNG_MODEL_KEY));\n")
        self.assertEqual(got, {"opus": "bob", "takeover": "escalation", "fable": "escalation"})
        for legacy, current in _esc.LEGACY_RUNG_ALIASES.items():
            self.assertEqual(got[legacy], got[current])

    def test_the_js_normaliser_agrees_with_seat_model_is_benched(self):
        src = (_js_block(self.text, "function idTokens(id) {")
               + "\n" + _js_block(self.text, "function isBenchedModel(model, benched) {")
               + "\nconst ids = JSON.parse(process.argv[2]);"
               + "\nconsole.log(JSON.stringify(ids.map((m) => isBenchedModel(m, ['fable']))));\n")
        ids = ["fable", "fable[1m]", "FABLE", "claude-fable-5-1", " Fable ", "opus", "opus[1m]",
               "claude-opus-5-5", "sonnet", "fablex", "notfable", "claude-fables-1", "", "fable-5",
               # #291 fix round 1 (F, G): stacked suffixes, every separator, a glued version
               "fable[1m][1m]", "fable[1m] [1m]", "Fable 5.1", "claude_fable", "claude.fable.5",
               "claude/fable", "claude@fable", "claude:fable-5", "claude-fable5-1", "fable5",
               "Claude Fable 5.1 [1m]", "claude_fables", "fable5x", "fablea5", "5fable",
               "Opus 5.5", "claude.opus.5"]
        got = _node_json(src, json.dumps(ids))
        want = [_seat_model.is_benched(m, frozenset({"fable"})) for m in ids]
        self.assertEqual(got, want)
        # Pinned, not only "agrees with Python": both twins could drift together.
        benched = {"fable", "fable[1m]", "FABLE", "claude-fable-5-1", " Fable ", "fable-5",
                   "fable[1m][1m]", "fable[1m] [1m]", "Fable 5.1", "claude_fable", "claude.fable.5",
                   "claude/fable", "claude@fable", "claude:fable-5", "claude-fable5-1", "fable5",
                   "Claude Fable 5.1 [1m]"}
        self.assertEqual(dict(zip(ids, got)), {m: m in benched for m in ids})
        self.assertTrue(any(want) and not all(want), "the id list must exercise both answers")

    def test_n4_n5_bracket_groups_and_whitespace_are_pinned_in_both_twins(self):
        """#291 fix round 2. N4: a bracketed / parenthesised group ANYWHERE is removed (it
        acts as a separator), not only a trailing one. N5: the separator set is EXPLICIT --
        every character outside ASCII [a-z0-9] after ASCII lowercasing -- so Python and JS
        agree on BOM, U+0085, U+001C, NBSP and friends: they ARE separators (a broken id
        can only refuse more). Literal expectations, run through BOTH twins."""
        src = (_js_block(self.text, "function idTokens(id) {")
               + "\n" + _js_block(self.text, "function isBenchedModel(model, benched) {")
               + "\n" + _js_block(self.text, "function sameModel(a, b) {")
               + "\nconst q = JSON.parse(process.argv[2]);"
               + "\nconsole.log(JSON.stringify({benched: q.ids.map((m) => isBenchedModel(m, ['fable'])),"
               + " same: q.pairs.map(([a, b]) => sameModel(a, b))}));\n")
        pinned = {
            # N4: groups anywhere
            "claude-fable[1m]-5-1": True, "fable[1m]5": True, "fable(1m)": True,
            "claude-fable(1m)-5": True, "fable[1m](x)": True, "fable]": True, "(fable": True,
            "opus[fable]": False, "opus(fable)": False, "fablex[1m]": False, "fable[1m]x": True,
            "[1m]": False,
            # N5: non-ASCII / control characters are separators, identically in both
            "\ufefffable": True, "fable\u0085": True, "\x1cfable": True, "fable\u00a0": True,
            "fable\u2028": True, "claude\u00a0fable\u00a05": True, "fable\u200b": True,
            "fa\u00adble": False, "\uff46\uff41\uff42\uff4c\uff45": False, "fable\tx": True,
            "fable+5": True, "FABLE\u212a": True,
            # unchanged controls
            "fable": True, "claude-fable-5-1": True, "fablex": False, "fable5x": False, "opus": False,
        }
        pairs = [["opus[1m]", "opus"], ["claude-opus[1m]-5-5", "claude-opus-5-5"],
                 ["\ufeffopus", "opus"], ["opus", "sonnet"], ["opus(1m)", "OPUS"]]
        want_same = [True, True, True, False, True]
        ids = list(pinned)
        got = _node_json(src, json.dumps({"ids": ids, "pairs": pairs}))
        self.assertEqual(dict(zip(ids, got["benched"])), pinned, "JS twin")
        py = {m: _seat_model.is_benched(m, frozenset({"fable"})) for m in ids}
        self.assertEqual(py, pinned, "Python twin")
        self.assertEqual(got["same"], want_same, "JS sameModel")
        import model_ids as _ids
        self.assertEqual([_ids.id_tokens(a) == _ids.id_tokens(b) for a, b in pairs], want_same,
                         "Python token equality")

    def test_the_default_benched_set_equals_the_roster(self):
        # #291 fix round 1, finding H: DEFAULT_BENCHED is a hand-pinned copy of
        # model_roster.CLAUDE_BENCHED; the runbook (s3 step 2) edits both, this holds them equal.
        m = re.search(r"^const DEFAULT_BENCHED = (\[[^\]]*\]);", self.text, re.MULTILINE)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1)), sorted(_seat_model.model_roster.CLAUDE_BENCHED))

    def test_the_frontmatter_twin_matches_bob_md(self):
        m = re.search(r'^const BOB_FRONTMATTER_MODEL = "([^"]+)";', self.text, re.MULTILINE)
        self.assertIsNotNone(m)
        fm = _BOB_MD.read_text(encoding="utf-8").split("---", 2)[1]
        model = re.search(r"^model:\s*(\S+)\s*$", fm, re.MULTILINE)
        self.assertIsNotNone(model, "bob.md frontmatter declares no model")
        self.assertEqual(m.group(1), model.group(1))


if __name__ == "__main__":
    unittest.main()
