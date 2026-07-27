"""G_CLAIM_FRESHNESS gate contract tests.

The decay this gate blocks was observed live on 2026-07-26: the same `FAQPage`
fact lived in three skills in three states of staleness, and a full manual
review caught only one of them.

Contract:
  exit 0 = no contradiction, OR advisory mode (never blocks)
  exit 2 = contradicting verdicts found, strict mode
  exit 3 = environmental (linter missing / broken / bad args)

Key invariant: a BROKEN linter must escalate (3), never be read as "clean" (0).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parent.parent / "gates.py"


def _skill(root: Path, name: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: fixture\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATES), "G_CLAIM_FRESHNESS", *args],
        capture_output=True, text=True, timeout=180,
    )


@pytest.fixture()
def agreeing(tmp_path: Path) -> Path:
    root = tmp_path / "agree"
    _skill(root, "alpha", "| `FooSchema` | deprecated May 2026, removed from search |")
    _skill(root, "beta", "| `FooSchema` | deprecated — removed, keep markup only |")
    return root


@pytest.fixture()
def contradicting(tmp_path: Path) -> Path:
    root = tmp_path / "clash"
    _skill(root, "alpha", "| `FooSchema` | deprecated May 2026, removed from search |")
    _skill(root, "beta", "| `FooSchema` | CRITICAL — still supported, implement everywhere |")
    return root


def test_agreeing_passes_advisory(agreeing: Path) -> None:
    assert _run(str(agreeing)).returncode == 0


def test_agreeing_passes_strict(agreeing: Path) -> None:
    """Duplication alone must NEVER block — only contradiction does."""
    r = _run(str(agreeing), "--claim-mode", "strict")
    assert r.returncode == 0, r.stdout + r.stderr


def test_contradiction_does_not_block_in_advisory(contradicting: Path) -> None:
    r = _run(str(contradicting))
    assert r.returncode == 0
    assert "drift detected" in r.stdout


def test_contradiction_blocks_in_strict(contradicting: Path) -> None:
    r = _run(str(contradicting), "--claim-mode", "strict")
    assert r.returncode == 2
    assert "G_CLAIM_FRESHNESS_FAIL" in r.stderr


def test_contradiction_report_names_both_owners(contradicting: Path) -> None:
    """A drift report is useless if it does not say WHERE the fact lives."""
    out = _run(str(contradicting), "--claim-mode", "strict").stdout
    assert "FooSchema" in out
    assert "alpha" in out and "beta" in out


def test_invalid_mode_is_environmental() -> None:
    assert _run("--claim-mode", "banana").returncode == 3


def test_missing_skills_root_is_environmental(tmp_path: Path) -> None:
    assert _run(str(tmp_path / "nope")).returncode == 3


def test_broken_linter_escalates_never_silently_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A linter that crashes must exit 3 — reading it as 'clean' would make the
    gate silently useless, which is worse than not having it."""
    sys.path.insert(0, str(GATES.parent))
    import gates  # type: ignore

    broken = tmp_path / "broken_lint.py"
    broken.write_text("import sys\nsys.exit(42)\n", encoding="utf-8")
    monkeypatch.setattr(gates, "_g_claim_freshness_linter", lambda: broken)

    root = tmp_path / "skills"
    _skill(root, "alpha", "| `FooSchema` | deprecated |")

    with pytest.raises(SystemExit) as exc:
        gates.check_G_CLAIM_FRESHNESS(root, mode="strict")
    assert exc.value.code == 3


def test_absent_linter_escalates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(GATES.parent))
    import gates  # type: ignore

    monkeypatch.setattr(gates, "_g_claim_freshness_linter", lambda: None)
    with pytest.raises(SystemExit) as exc:
        gates.check_G_CLAIM_FRESHNESS(tmp_path, mode="advisory")
    assert exc.value.code == 3


def test_linter_is_locatable_from_this_checkout() -> None:
    """Guards the repo-vs-home path bug: gates.py runs from both trees, but only
    the live tree carries domain skills."""
    sys.path.insert(0, str(GATES.parent))
    import gates  # type: ignore

    found = gates._g_claim_freshness_linter()
    assert found is not None and found.is_file()
