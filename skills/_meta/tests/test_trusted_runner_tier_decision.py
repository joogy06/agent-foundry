#!/usr/bin/env python3
"""Tests for trusted_runner R-B1 tier-decision stamping (S048 / #116).

  - inventory_tier_and_hash reads tier + hashes the bytes
  - stamp_tier_decision marks sanctioned_tier_skip iff skipped AND required>host
  - a skip whose tier IS met gets NO sanction (should-have-run)
  - a non-skip outcome never gets sanctioned
  - run_trusted_test_suite without required_tiers keeps the exact prior shape
    (no tier_decision key, no sanction) — back-compat / byte-shape preserved
  - the stamp is applied BEFORE bundle_hash (hash-bound into evidence)
"""
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import trusted_runner as tr  # type: ignore


def _write_inventory(tmp_path: Path, tier):
    p = tmp_path / "inventory.json"
    p.write_text(json.dumps({"tier": tier, "tools": {}}), encoding="utf-8")
    return p


def test_inventory_tier_and_hash(tmp_path):
    p = _write_inventory(tmp_path, 1)
    tier, h = tr.inventory_tier_and_hash(p)
    assert tier == 1
    assert isinstance(h, str) and len(h) == 64


def test_inventory_missing_returns_none(tmp_path):
    tier, h = tr.inventory_tier_and_hash(tmp_path / "nope.json")
    assert tier is None and h is None


def test_stamp_sanctions_tier_gated_skip(tmp_path):
    inv = _write_inventory(tmp_path, 1)  # host tier 1
    bundle = {
        "results": [{
            "tests": [
                {"nodeid": "t::needs_tier2", "outcome": "skipped"},
                {"nodeid": "t::ran", "outcome": "passed"},
            ],
        }],
    }
    tr.stamp_tier_decision(
        bundle,
        {"t::needs_tier2": 2, "t::ran": 0},
        inventory_path=inv,
    )
    assert bundle["tier_decision"] == {"inventory_tier": 1, "inventory_hash": tr.inventory_tier_and_hash(inv)[1]}
    skipped = bundle["results"][0]["tests"][0]
    assert skipped["required_tier"] == 2
    assert skipped["sanctioned_tier_skip"] is True
    ran = bundle["results"][0]["tests"][1]
    # a passing test is never sanctioned
    assert "sanctioned_tier_skip" not in ran


def test_skip_whose_tier_is_met_is_not_sanctioned(tmp_path):
    inv = _write_inventory(tmp_path, 2)  # host tier 2 — meets required_tier 1
    bundle = {"results": [{"tests": [
        {"nodeid": "t::a", "outcome": "skipped"},
    ]}]}
    tr.stamp_tier_decision(bundle, {"t::a": 1}, inventory_path=inv)
    t = bundle["results"][0]["tests"][0]
    assert t.get("required_tier") == 1
    assert "sanctioned_tier_skip" not in t  # should-have-run -> no sanction


def test_skip_without_tier_mapping_is_not_sanctioned(tmp_path):
    inv = _write_inventory(tmp_path, 1)
    bundle = {"results": [{"tests": [
        {"nodeid": "t::a", "outcome": "skipped"},
    ]}]}
    tr.stamp_tier_decision(bundle, {}, inventory_path=inv)
    t = bundle["results"][0]["tests"][0]
    assert "sanctioned_tier_skip" not in t


def test_unknown_inventory_tier_never_sanctions(tmp_path):
    # No inventory file -> tier None -> no sanction (fail-safe, never false-GREEN)
    bundle = {"results": [{"tests": [
        {"nodeid": "t::a", "outcome": "skipped"},
    ]}]}
    tr.stamp_tier_decision(bundle, {"t::a": 2}, inventory_path=tmp_path / "nope.json")
    t = bundle["results"][0]["tests"][0]
    assert t.get("required_tier") == 2
    assert "sanctioned_tier_skip" not in t
    assert bundle["tier_decision"]["inventory_tier"] is None


def test_run_suite_without_tiers_has_no_tier_decision(tmp_path):
    # Back-compat: default call (no required_tiers) -> NO tier_decision key.
    test_file = tmp_path / "test_pass.py"
    test_file.write_text("def test_ok():\n    assert True\n")
    bundle = tr.run_trusted_test_suite("comp", [test_file], runner="pytest")
    assert "tier_decision" not in bundle
    # hash still present + recomputes
    assert tr.bundle_hash_hex(bundle) == bundle["bundle_hash"]


def test_run_suite_with_tiers_stamps_before_hash(tmp_path):
    test_file = tmp_path / "test_pass.py"
    test_file.write_text("def test_ok():\n    assert True\n")
    inv = _write_inventory(tmp_path, 1)
    bundle = tr.run_trusted_test_suite(
        "comp", [test_file], runner="pytest",
        required_tiers={}, inventory_path=inv,
    )
    assert "tier_decision" in bundle
    assert bundle["tier_decision"]["inventory_tier"] == 1
    # the tier_decision is INSIDE the hashed bytes (hash-bound).
    assert tr.bundle_hash_hex(bundle) == bundle["bundle_hash"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
