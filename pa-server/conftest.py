"""Root conftest for the pa-server test tree (AMY M0a).

Pins ``pa-server/`` onto ``sys.path`` so ``from tests.fixtures import ...``
resolves regardless of the working directory pytest is launched from (bob's
trusted_runner invokes ``pytest <abs path to test file>`` from the project root,
not from inside pa-server/). pytest's default prepend-import already does this
via the package ``__init__.py`` files; this is belt-and-suspenders so the suite
is portable across invocation contexts.
"""
import sys
from pathlib import Path

_PA_SERVER_ROOT = Path(__file__).resolve().parent
if str(_PA_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PA_SERVER_ROOT))
