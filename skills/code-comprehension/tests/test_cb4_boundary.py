"""HARD GATE #1 — CB4 boundary: a full standalone run touches NOTHING under
.ledger/ or progress/.

Snapshots .ledger/ and progress/ (recursive file list + per-file sha256) before
and after a complete `comprehension_run.orchestrate(...)` and asserts byte-identity
(zero new/changed/deleted files). Uses the fake intent backend (no real LLM).
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import comprehension_run  # noqa: E402
import partition as partition_mod  # noqa: E402


_FAKE_INTENT_YAML = """
schema_version: "1.0.0"
component_id: PLACEHOLDER
workspace_tree_hash: "0000000000000000000000000000000000000000"
content_hash: "0000000000000000000000000000000000000000000000000000000000000000"
extractor_id: intent-extract
extractor_version: "1.0.0"
model_id: claude-opus-4-7
sampled_at: "2026-06-08T00:00:00Z"
template_hash: "0000000000000000000000000000000000000000000000000000000000000000"
function_class: service
entry_points: []
inputs: []
outputs: []
side_effects: []
flows_participated: []
intent:
  one_line: "A component."
  confidence_level: interpretive
error_paths: []
test_seeds: []
unknowns: []
determinism_class: fresh_interpretive
"""


def _snapshot(dirs) -> dict:
    """Recursive {rel_path: sha256} over the given dirs (absent dir => empty)."""
    snap = {}
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                h = hashlib.sha256(p.read_bytes()).hexdigest()
                snap[str(p)] = h
    return snap


def _seed_repo_with_ledger_and_progress(tmp_path: Path) -> Path:
    """A repo that ALREADY has .ledger/ + progress/ (the hostile case — they must
    survive byte-identical)."""
    repo = tmp_path
    # source
    (repo / "svc").mkdir(parents=True)
    (repo / "svc" / "app.py").write_text("def handler():\n    return 1\n")
    (repo / "svc" / "main.py").write_text("if __name__ == '__main__':\n    handler()\n")
    (repo / "lib").mkdir()
    (repo / "lib" / "util.py").write_text("def helper():\n    return 2\n")
    # a SIGNED-looking contract-map + .sig under progress/ (the thing we must not touch)
    (repo / "progress").mkdir()
    (repo / "progress" / "contract-map.yaml").write_text(
        yaml.safe_dump({"schema_version": "1.0.0", "revision": 1,
                        "components": [{"id": "stale-comp", "source_paths": ["svc/*.py"]}]})
    )
    (repo / "progress" / "contract-map.yaml.sig").write_text("DEADBEEFSIGNATURE\n")
    # a pre-existing .ledger/
    (repo / ".ledger" / "requests").mkdir(parents=True)
    (repo / ".ledger" / "integration-ledger.md").write_text("# ledger\n")
    # git init
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    return repo


def test_cb4_ledger_and_progress_byte_identical(tmp_path: Path) -> None:
    repo = _seed_repo_with_ledger_and_progress(tmp_path)
    watched = [repo / ".ledger", repo / "progress"]
    before = _snapshot(watched)

    result = comprehension_run.orchestrate(
        repo,
        backend="fake",
        fake_yaml=_FAKE_INTENT_YAML,
        two_arm="skip",
        render=False,   # render tested separately (WP-6)
    )
    assert result["run_id"]

    after = _snapshot(watched)
    assert before == after, (
        "CB4 VIOLATION: .ledger/ or progress/ changed during a standalone run.\n"
        f"added/changed: {set(after) - set(before) | {k for k in before if before.get(k) != after.get(k)}}\n"
        f"removed: {set(before) - set(after)}"
    )


def test_cb4_specific_signed_map_untouched(tmp_path: Path) -> None:
    repo = _seed_repo_with_ledger_and_progress(tmp_path)
    cm = repo / "progress" / "contract-map.yaml"
    sig = repo / "progress" / "contract-map.yaml.sig"
    cm_hash_before = hashlib.sha256(cm.read_bytes()).hexdigest()
    sig_hash_before = hashlib.sha256(sig.read_bytes()).hexdigest()

    comprehension_run.orchestrate(repo, backend="fake", fake_yaml=_FAKE_INTENT_YAML,
                                  two_arm="skip", render=False)

    assert hashlib.sha256(cm.read_bytes()).hexdigest() == cm_hash_before
    assert hashlib.sha256(sig.read_bytes()).hexdigest() == sig_hash_before


def test_cb4_no_ledger_requests_created(tmp_path: Path) -> None:
    repo = _seed_repo_with_ledger_and_progress(tmp_path)
    comprehension_run.orchestrate(repo, backend="fake", fake_yaml=_FAKE_INTENT_YAML,
                                  two_arm="skip", render=False)
    # the pre-existing requests dir must remain empty (no transition requests emitted)
    reqs = list((repo / ".ledger" / "requests").glob("*"))
    assert reqs == [], f"standalone run must emit NO transition requests; found {reqs}"


def test_cb4_scratch_lands_under_comprehension(tmp_path: Path) -> None:
    repo = _seed_repo_with_ledger_and_progress(tmp_path)
    comprehension_run.orchestrate(repo, backend="fake", fake_yaml=_FAKE_INTENT_YAML,
                                  two_arm="skip", render=False)
    # the synthetic map + partition lock are under .comprehension/, not progress/
    assert (repo / ".comprehension" / "synthetic-contract-map.yaml").is_file()
    assert (repo / ".comprehension" / "partition.lock").is_file()
    assert not (repo / "progress" / "synthetic-contract-map.yaml").exists()
