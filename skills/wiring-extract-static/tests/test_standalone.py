"""WP-4 — tests for wiring-extract-static --standalone + --contract-map-path +
canonical-inventory resolver (code-comprehension).

CB4-critical properties:
  - --standalone needs NO claim, writes NO .ledger/, constructs NO heartbeat
  - --standalone creates the wiring root itself (orchestrator-as-single-creator)
  - --contract-map-path none => NullResolver (no progress/ fallback)
  - --contract-map-path <synthetic> => canonical-inventory (source_files) resolution
  - the normal path is unchanged (claim still required without --standalone)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import component_resolver  # noqa: E402
import run  # noqa: E402


# ---------------------------------------------------------------------------
# component_resolver — canonical inventory (C5)
# ---------------------------------------------------------------------------


def _write_map(path: Path, components: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"schema_version": "1.0.0", "components": components}))


def test_canonical_inventory_resolves_exact_file(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    f = tmp_path / "pkg" / "a.py"
    f.write_text("x=1\n")
    mp = tmp_path / "synthetic.yaml"
    _write_map(mp, [{"id": "pkg", "source_paths": ["pkg/**"], "source_files": ["pkg/a.py"]}])
    r = component_resolver.ComponentResolver(mp, tmp_path)
    assert r.resolve(f) == "pkg"


def test_canonical_inventory_takes_precedence_over_glob(tmp_path: Path) -> None:
    # file is in comp-A's canonical inventory but comp-B's glob would also match;
    # canonical inventory must win.
    (tmp_path / "shared").mkdir()
    f = tmp_path / "shared" / "x.py"
    f.write_text("x=1\n")
    mp = tmp_path / "synthetic.yaml"
    _write_map(mp, [
        {"id": "comp-A", "source_paths": [], "source_files": ["shared/x.py"]},
        {"id": "comp-B", "source_paths": ["shared/**"], "source_files": []},
    ])
    r = component_resolver.ComponentResolver(mp, tmp_path)
    assert r.resolve(f) == "comp-A"


def test_real_map_without_source_files_uses_globs(tmp_path: Path) -> None:
    # a real signed map has no source_files key → glob behavior is byte-identical
    (tmp_path / "src" / "auth").mkdir(parents=True)
    f = tmp_path / "src" / "auth" / "r.py"
    f.write_text("x=1\n")
    mp = tmp_path / "progress" / "contract-map.yaml"
    _write_map(mp, [{"id": "auth", "source_paths": ["src/auth/*.py"]}])
    r = component_resolver.ComponentResolver(mp, tmp_path)
    assert r.resolve(f) == "auth"


def test_null_resolver_maps_nothing(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x=1\n")
    r = component_resolver.make_resolver_for_path(tmp_path, "none")
    assert r.resolve(f) is None
    assert str(f.resolve()) in r.unmapped_paths


def test_make_resolver_for_path_none_does_not_read_progress(tmp_path: Path) -> None:
    # Even if a progress/contract-map.yaml exists, 'none' must ignore it.
    (tmp_path / "pkg").mkdir()
    f = tmp_path / "pkg" / "a.py"
    f.write_text("x=1\n")
    _write_map(tmp_path / "progress" / "contract-map.yaml",
               [{"id": "pkg", "source_paths": ["pkg/**"]}])
    r = component_resolver.make_resolver_for_path(tmp_path, "none")
    assert r.resolve(f) is None, "'none' must NOT fall back to progress/contract-map.yaml"


# ---------------------------------------------------------------------------
# run.py --standalone
# ---------------------------------------------------------------------------

import uuid as _uuid  # noqa: E402


def _seed_repo(tmp_path: Path) -> Path:
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "app.py").write_text(
        "def handler():\n    return 1\n"
    )
    # make it a git repo so git write-tree works
    import subprocess
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    return tmp_path


def test_standalone_runs_without_claim_no_ledger(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    run_id = str(_uuid.uuid4())
    wiring_root = repo / ".comprehension" / ".wiring"
    rc = run.main([
        "--project-dir", str(repo),
        "--run-id", run_id,
        "--standalone",
        "--contract-map-path", "none",
        "--wiring-root", str(wiring_root),
    ])
    assert rc == 0
    # CB4: nothing under .ledger/
    assert not (repo / ".ledger").exists()
    # the orchestrator-owned wiring root was created + populated
    assert (wiring_root / "runs" / run_id / "static.jsonl").is_file()


def test_standalone_creates_wiring_root_itself(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    run_id = str(_uuid.uuid4())
    wiring_root = repo / ".comprehension" / ".wiring"
    assert not wiring_root.exists()
    rc = run.main([
        "--project-dir", str(repo),
        "--run-id", run_id,
        "--standalone",
        "--contract-map-path", "none",
        "--wiring-root", str(wiring_root),
    ])
    assert rc == 0
    assert wiring_root.is_dir(), "orchestrator/standalone must create the wiring root"


def test_standalone_never_constructs_heartbeat(tmp_path: Path, monkeypatch) -> None:
    repo = _seed_repo(tmp_path)
    constructed = {"n": 0}
    real_init = run.HeartbeatThread.__init__

    def spy_init(self, *a, **k):  # noqa: ANN001
        constructed["n"] += 1
        return real_init(self, *a, **k)

    monkeypatch.setattr(run.HeartbeatThread, "__init__", spy_init)
    run_id = str(_uuid.uuid4())
    rc = run.main([
        "--project-dir", str(repo),
        "--run-id", run_id,
        "--standalone",
        "--contract-map-path", "none",
        "--wiring-root", str(repo / ".comprehension" / ".wiring"),
    ])
    assert rc == 0
    assert constructed["n"] == 0, "HeartbeatThread must NEVER be constructed in --standalone"


def test_normal_mode_still_requires_claim(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    (repo / ".wiring").mkdir()
    rc = run.main([
        "--project-dir", str(repo),
        "--run-id", str(_uuid.uuid4()),
    ])
    assert rc == 1, "normal mode must still require --claim-uuid"


def test_standalone_with_synthetic_map_resolves_components(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    synthetic = repo / ".comprehension" / "synthetic-contract-map.yaml"
    _write_map(synthetic, [
        {"id": "svc", "source_paths": ["svc/**"], "source_files": ["svc/app.py"]}
    ])
    run_id = str(_uuid.uuid4())
    rc = run.main([
        "--project-dir", str(repo),
        "--run-id", run_id,
        "--standalone",
        "--contract-map-path", str(synthetic),
        "--wiring-root", str(repo / ".comprehension" / ".wiring"),
    ])
    assert rc == 0
    # no contract_map_hash from the stale progress/ map (there is none here anyway),
    # and the run produced a manifest
    manifest = repo / ".comprehension" / ".wiring" / "runs" / run_id / "manifest.json"
    assert manifest.is_file()
