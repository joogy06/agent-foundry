"""Smoke test for the dependency doctor (check_deps.py)."""
import io
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"


def test_doctor_reports_this_skill_and_exits_zero():
    """report() must identify THIS skill and never fail on a missing OPTIONAL dep."""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("_les_check_deps_t", SCRIPTS / "check_deps.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.report()
    out = buf.getvalue()
    assert rc == 0
    assert "lineage-extract-static — dependency check" in out
    assert "jinja2" in out                          # this skill's enhancer
    assert "sqlglot" not in out                     # NOT this skill's enhancer
