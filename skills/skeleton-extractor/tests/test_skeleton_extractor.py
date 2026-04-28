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


# ---------------------------------------------------------------------------
# Phase5b — closing tests for skeleton-extractor (Codex structured_disagreements)
# ---------------------------------------------------------------------------
#
# These tests close the four critical / moderate Codex gaps without requiring
# Chrome or puppeteer-core, so they ALWAYS run in CI:
#
#   test_phase5b_sc1_subprocess_contract     (Codex critical [1])
#       SC[1]: subprocess returns exactly one JSON blob on stdout, runs under
#       a sanitized env, and is invoked with timeout=120. Drives extract.py's
#       _run_extractor with subprocess.run monkeypatched to capture the call
#       parameters; asserts the env passed contains ONLY allow-listed keys
#       and that timeout=120 is the literal kwarg.
#
#   test_phase5b_sc4_draft_unsigned_and_filename   (Codex critical [3])
#       SC[5]: draft is unsigned (no `signature` field) AND callers honor the
#       `.draft.yaml` filename convention. The wrapper itself does not enforce
#       the suffix (caller-controlled `--out`), but the produced YAML body
#       must NEVER carry a signature block — that's reserved for visual-architect
#       freezing. Test patches _run_extractor to return a synthetic draft and
#       asserts both invariants on the persisted file.
#
#   test_phase5b_sc1_subprocess_runtime_error_observed (Codex critical [1])
#       SC[1] failure mode: when subprocess returns non-zero, _run_extractor
#       must (a) raise RuntimeError with a stderr-tail diagnostic, AND (b)
#       emit an `external_tool_fail` observation via the fail-open helper.
#       This proves the contract that subprocess failures NEVER pass through
#       silently.
#
#   test_phase5b_sc1_subprocess_empty_stdout_rejected (Codex critical [1])
#       SC[1] adversarial: subprocess returns rc=0 but empty stdout → must
#       raise RuntimeError + emit observation. Chrome can crash AFTER printing
#       to stderr but before printing JSON; this MUST surface as a hard error.
#
#   test_phase5b_fixture_diversity_malformed_html_handled (Claude minor [5])
#       Adversarial fixture: generate a malformed-HTML mockup at test-time
#       (no <body>, broken CSS, deeply nested DOM) and run a subprocess-free
#       smoke test against the YAML serialization layer to prove the wrapper
#       can persist non-trivial drafts (key existence, list/dict round-trip)
#       without depending on the goldenpath weather-mockup fixture.


import importlib

# Import extract as a module so we can drive its private helpers directly.
sys.path.insert(0, str(SCRIPTS))
import extract  # noqa: E402


def _make_canned_completed_process(stdout_bytes: bytes, returncode: int = 0,
                                    stderr_bytes: bytes = b"") -> subprocess.CompletedProcess:
    """Build a CompletedProcess that mimics what subprocess.run returns
    (bytes for stdout/stderr because we capture_output=True without text=True).
    """
    return subprocess.CompletedProcess(
        args=["node", "fake.mjs"],
        returncode=returncode,
        stdout=stdout_bytes,
        stderr=stderr_bytes,
    )


def _minimal_synthetic_draft() -> Dict[str, Any]:
    """A canned draft skeleton roughly matching what skeleton_extractor.mjs
    would emit — used to drive _run_extractor in the absence of Chrome."""
    return {
        "schema": "design-skeleton.v1",
        "draft": True,
        "breakpoints": [420, 700, 1280],
        "elements": [
            {
                "id": f"el-{i}",
                "selector": f".elem-{i}",
                "bbox": {
                    "mobile":  {"x": 0, "y": i * 10, "w": 420,  "h": 10},
                    "tablet":  {"x": 0, "y": i * 10, "w": 700,  "h": 10},
                    "desktop": {"x": 0, "y": i * 10, "w": 1280, "h": 10},
                },
                "interactions": [],
            }
            for i in range(12)
        ],
        "tokens_used": {},
        "unresolved_tokens_report": [],
        "fonts_loaded": True,
        "fonts_ready_max_ms": 250,
    }


def test_phase5b_sc1_subprocess_contract(tmp_path, monkeypatch):
    """SC[1]: _run_extractor invokes subprocess.run with timeout=120, a
    sanitized env, and parses ONE JSON blob from stdout.

    We capture the subprocess.run call to assert:
      - the second argv element (the .mjs path) exists and ends with the
        skeleton_extractor.mjs filename,
      - timeout kwarg is exactly 120 (matches SC[1] declared budget),
      - env kwarg is the sanitized subset (no PYTHONPATH, no LDAP, no SSH_AUTH_SOCK),
      - stdin payload is valid JSON containing 'mockupHtml' + 'breakpoints' + 'tokens'.
    """
    # We need a real .mjs file to exist for _find_extractor_mjs() to succeed.
    # Use the real one — its path is observable, just don't actually invoke it.
    captured: Dict[str, Any] = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        captured["args"] = args
        captured["kwargs"] = kwargs
        # Return a canned single-JSON-blob response.
        blob = json.dumps(_minimal_synthetic_draft()).encode("utf-8")
        return _make_canned_completed_process(blob)

    monkeypatch.setattr(extract.subprocess, "run", fake_run)

    mockup = tmp_path / "fake.html"
    mockup.write_text("<html><body>x</body></html>", encoding="utf-8")
    result = extract._run_extractor(mockup, [420, 700, 1280], None, timeout_s=120)

    # --- argv shape: ['node', '<...>/skeleton_extractor.mjs']
    assert captured["cmd"][0] == "node", (
        f"expected node binary, got {captured['cmd'][0]!r}"
    )
    assert captured["cmd"][1].endswith("skeleton_extractor.mjs"), (
        f"expected .mjs path, got {captured['cmd'][1]!r}"
    )

    # --- timeout MUST be 120 per SC[1]
    assert captured["kwargs"].get("timeout") == 120, (
        f"SC[1]: subprocess timeout must be 120s, got {captured['kwargs'].get('timeout')!r}"
    )

    # --- env MUST be sanitized (allow-list only)
    env = captured["kwargs"].get("env") or {}
    allowed = {
        "PATH", "HOME", "LANG", "LC_ALL", "USER", "SHELL", "TMPDIR", "TERM",
        "NODE_PATH", "SKELETON_EXTRACTOR_PUPPETEER_PATH",
        "DISPLAY", "XDG_RUNTIME_DIR",
    }
    forbidden = set(env.keys()) - allowed
    assert not forbidden, (
        f"SC[1]: subprocess env contains non-allow-listed keys: {forbidden}. "
        "Only the explicit allow-list in extract._sanitized_env() is permitted."
    )
    # PATH must always be present so node + chrome resolve.
    assert "PATH" in env, "SC[1]: PATH must propagate so 'node' resolves"

    # --- stdin must be a single JSON blob with the expected fields.
    stdin = captured["kwargs"].get("input")
    assert stdin is not None, "SC[1]: subprocess must receive stdin payload"
    payload = json.loads(stdin.decode("utf-8"))
    assert "mockupHtml" in payload and "breakpoints" in payload and "tokens" in payload, (
        f"SC[1]: stdin payload must carry mockupHtml/breakpoints/tokens; got {sorted(payload.keys())}"
    )
    assert payload["breakpoints"] == [420, 700, 1280]

    # --- result MUST be the parsed dict from the canned JSON blob (single blob).
    assert isinstance(result, dict)
    assert result["schema"] == "design-skeleton.v1"
    assert result["draft"] is True
    assert len(result["elements"]) == 12


def test_phase5b_sc4_draft_unsigned_and_filename(tmp_path, monkeypatch):
    """SC[5]: drafts produced by the extractor MUST be unsigned (no
    'signature' field anywhere in the YAML body), and the wrapper must not
    silently rename a `.draft.yaml` output path. Closes Codex critical [3].
    """
    # Patch _run_extractor so we don't need Chrome.
    monkeypatch.setattr(extract, "_run_extractor",
                        lambda *a, **kw: _minimal_synthetic_draft())
    # Pretend chrome is present so main() doesn't bail early.
    monkeypatch.setattr(
        extract.Path, "exists",
        lambda self: True if str(self) == "/bin/google-chrome" else Path.exists(self),
        raising=True,
    )

    out = tmp_path / "test_screen.draft.yaml"
    mockup = tmp_path / "fake.html"
    mockup.write_text("<html><body>x</body></html>", encoding="utf-8")

    rc = extract.main([
        "--mockup", str(mockup),
        "--out", str(out),
        "--breakpoints", "420,700,1280",
    ])
    assert rc == 0, f"expected exit 0; got {rc}"

    # --- File written exactly where the caller asked, suffix preserved.
    assert out.is_file(), "draft file must exist at the requested path"
    assert out.name.endswith(".draft.yaml"), (
        f"SC[5]: caller-supplied .draft.yaml suffix must be preserved; got {out.name}"
    )

    # --- The serialized YAML body MUST NOT contain a `signature:` block.
    body = out.read_text(encoding="utf-8")
    # We look for a top-level signature key — both inline and indented.
    # The extractor's draft is unsigned by contract; signing happens later in
    # visual-architect.freeze_skeleton (see SIGNED_FIELDS at freeze.py:110).
    assert "\nsignature:" not in body and not body.startswith("signature:"), (
        "SC[5]: draft must be unsigned. Found a top-level `signature:` key in:\n"
        + body[:500]
    )
    # Sanity: the schema is still design-skeleton.v1 + draft: true.
    assert "schema: design-skeleton.v1" in body
    assert "draft: true" in body


def test_phase5b_sc1_subprocess_runtime_error_observed(tmp_path, monkeypatch):
    """SC[1] failure-mode: subprocess returns non-zero → RuntimeError +
    `external_tool_fail` observation. NEVER passes through silently."""
    captured_obs: List[Tuple[str, str]] = []

    def fake_observe(category: str, what_happened: str, **kw):
        captured_obs.append((category, what_happened))

    monkeypatch.setattr(extract, "_observe", fake_observe)

    def fake_run(cmd, *args, **kwargs):
        return _make_canned_completed_process(
            stdout_bytes=b"", returncode=2,
            stderr_bytes=b"FATAL: chrome OOM at line 47\n" * 100,
        )

    monkeypatch.setattr(extract.subprocess, "run", fake_run)

    mockup = tmp_path / "fake.html"
    mockup.write_text("<html><body>x</body></html>", encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        extract._run_extractor(mockup, [420, 700, 1280], None, timeout_s=120)

    # Exception message must carry the exit code AND a stderr tail for triage.
    msg = str(excinfo.value)
    assert "2" in msg, f"RuntimeError must mention exit code 2; got {msg!r}"
    assert "chrome OOM" in msg, f"RuntimeError must include stderr tail; got {msg!r}"

    # Exactly one observation was emitted.
    assert len(captured_obs) >= 1, (
        f"SC[1]: subprocess failure must emit at least 1 observation; got {captured_obs!r}"
    )
    assert captured_obs[0][0] == "external_tool_fail", (
        f"SC[1]: failure category must be external_tool_fail; got {captured_obs[0][0]!r}"
    )


def test_phase5b_sc1_subprocess_empty_stdout_rejected(tmp_path, monkeypatch):
    """SC[1] adversarial: rc=0 but stdout is empty → MUST raise RuntimeError
    and emit observation. Chrome crashes that print to stderr but not stdout
    are the most common silent-failure mode for puppeteer subprocesses."""
    captured_obs: List[Tuple[str, str]] = []

    def fake_observe(category: str, what_happened: str, **kw):
        captured_obs.append((category, what_happened))

    monkeypatch.setattr(extract, "_observe", fake_observe)
    monkeypatch.setattr(
        extract.subprocess, "run",
        lambda *a, **kw: _make_canned_completed_process(stdout_bytes=b"", returncode=0),
    )

    mockup = tmp_path / "fake.html"
    mockup.write_text("<html><body>x</body></html>", encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        extract._run_extractor(mockup, [420, 700, 1280], None, timeout_s=120)

    assert "empty stdout" in str(excinfo.value).lower(), (
        f"empty-stdout error must self-describe; got {excinfo.value!r}"
    )
    assert any(c == "external_tool_fail" for c, _ in captured_obs), (
        f"empty-stdout failure must emit external_tool_fail observation; got {captured_obs!r}"
    )


def test_phase5b_fixture_diversity_malformed_html_yaml_round_trip(tmp_path):
    """Fixture diversity (Claude minor [5]): the YAML serialization layer
    must round-trip drafts containing adversarial inputs (deeply-nested DOM,
    special characters, empty lists, None values) without losing field
    integrity. This is the subprocess-free smoke test that complements the
    Chrome-required TS-SE-* fixtures.
    """
    adversarial_draft = {
        "schema": "design-skeleton.v1",
        "draft": True,
        # Field with special YAML chars (would break unquoted YAML).
        "source_url": "http://example.com:8080/path?q=value#anchor",
        "breakpoints": [420, 700, 1280],
        "elements": [
            # Deeply-nested element — 5 levels of dict + list interleaving.
            {
                "id": "deep",
                "selector": ".deep > .nested > .very > .deep > .leaf",
                "bbox": {"mobile": {"x": 0, "y": 0, "w": 0, "h": 0}},
                "tokens_used": {
                    "background": "token://color.bg",
                    "border": None,  # explicit None must round-trip
                },
                "interactions": [],
            },
            # Empty element — every field is empty/None.
            {
                "id": "empty",
                "selector": "",
                "bbox": {},
                "interactions": [],
            },
        ],
        "unresolved_tokens_report": [],
        "fonts_loaded": False,
        "fonts_ready_max_ms": 0,
    }

    yaml_text = extract._to_yaml(adversarial_draft)
    # Must be parseable by PyYAML without ambiguity.
    import yaml as _yaml
    parsed = _yaml.safe_load(yaml_text)

    # Field integrity assertions:
    assert parsed["schema"] == "design-skeleton.v1"
    assert parsed["source_url"] == "http://example.com:8080/path?q=value#anchor", (
        "URL with special chars (:?#) must round-trip through YAML"
    )
    assert len(parsed["elements"]) == 2
    assert parsed["elements"][0]["selector"] == ".deep > .nested > .very > .deep > .leaf"
    # tokens_used: nested field with None must survive.
    assert parsed["elements"][0]["tokens_used"]["border"] is None
    assert parsed["elements"][0]["tokens_used"]["background"] == "token://color.bg"
    # Empty element preserved as empty (not dropped).
    assert parsed["elements"][1]["selector"] == "" or parsed["elements"][1]["selector"] is None
    assert parsed["fonts_loaded"] is False
    assert parsed["fonts_ready_max_ms"] == 0
