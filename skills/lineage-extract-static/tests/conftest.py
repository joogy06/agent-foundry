"""Pytest path-load shim for lineage-extract-static.

The skill ships flat scripts under ``scripts/`` that import each other via
``sys.path.insert(0, <scripts dir>)`` at runtime (e.g. merge_into_ol imports
validate_ol). Tests import those modules directly, so we prepend the scripts dir
to ``sys.path`` here — mirroring the existing in-script idiom — instead of making
the skill a package.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
