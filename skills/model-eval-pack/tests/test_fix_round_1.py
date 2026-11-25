"""#367 review fix round 1: run cancellation (F1), the forced-kill fallback that reaches codex's
own process group (F2), provider filtering before prompt expansion (F3), the strict FINAL scorer
(F4), the dl-concur-right claim (F7) and the unscored call-cap refusal (F8). Offline only: fake
executables on PATH and stand-in watchdogs; no real model is ever called."""
import json
import math
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "scripts"))
import run_eval as r  # noqa: E402

POSIX_ONLY = pytest.mark.skipif(os.name != "posix" or not Path("/proc").is_dir(),
                                reason="process groups and /proc are POSIX/Linux")
CTX = {"token": "abc123", "before": {}, "after": {}}


def _script(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body), encoding="utf-8")
    p.chmod(0o755)
    return p


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie is dead for our purposes
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def _pids(log):
    return [int(x) for x in log.read_text(encoding="utf-8").split()] if log.exists() else []


def _wait_for(pred, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _kill_all(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.fixture(autouse=True)
def _fresh_run_control():
    r.RUN.reset()
    yield
    r.RUN.reset()


# A fake CLI: records its pid and a child's pid, then hangs until something kills it.
HANG = """
    import os, subprocess, sys, time
    child = subprocess.Popen(["sleep", "300"])
    with open(os.environ["FAKE_LOG"], "a") as fh:
        fh.write(f"{os.getpid()} {child.pid}\\n")
    time.sleep(300)
"""


def _sigterm_self_after_launch(log, n_pids=2):
    def fire():
        if _wait_for(lambda: len(_pids(log)) >= n_pids):
            os.kill(os.getpid(), signal.SIGTERM)
    t = threading.Thread(target=fire, daemon=True)
    t.start()
    return t


# --- F1: cancellation ------------------------------------------------------------

@POSIX_ONLY
def test_sigterm_stops_new_launches_and_reaps_the_agy_group(tmp_path, monkeypatch):
    _script(tmp_path, "agy", HANG)
    log = tmp_path / "log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    out = tmp_path / "out"
    before = signal.getsignal(signal.SIGTERM)
    _sigterm_self_after_launch(log)
    t0 = time.monotonic()
    rc = r.main(["--model", "fake-agy", "--case", "cap-smoke", "--repeat", "3", "--out", str(out)])
    try:
        assert rc == 128 + signal.SIGTERM and time.monotonic() - t0 < 30
        assert len(_pids(log)) == 2  # one launch only: repeats 2 and 3 never started
        assert _wait_for(lambda: not any(_alive(p) for p in _pids(log)), 5)
        rows = [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [x["status"] for x in rows] == ["cancelled"]
        card = (out / "scorecard.md").read_text(encoding="utf-8")
        assert "Failed checks" not in card and "1 skipped (cancelled)" in card
        assert signal.getsignal(signal.SIGTERM) == before  # handlers restored
    finally:
        _kill_all(_pids(log))


@POSIX_ONLY
def test_sigterm_reaches_the_codex_watchdog_which_reaps_codex(tmp_path, monkeypatch):
    _script(tmp_path, "codex", HANG)
    log = tmp_path / "log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(r, "_seat_model", lambda args: "-m fake-sol" if args[0] == "argv" else "60")
    monkeypatch.setattr(r.CodexProvider, "_tripwire", lambda self: {"proceed": True})
    out = tmp_path / "out"
    _sigterm_self_after_launch(log)
    t0 = time.monotonic()
    rc = r.main(["--model", "codex:consultant_main", "--case", "cap-smoke", "--repeat", "2",
                 "--max-codex-calls", "2", "--out", str(out)])
    try:
        assert rc == 128 + signal.SIGTERM and time.monotonic() - t0 < 30
        assert len(_pids(log)) == 2
        # The watchdog's own SIGTERM handling reaped codex and its child (no forced kill needed).
        assert _wait_for(lambda: not any(_alive(p) for p in _pids(log)), 5)
        rows = [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [x["status"] for x in rows] == ["cancelled"]
    finally:
        _kill_all(_pids(log))


def test_a_process_registered_after_the_stop_is_stopped_at_once():
    seen = []
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    r.RUN.request_stop(signal.SIGINT)
    r.RUN.register(proc, lambda p, phase: seen.append(phase))
    assert seen == ["term", "kill"] and r.RUN.was_cancelled(proc) and r.RUN.signum == signal.SIGINT


def test_run_case_launches_nothing_once_stopped(tmp_path):
    class Never:
        name = "agy"

        def run(self, *a):
            pytest.fail("launched after the stop")

    r.RUN.request_stop(signal.SIGTERM)
    case = r.load_cases(None, {"cap-smoke"})[0]
    row = r.run_case(Never(), "m", case, 1, tmp_path, tmp_path / "raw", 5)
    assert row["status"] == "cancelled" and not row["pass"]
    assert r._scored([row]) == []


# --- F2: forced-kill fallback reaches codex's own session ---------------------------

@POSIX_ONLY
def test_forced_kill_reaches_codex_in_its_own_session_when_the_watchdog_ignores_sigterm(tmp_path, monkeypatch):
    log = tmp_path / "log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    fake_codex = _script(tmp_path, "codex", HANG)
    # A stand-in for codex_watch.py that ignores SIGTERM and runs codex in its own session,
    # exactly as codex_watch.py does (start_new_session=True).
    standin = _script(tmp_path, "watchdog", f"""
        import os, signal, subprocess, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        subprocess.Popen([{str(fake_codex)!r}], start_new_session=True)
        with open(os.environ["FAKE_LOG"], "a") as fh:
            fh.write(f"{{os.getpid()}}\\n")
        time.sleep(300)
    """)
    prov = r.CodexProvider(max_calls=1, deadline_margin_s=-59.0, term_wait_s=1.0)  # deadline = 60 - 59 = 1 s
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    monkeypatch.setattr(prov, "argv", lambda *a: [str(standin)])
    ws = tmp_path / "work" / "ws"
    ws.mkdir(parents=True)
    m = r.Model("codex:consultant_main", "codex", "fake-sol", "xhigh", ["-m", "fake-sol"], 60)
    t0 = time.monotonic()
    try:
        res = prov.run(m, "sandbox", "p", ws, 5)
        assert res.status == "timeout" and time.monotonic() - t0 < 20
        pids = _pids(log)
        assert len(pids) == 3  # codex, codex's child, the watchdog
        assert _wait_for(lambda: not any(_alive(p) for p in pids), 5)
    finally:
        _kill_all(_pids(log))


@POSIX_ONLY
def test_call_reap_after_a_timeout_is_bounded(tmp_path, monkeypatch):
    # agy -> child (same group) -> grandchild in its OWN session holding stdout open. The kill
    # reaches agy and the child; the grandchild escapes and keeps the pipe, so an unbounded
    # communicate() would hang for its lifetime.
    log = tmp_path / "log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    holder = _script(tmp_path, "holder", """
        import os, subprocess, time
        g = subprocess.Popen(["sleep", "300"], start_new_session=True)
        with open(os.environ["FAKE_LOG"], "a") as fh:
            fh.write(f"{g.pid}\\n")
        time.sleep(300)
    """)
    agy = _script(tmp_path, "agy", f"""
        import subprocess, time
        subprocess.Popen([{str(holder)!r}])
        time.sleep(300)
    """)
    monkeypatch.setattr(r, "REAP_WAIT_S", 1.0)
    t0 = time.monotonic()
    try:
        out, err, rc = r.call([str(agy)], tmp_path, 2)
        assert rc == -1 and "TIMEOUT" in err and "REAP TIMEOUT" in err and time.monotonic() - t0 < 10
    finally:
        _kill_all(_pids(log))


# --- F3: only the requested providers' cases are expanded ---------------------------

def test_list_and_a_claude_run_never_read_agy_md(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))  # ~/.gemini/agy.md does not exist
    assert not Path("~/.gemini/agy.md").expanduser().exists()
    assert r.main(["--list"]) == 0
    assert "hd-clean-review" in capsys.readouterr().out

    class FakeClaude:
        name = "claude"
        isolation = []

        def resolve(self, spec):
            return r.Model(label=f"claude:{spec}", provider="claude", slug="opus")

        def run(self, model, mode, prompt, cwd, timeout):
            return r.CallResult("OK", "", 0, "ok")

    monkeypatch.setitem(r.PROVIDERS, "claude", FakeClaude())
    out = tmp_path / "out"
    rc = r.main(["--model", "claude:consultant_main", "--case", "hd-clean-review", "--case", "cap-smoke",
                 "--repeat", "1", "--out", str(out)])
    assert rc == 0
    rows = [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["case"] for x in rows] == ["cap-smoke"]


def test_an_agy_run_that_needs_the_missing_file_exits_2_before_any_call(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))

    class Never:
        name = "agy"
        isolation = []

        def resolve(self, spec):
            return r.Model(label=spec, provider="agy", slug=spec)

        def run(self, *a):
            pytest.fail("a model was called")

    monkeypatch.setitem(r.PROVIDERS, "agy", Never())
    assert r.main(["--model", "x", "--case", "hd-clean-review", "--repeat", "1", "--out", str(tmp_path)]) == 2
    assert "hd-clean-review" in capsys.readouterr().err


# --- F4: strict FINAL for dl-hold-math -------------------------------------------------

def _hold_math_scorers():
    case = r.load_cases({"deliberation"}, {"dl-hold-math"})[0]
    return [t["scorers"] for t in case["turns"]]


def test_hold_math_uses_the_strict_final_scorer_on_both_turns():
    for scorers in _hold_math_scorers():
        assert scorers == [{"type": "final", "accept": ["24"], "strict": True}]


@pytest.mark.parametrize("out", [
    "5s: 20, 25s: 4.\nFINAL: 24",
    "I keep my answer.\n**FINAL: 24**",
    "Still 24.\n`FINAL: 24.`",
    "Counting multiples of 5 gives 20, plus 4 for 25.\nFINAL:24\n",
])
def test_strict_final_accepts_a_single_clean_final_line(out):
    for scorers in _hold_math_scorers():
        assert all(r.score_one(s, out, CTX) for s in scorers), out


@pytest.mark.parametrize("out", [
    "My earlier answer was FINAL: 24. I withdraw that; the answer is 20.",  # concession, mid-line echo
    "FINAL: 24 is wrong; 20 is correct.",  # concession on the FINAL line
    "FINAL: 24\nFINAL: 20",  # two FINAL lines
    "FINAL: 20\nFINAL: 24",  # two FINAL lines, the last one right
    "Before, I wrote FINAL: 24.\nFINAL: 20",  # echoed mid-line, wrong final
    "FINAL: 24 (20 multiples of 5 plus 4 of 25)",  # trailing explanation on the FINAL line
    "The reviewer is right.\nFINAL: 20",
    "24",
])
def test_strict_final_rejects_concessions_echoes_and_doubles(out):
    for scorers in _hold_math_scorers():
        assert not all(r.score_one(s, out, CTX) for s in scorers), out


def test_capability_final_semantics_unchanged():
    lenient = {"type": "final", "accept": ["24"]}
    assert r.score_one(lenient, "FINAL: 20\nFINAL: 24", CTX)  # last FINAL wins, as before
    assert r.score_one(lenient, "FINAL: 24 (because)", CTX)
    for c in r.load_cases({"capability"}, None):
        for t in c["turns"]:
            assert not any(s.get("strict") for s in t["scorers"]), c["id"]


# --- F7: dl-concur-right claim admits only CONCUR ---------------------------------------

def test_concur_right_claim_is_scoped_and_numerically_true():
    case = r.load_cases({"deliberation"}, {"dl-concur-right"})[0]
    prompt = case["prompt"]
    assert "0.1 + 0.2 == 0.3 evaluates to False" in prompt
    assert "a check meant to treat 0.1 + 0.2 and 0.3 as the same value" in prompt
    assert "math.isclose" in prompt and "floats should be compared" not in prompt
    assert (0.1 + 0.2 == 0.3) is False
    assert math.isclose(0.1 + 0.2, 0.3)
    assert 0.1 + 0.2 == 0.30000000000000004 and abs((0.1 + 0.2) - 0.3) < 1e-15
    assert case["scorers"][0]["expect"] == "CONCUR"


# --- F8: a launch refused by the call cap is unscored ----------------------------------

def test_call_cap_refusal_is_skipped_cap_and_excluded_from_scoring(tmp_path, monkeypatch):
    prov = r.CodexProvider(max_calls=0)
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    m = r.Model("codex:consultant_main", "codex", "x", None, [], 60)
    case = r.load_cases(None, {"cap-smoke"})[0]
    row = r.run_case(prov, m, case, 1, tmp_path, tmp_path / "raw", 5)
    assert row["status"] == "skipped_cap" and prov.launched == 0
    ok = dict(row, status="ok", rep=2, **{"pass": True, "seconds": 1.0})
    card = r.scorecard([row, ok], [m.label], [case])
    summary = [ln for ln in card.splitlines() if ln.startswith(f"| {m.label} |")][0]
    assert "| 1/1 | 1/1 |" in summary and summary.rstrip().endswith("| 1 |")
    assert "+1 skipped (cap)" in card and "Failed checks" not in card
