#!/usr/bin/env python3
"""Tests for portability_lint + portable_cli — S076 (#249/#251).

Every rule is negative-controlled in BOTH directions: it fires on the real defect, and it
stays silent on the legitimate construct that looks like it. That is not ceremony here —
a linter nobody trusts gets bypassed, and this repo has twice shipped a guard that flagged
prose describing the pattern it was hunting (`pip` inside a help string; the `exists()`
inventory guard matching its own docstring). So `test_the_linter_lints_itself_clean` is the
single most important test in this file.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

META = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_pt_{name}", META / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


lint = _load("portability_lint")
pcli = _load("portable_cli")


def codes(source: str) -> list[str]:
    return [f.code for f in lint.check_source(Path("t.py"), source)]


# --------------------------------------------------------------------------
# P001 — unguarded platform-exclusive import
# --------------------------------------------------------------------------

def test_p001_fires_on_module_level_fcntl():
    assert "P001" in codes("import fcntl\n")


def test_p001_fires_on_from_import():
    assert "P001" in codes("from fcntl import flock\n")


def test_p001_fires_on_windows_only_module_too():
    """The rule is symmetric — a Windows-only import breaks Linux just as hard."""
    assert "P001" in codes("import msvcrt\n")


def test_p001_silent_when_guarded_by_try_except():
    assert "P001" not in codes(
        "try:\n    import fcntl\nexcept ImportError:\n    fcntl = None\n")


def test_p001_silent_when_deferred_into_a_function():
    """The real `model_policy.py:234` shape. The module still IMPORTS on Windows, so it
    is a different (milder) defect than the nine that die at import, and conflating them
    would misreport the severity of #249."""
    assert "P001" not in codes("def rotate():\n    import fcntl\n    return fcntl\n")


def test_p001_silent_when_branched_on_platform():
    assert "P001" not in codes(
        "import sys\nif sys.platform != 'win32':\n    import fcntl\n")


def test_p001_ignores_the_word_in_prose():
    """THE REGRESSION THAT MATTERS. A docstring naming the bad pattern is not the bad
    pattern — the exact false positive that has shipped here twice."""
    src = '"""Never write `import fcntl` at module level."""\nimport os\n'
    assert codes(src) == []


def test_p001_ignores_it_in_a_comment():
    assert codes("# import fcntl  <- do not do this\nimport os\n") == []


def test_p001_ignores_it_inside_a_string_literal():
    assert codes("BAD = 'import fcntl'\n") == []


# --------------------------------------------------------------------------
# P002 — text I/O without an explicit encoding
# --------------------------------------------------------------------------

def test_p002_fires_on_write_text_without_encoding():
    assert "P002" in codes("p.write_text(x)\n")


def test_p002_fires_on_read_text_without_encoding():
    assert "P002" in codes("p.read_text()\n")


def test_p002_silent_with_explicit_encoding():
    assert "P002" not in codes("p.write_text(x, encoding='utf-8')\n")


def test_p002_fires_on_text_mode_open():
    assert "P002" in codes("f = open(path)\n")


def test_p002_silent_on_binary_open():
    """Binary mode has no codec to get wrong — flagging it would be noise, and noise is
    how a linter teaches people to ignore it."""
    assert "P002" not in codes("f = open(path, 'rb')\n")
    assert "P002" not in codes("f = open(path, mode='wb')\n")


def test_p002_silent_on_open_with_encoding():
    assert "P002" not in codes("f = open(path, 'r', encoding='utf-8')\n")


def test_p002_catches_the_real_244_shape():
    """#244 exactly: the write that used cp1252, raised, and left a 0-byte file."""
    found = lint.check_source(Path("install.py"), "target.write_text(COPILOT_AGENTS_MD)\n")
    assert [f.code for f in found] == ["P002"]
    assert "LOCALE" in found[0].message


# --------------------------------------------------------------------------
# P003 — an entrypoint that can emit non-ASCII without hardening its streams
# --------------------------------------------------------------------------

ENTRY = 'if __name__ == "__main__":\n    raise SystemExit(main())\n'


def test_p003_fires_on_unhardened_entrypoint_emitting_non_ascii():
    src = 'def main():\n    print("\\N{BRAIN}")\n' + ENTRY
    assert "P003" in codes(src)


def test_p003_silent_when_hardened():
    src = ('from portable_cli import run_cli\n'
           'def main():\n    print("\\N{BRAIN}")\n'
           'if __name__ == "__main__":\n    raise SystemExit(run_cli(main))\n')
    assert "P003" not in codes(src)


def test_p003_silent_when_module_is_pure_ascii():
    """No non-ASCII to emit means no cp1252 failure to have. Flagging all 223 entrypoints
    would bury the ~190 that genuinely can fail."""
    src = 'def main():\n    print("plain")\n' + ENTRY
    assert "P003" not in codes(src)


def test_p003_ignores_non_ascii_in_a_comment():
    """A comment cannot reach stdout. This is the AST-vs-regex distinction, tested."""
    src = 'def main():\n    # the digest prints \u2192 here\n    print("ok")\n' + ENTRY
    assert "P003" not in codes(src)


def test_p003_counts_the_module_docstring():
    """argparse routinely passes __doc__ as description=, so a docstring IS printed
    output on --help. This is not over-reach; it is the `scan_hard_rules` failure."""
    src = '"""Digest \u2192 output."""\ndef main():\n    pass\n' + ENTRY
    assert "P003" in codes(src)


def test_p003_silent_without_an_entrypoint():
    """A library module's strings are the caller's problem to print safely."""
    assert "P003" not in codes('X = "\u2192"\n')


# --------------------------------------------------------------------------
# Self-check and inventory
# --------------------------------------------------------------------------

def test_the_linter_lints_itself_clean():
    """Its docstring names `import fcntl`, `write_text()` without encoding, and quotes a
    cp1252 failure. If the rules matched text rather than the parsed tree, this fails."""
    assert lint.check_path(META / "portability_lint.py") == []


def test_portable_cli_lints_clean_despite_holding_the_emoji():
    """portable_cli's docstring contains the exact character that crashes Windows."""
    assert lint.check_path(META / "portable_cli.py") == []


def test_syntax_error_is_reported_not_swallowed():
    found = lint.check_source(Path("bad.py"), "def (\n")
    assert found and found[0].code == "P000" and found[0].severity == "E"


def test_known_fcntl_inventory_is_now_empty():
    """A #239-style inventory guard, re-pinned 9 -> 0 when #249 was fixed.

    It fails when the count MOVES IN EITHER DIRECTION, and both directions have now
    happened. Upward means a new unimportable module shipped. Downward meant #249
    progressed -- the nine modules moved to portable_lock -- and the guard refused to
    go quiet about it, which is the behaviour that forced this number to be lowered
    deliberately instead of drifting. Zero is the value that makes it a REGRESSION
    detector from here: any new unguarded platform import at module level fails this,
    not just an increase over some tolerated backlog.
    """
    skills = META.parent
    hits = [f for p in lint.iter_python(skills) for f in lint.check_path(p)
            if f.code == "P001"]
    assert len(hits) == 0, (
        f"#249 regressed: {len(hits)} module(s) import a platform-only module "
        f"unguarded at module level, so they die at IMPORT on the wrong OS: "
        f"{sorted(str(f.path) for f in hits)}")


# --------------------------------------------------------------------------
# portable_cli
# --------------------------------------------------------------------------

def test_make_streams_utf8_reports_how_many_it_hardened():
    import io
    s1, s2 = io.TextIOWrapper(io.BytesIO()), io.TextIOWrapper(io.BytesIO())
    assert pcli.make_streams_utf8([s1, s2]) == 2
    assert s1.encoding == "utf-8"


def test_make_streams_utf8_tolerates_a_stream_without_reconfigure():
    """pytest's capture and StringIO have no reconfigure. That is not an error."""
    import io
    assert pcli.make_streams_utf8([io.StringIO()]) == 0


def test_run_cli_normalises_a_none_return_to_zero():
    assert pcli.run_cli(lambda: None) == 0


def test_run_cli_passes_through_an_exit_code():
    assert pcli.run_cli(lambda: 2) == 2


def test_backslashreplace_keeps_the_character_identifiable():
    """Why not errors='replace': both survive, only one leaves evidence. 'replace' gives
    '?', which cannot be traced back to the site that produced it."""
    assert "\U0001f9e0".encode("cp1252", errors="backslashreplace") == b"\\U0001f9e0"
    assert "\U0001f9e0".encode("cp1252", errors="replace") == b"?"


def test_inline_stream_hardening_counts_as_hardened():
    """A standalone script that cannot import portable_cli must still be able to
    satisfy W003 by hardening inline — otherwise the rule flags its own correct fix.

    Written after W003 fired on `vs-code/scripts/render_handles.py`, which hardens
    with `sys.stdout.reconfigure(...)` because it is meant to run on a laptop where
    the harness may not be installed. A lint that cannot see a correct fix trains
    people to ignore it, which is the rule this repo already applies to the secrets
    scanner's fake-password allowlist.
    """
    src = (
        "import sys\n"
        "def main():\n"
        "    print('em dash — here')\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    for s in (sys.stdout, sys.stderr):\n"
        "        s.reconfigure(encoding='utf-8', errors='backslashreplace')\n"
        "    raise SystemExit(main())\n"
    )
    found = [f for f in lint.check_source(Path("inline.py"), src) if f.code == "P003"]
    assert found == [], f"inline hardening was not recognised: {found}"


def test_an_UNHARDENED_entrypoint_emitting_non_ascii_is_still_flagged():
    """The negative control for the line above: widening HARDENERS must not have
    switched the rule off."""
    src = (
        "def main():\n"
        "    print('em dash — here')\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )
    found = [f for f in lint.check_source(Path("bare.py"), src) if f.code == "P003"]
    assert len(found) == 1, f"W003 no longer fires on an unhardened entrypoint: {found}"
