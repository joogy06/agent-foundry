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


def _claude_md_rows(m, home, repo):
    sec = m.Section("Install")
    m.check_global_claude_md(sec, home, repo)
    return [(r.status, r.detail) for r in sec.results]


def test_project_pointer_at_home_fails(tmp_path):
    """#318 fix round 1 (item 8): presence alone passed a project file installed at home."""
    m = _load()
    (tmp_path / "CLAUDE.md").write_text("# p\n" + m.PROJECT_POINTER_MARKER + "\n", encoding="utf-8")
    rows = _claude_md_rows(m, tmp_path, None)
    assert rows[0][0] == m.FAIL and "pointer" in rows[0][1]


def test_home_is_compared_with_the_repo_global(tmp_path):
    m = _load()
    home, repo = tmp_path / "home", tmp_path / "repo"
    (repo / "global").mkdir(parents=True)
    home.mkdir()
    (repo / "global" / "CLAUDE.md").write_text("# global\n", encoding="utf-8")
    (home / "CLAUDE.md").write_text("# global\n", encoding="utf-8")
    assert _claude_md_rows(m, home, repo)[0][0] == m.PASS
    (home / "CLAUDE.md").write_text("# global, edited\n", encoding="utf-8")
    assert _claude_md_rows(m, home, repo)[0][0] == m.WARN


def test_marker_matches_the_real_project_file():
    m = _load()
    repo = SKILL.parents[1]
    if not (repo / "global" / "CLAUDE.md").is_file():
        import pytest
        pytest.skip("not running from a foundry-lab checkout")
    assert m.PROJECT_POINTER_MARKER in (repo / "CLAUDE.md").read_text(encoding="utf-8")


def test_a_crlf_home_copy_still_matches_the_repo_global(tmp_path):
    """#318 fix round 2 (item 7): a Windows copy differs only in line endings."""
    m = _load()
    home, repo = tmp_path / "home", tmp_path / "repo"
    (repo / "global").mkdir(parents=True)
    home.mkdir()
    (repo / "global" / "CLAUDE.md").write_bytes(b"# global\nrules\n")
    (home / "CLAUDE.md").write_bytes(b"# global\r\nrules\r\n")
    assert _claude_md_rows(m, home, repo)[0][0] == m.PASS


def _agy_rows(m, tmp_path, text):
    """Rows of the agy settings check for a home whose agy settings file holds `text` (None: no file)."""
    home = tmp_path / "h" / ".claude"
    home.mkdir(parents=True)
    if text is not None:
        cfg = home.parent / ".gemini" / "antigravity-cli" / "settings.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(text, encoding="utf-8")
    s = m.Section("Tooling")
    m.check_agy_settings(s, home)
    return s.results


def test_agy_non_workspace_access_true_is_a_warning(tmp_path):
    m = _load()
    rows = _agy_rows(m, tmp_path, json.dumps({"allowNonWorkspaceAccess": True}))
    assert len(rows) == 1 and rows[0].status == m.WARN and "allowNonWorkspaceAccess" in rows[0].detail


def test_agy_non_workspace_access_absent_or_false_passes(tmp_path):
    """Absent is the state #366 measured on this host, so it is not a warning."""
    m = _load()
    for n, text in enumerate(('{"model": "x"}', '{"allowNonWorkspaceAccess": false}')):
        rows = _agy_rows(m, tmp_path / str(n), text)
        assert [r.status for r in rows] == [m.PASS], text


def test_agy_settings_absent_says_nothing_and_broken_warns(tmp_path):
    m = _load()
    assert _agy_rows(m, tmp_path / "a", None) == []
    assert _agy_rows(m, tmp_path / "b", "{not json")[0].status == m.WARN


def test_the_tooling_section_runs_the_agy_check(tmp_path):
    m = _load()
    home = tmp_path / "h" / ".claude"
    home.mkdir(parents=True)
    cfg = home.parent / ".gemini" / "antigravity-cli" / "settings.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('{"allowNonWorkspaceAccess": true}', encoding="utf-8")
    details = [r.detail for sec in m.run(home=home, repo=None, project=None) for r in sec.results]
    assert any("allowNonWorkspaceAccess is not off" in d for d in details)
