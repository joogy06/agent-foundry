"""Tests for the env-readiness doctor — exercises verdict logic + read-only guarantee."""
import importlib.util as ilu
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "readiness.py"


def _load():
    spec = ilu.spec_from_file_location("_readiness_t", SCRIPT)
    mod = ilu.module_from_spec(spec)
    sys.modules[spec.name] = mod  # required before exec for dataclass annotation resolution
    spec.loader.exec_module(mod)
    return mod


def test_verdict_logic():
    m = _load()
    sec = m.Section("x")
    sec.add(m.PASS, "ok")
    assert m.verdict([sec]) == "READY"
    sec.add(m.WARN, "meh")
    assert m.verdict([sec]) == "READY-WITH-WARNINGS"
    sec.add(m.FAIL, "broken")
    assert m.verdict([sec]) == "NOT-READY"


def test_runs_on_empty_home_without_crashing(tmp_path):
    """A bare/empty claude-home must produce FAILs, not a traceback (crash-proof)."""
    m = _load()
    sections = m.run(home=tmp_path, repo=None, project=None)
    assert sections, "expected sections"
    v = m.verdict(sections)
    assert v in ("READY", "READY-WITH-WARNINGS", "NOT-READY")
    # An empty home has no skills/gates → must surface FAILs, i.e. NOT-READY.
    assert v == "NOT-READY"


def test_json_mode_and_strict_exit(tmp_path):
    """--json emits valid JSON; --strict exits 1 on NOT-READY."""
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--claude-home", str(tmp_path), "--json", "--strict"],
        capture_output=True, text=True, timeout=60,
    )
    payload = json.loads(r.stdout)
    assert payload["verdict"] == "NOT-READY"
    assert r.returncode == 1  # strict + NOT-READY
    assert "sections" in payload


def test_is_read_only(tmp_path):
    """The doctor must not create or modify any file under claude-home."""
    m = _load()
    before = set(p for p in tmp_path.rglob("*"))
    m.run(home=tmp_path, repo=None, project=None)
    after = set(p for p in tmp_path.rglob("*"))
    assert before == after, "doctor mutated the environment — it must be read-only"


def test_subprocess_checks_carry_readonly_flags(tmp_path, monkeypatch):
    """check_gates must not write .pyc (-B / PYTHONDONTWRITEBYTECODE) and check_identity
    must pass --no-write — both are read-only guarantees Codex flagged."""
    m = _load()
    calls = []

    class _R:
        returncode = 0
        stdout = "OK"
        stderr = ""

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return _R()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    # make gates.py + identity_check.py appear to exist
    meta = tmp_path / "skills" / "_meta"
    meta.mkdir(parents=True)
    (meta / "gates.py").write_text("# stub\n")
    (meta / "identity_check.py").write_text("# stub\n")

    sg = m.Section("Gates"); m.check_gates(sg, tmp_path)
    si = m.Section("Identity"); m.check_identity(si, tmp_path)

    gates_call = next(a for a, _ in calls if any("gates.py" in str(x) or "g',sys.argv" in str(x) for x in a))
    assert "-B" in gates_call, "gates import-smoke must use -B (no .pyc writes)"
    assert any("identity_check.py" in str(x) for a, _ in calls for x in a)
    id_call = next(a for a, _ in calls if any("identity_check.py" in str(x) for x in a))
    assert "--no-write" in id_call, "identity check must pass --no-write"
