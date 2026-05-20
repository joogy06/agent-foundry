"""pytest fixtures for the affordance-advisor test suite.

Adds the sibling `scripts/` directory to sys.path so tests can `import advise`,
`import detect_host_cli`, and `import lint_registry` directly.
"""
from __future__ import annotations

import sys
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def pytest_configure(config):
    """Register custom markers so unknown-marker warnings don't surface."""
    config.addinivalue_line(
        "markers",
        "manual: tests that require manual invocation; skipped in CI by default",
    )
