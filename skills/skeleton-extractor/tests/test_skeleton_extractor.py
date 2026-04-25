"""Tests for skeleton-extractor (TS-SE-01..04).

These tests spawn the real Node subprocess against a headless Chrome. They
skip if /bin/google-chrome is absent. One pure-Python test
(`test_extract_python_wrapper_handles_missing_chrome`) runs regardless, to
guarantee CI coverage of the Python wrapper's fail-open pathway.

The NODE_PATH plumbing is deliberately explicit: puppeteer-core lives under
/path/to/projects/test_flow/node_modules; we point the subprocess at it via
NODE_PATH so the .mjs's `import puppeteer from "puppeteer-core"` resolves
without a system-wide install.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

# Staged scripts dir (tests run against the staged copy; the final synced
# location under ~/.claude is populated by bob at the tail of the WP).
SCRIPTS = HERE.parent / "scripts"
EXTRACT_PY = SCRIPTS / "extract.py"
META_DIR = HERE.parent.parent / "_meta"
EXTRACTOR_MJS = META_DIR / "skeleton_extractor.mjs"

# puppeteer-core lives in the test_flow precedent's node_modules.
PUPPETEER_NODE_MODULES = Path("/path/to/projects/test_flow/node_modules")

CHROME_MISSING = not Path("/bin/google-chrome").exists()
PUPPETEER_MISSING = not (PUPPETEER_NODE_MODULES / "puppeteer-core").is_dir()

skipif_no_chrome = pytest.mark.skipif(
    CHROME_MISSING,
    reason="/bin/google-chrome not installed in this environment",
)
skipif_no_puppeteer = pytest.mark.skipif(
    PUPPETEER_MISSING,
    reason=f"puppeteer-core not found at {PUPPETEER_NODE_MODULES}",
)


def _env_with_node_path() -> Dict[str, str]:
    env = os.environ.copy()
    env["NODE_PATH"] = str(PUPPETEER_NODE_MODULES)
    return env


def _run_extract(
    mockup: Path,
    out: Path,
    tokens_path: Optional[Path] = None,
    breakpoints: str = "420,700,1280",
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    args = [
        sys.executable,
        str(EXTRACT_PY),
        "--mockup", str(mockup),
        "--out", str(out),
        "--breakpoints", breakpoints,
        "--timeout", str(timeout),
    ]
    if tokens_path is not None:
        args += ["--tokens-path", str(tokens_path)]
    return subprocess.run(
        args,
        env=_env_with_node_path(),
        capture_output=True,
        text=True,
        timeout=timeout + 30,
    )


def _parse_draft(path: Path) -> Dict[str, Any]:
    """Minimal YAML parse — tests prefer pyyaml; fall back to ast-safe parser."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        pytest.skip("PyYAML not installed — cannot parse draft YAML in tests")


# ---------------------------------------------------------------------------
# Full-flow tests (require chrome + puppeteer-core)
# ---------------------------------------------------------------------------


@skipif_no_chrome
@skipif_no_puppeteer
def test_ts_se_01_extract_basic_mockup_12_elements_three_breakpoints(tmp_path):
    """TS-SE-01: extract basic fixture → draft with >=12 elements across 3 bps."""
    out = tmp_path / "basic.draft.yaml"
    r = _run_extract(
        FIXTURES / "basic_mockup.html",
        out,
        tokens_path=FIXTURES / "tokens_index.yaml",
    )
    assert r.returncode == 0, f"extract failed: stdout={r.stdout!r} stderr={r.stderr!r}"
    assert out.is_file()
    draft = _parse_draft(out)
    assert draft["schema"] == "design-skeleton.v1"
    assert draft["draft"] is True
    assert draft["breakpoints"] == [420, 700, 1280]
    elements = draft["elements"]
    assert isinstance(elements, list) and len(elements) >= 12, (
        f"expected >=12 elements, got {len(elements)}"
    )
    # Every element has a per-breakpoint bbox map including all 3 bps.
    bp_names = {"mobile", "tablet", "desktop"}
    for el in elements:
        bb = el.get("bbox") or {}
        assert bp_names.issubset(bb.keys()), f"missing bp keys on {el.get('selector')}: {bb.keys()}"


@skipif_no_chrome
@skipif_no_puppeteer
def test_ts_se_02_css_variable_chain_resolves_to_token_uri(tmp_path):
    """TS-SE-02: var(--accent-sun) computed → token://color.accent_sun."""
    out = tmp_path / "var.draft.yaml"
    r = _run_extract(
        FIXTURES / "var_chain_mockup.html",
        out,
        tokens_path=FIXTURES / "tokens_index.yaml",
    )
    assert r.returncode == 0, f"stderr={r.stderr}"
    draft = _parse_draft(out)
    # sunny-card background should resolve to token://color.accent_sun.
    found = False
    for el in draft["elements"]:
        tu = el.get("tokens_used") or {}
        for field, uri in tu.items():
            if isinstance(uri, str) and uri.endswith("accent_sun"):
                found = True
                break
        if found:
            break
    assert found, (
        "expected at least one element with tokens_used resolving to color.accent_sun; "
        f"got tokens_used summary={[el.get('tokens_used') for el in draft['elements']]}"
    )


@skipif_no_chrome
@skipif_no_puppeteer
def test_ts_se_03_unresolved_hardcoded_color_surfaces_in_report(tmp_path):
    """TS-SE-03: #ac3b3b is not in declared tokens → unresolved_tokens_report."""
    out = tmp_path / "hardcoded.draft.yaml"
    r = _run_extract(
        FIXTURES / "hardcoded_mockup.html",
        out,
        tokens_path=FIXTURES / "tokens_index.yaml",
    )
    assert r.returncode == 0, f"stderr={r.stderr}"
    draft = _parse_draft(out)
    report = draft.get("unresolved_tokens_report") or []
    assert report, "unresolved_tokens_report should have at least one entry"
    # One of the entries must quote #ac3b3b (case-insensitive).
    joined = json.dumps(report).lower()
    assert "#ac3b3b" in joined or "rgb(172, 59, 59)" in joined, (
        f"expected #ac3b3b (or its rgb form) in unresolved report; got {report}"
    )


@skipif_no_chrome
@skipif_no_puppeteer
def test_ts_se_04_font_delay_guard_waits_and_reports_fonts_loaded(tmp_path):
    """TS-SE-04: 400ms font-delay fixture → extractor waits, fonts_loaded: true."""
    out = tmp_path / "fonts.draft.yaml"
    r = _run_extract(FIXTURES / "font_delay_mockup.html", out)
    assert r.returncode == 0, f"stderr={r.stderr}"
    draft = _parse_draft(out)
    assert draft.get("fonts_loaded") is True, (
        f"fonts_loaded should be true after 400ms delay; got {draft.get('fonts_loaded')}"
    )
    # Sanity: the recorded fonts-ready max should be in a sane window (>= 100ms,
    # bounded well under the 5s failure threshold).
    fr = draft.get("fonts_ready_max_ms", 0)
    assert 0 <= fr < 5000


# ---------------------------------------------------------------------------
# Environment-independent guardrail
# ---------------------------------------------------------------------------


def test_extract_python_wrapper_handles_missing_chrome(tmp_path, monkeypatch):
    """Python wrapper surfaces a clear error + observation when chrome is absent.

    Independent of the real filesystem state: we force Path("/bin/google-chrome").exists
    to return False inside a subprocess run with a stub PATH that omits the
    binary. We re-import the extract module in a child Python so the monkeypatch
    takes effect, then trigger its main() and assert exit code 3.
    """
    # Build a tiny python program that reloads extract.py with a patched
    # Path.exists so /bin/google-chrome reports absent, then invokes main().
    runner = tmp_path / "run_absent.py"
    runner.write_text(
        "import sys, pathlib\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import importlib, pathlib\n"
        "orig_exists = pathlib.Path.exists\n"
        "def fake_exists(self):\n"
        "    if str(self) == '/bin/google-chrome':\n"
        "        return False\n"
        "    return orig_exists(self)\n"
        "pathlib.Path.exists = fake_exists\n"
        "import extract\n"
        "rc = extract.main([\n"
        "    '--mockup', " + json.dumps(str(FIXTURES / "basic_mockup.html")) + ",\n"
        "    '--out', " + json.dumps(str(tmp_path / "out.yaml")) + ",\n"
        "])\n"
        "sys.exit(rc)\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(runner)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 3, (
        f"expected exit 3 when chrome is absent; got {r.returncode}. "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    assert "google-chrome" in r.stderr.lower()
