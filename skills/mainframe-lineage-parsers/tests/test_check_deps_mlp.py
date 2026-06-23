"""Smoke tests for the dependency doctor (check_deps.py) + the run_lineage --check-deps wiring."""
import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"


def test_doctor_reports_this_skill_and_exits_zero():
    """report() must identify THIS skill (not lineage-extract-static — the
    name-collision regression) and never fail on a missing OPTIONAL dep."""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("_mlp_check_deps_t", SCRIPTS / "check_deps.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.report()
    out = buf.getvalue()
    assert rc == 0
    assert "mainframe-lineage-parsers — dependency check" in out
    assert "sqlglot" in out and "networkx" in out  # this skill's enhancers
    assert "jinja2" not in out                      # NOT this skill's enhancer


def test_run_lineage_check_deps_flag_no_out_required():
    """--check-deps short-circuits before --out/--src and prints the mainframe doctor."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "run_lineage.py"), "--check-deps"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "mainframe-lineage-parsers — dependency check" in r.stdout
