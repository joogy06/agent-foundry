"""cpmail session watch (design 2026-10-30-cpmail-session-watch-design.md).

DW1 watch on|off|status, DW2 list --new, DW3 hook twins, DW4 watch-loop,
DW7 atomic writes. Every test runs against the AI_MAILBOX tmp fixture; the real
~/.ai-mailbox is never touched.
"""
import contextlib
import io
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
CPMAIL = SKILL_ROOT / "scripts" / "cpmail"
HOOK_PY = SKILL_ROOT / "hooks" / "session_start.py"
HOOK_SH = SKILL_ROOT / "hooks" / "session-start.sh"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX signals and process model")


def _run(cpmail, argv, stdin="body"):
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cpmail.main(argv)
            except SystemExit as e:
                rc = e.code if e.code is not None else 0
    finally:
        sys.stdin = old_stdin
    return rc, out.getvalue(), err.getvalue()


def _send(cpmail, to="proj-a", subject="s"):
    rc, out, err = _run(cpmail, ["send", "--to", to, "--subject", subject,
                                 "--from-project", "foundry-lab"])
    assert rc == 0, err
    return out.strip()


def _env(mailbox, **extra):
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env.pop("CLAUDE_SESSION_ID", None)
    env.update({"AI_MAILBOX": str(mailbox), "CPMAIL_BIN": str(CPMAIL),
                "CPMAIL_WATCH_MIN_INTERVAL": "0.05"})
    env.update(extra)
    return env


def _loop(mailbox, *args, **env_extra):
    return subprocess.Popen([sys.executable, str(CPMAIL), "watch-loop", "--project", "proj-a",
                             "--interval", "0.1", *args],
                            env=_env(mailbox, **env_extra), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _wait_for(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _locks(mailbox):
    d = mailbox / ".watch"
    return sorted(p.name for p in d.glob("*.lock")) if d.exists() else []


# ---------------------------------------------------------------- DW1 watch setting
def test_watch_status_defaults_off(cpmail):
    rc, out, _ = _run(cpmail, ["watch", "status", "--project", "proj-a"])
    assert rc == 0
    assert out.strip() == "watch: off for proj-a"


def test_watch_on_off_round_trip_keeps_aliases(cpmail, mailbox):
    (mailbox / ".config.yaml").write_text(
        yaml.safe_dump({"project_aliases": {"/srv/x": "x-proj"}, "other": [1, 2]}),
        encoding="utf-8")
    rc, out, _ = _run(cpmail, ["watch", "on", "--project", "proj-a"])
    assert rc == 0 and out.strip() == "watch: on for proj-a"
    cfg = yaml.safe_load((mailbox / ".config.yaml").read_text(encoding="utf-8"))
    assert cfg["project_aliases"] == {"/srv/x": "x-proj"}
    assert cfg["other"] == [1, 2]
    assert cfg["watch"] == {"proj-a": True}
    assert _run(cpmail, ["watch", "status", "--project", "proj-a"])[1].strip() == "watch: on for proj-a"
    assert _run(cpmail, ["watch", "status", "--project", "proj-b"])[1].strip() == "watch: off for proj-b"

    rc, out, _ = _run(cpmail, ["watch", "off", "--project", "proj-a"])
    assert rc == 0 and out.strip() == "watch: off for proj-a"
    cfg = yaml.safe_load((mailbox / ".config.yaml").read_text(encoding="utf-8"))
    assert cfg["project_aliases"] == {"/srv/x": "x-proj"} and cfg["watch"] == {"proj-a": False}
    assert not [p for p in mailbox.iterdir() if p.name.endswith(".tmp")]


def test_watch_on_without_config_creates_it(cpmail, mailbox):
    assert _run(cpmail, ["watch", "on", "--project", "proj-a"])[0] == 0
    assert yaml.safe_load((mailbox / ".config.yaml").read_text(encoding="utf-8")) == {
        "watch": {"proj-a": True}}


def test_watch_on_refuses_to_clobber_invalid_config(cpmail, mailbox):
    bad = "project_aliases: [unclosed\n"
    (mailbox / ".config.yaml").write_text(bad, encoding="utf-8")
    rc, _, err = _run(cpmail, ["watch", "on", "--project", "proj-a"])
    assert rc == 1 and "not changed" in err
    assert (mailbox / ".config.yaml").read_text(encoding="utf-8") == bad


def test_watch_exit_2_on_undetectable_project(cpmail, tmp_path, monkeypatch):
    odd = tmp_path / "Not A Slug!"
    odd.mkdir()
    monkeypatch.chdir(odd)
    assert _run(cpmail, ["watch", "status"])[0] == 2
    assert _run(cpmail, ["watch", "on"])[0] == 2


def test_watch_project_auto_detected(cpmail, tmp_path, monkeypatch):
    proj = tmp_path / "proj-a"
    proj.mkdir()
    monkeypatch.chdir(proj)
    assert _run(cpmail, ["watch", "on"])[1].strip() == "watch: on for proj-a"


# ---------------------------------------------------------------- DW2 list --new
def test_list_new_only_lists_unread_state(cpmail):
    first = _send(cpmail, subject="opened")
    second = _send(cpmail, subject="fresh")
    _run(cpmail, ["read", first])
    rc, out, _ = _run(cpmail, ["list", "--project", "proj-a", "--new"])
    assert rc == 0
    rows = [l for l in out.splitlines() if l]
    assert len(rows) == 1 and rows[0].startswith(second) and "\tunread\t" in rows[0]
    # --unread keeps its meaning: everything not acked
    rows = [l for l in _run(cpmail, ["list", "--project", "proj-a", "--unread"])[1].splitlines() if l]
    assert len(rows) == 2


def test_list_new_and_unread_are_exclusive(cpmail):
    assert _run(cpmail, ["list", "--new", "--unread"])[0] == 2


def test_read_state_bad_or_missing_state_counts_as_unread(cpmail, mailbox):
    inbox = mailbox / "inbox" / "proj-a"
    inbox.mkdir(parents=True)
    (inbox / "a.md").write_text("---\nsubject: x\n---\n\nbody\n", encoding="utf-8")
    (inbox / "b.md").write_text("---\nack_state: bogus\n---\n\nbody\n", encoding="utf-8")
    (inbox / "c.md").write_text("no frontmatter at all\n", encoding="utf-8")
    (inbox / "d.md").write_text("---\nack_state: read\n---\n\nbody\n", encoding="utf-8")
    assert cpmail.read_state(inbox / "a.md") == "unread"
    assert cpmail.read_state(inbox / "b.md") == "unread"
    assert cpmail.read_state(inbox / "c.md") == "unread"
    (inbox / "e.md").write_text("---\nack_state: read\nack_state: unread\n---\n\nb\n", encoding="utf-8")
    (inbox / "f.md").write_text("---\nack_state: 'read'\n---\n\nb\n", encoding="utf-8")
    assert cpmail.read_state(inbox / "gone.md") is None
    assert cpmail.read_state(inbox / "e.md") == "unread"  # not plain: the YAML parser decides
    assert cpmail.read_state(inbox / "f.md") == "read"
    assert cpmail.state_counts("proj-a") == (4, 2)


# ---------------------------------------------------------------- DW3 hook twins
def _hook(cmd, mailbox, cwd):
    p = subprocess.run(cmd, env=_env(mailbox), cwd=str(cwd), capture_output=True,
                       text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return p.stdout


@pytest.fixture
def hook_project(cpmail, mailbox, tmp_path):
    proj = tmp_path / "proj-a"
    proj.mkdir()
    return proj


def _both_hooks(mailbox, cwd):
    out_py = _hook([sys.executable, str(HOOK_PY)], mailbox, cwd)
    if shutil.which("bash") and os.name != "nt":
        out_sh = _hook(["bash", str(HOOK_SH)], mailbox, cwd)
        assert out_sh == out_py
    return out_py


def test_hooks_print_split_counts_and_watch_line_identically(cpmail, mailbox, hook_project):
    for i in range(2):
        _send(cpmail, subject=f"new {i}")
    opened = [_send(cpmail, subject=f"old {i}") for i in range(3)]
    for mid in opened:
        _run(cpmail, ["read", mid])
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    out = _both_hooks(mailbox, hook_project)
    assert out.splitlines() == [
        "[mail] 2 new for proj-a: read and handle them before other work (cpmail list --new)",
        "[mail] 3 read but not acked for proj-a (cpmail list --unread)",
        '[mail] watch is on for proj-a: start "cpmail watch-loop" as a background task '
        "(run_in_background), restart it after each wake",
    ]


def test_hooks_print_only_nonzero_parts(cpmail, mailbox, hook_project):
    mid = _send(cpmail)
    _run(cpmail, ["read", mid])
    assert _both_hooks(mailbox, hook_project).splitlines() == [
        "[mail] 1 read but not acked for proj-a (cpmail list --unread)"]


def test_hooks_silent_on_empty_inbox_and_watch_off(cpmail, mailbox, hook_project):
    assert _both_hooks(mailbox, hook_project) == ""


def test_hooks_exit_0_when_cpmail_missing(mailbox, tmp_path):
    env = _env(mailbox, CPMAIL_BIN=str(tmp_path / "no-such-cpmail"))
    p = subprocess.run([sys.executable, str(HOOK_PY)], env=env, capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout == ""


# ---------------------------------------------------------------- DW4 watch-loop
def test_watch_loop_exits_at_once_when_off(cpmail, mailbox):
    p = _loop(mailbox)
    out, _ = p.communicate(timeout=10)
    assert p.returncode == 0 and out.strip() == "watch is off for proj-a"
    assert _locks(mailbox) == []


def test_watch_loop_rejects_interval_below_floor(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    rc, _, err = _run(cpmail, ["watch-loop", "--project", "proj-a", "--interval", "5"])
    assert rc == 2 and "at least 30" in err


def test_watch_loop_reports_new_mail_present_at_start(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    mid = _send(cpmail, subject="hello")
    old = _send(cpmail, subject="already read")
    _run(cpmail, ["read", old])
    p = _loop(mailbox)
    out, _ = p.communicate(timeout=10)
    assert p.returncode == 0
    lines = out.splitlines()
    assert lines[0] == "NEW CPMAIL for proj-a:"
    assert len(lines) == 2 and lines[1].startswith(mid) and lines[1].endswith("\thello")
    assert _locks(mailbox) == []


def test_watch_loop_wakes_on_mail_arriving_later(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    p = _loop(mailbox)
    try:
        assert _wait_for(lambda: _locks(mailbox))
        time.sleep(0.3)
        assert p.poll() is None
        mid = _send(cpmail, subject="later")
        out, _ = p.communicate(timeout=10)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 0 and mid in out


def test_watch_loop_ignores_read_mail(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    _run(cpmail, ["read", _send(cpmail)])
    p = _loop(mailbox)
    try:
        time.sleep(0.5)
        assert p.poll() is None
    finally:
        p.terminate()
        p.communicate(timeout=10)


@POSIX_ONLY
def test_watch_loop_second_loop_exits_3_and_sigterm_removes_lock(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    first = _loop(mailbox, "--session", "s1")
    try:
        assert _wait_for(lambda: _locks(mailbox) == ["proj-a-s1.lock"])
        second = _loop(mailbox, "--session", "s1")
        out, _ = second.communicate(timeout=10)
        assert second.returncode == 3
        assert out.strip() == f"already watching (pid {first.pid})"
        # a different session is a different loop
        other = _loop(mailbox, "--session", "s2")
        assert _wait_for(lambda: "proj-a-s2.lock" in _locks(mailbox))
        other.send_signal(signal.SIGTERM)
        other.communicate(timeout=10)
        first.send_signal(signal.SIGTERM)
        first.communicate(timeout=10)
    finally:
        for p in (first,):
            if p.poll() is None:
                p.kill()
    assert first.returncode == 143
    assert _locks(mailbox) == []


@POSIX_ONLY
def test_watch_loop_sigint_removes_lock(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    p = _loop(mailbox, "--session", "s1")
    assert _wait_for(lambda: _locks(mailbox))
    p.send_signal(signal.SIGINT)
    p.communicate(timeout=10)
    assert p.returncode == 130
    assert _locks(mailbox) == []


@POSIX_ONLY
def test_watch_loop_reclaims_lock_of_killed_holder(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    holder = _loop(mailbox, "--session", "s1")
    assert _wait_for(lambda: _locks(mailbox))
    holder.kill()  # SIGKILL: no cleanup, lock file stays behind
    holder.communicate(timeout=10)
    assert _locks(mailbox) == ["proj-a-s1.lock"]
    nxt = _loop(mailbox, "--session", "s1")
    try:
        time.sleep(0.5)
        assert nxt.poll() is None, nxt.communicate()[0]
        text = (mailbox / ".watch" / "proj-a-s1.lock").read_text(encoding="utf-8")
        assert text.split()[0] == str(nxt.pid)
    finally:
        nxt.terminate()
        nxt.communicate(timeout=10)


def test_watch_loop_stale_pid_file_without_lock_is_reclaimed(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    (mailbox / ".watch").mkdir()
    (mailbox / ".watch" / "proj-a-s1.lock").write_text("999999 elsewhere\n", encoding="utf-8")
    _send(cpmail)
    p = _loop(mailbox, "--session", "s1")
    out, _ = p.communicate(timeout=10)
    assert p.returncode == 0 and out.startswith("NEW CPMAIL for proj-a:")


def test_watch_loop_exits_when_watch_turned_off(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    p = _loop(mailbox)
    try:
        assert _wait_for(lambda: _locks(mailbox))
        _run(cpmail, ["watch", "off", "--project", "proj-a"])
        out, _ = p.communicate(timeout=10)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 0 and out.strip() == "watch turned off for proj-a"
    assert _locks(mailbox) == []


@POSIX_ONLY
def test_watch_loop_exits_quietly_when_parent_is_gone(cpmail, mailbox, tmp_path):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    out_file = tmp_path / "orphan.out"
    # The shell starts the loop in the background, prints its pid, lives long enough
    # for the loop to record it as the parent, then exits: the loop is orphaned.
    script = (f'"{sys.executable}" "{CPMAIL}" watch-loop --project proj-a --interval 0.1 '
              f'--session orphan > "{out_file}" 2>&1 & echo $!; sleep 1')
    shell = subprocess.Popen(["sh", "-c", script], env=_env(mailbox), stdout=subprocess.PIPE,
                             text=True)
    pid = int(shell.stdout.readline())
    try:
        assert _wait_for(lambda: _locks(mailbox) == ["proj-a-orphan.lock"])
        shell.wait(timeout=10)
        assert _wait_for(lambda: _locks(mailbox) == [], timeout=10)
        assert out_file.read_text(encoding="utf-8") == ""
    finally:
        shell.stdout.close()
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@POSIX_ONLY
def test_watch_loop_hashes_an_invalid_session_id(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    bad = "../../etc/passwd"
    p = _loop(mailbox, "--session", bad)
    try:
        assert _wait_for(lambda: _locks(mailbox))
        names = _locks(mailbox)
        expected = "proj-a-" + cpmail.session_filename_part(bad) + ".lock"
        assert names == [expected]
        assert expected.startswith("proj-a-h-") and len(expected) == len("proj-a-h-") + 16 + 5
        assert not (mailbox.parent / "etc").exists()
    finally:
        p.terminate()
        p.communicate(timeout=10)


@POSIX_ONLY
def test_watch_loop_session_defaults_to_claude_code_session_id(cpmail, mailbox):
    _run(cpmail, ["watch", "on", "--project", "proj-a"])
    p = _loop(mailbox, CLAUDE_CODE_SESSION_ID="abc-123", CLAUDE_SESSION_ID="zzz")
    try:
        assert _wait_for(lambda: _locks(mailbox))
        assert _locks(mailbox) == ["proj-a-abc-123.lock"]
    finally:
        p.terminate()
        p.communicate(timeout=10)


def test_session_id_resolution_order(cpmail, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    assert cpmail.session_id(None) == f"ppid-{os.getppid()}"
    monkeypatch.setenv("CLAUDE_SESSION_ID", "old")
    assert cpmail.session_id(None) == "old"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "new")
    assert cpmail.session_id(None) == "new"
    assert cpmail.session_id("explicit") == "explicit"
    assert cpmail.session_filename_part("ok.id_1-2") == "ok.id_1-2"
    for bad in ("..", "a/b", "x" * 129, "sp ace", ""):
        part = cpmail.session_filename_part(bad)
        assert part.startswith("h-") and len(part) == 18


# ---------------------------------------------------------------- DW7 atomic writes
def test_send_never_exposes_a_partial_message(cpmail, mailbox, monkeypatch):
    real_replace = os.replace
    seen = []

    def checking_replace(src, dst):
        # At the moment of the rename the temp file is complete and hidden, and the
        # destination does not yet exist: no scan can list a partial message.
        assert Path(src).name.startswith(".") and str(src).endswith(".tmp")
        seen.append(len(cpmail.list_active("proj-a")))
        assert cpmail.state_counts("proj-a") == (len(seen) - 1, 0)
        cpmail.load_message(Path(src).with_name(Path(src).name))  # parses whole
        return real_replace(src, dst)

    monkeypatch.setattr(cpmail.os, "replace", checking_replace)
    for i in range(3):
        _send(cpmail, subject=f"m{i}")
    assert seen == [0, 1, 2]
    assert len(cpmail.list_active("proj-a")) == 3


def test_read_and_ack_write_atomically(cpmail, mailbox, monkeypatch):
    mid = _send(cpmail)
    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append(Path(dst).parent.name)
        return real_replace(src, dst)

    monkeypatch.setattr(cpmail.os, "replace", spy)
    _run(cpmail, ["read", mid])
    _run(cpmail, ["ack", mid])
    assert calls == ["proj-a", ".acked"]
    if os.name != "nt":
        assert (mailbox / "inbox" / "proj-a" / ".acked" / f"{mid}.md").stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_sent_message_mode_is_0600(cpmail, mailbox):
    mid = _send(cpmail)
    assert (mailbox / "inbox" / "proj-a" / f"{mid}.md").stat().st_mode & 0o777 == 0o600


def test_dot_and_tmp_files_are_never_messages(cpmail, mailbox):
    mid = _send(cpmail)
    inbox = mailbox / "inbox" / "proj-a"
    stub = "---\nack_state: unread\nmsg_id: X\n---\n\npartial"
    (inbox / f".{mid}.md.abc123.tmp").write_text(stub, encoding="utf-8")
    (inbox / ".hidden.md").write_text(stub, encoding="utf-8")
    (inbox / "inflight.tmp").write_text(stub, encoding="utf-8")
    assert [p.name for p in cpmail.list_active("proj-a")] == [f"{mid}.md"]
    rows = [l for l in _run(cpmail, ["list", "--project", "proj-a"])[1].splitlines() if l]
    assert len(rows) == 1
    assert cpmail.state_counts("proj-a") == (1, 0)
    assert len(cpmail.new_message_rows("proj-a")) == 1


def test_message_vanishing_between_listing_and_reading_is_absent(cpmail, mailbox, monkeypatch):
    keep = _send(cpmail, subject="keep")
    gone = _send(cpmail, subject="gone")
    real = cpmail.list_active

    def listing_then_vanish(project):
        files = real(project)
        (mailbox / "inbox" / "proj-a" / f"{gone}.md").unlink()
        return files

    monkeypatch.setattr(cpmail, "list_active", listing_then_vanish)
    rc, out, err = _run(cpmail, ["list", "--project", "proj-a"])
    assert rc == 0, err
    assert [l.split("\t")[0] for l in out.splitlines() if l] == [keep]
