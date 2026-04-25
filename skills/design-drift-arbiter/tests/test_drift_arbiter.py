"""Tests for design-drift-arbiter (WP-10, S028 Phase 3).

Covers contract-map TS-DA-01..04 plus bonus ΔE2000 sanity test TS-DA-05.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
META_DIR = SCRIPT_DIR.parent.parent / "_meta"
SPAWN = META_DIR / "design_drift_arbiter_spawn.py"

# Make the spawn script importable for direct unit tests (not just CLI)
sys.path.insert(0, str(META_DIR))
import design_drift_arbiter_spawn as drift  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


TOKENS_SAMPLE = {
    "tokens": {
        "color": {
            "ink": "#0a0a0a",
            "paper": "#f5f1e8",
            "accent": {
                "sun": "#ffd23f",
                "sunset": "#ffd150",   # very close to sun (same family)
                "rain": "#4ea8de",
            },
            "colors": {
                "primary": "#ff0000",  # distinct namespace
            },
        },
        "typography": {
            "display": {"family": "Bungee", "weight": 400, "fallback": "sans-serif"},
            "body":    {"family": "IBM Plex Mono", "weight": 400, "fallback": "monospace"},
        },
        "spacing": {
            "unit_px": 4,
            "scale": [0, 4, 8, 12, 16, 24, 32, 48, 64],
        },
    }
}

BASE_TUPLE = {
    "request_id": "a" * 32,
    "attempt_id": "attempt-1",
    "prior_state_version": "v1",
    "skeleton_hash": "b" * 64,
    "impl_hash": "c" * 64,
    "inventory_hash": "d" * 64,
    "runner_version": "runner@1.0.0",
    "rubric_version": "drift-arbiter-v1.0.0",
}


def _write_inputs(tmp_path: Path, verdict: dict, profile: str = "strict",
                  tokens: dict = None) -> tuple:
    """Write verdict + tokens + config to tmp_path, return paths."""
    if tokens is None:
        tokens = TOKENS_SAMPLE
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(json.dumps(verdict))
    tokens_path = tmp_path / "index.yaml"
    tokens_path.write_text(yaml.safe_dump(tokens))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "design_drift_arbiter": {
            "active_profile": profile,
            "profiles": {
                "strict":  {"bbox_tolerance_px": 2, "token_swap_allowed": False},
                "lenient": {
                    "bbox_tolerance_px": 8,
                    "token_swap_allowed": True,
                    "token_swap_same_family_only": True,
                },
            }
        }
    }))
    return verdict_path, tokens_path, config_path


def _run_cli(verdict_path, tokens_path, config_path, profile=None,
             project_root=None):
    cmd = [sys.executable, str(SPAWN),
           "--verdict-path", str(verdict_path),
           "--tokens-path", str(tokens_path),
           "--config-path", str(config_path)]
    if profile:
        cmd.extend(["--profile", profile])
    if project_root:
        cmd.extend(["--project-root", str(project_root)])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result


# ---------------------------------------------------------------------------
# TS-DA-01: 1px bbox drift + color swap within accent.* family -> auto_approved
# ---------------------------------------------------------------------------


def test_TS_DA_01_micro_drift_lenient_auto_approves(tmp_path):
    """1px bbox drift + color swap within accent.* family on lenient profile."""
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "step_card_1",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "bbox_drift",
                 "bbox_drift_px": {"x": 1, "y": 0, "w": 1, "h": 0}},
                {"kind": "token_mismatch",
                 "field": "color",
                 "expected": "accent.sun",      # #ffd23f
                 "computed": "accent.sunset"},  # #ffd150 — ΔE small, same ns
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="lenient")
    r = _run_cli(v, t, c)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "auto_approved", out
    assert out["profile_used"] == "lenient"
    # Tuple echo verbatim
    for k, want in BASE_TUPLE.items():
        assert out["tuple_echo"][k] == want, (k, out["tuple_echo"][k], want)
    # Both failures classified micro
    cls = out["classification_per_element"][0]
    assert cls["classification"] == "micro-drift"
    joined = " | ".join(cls["reasons"])
    assert "bbox_drift worst=1px" in joined
    assert "same-family" in joined


# ---------------------------------------------------------------------------
# TS-DA-02: 3px bbox drift at strict profile (tolerance=2) -> escalate
# ---------------------------------------------------------------------------


def test_TS_DA_02_strict_rejects_3px_bbox(tmp_path):
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "step_card_2",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "bbox_drift",
                 "bbox_drift_px": {"x": 3, "y": 0, "w": 0, "h": 0}},
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="strict")
    r = _run_cli(v, t, c)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "escalate_to_user", out
    assert out["profile_used"] == "strict"
    cls = out["classification_per_element"][0]
    assert cls["classification"] == "material"
    assert any("3" in reason and "tolerance 2" in reason for reason in cls["reasons"])


# ---------------------------------------------------------------------------
# TS-DA-03: color swap across namespaces -> escalate (not same family)
# ---------------------------------------------------------------------------


def test_TS_DA_03_cross_namespace_color_escalates(tmp_path):
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "cta_button",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "token_mismatch",
                 "field": "color",
                 "expected": "accent.sun",         # in accent.* namespace
                 "computed": "colors.primary"},    # in colors.* namespace
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="lenient")
    r = _run_cli(v, t, c)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "escalate_to_user", out
    cls = out["classification_per_element"][0]
    assert cls["classification"] == "material"
    assert any("namespace mismatch" in r.lower() for r in cls["reasons"])


# ---------------------------------------------------------------------------
# TS-DA-04: missing element in verdict -> escalate (material omission)
# ---------------------------------------------------------------------------


def test_TS_DA_04_missing_from_dom_escalates(tmp_path):
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "ambient_nudge",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "missing_from_dom"},
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="lenient")
    r = _run_cli(v, t, c)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "escalate_to_user", out
    cls = out["classification_per_element"][0]
    assert cls["classification"] == "material"
    assert any("missing_from_dom" in r for r in cls["reasons"])


# ---------------------------------------------------------------------------
# TS-DA-05 (bonus): ΔE2000 known-value sanity
# ---------------------------------------------------------------------------


def test_TS_DA_05_delta_e2000_known_values():
    """Small ΔE for similar colors, large ΔE for red vs green."""
    # Similar reds: #ff0000 vs #fe0000 — should be small (<1)
    lab_red = drift.hex_to_lab("#ff0000")
    lab_slightly_off_red = drift.hex_to_lab("#fe0000")
    dE_small = drift.delta_e_2000(lab_red, lab_slightly_off_red)
    assert 0 < dE_small < 1.0, f"expected small ΔE, got {dE_small}"

    # Red vs Green — should be huge (>60)
    lab_green = drift.hex_to_lab("#00ff00")
    dE_big = drift.delta_e_2000(lab_red, lab_green)
    assert dE_big > 60, f"expected large ΔE, got {dE_big}"

    # Identity: same color -> ΔE == 0
    dE_same = drift.delta_e_2000(lab_red, lab_red)
    assert dE_same == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Bonus: determinism + tuple echo
# ---------------------------------------------------------------------------


def test_deterministic_same_input_same_output(tmp_path):
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "step_card",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [{"kind": "bbox_drift",
                          "bbox_drift_px": {"x": 1, "y": 1, "w": 0, "h": 0}}],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="strict")
    r1 = _run_cli(v, t, c)
    r2 = _run_cli(v, t, c)
    assert r1.stdout == r2.stdout  # byte-identical


def test_help_exits_zero():
    r = subprocess.run([sys.executable, str(SPAWN), "--help"],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert "Pure-Python micro-drift auto-approver" in r.stdout


def test_strict_blocks_token_swap(tmp_path):
    """Strict profile with token_swap_allowed=false -> token_mismatch material."""
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "e1",
            "breakpoint": "mobile",
            "status": "fail",
            "failures": [
                {"kind": "token_mismatch",
                 "field": "color",
                 "expected": "accent.sun",
                 "computed": "accent.sunset"},
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="strict")
    r = _run_cli(v, t, c)
    out = json.loads(r.stdout)
    assert out["status"] == "escalate_to_user"
    cls = out["classification_per_element"][0]
    assert cls["classification"] == "material"
    assert any("token_swap_allowed=false" in reason for reason in cls["reasons"])


def test_spacing_same_family_adjacent(tmp_path):
    """spacing.8 -> spacing.12 should be same family (adjacent scale index)."""
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "e2",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "token_mismatch",
                 "field": "spacing",
                 "expected": "spacing.8",
                 "computed": "spacing.12"},
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="lenient")
    r = _run_cli(v, t, c)
    out = json.loads(r.stdout)
    assert out["status"] == "auto_approved", out["classification_per_element"]


def test_spacing_jump_too_far_escalates(tmp_path):
    """spacing.8 -> spacing.32 exceeds ±1 scale step."""
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "e3",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "token_mismatch",
                 "field": "spacing",
                 "expected": "spacing.8",
                 "computed": "spacing.32"},
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="lenient")
    r = _run_cli(v, t, c)
    out = json.loads(r.stdout)
    assert out["status"] == "escalate_to_user"


def test_typography_weight_step_ok(tmp_path):
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "h1",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "token_mismatch",
                 "field": "typography.body",
                 "expected": {"family": "Bungee", "weight": 400, "size_px": 32},
                 "computed": {"family": "Bungee", "weight": 500, "size_px": 32}},
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="lenient")
    r = _run_cli(v, t, c)
    out = json.loads(r.stdout)
    assert out["status"] == "auto_approved", out


def test_typography_weight_leap_escalates(tmp_path):
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "h1",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [
                {"kind": "token_mismatch",
                 "field": "typography.body",
                 "expected": {"family": "Bungee", "weight": 400, "size_px": 32},
                 "computed": {"family": "Bungee", "weight": 900, "size_px": 32}},
            ],
        }],
    }
    v, t, c = _write_inputs(tmp_path, verdict, profile="lenient")
    r = _run_cli(v, t, c)
    out = json.loads(r.stdout)
    assert out["status"] == "escalate_to_user"


def test_malformed_profile_falls_back_to_strict(tmp_path):
    """Missing profile -> fall back to strict (fail-open observation)."""
    verdict = {
        "verdict": "reject",
        **BASE_TUPLE,
        "element_verdicts": [{
            "element_id": "x",
            "breakpoint": "desktop",
            "status": "fail",
            "failures": [{"kind": "bbox_drift",
                          "bbox_drift_px": {"x": 1, "y": 1, "w": 0, "h": 0}}],
        }],
    }
    v, t, _ = _write_inputs(tmp_path, verdict)
    # Point at a nonexistent config → falls back to strict
    bad_cfg = tmp_path / "nope.yaml"
    r = _run_cli(v, t, bad_cfg)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    # strict tolerance = 2, 1px drift is micro
    assert out["profile_used"] == "strict"
    assert out["status"] == "auto_approved"
