"""pytest configuration for skills/forge/tests: the live-HOME guard (#282 H2, plan K23).

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


def pytest_addoption(parser):
    _guard.addoption(parser)


def pytest_configure(config):
    _guard.register(config, __file__)
