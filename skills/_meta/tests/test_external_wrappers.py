#!/usr/bin/env python3
"""test_external_wrappers.py — ecosystem-keystone §5.9 + Contract 4.

Covers `external_wrappers.run_with_observation` and
`external_wrappers.emit_malformed` per contract-map `external-wrappers`
test scenarios TS-EW-01..03:

    TS-EW-01 happy path: returncode == 0, no observation emitted,
             CompletedProcess returned.
    TS-EW-02 non-zero exit: observation emitted with
             fingerprint=`f"{fingerprint_on_error}-{returncode}"`,
             CompletedProcess still returned (not raised).
    TS-EW-03 timeout: observation emitted with fingerprint=`f"timeout-{T}s"`
             BEFORE subprocess.TimeoutExpired is re-raised.

Bonus coverage:
    TS-EW-04 emit_malformed sibling helper writes the expected
             `external_tool_fail` with fingerprint=`malformed_output`.
    TS-EW-05 fail-open: observation-layer raising does NOT block the
             primary return path nor the TimeoutExpired re-raise.

Run:
    pytest skills/_meta/tests/test_external_wrappers.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import external_wrappers  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


class _ObserveSpy:
    """Records every claude_observe call so tests can assert on them."""

    def __init__(self):
        self.calls = []  # list[tuple[args, kwargs]]

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return None


@pytest.fixture
def spy(monkeypatch):
    """Intercept the `claude_observe` symbol inside external_wrappers.

    We patch the name in the external_wrappers module namespace, which is
    what `_safe_observe` resolves at call time. This is the canonical
    monkeypatch target for code of the form `from foo import bar`.
    """
    s = _ObserveSpy()
    monkeypatch.setattr(external_wrappers, "claude_observe", s)
    return s


# ---------------------------------------------------------------------------
# TS-EW-01 — happy path
# ---------------------------------------------------------------------------


def test_ts_ew_01_happy_path_no_observation(spy):
    """TS-EW-01: returncode == 0, no observation emitted, CompletedProcess returned."""
    result = external_wrappers.run_with_observation(
        [sys.executable, "-c", "print('hello')"],
        timeout=10,
        subject_id="test-codex",
    )
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert "hello" in (result.stdout or "")
    assert spy.calls == [], (
        f"expected no observation on returncode 0, got {spy.calls!r}"
    )


# ---------------------------------------------------------------------------
# TS-EW-02 — non-zero exit
# ---------------------------------------------------------------------------


def test_ts_ew_02_non_zero_exit_emits_observation(spy):
    """TS-EW-02: returncode != 0, external_tool_fail emitted, CompletedProcess returned."""
    result = external_wrappers.run_with_observation(
        [sys.executable, "-c", "import sys; sys.exit(42)"],
        timeout=10,
        subject_id="test-codex",
    )
    # Primary return path: CompletedProcess still returned — caller decides policy.
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 42

    # Observation side-effect: exactly one call with the expected shape.
    assert len(spy.calls) == 1, f"expected 1 observation, got {spy.calls!r}"
    args, kwargs = spy.calls[0]
    assert args == ("external_tool_fail",), (
        f"expected positional category 'external_tool_fail', got {args!r}"
    )
    assert kwargs.get("subject_id") == "test-codex"
    assert kwargs.get("fingerprint") == "returncode-42"
    assert kwargs.get("subject_type") == "external_tool"
    what = kwargs.get("what_happened", "")
    assert "test-codex" in what
    assert "42" in what


def test_ts_ew_02_custom_fingerprint_prefix(spy):
    """TS-EW-02 variant: custom fingerprint_on_error prefix flows through."""
    result = external_wrappers.run_with_observation(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        timeout=10,
        subject_id="test-gemini",
        fingerprint_on_error="exit",
    )
    assert result.returncode == 7
    assert len(spy.calls) == 1
    _, kwargs = spy.calls[0]
    assert kwargs.get("fingerprint") == "exit-7", (
        f"expected custom prefix fingerprint 'exit-7', got {kwargs.get('fingerprint')!r}"
    )


# ---------------------------------------------------------------------------
# TS-EW-03 — timeout
# ---------------------------------------------------------------------------


def test_ts_ew_03_timeout_emits_observation_before_raise(spy):
    """TS-EW-03: TimeoutExpired re-raised AFTER external_tool_slow observation."""
    with pytest.raises(subprocess.TimeoutExpired):
        external_wrappers.run_with_observation(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=1,
            subject_id="test-codex",
        )

    # Observation must have been emitted BEFORE the exception propagated.
    assert len(spy.calls) == 1, (
        f"expected exactly 1 observation before raise, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args == ("external_tool_slow",), (
        f"expected positional category 'external_tool_slow', got {args!r}"
    )
    assert kwargs.get("subject_id") == "test-codex"
    assert kwargs.get("fingerprint") == "timeout-1s"
    assert kwargs.get("subject_type") == "external_tool"
    assert "1s" in kwargs.get("what_happened", "") or "1" in kwargs.get(
        "what_happened", ""
    )


# ---------------------------------------------------------------------------
# TS-EW-04 — emit_malformed sibling
# ---------------------------------------------------------------------------


def test_ts_ew_04_emit_malformed_writes_expected_observation(spy):
    """TS-EW-04: emit_malformed writes external_tool_fail + malformed_output."""
    external_wrappers.emit_malformed("test-codex", "not-valid-json}}}")
    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    assert args == ("external_tool_fail",)
    assert kwargs.get("subject_id") == "test-codex"
    assert kwargs.get("fingerprint") == "malformed_output"
    assert kwargs.get("subject_type") == "external_tool"
    assert "unparseable output" in kwargs.get("what_happened", "")
    assert "not-valid-json" in kwargs.get("what_happened", "")


def test_ts_ew_04_emit_malformed_truncates_excerpt(spy):
    """emit_malformed excerpt > 200 chars is truncated (bound aggregate)."""
    long_excerpt = "x" * 500
    external_wrappers.emit_malformed("test-codex", long_excerpt)
    assert len(spy.calls) == 1
    _, kwargs = spy.calls[0]
    what = kwargs.get("what_happened", "")
    # Prefix ("unparseable output: ") + 200 x's expected; no full 500.
    assert "x" * 200 in what
    assert "x" * 201 not in what


# ---------------------------------------------------------------------------
# TS-EW-05 — fail-open: observation-layer raising does not block caller
# ---------------------------------------------------------------------------


def _raising_observe(*args, **kwargs):
    raise RuntimeError("simulated observation backend failure")


def test_ts_ew_05_fail_open_on_non_zero(monkeypatch):
    """Observation-layer RuntimeError does NOT block CompletedProcess return."""
    monkeypatch.setattr(external_wrappers, "claude_observe", _raising_observe)
    # Must NOT raise — the observation layer raising is suppressed by
    # _safe_observe; the primary return path still yields the CompletedProcess.
    result = external_wrappers.run_with_observation(
        [sys.executable, "-c", "import sys; sys.exit(9)"],
        timeout=10,
        subject_id="test-codex",
    )
    assert result.returncode == 9


def test_ts_ew_05_fail_open_on_timeout_still_raises_timeoutexpired(monkeypatch):
    """Observation-layer RuntimeError during timeout path: TimeoutExpired still raised."""
    monkeypatch.setattr(external_wrappers, "claude_observe", _raising_observe)
    with pytest.raises(subprocess.TimeoutExpired):
        external_wrappers.run_with_observation(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=1,
            subject_id="test-codex",
        )


def test_ts_ew_05_fail_open_on_emit_malformed(monkeypatch):
    """emit_malformed never raises even if claude_observe is broken."""
    monkeypatch.setattr(external_wrappers, "claude_observe", _raising_observe)
    # Must NOT raise.
    external_wrappers.emit_malformed("test-codex", "bad output")


# ---------------------------------------------------------------------------
# Import / surface checks
# ---------------------------------------------------------------------------


def test_module_surface_exposes_both_helpers():
    """Module exports both run_with_observation + emit_malformed per Contract 4."""
    assert hasattr(external_wrappers, "run_with_observation")
    assert hasattr(external_wrappers, "emit_malformed")
    assert callable(external_wrappers.run_with_observation)
    assert callable(external_wrappers.emit_malformed)


def test_module_does_not_mutate_cmd(spy):
    """The cmd list argument must not be mutated by run_with_observation."""
    cmd = [sys.executable, "-c", "print('keep')"]
    before = list(cmd)
    external_wrappers.run_with_observation(
        cmd, timeout=10, subject_id="test-codex"
    )
    assert cmd == before, f"cmd was mutated: before={before!r} after={cmd!r}"
