#!/usr/bin/env python3
"""mail-scan -- test_mail_flow.py (#351 WP-6, the three declared flows).

The flows the contract map declares, and no other (nothing here is found by walking the
call graph):

    flow-scan      mail-scan-core -> mail-parse -> mail-view -> mail-rules -> mail-state
                   a raw message to a stored verdict and a framed view
    flow-draft     mail-scan-core -> mail-draft-check -> mail-state
                   a draft checked against a scanned message
    flow-override  mail-scan-core -> mail-state -> mail-draft-check
                   an override changes the effective verdict for one digest

WRITTEN FROM THE CONSUMER'S SIDE. `references/building-a-mail-gate.md` tells a consumer how
to build its gate: scan, read the reply decision, hand ONE framed view to a model with no
tools, check the draft, scan again before placing it, and place only what the returned
digests name. `Gate` below is that gate with the mailbox left out, once on the library
(`LibraryGate`) and once on the command (`CommandGate`, the command line of the reference,
argument for argument, run in this process). Every flow goes through one of the two real
entry points with messages `samples.py` builds at call time.

THREE THINGS THE FIRST RUN OF THESE FLOWS SETTLED, each pinned here:

    * a scan reports the decision twice: AS RECORDED, and EFFECTIVE (after the overrides a
      person gave for that raw digest). The gate reads the effective reply, and the exit
      code follows the effective verdict, so a released block exits 1 and gets its draft.
      The record of a scan after a release still holds the decision as it was made.
    * the command never prints the reply target (it prints nothing of a message): a gate
      built on the command takes it from its own parse of the From mailbox and hands it
      to check-draft, which proves it belongs to the sender. The tests hand it to `handle`.
    * the library returns the reply target only when the effective reply is `draft`.

EVERY TEST USES A TEMPORARY STATE ROOT. The home directory and `$FOUNDRY_MAILSCAN_ROOT`
point at an empty temporary directory for the whole module, the module ends by asserting
that directory is still empty, and that the real default root was not created or changed
(only that one directory entry is looked at; it is never listed).

Text in a sample that reads like a request is content of a test; it is addressed to nobody.

Stdlib unittest; pytest only runs it. The scripts may not start a process; these tests may.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import NamedTuple
from unittest import mock

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mail_frame  # noqa: E402
import mail_lists  # noqa: E402
import mail_scan  # noqa: E402
import mail_state  # noqa: E402
import mailscan  # noqa: E402


def _load_samples():
    """samples.py under a name of its own: `samples` is too common a module name to share."""
    name = "mail_scan_samples"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(HERE / "samples.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


samples = _load_samples()

MARKER = samples.FLOW_MARKER
NOW = samples.STATE_NOW
DAY = samples.DAY
RECORD_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")

# The flows as the contract map declares them: the path of each, entry first.
DECLARED_FLOWS = {
    "flow-scan": ("mail-scan-core", "mail-parse", "mail-view", "mail-rules", "mail-state"),
    "flow-draft": ("mail-scan-core", "mail-draft-check", "mail-state"),
    "flow-override": ("mail-scan-core", "mail-state", "mail-draft-check"),
}

# The real default root, as it was before this module pointed the home directory elsewhere.
# Only this one directory entry is looked at; it is never listed and nothing under it is read.
REAL_DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".foundry", "mail-scan")

_REAL_ROOT_BEFORE = []
_SAVED_ENV = {}
_FAKE_HOME = []


def _entry_state(path):
    try:
        found = os.lstat(path)
    except OSError:
        return None
    return (found.st_mode, found.st_mtime_ns, found.st_ino)


def setUpModule():
    """No test may reach a default root: home and the environment point at an empty temp directory."""
    _REAL_ROOT_BEFORE.append(_entry_state(REAL_DEFAULT_ROOT))
    home = tempfile.mkdtemp(prefix="mailscan-flow-home-")
    _FAKE_HOME.append(home)
    for name, value in (("HOME", home), ("USERPROFILE", home),
                        (mail_state.ENV_ROOT, os.path.join(home, "environment-root"))):
        _SAVED_ENV[name] = os.environ.get(name)
        os.environ[name] = value


def tearDownModule():
    for name, value in _SAVED_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    home = _FAKE_HOME.pop()
    left = os.listdir(home)
    shutil.rmtree(home, ignore_errors=True)
    assert left == [], "a test wrote under the home directory or the default root: %r" % (left,)
    assert _entry_state(REAL_DEFAULT_ROOT) == _REAL_ROOT_BEFORE.pop(), "the real default state root changed"


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# The gate a consumer builds, with the mailbox left out
# --------------------------------------------------------------------------------------

class Scanned(NamedTuple):
    record_id: object       # None when the scanner could store no record
    verdict: str
    reply: str              # the reply decision AS RECORDED
    released: str           # `reply if released`
    holds: tuple
    code: int               # the exit code (the library gives the same number)
    target: object          # the reply target; the command never gives one
    effective_verdict: str = "block"    # after the overrides given for this raw digest
    effective_reply: str = "held"


class Checked(NamedTuple):
    accepted: bool
    rules: tuple            # (rule id, count) of every refusal
    body_sha256: object
    subject_sha256: object
    code: int


class Standing(NamedTuple):
    """A record after overrides: what `effective_record` and `status RECORD` say."""
    verdict: str
    reply: str
    holds: tuple
    lifted: tuple


class Outcome(NamedTuple):
    step: str               # placed | stopped | refused | stopped-at-rescan | oversize
    first: object = None    # the first Scanned
    second: object = None   # the Scanned of the scan before placing
    checked: object = None
    to: object = None
    body: object = None
    subject: object = None


class Gate:
    """The steps of section 1 of the gate reference, in its order. A subclass is one transport.

    `model` stands in for the drafting model: a callable that is given ONE framed view and
    returns (body, subject). `target` is the reply target a gate on the command worked out
    itself; a gate on the library gets it from the scan.
    """

    def __init__(self, config, root, tmp):
        self.config = config
        self.root = root
        self.tmp = tmp
        self.now = None             # seconds since the epoch for the next call; None: the clock
        self.outputs = []           # every text the scanner wrote to a stream
        self.views_given = []       # every view the model was handed

    # ---- what a transport gives --------------------------------------------------------

    def scan(self, raw):
        raise NotImplementedError

    def view_text(self, scanned):
        raise NotImplementedError

    def check(self, record_id, body, subject, target):
        raise NotImplementedError

    def standing(self, record_id):
        raise NotImplementedError

    def lift(self, record_id, kind, reason):
        """A PERSON lifts one hold. Returns None, or the fixed word of the refusal."""
        raise NotImplementedError

    # ---- the flow ----------------------------------------------------------------------

    def _may_draft(self, scanned):
        if scanned.record_id is None:
            return False
        # "Any exit other than 0 or 1 means no draft" and "draft only when the effective reply is draft"
        return scanned.code in (0, 1) and scanned.effective_reply == mail_lists.REPLY_DRAFT

    def handle(self, raw, model, target=None):
        if len(raw) > self.config["max_bytes"]:                       # read the size first
            return Outcome("oversize")
        first = self.scan(raw)                                        # 2. scan
        if not self._may_draft(first):                 # 3. not `draft`: stop
            return Outcome("stopped", first)
        to = first.target if first.target is not None else target
        view = self.view_text(first)                                  # 4. ONE framed view, no tools
        self.views_given.append(view)
        body, subject = model(view)
        checked = self.check(first.record_id, body, subject, to)      # 5. check the draft
        if not checked.accepted:
            return Outcome("refused", first, None, checked)
        second = self.scan(raw)                                       # 6. fetch again, scan again
        if not self._may_draft(second):
            return Outcome("stopped-at-rescan", first, second, checked)
        # place only a body and a subject whose digests the check returned
        if (sha(body), sha(subject)) != (checked.body_sha256, checked.subject_sha256):
            return Outcome("refused", first, second, checked)
        return Outcome("placed", first, second, checked, to, body, subject)


class LibraryGate(Gate):
    """The gate on the library, as the example of section 4 of the reference calls it."""

    def __init__(self, config, root, tmp):
        Gate.__init__(self, config, root, tmp)
        self.view_paths = {}

    def scan(self, raw):
        result = mail_scan.scan_bytes(raw, self.config, self.root, self.now)
        record = result.record
        if record is None:
            return Scanned(None, result.verdict, result.reply, "", (), mail_scan.exit_code(result), None)
        self.view_paths[result.record_id] = result.view_path
        return Scanned(result.record_id, result.verdict, result.reply, record["reply_if_released"],
                       tuple(record["holds"]), mail_scan.exit_code(result), result.reply_target,
                       result.effective_verdict, result.effective_reply)

    def view_text(self, scanned):
        with open(self.view_paths[scanned.record_id], encoding="utf-8") as handle:
            return handle.read()

    def check(self, record_id, body, subject, target):
        result = mail_scan.check_draft(record_id, body, subject, target, self.config, self.root)
        return Checked(result.accepted(), tuple((hit.rule_id, hit.count) for hit in result.rule_hits),
                       result.body_sha256, result.subject_sha256, mail_scan.draft_exit_code(result))

    def standing(self, record_id):
        found = mail_scan.effective_record(record_id, self.root)
        return Standing(found.verdict, found.reply, tuple(found.holds), tuple(found.lifted))

    def lift(self, record_id, kind, reason):
        try:
            mail_state.add_override(record_id, kind, reason, self.root, self.now)
        except mail_state.StateError as error:
            return error.code
        return None


def run(argv, stdin=b""):
    """`mailscan.main(argv)` in this process, with its two streams caught: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mailscan.main(list(argv), stdin=io.BytesIO(stdin))
    return code, out.getvalue(), err.getvalue()


def value(text, label):
    """The text after `label: ` on the first line of `text` that starts with it."""
    for line in text.splitlines():
        if line.startswith(label + ": "):
            return line[len(label) + 2:]
    raise AssertionError("no line %r in %r" % (label, text))


def listed(text):
    return () if text == "none" else tuple(text.split(", "))


class CommandGate(Gate):
    """The gate on the command: each line as the command table of the reference writes it.

    The command runs in this process (`mailscan.main`). Its clock is the system clock;
    `clock_of` below stands in for it where a flow needs mail to arrive at known times.
    """

    def __init__(self, config, root, tmp):
        Gate.__init__(self, config, root, tmp)
        self.config_path = samples.scan_config_file(tmp, config, "gate-config.json")
        self.count = 0

    def _run(self, argv, stdin=b""):
        code, out, err = run(argv, stdin)
        self.outputs.extend((out, err))
        return code, out, err

    def scan(self, raw):
        self.count += 1
        path = samples.scan_message_file(self.tmp, raw, "fetched-%d.eml" % self.count)
        code, out, _err = self._run(["scan", "--config", self.config_path, "--root", self.root, path])
        record_id = value(out, "record")
        if record_id == "none":
            return Scanned(None, value(out, "verdict"), value(out, "reply"), "", (), code, None)
        return Scanned(record_id, value(out, "verdict"), value(out, "reply"), value(out, "reply if released"),
                       listed(value(out, "holds")), code, None, value(out, "effective verdict"),
                       value(out, "effective reply"))

    def view_text(self, scanned):
        # "the view is views/<record-id>.txt ... under the state root you supplied"
        with open(os.path.join(self.root, "views", scanned.record_id + ".txt"), encoding="utf-8") as handle:
            return handle.read()

    def check(self, record_id, body, subject, target):
        self.count += 1
        files = samples.scan_draft_files(self.tmp, body, subject, target, "draft-%d" % self.count)
        code, out, _err = self._run([
            "check-draft", "--config", self.config_path, "--body-file", files["body"], "--subject-file",
            files["subject"], "--reply-target-file", files["target"], "--root", self.root, record_id])
        if value(out, "result") == mail_lists.DRAFT_ACCEPT:
            return Checked(True, (), value(out, "body sha256"), value(out, "subject sha256"), code)
        rules = tuple((line.split()[1], int(line.split()[2][1:])) for line in out.splitlines()
                      if line.startswith("  "))
        return Checked(False, rules, None, None, code)

    def standing(self, record_id):
        _code, out, _err = self._run(["status", "--root", self.root, record_id])
        return Standing(value(out, "verdict"), value(out, "reply"), listed(value(out, "holds")),
                        listed(value(out, "lifted")))

    def lift(self, record_id, kind, reason):
        # The argument list is put together here; a person types this line at a prompt.
        argv = ["override", record_id, "--kind", kind, "--reason", reason, "--root", self.root]
        code, out, _err = self._run(argv)
        if code == 0:
            return None
        return value(out, "refused")


class _Clock:
    """Stands where `mail_state` reads the `time` module: its `time()` is the gate's clock."""

    def __init__(self, gate):
        self._gate = gate

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return time.time() if self._gate.now is None else self._gate.now


def clock_of(gate):
    """While this holds, a call with no `now` (the command) reads `gate.now` as its clock."""
    return mock.patch.object(mail_state, "time", _Clock(gate))


TRANSPORTS = (("library", LibraryGate), ("command", CommandGate))


class FlowCase(unittest.TestCase):
    """A temporary directory, a config and one gate per transport, each with a state root of its own."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mailscan-flow-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = samples.scan_config()
        self.replies = samples.flow_replies(MARKER)
        self.gates = []

    def gate(self, label):
        folder = os.path.join(self.tmp, "%s-%d" % (label, len(self.gates)))
        os.mkdir(folder)
        made = dict(TRANSPORTS)[label](self.config, os.path.join(folder, "state"), folder)
        self.gates.append(made)
        return made

    def for_each_gate(self, flow):
        """Run `flow(gate)` once per transport, each under the clock of its gate."""
        for label, _kind in TRANSPORTS:
            with self.subTest(transport=label):
                gate = self.gate(label)
                with clock_of(gate):
                    flow(gate)

    def model(self, name="plain"):
        return lambda _view: self.replies[name]

    # ---- asserting ---------------------------------------------------------------------

    def stored(self, gate, views=False):
        """(relative path, bytes) of every file of the state root; the views only when asked."""
        out = {}
        for directory, _dirs, names in os.walk(gate.root):
            for name in names:
                path = os.path.join(directory, name)
                relative = os.path.relpath(path, gate.root)
                if not views and relative.split(os.sep)[0] == mail_state.DIR_VIEWS:
                    continue
                with open(path, "rb") as handle:
                    out[relative] = handle.read()
        return out

    def assert_no_leak(self, gate, *words):
        """None of `words` is in an output of the scanner or in a stored file other than a view.

        Compared in lower case, since an address is stored and shown in lower case.
        """
        self.assertTrue(words)
        for word in words:
            needle = word.lower()
            for text in gate.outputs:
                self.assertNotIn(needle, text.lower())
            for path, data in self.stored(gate).items():
                self.assertNotIn(needle.encode("utf-8"), data.lower(), path)
                self.assertNotIn(needle, path.lower())
        for text in gate.outputs:
            for word in ("Traceback", gate.tmp, ".eml", ".txt"):
                self.assertNotIn(word, text)
            self.assertTrue(text.isascii(), ascii(text))

    def assert_state_sound(self, gate):
        """Every record validates and can be read, and every mode is the private one."""
        ids = mail_state.record_ids(gate.root)
        self.assertTrue(ids)
        for record_id in ids:
            self.assertEqual(mail_state.schema_errors(mail_state.load_record(record_id, gate.root)), [])
        self.assertEqual(mail_state.mode_report(gate.root), [])
        self.assertEqual(stat.S_IMODE(os.stat(gate.root).st_mode), 0o700)
        return ids


# --------------------------------------------------------------------------------------
# flow-scan: a raw message to a stored verdict and a framed view
# --------------------------------------------------------------------------------------

class FlowScan(FlowCase):
    def test_flow_scan_a_plain_customer_mail_is_a_caution_record_with_reply_draft_and_a_framed_view(self):
        raw = samples.flow_customer_message()
        def flow(gate):
            scanned = gate.scan(raw)
            self.assertTrue(RECORD_ID.fullmatch(scanned.record_id))
            self.assertEqual((scanned.verdict, scanned.reply, scanned.released, scanned.holds, scanned.code),
                             ("caution", "draft", "draft", (), 1))
            self.assertEqual((scanned.effective_verdict, scanned.effective_reply), ("caution", "draft"))
            # mail-state: the record, the view and the sheet are stored, private and sealed
            self.assertEqual(self.assert_state_sound(gate), [scanned.record_id])
            record = mail_state.load_record(scanned.record_id, gate.root)
            self.assertEqual((record["schema"], record["sha256"], record["subject"]),
                             ("mail-verdict.v1", sha(raw), {"kind": "email"}))
            files = self.stored(gate, views=True)
            for folder, suffix in (("records", ".json"), ("views", ".txt"), ("sheets", ".txt")):
                self.assertIn(os.path.join(folder, scanned.record_id + suffix), files)
            # mail-parse: one selected text part, nothing else
            self.assertEqual([(part["type"], part["role"]) for part in record["inventory"]["parts"]],
                             [("text/plain", "selected")])
            # mail-rules: no profile header on the message, so the sender is not verified
            self.assertEqual(record["rules"], [{"rule": "sender-unverified", "class": "caution", "count": 1}])
            self.assertEqual(record["gaps"], [])
            # mail-view: the question, framed; every content line under the fixed prefix
            view = gate.view_text(scanned)
            self.assertTrue(mail_state.is_frame(view))
            lines = mail_frame.content_lines(view)
            self.assertIn("where is my order %s? It is question number 0 this week." % samples.FLOW_ORDER, lines)
            for line in view.splitlines()[1:-1]:
                self.assertTrue(line.startswith(mail_lists.FRAME_LINE_PREFIX), line)
            # the sheet a person is shown holds the verdict and no text of the message
            sheet = files[os.path.join("sheets", scanned.record_id + ".txt")].decode("ascii")
            self.assertIn("verdict: caution", sheet)
            self.assertIn("sender-unverified", sheet)
            self.assert_no_leak(gate, samples.FLOW_ORDER, "opening hours", samples.FLOW_SENDER_ADDRESS)

        self.for_each_gate(flow)

    def test_flow_scan_the_library_returns_the_reply_target_in_memory_and_the_command_prints_none(self):
        raw = samples.flow_customer_message()
        library, command = self.gate("library"), self.gate("command")
        self.assertEqual(library.scan(raw).target, samples.FLOW_SENDER_ADDRESS)
        # on the command a gate gets no reply target: it works it out and check-draft proves it
        self.assertIsNone(command.scan(raw).target)
        self.assertEqual(command.outputs[0].splitlines()[:7], [
            "record: %s" % mail_state.record_ids(command.root)[0], "verdict: caution", "reply: draft",
            "reply if released: draft", "holds: none", "effective verdict: caution", "effective reply: draft"])
        for gate in (library, command):
            self.assert_no_leak(gate, samples.FLOW_SENDER_ADDRESS)

    def test_flow_scan_the_library_returns_a_reply_target_only_when_the_effective_reply_is_draft(self):
        gate = self.gate("library")
        mails = [samples.flow_customer_message(index) for index in range(4)]
        scans = []
        for index, raw in enumerate(mails):
            gate.now = NOW + 600 * index
            scans.append(gate.scan(raw))
        gate.now = NOW + 3600
        hostile = samples.flow_hostile_message(MARKER)
        cases = {
            "draft": scans[0],
            "held": scans[3],                                                    # the fourth mail: budget
            "none-list": gate.scan(samples.ordinary_messages()["newsletter"]),
            "none-automated": gate.scan(samples.ordinary_messages()["out-of-office"]),
            "block": gate.scan(hostile),
        }
        self.assertEqual({label: (found.reply, found.effective_reply) for label, found in cases.items()}, {
            "draft": ("draft", "draft"), "held": ("held", "held"), "none-list": ("none-list", "none-list"),
            "none-automated": ("none-automated", "none-automated"), "block": ("held", "held")})
        self.assertEqual({label: found.target for label, found in cases.items()}, {
            "draft": samples.FLOW_SENDER_ADDRESS, "held": None, "none-list": None, "none-automated": None,
            "block": None})
        # a person releases the block: the next scan of those bytes returns the target
        self.assertIsNone(gate.lift(cases["block"].record_id, "block", "a person read it"))
        released = gate.scan(hostile)
        self.assertEqual((released.reply, released.effective_reply, released.target),
                         ("held", "draft", samples.FLOW_HOSTILE_SENDER_ADDRESS))
        # and so for the budget hold of the fourth mail, and for list mail released by its own kind
        self.assertIsNone(gate.lift(scans[3].record_id, "budget", "a customer we know"))
        self.assertEqual(gate.scan(mails[3]).target, samples.FLOW_SENDER_ADDRESS)
        self.assertIsNone(gate.lift(cases["none-list"].record_id, "list", "we answer this list"))
        again = gate.scan(samples.ordinary_messages()["newsletter"])
        self.assertEqual((again.reply, again.effective_reply, again.target),
                         ("none-list", "draft", "news@example.org"))

    def test_flow_scan_a_hostile_mail_is_a_block_record_with_reply_held_and_no_marker_leaks(self):
        raw = samples.flow_hostile_message(MARKER)
        phrase = samples.hidden_phrase_texts()["ignore-previous"]
        def flow(gate):
            outcome = gate.handle(raw, self.model(), samples.FLOW_HOSTILE_SENDER_ADDRESS)
            self.assertEqual(outcome.step, "stopped")
            self.assertEqual(gate.views_given, [])          # no model ever saw it
            scanned = outcome.first
            self.assertEqual((scanned.verdict, scanned.reply, scanned.released, scanned.holds, scanned.code),
                             ("block", "held", "draft", ("block",), 2))
            self.assertEqual((scanned.effective_verdict, scanned.effective_reply, scanned.target),
                             ("block", "held", None))
            self.assertEqual(self.assert_state_sound(gate), [scanned.record_id])
            record = mail_state.load_record(scanned.record_id, gate.root)
            rules = {row["rule"]: row["class"] for row in record["rules"]}
            # the hidden instruction, the program named like an invoice
            self.assertEqual(rules["hidden-phrase"], "block")
            self.assertEqual(rules["attachment-dangerous"], "block")
            # the forged header: only the provider's own first header is read, and it passes another domain
            self.assertEqual(rules["sender-unverified"], "caution")
            self.assertNotIn("dmarc-fail", rules)
            self.assertEqual(record["view"]["counts"]["hidden_chars"] > 0, True)
            self.assertEqual([item["signature"] for item in record["inventory"]["attachments"]], ["mz"])
            # the view holds what a reader would see, and none of what was hidden from one
            view = gate.view_text(scanned)
            self.assertTrue(mail_state.is_frame(view))
            self.assertIn("where is my order %s?" % samples.FLOW_ORDER, view)
            for hidden in (samples.FLOW_HIDDEN_WORD, phrase, "price list", "example.net"):
                self.assertNotIn(hidden.lower(), view.lower())
            # nothing its sender chose is in an output, the record, the sheet or a file name
            self.assert_no_leak(gate, MARKER, samples.FLOW_HIDDEN_WORD, phrase, "invoice",
                                samples.FLOW_HOSTILE_SENDER_ADDRESS, samples.FLOW_ORDER)

        self.for_each_gate(flow)

    def test_flow_scan_mails_one_to_five_of_one_sender_one_to_three_draft_four_and_five_held(self):
        mails = [samples.flow_customer_message(index) for index in range(5)]
        self.assertEqual(len({sha(raw) for raw in mails}), 5)
        expected = ["draft", "draft", "draft", "held", "held"]
        def flow(gate):
            outcomes = []
            for index, raw in enumerate(mails):
                gate.now = NOW + 600 * index
                outcomes.append(gate.handle(raw, self.model(), samples.FLOW_SENDER_ADDRESS))
            # one to three: a draft is placed, and the scan before placing agreed with the first
            self.assertEqual([outcome.step for outcome in outcomes], ["placed"] * 3 + ["stopped"] * 2)
            for outcome in outcomes[:3]:
                self.assertEqual((outcome.first.reply, outcome.second.reply), ("draft", "draft"))
                self.assertEqual(outcome.to, samples.FLOW_SENDER_ADDRESS)
            for outcome in outcomes[3:]:
                self.assertEqual((outcome.first.verdict, outcome.first.reply, outcome.first.holds,
                                  outcome.first.released, outcome.first.code),
                                 ("caution", "held", ("budget",), "draft", 1))
            self.assertEqual(len(gate.views_given), 3)
            # every mail scanned again, an hour and then two days later: later mail never counts
            for later in (NOW + 3600, NOW + 2 * DAY):
                again = []
                for index, raw in enumerate(mails):
                    gate.now = later + index
                    again.append(gate.scan(raw).reply)
                self.assertEqual(again, expected)
            # another sender is not held by it
            gate.now = NOW + 3 * DAY
            other = gate.scan(samples.flow_customer_message(9, sender="Finn Example <finn@example.org>"))
            self.assertEqual(other.reply, "draft")
            # a person lifts the budget hold of mail four: four may be answered, five may not
            fourth, fifth = outcomes[3].first.record_id, outcomes[4].first.record_id
            self.assertEqual(gate.lift(fourth, "block", "wrong kind"), "kind-not-held")
            self.assertIsNone(gate.lift(fourth, "budget", "a customer we know"))
            self.assertEqual(gate.standing(fourth), Standing("caution", "draft", (), ("budget",)))
            self.assertEqual(gate.standing(fifth), Standing("caution", "held", ("budget",), ()))
            body, subject = self.replies["plain"]
            self.assertTrue(gate.check(fourth, body, subject, samples.FLOW_SENDER_ADDRESS).accepted)
            refused = gate.check(fifth, body, subject, samples.FLOW_SENDER_ADDRESS)
            self.assertEqual((refused.accepted, refused.rules, refused.code),
                             (False, (("draft-reply-not-allowed", 1),), 2))
            self.assert_state_sound(gate)

        self.for_each_gate(flow)

    def test_flow_scan_automated_mail_gets_no_draft_and_no_override_releases_it(self):
        automated = samples.ordinary_messages()["out-of-office"]
        newsletter = samples.ordinary_messages()["newsletter"]
        body, subject = self.replies["plain"]
        def flow(gate):
            outcome = gate.handle(automated, self.model(), samples.SENDER_ADDRESS)
            scanned = outcome.first
            # the exit code says pass; the reply decision, not the exit code, decides
            self.assertEqual((outcome.step, scanned.verdict, scanned.code, scanned.reply, scanned.released,
                              scanned.holds), ("stopped", "pass", 0, "none-automated", "none-automated", ()))
            for kind in mail_lists.OVERRIDE_KINDS:
                self.assertEqual(gate.lift(scanned.record_id, kind, "a person asked"), "override-automated")
            self.assertEqual(gate.standing(scanned.record_id), Standing("pass", "none-automated", (), ()))
            refused = gate.check(scanned.record_id, body, subject, samples.SENDER_ADDRESS)
            self.assertFalse(refused.accepted)
            self.assertIn(("draft-reply-not-allowed", 1), refused.rules)
            # effective equals recorded: nothing was lifted and nothing can be
            self.assertEqual((scanned.effective_verdict, scanned.effective_reply, scanned.target),
                             ("pass", "none-automated", None))
            self.assertEqual(gate.handle(automated, self.model(), samples.SENDER_ADDRESS).step, "stopped")
            self.assertFalse(os.path.exists(os.path.join(gate.root, mail_state.FILE_OVERRIDES)))
            # list mail gets no draft either, but a person may release it with the kind of its own
            listed_mail = gate.handle(newsletter, self.model(), "news@example.org").first
            self.assertEqual((listed_mail.reply, listed_mail.released), ("none-list", "none-list"))
            self.assertEqual(gate.lift(listed_mail.record_id, "block", "wrong kind"), "kind-not-held")
            self.assertIsNone(gate.lift(listed_mail.record_id, "list", "we answer this list"))
            self.assertEqual(gate.standing(listed_mail.record_id).reply, "draft")
            self.assertEqual(gate.standing(scanned.record_id).reply, "none-automated")
            self.assertEqual(gate.views_given, [])

        self.for_each_gate(flow)


# --------------------------------------------------------------------------------------
# flow-draft: a draft checked against a scanned message
# --------------------------------------------------------------------------------------

class FlowDraft(FlowCase):
    def test_flow_draft_a_plain_reply_is_accepted_with_its_digests_and_placed(self):
        raw = samples.flow_customer_message()
        body, subject = self.replies["plain"]
        def flow(gate):
            outcome = gate.handle(raw, self.model(), samples.FLOW_SENDER_ADDRESS)
            self.assertEqual(outcome.step, "placed")
            self.assertEqual((outcome.to, outcome.body, outcome.subject),
                             (samples.FLOW_SENDER_ADDRESS, body, subject))
            # the digests the check returned are those of exactly what the gate places
            self.assertEqual((outcome.checked.accepted, outcome.checked.code, outcome.checked.body_sha256,
                              outcome.checked.subject_sha256), (True, 0, sha(body), sha(subject)))
            # the model was handed one view: a frame of ours holding the customer's question
            self.assertEqual(len(gate.views_given), 1)
            self.assertTrue(mail_state.is_frame(gate.views_given[0]))
            self.assertIn(samples.FLOW_ORDER, gate.views_given[0])
            # the scan before placing made a second record of the same message, with the same answer
            ids = self.assert_state_sound(gate)
            self.assertEqual(sorted(ids), sorted([outcome.first.record_id, outcome.second.record_id]))
            self.assertEqual({mail_state.load_record(record_id, gate.root)["sha256"] for record_id in ids},
                             {sha(raw)})
            self.assertEqual(outcome.first[1:6], outcome.second[1:6])
            # the draft is nowhere in the state: a check writes nothing
            self.assert_no_leak(gate, "Kind regards", "It left us today")
            self.assertFalse(os.path.exists(os.path.join(gate.root, mail_state.FILE_OVERRIDES)))

        self.for_each_gate(flow)

    def test_flow_draft_a_check_writes_nothing_under_the_state_root(self):
        raw = samples.flow_customer_message()
        def flow(gate):
            scanned = gate.scan(raw)
            before = self.stored(gate, views=True)
            for name in sorted(self.replies):
                gate.check(scanned.record_id, self.replies[name][0], self.replies[name][1],
                           samples.FLOW_SENDER_ADDRESS)
            after = self.stored(gate, views=True)
            for files in (before, after):       # reading the override log may leave its empty lock file
                files.pop(mail_state.FILE_LOCK, None)
            self.assertEqual(after, before)

        self.for_each_gate(flow)

    def test_flow_draft_a_reply_holding_a_foreign_address_is_refused(self):
        raw = samples.flow_customer_message()
        def flow(gate):
            outcome = gate.handle(raw, self.model("foreign-address"), samples.FLOW_SENDER_ADDRESS)
            self.assertEqual((outcome.step, outcome.checked.accepted, outcome.checked.code,
                              outcome.checked.rules), ("refused", False, 2, (("draft-address", 1),)))
            self.assertEqual((outcome.checked.body_sha256, outcome.checked.subject_sha256, outcome.to),
                             (None, None, None))
            self.assert_no_leak(gate, MARKER, "example.net")

        self.for_each_gate(flow)

    def test_flow_draft_a_reply_holding_a_link_is_refused(self):
        raw = samples.flow_customer_message()
        def flow(gate):
            outcome = gate.handle(raw, self.model("link"), samples.FLOW_SENDER_ADDRESS)
            self.assertEqual((outcome.step, outcome.checked.accepted, outcome.checked.code,
                              outcome.checked.rules), ("refused", False, 2, (("draft-url", 1),)))
            self.assertEqual(outcome.to, None)
            self.assert_no_leak(gate, MARKER, "example.net")

        self.for_each_gate(flow)

    def test_flow_draft_a_reply_to_anybody_but_the_sender_is_refused(self):
        raw = samples.flow_customer_message()
        body, subject = self.replies["plain"]
        def flow(gate):
            scanned = gate.scan(raw)
            for target in ("%s@example.net" % MARKER.lower(), samples.FLOW_HOSTILE_SENDER_ADDRESS,
                           samples.OWN_ADDRESS):
                refused = gate.check(scanned.record_id, body, subject, target)
                self.assertFalse(refused.accepted, target)
                self.assertEqual(refused.code, 2)
            self.assertTrue(gate.check(scanned.record_id, body, subject, samples.FLOW_SENDER_ADDRESS).accepted)
            self.assert_no_leak(gate, MARKER)

        self.for_each_gate(flow)

    def test_flow_draft_the_subject_is_hashed_after_one_trailing_line_break_is_dropped(self):
        # the command reads the subject from a file a program wrote: it ends in one line break
        gate = self.gate("command")
        scanned = gate.scan(samples.flow_customer_message())
        body, subject = self.replies["plain"]
        checked = gate.check(scanned.record_id, body, subject, samples.FLOW_SENDER_ADDRESS)
        self.assertEqual((checked.body_sha256, checked.subject_sha256), (sha(body), sha(subject)))
        self.assertNotEqual(checked.subject_sha256, sha(subject + "\n"))

    def test_flow_draft_after_purge_a_draft_for_a_purged_view_is_refused(self):
        body, subject = self.replies["plain"]
        def flow(gate):
            now = int(time.time())
            gate.now = now - 8 * DAY
            old = gate.scan(samples.flow_customer_message(1))
            gate.now = now - DAY
            fresh = gate.scan(samples.flow_customer_message(2))
            gate.now = now
            self.assertTrue(gate.check(old.record_id, body, subject, samples.FLOW_SENDER_ADDRESS).accepted)
            code, out, _err = run(["status", "--root", gate.root])
            self.assertEqual((code, out.splitlines()[-1]), (1, "retention: not running"))
            code, out, _err = run(["purge", "--root", gate.root])
            self.assertEqual((code, out.splitlines()[0]),
                             (0, "purged: views 1, sheets 1, records 0, temporary files 0"))
            # the record is kept 90 days, its view seven: the view of the old mail is gone
            self.assertEqual(sorted(mail_state.record_ids(gate.root)), sorted([old.record_id, fresh.record_id]))
            self.assertEqual(os.listdir(os.path.join(gate.root, "views")), [fresh.record_id + ".txt"])
            refused = gate.check(old.record_id, body, subject, samples.FLOW_SENDER_ADDRESS)
            self.assertEqual((refused.accepted, refused.rules, refused.code),
                             (False, (("draft-view-missing", 1),), 2))
            self.assertTrue(gate.check(fresh.record_id, body, subject, samples.FLOW_SENDER_ADDRESS).accepted)
            code, out, _err = run(["status", "--root", gate.root])
            self.assertEqual((code, out.splitlines()[-1]), (0, "retention: running"))
            # the old mail fetched and scanned again has a view again, and a draft for it passes
            again = gate.handle(samples.flow_customer_message(1), self.model(), samples.FLOW_SENDER_ADDRESS)
            self.assertEqual(again.step, "placed")

        self.for_each_gate(flow)

    def test_flow_draft_an_edited_record_is_refused_as_unreadable(self):
        raw = samples.flow_hostile_message(MARKER)
        body, subject = self.replies["plain"]
        target = samples.FLOW_HOSTILE_SENDER_ADDRESS
        def flow(gate):
            scanned = gate.scan(raw)
            self.assertEqual(scanned.verdict, "block")
            # somebody turns the block into a pass by hand, in the record file
            path = mail_state.record_path(scanned.record_id, gate.root)
            with open(path, "rb") as handle:
                data = handle.read()
            edited = data.replace(b'"verdict": "block"', b'"verdict": "pass"', 1)
            edited = edited.replace(b'"reply": "held"', b'"reply": "draft"', 1)
            self.assertIn(b'"verdict": "pass"', edited)
            self.assertIn(b'"reply": "draft"', edited)
            with open(path, "wb") as handle:
                handle.write(edited)
            os.chmod(path, 0o600)
            # the draft check refuses it, and so does everything else that reads the record
            refused = gate.check(scanned.record_id, body, subject, target)
            self.assertEqual((refused.accepted, refused.rules, refused.code),
                             (False, (("draft-record-missing", 1),), 2))
            code, out, err = run(["status", "--root", gate.root, scanned.record_id])
            self.assertEqual((code, out.splitlines(), err), (2, ["refused: record-unreadable"], ""))
            with self.assertRaises(mail_state.StateError) as caught:
                mail_scan.effective_record(scanned.record_id, gate.root)
            self.assertEqual(caught.exception.code, "record-unreadable")
            self.assertIsNone(mail_scan.effective(sha(raw), gate.root))
            self.assertEqual(gate.lift(scanned.record_id, "block", "a person asked"), "record-unreadable")
            code, out, _err = run(["status", "--root", gate.root])
            self.assertEqual(code, 1)
            self.assertIn("records unreadable: 1", out.splitlines())
            # the message scanned again is judged again: still a block
            again = gate.scan(raw)
            self.assertEqual((again.verdict, again.reply, again.code), ("block", "held", 2))
            self.assertFalse(gate.check(again.record_id, body, subject, target).accepted)

        self.for_each_gate(flow)

    def test_flow_draft_scan_and_check_as_processes_of_their_own(self):
        """The gate of a consumer that starts the command: two processes, exit codes and fixed lines."""
        folder = os.path.join(self.tmp, "process")
        os.mkdir(folder)
        root = os.path.join(folder, "state")
        config_path = samples.scan_config_file(folder, self.config)
        message = samples.scan_message_file(folder, samples.flow_customer_message())
        body, subject = self.replies["plain"]
        files = samples.scan_draft_files(folder, body, subject, samples.FLOW_SENDER_ADDRESS)
        program = [sys.executable, str(SCRIPTS / "mailscan.py")]

        def process(argv):
            return subprocess.run(program + argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  encoding="utf-8", timeout=120, env=dict(os.environ))

        scanned = process(["scan", "--config", config_path, "--root", root, message])
        self.assertEqual((scanned.returncode, scanned.stderr), (1, ""))
        record_id = value(scanned.stdout, "record")
        self.assertTrue(RECORD_ID.fullmatch(record_id))
        self.assertEqual(value(scanned.stdout, "reply"), "draft")
        checked = process(["check-draft", "--config", config_path, "--body-file", files["body"],
                           "--subject-file", files["subject"], "--reply-target-file", files["target"],
                           "--root", root, record_id])
        self.assertEqual((checked.returncode, checked.stderr), (0, ""))
        self.assertEqual(checked.stdout.splitlines(), ["result: accept", "body sha256: %s" % sha(body),
                                                       "subject sha256: %s" % sha(subject)])
        hostile = samples.scan_message_file(folder, samples.flow_hostile_message(MARKER), "second.eml")
        blocked = process(["scan", "--config", config_path, "--root", root, hostile])
        self.assertEqual((blocked.returncode, blocked.stderr, value(blocked.stdout, "reply")), (2, "", "held"))
        for text in (scanned.stdout, blocked.stdout):
            self.assertNotIn(MARKER.lower(), text.lower())
            self.assertNotIn(folder, text)


# --------------------------------------------------------------------------------------
# flow-override: an override changes the effective verdict for one digest
# --------------------------------------------------------------------------------------

class FlowOverride(FlowCase):
    def setUp(self):
        FlowCase.setUp(self)
        self.first = samples.flow_hostile_message(MARKER)
        self.second = samples.flow_hostile_message(MARKER + "B")
        self.assertNotEqual(sha(self.first), sha(self.second))
        self.target = samples.FLOW_HOSTILE_SENDER_ADDRESS
        self.reason = "a person read it: %s" % MARKER

    def test_flow_override_check_draft_refuses_before_the_override_and_accepts_after_it(self):
        body, subject = self.replies["plain"]
        def flow(gate):
            one, two = gate.scan(self.first), gate.scan(self.second)
            for scanned in (one, two):
                self.assertEqual((scanned.verdict, scanned.reply, scanned.holds), ("block", "held", ("block",)))
                refused = gate.check(scanned.record_id, body, subject, self.target)
                self.assertEqual((refused.accepted, refused.code, refused.rules),
                                 (False, 2, (("draft-record-blocked", 1), ("draft-reply-not-allowed", 1))))
            # what cannot lift it: another kind, no reason
            self.assertEqual(gate.lift(one.record_id, "budget", "wrong kind"), "kind-not-held")
            self.assertEqual(gate.lift(one.record_id, "block", "   "), "reason-missing")
            self.assertEqual(gate.standing(one.record_id), Standing("block", "held", ("block",), ()))
            # a person lifts the block of the first message
            self.assertIsNone(gate.lift(one.record_id, "block", self.reason))
            self.assertEqual(gate.standing(one.record_id), Standing("caution", "draft", (), ("block",)))
            accepted = gate.check(one.record_id, body, subject, self.target)
            self.assertEqual((accepted.accepted, accepted.code, accepted.body_sha256, accepted.subject_sha256),
                             (True, 0, sha(body), sha(subject)))
            # the second message has another digest: it stays blocked, and so does a draft for it
            self.assertEqual(gate.standing(two.record_id), Standing("block", "held", ("block",), ()))
            still = gate.check(two.record_id, body, subject, self.target)
            self.assertEqual((still.accepted, still.rules),
                             (False, (("draft-record-blocked", 1), ("draft-reply-not-allowed", 1))))
            mine, theirs = mail_scan.effective(sha(self.first), gate.root), mail_scan.effective(sha(self.second),
                                                                                              gate.root)
            self.assertEqual((mine.verdict, mine.reply, mine.lifted), ("caution", "draft", ("block",)))
            self.assertEqual((theirs.verdict, theirs.reply, theirs.lifted), ("block", "held", ()))
            # the record itself is not rewritten, and the log is one sealed line bound to the digest
            self.assertEqual(mail_state.load_record(one.record_id, gate.root)["verdict"], "block")
            log = mail_state.read_overrides(gate.root)
            self.assertEqual((len(log.entries), log.ignored), (1, 0))
            entry = log.entries[0]
            self.assertEqual((entry.record, entry.sha256, entry.kind, entry.reason_length, entry.reason_sha256),
                             (one.record_id, sha(self.first), "block", len(self.reason), sha(self.reason)))
            self.assert_no_leak(gate, MARKER, "a person read it", self.target)
            self.assert_state_sound(gate)

        self.for_each_gate(flow)

    def test_flow_override_a_scan_reports_the_recorded_block_and_the_effective_release(self):
        """A blocked mail, an override for its digest, then the same bytes scanned again: recorded
        block, effective caution with effective reply draft, exit 1, and the gate of the one-page
        flow places its draft. A second message of another digest is unchanged.
        """
        body, subject = self.replies["plain"]

        def flow(gate):
            stopped = gate.handle(self.first, self.model(), self.target)
            self.assertEqual(stopped.step, "stopped")
            self.assertIsNone(gate.lift(stopped.first.record_id, "block", self.reason))
            again = gate.scan(self.first)
            self.assertNotEqual(again.record_id, stopped.first.record_id)
            self.assertEqual((again.verdict, again.reply, again.released, again.holds),
                             ("block", "held", "draft", ("block",)))
            self.assertEqual((again.effective_verdict, again.effective_reply, again.code), ("caution", "draft", 1))
            # the record of that scan holds the decision as it was made: nothing of the override
            record = mail_state.load_record(again.record_id, gate.root)
            self.assertEqual((record["verdict"], record["reply"], record["holds"]), ("block", "held", ["block"]))
            self.assertEqual(sorted(record), sorted(mail_state.load_record(stopped.first.record_id, gate.root)))
            # check-draft accepts, for the first record and for the new one of the same digest
            for record_id in (stopped.first.record_id, again.record_id):
                self.assertTrue(gate.check(record_id, body, subject, self.target).accepted)
            # the gate of the reference, unchanged, now places the draft
            self.assertEqual(gate.views_given, [])
            placed = gate.handle(self.first, self.model(), self.target)
            self.assertEqual((placed.step, placed.to), ("placed", self.target))
            self.assertEqual((placed.first.code, placed.second.code), (1, 1))
            self.assertEqual((placed.checked.body_sha256, placed.checked.subject_sha256),
                             (sha(placed.body), sha(placed.subject)))
            self.assertEqual(len(gate.views_given), 1)
            self.assertNotIn(samples.FLOW_HIDDEN_WORD, gate.views_given[0])
            # the second message has another digest: recorded and effective agree, exit 2, no draft
            other = gate.handle(self.second, self.model(), self.target)
            self.assertEqual(other.step, "stopped")
            self.assertEqual((other.first.verdict, other.first.reply, other.first.effective_verdict,
                              other.first.effective_reply, other.first.code),
                             ("block", "held", "block", "held", 2))
            self.assertFalse(gate.check(other.first.record_id, body, subject, self.target).accepted)
            self.assert_no_leak(gate, MARKER, "a person read it", samples.FLOW_HIDDEN_WORD, self.target)

        self.for_each_gate(flow)

    def test_flow_override_the_scan_lines_of_a_released_block(self):
        gate = self.gate("command")
        first = gate.scan(self.first)
        self.assertIsNone(gate.lift(first.record_id, "block", self.reason))
        again = gate.scan(self.first)
        self.assertEqual(gate.outputs[-2].splitlines(), [
            "record: %s" % again.record_id, "verdict: block", "reply: held", "reply if released: draft",
            "holds: block", "effective verdict: caution", "effective reply: draft", "rules: 5",
            "  block attachment-dangerous x1", "  block attachment-type-mismatch x1", "  block hidden-phrase x1",
            "  caution sender-unverified x1", "  caution attachment-present x1",
            "gaps: 0"])
        self.assertEqual((again.code, gate.outputs[-1]), (1, ""))

    def test_flow_override_a_released_message_still_has_its_bad_draft_refused(self):
        def flow(gate):
            scanned = gate.scan(self.first)
            self.assertIsNone(gate.lift(scanned.record_id, "block", self.reason))
            outcome = gate.handle(self.first, self.model("link"), self.target)
            self.assertEqual((outcome.step, outcome.checked.rules), ("refused", (("draft-url", 1),)))
            outcome = gate.handle(self.first, self.model("foreign-address"), self.target)
            self.assertEqual((outcome.step, outcome.checked.rules), ("refused", (("draft-address", 1),)))

        self.for_each_gate(flow)

    def test_flow_override_a_line_typed_into_the_log_lifts_nothing(self):
        body, subject = self.replies["plain"]
        gate = self.gate("command")
        scanned = gate.scan(self.first)
        log = os.path.join(gate.root, mail_state.FILE_OVERRIDES)
        with open(log, "ab") as handle:
            handle.write(('{"record": "%s", "sha256": "%s", "kind": "block"}\n'
                          % (scanned.record_id, sha(self.first))).encode("ascii"))
        os.chmod(log, 0o600)
        self.assertEqual(gate.standing(scanned.record_id), Standing("block", "held", ("block",), ()))
        self.assertFalse(gate.check(scanned.record_id, body, subject, self.target).accepted)
        code, out, _err = run(["status", "--root", gate.root])
        self.assertEqual(code, 1)
        self.assertIn("override lines ignored: 1", out.splitlines())


# --------------------------------------------------------------------------------------
# The file itself
# --------------------------------------------------------------------------------------

class TheFlowFile(unittest.TestCase):
    def test_the_flow_tests_are_named_after_the_declared_flows_only(self):
        prefixes = tuple("test_" + name.replace("-", "_") + "_" for name in DECLARED_FLOWS)
        names = []
        for case in (FlowScan, FlowDraft, FlowOverride):
            names.extend(name for name in vars(case) if name.startswith("test_"))
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertTrue(name.startswith(prefixes), name)
        for prefix in prefixes:
            self.assertTrue([name for name in names if name.startswith(prefix)], prefix)

    def test_the_flow_file_is_ascii_and_the_flow_builders_are_listed(self):
        data = (HERE / "test_mail_flow.py").read_bytes()
        self.assertTrue(data.isascii())
        self.assertNotIn(b"\r", data)
        self.assertEqual(samples.BUILDERS["flows"],
                         ("flow_customer_message", "flow_hostile_message", "flow_replies"))
        for name in samples.BUILDERS["flows"]:
            self.assertTrue(callable(getattr(samples, name)), name)


if __name__ == "__main__":
    unittest.main()
