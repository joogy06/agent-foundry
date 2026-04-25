#!/usr/bin/env python3
"""test_visual_arbiter.py — TS-VAR-01..05 per contract-map `visual-arbiter`.

Tests the pure-Python visual-arbiter binary (ecosystem-keystone §2.6, §2.9).
Fixtures are tiny HTML "built products" + paired skeleton.yaml bundles.

Runs require a chrome binary at /bin/google-chrome (or VISUAL_ARBITER_CHROME_PATH);
tests that require chrome are skipped when absent.

Test coverage (TS-VAR-01..05 from contract-map):
    TS-VAR-01  happy path: built product matches skeleton → verdict=pass
    TS-VAR-02  missing element: ambient_nudge absent → verdict=reject (missing_from_dom)
    TS-VAR-03  hardcoded color: #ffcc33 in inline style → verdict=reject (token_mismatch)
    TS-VAR-04  dead handler: button in DOM, no listener → verdict=reject (dead_handler)
    TS-VAR-05  bbox tolerance: 2px drift passes (tolerance=2); 3px drift fails

Extra coverage:
    TS-VAR-06  tuple echo discipline: all 8 fields echoed verbatim
    TS-VAR-07  help and argv validation (pure-Python, no chrome)
    TS-VAR-08  tolerance formula: min(must_satisfy.tolerance_px, spacing.unit_px/2)

Run:
    pytest ~/.claude/skills/visual-arbiter/tests/ -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# Locate the binary under test
HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
META_DIR = SKILL_DIR.parent / "_meta"
BINARY = META_DIR / "visual_arbiter_spawn.py"
MEASURE = META_DIR / "visual_arbiter_measure.mjs"

# Import the binary as a module for unit-level testing of pure-Python pieces
# (tolerance compute, drift compute, token detection).
if str(META_DIR) not in sys.path:
    sys.path.insert(0, str(META_DIR))

# Skip chrome-required tests if binary is missing.
CHROME_PATH = Path(os.environ.get("VISUAL_ARBITER_CHROME_PATH", "/bin/google-chrome"))
NEEDS_CHROME = pytest.mark.skipif(
    not CHROME_PATH.exists(),
    reason=f"google-chrome not available at {CHROME_PATH} (set VISUAL_ARBITER_CHROME_PATH)",
)


# ---------------------------------------------------------------------------
# Fixture helpers: tiny HTML + paired skeleton
# ---------------------------------------------------------------------------

SKELETON_INDEX_YAML = """\
schema: design-skeleton-index.v1
index_id: "test-index-uuid"
index_hash: "0000000000000000000000000000000000000000000000000000000000000000"
design_doc_hash: "1111111111111111111111111111111111111111111111111111111111111111"
skeleton_version: "1.0"
parent_version: null
created_at: "2026-04-23T12:00:00Z"
created_by: "test"
forge_session_id: "test-session"
breakpoints:
  desktop: {width: 1280, height: 900, device_pixel_ratio: 1}
tokens:
  color:
    ink: "#0a0a0a"
    accent.sun: "#ffd23f"
  spacing:
    unit_px: 4
    scale: [0, 4, 8, 12, 16]
components: {}
screens:
  - screen_id: "main"
    screen_uuid: "test-screen-uuid"
    file: "main.yaml"
    entry: true
    navigation_from: []
must_satisfy:
  tolerance_px: 4
  all_interactions_wired: true
  tokens_match_by_reference_only: true
  required_breakpoints: [desktop]
"""


def _screen_yaml(elements_block: str) -> str:
    return f"""\
schema: design-skeleton.v1
screen_id: "main"
screen_uuid: "test-screen-uuid"
parent_index: {{path: "index.yaml", hash: "0000000000000000000000000000000000000000000000000000000000000000"}}
skeleton_version: "1.0"
layout:
  desktop: {{root: {{grid_template_columns: "1fr", gap_token: "spacing.16"}}}}
elements:
{elements_block}
"""


def _write_skeleton(tmpdir: Path, elements_block: str) -> Path:
    (tmpdir / "index.yaml").write_text(SKELETON_INDEX_YAML)
    (tmpdir / "main.yaml").write_text(_screen_yaml(elements_block))
    return tmpdir / "index.yaml"


def _write_html(tmpdir: Path, body: str, *, extra_css: str = "", inline_style_nudge: str = "") -> Path:
    html = f"""<!doctype html>
<html><head>
<style>
  :root {{
    --color-ink: #0a0a0a;
    --accent-sun: #ffd23f;
  }}
  body {{ margin: 0; padding: 0; background: #f5f1e8; font-family: sans-serif; }}
  header.masthead {{ width: 1280px; height: 120px; background-color: var(--color-ink); color: #fff; box-sizing: border-box; }}
  #ambient-nudge {{
    position: absolute; left: 1100px; top: 20px; width: 160px; height: 60px;
    background-color: var(--accent-sun); border: 1px solid var(--color-ink);
  }}
  #action-btn {{
    position: absolute; left: 100px; top: 200px; width: 120px; height: 40px;
    background-color: var(--accent-sun);
  }}
  {extra_css}
</style>
</head>
<body>
{body}
<script>
  // Optional handler wiring; each test overrides this string.
</script>
</body></html>
"""
    p = tmpdir / "index.html"
    p.write_text(html)
    return p


# ---------------------------------------------------------------------------
# Stub argv tuple (hex formats required by argv validation)
# ---------------------------------------------------------------------------

HEX32 = "a" * 32
HEX64 = "b" * 64
HEX64B = "c" * 64
HEX64C = "d" * 64


def _run_arbiter(
    skeleton_path: Path,
    product_url: str,
    *,
    skeleton_hash: str = HEX64,
    request_id: str = HEX32,
    attempt_id: str = "attempt-1",
    prior_state_version: str = "v0",
    product_hash: str = HEX64B,
    inventory_hash: str = HEX64C,
    runner_version: str = "runner-1.0",
    rubric_version: str = "v1.0.0",
    timeout_s: int = 120,
) -> Dict[str, Any]:
    """Invoke the arbiter binary and return parsed stdout."""
    env = os.environ.copy()
    env.setdefault("VISUAL_ARBITER_TIMEOUT_S", str(timeout_s))
    cmd = [
        sys.executable, str(BINARY),
        str(skeleton_path), skeleton_hash, request_id, attempt_id,
        prior_state_version, product_url, product_hash,
        inventory_hash, runner_version, rubric_version,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout_s + 30)
    try:
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        out = {"_parse_error": True, "_stdout": proc.stdout, "_stderr": proc.stderr}
    out["_returncode"] = proc.returncode
    out["_stderr"] = proc.stderr
    return out


# ---------------------------------------------------------------------------
# Pure-Python unit tests (no chrome required)
# ---------------------------------------------------------------------------

def test_help_flag_works_and_returns_zero():
    """TS-VAR-07a: --help prints usage and exits 0."""
    proc = subprocess.run(
        [sys.executable, str(BINARY), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, f"help exit {proc.returncode}: {proc.stderr}"
    assert "visual_arbiter_spawn.py" in proc.stdout
    assert "10 positional args" in proc.stdout or "positional" in proc.stdout.lower()


def test_argv_validation_rejects_bad_hash():
    """TS-VAR-07b: bad skeleton_hash → exit 3 with AUDIT_UNAVAILABLE."""
    proc = subprocess.run(
        [sys.executable, str(BINARY)] + ["x"] * 10,
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 3, f"expected 3, got {proc.returncode}"
    out = json.loads(proc.stdout)
    assert out["verdict"] == "AUDIT_UNAVAILABLE"


def test_argv_wrong_count_env_error():
    """TS-VAR-07c: wrong argv count → exit 3."""
    proc = subprocess.run(
        [sys.executable, str(BINARY), "only-one-arg"],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 3
    out = json.loads(proc.stdout)
    assert out["verdict"] == "AUDIT_UNAVAILABLE"
    assert "ENV_ERROR" in out.get("reason", "")


def test_tolerance_formula_minimum():
    """TS-VAR-08: tolerance = min(must_satisfy.tolerance_px, spacing.unit_px / 2).

    Skeleton with tolerance_px=4 and unit_px=2 → tolerance=1 (unit/2 wins).
    Skeleton with tolerance_px=2 and unit_px=8 → tolerance=2 (declared wins).
    """
    import visual_arbiter_spawn as va

    sk_a = {
        "must_satisfy": {"tolerance_px": 4},
        "tokens": {"spacing": {"unit_px": 2}},
    }
    assert va.compute_tolerance_px(sk_a) == 1, "min(4, 2//2=1) = 1"

    sk_b = {
        "must_satisfy": {"tolerance_px": 2},
        "tokens": {"spacing": {"unit_px": 8}},
    }
    assert va.compute_tolerance_px(sk_b) == 2, "min(2, 8//2=4) = 2"

    # No declared tolerance → fall back to unit/2
    sk_c = {
        "must_satisfy": {},
        "tokens": {"spacing": {"unit_px": 10}},
    }
    assert va.compute_tolerance_px(sk_c) == 5


def test_bbox_drift_computation():
    """Unit: drift = measured - declared per-dim."""
    import visual_arbiter_spawn as va
    declared = {"x": 100, "y": 200, "w": 50, "h": 30}
    measured = {"x": 102, "y": 198, "w": 51, "h": 30}
    drift = va._compute_bbox_drift(declared, measured)
    assert drift == {"x": 2, "y": -2, "w": 1, "h": 0}

    assert va._bbox_within_tolerance(drift, 2) is True
    assert va._bbox_within_tolerance(drift, 1) is False  # y=-2 exceeds


def test_hardcoded_color_detection():
    """Unit: hex/rgb in inline style triggers hardcoded detection."""
    import visual_arbiter_spawn as va
    computed_clean = {"__inline_style__": "width: 100px;", "__outer_html__": ""}
    assert va._detect_hardcoded_color(computed_clean) is None

    computed_hex = {"__inline_style__": "background-color: #ffcc33;", "__outer_html__": ""}
    assert va._detect_hardcoded_color(computed_hex) == "#ffcc33"

    computed_rgb = {"__inline_style__": "color: rgb(255, 128, 0);", "__outer_html__": ""}
    assert va._detect_hardcoded_color(computed_rgb) == "rgb(255, 128, 0)"


def test_token_var_detection():
    """Unit: computed style with var(--token-name) passes; without fails."""
    import visual_arbiter_spawn as va
    ok = {"__inline_style__": "", "__outer_html__": '<div style="color: var(--accent-sun);">x</div>'}
    assert va._computed_uses_token(ok, "accent.sun") is True

    bad = {"__inline_style__": "", "__outer_html__": '<div>x</div>'}
    assert va._computed_uses_token(bad, "accent.sun") is False


# ---------------------------------------------------------------------------
# Chrome-required integration tests (TS-VAR-01..05)
# ---------------------------------------------------------------------------

@NEEDS_CHROME
def test_ts_var_01_happy_path(tmp_path):
    """TS-VAR-01: built product matches skeleton exactly → verdict=pass."""
    # Skeleton: one masthead element at desktop
    elements_block = """\
  - id: "masthead"
    kind: structural
    selector: "header.masthead"
    bbox:
      desktop: {x: 0, y: 0, w: 1280, h: 120}
    tokens_used: {color: "$color.ink"}
    visibility: {default: visible}
    interactions: []
"""
    skeleton = _write_skeleton(tmp_path, elements_block)
    html = _write_html(
        tmp_path,
        body='<header class="masthead"></header>',
    )
    result = _run_arbiter(skeleton, html.as_uri())

    assert result.get("_returncode") == 0, f"stderr: {result.get('_stderr')}"
    assert result["schema"] == "visual-verdict.v1"
    assert result["verdict"] == "pass", f"element_verdicts={result.get('element_verdicts')}"
    # 8-field tuple echo
    assert result["request_id"] == HEX32
    assert result["skeleton_hash"] == HEX64
    assert result["product_hash"] == HEX64B
    assert result["inventory_hash"] == HEX64C
    assert result["rubric_version"] == "v1.0.0"
    # Element verified
    assert result["coverage"]["elements_total"] == 1
    assert result["coverage"]["elements_verified"] == 1


@NEEDS_CHROME
def test_ts_var_02_missing_element(tmp_path):
    """TS-VAR-02: built product omits ambient_nudge → verdict=reject (missing_from_dom)."""
    elements_block = """\
  - id: "ambient_nudge"
    kind: element
    selector: "#ambient-nudge"
    bbox:
      desktop: {x: 1100, y: 20, w: 160, h: 60}
    tokens_used: {color: "$color.accent.sun"}
    visibility: {default: visible}
    interactions: []
"""
    skeleton = _write_skeleton(tmp_path, elements_block)
    # HTML omits #ambient-nudge entirely
    html = _write_html(
        tmp_path,
        body='<header class="masthead"></header>',
    )
    result = _run_arbiter(skeleton, html.as_uri())

    assert result.get("_returncode") == 0, f"stderr: {result.get('_stderr')}"
    assert result["verdict"] == "reject"
    # Find ambient_nudge element_verdict with missing_from_dom
    nudge = next(
        (ev for ev in result["element_verdicts"] if ev["element_id"] == "ambient_nudge"),
        None,
    )
    assert nudge is not None, f"ambient_nudge not in element_verdicts: {result['element_verdicts']}"
    assert nudge["status"] == "fail"
    assert nudge.get("missing_from_dom") is True
    assert "ambient_nudge@desktop" in result["coverage"]["uncovered"]


@NEEDS_CHROME
def test_ts_var_03_hardcoded_color(tmp_path):
    """TS-VAR-03: CSS has #ffcc33 hardcoded instead of var(--accent-sun) → token_mismatch reject."""
    elements_block = """\
  - id: "ambient_nudge"
    kind: element
    selector: "#ambient-nudge"
    bbox:
      desktop: {x: 1100, y: 20, w: 160, h: 60}
    tokens_used: {color: "$color.accent.sun"}
    visibility: {default: visible}
    interactions: []
"""
    skeleton = _write_skeleton(tmp_path, elements_block)
    # HTML renders #ambient-nudge but with a hardcoded INLINE hex (overrides the CSS var)
    body = (
        '<header class="masthead"></header>'
        '<div id="ambient-nudge" '
        'style="position:absolute;left:1100px;top:20px;width:160px;height:60px;'
        'background-color:#ffcc33;"></div>'
    )
    html = _write_html(tmp_path, body=body)
    result = _run_arbiter(skeleton, html.as_uri())

    assert result.get("_returncode") == 0, f"stderr: {result.get('_stderr')}"
    assert result["verdict"] == "reject"
    nudge = next(
        (ev for ev in result["element_verdicts"] if ev["element_id"] == "ambient_nudge"),
        None,
    )
    assert nudge is not None
    assert nudge["status"] == "fail"
    assert nudge.get("tokens_ok") is False
    assert "token_mismatch" in nudge, f"expected token_mismatch key; got {nudge}"
    tm_first = nudge["token_mismatch"][0]
    assert tm_first["computed"] == "#ffcc33"


@NEEDS_CHROME
def test_ts_var_04_dead_click_handler(tmp_path):
    """TS-VAR-04: button in DOM but no event wired → verdict=reject (dead_handler)."""
    elements_block = """\
  - id: "action_btn"
    kind: element
    selector: "#action-btn"
    bbox:
      desktop: {x: 100, y: 200, w: 120, h: 40}
    tokens_used: {}
    visibility: {default: visible}
    interactions:
      - event: click
        binds_to: "capability://action_controller.do_thing"
"""
    skeleton = _write_skeleton(tmp_path, elements_block)
    # Button present, but NO click handler wired (no onclick attr, no data-arbiter-wired)
    body = (
        '<header class="masthead"></header>'
        '<button id="action-btn">Do Thing</button>'
    )
    html = _write_html(tmp_path, body=body)
    result = _run_arbiter(skeleton, html.as_uri())

    assert result.get("_returncode") == 0, f"stderr: {result.get('_stderr')}"
    assert result["verdict"] == "reject"
    btn = next(
        (ev for ev in result["element_verdicts"] if ev["element_id"] == "action_btn"),
        None,
    )
    assert btn is not None, f"action_btn missing: {result['element_verdicts']}"
    assert btn["status"] == "fail"
    # dead_handler key present when interaction wire failed
    assert "dead_handler" in btn, f"expected dead_handler; got {btn}"
    assert any(d.get("event") == "click" for d in btn["dead_handler"])


@NEEDS_CHROME
def test_ts_var_05a_bbox_within_tolerance_passes(tmp_path):
    """TS-VAR-05a: 2px drift at desktop with tolerance=min(4,2)=2 → pass."""
    # Skeleton spacing.unit_px=4 → unit/2=2; must_satisfy.tolerance_px=4 → tolerance=min(4,2)=2
    elements_block = """\
  - id: "masthead"
    kind: structural
    selector: "header.masthead"
    bbox:
      desktop: {x: 0, y: 0, w: 1280, h: 120}
    tokens_used: {}
    visibility: {default: visible}
    interactions: []
"""
    skeleton = _write_skeleton(tmp_path, elements_block)
    # Render masthead 2px wider than declared: w=1282 (still within tolerance=2)
    # Using inline style to shift by 2px horizontally-sized element
    body = '<header class="masthead" style="width:1282px;height:120px;"></header>'
    html = _write_html(tmp_path, body=body)
    result = _run_arbiter(skeleton, html.as_uri())

    assert result.get("_returncode") == 0, f"stderr: {result.get('_stderr')}"
    # 2px drift with tolerance=2 should pass (abs<=tolerance)
    masthead = next(
        (ev for ev in result["element_verdicts"] if ev["element_id"] == "masthead"),
        None,
    )
    assert masthead is not None
    # drift.w should be 2, which is == tolerance (inclusive pass)
    assert abs(masthead["bbox_drift_px"]["w"]) <= 2
    assert masthead["status"] == "pass", f"expected pass; got {masthead}"


@NEEDS_CHROME
def test_ts_var_05b_bbox_exceeds_tolerance_fails(tmp_path):
    """TS-VAR-05b: 8px drift with tolerance=2 → fail."""
    elements_block = """\
  - id: "masthead"
    kind: structural
    selector: "header.masthead"
    bbox:
      desktop: {x: 0, y: 0, w: 1280, h: 120}
    tokens_used: {}
    visibility: {default: visible}
    interactions: []
"""
    skeleton = _write_skeleton(tmp_path, elements_block)
    # Render 8px wider — well outside tolerance=2
    body = '<header class="masthead" style="width:1288px;height:120px;"></header>'
    html = _write_html(tmp_path, body=body)
    result = _run_arbiter(skeleton, html.as_uri())

    assert result.get("_returncode") == 0, f"stderr: {result.get('_stderr')}"
    masthead = next(
        (ev for ev in result["element_verdicts"] if ev["element_id"] == "masthead"),
        None,
    )
    assert masthead is not None
    assert abs(masthead["bbox_drift_px"]["w"]) > 2
    assert masthead["status"] == "fail"
    assert result["verdict"] == "reject"


@NEEDS_CHROME
def test_ts_var_06_tuple_echo_verbatim(tmp_path):
    """TS-VAR-06: all 8 tuple fields echoed verbatim in output JSON."""
    elements_block = """\
  - id: "masthead"
    kind: structural
    selector: "header.masthead"
    bbox:
      desktop: {x: 0, y: 0, w: 1280, h: 120}
    tokens_used: {}
    visibility: {default: visible}
    interactions: []
"""
    skeleton = _write_skeleton(tmp_path, elements_block)
    html = _write_html(tmp_path, body='<header class="masthead"></header>')

    # Custom tuple to ensure echo
    req_id = "ff" * 16  # 32-hex
    attempt = "custom-attempt-id-42"
    pfs = "state-v7"
    skel_h = "ab" * 32  # 64-hex
    prod_h = "cd" * 32
    inv_h = "ef" * 32
    runner = "runner-v2.3.1"
    rubric = "v1.0.0"

    result = _run_arbiter(
        skeleton, html.as_uri(),
        skeleton_hash=skel_h, request_id=req_id, attempt_id=attempt,
        prior_state_version=pfs, product_hash=prod_h, inventory_hash=inv_h,
        runner_version=runner, rubric_version=rubric,
    )

    assert result.get("_returncode") == 0, f"stderr: {result.get('_stderr')}"
    # Every tuple field echoed verbatim
    assert result["request_id"] == req_id
    assert result["attempt_id"] == attempt
    assert result["prior_state_version"] == pfs
    assert result["skeleton_hash"] == skel_h
    assert result["product_hash"] == prod_h
    assert result["inventory_hash"] == inv_h
    assert result["runner_version"] == runner
    assert result["rubric_version"] == rubric


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
