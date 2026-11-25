#!/usr/bin/env python3
"""Tests for codex_watch.py -- the D24 activity watchdog (S081 rev 4, WP-A01).

STUB BINARIES ONLY. No real `codex exec`, no real `agy`, no network, no model
call of any kind. Every process this suite starts is the parameterised fixture
script written into `tmp_path` by the `stub` fixture, and
`test_every_spawn_was_a_stub` is the control that proves it.

Time is driven by an injected clock so the REAL thresholds (300 s idle, 2400 s
xhigh cap, 60 s progress line) are exercised without spending real seconds; the
constants are ALSO asserted as plain values, because a suite that only ever sees
the injected numbers would pass with the table rewritten.

Every positive claim here has its negative control:
  stderr keeps a codex call alive         <-> the same stub in agy mode never
                                              registers activity at all
  rollout mtime keeps a silent call alive <-> the same stub untouched dies
  activity keeps a call to the hard cap   <-> silence stops it at the idle timeout
  a silent agy call survives past 300 s   <-> THE SAME STUB in codex mode still
                                              idle-times-out at 300 s
  the agy idle timeout is disabled        <-> the agy HARD CAP still fires
"""
import ast
import hashlib
import io
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import codex_watch as cw  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
_STUB_SOURCE = '''#!/usr/bin/env python3
"""Watchdog test stub. Prints on a schedule, then exits with a chosen code."""
import argparse
import os
import sys
import time

p = argparse.ArgumentParser()
p.add_argument("--lines", type=int, default=3)
p.add_argument("--interval", type=float, default=0.01)
p.add_argument("--exit", type=int, default=0)
p.add_argument("--stream", default="stdout", choices=("stdout", "stderr", "both", "none"))
p.add_argument("--pidfile", default=None)
p.add_argument("--hold", type=float, default=0.0)
p.add_argument("--forever", action="store_true")
p.add_argument("--session-id", default=None)
a = p.parse_args()

if a.pidfile:
    with open(a.pidfile, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))


def emit(i):
    if a.stream in ("stdout", "both"):
        sys.stdout.write("line %d\\n" % i)
        sys.stdout.flush()
    if a.stream in ("stderr", "both"):
        sys.stderr.write("err %d\\n" % i)
        sys.stderr.flush()


if a.session_id:
    sys.stdout.write('{"type":"thread.started","thread_id":"%s"}\\n' % a.session_id)
    sys.stdout.flush()

if a.forever:
    end = time.time() + 60.0          # hard stop so a broken test cannot hang
    i = 0
    while time.time() < end:
        i += 1
        emit(i)
        time.sleep(a.interval)
else:
    for i in range(1, a.lines + 1):
        emit(i)
        time.sleep(a.interval)

if a.hold:
    time.sleep(a.hold)
sys.exit(a.exit)
'''


@pytest.fixture
def stub(tmp_path):
    """Write the stub script and return a builder for its argv."""
    path = tmp_path / "stub_codex.py"
    path.write_text(_STUB_SOURCE, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)

    def build(*args):
        return [str(path), *[str(a) for a in args]]

    build.path = path
    return build


class FakeClock:
    """A monotonic clock that jumps `step` seconds every time the loop sleeps.

    The child runs in REAL time; only the watchdog's sense of elapsed time is
    accelerated. `real` is how long each poll actually waits, so a stub still
    gets scheduled between polls.
    """

    def __init__(self, step=10.0, real=0.002, on_sleep=None):
        self.t = 0.0
        self.step = step
        self.real = real
        self.polls = 0
        self.on_sleep = on_sleep

    def now(self):
        return self.t

    def sleep(self, _requested):
        self.t += self.step
        self.polls += 1
        if self.on_sleep is not None:
            self.on_sleep(self.polls)
        time.sleep(self.real)


@pytest.fixture
def spawned(monkeypatch):
    """Capture every Popen the watchdog creates, for reap and argv assertions."""
    created = []
    real_popen = subprocess.Popen

    class Recording(real_popen):
        def __init__(self, argv, *a, **kw):
            created.append(self)
            self.recorded_argv = list(argv)
            # D21 f11: the kwargs watch() passed -- what `stdin=` really was and which
            # handle objects it opened -- so a test can assert on them rather than on
            # Popen attributes that are None for every non-PIPE redirect.
            self.recorded_kwargs = dict(kw)
            super().__init__(argv, *a, **kw)

    monkeypatch.setattr(cw.subprocess, "Popen", Recording)
    return created


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "out.txt", tmp_path / "err.txt"


def run(stub_argv, out, err, **kwargs):
    """`watch()` with telemetry off and a captured progress stream by default."""
    kwargs.setdefault("record_telemetry", False)
    kwargs.setdefault("progress_stream", io.StringIO())
    kwargs.setdefault("reap_grace_s", 5.0)
    return cw.watch(stub_argv, stdout_path=out, stderr_path=err, **kwargs)


def assert_reaped(spawned):
    """Every child the watchdog started was waited on -- no orphan, no zombie."""
    assert spawned, "no process was spawned"
    for proc in spawned:
        assert proc.returncode is not None, (
            "child pid %s was never reaped (returncode is None)" % proc.pid
        )
        assert proc.poll() is not None


# --------------------------------------------------------------------------- #
# The frozen constants -- asserted as VALUES, not through the injected clock
# --------------------------------------------------------------------------- #
class TestFrozenConstants:
    def test_idle_timeout_is_300_seconds(self):
        # 1.6x the 183 s longest silence measured in a real, healthy session.
        assert cw.IDLE_TIMEOUT_S == 300

    def test_hard_caps_match_the_design_table(self):
        assert cw.HARD_CAP_S == {
            "low": 1200,
            "medium": 1200,
            "high": 2400,
            "xhigh": 2400,
            "max": 3600,
            "ultra": 5400,
        }

    def test_agy_caps(self):
        assert cw.AGY_HARD_CAP_S == 900

    def test_the_agy_idle_timeout_is_the_DISABLED_sentinel_not_a_number(self):
        """WP-A01b ruling 4. RE-POINTED: this previously asserted
        `AGY_IDLE_TIMEOUT_S == 300`.

        agy emits nothing while it reasons (probed: 0 B at t=5 s and t=10 s,
        250 B at 15 s, 10,730 B at completion ~20 s), and stdout growth is its
        only heartbeat -- so an idle timeout on the agy arm can ONLY ever fire
        on a HEALTHY call. The fix is DISABLE, not enlarge: a large number
        reads as a tuned value and invites someone to tune it later.

        Asserting `is None` -- rather than `!= 300` or `> 300` -- is the whole
        point of this test: an edit that sets the constant to ANY number fails
        here instead of shipping.
        """
        assert cw.AGY_IDLE_TIMEOUT_S is None
        assert not isinstance(cw.AGY_IDLE_TIMEOUT_S, (int, float))
        # THE CONTROL: the codex arm was NOT disabled by the same edit. Its
        # heartbeat includes the rollout mtime, which advances DURING
        # reasoning, so 300 s is well founded there.
        assert cw.IDLE_TIMEOUT_S == 300

    def test_progress_interval_is_60_seconds(self):
        assert cw.PROGRESS_INTERVAL_S == 60

    def test_exit_codes_are_111_and_112(self):
        assert cw.EXIT_IDLE_TIMEOUT == 111
        assert cw.EXIT_HARD_CAP == 112

    def test_exit_codes_collide_with_nothing_in_the_chain(self):
        """0-2 are codex's own; 124 is `timeout`'s; 125-127 are shell reserved;
        128+N is death by signal. Ours must be none of those."""
        reserved = {0, 1, 2, 124, 125, 126, 127}
        reserved |= {128 + n for n in range(1, 65)}
        for code in (cw.EXIT_IDLE_TIMEOUT, cw.EXIT_HARD_CAP):
            assert code not in reserved
            assert 100 <= code <= 123
        assert cw.EXIT_IDLE_TIMEOUT != cw.EXIT_HARD_CAP

    def test_stop_reasons_are_the_three_documented_tokens(self):
        assert cw.STOP_REASONS == ("ok", "idle_timeout", "hard_cap")


class TestHardCapLookup:
    @pytest.mark.parametrize(
        "effort,expected",
        [("low", 1200), ("medium", 1200), ("high", 2400),
         ("xhigh", 2400), ("max", 3600), ("ultra", 5400)],
    )
    def test_each_tabulated_effort(self, effort, expected):
        assert cw.hard_cap_for(effort) == expected

    def test_minimal_raises_rather_than_inheriting_another_tier(self):
        # codex_model tabulates `minimal` for TIMEOUTS; D24 gives it no cap.
        # A `.get(effort, <scalar>)` here is the defect codex_model refuses.
        with pytest.raises(cw.CodexWatchError) as exc:
            cw.hard_cap_for("minimal")
        assert "minimal" in str(exc.value)

    @pytest.mark.parametrize("bad", ["", "XHIGH", "turbo", None, 2400])
    def test_an_unknown_effort_raises(self, bad):
        with pytest.raises(cw.CodexWatchError):
            cw.hard_cap_for(bad)

    def test_codex_mode_without_effort_or_cap_raises(self, stub, paths):
        out, err = paths
        with pytest.raises(cw.CodexWatchError):
            run(stub("--lines", 1), out, err, mode="codex")


# --------------------------------------------------------------------------- #
# Normal completion: the child's own exit is passed through
# --------------------------------------------------------------------------- #
class TestNormalCompletion:
    def test_a_stub_that_prints_then_exits_zero_is_ok(self, stub, paths, spawned):
        out, err = paths
        clock = FakeClock()
        result = run(
            stub("--lines", 3, "--interval", 0.01),
            out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_OK
        assert result.exit_code == 0
        assert result.child_exit_code == 0
        assert result.elapsed_s >= 0.0
        assert out.read_text(encoding="utf-8").count("line") == 3
        assert_reaped(spawned)

    @pytest.mark.parametrize("code", [1, 2, 7, 42])
    def test_a_non_zero_stub_exit_is_passed_through(self, stub, paths, spawned, code):
        out, err = paths
        clock = FakeClock()
        result = run(
            stub("--lines", 1, "--exit", code),
            out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_OK, "a child that exits is never a timeout"
        assert result.exit_code == code
        assert result.child_exit_code == code
        assert not result.timed_out
        assert_reaped(spawned)

    def test_the_partial_output_files_are_left_for_the_classifier(self, stub, paths):
        out, err = paths
        clock = FakeClock()
        run(stub("--lines", 2, "--stream", "both"), out, err,
            effort="xhigh", clock=clock.now, sleep=clock.sleep)
        assert out.exists() and err.exists()
        assert "line 1" in out.read_text(encoding="utf-8")
        assert "err 1" in err.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Idle timeout -- the NORMAL stop
# --------------------------------------------------------------------------- #
class TestIdleTimeout:
    def test_prints_once_then_goes_quiet_past_300s(self, stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=10.0)
        result = run(
            stub("--lines", 1, "--hold", 30),
            out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_IDLE_TIMEOUT
        assert result.exit_code == cw.EXIT_IDLE_TIMEOUT == 111
        assert result.max_silence_s >= 300, result.max_silence_s
        assert result.timed_out
        # It stopped on SILENCE, not on the wall clock.
        assert result.elapsed_s < cw.HARD_CAP_S["xhigh"]
        assert_reaped(spawned)

    def test_a_completely_silent_child_idles_out(self, stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=10.0)
        result = run(
            stub("--lines", 0, "--stream", "none", "--hold", 30),
            out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_IDLE_TIMEOUT
        assert result.max_silence_s >= 300
        assert out.stat().st_size == 0 and err.stat().st_size == 0
        assert_reaped(spawned)


# --------------------------------------------------------------------------- #
# Hard cap -- runaway protection, and the control proving activity keeps a call
# alive right past the idle timeout
# --------------------------------------------------------------------------- #
class TestHardCap:
    def test_a_stub_that_keeps_printing_reaches_the_effort_cap(self, stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            stub("--forever", "--interval", 0.005),
            out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_HARD_CAP
        assert result.exit_code == cw.EXIT_HARD_CAP == 112
        # THE NEGATIVE CONTROL: it ran 8x past the 300 s idle timeout because it
        # never went quiet. A wall-clock watchdog would have killed it at 600 s.
        assert result.elapsed_s >= cw.HARD_CAP_S["xhigh"]
        assert result.max_silence_s < cw.IDLE_TIMEOUT_S, result.max_silence_s
        assert_reaped(spawned)

    def test_the_cap_that_fires_is_the_efforts_own(self, stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=40.0, real=0.002)
        result = run(
            stub("--forever", "--interval", 0.005),
            out, err, effort="low", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_HARD_CAP
        assert result.hard_cap_s == 1200
        assert cw.HARD_CAP_S["low"] <= result.elapsed_s < cw.HARD_CAP_S["xhigh"]
        assert_reaped(spawned)


# --------------------------------------------------------------------------- #
# Heartbeat sources
# --------------------------------------------------------------------------- #
class TestStderrIsAHeartbeat:
    def test_stderr_growth_alone_keeps_a_codex_call_alive(self, stub, paths, spawned):
        """codex prints its transcript to stderr; a call silent on stdout is
        not a dead call."""
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            stub("--forever", "--stream", "stderr", "--interval", 0.005),
            out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_HARD_CAP
        # The proof: stdout NEVER grew, so stderr is the only thing that can
        # have kept it alive past 300 s.
        assert out.stat().st_size == 0
        assert err.stat().st_size > 0
        assert result.elapsed_s >= cw.HARD_CAP_S["xhigh"]
        assert_reaped(spawned)

    # The negative control for the claim above lives in
    # TestAgyMode.test_agy_stderr_growth_is_NOT_a_heartbeat: the same busy-on-
    # stderr shape, run in the mode where stderr is not a heartbeat, idles out.


class TestRolloutIsAHeartbeat:
    def test_a_touched_rollout_keeps_a_doubly_silent_call_alive(
        self, stub, paths, spawned, tmp_path
    ):
        out, err = paths
        rollout = tmp_path / "rollout-2026-09-16T00-00-00-abc.jsonl"
        rollout.write_text("{}\n", encoding="utf-8")
        state = {"ns": rollout.stat().st_mtime_ns}

        def touch(poll_count):
            if poll_count % 5 == 0:
                state["ns"] += 1_000_000_000
                os.utime(rollout, ns=(state["ns"], state["ns"]))

        clock = FakeClock(step=10.0, real=0.002, on_sleep=touch)
        result = run(
            stub("--lines", 0, "--stream", "none", "--hold", 30),
            out, err, effort="ultra", rollout_path=rollout,
            clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_HARD_CAP
        # Both byte counters stayed at zero for the whole run.
        assert out.stat().st_size == 0 and err.stat().st_size == 0
        assert result.elapsed_s >= cw.HARD_CAP_S["ultra"]
        assert result.max_silence_s < cw.IDLE_TIMEOUT_S
        assert_reaped(spawned)

    def test_the_same_call_idles_out_when_the_rollout_is_not_touched(
        self, stub, paths, spawned, tmp_path
    ):
        """NEGATIVE CONTROL: the rollout arm is what kept the call above alive."""
        out, err = paths
        rollout = tmp_path / "rollout-2026-09-16T00-00-00-abc.jsonl"
        rollout.write_text("{}\n", encoding="utf-8")
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            stub("--lines", 0, "--stream", "none", "--hold", 30),
            out, err, effort="ultra", rollout_path=rollout,
            clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_IDLE_TIMEOUT
        assert result.max_silence_s >= 300
        assert_reaped(spawned)

    def test_the_rollout_is_located_from_the_session_id_in_the_stream(
        self, stub, paths, tmp_path, spawned
    ):
        session = "019efdb9-c573-7983-a75a-c1f0a33fde5e"
        sessions = tmp_path / "sessions" / "2026" / "09" / "16"
        sessions.mkdir(parents=True)
        rollout = sessions / ("rollout-2026-09-16T08-00-00-%s.jsonl" % session)
        rollout.write_text("{}\n", encoding="utf-8")
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            stub("--session-id", session, "--lines", 1, "--hold", 30),
            out, err, effort="xhigh", sessions_dir=tmp_path / "sessions",
            clock=clock.now, sleep=clock.sleep,
        )
        assert result.rollout_path == rollout, "the rollout was not discovered"
        assert_reaped(spawned)

    def test_an_ephemeral_call_with_no_rollout_still_runs_on_the_byte_counters(
        self, stub, paths, tmp_path, spawned
    ):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            stub("--forever", "--interval", 0.005),
            out, err, effort="xhigh", sessions_dir=tmp_path / "no-such-dir",
            clock=clock.now, sleep=clock.sleep,
        )
        assert result.rollout_path is None
        assert result.stop_reason == cw.STOP_HARD_CAP
        assert_reaped(spawned)


# --------------------------------------------------------------------------- #
# agy mode
# --------------------------------------------------------------------------- #
_AGY_STUB_SOURCE = '''#!/usr/bin/env python3
"""agy-shaped stub: accepts agy's flag order, prints to a chosen stream."""
import os
import sys
import time

args = sys.argv[1:]
stream = "stdout"
hold = 0.0
forever = False
quiet_until = None
for i, a in enumerate(args):
    if a == "--stub-stream":
        stream = args[i + 1]
    elif a == "--stub-hold":
        hold = float(args[i + 1])
    elif a == "--stub-forever":
        forever = True
    elif a == "--stub-quiet-until":
        quiet_until = args[i + 1]

if quiet_until is not None:
    # Say NOTHING until the watcher creates the sentinel, then speak and exit.
    # This models agy's silent reasoning prefix, and it is deterministic in
    # WATCHDOG time (the test creates the sentinel at a chosen poll) rather
    # than in real time.
    end = time.time() + 60.0            # hard stop so a broken test cannot hang
    while time.time() < end and not os.path.exists(quiet_until):
        time.sleep(0.002)
    sys.stdout.write("the answer, after a long think\\n")
    sys.stdout.flush()
    sys.exit(0)

if forever:
    end = time.time() + 60.0
    i = 0
    while time.time() < end:
        i += 1
        if stream == "stdout":
            sys.stdout.write("out %d\\n" % i)
            sys.stdout.flush()
        elif stream == "stderr":
            sys.stderr.write("err %d\\n" % i)
            sys.stderr.flush()
        time.sleep(0.005)
if hold:
    time.sleep(hold)
sys.exit(0)
'''


@pytest.fixture
def agy_stub(tmp_path):
    path = tmp_path / "stub_agy.py"
    path.write_text(_AGY_STUB_SOURCE, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)

    def build(*flags, prompt="advisory only"):
        return [str(path), "--sandbox", *[str(f) for f in flags], "-p", prompt]

    build.path = path
    return build


class TestAgyArgvRules:
    def test_a_well_formed_argv_passes(self, agy_stub):
        argv = agy_stub("--stub-forever")
        assert cw.validate_agy_argv(argv) == tuple(argv)

    def test_flag_after_the_prompt_flag_is_refused(self, agy_stub):
        """`agy -p --sandbox "X"` runs UN-sandboxed with the literal prompt
        "--sandbox" and discards "X". The flag-order rule exists for this."""
        bad = [str(agy_stub.path), "-p", "--sandbox", "the real prompt"]
        with pytest.raises(cw.AgyArgvError) as exc:
            cw.validate_agy_argv(bad)
        assert "FLAG ORDER" in str(exc.value)

    def test_trailing_tokens_after_the_prompt_are_refused(self, agy_stub):
        bad = [str(agy_stub.path), "--sandbox", "-p", "prompt", "--model", "x"]
        with pytest.raises(cw.AgyArgvError) as exc:
            cw.validate_agy_argv(bad)
        assert "FLAG ORDER" in str(exc.value)

    def test_a_missing_prompt_flag_is_refused(self, agy_stub):
        with pytest.raises(cw.AgyArgvError):
            cw.validate_agy_argv([str(agy_stub.path), "--sandbox"])

    def test_a_repeated_prompt_flag_is_refused(self, agy_stub):
        with pytest.raises(cw.AgyArgvError):
            cw.validate_agy_argv(
                [str(agy_stub.path), "--sandbox", "-p", "a", "-p", "b"]
            )

    def test_a_missing_sandbox_is_refused(self, agy_stub):
        """S052: an un-sandboxed 'analyst' has authored and git-committed code.
        There is no opt-out here -- the rule is add --dangerously-skip-
        permissions, never drop --sandbox."""
        bad = [str(agy_stub.path), "-p", "prompt"]
        with pytest.raises(cw.AgyArgvError) as exc:
            cw.validate_agy_argv(bad)
        assert "SANDBOX" in str(exc.value)

    def test_sandbox_after_the_prompt_flag_does_not_count(self, agy_stub):
        bad = [str(agy_stub.path), "-p", "prompt", "--sandbox"]
        with pytest.raises(cw.AgyArgvError):
            cw.validate_agy_argv(bad)

    @pytest.mark.parametrize("flag", ["-p", "--print", "--prompt"])
    def test_every_spelling_of_the_prompt_flag_is_recognised(self, agy_stub, flag):
        argv = [str(agy_stub.path), "--sandbox", flag, "prompt"]
        assert cw.validate_agy_argv(argv) == tuple(argv)

    def test_an_empty_argv_is_refused(self):
        with pytest.raises(cw.AgyArgvError):
            cw.validate_agy_argv([])

    def test_watch_refuses_an_illegal_agy_argv_before_spawning(self, agy_stub, paths, spawned):
        out, err = paths
        with pytest.raises(cw.AgyArgvError):
            run([str(agy_stub.path), "-p", "prompt"], out, err, mode="agy")
        assert spawned == [], "an illegal argv must never reach Popen"


class TestAgyMode:
    def test_stdin_is_closed_so_the_135_hang_cannot_return(self, agy_stub, paths, spawned):
        """Headless agy reads a non-TTY stdin to EOF before calling the model;
        an inherited stdin that never EOFs hangs it forever at 0 bytes."""
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        run(agy_stub("--stub-hold", "1"), out, err, mode="agy",
            clock=clock.now, sleep=clock.sleep)
        assert spawned
        # Never a pipe the parent must drain: Popen.stdin is set only for PIPE.
        assert spawned[0].stdin is None
        # DEVNULL, never None (inherit). S081 rev 4 D21 f11: the line above cannot
        # tell those two apart -- Popen.stdin is None for DEVNULL AND for an
        # inherited stdin -- so the #135 regression it names is asserted on the
        # kwarg watch() actually passed.
        assert "stdin" in spawned[0].recorded_kwargs
        assert spawned[0].recorded_kwargs["stdin"] is subprocess.DEVNULL

    def test_agy_uses_the_900_second_cap(self, agy_stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(agy_stub("--stub-forever"), out, err, mode="agy",
                     clock=clock.now, sleep=clock.sleep)
        assert result.stop_reason == cw.STOP_HARD_CAP
        assert result.hard_cap_s == 900
        assert result.elapsed_s >= 900
        assert_reaped(spawned)

    def test_agy_stdout_growth_is_a_heartbeat(self, agy_stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(agy_stub("--stub-forever", "--stub-stream", "stdout"),
                     out, err, mode="agy", clock=clock.now, sleep=clock.sleep)
        assert result.stop_reason == cw.STOP_HARD_CAP
        # RE-POINTED at WP-A01b: the reference used to be AGY_IDLE_TIMEOUT_S,
        # which is now None. The claim is unchanged -- stdout growth kept the
        # silence near zero -- so it is measured against the codex threshold,
        # the only idle number left in the module.
        assert result.max_silence_s < cw.IDLE_TIMEOUT_S
        assert out.stat().st_size > 0

    def test_agy_stderr_growth_is_NOT_a_heartbeat(self, agy_stub, paths, spawned):
        """The negative control that makes the test above mean something: the
        same busy stub, writing only to stderr, registers NO activity at all.

        RE-POINTED at WP-A01b (ruling 4): this previously asserted
        STOP_IDLE_TIMEOUT. With the agy idle timeout disabled the call now runs
        to the hard cap instead -- but the claim under test is unchanged, and
        `max_silence_s` is the observable that carries it: it grew to the FULL
        length of the run, i.e. nothing the stub wrote to stderr was ever
        counted. Contrast the stdout test above, where it stays near zero. Make
        agy count stderr and this collapses toward zero and fails.
        """
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(agy_stub("--stub-forever", "--stub-stream", "stderr"),
                     out, err, mode="agy", clock=clock.now, sleep=clock.sleep)
        assert result.stop_reason == cw.STOP_HARD_CAP
        assert result.max_silence_s >= cw.AGY_HARD_CAP_S
        assert err.stat().st_size > 0, "the stub really was busy on stderr"
        assert out.stat().st_size == 0
        assert_reaped(spawned)

    def test_agy_watch_wrapper_needs_no_effort(self, agy_stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = cw.agy_watch(
            agy_stub("--stub-hold", "1"),
            stdout_path=out, stderr_path=err, clock=clock.now, sleep=clock.sleep,
            record_telemetry=False, progress_stream=io.StringIO(),
        )
        assert result.mode == "agy"
        assert result.hard_cap_s == 900
        assert result.idle_timeout_s is None


# --------------------------------------------------------------------------- #
# WP-A01b ruling 4 -- agy has NO idle timeout, and the codex control that proves
# the two arms genuinely differ rather than both being switched off
# --------------------------------------------------------------------------- #
class TestAgyHasNoIdleTimeout:
    """The mechanism, not just the constant.

    The shared fixture below is ONE stub that says nothing until the watcher
    creates a sentinel file, then speaks and exits -- agy's silent reasoning
    prefix, made deterministic in WATCHDOG time. The sentinel is created at
    ~400 s of watchdog time: past the 300 s idle timeout, well short of the
    900 s cap. The SAME stub, the SAME schedule, run in the two modes, is what
    makes this a control rather than two unrelated assertions.
    """

    SPEAK_AT_S = 400.0

    def _clock_that_breaks_the_silence(self, sentinel, step=10.0):
        """A FakeClock that creates `sentinel` once watchdog time passes
        SPEAK_AT_S -- i.e. after the old 300 s threshold, before the 900 s cap."""

        def on_sleep(polls):
            if polls * step >= self.SPEAK_AT_S and not sentinel.exists():
                sentinel.write_text("speak", encoding="utf-8")

        return FakeClock(step=step, real=0.002, on_sleep=on_sleep)

    def test_a_silent_agy_call_that_finally_speaks_completes_normally(
        self, agy_stub, paths, spawned, tmp_path
    ):
        """THE POINT OF RULING 4: 400 s of silence is a HEALTHY agy call, and
        the watchdog must not kill it. Before this change it stopped at 300 s
        with exit 111 -- the exact failure the watchdog exists to prevent,
        reintroduced on the agy arm."""
        out, err = paths
        sentinel = tmp_path / "speak-now"
        clock = self._clock_that_breaks_the_silence(sentinel)
        result = run(
            agy_stub("--stub-quiet-until", str(sentinel)),
            out, err, mode="agy", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_OK
        assert result.exit_code == 0
        assert result.child_exit_code == 0
        assert not result.timed_out
        # It really was silent past the threshold that used to kill it.
        assert result.max_silence_s >= cw.IDLE_TIMEOUT_S, result.max_silence_s
        # And it really did produce its answer.
        assert out.stat().st_size > 0
        assert "the answer" in out.read_text(encoding="utf-8")
        assert result.idle_timeout_s is None
        assert_reaped(spawned)

    def test_THE_CONTROL_the_same_stub_in_codex_mode_still_idle_times_out(
        self, agy_stub, paths, spawned, tmp_path
    ):
        """THE CONTROL the ruling asks for BY NAME. Same stub, same sentinel
        schedule, same clock -- only the mode differs. codex still stops at
        300 s with exit 111, which proves two things at once: the two arms
        genuinely differ, and the codex idle timeout was not switched off by
        accident along with agy's.

        The stub is killed while still waiting, so the sentinel is never even
        written -- the codex arm never reaches the moment agy survives to.
        """
        out, err = paths
        sentinel = tmp_path / "speak-now"
        clock = self._clock_that_breaks_the_silence(sentinel)
        result = run(
            agy_stub("--stub-quiet-until", str(sentinel)),
            out, err, mode="codex", effort="xhigh",
            clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_IDLE_TIMEOUT
        assert result.exit_code == cw.EXIT_IDLE_TIMEOUT == 111
        assert result.idle_timeout_s == 300
        assert result.max_silence_s >= 300
        # Stopped at the idle timeout, nowhere near the xhigh cap.
        assert result.elapsed_s < cw.HARD_CAP_S["xhigh"]
        assert not sentinel.exists(), (
            "codex stopped before the stub would have spoken -- the control is "
            "comparing the two modes at the SAME moment"
        )
        assert out.stat().st_size == 0
        assert_reaped(spawned)

    def test_a_silent_agy_call_is_still_stopped_by_the_hard_cap(
        self, agy_stub, paths, spawned, tmp_path
    ):
        """Disabling the idle timeout must NOT disable the runaway guard. The
        same stub with a sentinel that is never created runs forever; the 900 s
        cap is the only thing left to stop it, and it does."""
        out, err = paths
        never = tmp_path / "never-created"
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            agy_stub("--stub-quiet-until", str(never)),
            out, err, mode="agy", clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_HARD_CAP
        assert result.exit_code == cw.EXIT_HARD_CAP == 112
        assert result.hard_cap_s == cw.AGY_HARD_CAP_S == 900
        assert result.elapsed_s >= 900
        assert not never.exists()
        assert out.stat().st_size == 0
        assert_reaped(spawned)

    def test_an_agy_caller_may_still_pass_an_explicit_idle_timeout(
        self, agy_stub, paths, spawned
    ):
        """The disable is a DEFAULT, not a prohibition: a caller that has its
        own liveness signal can still set one, which is what makes reinstating
        an idle timeout later a configuration change rather than a rewrite."""
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            agy_stub("--stub-stream", "stderr", "--stub-forever"),
            out, err, mode="agy", idle_timeout_s=120,
            clock=clock.now, sleep=clock.sleep,
        )
        assert result.stop_reason == cw.STOP_IDLE_TIMEOUT
        assert result.idle_timeout_s == 120
        assert_reaped(spawned)


# --------------------------------------------------------------------------- #
# The 60 s progress line
# --------------------------------------------------------------------------- #
_PROGRESS_RE = re.compile(
    r"^(codex|agy) alive: (\d+) s elapsed, last activity (\d+) s ago, model (.+)$"
)


class TestProgressLine:
    def test_a_line_every_60_seconds_with_the_designs_shape(self, stub, paths):
        out, err = paths
        sink = io.StringIO()
        clock = FakeClock(step=10.0, real=0.002)
        result = run(
            stub("--lines", 0, "--stream", "none", "--hold", 30),
            out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
            progress_stream=sink,
        )
        lines = [ln for ln in sink.getvalue().splitlines() if ln]
        assert lines == list(result.progress_lines)
        # 300 s of silence at one line per 60 s.
        assert len(lines) >= 4, lines
        for line in lines:
            assert _PROGRESS_RE.match(line), line
        first = _PROGRESS_RE.match(lines[0])
        assert first.group(1) == "codex"
        assert int(first.group(2)) == 60
        assert first.group(4) == "unknown"

    def test_the_model_name_is_shown_when_given(self, stub, paths):
        out, err = paths
        sink = io.StringIO()
        clock = FakeClock(step=10.0, real=0.002)
        run(stub("--lines", 0, "--stream", "none", "--hold", 30), out, err,
            effort="xhigh", model="gpt-6-astra", clock=clock.now,
            sleep=clock.sleep, progress_stream=sink)
        lines = [ln for ln in sink.getvalue().splitlines() if ln]
        assert lines
        for line in lines:
            assert line.endswith("model gpt-6-astra"), line

    def test_the_default_progress_stream_is_stderr(self, stub, paths, capsys):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        cw.watch(
            stub("--lines", 0, "--stream", "none", "--hold", 30),
            stdout_path=out, stderr_path=err, effort="xhigh",
            clock=clock.now, sleep=clock.sleep, record_telemetry=False,
        )
        captured = capsys.readouterr()
        assert "codex alive:" in captured.err
        assert "codex alive:" not in captured.out

    def test_the_elapsed_and_silence_numbers_advance(self, stub, paths):
        out, err = paths
        sink = io.StringIO()
        clock = FakeClock(step=10.0, real=0.002)
        run(stub("--lines", 0, "--stream", "none", "--hold", 30), out, err,
            effort="xhigh", clock=clock.now, sleep=clock.sleep,
            progress_stream=sink)
        elapsed = [int(_PROGRESS_RE.match(ln).group(2))
                   for ln in sink.getvalue().splitlines() if ln]
        assert elapsed == sorted(elapsed)
        assert elapsed[0] == 60 and elapsed[1] == 120

    def test_a_broken_progress_stream_never_breaks_the_call(self, stub, paths):
        class Exploding(io.StringIO):
            def write(self, _s):
                raise OSError("stream gone")

        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 0, "--stream", "none", "--hold", 30),
                     out, err, effort="xhigh", clock=clock.now,
                     sleep=clock.sleep, progress_stream=Exploding())
        assert result.stop_reason == cw.STOP_IDLE_TIMEOUT


# --------------------------------------------------------------------------- #
# Reaping -- asserted on EVERY stop path
# --------------------------------------------------------------------------- #
class TestReaping:
    @pytest.mark.parametrize(
        "args,effort,expected",
        [
            (("--lines", 2), "xhigh", cw.STOP_OK),
            (("--lines", 1, "--exit", 3), "xhigh", cw.STOP_OK),
            (("--lines", 1, "--hold", 30), "xhigh", cw.STOP_IDLE_TIMEOUT),
            (("--forever", "--interval", 0.005), "low", cw.STOP_HARD_CAP),
        ],
    )
    def test_the_child_is_reaped_on_every_stop_path(
        self, stub, paths, spawned, args, effort, expected
    ):
        out, err = paths
        clock = FakeClock(step=40.0, real=0.002)
        result = run(stub(*args), out, err, effort=effort,
                     clock=clock.now, sleep=clock.sleep)
        assert result.stop_reason == expected
        assert_reaped(spawned)

    @pytest.mark.skipif(not Path("/proc").is_dir(), reason="needs /proc")
    def test_no_zombie_is_left_behind(self, stub, paths, spawned, tmp_path):
        pidfile = tmp_path / "pid"
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        run(stub("--lines", 1, "--pidfile", pidfile, "--hold", 30), out, err,
            effort="xhigh", clock=clock.now, sleep=clock.sleep)
        pid = int(pidfile.read_text(encoding="utf-8"))
        deadline = time.time() + 5.0
        while time.time() < deadline:
            stat_path = Path("/proc/%d/stat" % pid)
            if not stat_path.exists():
                return
            try:
                fields = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[-1].split()
            except OSError:
                return
            if fields and fields[0] != "Z":
                # Still running is also a failure -- give it a moment to die.
                time.sleep(0.05)
                continue
            if fields and fields[0] == "Z":
                pytest.fail("child pid %d is a zombie" % pid)
        pytest.fail("child pid %d never exited" % pid)

    def test_the_output_handles_are_closed(self, stub, paths, spawned):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        run(stub("--lines", 1), out, err, effort="xhigh",
            clock=clock.now, sleep=clock.sleep)
        # Both streams went to files, never to a PIPE the parent holds.
        assert spawned[0].stdout is None and spawned[0].stderr is None
        # S081 rev 4 D21 f11: the line above is true of ANY file redirect and says
        # nothing about the handles watch() opened. These are those handles, as
        # watch() passed them to Popen -- each must be the right file, and closed.
        handles = [spawned[0].recorded_kwargs.get(name) for name in ("stdout", "stderr")]
        assert [getattr(h, "name", None) for h in handles] == [str(out), str(err)]
        for handle in handles:
            assert handle.closed, "watch() left %r open" % handle.name


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #
class TestTelemetry:
    def test_the_row_carries_elapsed_max_silence_and_stop_reason(self, stub, paths):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 1, "--hold", 30), out, err, effort="xhigh",
                     clock=clock.now, sleep=clock.sleep)
        row = cw.telemetry_row(result)
        assert row["stop_reason"] == "idle_timeout"
        assert row["elapsed_s"] == result.elapsed_s
        assert row["max_silence_s"] >= 300
        assert row["exit_code"] == 111
        assert row["tool"] == "codex_watch"
        assert row["status"] == "idle_timeout"

    def test_elapsed_and_stop_reason_reach_the_existing_sidecar_fields(
        self, stub, paths, monkeypatch
    ):
        """No second log: elapsed_s rides the sidecar's existing `wall_clock_s`
        and stop_reason its existing `status`."""
        seen = {}

        def recorder(*, tool, status, cost_usd, duration_ms, num_turns,
                     wall_clock_s, model=None, **_kw):
            seen.update(tool=tool, status=status, wall_clock_s=wall_clock_s,
                        duration_ms=duration_ms, model=model)

        monkeypatch.setattr(cw, "_load_record_spawn_run", lambda: recorder)
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 1, "--hold", 30), out, err, effort="xhigh",
                     model="gpt-6-astra", clock=clock.now, sleep=clock.sleep,
                     record_telemetry=True)
        assert seen["tool"] == "codex_watch"
        assert seen["status"] == "idle_timeout"
        assert seen["wall_clock_s"] == result.elapsed_s
        assert seen["model"] == "gpt-6-astra"

    def test_max_silence_is_offered_and_lands_once_the_sidecar_accepts_it(
        self, stub, paths, monkeypatch
    ):
        """Pinned as an executable fact: a recorder that declares
        max_silence_s RECEIVES it. WP-A01 shipped with this condition unmet --
        the installed sidecar had no such parameter -- and WP-A01b's ruling-1
        amendment met it. `test_the_installed_sidecar_accepts_every_watchdog_
        field` below is the half that checks the real sidecar; this one checks
        the offer, independent of which sidecar is installed."""
        seen = {}

        def recorder(*, tool, status, cost_usd, duration_ms, num_turns,
                     wall_clock_s, model=None, max_silence_s=None,
                     stop_reason=None, exit_code=None, **_kw):
            seen.update(max_silence_s=max_silence_s, stop_reason=stop_reason,
                        exit_code=exit_code)

        monkeypatch.setattr(cw, "_load_record_spawn_run", lambda: recorder)
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        run(stub("--lines", 1, "--hold", 30), out, err, effort="xhigh",
            clock=clock.now, sleep=clock.sleep, record_telemetry=True)
        assert seen["max_silence_s"] >= 300
        assert seen["stop_reason"] == "idle_timeout"
        assert seen["exit_code"] == 111

    def test_a_sidecar_without_the_new_fields_is_still_called(
        self, stub, paths, monkeypatch
    ):
        """The PRE-amendment signature -- a stale or half-copied tree. The
        extra kwargs are filtered out rather than raising TypeError and losing
        the row entirely. The filter stays deliberately even though the
        installed sidecar now accepts all five: a dropped field is a lesser
        failure than a dropped row."""
        calls = []

        def old_recorder(*, tool, status, cost_usd, duration_ms, num_turns,
                         wall_clock_s, model=None):
            calls.append(status)

        monkeypatch.setattr(cw, "_load_record_spawn_run", lambda: old_recorder)
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 1), out, err, effort="xhigh",
                     clock=clock.now, sleep=clock.sleep, record_telemetry=True)
        assert calls == ["ok"]
        assert result.stop_reason == "ok"

    def test_the_declared_extra_fields_are_exactly_the_watchdog_five(self):
        assert cw.TELEMETRY_EXTRA_FIELDS == (
            "max_silence_s", "stop_reason", "exit_code",
            "idle_timeout_s", "hard_cap_s",
        )

    def test_the_installed_sidecar_accepts_every_watchdog_field(self):
        """WP-A01b ruling 1, the two halves meeting: codex_watch OFFERS the
        five and the INSTALLED `spawn_runs.record_spawn_run` accepts them.

        This is loaded the way the module itself loads it -- relative to
        `__file__` -- so each tree checks its OWN sidecar. That makes it the
        half-copy detector: land the codex_watch half of this amendment
        without the spawn_runs half and this fails in the tree that is behind,
        instead of silently dropping `max_silence_s` at runtime.
        """
        import inspect

        record = cw._load_record_spawn_run()
        assert record is not None, "the sibling sidecar must be importable"
        accepted = set(inspect.signature(record).parameters)
        missing = [f for f in cw.TELEMETRY_EXTRA_FIELDS if f not in accepted]
        assert missing == [], (
            "spawn_runs.record_spawn_run is missing {0} -- this tree's sidecar "
            "predates the WP-A01b telemetry amendment".format(missing)
        )

    def test_an_agy_row_carries_no_idle_timeout_because_none_applies(
        self, agy_stub, paths, monkeypatch
    ):
        """Ruling 4 meets ruling 1: `idle_timeout_s` is None on an agy call, so
        the row simply has no such key. The absence is the honest record that
        the mechanism does not apply -- not 0, and not a fabricated number."""
        seen = {}

        def recorder(*, tool, status, cost_usd, duration_ms, num_turns,
                     wall_clock_s, model=None, max_silence_s=None,
                     stop_reason=None, exit_code=None, idle_timeout_s=None,
                     hard_cap_s=None, **_kw):
            seen.update(tool=tool, idle_timeout_s=idle_timeout_s,
                        hard_cap_s=hard_cap_s, stop_reason=stop_reason,
                        max_silence_s=max_silence_s, exit_code=exit_code)

        monkeypatch.setattr(cw, "_load_record_spawn_run", lambda: recorder)
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        run(agy_stub("--stub-forever", "--stub-stream", "stdout"), out, err,
            mode="agy", clock=clock.now, sleep=clock.sleep,
            record_telemetry=True)
        assert seen["tool"] == "agy_watch"
        assert seen["idle_timeout_s"] is None
        # Everything else the watchdog measures is still reported.
        assert seen["hard_cap_s"] == 900
        assert seen["stop_reason"] == "hard_cap"
        assert seen["exit_code"] == 112
        assert seen["max_silence_s"] is not None

    def test_a_broken_backend_never_breaks_the_call(self, stub, paths, monkeypatch):
        def exploding(**_kw):
            raise RuntimeError("sidecar on fire")

        monkeypatch.setattr(cw, "_load_record_spawn_run", lambda: exploding)
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 1, "--exit", 5), out, err, effort="xhigh",
                     clock=clock.now, sleep=clock.sleep, record_telemetry=True)
        assert result.exit_code == 5, "telemetry must not perturb the exit code"

    def test_an_unloadable_sidecar_never_breaks_the_call(self, stub, paths, monkeypatch):
        monkeypatch.setattr(cw, "_load_record_spawn_run", lambda: None)
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 1), out, err, effort="xhigh",
                     clock=clock.now, sleep=clock.sleep, record_telemetry=True)
        assert result.stop_reason == "ok"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class TestCli:
    def test_the_exit_code_is_the_childs_own(self, stub, paths, capsys):
        out, err = paths
        code = cw.main([
            "--effort", "xhigh", "--stdout-file", str(out), "--stderr-file", str(err),
            "--poll-interval", "0.01", "--no-telemetry",
            "--", *stub("--lines", 1, "--exit", 9),
        ])
        assert code == 9

    def test_no_command_is_a_usage_error(self, capsys):
        code = cw.main(["--stdout-file", "a", "--stderr-file", "b"])
        assert code == 2
        assert "no command" in capsys.readouterr().err

    def test_an_unknown_effort_is_reported_not_defaulted(self, stub, paths, capsys):
        out, err = paths
        code = cw.main([
            "--effort", "turbo", "--stdout-file", str(out), "--stderr-file", str(err),
            "--no-telemetry", "--", *stub("--lines", 1),
        ])
        assert code == 2
        assert "hard cap" in capsys.readouterr().err

    def test_json_prints_the_row(self, stub, paths, capsys):
        import json

        out, err = paths
        cw.main([
            "--effort", "xhigh", "--stdout-file", str(out), "--stderr-file", str(err),
            "--poll-interval", "0.01", "--no-telemetry", "--json",
            "--", *stub("--lines", 1),
        ])
        row = json.loads(capsys.readouterr().out.strip())
        assert row["stop_reason"] == "ok"
        assert row["tool"] == "codex_watch"


# --------------------------------------------------------------------------- #
# Misuse and the live-call prohibition
# --------------------------------------------------------------------------- #
class TestContract:
    def test_an_unknown_mode_raises(self, stub, paths):
        out, err = paths
        with pytest.raises(cw.CodexWatchError):
            run(stub("--lines", 1), out, err, mode="gemini")

    def test_an_empty_argv_raises(self, paths):
        out, err = paths
        with pytest.raises(cw.CodexWatchError):
            run([], out, err, effort="xhigh")

    def test_codex_watch_wrapper_sets_the_mode(self, stub, paths):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = cw.codex_watch(
            stub("--lines", 1), effort="max", stdout_path=out, stderr_path=err,
            clock=clock.now, sleep=clock.sleep, record_telemetry=False,
            progress_stream=io.StringIO(),
        )
        assert result.mode == "codex" and result.hard_cap_s == 3600

    def test_the_result_is_immutable(self, stub, paths):
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 1), out, err, effort="xhigh",
                     clock=clock.now, sleep=clock.sleep)
        with pytest.raises(Exception):
            result.stop_reason = "hard_cap"

    def test_output_parent_directories_are_created(self, stub, tmp_path):
        out = tmp_path / "deep" / "nested" / "out.txt"
        err = tmp_path / "deep" / "nested" / "err.txt"
        clock = FakeClock(step=10.0, real=0.002)
        result = run(stub("--lines", 1), out, err, effort="xhigh",
                     clock=clock.now, sleep=clock.sleep)
        assert result.stop_reason == "ok" and out.exists()


class TestEverySpawnWasAStub:
    def test_no_real_codex_or_agy_binary_is_ever_invoked(
        self, stub, agy_stub, paths, spawned, tmp_path
    ):
        """live_prohibitions control: this cycle makes NO model call. Every
        process the watchdog starts is a fixture under tmp_path."""
        out, err = paths
        clock = FakeClock(step=10.0, real=0.002)
        run(stub("--lines", 1), out, err, effort="xhigh",
            clock=clock.now, sleep=clock.sleep)
        run(agy_stub("--stub-hold", "0"), out, err, mode="agy",
            clock=clock.now, sleep=clock.sleep)
        assert len(spawned) == 2
        for proc in spawned:
            argv0 = Path(proc.recorded_argv[0])
            assert argv0.is_relative_to(tmp_path), argv0
            assert argv0.name.startswith("stub_")
            assert Path(argv0).name not in ("codex", "agy")


# =========================================================================== #
# S081 revision 4, D21 fix round 1 -- WP-X5: F8, F9 and f9 (f11 is fixed in
# place above; f10 is a comment). Review: docs/reviews/2026-09-22-S081-rev4-
# review.md. Every test below is NEW, so none is flake-eligible, and none races
# a FakeClock against a real subprocess or asserts an elapsed window of REAL
# time: the F8 heartbeat runs with NO process at all; the in-process F9 tests
# keep the REAL monotonic clock, whose 300 s / 2400 s thresholds cannot fire in
# the milliseconds they take; the subprocess F9 tests assert outcomes only.
# =========================================================================== #

#: The first 12 stderr lines of the D21 review's astra call (codex-cli 0.155.1),
#: VERBATIM except the workdir path, anonymised for publication (the sha256 is of these bytes). Captured at progress/.golden-rev4/fix-round-1/codex-banner-0.155.1.stderr
#: and EMBEDDED, because this file runs in both trees and ~/.claude has no progress/
#: directory; the sha256 below is asserted, so an edit of the fixture fails. The
#: workdir line carries ANOTHER uuid (the session scratchpad's) -- see the banner-first
#: test.
_BANNER_0155_1 = (
    "Reading additional input from stdin...\n"
    "OpenAI Codex v0.155.1\n"
    "--------\n"
    "workdir: /tmp/claude-1000/-path-to-project/"
    "148bbc98-4e5f-4060-8444-37a973666792/scratchpad/d21clone\n"
    "model: gpt-6-astra\n"
    "provider: openai\n"
    "approval: never\n"
    "sandbox: read-only\n"
    "reasoning effort: xhigh\n"
    "reasoning summaries: none\n"
    "session id: 01a0cb17-355b-7f32-92f6-010c8f42b7d6\n"
    "--------\n"
)
_BANNER_0155_1_SHA256 = "7c0d297a7878e142859811f691f2f01fd8ee9335a58be0a6287d335aa0152f8f"
_BANNER_0155_1_ID = "01a0cb17-355b-7f32-92f6-010c8f42b7d6"
_BANNER_0155_1_WORKDIR_UUID = "148bbc98-4e5f-4060-8444-37a973666792"

#: The codex 0.154.0 banner, VERBATIM from test_audit_spawn_defaults.REAL_CODEX_0154_STDERR.
_BANNER_0154_0_ID = "01a0a02a-bdf9-7281-b75e-d9ce6c8f591b"
_BANNER_0154_0 = (
    "Reading additional input from stdin...\n"
    "OpenAI Codex v0.154.0\n"
    "--------\n"
    "workdir: /tmp/scratch\n"
    "model: gpt-5.6-sol\n"
    "provider: openai\n"
    "approval: never\n"
    "sandbox: read-only\n"
    "reasoning effort: xhigh\n"
    "reasoning summaries: none\n"
    "session id: 01a0a02a-bdf9-7281-b75e-d9ce6c8f591b\n"
    "--------\n"
    "user\n"
)

#: The codex 0.153.4 banner (test_audit_spawn_defaults.REAL_CODEX_STDERR): NO session id line.
_BANNER_0153_4_NO_ID = (
    "Reading additional input from stdin...\n"
    "OpenAI Codex v0.153.4\n"
    "--------\n"
    "workdir: /tmp/scratch\n"
    "model: gpt-5.6-sol\n"
    "provider: openai\n"
    "approval: never\n"
    "sandbox: read-only\n"
    "reasoning effort: low\n"
    "--------\n"
    "user\n"
    "Reply with exactly: OK\n"
)


def _streams(tmp_path, stdout="", stderr=""):
    out = tmp_path / "found.out"
    err = tmp_path / "found.err"
    out.write_text(stdout, encoding="utf-8")
    err.write_text(stderr, encoding="utf-8")
    return out, err


class TestX5F8TheBannerNamesTheSession:
    """D21 F8 (major): `_find_session_id` read only the `--json` key form, so the plain
    `codex exec` every caller runs -- whose stderr banner says `session id: <uuid>` --
    never yielded an id, the rollout was never located, and the rollout heartbeat was
    dead in production."""

    def test_x5_F8_the_embedded_0155_banner_is_the_captured_bytes(self):
        # INSTRUMENT: the fixture is the real capture, byte for byte.
        assert hashlib.sha256(_BANNER_0155_1.encode("utf-8")).hexdigest() == _BANNER_0155_1_SHA256
        assert _BANNER_0155_1.count("\n") == 12

    def test_x5_F8_major_the_real_0155_banner_names_its_session(self, tmp_path):
        out, err = _streams(tmp_path, stderr=_BANNER_0155_1)
        assert cw._find_session_id(out, err) == _BANNER_0155_1_ID

    def test_x5_F8_major_the_0154_banner_names_its_session(self, tmp_path):
        out, err = _streams(tmp_path, stderr=_BANNER_0154_0)
        assert cw._find_session_id(out, err) == _BANNER_0154_0_ID

    def test_x5_F8_major_the_banner_wins_over_the_workdir_uuid(self, tmp_path):
        """BANNER FIRST. The 0.155.1 banner's workdir line carries another uuid, and a
        prompt echoed after the banner can say `session_meta`. The `--json` key rule
        alone then returns the FIRST uuid in the text -- the workdir's, which names no
        rollout. The banner line is the id codex announced."""
        text = _BANNER_0155_1 + "user\nreview the session_meta handling in codex_watch.py\n"
        out, err = _streams(tmp_path, stderr=text)
        assert cw._find_session_id(out, err) == _BANNER_0155_1_ID
        # INSTRUMENT: the key rule on its own really does pick the workdir uuid here.
        assert cw._SESSION_KEY_RE.search(text)
        assert cw._SESSION_ID_RE.search(text).group(1) == _BANNER_0155_1_WORKDIR_UUID

    def test_x5_F8_major_a_later_session_line_does_not_displace_the_banner(self, tmp_path):
        """codex echoes the prompt onto stderr AFTER its banner; a prompt holding its own
        `session id:` line must not displace the real one (first match wins)."""
        other = "11111111-2222-3333-4444-555555555555"
        out, err = _streams(tmp_path, stderr=_BANNER_0154_0 + "session id: %s\n" % other)
        assert cw._find_session_id(out, err) == _BANNER_0154_0_ID

    def test_x5_F8_major_the_stderr_banner_wins_over_a_banner_shaped_line_on_stdout(self, tmp_path):
        """codex prints its banner on STDERR. A plain call's stdout is the model's own
        answer, which can say anything, so stderr is read first."""
        spoof = "session id: 22222222-3333-4444-5555-666666666666\n"
        out, err = _streams(tmp_path, stdout=spoof, stderr=_BANNER_0155_1)
        assert cw._find_session_id(out, err) == _BANNER_0155_1_ID

    def test_x5_F8_major_a_banner_line_still_being_written_is_not_read(self, tmp_path):
        """A poll can land mid-write. `session id: 01a0cb17-355b` with no newline yet
        would pass the regex (its `$` also matches at the end of the text) as a TRUNCATED
        id; only a completed line is read."""
        partial = _BANNER_0155_1[: _BANNER_0155_1.index(_BANNER_0155_1_ID) + 13]
        assert partial.endswith("session id: 01a0cb17-355b")
        out, err = _streams(tmp_path, stderr=partial)
        assert cw._find_session_id(out, err) is None
        err.write_text(_BANNER_0155_1, encoding="utf-8")
        assert cw._find_session_id(out, err) == _BANNER_0155_1_ID

    def test_x5_F8_control_the_json_key_form_still_resolves(self, tmp_path):
        session = "019efdb9-c573-7983-a75a-c1f0a33fde5e"
        out, err = _streams(tmp_path, stdout='{"type":"thread.started","thread_id":"%s"}\n' % session)
        assert cw._find_session_id(out, err) == session

    def test_x5_F8_control_no_session_id_anywhere_is_none(self, tmp_path):
        out, err = _streams(tmp_path, stdout="the answer\n", stderr=_BANNER_0153_4_NO_ID)
        assert cw._find_session_id(out, err) is None

    def test_x5_F8_control_a_glob_unsafe_id_is_not_a_banner_id(self, tmp_path):
        """The id is interpolated into a glob; the banner charset (hex and dashes) keeps
        `*`, `?`, `[` and path separators out of it."""
        out, err = _streams(tmp_path, stderr="session id: 0000000*-0000\nsession id: ../../abcdef01\n")
        assert cw._find_session_id(out, err) is None

    def test_x5_F8_the_banner_regex_is_public_and_moved_verbatim(self):
        """ONE definition (plan L40): codex_watch owns it and audit_spawn binds the same
        object (test_audit_spawn_defaults asserts the binding). Moved VERBATIM from
        audit_spawn, glob-safe charset included."""
        pattern = cw.CODEX_BANNER_SESSION_RE
        assert pattern.pattern == r"^session id:[ \t]*([0-9A-Fa-f][0-9A-Fa-f-]{7,63})[ \t]*$"
        assert pattern.flags & re.MULTILINE
        assert "CODEX_BANNER_SESSION_RE" in cw.__all__


class TestX5F8TheRolloutIsWhereTheChildWritesIt:
    def test_x5_F8_major_codex_home_relocates_the_sessions_dir(self, tmp_path, monkeypatch):
        """The child inherits the watchdog's environment, and codex relocates its whole
        home -- sessions included -- with CODEX_HOME. The watchdog looks where the CHILD
        writes (plan L40; codex_quota's meter not honouring CODEX_HOME is its own
        recorded limit, deliberately left as it is)."""
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "relocated"))
        assert cw._default_sessions_dir() == tmp_path / "relocated" / "sessions"

    @pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
    def test_x5_F8_control_an_unset_or_empty_codex_home_is_the_home_default(
        self, tmp_path, monkeypatch, value
    ):
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        if value is None:
            monkeypatch.delenv("CODEX_HOME", raising=False)
        else:
            monkeypatch.setenv("CODEX_HOME", value)
        assert cw._default_sessions_dir() == home / ".codex" / "sessions"


class _FakeCodexChild:
    """A FAKE `codex exec` child: NO process is started.

    It writes `announce` to the stream the watchdog handed it (codex prints its banner
    before the model call), then says NOTHING more on either stream, and "exits 0" once
    the injected clock reaches `exit_at`. `pid` names no process: `fake_codex` replaces
    the reap as well, so nothing is ever signalled.
    """

    def __init__(self, argv, kwargs, clock, exit_at, announce, stream):
        self.args = list(argv)
        self.kwargs = dict(kwargs)
        self.clock = clock
        self.exit_at = exit_at
        self.pid = None
        self.returncode = None
        self.stopped_by_watchdog = False
        handle = kwargs[stream]
        handle.write(announce.encode("utf-8"))
        handle.flush()

    def poll(self):
        if self.returncode is None and self.clock.t >= self.exit_at:
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        return self.poll()


@pytest.fixture
def fake_codex(monkeypatch):
    """Install `_FakeCodexChild` as Popen and a recorder as the reap; return a
    configure(clock, exit_at, announce, stream="stderr") -> children list."""
    children = []
    config = {}

    def popen(argv, **kwargs):
        child = _FakeCodexChild(argv, kwargs, config["clock"], config["exit_at"],
                                config["announce"], config["stream"])
        children.append(child)
        return child

    def reap(proc, _grace_s):
        proc.stopped_by_watchdog = True
        proc.returncode = -15
        return proc.returncode

    monkeypatch.setattr(cw.subprocess, "Popen", popen)
    monkeypatch.setattr(cw, "_terminate_and_reap", reap)

    def configure(clock, exit_at, announce, stream="stderr"):
        config.update(clock=clock, exit_at=exit_at, announce=announce, stream=stream)
        return children

    return configure


def _rollout_under(sessions_root, session_id):
    path = sessions_root / "2026" / "09" / "22" / ("rollout-2026-09-22T22-48-10-%s.jsonl" % session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return path


def _advancing(rollout):
    """on_sleep: the rollout's mtime moves one second per poll -- codex appending its
    reasoning events -- deterministically (explicit nanosecond stamps)."""
    state = {"ns": rollout.stat().st_mtime_ns}

    def on_sleep(_polls):
        state["ns"] += 1_000_000_000
        os.utime(rollout, ns=(state["ns"], state["ns"]))

    return on_sleep


class TestX5F8TheRolloutKeepsASilentCallAlive:
    """D21 F8 end to end, DETERMINISTIC: no process, an injected clock and sleep. A fake
    codex child prints its banner and then says nothing on either stream while the
    injected sleep advances its rollout's mtime. The call must run to the child's own end
    rather than be killed as idle at 300 s -- the D24 failure F8 reintroduced."""

    EXIT_AT_S = 900.0   # three idle timeouts; well short of the xhigh cap

    def _call(self, tmp_path, fake_codex, announce, rollout=None, stream="stderr"):
        clock = FakeClock(step=10.0, real=0.0, on_sleep=_advancing(rollout) if rollout else None)
        children = fake_codex(clock, self.EXIT_AT_S, announce, stream)
        out, err = tmp_path / "call.out", tmp_path / "call.err"
        # argv[0] is a path that does not exist: were the fake ever bypassed, Popen would
        # fail with FileNotFoundError rather than start anything real.
        result = run([str(tmp_path / "no-such-codex-binary"), "exec"], out, err,
                     effort="xhigh", clock=clock.now, sleep=clock.sleep)
        return result, children, out, err

    def test_x5_F8_major_the_banner_sessions_rollout_under_codex_home_is_a_heartbeat(
        self, tmp_path, monkeypatch, fake_codex
    ):
        codex_home = tmp_path / "codex-home"
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        rollout = _rollout_under(codex_home / "sessions", _BANNER_0155_1_ID)
        result, children, out, err = self._call(tmp_path, fake_codex, _BANNER_0155_1, rollout)
        assert (result.stop_reason, result.exit_code) == (cw.STOP_OK, 0)
        assert result.rollout_path == rollout
        assert result.max_silence_s < cw.IDLE_TIMEOUT_S, result.max_silence_s
        assert result.elapsed_s >= self.EXIT_AT_S
        assert len(children) == 1 and not children[0].stopped_by_watchdog
        # Neither byte counter moved after the banner: the rollout ALONE kept it alive.
        assert out.stat().st_size == 0
        assert err.read_text(encoding="utf-8") == _BANNER_0155_1

    def test_x5_F8_major_with_codex_home_unset_the_home_default_is_searched(
        self, tmp_path, monkeypatch, fake_codex
    ):
        home = tmp_path / "home"
        monkeypatch.delenv("CODEX_HOME", raising=False)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        rollout = _rollout_under(home / ".codex" / "sessions", _BANNER_0154_0_ID)
        result, children, _out, _err = self._call(tmp_path, fake_codex, _BANNER_0154_0, rollout)
        assert (result.stop_reason, result.exit_code) == (cw.STOP_OK, 0)
        assert result.rollout_path == rollout
        assert not children[0].stopped_by_watchdog

    def test_x5_F8_control_with_no_session_id_the_idle_stop_still_fires(
        self, tmp_path, monkeypatch, fake_codex
    ):
        """An advancing rollout that nothing NAMES is not this call's heartbeat."""
        codex_home = tmp_path / "codex-home"
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        rollout = _rollout_under(codex_home / "sessions", _BANNER_0155_1_ID)
        result, children, _out, _err = self._call(tmp_path, fake_codex, _BANNER_0153_4_NO_ID, rollout)
        assert (result.stop_reason, result.exit_code) == (cw.STOP_IDLE_TIMEOUT, cw.EXIT_IDLE_TIMEOUT)
        assert result.rollout_path is None
        assert result.max_silence_s >= cw.IDLE_TIMEOUT_S
        assert children[0].stopped_by_watchdog

    def test_x5_F8_control_another_sessions_rollout_is_not_a_heartbeat(
        self, tmp_path, monkeypatch, fake_codex
    ):
        codex_home = tmp_path / "codex-home"
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        rollout = _rollout_under(codex_home / "sessions", "33333333-4444-5555-6666-777777777777")
        result, children, _out, _err = self._call(tmp_path, fake_codex, _BANNER_0155_1, rollout)
        assert (result.stop_reason, result.exit_code) == (cw.STOP_IDLE_TIMEOUT, cw.EXIT_IDLE_TIMEOUT)
        assert result.rollout_path is None
        assert children[0].stopped_by_watchdog

    def test_x5_F8_control_the_json_key_form_still_finds_the_rollout(
        self, tmp_path, monkeypatch, fake_codex
    ):
        """CONTROL (green at the round base): the `--json` event form, under the HOME
        default the base already searched, still locates the rollout and keeps the call
        alive -- the banner-first rule did not displace it."""
        session = "019efdb9-c573-7983-a75a-c1f0a33fde5e"
        home = tmp_path / "home"
        monkeypatch.delenv("CODEX_HOME", raising=False)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        rollout = _rollout_under(home / ".codex" / "sessions", session)
        event = '{"type":"thread.started","thread_id":"%s"}\n' % session
        result, _children, _out, _err = self._call(tmp_path, fake_codex, event, rollout, stream="stdout")
        assert (result.stop_reason, result.exit_code) == (cw.STOP_OK, 0)
        assert result.rollout_path == rollout


#: codex_watch's HEARTBEAT SOURCES rollout bullet as it stood at the round base
#: (13a3e04), VERBATIM -- NEGATIVE CONTROL only (~/.claude is not a git repository, so
#: it is embedded, never read through git).
_X5_BASE_ROLLOUT_BULLET = """\
  * the session rollout file's mtime advanced. The rollout is located from the
    session id that `thread.started` / `session_meta` puts in the stream, then
    matched under ~/.codex/sessions/YYYY/MM/DD/rollout-*<session id>*.jsonl.
"""


def _x5_heartbeat_section(doc):
    start = doc.index("HEARTBEAT SOURCES")
    return doc[start:doc.index("THRESHOLDS", start)]


def _x5_heartbeat_doc_problems(section):
    problems = []
    if "session id: <uuid>" not in section:
        problems.append("does not name the banner line codex prints")
    if "CODEX_HOME" not in section:
        problems.append("does not name CODEX_HOME")
    if "session id that `thread.started` / `session_meta` puts in the stream, then" in section:
        problems.append("still says the id comes only from the --json events")
    return problems


def test_x5_F8_the_docstring_heartbeat_sources_name_the_banner_and_codex_home():
    assert _x5_heartbeat_doc_problems(_x5_heartbeat_section(cw.__doc__)) == []
    # NEGATIVE CONTROL: the base bullet trips all three.
    assert len(_x5_heartbeat_doc_problems("HEARTBEAT SOURCES\n" + _X5_BASE_ROLLOUT_BULLET)) == 3


# --------------------------------------------------------------------------- #
# F9 -- a stop signal to the watchdog must never orphan its child
# --------------------------------------------------------------------------- #
_POSIX_SIGNALS = pytest.mark.skipif(
    os.name != "posix" or not hasattr(signal, "SIGHUP"),
    reason="POSIX stop signals (SIGTERM / SIGHUP to a process) -- the F9 scenario",
)


def _deliver(signame):
    """Deliver `signame` as the interpreter does -- run the handler installed for it,
    NOW, in the main thread -- at exactly this point of the call."""
    signum = getattr(signal, signame)
    handler = signal.getsignal(signum)
    assert callable(handler), (
        "the watchdog holds no %s handler during the call (found %r)" % (signame, handler)
    )
    handler(signum, None)


@pytest.fixture
def restore_signal_handlers():
    """Whatever a test did, put back the runner's own stop-signal handlers."""
    saved = {}
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        signum = getattr(signal, name, None)
        if signum is not None:
            saved[signum] = signal.getsignal(signum)
    yield
    for signum, handler in saved.items():
        if handler is not None:
            signal.signal(signum, handler)


@pytest.fixture
def leftovers():
    """Every child a hooked Popen created. Any still running at teardown is killed and
    reaped, so a red run (base or mutant) never leaves a process behind."""
    procs = []
    yield procs
    for proc in procs:
        proc._first_wait = False
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def _hooked_popen(procs, *, on_return=None, on_first_wait=None):
    """A real Popen that records itself and can run a hook the instant it returns, or
    on the first wait() -- which is the watchdog's reap."""
    real_popen = subprocess.Popen

    class Hooked(real_popen):
        def __init__(self, *a, **kw):
            procs.append(self)
            self._first_wait = True
            super().__init__(*a, **kw)
            if on_return is not None:
                on_return()

        def wait(self, timeout=None):
            if self._first_wait and on_first_wait is not None:
                self._first_wait = False
                on_first_wait()
            return super().wait(timeout=timeout)

    return Hooked


def _watch_with(monkeypatch, **inject):
    """main() calls the REAL watch() with `inject` added; main() takes no clock or sleep."""
    real = cw.watch

    def watch_with(argv, **kwargs):
        kwargs.update(inject)
        return real(argv, **kwargs)

    monkeypatch.setattr(cw, "watch", watch_with)


def _sleep_hook(at, action):
    """A short REAL sleep that runs `action` on call number `at`."""
    state = {"n": 0}

    def sleep(_requested):
        state["n"] += 1
        if state["n"] == at:
            action()
        time.sleep(0.005)

    return sleep


def _cli(out, err, command, telemetry=False):
    args = ["--effort", "xhigh", "--poll-interval", "0.01",
            "--stdout-file", str(out), "--stderr-file", str(err)]
    if not telemetry:
        args.append("--no-telemetry")
    return args + ["--", *command]


def _finished(out, err, code):
    return cw.WatchResult(
        stop_reason=cw.STOP_OK, exit_code=code, child_exit_code=code, elapsed_s=0.0,
        max_silence_s=0.0, mode="codex", argv=("unused",), stdout_path=out, stderr_path=err,
        idle_timeout_s=float(cw.IDLE_TIMEOUT_S), hard_cap_s=2400.0,
    )


_SILENT = ("--lines", 0, "--stream", "none", "--hold", 30)


class TestX5F9TheStopLatch:
    """The latch main() installs as the SIGTERM / SIGHUP handler. Platform-neutral."""

    def test_x5_F9_a_stop_before_the_reap_is_armed_is_held_then_raised_on_arming(self):
        latch = cw._StopLatch()
        assert latch.handler(15, None) is None, "an unarmed stop is HELD, never raised"
        assert latch.signum == 15
        with pytest.raises(cw._StopSignal) as exc:
            latch.arm()
        assert exc.value.signum == 15

    def test_x5_F9_an_armed_latch_raises_the_first_stop_and_never_a_second(self):
        latch = cw._StopLatch()
        latch.arm()
        with pytest.raises(cw._StopSignal) as exc:
            latch.handler(1, None)
        assert exc.value.signum == 1
        # A second stop never raises: raised during the reap, it would abort it.
        assert latch.handler(15, None) is None
        assert latch.signum == 1, "the FIRST stop decides the exit code"

    def test_x5_F9_the_stop_is_a_base_exception_nothing_on_the_way_out_swallows(self):
        assert issubclass(cw._StopSignal, BaseException)
        assert not issubclass(cw._StopSignal, Exception)


class TestRecordOnlyLatch292:
    """#292: an in-process caller runs watch() on a WORKER thread; the signal handler runs
    on the main thread, so a record-only latch must never raise there, and the worker's
    poll loop must raise the stop and reap its child."""

    def test_a_record_only_handler_never_raises_even_when_armed(self):
        latch = cw._StopLatch(record_only=True)
        latch.armed = True
        assert latch.handler(15, None) is None
        assert latch.signum == 15

    def test_a_stop_latched_from_another_thread_reaps_the_worker_child(self, stub, paths, spawned):
        import threading

        latch = cw._StopLatch(record_only=True)
        out, err = paths
        caught = {}

        def worker():
            try:
                run(stub(*_SILENT), out, err, hard_cap_s=30.0, poll_interval_s=0.01, _stop_latch=latch)
            except cw._StopSignal as stop:
                caught["signum"] = stop.signum

        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 10
        while not spawned and time.monotonic() < deadline:
            time.sleep(0.01)
        assert spawned, "the child never started"
        # D21 codex F3: wait until watch() has ARMED, i.e. passed the arm() check and entered
        # its poll loop, so only the poll-loop check can catch the stop below.
        while not latch.armed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert latch.armed, "watch() never armed its latch"
        time.sleep(0.05)
        latch.handler(15, None)  # what the main thread's handler does on SIGTERM
        thread.join(timeout=10)
        assert not thread.is_alive(), "the worker ignored the latched stop"
        assert caught.get("signum") == 15
        assert spawned[0].returncode is not None, "the worker's child was orphaned"


@_POSIX_SIGNALS
@pytest.mark.usefixtures("restore_signal_handlers")
class TestX5F9TheCliReapsOnAStop:
    """D21 F9 (major), in process and deterministic: the stop is DELIVERED by calling the
    installed handler at a chosen point, exactly as the interpreter would."""

    @pytest.mark.parametrize("signame", ["SIGTERM", "SIGHUP"])
    def test_x5_F9_major_a_stop_mid_call_reaps_the_child_and_exits_128_plus_signum(
        self, stub, paths, monkeypatch, leftovers, signame
    ):
        monkeypatch.setattr(cw.subprocess, "Popen", _hooked_popen(leftovers))
        _watch_with(monkeypatch, sleep=_sleep_hook(3, lambda: _deliver(signame)))
        out, err = paths
        code = cw.main(_cli(out, err, stub(*_SILENT)))
        assert len(leftovers) == 1
        assert leftovers[0].returncode is not None, "the child outlived its watchdog's stop"
        assert code == 128 + getattr(signal, signame)

    def test_x5_F9_major_the_cli_holds_its_stop_handlers_only_for_the_call(self, monkeypatch, paths):
        def previous_term(_signum, _frame):
            pass

        def previous_hup(_signum, _frame):
            pass

        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(getattr(signal, "SIGHUP"), previous_hup)
        out, err = paths
        seen = []

        def fake_watch(_argv, **_kwargs):
            seen.append((signal.getsignal(signal.SIGTERM), signal.getsignal(getattr(signal, "SIGHUP"))))
            if len(seen) == 1:
                raise cw.CodexWatchError("refused before any spawn")
            return _finished(out, err, 5)

        monkeypatch.setattr(cw, "watch", fake_watch)
        assert cw.main(_cli(out, err, ["unused"])) == 2
        assert cw.main(_cli(out, err, ["unused"])) == 5
        assert len(seen) == 2
        for during_term, during_hup in seen:
            assert callable(during_term) and during_term is not previous_term
            assert callable(during_hup) and during_hup is not previous_hup
        # Restored on the error return AND on the normal one.
        assert signal.getsignal(signal.SIGTERM) is previous_term
        assert signal.getsignal(getattr(signal, "SIGHUP")) is previous_hup

    def test_x5_F9_major_a_stop_at_the_instant_popen_returns_is_not_lost(
        self, stub, paths, monkeypatch, leftovers
    ):
        """THE EARLY-ARMED REAP. The stop lands the instant the child exists -- before
        watch() has even bound the Popen object. The handler HOLDS a stop that lands
        before the reap is armed, and watch() raises it the moment it is."""
        monkeypatch.setattr(cw.subprocess, "Popen",
                            _hooked_popen(leftovers, on_return=lambda: _deliver("SIGTERM")))
        out, err = paths
        code = cw.main(_cli(out, err, stub(*_SILENT)))
        assert len(leftovers) == 1
        assert leftovers[0].returncode is not None, "the stop that landed at the spawn orphaned the child"
        assert code == 128 + signal.SIGTERM

    def test_x5_F9_major_a_second_stop_during_the_reap_does_not_abort_it(
        self, stub, paths, monkeypatch, leftovers
    ):
        monkeypatch.setattr(cw.subprocess, "Popen",
                            _hooked_popen(leftovers, on_first_wait=lambda: _deliver("SIGHUP")))
        _watch_with(monkeypatch, sleep=_sleep_hook(2, lambda: _deliver("SIGTERM")))
        out, err = paths
        code = cw.main(_cli(out, err, stub(*_SILENT)))
        assert leftovers[0].returncode is not None, "a second stop aborted the reap"
        assert code == 128 + signal.SIGTERM, "the FIRST stop decides the exit code"

    def test_x5_F9_major_a_first_stop_during_an_exception_reap_is_held(
        self, stub, paths, monkeypatch, leftovers
    ):
        """watch()'s `finally` also reaps for an exception that is NOT a stop (a failing
        clock, say). A stop landing DURING that reap is held -- raised there, it would
        abort the reap and orphan the child -- and the original exception propagates."""
        def fail():
            raise RuntimeError("the clock failed")

        monkeypatch.setattr(cw.subprocess, "Popen",
                            _hooked_popen(leftovers, on_first_wait=lambda: _deliver("SIGTERM")))
        _watch_with(monkeypatch, sleep=_sleep_hook(2, fail))
        out, err = paths
        with pytest.raises(RuntimeError, match="the clock failed"):
            cw.main(_cli(out, err, stub(*_SILENT)))
        assert leftovers[0].returncode is not None, "a stop during the reap aborted it"

    def test_x5_F9_major_a_stop_before_the_spawn_never_starts_the_child(
        self, stub, paths, monkeypatch, leftovers
    ):
        monkeypatch.setattr(cw.subprocess, "Popen", _hooked_popen(leftovers))
        real_cap = cw.hard_cap_for

        def cap(effort):
            _deliver("SIGTERM")
            return real_cap(effort)

        monkeypatch.setattr(cw, "hard_cap_for", cap)
        out, err = paths
        code = cw.main(_cli(out, err, stub(*_SILENT)))
        assert (code, leftovers) == (128 + signal.SIGTERM, [])

    def test_x5_F9_major_a_stop_after_the_reap_still_exits_128_plus_signum(
        self, stub, paths, monkeypatch, leftovers
    ):
        """The child is already reaped when the stop lands (telemetry is being written):
        nothing to orphan, but the caller asked the watchdog to stop, and says so."""
        monkeypatch.setattr(cw.subprocess, "Popen", _hooked_popen(leftovers))
        monkeypatch.setattr(cw, "_record_telemetry", lambda _result, _extra=None: _deliver("SIGHUP"))
        out, err = paths
        code = cw.main(_cli(out, err, stub("--lines", 1), telemetry=True))
        assert leftovers[0].returncode == 0, "the child finished on its own"
        assert code == 128 + getattr(signal, "SIGHUP")

    def test_x5_F9_an_ignored_stop_signal_stays_ignored(self, monkeypatch, paths):
        """`nohup` (or any caller) that IGNORES SIGHUP chose to survive a hangup. The
        watchdog leaves an ignored signal ignored -- a signal that cannot stop the
        watchdog cannot orphan its child -- and still takes SIGTERM."""
        sighup = getattr(signal, "SIGHUP")
        signal.signal(sighup, signal.SIG_IGN)
        out, err = paths
        seen = []

        def fake_watch(_argv, **_kwargs):
            seen.append((signal.getsignal(signal.SIGTERM), signal.getsignal(sighup)))
            return _finished(out, err, 0)

        monkeypatch.setattr(cw, "watch", fake_watch)
        assert cw.main(_cli(out, err, ["unused"])) == 0
        during_term, during_hup = seen[0]
        assert during_hup == signal.SIG_IGN
        assert callable(during_term)
        assert signal.getsignal(sighup) == signal.SIG_IGN


#: Runs the watchdog CLI's own `__main__` with the stop signals at their DEFAULT
#: dispositions and SIGINT as KeyboardInterrupt, whatever the test runner inherited (a
#: background shell ignores SIGINT; nohup ignores SIGHUP).
_CLI_LAUNCHER = (
    "import runpy, signal, sys\n"
    "meta, script, args = sys.argv[1], sys.argv[2], sys.argv[3:]\n"
    "signal.signal(signal.SIGTERM, signal.SIG_DFL)\n"
    "signal.signal(signal.SIGHUP, signal.SIG_DFL)\n"
    "signal.signal(signal.SIGINT, signal.default_int_handler)\n"
    "sys.path.insert(0, meta)\n"
    "sys.argv = [script] + args\n"
    "runpy.run_path(script, run_name='__main__')\n"
)

_PID_SLEEPER = '''#!/usr/bin/env python3
"""F9 stub: record my pid atomically, then sleep silently (bounded)."""
import os
import sys
import time

tmp = sys.argv[1] + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))
os.replace(tmp, sys.argv[1])
end = time.time() + 120.0
while time.time() < end:
    time.sleep(0.2)
'''


@_POSIX_SIGNALS
class TestX5F9TheRealCliUnderASignal:
    """D21 F9, OUTCOME-BASED against the real CLI in its own process: the watchdog's exit
    code and whether its child's pid still exists. No elapsed-window assertion; every wait
    has a generous bound; teardown kills any survivor BY PID."""

    def _start(self, tmp_path):
        sleeper = tmp_path / "stub_pid_sleeper.py"
        sleeper.write_text(_PID_SLEEPER, encoding="utf-8")
        sleeper.chmod(sleeper.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
        pidfile = tmp_path / "child.pid"
        argv = [sys.executable, "-c", _CLI_LAUNCHER, str(_META), str(_META / "codex_watch.py"),
                "--mode", "codex", "--effort", "xhigh", "--no-telemetry", "--poll-interval", "0.05",
                "--stdout-file", str(tmp_path / "call.out"), "--stderr-file", str(tmp_path / "call.err"),
                "--", str(sleeper), str(pidfile)]
        watchdog = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return watchdog, pidfile, sleeper

    @staticmethod
    def _await_child(pidfile, watchdog):
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if pidfile.exists():
                return int(pidfile.read_text(encoding="utf-8"))
            assert watchdog.poll() is None, "the watchdog exited before its child started"
            time.sleep(0.05)
        pytest.fail("the child never started")

    @staticmethod
    def _alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _gone_within(self, pid, bound_s):
        deadline = time.monotonic() + bound_s
        while time.monotonic() < deadline:
            if not self._alive(pid):
                return True
            time.sleep(0.05)
        return not self._alive(pid)

    def _kill_survivors(self, watchdog, pid, sleeper):
        if watchdog.poll() is None:
            watchdog.kill()
            watchdog.wait(timeout=30)
        if pid is None or not self._alive(pid):
            return
        proc_dir = Path("/proc")
        if proc_dir.is_dir():
            try:
                if str(sleeper).encode("utf-8") not in (proc_dir / str(pid) / "cmdline").read_bytes():
                    return  # the pid was reused by something that is not our stub
            except OSError:
                return
        os.kill(pid, signal.SIGKILL)

    @pytest.mark.parametrize("signame", ["SIGTERM", "SIGHUP"])
    def test_x5_F9_major_a_stop_signal_to_the_watchdog_never_orphans_its_child(self, tmp_path, signame):
        signum = getattr(signal, signame)
        watchdog, pidfile, sleeper = self._start(tmp_path)
        pid = None
        try:
            pid = self._await_child(pidfile, watchdog)
            watchdog.send_signal(signum)
            code = watchdog.wait(timeout=60)
            gone = self._gone_within(pid, 30.0)
            assert (gone, code) == (True, 128 + signum), (
                "child %d still alive: %s; watchdog exit %s" % (pid, not gone, code)
            )
        finally:
            self._kill_survivors(watchdog, pid, sleeper)

    def test_x5_F9_control_sigint_still_reaps_the_child(self, tmp_path):
        """CONTROL (green at the round base): Ctrl-C was always reaped -- KeyboardInterrupt
        runs watch()'s `finally`. What F9 adds is the same for SIGTERM and SIGHUP."""
        watchdog, pidfile, sleeper = self._start(tmp_path)
        pid = None
        try:
            pid = self._await_child(pidfile, watchdog)
            watchdog.send_signal(signal.SIGINT)
            watchdog.wait(timeout=60)
            assert self._gone_within(pid, 30.0), "child %d outlived a Ctrl-C to its watchdog" % pid
        finally:
            self._kill_survivors(watchdog, pid, sleeper)


# --------------------------------------------------------------------------- #
# f9 -- a progress interval that is not a finite positive number
# --------------------------------------------------------------------------- #
_BAD_INTERVALS = [0, 0.0, -1, -0.5, float("nan"), float("inf"), float("-inf"), True, "60"]


class TestX5f9TheProgressIntervalIsValidated:
    """D21 f9 (minor): `--progress-interval 0` spun forever in `next_progress += 0`, past
    the idle timeout and the hard cap, after the child had exited."""

    @pytest.mark.parametrize("bad", _BAD_INTERVALS,
                             ids=["0", "0.0", "-1", "-0.5", "nan", "inf", "-inf", "True", "str"])
    def test_x5_f9_minor_an_interval_that_is_not_finite_and_positive_is_refused_before_the_spawn(
        self, stub, paths, spawned, bad
    ):
        out, err = paths
        with pytest.raises(cw.CodexWatchError, match="progress interval"):
            run(stub("--lines", 1), out, err, effort="xhigh", progress_interval_s=bad)
        assert spawned == [], "the refusal must come BEFORE any child is started"

    @pytest.mark.parametrize("bad", ["0", "-1", "nan"])
    def test_x5_f9_minor_the_cli_exits_2_before_spawning(self, stub, paths, spawned, capsys, bad):
        out, err = paths
        code = cw.main([
            "--effort", "xhigh", "--no-telemetry", "--stdout-file", str(out),
            "--stderr-file", str(err), "--progress-interval", bad, "--", *stub("--lines", 1),
        ])
        assert code == 2
        assert "progress interval" in capsys.readouterr().err
        assert spawned == []


# =========================================================================== #
# S081 revision 4, D21 fix round 2 -- WP-Y1: N1 (a stop landing during the
# progress write), R2-12 (the poll interval) and R2-12b (the hard cap and the idle
# timeout). Review: docs/reviews/2026-09-22-S081-rev4-review.md. Every test below
# is NEW, so none is flake-eligible, and NONE STARTS A PROCESS: the child is the
# `fake_codex` stand-in (argv[0] names a path that does not exist, so a bypassed
# fake fails rather than runs anything), time is a FakeClock that advances only
# when the watchdog sleeps, and no assertion reads a real elapsed window.
# =========================================================================== #
def _y1_argv(tmp_path):
    return [str(tmp_path / "no-such-codex-binary"), "exec"]


def _y1_agy_argv(tmp_path):
    return [str(tmp_path / "no-such-agy-binary"), "--sandbox", "-p", "advisory only"]


def _y1_paths(tmp_path):
    return tmp_path / "call.out", tmp_path / "call.err"


class _Y1Stream(io.StringIO):
    """A progress stream that runs `on_write` / `on_flush` INSIDE the watchdog's progress write -- the
    point where a stop can land while a line is being printed -- and counts the lines it was handed."""

    def __init__(self, on_write=None, on_flush=None):
        super().__init__()
        self.writes = 0
        self.on_write = on_write
        self.on_flush = on_flush

    def write(self, text):
        self.writes += 1
        if self.on_write is not None:
            self.on_write()
        return super().write(text)

    def flush(self):
        if self.on_flush is not None:
            self.on_flush()
        return super().flush()

    def close(self):
        # Garbage collection closes (and so flushes) the stream: never re-run a hook then.
        self.on_write = self.on_flush = None
        super().close()


def _y1_raiser(exc):
    def hook():
        raise exc
    return hook


class TestY1N1AStopDuringTheProgressWriteStopsTheCall:
    """D21 fix round 2, N1 (MAJOR as approved; astra D21-1 = fable-r2-1). The progress write sat in
    `except BaseException: pass`, which also caught the _StopSignal the latch raises while the reap is
    armed; the latch keeps only the FIRST stop, so every later SIGTERM / SIGHUP was a no-op and the call
    ran on to its own end, its idle stop or its hard cap -- a caller that asked for a stop got a whole
    call's quota spend. Here the child is silent after it spawns and would exit on its own at t=900;
    the first progress line is written at t=60, so a stop that lands in it must end the call at t=60."""

    EXIT_AT_S = 900.0
    STOP_TICK_S = float(cw.PROGRESS_INTERVAL_S)   # the first progress line

    @pytest.mark.parametrize("where", ["write", "flush"])
    def test_y1_N1_major_a_stop_during_the_progress_write_propagates_and_reaps_at_that_tick(
        self, tmp_path, fake_codex, where
    ):
        latch = cw._StopLatch()

        def deliver():
            latch.handler(signal.SIGTERM, None)

        stream = _Y1Stream(on_write=deliver) if where == "write" else _Y1Stream(on_flush=deliver)
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, self.EXIT_AT_S, "")
        out, err = _y1_paths(tmp_path)
        with pytest.raises(cw._StopSignal) as stop:
            run(_y1_argv(tmp_path), out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
                progress_stream=stream, _stop_latch=latch)
        assert stop.value.signum == signal.SIGTERM
        assert len(children) == 1 and children[0].stopped_by_watchdog, "the finally did not reap the child"
        assert clock.t == self.STOP_TICK_S, "the call polled on after the stop, to t=%s" % clock.t
        assert stream.writes == 1, "the stop landed in the FIRST progress line; %d were written" % stream.writes

    @_POSIX_SIGNALS
    @pytest.mark.usefixtures("restore_signal_handlers")
    @pytest.mark.parametrize("signame", ["SIGTERM", "SIGHUP"])
    def test_y1_N1_major_the_cli_reaps_at_the_tick_a_stop_lands_in_the_progress_write(
        self, tmp_path, monkeypatch, fake_codex, signame
    ):
        """THE CLI PATH: main() installs the latch as the SIGTERM / SIGHUP handler and the stop is
        delivered through the INSTALLED handler from inside the progress write. The exit code was
        128+N at the round base as well -- after the call had run on -- so the assertion is on WHEN and
        HOW the child stopped: reaped by the watchdog at the stop tick, never at its own end or at an
        idle / cap stop."""
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, self.EXIT_AT_S, "")
        reaped_at = []
        fake_reap = cw._terminate_and_reap

        def reap(proc, grace_s):
            reaped_at.append(clock.t)
            return fake_reap(proc, grace_s)

        monkeypatch.setattr(cw, "_terminate_and_reap", reap)
        stream = _Y1Stream(on_write=lambda: _deliver(signame))
        _watch_with(monkeypatch, clock=clock.now, sleep=clock.sleep, progress_stream=stream)
        out, err = _y1_paths(tmp_path)
        code = cw.main(_cli(out, err, _y1_argv(tmp_path)))
        assert code == 128 + getattr(signal, signame)
        assert reaped_at == [self.STOP_TICK_S], (
            "the child was reaped at t=%s, not at the stop tick t=%s" % (reaped_at, self.STOP_TICK_S)
        )
        assert children[0].stopped_by_watchdog and stream.writes == 1

    def test_y1_N1_major_a_ctrl_c_during_the_progress_write_propagates_and_reaps(self, tmp_path, fake_codex):
        """N1's same-handler red (plan L53): the line swallowed a KeyboardInterrupt too, since 13a3e04.
        A Ctrl-C is a stop request; it now reaches watch()'s `finally` like one landing anywhere else."""
        stream = _Y1Stream(on_write=_y1_raiser(KeyboardInterrupt))
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, self.EXIT_AT_S, "")
        out, err = _y1_paths(tmp_path)
        with pytest.raises(KeyboardInterrupt):
            run(_y1_argv(tmp_path), out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
                progress_stream=stream)
        assert children[0].stopped_by_watchdog, "the finally did not reap the child"
        assert clock.t == self.STOP_TICK_S and stream.writes == 1

    @pytest.mark.parametrize("failure", ["closed", "broken_pipe", "oserror_on_flush", "unencodable"])
    def test_y1_N1_control_a_failing_progress_stream_never_stops_the_call(self, tmp_path, fake_codex, failure):
        """CONTROL (green at the round base): every way a progress stream FAILS is an Exception, and a
        failed line never stops a call. The child exits on its own at t=200, after three lines."""
        if failure == "closed":
            stream = io.StringIO()
            stream.close()                         # write() -> ValueError: I/O operation on closed file
        elif failure == "broken_pipe":
            stream = _Y1Stream(on_write=_y1_raiser(BrokenPipeError(32, "Broken pipe")))
        elif failure == "oserror_on_flush":
            stream = _Y1Stream(on_flush=_y1_raiser(OSError(5, "Input/output error")))
        else:
            stream = _Y1Stream(on_write=_y1_raiser(
                UnicodeEncodeError("cp1252", "\u2014", 0, 1, "character maps to <undefined>")))
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 200.0, "")
        out, err = _y1_paths(tmp_path)
        result = run(_y1_argv(tmp_path), out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
                     progress_stream=stream)
        assert (result.stop_reason, result.exit_code) == (cw.STOP_OK, 0)
        assert clock.t == 200.0 and not children[0].stopped_by_watchdog
        assert len(result.progress_lines) == 3


# --------------------------------------------------------------------------- #
# N1 -- the SWEEP (plan L54), encoded as a STRUCTURE guard over the module source
# --------------------------------------------------------------------------- #
#: The names whose handler can catch a stop request: a bare `except` is the third case.
_Y1_STOP_CATCHERS = {"BaseException", "_StopSignal"}


def _y1_is_disarm(stmt):
    """True when `stmt` holds the finally's `latch.armed = False`."""
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Attribute) and t.attr == "armed" for t in node.targets)
        and isinstance(node.value, ast.Constant) and node.value.value is False
        for node in ast.walk(stmt)
    )


def _y1_armed_window(source):
    """(handlers, reached) for watch()'s ARMED WINDOW in `source`.

    The window is the body of watch()'s try whose `finally` disarms the latch -- a superset by one
    statement, the spawn, where a stop is only ever HELD -- plus, transitively, every function of the
    module that body calls by name: a function nested in watch(), a module-level function, a method of
    a module-level class it names, or a module-level class method it calls by attribute. The finally is
    NOT in the window (after the disarm the latch never raises). Caller-owned callables (clock, sleep,
    the progress stream) and the standard library are outside the module and out of its reach.
    `handlers` is [(where, lineno, ExceptHandler)], each handler once; `reached` names what was walked."""
    tree = ast.parse(source)
    module_funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    methods = {}
    for cls in classes.values():
        for node in cls.body:
            if isinstance(node, ast.FunctionDef):
                methods.setdefault(node.name, []).append(("%s.%s" % (cls.name, node.name), node))
    watch = module_funcs["watch"]
    local_funcs = {n.name: n for n in ast.walk(watch) if isinstance(n, ast.FunctionDef) and n is not watch}
    tries = [n for n in ast.walk(watch)
             if isinstance(n, ast.Try) and any(_y1_is_disarm(s) for s in n.finalbody)]
    assert len(tries) == 1, "expected ONE try whose finally disarms the latch, found %d" % len(tries)
    queue = [("watch() try body", tries[0].body)]
    reached, handlers = set(), {}
    while queue:
        where, body = queue.pop(0)
        for stmt in body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.ExceptHandler):
                    handlers.setdefault(id(node), (where, node.lineno, node))
                if not isinstance(node, ast.Call):
                    continue
                func, targets = node.func, []
                if isinstance(func, ast.Name):
                    if func.id in local_funcs:
                        targets.append((func.id, local_funcs[func.id]))
                    elif func.id in module_funcs:
                        targets.append((func.id, module_funcs[func.id]))
                    elif func.id in classes:
                        targets += [("%s.%s" % (func.id, m.name), m) for m in classes[func.id].body
                                    if isinstance(m, ast.FunctionDef)]
                elif isinstance(func, ast.Attribute) and func.attr in methods:
                    targets += methods[func.attr]
                for name, fn in targets:
                    if name not in reached:
                        reached.add(name)
                        queue.append((name + "()", fn.body))
    return sorted(handlers.values(), key=lambda h: h[1]), reached


def _y1_catches_a_stop(handler):
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names = {t.id if isinstance(t, ast.Name) else getattr(t, "attr", None) for t in types}
    return bool(names & _Y1_STOP_CATCHERS)


def _y1_reraises(handler):
    last = handler.body[-1] if handler.body else None
    return isinstance(last, ast.Raise) and last.exc is None


def _y1_swallowers(source):
    """Every handler in the armed window that can catch a stop and does not end in a bare `raise`."""
    handlers, _reached = _y1_armed_window(source)
    return ["%s line %d" % (where, lineno) for where, lineno, h in handlers
            if _y1_catches_a_stop(h) and not _y1_reraises(h)]


_Y1_SYNTHETIC = '''
class _StopSignal(BaseException):
    pass

def helper():
    try:
        return 1
    except {helper_catch}:
        {helper_body}

def watch(latch):
    try:
        latch.arm()
        try:
            helper()
        except {window_catch}:
            {window_body}
    finally:
        latch.armed = False
        try:
            helper()
        except {finally_catch}:
            pass
'''


def _y1_synthetic(helper_catch="OSError", helper_body="return None", window_catch="OSError",
                  window_body="pass", finally_catch="OSError"):
    return _Y1_SYNTHETIC.format(helper_catch=helper_catch, helper_body=helper_body, window_catch=window_catch,
                                window_body=window_body, finally_catch=finally_catch)


def test_y1_N1_sweep_the_guard_trips_on_a_swallowing_handler_and_only_there():
    """INSTRUMENT / NEGATIVE CONTROLS (green at the round base): the guard is shown to fire before it is
    trusted, on synthetic source shaped like watch()."""
    assert _y1_swallowers(_y1_synthetic()) == []
    # A swallowing handler inside the try trips it -- BaseException, a bare except, _StopSignal, a tuple.
    for catch in ("BaseException", "_StopSignal", "(OSError, _StopSignal)"):
        assert _y1_swallowers(_y1_synthetic(window_catch=catch)) == ["watch() try body line 16"], catch
    assert _y1_swallowers(_y1_synthetic().replace("except OSError:\n            pass\n    finally",
                                                  "except:\n            pass\n    finally")) \
        == ["watch() try body line 16"]
    # The same handler ending in a bare `raise` does not.
    assert _y1_swallowers(_y1_synthetic(window_catch="BaseException", window_body="raise")) == []
    # One inside the finally, after the disarm, does not.
    assert _y1_swallowers(_y1_synthetic(finally_catch="BaseException")) == []
    # A helper the window calls is IN the window, transitively.
    assert _y1_swallowers(_y1_synthetic(helper_catch="BaseException")) == ["helper() line 8"]
    # Catching Exception (what a failing stream raises) is not a stop catcher.
    assert _y1_swallowers(_y1_synthetic(window_catch="Exception")) == []


def test_y1_N1_sweep_no_handler_in_the_armed_window_can_swallow_a_stop():
    """STRUCTURE (plan L54): no except-handler reachable while the reap is armed catches BaseException,
    a bare except or _StopSignal unless it ends in a bare `raise`. At the round base the progress
    write's `except BaseException: pass` was the one that did (N1)."""
    source = Path(cw.__file__).read_text(encoding="utf-8")
    handlers, reached = _y1_armed_window(source)
    # INSTRUMENT: the walk really reached the module functions the window calls, transitively.
    assert {"_activity", "_spawn", "_size", "_mtime_ns", "_find_session_id", "_tail_text", "_complete_lines",
            "_default_sessions_dir", "_find_rollout", "_terminate_and_reap", "_StopLatch.arm"} <= reached, reached
    assert len(handlers) >= 6, handlers
    assert _y1_swallowers(source) == []


#: codex_watch's STOP SIGNALS section as it stood at the round base (615231b), its closing lines
#: VERBATIM -- NEGATIVE CONTROL only (~/.claude is not a git repository, so it is embedded).
_Y1_BASE_STOP_SIGNALS_TAIL = """\
  * a signal the caller IGNORES (`nohup` ignores SIGHUP) stays ignored: it
    cannot stop the watchdog, so it cannot orphan the child either.

SIGINT keeps Python's KeyboardInterrupt, which always ran the `finally`.

"""


def _y1_stop_signals_section(doc):
    start = doc.index("STOP SIGNALS (")
    # #292 removed the RECORDED LIMIT note that used to close this section.
    return doc[start:doc.index("TELEMETRY\n---", start)]


def _y1_stop_doc_problems(section):
    flat = " ".join(section.split())
    problems = []
    if "A stream failure never stops a call" not in flat:
        problems.append("does not say a stream failure never stops a call")
    if "a stop request always does, the progress write included" not in flat:
        problems.append("does not say a stop request stops it, the progress write included")
    return problems


def test_y1_N1_the_stop_signals_doc_states_the_progress_write_rule():
    """GUARD (plan L53's one STOP SIGNALS sentence)."""
    assert _y1_stop_doc_problems(_y1_stop_signals_section(cw.__doc__)) == []
    # NEGATIVE CONTROL: the base text trips both.
    assert len(_y1_stop_doc_problems("STOP SIGNALS (\n" + _Y1_BASE_STOP_SIGNALS_TAIL)) == 2


# --------------------------------------------------------------------------- #
# R2-12 -- the poll interval; R2-12b -- the hard cap and the idle timeout
# --------------------------------------------------------------------------- #
_Y1_BAD_SECONDS = [0, 0.0, -1, -0.5, float("nan"), float("inf"), float("-inf"), True, "60"]
_Y1_BAD_IDS = ["0", "0.0", "-1", "-0.5", "nan", "inf", "-inf", "True", "str"]


class TestY1R2_12ThePollIntervalIsValidated:
    """D21 fix round 2, R2-12 (minor; WP-X5 FOUND 1): `--poll-interval` / poll_interval_s reached
    `sleep()` unchecked -- -1, NaN and a string raised AFTER the spawn, 0 busy-polled at full CPU, +inf
    and True were accepted. The same checker as the progress interval (f9) now refuses them first."""

    @pytest.mark.parametrize("bad", _Y1_BAD_SECONDS, ids=_Y1_BAD_IDS)
    def test_y1_R2_12_minor_a_poll_interval_that_is_not_finite_and_positive_is_refused_before_the_spawn(
        self, tmp_path, fake_codex, bad
    ):
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        out, err = _y1_paths(tmp_path)
        with pytest.raises(cw.CodexWatchError, match="poll interval"):
            run(_y1_argv(tmp_path), out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
                poll_interval_s=bad)
        assert children == [], "the refusal must come BEFORE any child is started"

    @pytest.mark.usefixtures("restore_signal_handlers")
    @pytest.mark.parametrize("bad", ["0", "-1", "nan"])
    def test_y1_R2_12_minor_the_cli_exits_2_before_spawning(self, tmp_path, monkeypatch, fake_codex, capsys, bad):
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        _watch_with(monkeypatch, clock=clock.now, sleep=clock.sleep)
        out, err = _y1_paths(tmp_path)
        code = cw.main(["--effort", "xhigh", "--no-telemetry", "--stdout-file", str(out), "--stderr-file", str(err),
                        "--poll-interval", bad, "--", *_y1_argv(tmp_path)])
        assert code == 2
        assert "poll interval" in capsys.readouterr().err
        assert children == []

    @pytest.mark.parametrize("good", [0.01, 0.02, 0.05, 1.0, 1], ids=["0.01", "0.02", "0.05", "1.0", "int-1"])
    def test_y1_R2_12_control_the_intervals_callers_pass_are_accepted_and_slept(self, tmp_path, fake_codex, good):
        """CONTROL (green at the round base): 0.01 and 0.02 (audit_spawn's tests), 0.05 (the forge
        harness), the 1.0 default -- accepted, and each poll sleeps exactly that long."""
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        slept = []

        def sleep(requested):
            slept.append(requested)
            clock.sleep(requested)

        out, err = _y1_paths(tmp_path)
        result = run(_y1_argv(tmp_path), out, err, effort="xhigh", clock=clock.now, sleep=sleep,
                     poll_interval_s=good)
        assert result.stop_reason == cw.STOP_OK and len(children) == 1
        assert slept and set(slept) == {good}


_Y1_QUANTITIES = [("hard_cap_s", "hard cap"), ("idle_timeout_s", "idle timeout")]
_Y1_QUANTITY_IDS = ["hard_cap", "idle_timeout"]


class TestY1R2_12bTheHardCapAndTheIdleTimeoutAreValidated:
    """D21 fix round 2, R2-12b (minor; the revision-43 compile's found item (1), folded in at revision
    44): a CALLER-SUPPLIED hard cap or idle timeout reached the loop unchecked. NaN or +inf DISABLED the
    stop (`elapsed >= nan` is always False: a NaN cap let a talking child run past its effort's cap, a NaN
    idle timeout let a silent one run to the cap); 0 or a negative stopped the call the instant it
    spawned; a string raised AFTER the spawn; True was a 1 s stop. None keeps its meaning: the effort's
    own cap, the mode's idle default -- and in agy mode, NO idle stop at all."""

    @pytest.mark.parametrize("kwarg,quantity", _Y1_QUANTITIES, ids=_Y1_QUANTITY_IDS)
    @pytest.mark.parametrize("bad", _Y1_BAD_SECONDS, ids=_Y1_BAD_IDS)
    def test_y1_R2_12b_minor_a_value_that_is_not_finite_and_positive_is_refused_before_the_spawn(
        self, tmp_path, fake_codex, bad, kwarg, quantity
    ):
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        out, err = _y1_paths(tmp_path)
        with pytest.raises(cw.CodexWatchError, match=quantity):
            run(_y1_argv(tmp_path), out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep, **{kwarg: bad})
        assert children == [], "the refusal must come BEFORE any child is started"

    @pytest.mark.parametrize("kwarg,quantity", _Y1_QUANTITIES, ids=_Y1_QUANTITY_IDS)
    @pytest.mark.parametrize("bad", [0, float("nan")], ids=["0", "nan"])
    def test_y1_R2_12b_minor_an_explicit_agy_value_is_checked_too(self, tmp_path, fake_codex, bad, kwarg, quantity):
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        out, err = _y1_paths(tmp_path)
        with pytest.raises(cw.CodexWatchError, match=quantity):
            run(_y1_agy_argv(tmp_path), out, err, mode="agy", clock=clock.now, sleep=clock.sleep, **{kwarg: bad})
        assert children == []

    @pytest.mark.usefixtures("restore_signal_handlers")
    @pytest.mark.parametrize("flag,value,quantity", [
        ("--hard-cap", "nan", "hard cap"), ("--hard-cap", "0", "hard cap"), ("--hard-cap", "-1", "hard cap"),
        ("--idle-timeout", "nan", "idle timeout"), ("--idle-timeout", "0", "idle timeout"),
        ("--idle-timeout", "inf", "idle timeout"),
    ], ids=["hard-cap-nan", "hard-cap-0", "hard-cap--1", "idle-timeout-nan", "idle-timeout-0", "idle-timeout-inf"])
    def test_y1_R2_12b_minor_the_cli_exits_2_before_spawning(
        self, tmp_path, monkeypatch, fake_codex, capsys, flag, value, quantity
    ):
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        _watch_with(monkeypatch, clock=clock.now, sleep=clock.sleep)
        out, err = _y1_paths(tmp_path)
        code = cw.main(["--effort", "xhigh", "--no-telemetry", "--stdout-file", str(out), "--stderr-file", str(err),
                        flag, value, "--", *_y1_argv(tmp_path)])
        assert code == 2
        assert quantity in capsys.readouterr().err
        assert children == []

    @pytest.mark.parametrize("effort", sorted(cw.HARD_CAP_S))
    def test_y1_R2_12b_control_none_derives_the_efforts_cap_and_the_codex_idle_default(
        self, tmp_path, fake_codex, effort
    ):
        """CONTROL (green at the round base): only a CALLER-SUPPLIED value is checked."""
        clock = FakeClock(step=10.0, real=0.0)
        fake_codex(clock, 30.0, "")
        out, err = _y1_paths(tmp_path)
        result = run(_y1_argv(tmp_path), out, err, effort=effort, clock=clock.now, sleep=clock.sleep,
                     hard_cap_s=None, idle_timeout_s=None)
        assert (result.hard_cap_s, result.idle_timeout_s) == (cw.HARD_CAP_S[effort], cw.IDLE_TIMEOUT_S)

    def test_y1_R2_12b_control_in_agy_mode_none_still_means_no_idle_stop(self, tmp_path, fake_codex):
        """CONTROL (green at the round base): the agy default is the None SENTINEL, never a number the
        checker could refuse -- a child silent for 400 s (past the codex 300 s idle stop) finishes."""
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 400.0, "")
        out, err = _y1_paths(tmp_path)
        result = run(_y1_agy_argv(tmp_path), out, err, mode="agy", clock=clock.now, sleep=clock.sleep)
        assert (result.stop_reason, result.idle_timeout_s, result.hard_cap_s) == (cw.STOP_OK, None, cw.AGY_HARD_CAP_S)
        assert result.max_silence_s >= cw.IDLE_TIMEOUT_S and not children[0].stopped_by_watchdog

    def test_y1_R2_12b_control_an_explicit_agy_idle_timeout_is_still_honoured(self, tmp_path, fake_codex):
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 400.0, "")
        out, err = _y1_paths(tmp_path)
        result = run(_y1_agy_argv(tmp_path), out, err, mode="agy", idle_timeout_s=120, clock=clock.now,
                     sleep=clock.sleep)
        assert (result.stop_reason, result.idle_timeout_s) == (cw.STOP_IDLE_TIMEOUT, 120)
        assert clock.t == 120.0 and children[0].stopped_by_watchdog

    @pytest.mark.parametrize("kwarg,good", [
        ("idle_timeout_s", 0.5), ("idle_timeout_s", 1), ("idle_timeout_s", 1.0), ("idle_timeout_s", 30),
        ("idle_timeout_s", 120), ("hard_cap_s", 1.0), ("hard_cap_s", 30.0), ("hard_cap_s", 600),
        ("hard_cap_s", 2400.0), ("hard_cap_s", 3600),
    ], ids=["idle-0.5", "idle-1", "idle-1.0", "idle-30", "idle-120", "cap-1.0", "cap-30.0", "cap-600",
            "cap-2400.0", "cap-3600"])
    def test_y1_R2_12b_control_every_value_the_callers_pass_is_accepted(self, tmp_path, fake_codex, kwarg, good):
        """CONTROL (green at the round base): the values measured at the revision-44 fold -- the in-process
        tests' idle 0.5-120 and caps 1.0-2400, the CLI users' seat_model timeouts 600-3600."""
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        out, err = _y1_paths(tmp_path)
        result = run(_y1_argv(tmp_path), out, err, effort="xhigh", clock=clock.now, sleep=clock.sleep,
                     **{kwarg: good})
        assert len(children) == 1
        assert getattr(result, kwarg) == good

    @pytest.mark.usefixtures("restore_signal_handlers")
    def test_y1_R2_12b_control_the_cli_takes_a_registry_cap_and_the_forge_harness_idle_timeout(
        self, tmp_path, monkeypatch, fake_codex
    ):
        """CONTROL (green at the round base): `--hard-cap 2400 --idle-timeout 1`, the forge harness's shape."""
        clock = FakeClock(step=10.0, real=0.0)
        children = fake_codex(clock, 30.0, "")
        _watch_with(monkeypatch, clock=clock.now, sleep=clock.sleep)
        out, err = _y1_paths(tmp_path)
        code = cw.main(["--hard-cap", "2400", "--idle-timeout", "1", "--no-telemetry", "--stdout-file", str(out),
                        "--stderr-file", str(err), "--", *_y1_argv(tmp_path)])
        assert code == cw.EXIT_IDLE_TIMEOUT and len(children) == 1


#: The base `--idle-timeout` help, VERBATIM (the other two flags had none) -- NEGATIVE CONTROL only.
_Y1_BASE_IDLE_HELP = ("seconds of silence that stop the call; omit for the mode default (300 s in codex mode, "
                      "NONE in agy mode -- agy has no liveness signal while it reasons)")


def _y1_help_states_the_rule(text):
    return bool(text) and "finite number" in text and "> 0" in text


def test_y1_R2_12_the_cli_help_states_the_rule_for_every_duration_flag():
    """GUARD: each flag the checker covers says what it accepts."""
    helps = {a.option_strings[0]: a.help for a in cw._build_parser()._actions if a.option_strings}
    missing = [flag for flag in ("--poll-interval", "--hard-cap", "--idle-timeout", "--progress-interval")
               if not _y1_help_states_the_rule(helps.get(flag))]
    assert missing == [], missing
    # NEGATIVE CONTROL: the base help trips it (and a flag with no help at all does).
    assert not _y1_help_states_the_rule(_Y1_BASE_IDLE_HELP)
    assert not _y1_help_states_the_rule(None)


# --------------------------------------------------------------------------- #
# #291 fix round 2, N2 -- a prompt can be fed on stdin from a REGULAR FILE
# --------------------------------------------------------------------------- #
_ECHO_STDIN = ("import sys; data = sys.stdin.buffer.read(); "
               "sys.stdout.write('len=%d eof=1\\n' % len(data)); sys.stdout.flush()")


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO / E2BIG semantics")
class TestStdinFile:
    def test_a_regular_file_reaches_the_child_on_stdin_and_eofs(self, tmp_path):
        prompt = tmp_path / "prompt.txt"
        prompt.write_bytes(b"x" * 200_000)
        out, err = tmp_path / "o", tmp_path / "e"
        result = cw.watch([sys.executable, "-c", _ECHO_STDIN], mode=cw.MODE_CODEX,
                          stdout_path=out, stderr_path=err, hard_cap_s=60,
                          stdin_path=prompt, record_telemetry=False)
        assert result.stop_reason == cw.STOP_OK, err.read_text(encoding="utf-8")
        assert out.read_text(encoding="utf-8") == "len=200000 eof=1\n"

    def test_control_without_a_stdin_file_the_child_reads_an_empty_eof(self, tmp_path):
        out, err = tmp_path / "o", tmp_path / "e"
        result = cw.watch([sys.executable, "-c", _ECHO_STDIN], mode=cw.MODE_CODEX,
                          stdout_path=out, stderr_path=err, hard_cap_s=60, record_telemetry=False)
        assert result.stop_reason == cw.STOP_OK
        assert out.read_text(encoding="utf-8") == "len=0 eof=1\n"

    def test_set_blocking_runs_only_when_o_nonblock_was_set(self, tmp_path, monkeypatch):
        # #291 final re-review F1: on Windows there is no O_NONBLOCK, and os.set_blocking (3.12+)
        # works on pipes only -- on a regular file it raises. It must not be called at all when
        # the open never set O_NONBLOCK.
        src = tmp_path / "prompt.txt"
        src.write_bytes(b"x")
        calls = []
        monkeypatch.delattr(os, "O_NONBLOCK", raising=False)
        monkeypatch.setattr(os, "set_blocking", lambda fd, b: calls.append((fd, b)), raising=False)
        handle = cw._open_stdin(src)
        try:
            assert handle.read() == b"x"
        finally:
            handle.close()
        assert calls == []

    def test_a_set_blocking_failure_is_a_watch_error_and_closes_the_fd(self, tmp_path, monkeypatch):
        # #291 final re-review F1: an OSError from set_blocking must surface as CodexWatchError
        # (a refused call, before the spawn) and must not leak the descriptor.
        src = tmp_path / "prompt.txt"
        src.write_bytes(b"x")
        opened, closed = [], []
        real_open, real_close = os.open, os.close
        monkeypatch.setattr(os, "open", lambda *a, **k: opened.append(real_open(*a, **k)) or opened[-1])
        monkeypatch.setattr(os, "close", lambda fd: closed.append(fd) or real_close(fd))

        def boom(fd, blocking):
            raise OSError(22, "set_blocking unsupported on this handle")

        monkeypatch.setattr(os, "set_blocking", boom, raising=False)
        with pytest.raises(cw.CodexWatchError):
            cw._open_stdin(src)
        assert opened and opened[-1] in closed

    @pytest.mark.parametrize("kind", ["fifo", "directory", "missing"])
    def test_a_stdin_source_that_may_never_eof_is_refused_before_spawning(self, tmp_path, kind):
        # STDIN RULE: only a regular file is accepted -- a FIFO may never EOF (the #135 hang).
        src = tmp_path / "src"
        if kind == "fifo":
            os.mkfifo(src)
        elif kind == "directory":
            src.mkdir()
        spawned = []
        real = cw._spawn
        try:
            cw._spawn = lambda *a, **k: spawned.append(a) or real(*a, **k)
            with pytest.raises(cw.CodexWatchError):
                cw.watch([sys.executable, "-c", _ECHO_STDIN], mode=cw.MODE_CODEX,
                         stdout_path=tmp_path / "o", stderr_path=tmp_path / "e", hard_cap_s=60,
                         stdin_path=src, record_telemetry=False)
        finally:
            cw._spawn = real
        assert spawned == []
