"""Codex review C5: the large-file chunk recipe reports incomplete coverage. Runs the recipe as
shipped against a stub agy, so no model is called."""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "large-file-analysis" / "SKILL.md"
_POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX shell recipe")

#: The stub answers, except for a chunk holding FAIL (exit 1) or SILENT (exit 0, no output: a no-show).
STUB = """#!/usr/bin/env bash
for a in "$@"; do last="$a"; done
pwd >> "$STUB_LOG"
case "$last" in
  *FAIL*) exit 1 ;;
  *SILENT*) exit 0 ;;
esac
echo "analysis"
"""


def _recipe(path: Path) -> str:
    text = SKILL.read_text(encoding="utf-8")
    block = next(b for b in re.findall(r"```bash\n(.*?)```", text, re.S) if "split -C 100000" in b)
    lines = block.splitlines()
    assert lines[0].startswith("AGY_MODEL=")
    return "\n".join(['AGY_MODEL="--model stub"'] + lines[1:]).replace("/path/to/file", str(path)) + "\n"


def _run(tmp_path, content, *extra_bins):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("agy", STUB), *extra_bins):
        f = bindir / name
        f.write_text(body, encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    big = tmp_path / "big.txt"
    big.write_text(content, encoding="utf-8")
    log = tmp_path / "log"
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", STUB_LOG=str(log))
    p = subprocess.run(["bash", "-c", _recipe(big)], env=env, capture_output=True, text=True, timeout=60)
    return p, log


FILL = "alpha line\n" * 12000          # 132 KB: two chunks


@_POSIX
def test_a_clean_run_exits_0(tmp_path):
    p, log = _run(tmp_path, FILL)
    assert p.returncode == 0 and p.stdout.count("analysis") == 2 and "INCOMPLETE" not in p.stderr
    assert len(log.read_text().splitlines()) == 2


@_POSIX
def test_a_failed_chunk_exits_non_zero_and_is_named(tmp_path):
    p, _log = _run(tmp_path, FILL + "FAIL\n")
    assert p.returncode != 0
    assert "INCOMPLETE: no analysis of chunks: ab" in p.stderr      # the second chunk


@_POSIX
def test_a_no_show_counts_as_a_failed_chunk(tmp_path):
    p, _log = _run(tmp_path, "SILENT\n" + FILL)
    assert p.returncode != 0
    assert "INCOMPLETE: no analysis of chunks: aa" in p.stderr      # the first chunk


@_POSIX
def test_a_failed_read_skips_agy_for_that_chunk_and_continues(tmp_path):
    """Re-review major: a failed `cat` used to send its partial output to agy and exit 0."""
    fail_on_ab = '#!/bin/sh\ncase "$1" in *chunk.ab) echo PARTIAL; exit 1 ;; esac\nexec /bin/cat "$@"\n'
    p, log = _run(tmp_path, FILL + "x\n" * 200 + FILL, ("cat", fail_on_ab))
    assert p.returncode != 0
    assert "INCOMPLETE: no analysis of chunks: ab" in p.stderr
    assert len(log.read_text().splitlines()) == 2                  # chunks aa and ac only
    assert "PARTIAL" not in p.stdout


@_POSIX
@pytest.mark.parametrize("rel,blocked", [
    ("skills/codex-orchestration/references/agy-patterns.md", "/tmp/codex-"),
    ("skills/codex-orchestration/references/agy-patterns.md", "/tmp/agy-"),
    ("skills/claude-code-cli/references/cross-tool-integration.md", "/tmp/codex-"),
    ("skills/research-for-skills/SKILL.md", "/tmp/codex-"),
])
def test_each_shipped_allocation_stops_the_recipe_alone(tmp_path, rel, blocked):
    """Each allocation fails on its own, the others succeed, and nothing after it runs."""
    text = (Path(__file__).resolve().parents[3] / rel).read_text(encoding="utf-8")
    lines = [m for m in re.findall(r"^\w+=\$\(mktemp .*$", text, re.M) if blocked in m]
    assert lines and all(ln.endswith("|| exit 1") for ln in lines)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "mktemp"
    stub.write_text(f'#!/bin/sh\ncase "$*" in *{blocked}*) exit 1 ;; esac\nexec /usr/bin/mktemp "$@"\n', encoding="utf-8")
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}")
    p = subprocess.run(["bash", "-c", lines[0] + "\necho REACHED\n"], env=env, capture_output=True, text=True, timeout=20)
    assert p.returncode != 0 and "REACHED" not in p.stdout


@_POSIX
def test_a_failed_mktemp_makes_no_agy_call(tmp_path):
    p, log = _run(tmp_path, FILL, ("mktemp", "#!/bin/sh\nexit 1\n"))
    assert p.returncode != 0
    assert not log.exists()


@_POSIX
def test_each_chunk_runs_from_its_own_empty_directory(tmp_path):
    _p, log = _run(tmp_path, FILL)
    dirs = log.read_text().splitlines()
    assert len(set(dirs)) == 2 and all(not os.listdir(d) for d in dirs)
