#!/usr/bin/env python3
"""Tests for identity_check.py (Evergreening v1, S041, #119 detection).

§9.1: identity 3-tree fixtures — match, mismatch, missing-tree -> partial.

stdlib unittest. Run:
  python3 -m unittest discover -s ~/.claude/skills/_meta/tests -p 'test_identity_check.py' -v
"""
from __future__ import annotations

import importlib.util
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
        SAFETY_KEYWORDS = (
            "gates", "claims", "trusted_runner", "pause", "scope",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
