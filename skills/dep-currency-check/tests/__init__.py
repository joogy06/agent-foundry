"""Test package for dep-currency-check. Stdlib unittest only.

Each test module imports from `dep_currency_check.*` modules. The skill
root has a `dep_currency_check` symlink pointing at `scripts/` so
`python3 -m unittest tests.test_*` works from the tests/ parent dir.
"""
import sys
from pathlib import Path

# Make the skill root importable so `dep_currency_check` resolves to scripts/
_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))
