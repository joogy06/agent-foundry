#!/usr/bin/env python3
"""test_heartbeat.py — unit tests for heartbeat thread.

We simulate the claims.py subprocess by pointing heartbeat at a stub script
that prints a pre-seeded state. This validates the stop-event wiring without
requiring real bob infrastructure.
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-extract-static"
sys.path.insert(0, str(_SKILL / "scripts"))

from heartbeat import HeartbeatThread  # noqa: E402


def _make_stub(tmp: Path, responses: list[str]) -> Path:
    """Write a shell script that prints the next canned response per call."""
    state_file = tmp / "state"
    state_file.write_text("0")
    stub = tmp / "stub_claims.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, pathlib\n"
        f"state_f = pathlib.Path({str(state_file)!r})\n"
        f"responses = {responses!r}\n"
        "i = int(state_f.read_text().strip())\n"
        "state_f.write_text(str(i+1))\n"
        "print(responses[min(i, len(responses)-1)])\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def test_heartbeat_stops_on_revoked():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        stub = _make_stub(tmp, ["ok", "ok", "revoked"])
        stop = threading.Event()
        hb = HeartbeatThread(
            claim_uuid="00000000-0000-0000-0000-000000000000",
            project_root=tmp,
            stop_event=stop,
            interval_seconds=1,  # tight loop for the test
            claims_script=stub,
        )
        hb.start()
        # Wait up to 10 seconds for stop event
        start = time.time()
        while not stop.is_set() and time.time() - start < 10:
            time.sleep(0.2)
        assert stop.is_set(), "heartbeat did not stop on revoked"
        hb.join(timeout=5)
        assert hb.last_state == "revoked", f"last_state={hb.last_state!r}"


def test_heartbeat_ok_keeps_running():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        stub = _make_stub(tmp, ["ok"])  # always ok
        stop = threading.Event()
        hb = HeartbeatThread(
            claim_uuid="00000000-0000-0000-0000-000000000000",
            project_root=tmp,
            stop_event=stop,
            interval_seconds=1,
            claims_script=stub,
        )
        hb.start()
        time.sleep(2.5)  # let several beats happen
        assert not stop.is_set(), "heartbeat stopped unexpectedly"
        assert hb.last_state == "ok"
        stop.set()
        hb.join(timeout=5)


def test_heartbeat_stops_on_startup_if_missing():
    """First beat failure sets stop immediately."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        stub = tmp / "nonexistent.py"  # not created
        stop = threading.Event()
        hb = HeartbeatThread(
            claim_uuid="00000000-0000-0000-0000-000000000000",
            project_root=tmp,
            stop_event=stop,
            interval_seconds=1,
            claims_script=stub,
        )
        hb.start()
        start = time.time()
        while not stop.is_set() and time.time() - start < 5:
            time.sleep(0.1)
        assert stop.is_set()
        hb.join(timeout=5)
        assert hb.last_state != "ok"


def main():
    tests = [
        test_heartbeat_stops_on_revoked,
        test_heartbeat_ok_keeps_running,
        test_heartbeat_stops_on_startup_if_missing,
    ]
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
