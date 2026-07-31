#!/usr/bin/env python3
"""portable_cli.py — S076 (#251). One place that makes a CLI survive a non-UTF-8 console.

Python's stdout on a Windows console uses the LOCALE codec — cp1252 on the machines we
run on. Any non-ASCII byte then raises `UnicodeEncodeError`, and the observed failure is
not a crash the user can read: `_meta/memory_primer.py` prints `🧠`, dies, and **exits 0
with no output**, so the SessionStart digest simply never appears on Windows and looks
exactly like a session with nothing to report.

Its own error handler printed `🧠` too, so the message announcing the failure also failed.
That is the shape this module exists to make impossible.

`errors="backslashreplace"`, NOT `"replace"`. Both stop the crash; only one keeps the
missing character identifiable afterwards. `replace` turns `🧠` into `?` and destroys the
evidence needed to find the site — and finding the site is the entire point of surviving.

Reconfiguring the STREAM is the fix; `PYTHONUTF8=1` in a spawned environment is defence in
depth. A stream that has already been wrapped (pytest's capture, a pipe) may not offer
`reconfigure`, so its absence is not an error.

    from portable_cli import run_cli
    if __name__ == "__main__":
        raise SystemExit(run_cli(main))

Stdlib only. Importing this module has no side effects — the reconfiguration happens in
`run_cli`, so importing it inside a test never mutates the test runner's streams.
"""
from __future__ import annotations

import sys
from typing import Callable


def make_streams_utf8(streams=None) -> int:
    """Reconfigure the given text streams (default stdout+stderr) to UTF-8.

    Returns how many were successfully reconfigured — callers that want to assert the
    hardening actually happened can, rather than trusting that it did.
    """
    done = 0
    for stream in (streams if streams is not None else (sys.stdout, sys.stderr)):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # Not a TextIOWrapper — pytest capture, a StringIO, a closed stream.
            # Nothing to harden and nothing wrong.
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
            done += 1
        except (OSError, ValueError):                 # pragma: no cover - env dependent
            # A detached or already-closed stream. Refusing to crash the CLI over its
            # own hardening is the whole point.
            continue
    return done


def run_cli(main: Callable[[], int | None]) -> int:
    """Harden the streams, then run `main` and normalise its exit code.

    `BrokenPipeError` is caught because `… | head` closes the pipe early and the
    resulting traceback is noise, not a defect.
    """
    make_streams_utf8()
    try:
        return int(main() or 0)
    except BrokenPipeError:                           # pragma: no cover - needs a pipe
        return 1
