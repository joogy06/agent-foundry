"""`cpmail send --dedupe` (#329): refuse a second unacked message on the same topic.

An agent that sends cross-project mail on its own initiative must not flood the
recipient. With --dedupe, send refuses (exit 4, naming the existing msg_id) when
an unacked message from this sender to the same project carries the same dedupe
key. The key is --dedupe-key when given, else the normalised subject.
"""
import io
import contextlib
import sys


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


def _send(cpmail, subject, *extra, to="website", sender="foundry-lab"):
    return _run(cpmail, ["send", "--to", to, "--subject", subject,
                         "--from-project", sender, "--source-type", "ai_summary",
                         *extra])


def _inbox(mailbox, project="website"):
    return sorted((mailbox / "inbox" / project).glob("*.md"))


def test_dedupe_refuses_same_subject_with_distinct_exit_and_names_existing_id(cpmail, mailbox):
    rc, out, err = _send(cpmail, "Broken skill link", "--dedupe")
    assert rc == 0, err
    first = out.strip()

    rc, out, err = _send(cpmail, "Broken skill link", "--dedupe")
    assert rc == cpmail.EXIT_DUPLICATE == 4
    assert first in err
    assert out.strip() == ""
    assert len(_inbox(mailbox)) == 1


def test_dedupe_key_defaults_to_normalised_subject(cpmail, mailbox):
    rc, out, _ = _send(cpmail, "  Broken   Skill link ", "--dedupe")
    assert rc == 0
    rc, _, err = _send(cpmail, "broken skill LINK", "--dedupe")
    assert rc == 4
    assert out.strip() in err
    env, _ = cpmail.load_message(_inbox(mailbox)[0])
    assert env["dedupe_key"] == "broken skill link"


def test_explicit_dedupe_key_matches_across_different_subjects(cpmail, mailbox):
    rc, out, _ = _send(cpmail, "Skill X renamed", "--dedupe-key", "skill-x-rename")
    assert rc == 0
    env, _ = cpmail.load_message(_inbox(mailbox)[0])
    assert env["dedupe_key"] == "skill-x-rename"

    rc, _, err = _send(cpmail, "Another angle on the rename", "--dedupe",
                       "--dedupe-key", "skill-x-rename")
    assert rc == 4
    assert out.strip() in err
    rc, _, _ = _send(cpmail, "Another angle on the rename", "--dedupe",
                     "--dedupe-key", "other-topic")
    assert rc == 0


def test_dedupe_allows_resend_after_ack(cpmail, mailbox):
    rc, out, _ = _send(cpmail, "topic", "--dedupe")
    assert rc == 0
    assert _run(cpmail, ["ack", out.strip()])[0] == 0
    rc, _, err = _send(cpmail, "topic", "--dedupe")
    assert rc == 0, err


def test_dedupe_counts_a_read_but_unacked_message(cpmail, mailbox):
    rc, out, _ = _send(cpmail, "topic", "--dedupe")
    _run(cpmail, ["read", out.strip()])
    rc, _, err = _send(cpmail, "topic", "--dedupe")
    assert rc == 4
    assert out.strip() in err


def test_dedupe_is_scoped_to_recipient_and_sender(cpmail, mailbox):
    assert _send(cpmail, "topic", "--dedupe")[0] == 0
    assert _send(cpmail, "topic", "--dedupe", to="other-project")[0] == 0
    assert _send(cpmail, "topic", "--dedupe", sender="third-project")[0] == 0


def test_dedupe_matches_legacy_message_without_key_by_subject(cpmail, mailbox):
    # A message sent before #329 (no --dedupe, no recorded key) is still a
    # duplicate for a --dedupe send on the same subject.
    rc, out, _ = _send(cpmail, "Legacy Topic")
    assert rc == 0
    env, _ = cpmail.load_message(_inbox(mailbox)[0])
    assert "dedupe_key" not in env
    rc, _, err = _send(cpmail, "legacy topic", "--dedupe")
    assert rc == 4
    assert out.strip() in err


def test_without_dedupe_duplicates_are_still_allowed(cpmail, mailbox):
    assert _send(cpmail, "same")[0] == 0
    assert _send(cpmail, "same")[0] == 0
    assert len(_inbox(mailbox)) == 2


def test_dedupe_key_is_a_known_envelope_field(cpmail, mailbox, capsys):
    _send(cpmail, "topic", "--dedupe")
    env, _ = cpmail.load_message(_inbox(mailbox)[0])
    cpmail.validate(env)
    assert "unknown envelope fields" not in capsys.readouterr().err


def test_empty_dedupe_key_is_rejected(cpmail, mailbox):
    rc, _, err = _send(cpmail, "topic", "--dedupe-key", "   ")
    assert rc == 2
    assert _inbox(mailbox) == []


# ---------------------------------------------------------------- concurrency
# sibling-project cpmail 01M5TH871YY2HVGKPW3HZ6QHMX: 12 concurrent sends with one
# key produced 5 messages, because the unacked-duplicate scan and the write were
# not one atomic step. Each send is a real process here, as in the field.
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CPMAIL_PATH = Path(__file__).resolve().parent.parent / "scripts" / "cpmail"


def _send_proc(mailbox, cwd, key):
    env = dict(os.environ, AI_MAILBOX=str(mailbox))
    return subprocess.run(
        [sys.executable, str(CPMAIL_PATH), "send", "--to", "website",
         "--subject", "same topic", "--from-project", "foundry-lab",
         "--source-type", "ai_summary", "--dedupe-key", key],
        input="body", capture_output=True, text=True, env=env, cwd=cwd, timeout=60)


def test_concurrent_dedupe_sends_write_exactly_one_message(mailbox, tmp_path):
    for round_no in range(3):
        key = f"race-{round_no}"
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: _send_proc(mailbox, tmp_path, key), range(12)))
        codes = sorted(r.returncode for r in results)
        assert codes == [0] + [4] * 11, [(r.returncode, r.stderr) for r in results]
    assert len(_inbox(mailbox)) == 3


def test_dedupe_waits_for_a_held_topic_lock(cpmail, mailbox):
    # A send that finds the topic lock held must not write past it; once the
    # holder is gone (stale), the send proceeds and writes one message.
    lock = cpmail.dedupe_lock_path("foundry-lab", "website", "topic")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("held", encoding="utf-8")
    old = lock.stat().st_mtime - cpmail.DEDUPE_LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    rc, _, err = _send(cpmail, "topic", "--dedupe")
    assert rc == 0, err
    assert len(_inbox(mailbox)) == 1
    assert not lock.exists()


def test_dedupe_gives_up_on_a_live_lock(cpmail, mailbox, monkeypatch):
    monkeypatch.setattr(cpmail, "DEDUPE_LOCK_WAIT_S", 0.3)
    lock = cpmail.dedupe_lock_path("foundry-lab", "website", "topic")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("held", encoding="utf-8")
    rc, _, err = _send(cpmail, "topic", "--dedupe")
    assert rc == 1
    assert "lock" in err
    assert _inbox(mailbox) == []
