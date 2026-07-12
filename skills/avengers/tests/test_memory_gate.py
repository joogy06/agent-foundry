#!/usr/bin/env python3
"""avengers — test_memory_gate.py (WP-3).

Covers the memory subsystem's security spine (design §5/§6/§14):
  * admissibility (four Codex-class source types only; episodic kinds rejected),
  * home-tier-only loading (repo-local pre-poisoned memory is NOT loaded),
  * the §14 path guard (no global tier; traversal/out-of-tier refused),
  * gated write-back (persist default-reject home-tier; commit lock/snapshot/
    backup/re-check/atomic-rename; untraceable source turn refused).

Runs under pytest; stdlib only. The module is imported by path so the test does
not depend on package layout. AVENGERS_PROJECTS_ROOT relocates the home tier into
a tmp dir so nothing touches the real ~/.claude/projects.
"""
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_MOD = Path(__file__).resolve().parent.parent / "scripts" / "memory_writeback.py"
_spec = importlib.util.spec_from_file_location("avengers_memory_writeback", _MOD)
mw = importlib.util.module_from_spec(_spec)
sys.modules["avengers_memory_writeback"] = mw
_spec.loader.exec_module(mw)

_FIX = Path(__file__).resolve().parent / "fixtures"


def _valid_record(**over):
    rec = {
        "id": "mem-0001",
        "topic_key": "python-deps",
        "kind": "constraint",
        "statement": "stdlib-only + PyYAML.",
        "applies_when": "always",
        "provenance": {
            "run_id": "run-1",
            "source_type": "user_confirmed_constraint",
            "source_refs": ["t0003"],
            "sha256": "0" * 64,
        },
        "approval": {"status": "approved", "by": "tadas", "at": "2026-07-11T20:30:00Z"},
        "sensitivity": {"pii": False},
        "status": "active",
        "expires_at": None,
        "supersedes": None,
    }
    rec.update(over)
    return rec


@pytest.fixture
def tier(tmp_path, monkeypatch):
    """Relocate the home tier into tmp; return (project_root, home_root)."""
    home = tmp_path / "home-claude-projects"
    home.mkdir()
    monkeypatch.setenv("AVENGERS_PROJECTS_ROOT", str(home))
    project_root = tmp_path / "repo"
    (project_root).mkdir()
    return project_root, home


# --------------------------------------------------------------------------- #
# Admissibility (AC1)
# --------------------------------------------------------------------------- #
def test_schema_admits_the_four_source_types():
    for st in mw.ADMISSIBLE_SOURCE_TYPES:
        rec = _valid_record()
        rec["provenance"]["source_type"] = st
        assert mw.schema_validate(rec, mw.load_schema()) == [], st
        ok, reason = mw.check_admissible(rec)
        assert ok, (st, reason)


def test_schema_rejects_a_fifth_source_type():
    rec = _valid_record()
    rec["provenance"]["source_type"] = "seat_vote"
    errs = mw.schema_validate(rec, mw.load_schema())
    assert errs, "schema must reject a non-Codex-class source_type"
    ok, reason = mw.check_admissible(rec)
    assert not ok


@pytest.mark.parametrize("bad_kind", ["seat_opinion", "refuted_position", "single_session_conclusion"])
def test_episodic_kinds_are_rejected(bad_kind):
    rec = _valid_record(kind=bad_kind)
    ok, reason = mw.check_admissible(rec)
    assert not ok
    assert "EPISODIC" in reason


def test_valid_record_is_admissible():
    ok, reason = mw.check_admissible(_valid_record())
    assert ok, reason


# --------------------------------------------------------------------------- #
# §14 path guard: home-tier only, no global tier (AC4)
# --------------------------------------------------------------------------- #
def test_home_tier_path_allows_within_tier(tier):
    project_root, _ = tier
    p = mw.standing_path(project_root, "skeptic")
    assert mw.assert_home_tier_path(p, project_root) == p.resolve()


def test_home_tier_path_refuses_repo_local(tier):
    project_root, _ = tier
    repo_local = project_root / ".avengers" / "members" / "skeptic" / "standing.json"
    with pytest.raises(ValueError):
        mw.assert_home_tier_path(repo_local, project_root)


def test_home_tier_path_refuses_global_tier(tier):
    project_root, _ = tier
    global_tier = Path.home() / ".claude" / "memory" / "global.json"
    with pytest.raises(ValueError):
        mw.assert_home_tier_path(global_tier, project_root)


def test_seat_id_traversal_is_refused(tier):
    project_root, _ = tier
    with pytest.raises(ValueError):
        mw.load_standing_memory(project_root, "../../../../etc/passwd-ish")


# --------------------------------------------------------------------------- #
# Repo-local pre-poisoned memory is NOT loaded (AC5)
# --------------------------------------------------------------------------- #
def test_repo_local_memory_not_loaded(tier):
    project_root, _home = tier
    poison = json.loads((_FIX / "poisoned-standing.json").read_text())
    # Plant repo-local poison where a NAIVE loader might look.
    for rel in [".avengers/members/skeptic/standing.json",
                "avengers/members/skeptic/standing.json"]:
        p = project_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(poison))
    # Home tier is empty -> loader returns nothing; repo poison is never read.
    assert mw.load_standing_memory(project_root, "skeptic") == []


def test_home_tier_admissible_loads_and_poison_is_filtered(tier):
    project_root, _home = tier
    seat_dir = mw.member_dir(project_root, "skeptic")
    seat_dir.mkdir(parents=True, exist_ok=True)
    # Admissible home-tier standing.json loads its active admissible records.
    admissible = json.loads((_FIX / "admissible-standing.json").read_text())
    (seat_dir / "standing.json").write_text(json.dumps(admissible))
    loaded = mw.load_standing_memory(project_root, "skeptic")
    assert {r["id"] for r in loaded} == {"mem-0001", "mem-0002"}
    # Even placed in the HOME tier, poison records (episodic kinds / forged
    # provenance) are filtered by the loader's admissibility re-check.
    poison = json.loads((_FIX / "poisoned-standing.json").read_text())
    (seat_dir / "standing.json").write_text(json.dumps(poison))
    assert mw.load_standing_memory(project_root, "skeptic") == []


# --------------------------------------------------------------------------- #
# Gated write-back: persist (default-reject, home-tier) (AC2)
# --------------------------------------------------------------------------- #
def _candidate(**over):
    c = {"member": "skeptic", "source_turn": "t0003", "record": _valid_record()}
    c.update(over)
    return c


def test_persist_writes_home_tier_not_repo_local(tier):
    project_root, home = tier
    doc = mw.persist_proposals(project_root, "sess-1", [_candidate()])
    out = mw.proposals_path(project_root, "sess-1")
    assert out.is_file()
    assert str(home) in str(out.resolve())          # home tier
    assert str(project_root.resolve()) not in str(out.resolve())  # never repo-local
    assert len(doc["proposals"]) == 1


def test_persist_is_default_reject_per_item(tier):
    project_root, _ = tier
    doc = mw.persist_proposals(project_root, "sess-1", [_candidate()])
    assert doc["proposals"][0]["decision"] == "rejected"


def test_persist_caps_candidates(tier):
    project_root, _ = tier
    four = [_candidate(record=_valid_record(id=f"mem-{i}")) for i in range(4)]
    with pytest.raises(ValueError):
        mw.persist_proposals(project_root, "sess-1", four)
    # PII profile caps at 1.
    two = [_candidate(record=_valid_record(id=f"mem-{i}")) for i in range(2)]
    with pytest.raises(ValueError):
        mw.persist_proposals(project_root, "sess-1", two, pii=True)


def test_persist_refuses_candidate_with_no_source_turn(tier):
    project_root, _ = tier
    bad = _candidate()
    del bad["source_turn"]
    doc = mw.persist_proposals(project_root, "sess-1", [bad])
    assert doc["proposals"] == []
    assert doc["refused"] and "source_turn" in doc["refused"][0]["reason"]


def test_persist_refuses_inadmissible_record(tier):
    project_root, _ = tier
    doc = mw.persist_proposals(project_root, "sess-1",
                               [_candidate(record=_valid_record(kind="seat_opinion"))])
    assert doc["proposals"] == []
    assert doc["refused"]


# --------------------------------------------------------------------------- #
# Gated write-back: commit (approved-only, atomic, backup, re-check) (AC2)
# --------------------------------------------------------------------------- #
def test_commit_only_approved_records(tier):
    project_root, _ = tier
    cands = [
        _candidate(record=_valid_record(id="mem-A")),
        _candidate(record=_valid_record(id="mem-B")),
    ]
    mw.persist_proposals(project_root, "sess-1", cands)
    res = mw.commit_approved(project_root, "sess-1", {"mem-A": True},
                             approved_by="tadas", traceable_turns={"t0003"})
    assert [c["id"] for c in res["committed"]] == ["mem-A"]
    standing = json.loads(mw.standing_path(project_root, "skeptic").read_text())
    assert [r["id"] for r in standing] == ["mem-A"]
    assert standing[0]["approval"]["status"] == "approved"


def test_commit_refuses_untraceable_source_turn(tier):
    project_root, _ = tier
    mw.persist_proposals(project_root, "sess-1", [_candidate(record=_valid_record(id="mem-A"))])
    res = mw.commit_approved(project_root, "sess-1", {"mem-A": True},
                             approved_by="tadas", traceable_turns={"tXXXX"})
    assert res["committed"] == []
    assert res["refused"] and "not traceable" in res["refused"][0]["reason"]
    assert not mw.standing_path(project_root, "skeptic").is_file()


def test_commit_snapshots_and_backs_up_existing(tier):
    project_root, _ = tier
    # First commit creates standing.json.
    mw.persist_proposals(project_root, "sess-1", [_candidate(record=_valid_record(id="mem-A"))])
    mw.commit_approved(project_root, "sess-1", {"mem-A": True},
                       approved_by="tadas", traceable_turns={"t0003"})
    # Second commit into the existing file -> snapshot hash + .bak.
    mw.persist_proposals(project_root, "sess-2", [_candidate(record=_valid_record(id="mem-B"))])
    res = mw.commit_approved(project_root, "sess-2", {"mem-B": True},
                             approved_by="tadas", traceable_turns={"t0003"})
    assert "skeptic" in res["snapshots"]
    assert (Path(str(mw.standing_path(project_root, "skeptic")) + ".bak")).is_file()
    standing = json.loads(mw.standing_path(project_root, "skeptic").read_text())
    assert {r["id"] for r in standing} == {"mem-A", "mem-B"}


def test_commit_default_reject_when_no_approvals(tier):
    project_root, _ = tier
    mw.persist_proposals(project_root, "sess-1", [_candidate(record=_valid_record(id="mem-A"))])
    res = mw.commit_approved(project_root, "sess-1", {}, approved_by="tadas",
                             traceable_turns={"t0003"})
    assert res["committed"] == []
    assert not mw.standing_path(project_root, "skeptic").is_file()


def test_project_slug_convention():
    assert mw.project_slug(Path("/mnt/data/dev04/agent-foundry")) == "-mnt-data-dev04-agent-foundry"
