"""pytest configuration for skills/avengers/tests: the live-HOME guard (#282 H2, plan K23).

The guard (skills/_meta/tests/live_home_guard.py) fails any test or collector that writes the REAL
home's ~/.claude/state/seat-model-*.json or ~/.claude/projects/*/astra-budget.jsonl (or their .lock
sidecars), creation included. The real home is captured HERE, at conftest import, before
collection. `--live-home-guard=report` lists the offenders instead of failing them.

The module is loaded BY PATH under one fixed name, so a session that collects several guarded suites
(skills/_meta, skills/avengers, skills/forge) shares one module, one audit hook and one plugin.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_GUARD_NAME = "foundry_live_home_guard"
_GUARD_FILE = Path(__file__).resolve().parents[2] / "_meta" / "tests" / "live_home_guard.py"


def _load_guard():
    module = sys.modules.get(_GUARD_NAME)
    if module is None:
        spec = importlib.util.spec_from_file_location(_GUARD_NAME, _GUARD_FILE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_GUARD_NAME] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(_GUARD_NAME, None)
            raise
    return module


_guard = _load_guard()
_guard.capture(__file__)

#: Per-test isolation: an empty temp HOME and a stub `codex` prepended to PATH.
empty_live_home = _guard.empty_live_home


_SEAT_MODEL_FILE = Path(__file__).resolve().parents[2] / "_meta" / "seat_model.py"


def seat_model_under_roster(monkeypatch, main, support, benched):
    """#291 WP-6 (design s3.9): a FRESH seat_model, loaded in-process under a private module name,
    over a model_roster whose tier attributes are monkeypatched to (main, support, benched). The
    shipped seat_model.py runs as-is (no production path override); only the roster DATA it imports
    differs, and monkeypatch restores it. A fixture HISTORY row keeps the roster's invariants
    satisfied, so the fresh import passes its fail-closed check as a real swap would. The same
    helper lives in skills/_meta/tests/conftest.py (conftests cannot import each other safely: each
    one registers the live-HOME guard at import). Returns (module, fixture_revision)."""
    meta = str(_SEAT_MODEL_FILE.parent)
    if meta not in sys.path:
        sys.path.insert(0, meta)
    import model_roster  # noqa: E402  (the one shared roster module seat_model imports)

    revision = model_roster.REVISION + 1
    row = {"rev": revision, "at": "2026-09-24", "claude_main": main, "claude_support": support,
           "codex_std": model_roster.CODEX_STD, "benched": tuple(sorted(benched)),
           "reason": "test fixture pair (#291 WP-6 reversibility)"}
    if hasattr(model_roster, "CODEX_SUPPORT"):
        # #302 WP-1: from roster rev 3 the last HISTORY row also carries the codex support tier, and
        # must equal the live value; a roster without the tier keeps the rev-2 row shape.
        row["codex_support"] = model_roster.CODEX_SUPPORT
    if hasattr(model_roster, "CODEX_TOP_ROLES"):
        # The astra reserve (roster rev 4): the last HISTORY row records the live TOP reserve too.
        row["codex_top_roles"] = model_roster.CODEX_TOP_ROLES
    if hasattr(model_roster, "AGY_FAMILY"):
        # #367 (roster rev 6): the last HISTORY row records the live agy family too.
        row["agy_family"] = model_roster.AGY_FAMILY
    if hasattr(model_roster, "AGY_LEVEL_BY_SIZE"):
        # #367 WP-C (roster rev 7): and the live agy size -> level map.
        row["agy_level_by_size"] = dict(model_roster.AGY_LEVEL_BY_SIZE)
    monkeypatch.setattr(model_roster, "CLAUDE_MAIN", main)
    monkeypatch.setattr(model_roster, "CLAUDE_SUPPORT", support)
    monkeypatch.setattr(model_roster, "CLAUDE_BENCHED", frozenset(benched))
    monkeypatch.setattr(model_roster, "REVISION", revision)
    monkeypatch.setattr(model_roster, "HISTORY", tuple(model_roster.HISTORY) + (row,))
    name = f"avengers_seat_model_roster_fixture_{main}_{support}"
    spec = importlib.util.spec_from_file_location(name, _SEAT_MODEL_FILE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module, revision


@pytest.fixture
def load_seat_model_under_roster(monkeypatch):
    """`load(main, support, benched) -> (fresh seat_model, fixture revision)` for the reversibility tests."""
    return lambda main, support, benched: seat_model_under_roster(monkeypatch, main, support, benched)


def pytest_addoption(parser):
    _guard.addoption(parser)


def pytest_configure(config):
    _guard.register(config, __file__)
