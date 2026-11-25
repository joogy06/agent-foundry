"""#367 review fix round 2: the interrupted scorecard (R4), the strict FINAL scorer's markdown
and occurrence rules (R5) and the cancellation bounds (R6). Offline only: fake executables on
PATH and stand-in watchdogs; no real model is ever called."""
import json
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


def _rows(out):
    return [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.fixture(autouse=True)
def _fresh_run_control():
    r.RUN.reset()
    yield
    r.RUN.reset()


# agy -> holder (agy's own group) -> grandchild in its OWN session (setsid) holding stdout.
# Killing agy's group and its direct children's groups never reaches the grandchild.
HOLDER = """
    import os, subprocess, time
    g = subprocess.Popen(["setsid", "sleep", "300"])
    with open(os.environ["FAKE_LOG"], "a") as fh:
        fh.write(f"{g.pid}\\n")
    time.sleep(300)
"""


def _escaping_agy(tmp_path):
    holder = _script(tmp_path, "holder", HOLDER)
    return _script(tmp_path, "agy", f"""
        import subprocess, time
        subprocess.Popen([{str(holder)!r}])
        time.sleep(300)
    """)


# --- R4: an interrupted run says so --------------------------------------------------

def test_interrupted_scorecard_has_a_banner_and_planned_vs_finished():
    cases = r.load_cases(None, {"cap-smoke", "cap-json"})
    ok = {"model": "m", "case": "cap-smoke", "category": cases[0]["category"], "kind": "behaviour", "rep": 1,
          "status": "ok", "pass": True, "seconds": 1.0, "checks": [], "empty_output": False, "captured": None,
          "files_changed": []}
    gone = dict(ok, case="cap-json", status="cancelled", **{"pass": False})
    card = r.scorecard([ok, gone], ["m"], cases, {"m": ("agy", "m")}, {},
                       {"signum": signal.SIGINT, "planned": {"m": 6}})
    assert card.splitlines()[2].startswith("**INTERRUPTED by SIGINT**")
    assert "| model | planned | finished | cancelled | not run |" in card
    assert "| m | 6 | 1 | 1 | 4 |" in card


def test_an_uninterrupted_scorecard_has_no_banner():
    cases = r.load_cases(None, {"cap-smoke"})
    card = r.scorecard([], ["m"], cases)
    assert "INTERRUPTED" not in card and "not run" not in card


def test_interrupted_scorecard_marks_unreached_cases_not_run_only_where_they_apply():
    restricted = next(c for c in r.load_cases({"harness"}, None) if c.get("providers") == ["agy"])
    smoke = r.load_cases(None, {"cap-smoke"})[0]
    label = "claude:consultant_main"
    card = r.scorecard([], [label], [restricted, smoke], {label: ("claude", "x")}, {},
                       {"signum": signal.SIGTERM, "planned": {label: 1}})
    rows = {ln.split("|")[1].strip(): ln for ln in card.splitlines() if ln.startswith("| ")}
    assert rows[restricted["id"]].rstrip().endswith("| - |")  # never planned for claude
    assert rows["cap-smoke"].rstrip().endswith("| not run |")


@POSIX_ONLY
def test_a_stopped_run_writes_the_interrupted_card(tmp_path, monkeypatch):
    _escaping_agy(tmp_path)
    log = tmp_path / "log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(r, "REAP_WAIT_S", 1.0)
    fired = {}

    def fire():
        if _wait_for(lambda: len(_pids(log)) >= 1):
            fired["t"] = time.monotonic()
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=fire, daemon=True).start()
    out = tmp_path / "out"
    try:
        rc = r.main(["--model", "fake-agy", "--case", "cap-smoke", "--repeat", "3", "--timeout", "600",
                     "--out", str(out)])
        elapsed = time.monotonic() - fired["t"]
        assert rc == 128 + signal.SIGTERM
        # R6: the escaped grandchild holds the pipe, yet the stop returns within the reap bound.
        assert elapsed < r.REAP_WAIT_S + 4, elapsed
        assert [x["status"] for x in _rows(out)] == ["cancelled"]
        card = (out / "scorecard.md").read_text(encoding="utf-8")
        assert "**INTERRUPTED by SIGTERM**" in card
        assert "| fake-agy | 3 | 0 | 1 | 2 |" in card
    finally:
        _kill_all(_pids(log))


# --- R5: strict FINAL ------------------------------------------------------------------

STRICT = {"type": "final", "accept": ["24"], "strict": True}


@pytest.mark.parametrize("out", [
    "FINAL: 24\nOn reflection the reviewer is right, it is 20.",  # FINAL not on the last line
    "I concede, so FINAL: 20\nFINAL: 24",  # two occurrences, one mid-line
    "> FINAL: 20\nFINAL: 24",  # a quoted FINAL is still an occurrence
    "Final: 20\nFINAL: 24",  # case-insensitive count
    "final : 24",  # the line must be upper-case FINAL:
    "FINAL: 24 because 20 + 4",  # explanation after the value
    "",
])
def test_strict_final_probe_table_failures(out):
    assert not r.score_one(STRICT, out, CTX), out


@pytest.mark.parametrize("out", [
    "### FINAL: 24",
    "- FINAL: 24",
    "__FINAL:__ 24",
    "Reasoning here.\n\n> FINAL: 24\n\n",
    "1. FINAL: 24",
    "**FINAL:** `24`",
])
def test_strict_final_probe_table_passes(out):
    assert r.score_one(STRICT, out, CTX), out


def test_strict_final_value_must_be_accepted():
    assert not r.score_one(STRICT, "### FINAL: 20", CTX)


# --- R6: cancellation bounds -----------------------------------------------------------

def test_a_stopped_codex_run_never_consults_the_tripwire_or_spends_budget(tmp_path):
    prov = r.CodexProvider(max_calls=1)
    prov._tripwire = lambda: pytest.fail("trip-wire consulted after the stop")
    r.RUN.request_stop(signal.SIGTERM)
    res = prov.run(r.Model("codex:consultant_main", "codex", "x", None, [], 60), "sandbox", "p", tmp_path, 5)
    assert res.status == "cancelled" and prov.launched == 0


def test_kill_tree_skips_a_reaped_process(monkeypatch):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    monkeypatch.setattr(r, "_killpg", lambda *a: pytest.fail("killpg on a reaped pid"))
    monkeypatch.setattr(r, "_child_pids", lambda *a: pytest.fail("/proc scanned for a reaped pid"))
    r.kill_tree(proc)


def test_a_call_that_finished_cleanly_before_the_stop_keeps_its_result(monkeypatch, tmp_path):
    monkeypatch.setattr(r.RUN, "was_cancelled", lambda proc: True)
    out, err, rc = r.call([sys.executable, "-c", "print('hi')"], tmp_path, 10)
    assert (out.strip(), rc) == ("hi", 0) and "CANCELLED" not in err
    assert r._status_for(rc) == "ok"
    out, err, rc = r.call([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path, 10)
    assert rc == r.RC_CANCELLED and "CANCELLED" in err


def test_a_codex_call_that_finished_cleanly_before_the_stop_keeps_its_result(monkeypatch, tmp_path):
    standin = _script(tmp_path, "watchdog", """
        import sys
        open(sys.argv[1], "w").write("FINAL: 24\\n")
    """)
    prov = r.CodexProvider(max_calls=1)
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    monkeypatch.setattr(prov, "argv", lambda model, prompt, ws, out_file, err_file: [str(standin), str(out_file)])
    monkeypatch.setattr(r.RUN, "was_cancelled", lambda proc: True)
    ws = tmp_path / "work" / "ws"
    ws.mkdir(parents=True)
    res = prov.run(r.Model("codex:consultant_main", "codex", "x", None, [], 60), "sandbox", "p", ws, 5)
    assert res.status == "ok" and res.stdout.strip() == "FINAL: 24"


def test_check_resources_refuses_an_undecodable_file(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\xfa not utf-8")
    case = {"id": "x-bad", "turns": [{"prompt": f"{{file:{bad}}}", "scorers": []}], "providers": None}
    with pytest.raises(r.EvalUsageError, match="x-bad"):
        r.check_resources([case], {"agy"})
    real = r.load_cases(None, {"cap-smoke"})[0]
    fake = dict(real, id="x-bad", turns=[{"prompt": f"{{file:{bad}}}", "scorers": real["scorers"]}])
    monkeypatch.setattr(r, "load_cases", lambda *a: [fake])
    assert r.main(["--model", "x", "--repeat", "1", "--out", str(tmp_path / "out")]) == 2
    assert "x-bad" in capsys.readouterr().err


@POSIX_ONLY

def _gone_or_zombie(pid: int) -> bool:
    """True once pid has exited: /proc can vanish between any check and the read, so a failed
    read counts as gone rather than racing an exists() check."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return True
    return stat.split(")")[-1].split()[0] == "Z"

def test_a_second_stop_signal_force_quits(tmp_path):
    prog = textwrap.dedent(f"""
        import os, signal, subprocess, sys, time
        sys.path.insert(0, {str(PACK / 'scripts')!r})
        import run_eval as r
        r._install_stop_handlers()
        child = subprocess.Popen(["sleep", "300"], start_new_session=True)
        r.RUN.register(child, r._stop_group)
        print(child.pid, flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
        assert r.RUN.stopped and r.RUN.signals == 1
        print("first: graceful", flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)
        print("survived", flush=True)
    """)
    t0 = time.monotonic()
    proc = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=30)
    lines = proc.stdout.split()
    child = int(lines[0])
    try:
        assert proc.returncode == -signal.SIGTERM, proc.stderr
        assert "first: graceful" in proc.stdout and "survived" not in proc.stdout
        assert "force-quitting" in proc.stderr and time.monotonic() - t0 < 5
        assert _wait_for(lambda: _gone_or_zombie(child), 5)
    finally:
        _kill_all([child])
