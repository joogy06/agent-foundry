#!/usr/bin/env python3
"""test_component_resolver.py — unit tests for component_resolver."""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-extract-static"
sys.path.insert(0, str(_SKILL / "scripts"))

from component_resolver import ComponentResolver, make_resolver  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _scaffold_project(tmp: Path) -> Path:
    project = tmp / "proj"
    project.mkdir()
    (project / "app" / "auth").mkdir(parents=True)
    (project / "app" / "auth" / "validator.py").write_text("# ok\n")
    (project / "app" / "users" / "routes.py").parent.mkdir(parents=True, exist_ok=True)
    (project / "app" / "users" / "routes.py").write_text("# ok\n")
    (project / "app" / "extras" / "unmapped.py").parent.mkdir(parents=True, exist_ok=True)
    (project / "app" / "extras" / "unmapped.py").write_text("# ok\n")
    progress = project / "progress"
    progress.mkdir()
    cm = textwrap.dedent(
        """
        schema_version: "1.0.0"
        revision: 1
        components:
          - id: auth
            source_paths:
              - "app/auth/"
          - id: users
            source_paths:
              - "app/users/"
        """
    )
    (progress / "contract-map.yaml").write_text(cm)
    return project


def test_resolver_known_and_unmapped():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        project = _scaffold_project(td_path)
        resolver = make_resolver(project)
        assert resolver.rule_count() == 2
        assert resolver.resolve(project / "app" / "auth" / "validator.py") == "auth"
        assert resolver.resolve(project / "app" / "users" / "routes.py") == "users"
        assert resolver.resolve(project / "app" / "extras" / "unmapped.py") is None
        # Unmapped path is recorded
        assert any("unmapped.py" in p for p in resolver.unmapped_paths)


def test_resolver_missing_map_is_empty():
    with tempfile.TemporaryDirectory() as td:
        project = Path(td) / "proj"
        project.mkdir()
        resolver = make_resolver(project)
        assert resolver.rule_count() == 0
        assert resolver.resolve(project / "anywhere.py") is None


def test_resolver_home_prefix():
    """~ -prefixed globs resolve to the real home directory."""
    with tempfile.TemporaryDirectory() as td:
        project = Path(td) / "proj"
        progress = project / "progress"
        progress.mkdir(parents=True)
        cm = textwrap.dedent(
            """
            schema_version: "1.0.0"
            revision: 1
            components:
              - id: home-based
                source_paths:
                  - "~/.claude/skills/wiring-extract-static/scripts/"
            """
        )
        (progress / "contract-map.yaml").write_text(cm)
        resolver = make_resolver(project)
        sample = Path.home() / ".claude" / "skills" / "wiring-extract-static" / "scripts" / "run.py"
        assert resolver.resolve(sample) == "home-based"


def main():
    tests = [test_resolver_known_and_unmapped, test_resolver_missing_map_is_empty, test_resolver_home_prefix]
    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed.append(f"{t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"FAIL {len(failed)}/{len(tests)}")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    print(f"PASS {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
