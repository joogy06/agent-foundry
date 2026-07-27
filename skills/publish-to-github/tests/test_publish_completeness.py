"""Tests for the publish skill-set completeness guard (avengers P3).

The guard compares the LIVE skill set against the STAGED skill set and hard-fails
if a live skill vanished from staging without an exclusion to explain it —
catching a staging engine that silently drops a skill. It REUSES should_exclude()
so config/always exclusions are accounted for, never flagged.
"""
import importlib.util as ilu
import json
import shutil
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "publish_prep.py"


def _load():
    spec = ilu.spec_from_file_location("_publish_prep_t", SCRIPT)
    m = ilu.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _mk_skills(root: Path, names):
    for n in names:
        d = root / "skills" / n
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"# {n}\n", encoding="utf-8")


# --- unit: check_skill_completeness --------------------------------------

def test_dropped_skill_is_unexplained(tmp_path):
    m = _load()
    src = tmp_path / "src"; stg = tmp_path / "stg"
    _mk_skills(src, ["keep-me", "drop-me"])
    _mk_skills(stg, ["keep-me"])            # drop-me silently lost, not excluded
    unexplained, explained = m.check_skill_completeness(src, stg, exclusions=[])
    assert unexplained == ["drop-me"]
    assert explained == []


def test_config_excluded_skill_is_explained(tmp_path):
    m = _load()
    src = tmp_path / "src"; stg = tmp_path / "stg"
    _mk_skills(src, ["keep-me", "secret-skill"])
    _mk_skills(stg, ["keep-me"])            # secret-skill absent BUT excluded
    unexplained, explained = m.check_skill_completeness(
        src, stg, exclusions=["skills/secret-skill"])
    assert unexplained == []
    assert explained == ["secret-skill"]


def test_always_pattern_excluded_skill_is_explained(tmp_path):
    m = _load()
    src = tmp_path / "src"; stg = tmp_path / "stg"
    _mk_skills(src, ["keep-me", "__pycache__"])   # matches ALWAYS_EXCLUDE_PATTERNS
    _mk_skills(stg, ["keep-me"])
    unexplained, explained = m.check_skill_completeness(src, stg, exclusions=[])
    assert unexplained == []
    assert "__pycache__" in explained


def test_complete_staging_has_no_findings(tmp_path):
    m = _load()
    src = tmp_path / "src"; stg = tmp_path / "stg"
    _mk_skills(src, ["a", "b", "c"])
    _mk_skills(stg, ["a", "b", "c"])
    unexplained, explained = m.check_skill_completeness(src, stg, exclusions=[])
    assert unexplained == [] and explained == []


# --- end-to-end: main() exit code ----------------------------------------

def _min_config(tmp_path, src_root: Path) -> Path:
    cfg = tmp_path / "publish-config.json"
    cfg.write_text(json.dumps({
        "version": 1,
        "source": {"root": str(src_root), "subdirs": ["skills"]},
        "exclusions": [],
        "scrubs": [],
        "forbidden_patterns": [],
        "bundle_files": [],
    }), encoding="utf-8")
    return cfg


def _run_main(m, cfg: Path, staging: Path):
    old = sys.argv
    sys.argv = ["publish_prep.py", "--config", str(cfg), "--staging-dir", str(staging)]
    try:
        return m.main()
    finally:
        sys.argv = old


def test_e2e_complete_staging_returns_zero(tmp_path):
    m = _load()
    src = tmp_path / "src"; _mk_skills(src, ["alpha", "beta"])
    cfg = _min_config(tmp_path, src)
    rc = _run_main(m, cfg, tmp_path / "staging")
    assert rc == 0


def test_e2e_dropped_skill_fails(tmp_path, monkeypatch):
    """A staging engine that loses a non-excluded skill must make prep FAIL."""
    m = _load()
    src = tmp_path / "src"; _mk_skills(src, ["alpha", "drop-me"])
    cfg = _min_config(tmp_path, src)

    # Simulate the staging-engine bug: after the real copy, drop-me disappears
    # from staging WITHOUT being added to any exclusion.
    original = m.copy_tree_with_exclusions

    def sabotage(src_root, staging_root, source_root, exclusions):
        res = original(src_root, staging_root, source_root, exclusions)
        shutil.rmtree(staging_root / "skills" / "drop-me", ignore_errors=True)
        return res

    monkeypatch.setattr(m, "copy_tree_with_exclusions", sabotage)
    rc = _run_main(m, cfg, tmp_path / "staging")
    assert rc == 1
