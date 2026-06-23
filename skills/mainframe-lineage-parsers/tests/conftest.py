"""conftest.py — path-load shim for the mainframe-lineage-parsers test suite.

The skill's scripts import each other by bare name (``import controlm_extract``,
``import openlineage_emit``) after inserting their own ``scripts/`` dir onto
``sys.path`` at runtime (the path-load idiom in run_lineage.py / openlineage_emit.py).
For pytest to import the modules directly, we add BOTH this skill's ``scripts/``
dir AND the sibling ``lineage-extract-static/scripts`` dir (the reused OL emit /
validate machinery) onto ``sys.path`` here, mirroring run_lineage.py's header.

No network, no LLM — pure import wiring.
"""

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_SKILL = _TESTS.parent
_SCRIPTS = _SKILL / "scripts"
_SKILLS_ROOT = _SKILL.parent
_SIBLING_SCRIPTS = _SKILLS_ROOT / "lineage-extract-static" / "scripts"

for _p in (str(_SCRIPTS), str(_SIBLING_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
