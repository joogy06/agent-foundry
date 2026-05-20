"""Regression tests for manifests.py — gitignore-respecting discovery (S035).

These 10 tests cover the fail-open bug fix in `_walk_for_manifests`. Mirrors
the pytest + tmp_path + real `git init` pattern of `test_manifests.py`.
Test 10 is the perf smoke test, marked @pytest.mark.slow and skipped by default.

See docs/plans/2026-05-20-dep-currency-gitignore-fix-design.md §5.4 for the
table this file implements 1-to-1.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from dep_currency_check import manifests as _manifests_mod
from dep_currency_check.manifests import (
    _enumerate_via_git,
    _gitignored_paths,
    _walk_for_manifests,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(root: Path, *, set_safe_dir: bool = False) -> None:
    """Initialize a git repo at root with a deterministic config."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _git_add_commit(root: Path, message: str = "init") -> None:
    """Stage all + commit. Lets us mark files as 'tracked' for the tests."""
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, check=True)


def _write(p: Path, content: str = "{}") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _rel(paths, root: Path) -> set:
    """Return relative paths as POSIX strings for assertion comparison."""
    return {p.relative_to(root).as_posix() for p in paths}


# ---------------------------------------------------------------------------
# Test 1 — Sub-path gitignore (THE bug)
# ---------------------------------------------------------------------------


def test_subpath_gitignore_does_not_poison_parent(tmp_path: Path):
    """git ls-files output `app/logs/x.log` previously poisoned `app/` into the
    skip set, hiding the tracked `app/requirements.txt`. With Option E,
    `app/requirements.txt` is enumerated by `git ls-files --cached`."""
    _git_init(tmp_path)
    _write(tmp_path / ".gitignore", "app/logs/\n")
    _write(tmp_path / "app" / "requirements.txt", "requests==2.28.0\n")
    _write(tmp_path / "app" / "logs" / "server.log", "log data\n")
    _git_add_commit(tmp_path)

    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert "app/requirements.txt" in rels, (
        f"Expected app/requirements.txt in result; got {rels}"
    )
    # The .log file is not a manifest by name, so it shouldn't appear anyway,
    # but let's also assert it's not there.
    assert "app/logs/server.log" not in rels


# ---------------------------------------------------------------------------
# Test 2 — v3-shaped fixture (the original real-world repro)
# ---------------------------------------------------------------------------


def test_v3_shaped_fixture_finds_both_manifests(tmp_path: Path):
    """Mirrors smart-analyst-platform-v3: app_deploy/{logs,data,uploads,staging}/
    are gitignored sub-paths, but app_deploy/requirements.txt and a deep
    package.json are tracked manifests. Both must be found."""
    _git_init(tmp_path)
    _write(
        tmp_path / ".gitignore",
        "app_deploy/logs/\napp_deploy/data/\n"
        "app_deploy/uploads/\napp_deploy/staging/\n",
    )
    _write(tmp_path / "app_deploy" / "requirements.txt", "idna==3.4\n")
    _write(
        tmp_path / "app_deploy" / "src" / "products" / "dlp" / "web"
        / "spa" / "lineage-v3" / "package.json",
        '{"name":"lineage-v3","dependencies":{"ws":"8.18.0"}}\n',
    )
    # Add some ignored noise — these must NOT poison the parent.
    _write(tmp_path / "app_deploy" / "logs" / "server.log", "noise\n")
    _write(tmp_path / "app_deploy" / "data" / "cache.bin", "noise\n")
    _git_add_commit(tmp_path)

    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert "app_deploy/requirements.txt" in rels, (
        f"Expected app_deploy/requirements.txt; got {sorted(rels)}"
    )
    assert any(
        "lineage-v3/package.json" in s for s in rels
    ), f"Expected lineage-v3/package.json; got {sorted(rels)}"


# ---------------------------------------------------------------------------
# Test 3 — Custom ignored top-level dir
# ---------------------------------------------------------------------------


def test_custom_ignored_toplevel_dir_skipped(tmp_path: Path):
    """If `generated/` is in .gitignore and `generated/package.json` is
    untracked, git won't list it via `--others --exclude-standard` — so we
    must NOT find it. Demonstrates that custom gitignore entries still work."""
    _git_init(tmp_path)
    _write(tmp_path / ".gitignore", "generated/\n")
    _write(tmp_path / "generated" / "package.json", '{"name":"gen"}\n')
    _write(tmp_path / "real" / "package.json", '{"name":"real"}\n')
    _git_add_commit(tmp_path)

    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert "real/package.json" in rels
    assert "generated/package.json" not in rels, (
        f"generated/ is in .gitignore; should not be discovered. Got {sorted(rels)}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Tracked-then-ignored (Option E's key advantage over Option D)
# ---------------------------------------------------------------------------


def test_tracked_then_ignored_still_found(tmp_path: Path):
    """A manifest that was committed BEFORE its parent was added to .gitignore
    remains tracked in git. git ls-files --cached lists it, so we must still
    find it. This is what Option D would have missed."""
    _git_init(tmp_path)
    # Step 1: commit a manifest while it is NOT ignored.
    _write(tmp_path / "generated" / "package.json", '{"name":"gen"}\n')
    _git_add_commit(tmp_path, message="track manifest")
    # Step 2: now add `generated/` to .gitignore + commit.
    _write(tmp_path / ".gitignore", "generated/\n")
    _git_add_commit(tmp_path, message="ignore generated dir")

    # `generated/package.json` is STILL tracked despite being in .gitignore.
    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert "generated/package.json" in rels, (
        f"Tracked manifest must still appear even when parent is in .gitignore. "
        f"Got {sorted(rels)}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Nested .gitignore
# ---------------------------------------------------------------------------


def test_nested_gitignore_honored(tmp_path: Path):
    """Nested .gitignore in apps/ ignores apps/cache/. The untracked
    apps/cache/package.json must NOT be found; the untracked apps/package.json
    (not ignored) must be found."""
    _git_init(tmp_path)
    # Root .gitignore is empty.
    _write(tmp_path / ".gitignore", "")
    _write(tmp_path / "apps" / ".gitignore", "cache/\n")
    _write(tmp_path / "apps" / "package.json", '{"name":"apps"}\n')
    _write(tmp_path / "apps" / "cache" / "package.json",
           '{"name":"cache"}\n')
    # Commit ONLY the .gitignores so the package.json files are "untracked"
    # — which is what test 5 wants per design.
    subprocess.run(["git", "add", ".gitignore", "apps/.gitignore"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "ignores"],
                   cwd=tmp_path, check=True)

    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert "apps/package.json" in rels
    assert "apps/cache/package.json" not in rels, (
        f"Nested .gitignore must hide apps/cache/. Got {sorted(rels)}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Static-skip preserved (non-git tree)
# ---------------------------------------------------------------------------


def test_static_skip_in_non_git_tree(tmp_path: Path):
    """No `git init`. _enumerate_via_git returns None; the rglob fallback
    must still apply static skip dirs so node_modules/foo/package.json is
    not picked up."""
    _write(tmp_path / "package.json", '{"name":"root"}\n')
    _write(tmp_path / "node_modules" / "foo" / "package.json",
           '{"name":"foo"}\n')

    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert rels == {"package.json"}, (
        f"node_modules/ must be skipped in rglob fallback. Got {sorted(rels)}"
    )


# ---------------------------------------------------------------------------
# Test 7 — Static-skip preserved (in-git, untracked, node_modules NOT in
# .gitignore — git WOULD list it)
# ---------------------------------------------------------------------------


def test_static_skip_in_git_tree_even_when_not_gitignored(tmp_path: Path):
    """If a user accidentally tracked node_modules/, git would list it via
    --cached/--others, but the static-skip post-filter on the git path must
    still drop it. Documents design decision §5.2 / §5.4 test 7."""
    _git_init(tmp_path)
    # Empty .gitignore — so node_modules/ is NOT gitignored.
    _write(tmp_path / ".gitignore", "")
    _write(tmp_path / "package.json", '{"name":"root"}\n')
    _write(tmp_path / "node_modules" / "foo" / "package.json",
           '{"name":"foo"}\n')
    _git_add_commit(tmp_path)

    # Verify the test setup: git WOULD list node_modules/foo/package.json
    # via --cached, so the static-skip filter is what saves us.
    git_listed = _enumerate_via_git(tmp_path)
    git_rel = {p.relative_to(tmp_path).as_posix() for p in (git_listed or [])}
    assert "node_modules/foo/package.json" in git_rel, (
        "Test setup invariant: git should list node_modules/foo/package.json "
        f"(it isn't gitignored). Got {sorted(git_rel)}"
    )

    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert rels == {"package.json"}, (
        f"Static-skip filter must still drop node_modules/ on git-enum path. "
        f"Got {sorted(rels)}"
    )


# ---------------------------------------------------------------------------
# Test 8 — Git timeout / error → degraded scan
# ---------------------------------------------------------------------------


def test_git_timeout_triggers_degraded_scan(tmp_path: Path):
    """When .git/ exists but `subprocess.run` raises TimeoutExpired, we
    should fall back to rglob and set _LAST_SCAN_DEGRADED + _LAST_SCAN_REASON
    so the CLI can surface a meta.degraded advisory."""
    _git_init(tmp_path)
    _write(tmp_path / "package.json", '{"name":"root"}\n')
    _git_add_commit(tmp_path)

    # Mock subprocess.run inside manifests module to raise TimeoutExpired.
    with patch(
        "dep_currency_check.manifests.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15),
    ):
        found = _walk_for_manifests(tmp_path)

    # Fallback rglob result must still find the manifest.
    rels = _rel(found, tmp_path)
    assert "package.json" in rels, (
        f"Timeout fallback must still find manifests via rglob. Got {sorted(rels)}"
    )
    # Degraded advisory must be set.
    assert _manifests_mod._LAST_SCAN_DEGRADED is True, (
        "Timeout with .git/ present must set _LAST_SCAN_DEGRADED"
    )
    assert _manifests_mod._LAST_SCAN_REASON is not None
    assert "timed out" in _manifests_mod._LAST_SCAN_REASON.lower(), (
        f"_LAST_SCAN_REASON should mention timeout; got "
        f"{_manifests_mod._LAST_SCAN_REASON!r}"
    )


def test_no_git_dir_does_not_degrade(tmp_path: Path):
    """A non-git tree (no .git/) is NOT a degraded scan — it's just no-git
    mode. The advisory flags must remain False/None after the walk."""
    _write(tmp_path / "package.json", '{"name":"root"}\n')

    found = _walk_for_manifests(tmp_path)
    assert "package.json" in _rel(found, tmp_path)
    assert _manifests_mod._LAST_SCAN_DEGRADED is False
    assert _manifests_mod._LAST_SCAN_REASON is None


# ---------------------------------------------------------------------------
# Test 9 — Filenames with spaces / `#` / weird chars (NUL-separated parsing)
# ---------------------------------------------------------------------------


def test_filenames_with_spaces_and_specials(tmp_path: Path):
    """git ls-files -z uses NUL separators so paths with spaces, `#`, or
    even newlines survive parsing. Plain `\n`-split would have broken this."""
    _git_init(tmp_path)
    weird = tmp_path / "weird name #1"
    _write(weird / "package.json", '{"name":"weird"}\n')
    _git_add_commit(tmp_path)

    found = _walk_for_manifests(tmp_path)
    rels = _rel(found, tmp_path)
    assert "weird name #1/package.json" in rels, (
        f"Spaces and # in path must survive -z parsing. Got {sorted(rels)}"
    )


# ---------------------------------------------------------------------------
# Test 10 — Performance smoke (10k files) — slow, skipped by default
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("RUN_SLOW_TESTS") != "1",
    reason="perf smoke test; set RUN_SLOW_TESTS=1 to enable",
)
def test_perf_10k_files_under_2s(tmp_path: Path):
    """Create 10k empty noise files + 5 real manifests in a git repo. The
    git-enum path must complete the walk in under 2s. With the old rglob+
    poisoned-skip walker, this would have walked all 10k files; the new
    git-enum path enumerates from the index instead."""
    _git_init(tmp_path)
    # 10k noise files spread across 100 directories.
    for i in range(100):
        d = tmp_path / "noise" / f"d{i:03d}"
        d.mkdir(parents=True, exist_ok=True)
        for j in range(100):
            (d / f"f{j:03d}.txt").write_text("x")
    # 5 real manifests.
    _write(tmp_path / "package.json", '{"name":"root"}\n')
    _write(tmp_path / "service-a" / "requirements.txt", "")
    _write(tmp_path / "service-b" / "go.mod", "module x\n")
    _write(tmp_path / "service-c" / "Cargo.toml", '[package]\nname="c"\n')
    _write(tmp_path / "service-d" / "Gemfile", "")
    _git_add_commit(tmp_path)

    t0 = time.monotonic()
    found = _walk_for_manifests(tmp_path)
    elapsed = time.monotonic() - t0

    rels = _rel(found, tmp_path)
    assert "package.json" in rels
    assert "service-a/requirements.txt" in rels
    assert "service-b/go.mod" in rels
    assert "service-c/Cargo.toml" in rels
    assert "service-d/Gemfile" in rels
    assert elapsed < 2.0, (
        f"Walk took {elapsed:.2f}s on 10k files; expected <2s with git-enum path."
    )
