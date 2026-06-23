"""Tests for prefs.py (per-domain preference profiles) + memory_primer digest."""
import importlib.util as ilu
import sys
from pathlib import Path

PREFS = Path(__file__).resolve().parent.parent / "scripts" / "prefs.py"
PRIMER = Path(__file__).resolve().parents[2] / "_meta" / "memory_primer.py"


def _load(path, name):
    spec = ilu.spec_from_file_location(name, path)
    m = ilu.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def test_set_load_roundtrip(tmp_path):
    m = _load(PREFS, "_prefs_t")
    m.cmd_set(tmp_path, "coding", "test_framework", "pytest", "2026-06-23")
    fm, body = m._read(tmp_path, "coding")
    assert fm["test_framework"] == "pytest"
    assert "set `test_framework` = pytest" in body          # dated note appended
    assert fm["domain"] == "coding" and fm["updated"] == "2026-06-23"


def test_load_empty_says_none(tmp_path, capsys):
    m = _load(PREFS, "_prefs_t2")
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "tone.md").write_text("---\ndomain: tone\nupdated:\n---\n\n# tone\n")
    m.cmd_load(tmp_path, "tone")
    assert "no recorded tone preferences yet" in capsys.readouterr().out


def test_set_updates_existing_and_records_old(tmp_path):
    m = _load(PREFS, "_prefs_t3")
    m.cmd_set(tmp_path, "tone", "length", "terse", "2026-06-23")
    m.cmd_set(tmp_path, "tone", "length", "balanced", "2026-06-24")
    fm, body = m._read(tmp_path, "tone")
    assert fm["length"] == "balanced"
    assert "(was: terse)" in body                            # history preserved


def test_invalid_domain_and_key_rejected(tmp_path):
    m = _load(PREFS, "_prefs_t4")
    import pytest
    with pytest.raises(SystemExit):
        m._profile_path(tmp_path, "bad/domain")
    with pytest.raises(SystemExit):
        m.cmd_set(tmp_path, "coding", "Bad Key", "x", "2026-06-23")


def test_newline_value_cannot_corrupt_frontmatter(tmp_path):
    """A value with newlines must be collapsed to one line so it can't inject a
    fake frontmatter key on the next parse (Codex finding)."""
    m = _load(PREFS, "_prefs_nl")
    m.cmd_set(tmp_path, "coding", "commit_style", "imperative\ninjected_key: evil", "2026-06-23")
    fm, _ = m._read(tmp_path, "coding")
    assert "injected_key" not in fm                      # NOT injected as a key
    assert "\n" not in fm["commit_style"]                # value is single-line
    assert fm["commit_style"] == "imperative injected_key: evil"


def test_primer_digest_never_crashes_and_has_both_lines():
    m = _load(PRIMER, "_primer_t")
    out = m.build_digest(Path("/tmp"))
    assert "Memory:" in out and "Environment:" in out
    assert "skills" in out and "agents" in out and "gates" in out


def test_primer_slug_matches_claude_convention():
    m = _load(PRIMER, "_primer_t2")
    assert m._project_slug(Path("/home/u/code/my_repo")) == "-home-u-code-my-repo"
