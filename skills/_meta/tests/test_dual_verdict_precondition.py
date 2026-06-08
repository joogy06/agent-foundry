#!/usr/bin/env python3
"""test_dual_verdict_precondition.py — S044 / #118 coverage.

Covers the prose-to-gate conversion (design §10 B1-B7):

  Legal-transition table (B1):
    - every legal pair in LEGAL_TRANSITIONS passes check_transition_legal
    - illegal pairs are rejected
    - any ->PLANNED demote bumps the component generation (CB1)

  R6 — assert_verified_preconditions (B2/B4):
    - both arms pass -> returns archive (ok)
    - audit arm missing -> raise
    - AUDIT_UNAVAILABLE on either arm -> raise
    - arbiter-pass-but-audit-REJECTED -> raise (#43-dev3)
    - unversioned archive -> raise (C6 schema-drift)
    - cross-binding mismatch (component/bundle/request/prior_state/generation) -> raise
    - the S039 asymmetric-key fixture (audit_arm.result vs arbiter_arm.verdict;
      misleading rerun_notes.first_run_result: AUDIT_UNAVAILABLE is IGNORED)

  apply_request_idempotent engine (B1/B5):
    - idempotent dedup by request_id ONLY across non-VERIFIED transitions
    - existing transitions (PLANNED->SCAFFOLDED->...->INTEGRATED) work through
      the engine
    - INTEGRATED->VERIFIED dispatches R6 (fails closed without a valid archive)
    - B5 crash-recovery: VERIFIED written then crash-before-consume -> replay is
      idempotent (exactly 1 transition-log event) + the stranded open request
      sweeps to 'abandoned' (NOT 'consumed') + a fresh request can open

Run:
    pytest ~/.claude/skills/_meta/tests/test_dual_verdict_precondition.py -v
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import yaml  # noqa: E402

import claims  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _mk_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="dual-verdict-"))


def _write_ledger(root: Path, rows: List[str]) -> Path:
    """Write a real-format ledger with the given projection rows.

    `rows` are full markdown table rows like
    '| WP-1 | alpha | PLANNED | 0 | — |'.
    """
    (root / "progress").mkdir(parents=True, exist_ok=True)
    ledger = root / "progress" / "integration-ledger.md"
    body_rows = "\n".join(rows)
    ledger.write_text(
        "---\n"
        "schema_version: 1\n"
        'contract_map_hash: "abc123"\n'
        "contract_map_revision: 2\n"
        "consumed_request_ids: []\n"
        'drift_canary: "ALDEBARAN-7"\n'
        "pause_epoch: 0\n"
        "---\n"
        "\n"
        "# Test ledger\n"
        "\n"
        "## Projection (current state — one row per WP/component)\n"
        "\n"
        "| WP | component | stage | generation | deps |\n"
        "|----|-----------|-------|------------|------|\n"
        f"{body_rows}\n"
        "\n"
        "## Transition log\n"
        "\n"
        "| # | WP | component | from -> to | generation | evidence |\n"
        "|---|----|-----------|-----------|------------|----------|\n"
        "\n"
        "## Notes\n"
        "\n"
        "- preserved verbatim marker XYZZY\n"
    )
    return ledger


def _write_archive(root: Path, bundle_hash: str, **overrides: Any) -> Path:
    """Write a dual-verdict.v1 archive; overrides patch top-level or arm keys."""
    vdir = root / ".ledger" / "verdicts"
    vdir.mkdir(parents=True, exist_ok=True)
    arch: Dict[str, Any] = {
        "schema_version": "dual-verdict.v1",
        "component_id": "foo",
        "bundle_hash": bundle_hash,
        "verification_request_id": "vr-1",
        "prior_state_version": "sv-1",
        "generation": 0,
        "audit_arm": {"result": "VERIFIED"},
        "arbiter_arm": {"verdict": "VERIFIED"},
    }
    for k, v in overrides.items():
        arch[k] = v
    path = vdir / f"{bundle_hash}.verdict.yaml"
    path.write_text(yaml.safe_dump(arch))
    return path


def _bh(seed: str = "a") -> str:
    return (seed * 64)[:64]


# S048 / #116: R6 now ALSO requires a GREEN deterministic bundle. Tests that
# expect R6 to PASS must write a real hash-addressed GREEN bundle and use ITS
# hash for the archive. This helper builds a passing bundle, hashes it with the
# canonical bundle_hash_hex (so the on-disk filename == the hash R6 recomputes),
# writes it, and returns the bundle_hash. Tests that expect R6 to FAIL at the
# LLM-arm checks (missing arm, AUDIT_UNAVAILABLE, schema, cross-binding) never
# reach the deterministic step, so they keep using the cheap _bh() fakes.

import json as _json  # noqa: E402

import trusted_runner as _tr  # noqa: E402
import deterministic_arm as _da  # noqa: E402


def _write_green_bundle(root: Path, component_id: str = "foo", *,
                        sanctioned_only: bool = False,
                        degraded: bool = False,
                        red: bool = False,
                        tests=None) -> str:
    """Write a hash-addressed bundle and return its bundle_hash.

    Default = a plain GREEN pytest bundle (1 passing test). Flags produce the
    other classification states for negative tests.
    """
    if tests is None:
        if red:
            results = [{"path": "t.py", "returncode": 1,
                        "summary": {"total": 1, "passed": 0, "failed": 1,
                                    "error": 0, "skipped": 0, "duration_s": 0.0},
                        "failed_tests": [{"nodeid": "t::a", "outcome": "failed"}],
                        "tests": [{"nodeid": "t::a", "outcome": "failed",
                                   "duration_s": 0.0, "keywords": []}]}]
        elif degraded:
            results = [{"path": "t.py", "returncode": 0,
                        "summary": {"total": 1, "passed": 1, "failed": 0,
                                    "error": 0, "skipped": 0, "duration_s": 0.0},
                        "failed_tests": []}]  # no tests[] -> degraded
        elif sanctioned_only:
            results = [{"path": "t.py", "returncode": 0,
                        "summary": {"total": 1, "passed": 0, "failed": 0,
                                    "error": 0, "skipped": 1, "duration_s": 0.0},
                        "failed_tests": [],
                        "tests": [{"nodeid": "t::a", "outcome": "skipped",
                                   "duration_s": 0.0, "keywords": [],
                                   "required_tier": 2,
                                   "sanctioned_tier_skip": True}]}]
        else:
            results = [{"path": "t.py", "returncode": 0,
                        "summary": {"total": 2, "passed": 2, "failed": 0,
                                    "error": 0, "skipped": 0, "duration_s": 0.0},
                        "failed_tests": [],
                        "tests": [{"nodeid": "t::a", "outcome": "passed",
                                   "duration_s": 0.0, "keywords": []},
                                  {"nodeid": "t::b", "outcome": "passed",
                                   "duration_s": 0.0, "keywords": []}]}]
    else:
        results = tests
    bundle = {
        "component_id": component_id,
        "produced_by": "bob-trusted-runner",
        "runner_info": {"runner": "pytest", "version": "test"},
        "run_at": "2026-06-08T00:00:00Z",
        "test_paths": ["t.py"],
        "results": results,
    }
    bh = _tr.bundle_hash_hex(bundle)
    bundle["bundle_hash"] = bh
    p = _da.bundle_path_for(component_id, bh, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(bundle), encoding="utf-8")
    return bh


def _event_rows(ledger: Path) -> List[str]:
    return [
        ln for ln in ledger.read_text().splitlines()
        if re.match(r"^\|\s*\d+\s*\|", ln)
    ]


# ---------------------------------------------------------------------------
# B1 — legal-transition table
# ---------------------------------------------------------------------------

class TestLegalTransitionTable(unittest.TestCase):
    def test_locked_table_shape(self) -> None:
        # The exact table from design §10 B1.
        self.assertEqual(
            set(claims.LEGAL_TRANSITIONS.keys()),
            {"PLANNED", "SCAFFOLDED", "UNIT_TESTED", "INTEGRATED",
             "VERIFIED", "DOCUMENTED", "BLOCKED"},
        )
        self.assertEqual(claims.LEGAL_TRANSITIONS["PLANNED"], frozenset({"SCAFFOLDED", "BLOCKED"}))
        self.assertEqual(claims.LEGAL_TRANSITIONS["SCAFFOLDED"], frozenset({"UNIT_TESTED", "BLOCKED", "PLANNED"}))
        self.assertEqual(claims.LEGAL_TRANSITIONS["UNIT_TESTED"], frozenset({"INTEGRATED", "BLOCKED", "PLANNED"}))
        self.assertEqual(claims.LEGAL_TRANSITIONS["INTEGRATED"], frozenset({"VERIFIED", "BLOCKED", "PLANNED"}))
        self.assertEqual(claims.LEGAL_TRANSITIONS["VERIFIED"], frozenset({"DOCUMENTED", "BLOCKED", "PLANNED"}))
        self.assertEqual(claims.LEGAL_TRANSITIONS["DOCUMENTED"], frozenset())  # terminal
        self.assertEqual(claims.LEGAL_TRANSITIONS["BLOCKED"], frozenset({"PLANNED"}))

    def test_legal_pairs_pass(self) -> None:
        for frm, tos in claims.LEGAL_TRANSITIONS.items():
            for to in tos:
                self.assertTrue(
                    claims.check_transition_legal(frm, to),
                    f"{frm}->{to} should be legal",
                )

    def test_illegal_pairs_reject(self) -> None:
        illegal = [
            ("PLANNED", "VERIFIED"),    # skip the chain
            ("PLANNED", "UNIT_TESTED"),
            ("INTEGRATED", "SCAFFOLDED"),  # backward
            ("DOCUMENTED", "PLANNED"),  # terminal cannot move
            ("DOCUMENTED", "VERIFIED"),
            ("VERIFIED", "UNIT_TESTED"),
            ("SCAFFOLDED", "VERIFIED"),
            ("UNKNOWN", "PLANNED"),     # unknown from -> fail closed
        ]
        for frm, to in illegal:
            self.assertFalse(
                claims.check_transition_legal(frm, to),
                f"{frm}->{to} should be illegal",
            )

    def test_demote_to_planned_bumps_generation(self) -> None:
        root = _mk_root()
        ledger = _write_ledger(root, ["| WP-1 | alpha | INTEGRATED | 0 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "demote-1", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "PLANNED", "evidence": "restart"}, root)
        self.assertEqual(r["outcome"], "applied")
        self.assertEqual(r["generation"], 1)  # 0 -> 1
        led = claims.read_ledger(ledger)
        self.assertEqual(led.row("WP-1").stage, "PLANNED")
        self.assertEqual(led.row("WP-1").generation, 1)

    def test_blocked_unblock_to_planned_bumps_generation(self) -> None:
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | BLOCKED | 2 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "unblock-1", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "PLANNED"}, root)
        self.assertEqual(r["outcome"], "applied")
        self.assertEqual(r["generation"], 3)  # 2 -> 3

    def test_forward_step_does_not_bump_generation(self) -> None:
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | PLANNED | 5 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "fwd-1", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "SCAFFOLDED"}, root)
        self.assertEqual(r["generation"], 5)  # unchanged


# ---------------------------------------------------------------------------
# B2/B4 — R6 assert_verified_preconditions
# ---------------------------------------------------------------------------

class TestR6Preconditions(unittest.TestCase):
    def test_both_pass_returns_archive(self) -> None:
        root = _mk_root()
        bh = _write_green_bundle(root, "foo")  # S048: GREEN bundle required
        _write_archive(root, bh)
        out = claims.assert_verified_preconditions(bh, root)
        self.assertEqual(out["component_id"], "foo")
        self.assertEqual(out["bundle_hash"], bh)

    def test_both_pass_with_concerns_allowed(self) -> None:
        root = _mk_root()
        bh = _write_green_bundle(root, "foo")
        _write_archive(root, bh, audit_arm={"result": "VERIFIED_WITH_CONCERNS"},
                       arbiter_arm={"verdict": "VERIFIED_WITH_CONCERNS"})
        out = claims.assert_verified_preconditions(bh, root)
        self.assertIsNotNone(out)

    def test_audit_arm_missing_raises(self) -> None:
        root = _mk_root()
        bh = _bh("b")
        _write_archive(root, bh)
        # remove audit_arm entirely (arbiter-only archive)
        p = root / ".ledger" / "verdicts" / f"{bh}.verdict.yaml"
        d = yaml.safe_load(p.read_text())
        del d["audit_arm"]
        p.write_text(yaml.safe_dump(d))
        with self.assertRaises(claims.VerifiedPreconditionError):
            claims.assert_verified_preconditions(bh, root)

    def test_arbiter_arm_missing_raises(self) -> None:
        root = _mk_root()
        bh = _bh("b")
        _write_archive(root, bh)
        p = root / ".ledger" / "verdicts" / f"{bh}.verdict.yaml"
        d = yaml.safe_load(p.read_text())
        del d["arbiter_arm"]
        p.write_text(yaml.safe_dump(d))
        with self.assertRaises(claims.VerifiedPreconditionError):
            claims.assert_verified_preconditions(bh, root)

    def test_audit_unavailable_raises(self) -> None:
        root = _mk_root()
        bh = _bh("c")
        _write_archive(root, bh, audit_arm={"result": "AUDIT_UNAVAILABLE"})
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("non-pass", str(ctx.exception))

    def test_arbiter_audit_unavailable_raises(self) -> None:
        root = _mk_root()
        bh = _bh("c")
        _write_archive(root, bh, arbiter_arm={"verdict": "AUDIT_UNAVAILABLE"})
        with self.assertRaises(claims.VerifiedPreconditionError):
            claims.assert_verified_preconditions(bh, root)

    def test_arbiter_pass_but_audit_rejected_raises(self) -> None:
        # The #43-dev3 case: arbiter passes, audit arm REJECTED -> fail closed.
        root = _mk_root()
        bh = _bh("d")
        _write_archive(root, bh, audit_arm={"result": "REJECTED"},
                       arbiter_arm={"verdict": "VERIFIED_WITH_CONCERNS"})
        with self.assertRaises(claims.VerifiedPreconditionError):
            claims.assert_verified_preconditions(bh, root)

    def test_missing_archive_raises(self) -> None:
        root = _mk_root()
        (root / ".ledger" / "verdicts").mkdir(parents=True)
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(_bh("z"), root)
        self.assertIn("not attempted", str(ctx.exception))

    def test_unversioned_archive_raises(self) -> None:
        root = _mk_root()
        bh = _bh("e")
        _write_archive(root, bh)
        p = root / ".ledger" / "verdicts" / f"{bh}.verdict.yaml"
        d = yaml.safe_load(p.read_text())
        del d["schema_version"]
        p.write_text(yaml.safe_dump(d))
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("schema_version", str(ctx.exception))

    def test_wrong_schema_version_raises(self) -> None:
        root = _mk_root()
        bh = _bh("e")
        _write_archive(root, bh, schema_version="dual-verdict.v2")
        with self.assertRaises(claims.VerifiedPreconditionError):
            claims.assert_verified_preconditions(bh, root)

    def test_missing_cross_binding_field_raises(self) -> None:
        for field in ("component_id", "verification_request_id",
                      "prior_state_version", "generation"):
            with self.subTest(field=field):
                root = _mk_root()
                bh = _bh("f")
                _write_archive(root, bh)
                p = root / ".ledger" / "verdicts" / f"{bh}.verdict.yaml"
                d = yaml.safe_load(p.read_text())
                del d[field]
                p.write_text(yaml.safe_dump(d))
                with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
                    claims.assert_verified_preconditions(bh, root)
                self.assertIn(field, str(ctx.exception))

    def test_cross_binding_mismatch_raises(self) -> None:
        # generation mismatch validated TOGETHER with the rest.
        root = _mk_root()
        bh = _bh("g")
        _write_archive(root, bh, generation=1)
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(
                bh, root, expected={"bundle_hash": bh, "generation": 2})
        self.assertIn("generation", str(ctx.exception))

    def test_cross_binding_component_mismatch_raises(self) -> None:
        root = _mk_root()
        bh = _bh("g")
        _write_archive(root, bh, component_id="foo")
        with self.assertRaises(claims.VerifiedPreconditionError):
            claims.assert_verified_preconditions(
                bh, root, expected={"bundle_hash": bh, "component_id": "WRONG"})

    def test_self_binding_bundle_hash_mismatch_raises(self) -> None:
        # archive.bundle_hash field != the lookup key (filename stem).
        root = _mk_root()
        bh = _bh("h")
        _write_archive(root, bh)
        # rewrite the internal bundle_hash field so it disagrees with the file.
        p = root / ".ledger" / "verdicts" / f"{bh}.verdict.yaml"
        d = yaml.safe_load(p.read_text())
        d["bundle_hash"] = "not-the-key"
        p.write_text(yaml.safe_dump(d))
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("self-binding", str(ctx.exception))

    def test_s039_asymmetric_key_fixture(self) -> None:
        """The S039 mis-bucketing fixture: canonical audit_arm.result is REJECTED
        but a free-text rerun_notes.first_run_result carries the misleading
        'AUDIT_UNAVAILABLE' string. R6 MUST read audit_arm.result ONLY (not
        substring-grep) and fail closed as REJECTED — not mis-bucket as
        AUDIT_UNAVAILABLE/indeterminate."""
        root = _mk_root()
        bh = _bh("i")
        _write_archive(
            root, bh,
            audit_arm={
                "result": "REJECTED",
                "claude_verdict": "pass_with_concerns",  # decoy sub-vocab
                "codex_verdict": "fail",                 # decoy sub-vocab
                "disagreements_count": 10,
            },
            arbiter_arm={"verdict": "VERIFIED_WITH_CONCERNS"},
            rerun_notes={
                "first_run_result":
                    "AUDIT_UNAVAILABLE (component_id mismatch: passed "
                    "design-drift-arbiter, map has drift-arbiter)",
            },
        )
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        msg = str(ctx.exception)
        # It must report the canonical audit_arm.result=REJECTED, NOT the
        # misleading rerun-history AUDIT_UNAVAILABLE string.
        self.assertIn("audit_arm.result", msg)
        self.assertIn("REJECTED", msg)

    def test_decoy_subvocab_not_read_as_axis(self) -> None:
        # claude_verdict/codex_verdict present but canonical result is VERIFIED
        # -> passes (the decoy keys are NOT the axis).
        root = _mk_root()
        bh = _write_green_bundle(root, "foo")
        _write_archive(
            root, bh,
            audit_arm={"result": "VERIFIED", "claude_verdict": "fail",
                       "codex_verdict": "fail"},
            arbiter_arm={"verdict": "VERIFIED"},
        )
        out = claims.assert_verified_preconditions(bh, root)
        self.assertIsNotNone(out)


# ---------------------------------------------------------------------------
# S048 / #116 — R6 deterministic-evidence conjunct + citation corroboration
# ---------------------------------------------------------------------------

class TestR6DeterministicArm(unittest.TestCase):
    def test_failed_bundle_vetoes_even_when_both_llm_arms_verified(self) -> None:
        """The headline case: a bundle with a FAILED test + both LLM arms say
        VERIFIED -> R6 vetoes (deterministic RED). A VERIFIED contradicting
        failing on-disk evidence is impossible."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo", red=True)  # RED bundle
        _write_archive(root, bh)  # both LLM arms VERIFIED
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("RED", str(ctx.exception))
        self.assertIn("deterministic", str(ctx.exception).lower())

    def test_empty_bundle_indeterminate_vetoes_despite_llms_verified(self) -> None:
        """Empty/all-skipped-NON-sanctioned bundle + LLMs VERIFIED -> veto
        (INDETERMINATE, not vacuous-pass)."""
        root = _mk_root()
        # all-skipped with no sanction stamp.
        bh = _write_green_bundle(root, "foo", tests=[{
            "path": "t.py", "returncode": 0,
            "summary": {"total": 1, "passed": 0, "failed": 0, "error": 0,
                        "skipped": 1, "duration_s": 0.0},
            "failed_tests": [],
            "tests": [{"nodeid": "t::a", "outcome": "skipped",
                       "duration_s": 0.0, "keywords": []}],
        }])
        _write_archive(root, bh)
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("INDETERMINATE", str(ctx.exception))

    def test_sanctioned_tier_skip_passes_R6(self) -> None:
        """R-B1: an all-skipped bundle whose skips are sanctioned tier-skips ->
        GREEN -> R6 PASSES (the false-block fix; no non-converging rerun)."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo", sanctioned_only=True)
        _write_archive(root, bh)
        out = claims.assert_verified_preconditions(bh, root)
        self.assertIsNotNone(out)

    def test_degraded_bundle_passes_R6(self) -> None:
        """R-I1: a returncode-only degraded bundle (rc==0) -> GREEN -> R6 PASSES;
        citation corroboration is unavailable on it (no veto)."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo", degraded=True)
        _write_archive(root, bh)
        out = claims.assert_verified_preconditions(bh, root)
        self.assertIsNotNone(out)

    def test_forged_archive_boolean_does_not_pass_when_real_bundle_red(self) -> None:
        """THE Codex-correction proof: a FORGED `deterministic_arm: GREEN` field
        in the archive does NOT pass when the REAL bundle is RED. R6 derives the
        verdict FROM the bundle, not from any producer-written boolean."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo", red=True)  # real bundle = RED
        # Bob/attacker plants a forged GREEN boolean in the archive.
        _write_archive(root, bh, deterministic_arm="GREEN",
                       deterministic_evidence={"state": "GREEN"})
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        # vetoed by the RE-DERIVED RED, ignoring the forged boolean.
        self.assertIn("RED", str(ctx.exception))

    def test_missing_bundle_indeterminate_vetoes(self) -> None:
        """Archive present + both LLM arms VERIFIED but NO on-disk bundle ->
        INDETERMINATE -> veto (never auto-pass on an evidence gap)."""
        root = _mk_root()
        bh = _bh("n")  # no bundle written at this hash
        _write_archive(root, bh)
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("not GREEN", str(ctx.exception))


class TestR6CitationCorroboration(unittest.TestCase):
    def test_new_rubric_requires_evidence_map(self) -> None:
        """R-B2: a verdict produced under the NEW rubric (>= cutover) MUST carry
        an evidence_map; absence -> veto."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo")
        _write_archive(root, bh,
                       arbiter_arm={"verdict": "VERIFIED", "rubric_version": "1.2.0"})
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("evidence_map", str(ctx.exception))

    def test_new_rubric_invented_citation_vetoes(self) -> None:
        """R-I3: under the new rubric, an evidence_map citing a non-existent
        nodeid -> veto (invented evidence)."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo")  # has t::a, t::b passing
        _write_archive(root, bh, arbiter_arm={
            "verdict": "VERIFIED", "rubric_version": "1.2.0",
            "evidence_map": {"REQ-1": ["t::a"], "REQ-2": ["t::ghost"]},
        })
        with self.assertRaises(claims.VerifiedPreconditionError) as ctx:
            claims.assert_verified_preconditions(bh, root)
        self.assertIn("citation", str(ctx.exception).lower())

    def test_new_rubric_valid_citation_passes(self) -> None:
        """Under the new rubric, an evidence_map citing only real passing nodeids
        -> R6 passes."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo")
        _write_archive(root, bh, arbiter_arm={
            "verdict": "VERIFIED", "rubric_version": "1.2.0",
            "evidence_map": {"REQ-1": ["t::a"], "REQ-2": ["t::b"]},
        })
        out = claims.assert_verified_preconditions(bh, root)
        self.assertIsNotNone(out)

    def test_old_rubric_skips_citation_deterministically(self) -> None:
        """The rubric-gated cutover: a verdict produced under the OLD rubric
        (< cutover) with NO evidence_map -> R6 does NOT require corroboration
        (deterministic, keyed to the producing rubric — no silent-disable gap)."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo")
        _write_archive(root, bh,
                       arbiter_arm={"verdict": "VERIFIED", "rubric_version": "1.1.0"})
        out = claims.assert_verified_preconditions(bh, root)
        self.assertIsNotNone(out)

    def test_new_rubric_degraded_bundle_citation_unavailable_no_veto(self) -> None:
        """Under the new rubric, a degraded bundle (no per-test records) with an
        evidence_map -> citation UNAVAILABLE -> no veto (can't corroborate what
        isn't there; the returncode floor still holds via GREEN)."""
        root = _mk_root()
        bh = _write_green_bundle(root, "foo", degraded=True)
        _write_archive(root, bh, arbiter_arm={
            "verdict": "VERIFIED", "rubric_version": "1.2.0",
            "evidence_map": {"REQ-1": ["anything"]},
        })
        out = claims.assert_verified_preconditions(bh, root)
        self.assertIsNotNone(out)


# ---------------------------------------------------------------------------
# B1 — engine: idempotent dedup + existing-transition flow + R6 dispatch
# ---------------------------------------------------------------------------

class TestEngineTransitions(unittest.TestCase):
    def test_existing_transitions_flow_through_engine(self) -> None:
        root = _mk_root()
        ledger = _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        for to in ("SCAFFOLDED", "UNIT_TESTED", "INTEGRATED"):
            r = claims.apply_request_idempotent(
                {"request_id": f"r-{to}", "wp": "WP-1", "component_id": "alpha",
                 "to_stage": to, "evidence": f"step {to}"}, root)
            self.assertEqual(r["outcome"], "applied", f"{to}: {r}")
        led = claims.read_ledger(ledger)
        self.assertEqual(led.row("WP-1").stage, "INTEGRATED")
        # exactly 3 transition-log events
        self.assertEqual(len(_event_rows(ledger)), 3)

    def test_idempotent_dedup_by_request_id(self) -> None:
        root = _mk_root()
        ledger = _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        req = {"request_id": "dup-req", "wp": "WP-1", "component_id": "alpha",
               "to_stage": "SCAFFOLDED"}
        r1 = claims.apply_request_idempotent(req, root)
        self.assertEqual(r1["outcome"], "applied")
        r2 = claims.apply_request_idempotent(req, root)
        self.assertEqual(r2["outcome"], "duplicate_ignored")
        # exactly 1 event despite 2 applies
        self.assertEqual(len(_event_rows(ledger)), 1)

    def test_dedup_is_by_request_id_only_not_attempt_id(self) -> None:
        """Two DIFFERENT request_ids for the same WP/stage both apply (the
        first as a legal transition, the second is then illegal because the
        stage already advanced — proving dedup is NOT keyed on
        request_id+attempt_id, design §10 B1 step 2)."""
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        r1 = claims.apply_request_idempotent(
            {"request_id": "req-A", "attempt_id": "1", "wp": "WP-1",
             "component_id": "alpha", "to_stage": "SCAFFOLDED"}, root)
        # different request_id, same logical target — NOT deduped; it is
        # re-evaluated against the (now advanced) ledger.
        r2 = claims.apply_request_idempotent(
            {"request_id": "req-B", "attempt_id": "2", "wp": "WP-1",
             "component_id": "alpha", "to_stage": "SCAFFOLDED"}, root)
        self.assertEqual(r1["outcome"], "applied")
        # SCAFFOLDED->SCAFFOLDED is not legal -> proves req-B was NOT a dedup
        # no-op (it was actually evaluated).
        self.assertEqual(r2["outcome"], "illegal_transition")

    def test_illegal_transition_outcome(self) -> None:
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "skip", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "VERIFIED"}, root)
        self.assertEqual(r["outcome"], "illegal_transition")

    def test_unknown_wp_outcome(self) -> None:
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "x", "wp": "WP-99", "component_id": "zeta",
             "to_stage": "SCAFFOLDED"}, root)
        self.assertEqual(r["outcome"], "unknown_wp")

    def test_missing_request_id_raises_keyerror(self) -> None:
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        with self.assertRaises(KeyError):
            claims.apply_request_idempotent(
                {"wp": "WP-1", "to_stage": "SCAFFOLDED"}, root)

    def test_integrated_to_verified_fails_closed_without_archive(self) -> None:
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | INTEGRATED | 0 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "v1", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "VERIFIED", "bundle_hash": _bh("a"),
             "generation": 0}, root)
        self.assertEqual(r["outcome"], "precondition_failed")
        self.assertIn("R6", r["reason"])

    def test_integrated_to_verified_no_bundle_hash_fails_closed(self) -> None:
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | INTEGRATED | 0 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "v2", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "VERIFIED"}, root)
        self.assertEqual(r["outcome"], "precondition_failed")

    def test_integrated_to_verified_applies_with_valid_archive(self) -> None:
        root = _mk_root()
        ledger = _write_ledger(root, ["| WP-1 | alpha | INTEGRATED | 0 | — |"])
        bh = _write_green_bundle(root, "alpha")  # S048: GREEN bundle required
        _write_archive(root, bh, component_id="alpha",
                       verification_request_id="vr-x",
                       prior_state_version="sv-x", generation=0)
        r = claims.apply_request_idempotent(
            {"request_id": "v3", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "VERIFIED", "bundle_hash": bh,
             "verification_request_id": "vr-x", "prior_state_version": "sv-x",
             "generation": 0, "evidence": "both arms pass"}, root)
        self.assertEqual(r["outcome"], "applied")
        self.assertEqual(claims.read_ledger(ledger).row("WP-1").stage, "VERIFIED")

    def test_header_and_notes_preserved_verbatim(self) -> None:
        root = _mk_root()
        ledger = _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        claims.apply_request_idempotent(
            {"request_id": "p1", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "SCAFFOLDED"}, root)
        text = ledger.read_text()
        self.assertIn("preserved verbatim marker XYZZY", text)
        self.assertIn('drift_canary: "ALDEBARAN-7"', text)
        self.assertIn('contract_map_hash: "abc123"', text)
        self.assertIn("p1", text)  # consumed_request_ids populated

    def test_invalid_claim_blocks(self) -> None:
        # A request carrying a claim_uuid that has no claim file -> invalid_claim.
        root = _mk_root()
        _write_ledger(root, ["| WP-1 | alpha | PLANNED | 0 | — |"])
        r = claims.apply_request_idempotent(
            {"request_id": "c1", "wp": "WP-1", "component_id": "alpha",
             "to_stage": "SCAFFOLDED",
             "claim_uuid": "00000000-0000-0000-0000-000000000000"}, root)
        self.assertEqual(r["outcome"], "invalid_claim")


# ---------------------------------------------------------------------------
# B5 — crash-recovery (validate -> write -> consume; replay idempotent)
# ---------------------------------------------------------------------------

class TestB5CrashRecovery(unittest.TestCase):
    def test_verified_written_then_crash_before_consume(self) -> None:
        root = _mk_root()
        ledger = _write_ledger(root, ["| WP-1 | gamma | INTEGRATED | 0 | — |"])
        bh = _write_green_bundle(root, "gamma")  # S048: GREEN bundle required

        # Open the verification request (the thing stranded on a crash).
        vr = claims.open_verification_request(
            root, component_id="gamma", attempt_id="1",
            prior_state_version="sv", bundle_hash=bh, plan_hash="",
            inventory_hash="ih", runner_version="rv", rubric_version="1.0.0")
        rid = vr["request_id"]
        self.assertEqual(vr["status"], "open")

        _write_archive(root, bh, component_id="gamma",
                       verification_request_id=rid, prior_state_version="sv",
                       generation=0)

        req = {"request_id": "rv-1", "wp": "WP-1", "component_id": "gamma",
               "to_stage": "VERIFIED", "bundle_hash": bh,
               "verification_request_id": rid, "prior_state_version": "sv",
               "generation": 0, "evidence": "pass"}

        # 1. Engine writes the VERIFIED event FIRST.
        r1 = claims.apply_request_idempotent(req, root)
        self.assertEqual(r1["outcome"], "applied")
        # ... simulate CRASH here: consume_verdict is NOT called; request open.
        req_path = (root / ".ledger" / "requests" / "verification"
                    / f"{rid}.request.yaml")
        self.assertEqual(yaml.safe_load(req_path.read_text())["status"], "open")

        # 2. REPLAY after restart: the SAME request_id is idempotent.
        r2 = claims.apply_request_idempotent(req, root)
        self.assertEqual(r2["outcome"], "duplicate_ignored")

        # 3. The LEDGER is idempotently correct: exactly ONE VERIFIED event.
        verified_events = [r for r in _event_rows(ledger) if "VERIFIED" in r]
        self.assertEqual(len(verified_events), 1)
        self.assertEqual(claims.read_ledger(ledger).row("WP-1").stage, "VERIFIED")

        # 4. Recovery sweeps the stranded open request to ABANDONED (terminal),
        #    NOT 'consumed'.
        old = os.environ.get("ARBITER_FRESHNESS_WINDOW_S")
        os.environ["ARBITER_FRESHNESS_WINDOW_S"] = "0"
        try:
            swept, _ = claims.recover_verification_requests(root)
        finally:
            if old is None:
                os.environ.pop("ARBITER_FRESHNESS_WINDOW_S", None)
            else:
                os.environ["ARBITER_FRESHNESS_WINDOW_S"] = old
        self.assertGreaterEqual(swept, 1)
        final = yaml.safe_load(req_path.read_text())
        self.assertEqual(final["status"], "abandoned")
        self.assertNotEqual(final["status"], "consumed")

        # 5. A fresh verification request can open afterward.
        vr_fresh = claims.open_verification_request(
            root, component_id="gamma", attempt_id="2",
            prior_state_version="sv", bundle_hash=bh, plan_hash="",
            inventory_hash="ih", runner_version="rv", rubric_version="1.0.0")
        self.assertEqual(vr_fresh["status"], "open")
        self.assertNotEqual(vr_fresh["request_id"], rid)


if __name__ == "__main__":
    unittest.main()
