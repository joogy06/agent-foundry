"""Tests package — adjusts sys.path so `ms_office_security_check` resolves to
the package directory inside this skill.

Mirrors the path-mangle convention used by dep-currency-check/tests/__init__.py.
"""
import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))
