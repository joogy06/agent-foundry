#!/usr/bin/env python3
"""mail-scan -- test_mail_state.py (#351 WP-3b, component mail-state).

The state root: records that hold no message text, views, sheets, the keyed sender hash,
the override log and the effective verdict, the budget query, purge and the retention
report.

    TS-STATE-01  a stored record validates and carries no marker string from the message
    TS-STATE-02  an override changes the effective verdict for its digest only and is
                 refused for automated mail
    TS-STATE-03  purge removes aged files and status reports the retention state

WHAT MUST NOT HAPPEN, AND IS TESTED. Message text in a record, a sheet or the log (a marker
in every field a sender controls, looked for in every stored file but the view). A hold
lifted by anything other than a person's override for that very message: an override for
another digest, a line copied to another record, a line somebody typed, a cut or malformed
line, a record edited after the override. A file outside the state root read or written
because of a record id. A partial file after a failed write.

EVERY TEST USES A TEMPORARY STATE ROOT. The home directory and `$FOUNDRY_MAILSCAN_ROOT` are
pointed at an empty temporary directory for the whole module, and the module ends by
asserting that directory is still empty: nothing here falls back to a default root, and the
real one is never created, read or written.

Every sample comes from `samples.py`, which builds it at call time. The parser, the view
and the rules are used by these TESTS to make real input; the module under test imports
none of them.

Stdlib unittest; pytest only runs it.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import hmac
import importlib.util
import itertools
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mail_frame  # noqa: E402
import mail_lists  # noqa: E402
import mail_parse  # noqa: E402
import mail_reuse  # noqa: E402
import mail_rules  # noqa: E402
import mail_state  # noqa: E402
import mail_view  # noqa: E402


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

MARKER = samples.STATE_MARKER
NOW = samples.STATE_NOW
DAY = samples.DAY
CHECKS = mail_reuse.catalog_checks().checks
CONFIG = samples.rules_config()
SCHEMA_FILE = SKILL / "schemas" / "mail-verdict.v1.json"
StateError = mail_state.StateError

# What the design says an override of each kind does, written out here.
#   label of samples.state_decisions -> {frozenset of override kinds given: (verdict, reply, holds left)}
DESIGN_EFFECT = {
    "pass": {frozenset(): ("pass", "draft", ())},
    "caution": {frozenset(): ("caution", "draft", ())},
    "block": {frozenset(): ("block", "held", ("block",)),
              frozenset({"block"}): ("caution", "draft", ())},
    "budget": {frozenset(): ("pass", "held", ("budget",)),
               frozenset({"budget"}): ("pass", "draft", ())},
    "held": {frozenset(): ("caution", "held", ("held",)),
             frozenset({"held"}): ("caution", "draft", ())},
    "block-budget": {frozenset(): ("block", "held", ("block", "budget")),
                     frozenset({"block"}): ("caution", "held", ("budget",)),
                     frozenset({"budget"}): ("block", "held", ("block",)),
                     frozenset({"block", "budget"}): ("caution", "draft", ())},
    "none-list": {frozenset(): ("pass", "none-list", ()),
                  frozenset({"list"}): ("pass", "draft", ())},
    "list-budget": {frozenset(): ("pass", "held", ("budget",)),
                    frozenset({"list"}): ("pass", "held", ("budget",)),
                    frozenset({"budget"}): ("pass", "none-list", ()),
                    frozenset({"budget", "list"}): ("pass", "draft", ())},
    "list-block": {frozenset(): ("block", "held", ("block",)),
                   frozenset({"list"}): ("block", "held", ("block",)),
                   frozenset({"block"}): ("caution", "none-list", ()),
                   frozenset({"block", "list"}): ("caution", "draft", ())},
    # nobody read the message: no override is taken for it at all (fix round 1, review B F4)
    "scanner-error": {frozenset(): ("block", "held", ("block",))},
    "dmarc-fail": {frozenset(): ("caution", "draft", ())},
    "no-single-from": {frozenset(): ("block", "held", ("block",)),
                       frozenset({"block"}): ("caution", "draft", ())},
}
AUTOMATED = ("none-automated", "none-automated-block")

_SAVED_ENV = {}
_FAKE_HOME = []


def setUpModule():
    """No test may reach a default root: home and the environment point at an empty temp directory."""
    home = tempfile.mkdtemp(prefix="mailscan-home-")
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


def facts(raw):
    """(parsed message, view, decision) of raw bytes, as the scan makes them."""
    parsed = mail_parse.parse(raw)
    view = mail_view.build(parsed, CHECKS)
    return parsed, view, mail_rules.decide(parsed, view, CONFIG)


def files_of(root):
    """(path relative to the root, bytes) of every file under the root."""
    out = []
    for directory, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as handle:
                out.append((os.path.relpath(path, root), handle.read()))
    return sorted(out)


def tree_of(root):
    """Every path under `root` with its bytes (a directory has None): to see that nothing changed."""
    out = {}
    for directory, dirs, names in os.walk(root):
        for name in dirs:
            out[os.path.relpath(os.path.join(directory, name), root)] = None
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, root)] = handle.read()
    return out


def mode_of(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


class StateCase(unittest.TestCase):
    """A temporary directory and a state root inside it, not yet created."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mailscan-state-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = samples.state_root_dir(self.tmp)

    def scan(self, label="pass", digest=None, address=samples.STATE_SENDER_ADDRESS, now=NOW, root=None,
             with_view=True):
        """Build and store the record of one sample decision; returns the record."""
        root = root or self.root
        digest = digest or samples.state_digest(label)
        view = samples.state_view()
        record = mail_state.build_record(digest, samples.state_parsed(), view, samples.state_decisions()[label],
                                         mail_state.sender_hash(address, root), root, now)
        mail_state.store(record, view["framed"] if with_view else None, root)
        return record

    def override(self, record, kind, reason="looked at it", now=NOW, root=None):
        return mail_state.add_override(record["id"], kind, reason, root or self.root, now, "tester")

    def effect(self, record, root=None):
        result = mail_state.effective_record(record["id"], root or self.root)
        return result.verdict, result.reply, result.holds

    def log_path(self, root=None):
        return os.path.join(root or self.root, mail_state.FILE_OVERRIDES)

    def log_bytes(self, root=None):
        try:
            with open(self.log_path(root), "rb") as handle:
                return handle.read()
        except FileNotFoundError:
            return None

    def append_raw(self, data, root=None):
        """Bytes at the end of the log, as somebody with an editor or a shell would put them."""
        with open(self.log_path(root), "ab") as handle:
            handle.write(data)

    def sealed_line(self, root=None, **fields):
        """A line carrying a GOOD seal of this root for the fields given: what only this module can write.

        Used to show that each check of a line holds by itself, not merely because a typed
        line has no seal.
        """
        root = root or self.root
        entry = mail_state.Override(**dict(dict(
            time=mail_state.time_text(NOW), record="20261013T120000Z-0123abcd", sha256="0" * 64, kind="block",
            reason_length=4, reason_sha256="1" * 64, user="tester"), **fields))
        return mail_state._override_line(mail_state.state_key(root), entry)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(StateError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)
        self.assertIn(code, mail_state.ERRORS)

    def assert_marker_only_in_views(self, root, marker):
        """`marker`, in any letter case, is in no file name and in no file but a view; views hold it."""
        needle = marker.lower().encode("ascii")
        seen_in_view = False
        for relative, data in files_of(root):
            self.assertNotIn(needle, relative.lower().encode("utf-8"), relative)
            if relative.split(os.sep)[0] == mail_state.DIR_VIEWS:
                seen_in_view = seen_in_view or needle in data.lower()
                continue
            self.assertNotIn(needle, data.lower(), relative)
        return seen_in_view


# --------------------------------------------------------------------------------------
# TS-STATE-01: records
# --------------------------------------------------------------------------------------

class Records(StateCase):
    def test_ts_state_01_a_stored_record_validates_and_carries_no_marker(self):
        for label in samples.state_decisions():
            with self.subTest(label=label):
                record = self.scan(label)
                self.assertEqual(mail_state.schema_errors(record), [])
                self.assertEqual(mail_state.load_record(record["id"], self.root), record)
                self.assertNotIn(MARKER.lower(), json.dumps(record).lower())
                self.assertNotIn(MARKER.lower(), mail_state.render_sheet(record).lower())
        self.assertTrue(self.assert_marker_only_in_views(self.root, MARKER))

    def test_a_whole_hostile_message_leaves_its_marker_in_the_view_and_nowhere_else(self):
        for name, raw in (("state", samples.state_marker_message(MARKER)), ("parse", samples.marker_message(MARKER))):
            with self.subTest(message=name):
                root = samples.state_root_dir(self.tmp, name)
                parsed, view, decision = facts(raw)
                self.assertIn(MARKER, decision.reply_target or MARKER)
                sender = mail_state.sender_hash(parsed.headers.from_address, root)
                record = mail_state.build_record(mail_state.raw_digest(raw), parsed, view, decision, sender, root, NOW)
                stored = mail_state.store(record, view.framed, root)
                if "block" in record["holds"]:
                    mail_state.add_override(record["id"], "block", "%s is the reason" % MARKER, root, NOW,
                                            "%s user" % MARKER)
                mail_state.purge(root, NOW)
                self.assertTrue(self.assert_marker_only_in_views(root, MARKER), "the view holds the text")
                self.assertIn(MARKER, mail_state.read_view(record["id"], root))
                with open(stored.sheet_path, "r", encoding="ascii") as handle:
                    self.assertNotIn(MARKER.lower(), handle.read().lower())

    def test_the_marker_of_the_sample_decisions_is_really_in_every_memory_only_field(self):
        # so the test above cannot pass because a sample forgot its marker
        decision = samples.state_decisions()["block"]
        for name in ("reply_target", "visible_text", "removed_hidden", "subject", "host", "url", "file_name"):
            self.assertIn(MARKER, decision[name], name)
        parsed = samples.state_parsed()
        self.assertIn(MARKER, parsed["links"][0]["url"])
        self.assertIn(MARKER, parsed["links"][0]["host"])
        self.assertIn(MARKER.lower(), parsed["attachments"][0]["extension"])
        self.assertIn(MARKER, parsed["attachments"][0]["declared_media_type"])
        self.assertIn(MARKER, parsed["selected"][0]["text"])
        for name in ("from_name", "from_address", "from_local", "from_domain", "subject"):
            self.assertIn(MARKER, parsed["headers"][name], name)
        view = samples.state_view()
        for name in ("framed", "visible_text", "removed_hidden", "removed_uncertain"):
            self.assertIn(MARKER, view[name], name)

    def test_only_the_fields_of_the_allowlist_are_read_from_the_inputs(self):
        read = set()

        class Spy(dict):
            def get(self, name, default=None):
                read.add(name)
                return dict.get(self, name, default)

        def spied(value):
            if isinstance(value, dict):
                return Spy({name: spied(item) for name, item in value.items()})
            if isinstance(value, list):
                return [spied(item) for item in value]
            return value

        mail_state.build_record(samples.state_digest(1), spied(samples.state_parsed()), spied(samples.state_view()),
                                spied(samples.state_decisions()["several-holds"]), None, self.root, NOW)
        allowed = set(mail_state._DECISION_WORDS) | {"holds", "rule_hits", "gaps", "header_ambiguous", "over_bound",
                                                    "attachment_only", "parts", "attachments", "links", "counts"}
        allowed |= set(mail_state.VIEW_FLAG_FIELDS) | set(mail_state.VIEW_COUNT_FIELDS)
        for fields in (mail_state._RULE_FIELDS, mail_state._GAP_FIELDS, mail_state._AMBIGUITY_FIELDS,
                       mail_state._PART_FIELDS, mail_state._ATTACHMENT_FIELDS, mail_state._LINK_FIELDS):
            allowed |= {name for name, _key in fields}
        self.assertEqual(read - allowed, set())
        memory_only = set()
        for module in (mail_parse, mail_view, mail_rules):
            for names in module.MEMORY_ONLY_FIELDS.values():
                memory_only |= set(names)
        self.assertEqual(read & memory_only, set(), "a field that holds message text was read")
        self.assertGreaterEqual(len(memory_only), 15)

    def test_real_scans_of_every_sample_message_build_a_valid_record(self):
        messages = {"plain": samples.plain_message(), "html": samples.html_message(),
                    "marker": samples.marker_message(MARKER)}
        messages.update(("ordinary " + name, raw) for name, raw in samples.ordinary_messages().items())
        messages.update(("gap " + name, raw) for name, raw in samples.gap_messages().items())
        for group, builder in (("reply", samples.reply_messages), ("link", samples.link_messages),
                               ("image", samples.image_only_messages)):
            for rule, cases in builder().items():
                messages.update(("%s %s %s" % (group, rule, name), raw) for name, raw in cases.items())
        for kind, cases in samples.attachment_cases().items():
            messages.update(("attachment %s %s" % (kind, name), samples.rules_message(attachments=[part]))
                            for name, part in cases.items())
        for name, values in samples.from_values().items():
            messages["from " + name] = samples.from_message(values)
        self.assertGreater(len(messages), 80)
        seen = set()
        for name, raw in messages.items():
            with self.subTest(message=name):
                parsed, view, decision = facts(raw)
                sender = mail_state.sender_hash(parsed.headers.from_address, self.root)
                record = mail_state.build_record(mail_state.raw_digest(raw), parsed, view, decision, sender,
                                                 self.root, NOW)
                self.assertEqual(mail_state.schema_errors(record), [])
                self.assertEqual((record["verdict"], record["reply"], record["reply_if_released"], record["holds"]),
                                 (decision.verdict, decision.reply, decision.reply_if_released, list(decision.holds)))
                self.assertEqual([(row["rule"], row["count"]) for row in record["rules"]],
                                 [(hit.rule_id, hit.count) for hit in decision.rule_hits])
                self.assertEqual([row["gap"] for row in record["gaps"]], [gap.name for gap in decision.gaps])
                self.assertEqual(len(record["inventory"]["parts"]), len(parsed.parts))
                self.assertEqual(len(record["inventory"]["links"]), len(parsed.links))
                self.assertEqual(record["sender"] is None, parsed.headers.from_address is None)
                stored = mail_state.store(record, view.framed, self.root)
                self.assertEqual(mail_state.read_view(stored.record_id, self.root), view.framed)
                seen.add((record["verdict"], record["reply"]))
        self.assertGreaterEqual(len(seen), 6)

    def test_a_message_nobody_judged_is_stored_without_a_view(self):
        record = mail_state.build_record(samples.state_digest("error"), None, None, mail_rules.error_decision(),
                                         None, self.root, NOW)
        self.assertEqual((record["verdict"], record["reply"], record["reply_if_released"], record["holds"]),
                         ("block", "held", "held", ["block"]))
        self.assertIsNone(record["view"])
        self.assertEqual(record["inventory"], {"parts": [], "attachments": [], "links": []})
        stored = mail_state.store(record, None, self.root)
        self.assertIsNone(stored.view_path)
        self.assertEqual(os.listdir(os.path.join(self.root, mail_state.DIR_VIEWS)), [])
        self.assert_code("view-unknown", mail_state.read_view, record["id"], self.root)
        with open(stored.sheet_path, "r", encoding="ascii") as handle:
            self.assertIn("view: none was built", handle.read())

    def test_the_tuples_and_their_recordable_forms_build_the_same_record(self):
        parsed, view, decision = facts(samples.ordinary_messages()["gmail-reply"]
                                       if "gmail-reply" in samples.ordinary_messages()
                                       else samples.html_message())
        digest = samples.state_digest("forms")
        one = mail_state.build_record(digest, parsed, view, decision, None, self.root, NOW)
        other = mail_state.build_record(digest, mail_parse.recordable(parsed), mail_view.recordable(view),
                                        mail_rules.recordable(decision), None, self.root, NOW)
        for record in (one, other):
            del record["id"], record["seal"]
        self.assertEqual(one, other)

    def test_the_record_names_its_message_time_and_versions(self):
        record = self.scan("caution", digest=samples.state_digest("x"))
        self.assertEqual(record["schema"], "mail-verdict.v1")
        self.assertEqual(record["subject"], {"kind": "email"})
        self.assertEqual(record["sha256"], samples.state_digest("x"))
        self.assertEqual(record["time"], "2026-10-13T12:00:00Z")
        self.assertTrue(record["id"].startswith("20261013T120000Z-"))
        self.assertEqual(record["versions"], {"scanner": mail_state.SCANNER_VERSION,
                                              "lists": mail_lists.LISTS_VERSION,
                                              "python": "%d.%d.%d" % sys.version_info[:3]})
        self.assertEqual(mail_state.raw_digest(b"abc"), hashlib.sha256(b"abc").hexdigest())

    def test_a_value_outside_its_fixed_list_is_refused(self):
        def changed(path, value):
            parsed, view, decision = samples.state_parsed(), samples.state_view(), samples.state_decisions()["caution"]
            target = {"parsed": parsed, "view": view, "decision": decision}
            for step in path[:-1]:
                target = target[step]
            target[path[-1]] = value
            return parsed, view, decision

        word = "x" + MARKER.lower()
        cases = [
            (("decision", "verdict"), word), (("decision", "verdict"), None), (("decision", "reply"), word),
            (("decision", "reply_if_released"), word), (("decision", "holds"), [word]),
            (("decision", "holds"), "block"), (("decision", "rule_hits"), "sender-unverified"),
            (("decision", "rule_hits", 0, "rule_id"), word), (("decision", "rule_hits", 0, "rule_id"), None),
            (("decision", "rule_hits", 0, "rule_id"), "draft-url"),
            (("decision", "rule_hits", 0, "rule_class"), "block"), (("decision", "rule_hits", 0, "count"), -1),
            (("decision", "rule_hits", 0, "count"), True), (("decision", "rule_hits", 0, "count"), 1.5),
            (("decision", "rule_hits", 0, "count"), "1"), (("decision", "rule_hits", 0, "count"), 2 ** 60),
            (("decision", "rule_hits", 0), word),
            (("decision", "gaps", 0, "name"), word), (("decision", "gaps", 0, "gap_class"), "block"),
            (("decision", "gaps", 0, "reply_effect"), "held"), (("decision", "gaps", 0, "detail"), word),
            (("parsed", "over_bound"), word), (("parsed", "attachment_only"), "no"),
            (("parsed", "header_ambiguous", 0, "header"), word), (("parsed", "header_ambiguous", 0, "reason"), word),
            (("parsed", "parts", 0, "part_id"), "p1/../" + word), (("parsed", "parts", 0, "part_id"), "p1\n"),
            (("parsed", "parts", 0, "media_type"), "text/x-" + word), (("parsed", "parts", 0, "media_type"), word),
            (("parsed", "parts", 0, "role"), word), (("parsed", "parts", 0, "depth"), None),
            (("parsed", "attachments", 0, "attachment_id"), word), (("parsed", "attachments", 0, "part_id"), "a1"),
            (("parsed", "attachments", 0, "role"), "selected"), (("parsed", "attachments", 0, "media_type"), word),
            (("parsed", "attachments", 0, "extension_class"), word), (("parsed", "attachments", 0, "signature"), word),
            (("parsed", "attachments", 0, "size"), -5),
            (("parsed", "links", 0, "link_id"), "l"), (("parsed", "links", 0, "kind"), word),
            (("parsed", "links", 0, "number"), "1"), (("parsed", "links", 0, "flags"), [word]),
            (("parsed", "links", 0, "flags"), "punycode"), (("parsed", "links"), {"l1": word}),
            (("view", "warning"), "yes"), (("view", "truncated"), 0), (("view", "counts"), None),
            (("view", "counts", "hidden_chars"), -1), (("view", "counts", "view_lines"), word),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=ascii(value)):
                with self.assertRaises(StateError) as caught:
                    mail_state.build_record(samples.state_digest(1), *changed(path, value), None, self.root, NOW)
                self.assertEqual(caught.exception.code, "record-invalid")
                self.assertNotIn(MARKER.lower(), str(caught.exception).lower())
        self.assertFalse(os.path.exists(self.root), "a refused build writes nothing, not even a key")

    def test_a_decision_that_does_not_hold_together_is_refused(self):
        bad = [
            ("block that drafts", ("block", "draft", "draft", [])),
            ("block without the hold", ("block", "held", "draft", ["held"])),
            ("held without a hold", ("caution", "held", "draft", [])),
            ("a hold without held", ("caution", "draft", "draft", ["held"])),
            ("a hold twice", ("block", "held", "draft", ["block", "block"])),
            ("automated with a hold", ("block", "none-automated", "none-automated", ["block"])),
            ("automated released to a draft", ("pass", "none-automated", "draft", [])),
            ("released to automated", ("pass", "draft", "none-automated", [])),
            ("list released to a draft", ("pass", "none-list", "draft", [])),
            ("draft released to list", ("pass", "draft", "none-list", [])),
            ("no hold and released held", ("pass", "draft", "held", [])),
        ]
        for name, (verdict, reply, released, holds) in bad:
            with self.subTest(case=name):
                decision = samples.state_decisions()["pass"]
                decision.update(verdict=verdict, reply=reply, reply_if_released=released, holds=holds)
                self.assert_code("record-invalid", mail_state.build_record, samples.state_digest(1),
                                 samples.state_parsed(), samples.state_view(), decision, None, self.root, NOW)
        for label, decision in samples.state_decisions().items():
            with self.subTest(sample=label):
                mail_state.build_record(samples.state_digest(1), None, None, decision, None, self.root, NOW)

    def test_a_digest_a_sender_or_a_time_of_the_wrong_form_is_refused(self):
        good = (samples.state_parsed(), samples.state_view(), samples.state_decisions()["pass"])
        for digest in ("", "abc", "A" * 64, "0" * 63, "0" * 65, "0" * 64 + "\n", None, 7, b"0" * 64, MARKER):
            with self.subTest(digest=ascii(digest)):
                self.assert_code("digest-invalid", mail_state.build_record, digest, *good, None, self.root, NOW)
        for sender in ("", "ann@example.org", "A" * 64, "0" * 64 + "\n", 7, MARKER):
            with self.subTest(sender=ascii(sender)):
                self.assert_code("sender-invalid", mail_state.build_record, samples.state_digest(1), *good, sender,
                                 self.root, NOW)
        for now in (-1, True, "now", float("nan"), float("inf"), 10 ** 12, [NOW]):
            with self.subTest(now=ascii(now)):
                self.assert_code("time-invalid", mail_state.build_record, samples.state_digest(1), *good, None,
                                 self.root, now)
        self.assert_code("record-invalid", mail_state.build_record, samples.state_digest(1), None, None, None, None,
                         self.root, NOW)

    def test_the_sheet_is_rendered_from_the_record_and_says_what_was_found(self):
        record = self.scan("several-holds")
        with open(mail_state.sheet_path(record["id"], self.root), "rb") as handle:
            stored = handle.read()
        self.assertTrue(stored.isascii())
        sheet = stored.decode("ascii")
        self.assertEqual(sheet, mail_state.render_sheet(mail_state.load_record(record["id"], self.root)))
        lines = sheet.splitlines()
        self.assertEqual(lines[0], mail_state.SHEET_TITLE)
        self.assertEqual(lines[-1], mail_state.SHEET_FOOTER)
        for expected in ("record: %s" % record["id"], "verdict: block", "reply: held", "reply if released: draft",
                         "holds: block, budget, held"):
            self.assertIn(expected, lines)
        for row in record["rules"]:
            self.assertTrue(any("%s x%d" % (row["rule"], row["count"]) in line and line.strip().startswith(row["class"])
                                for line in lines), row)
            self.assertIn(mail_lists.RULES[row["rule"]].description, sheet)
        self.assertTrue(any("html-ambiguous (element) x1" in line for line in lines))
        counts = record["view"]["counts"]
        self.assertIn("removed text, in characters: proven hidden %d, visibility uncertain %d, outside the allowlist %d"
                      % (counts["hidden_chars"], counts["uncertain_chars"], counts["dropped_chars"]), lines)
        self.assertIn("stripped characters: tag %d, bidi %d, format %d"
                      % (counts["tag_chars"], counts["bidi_chars"], counts["format_chars"]), lines)
        self.assertIn("header reply-to: repeated x2", lines)
        self.assertIn("inventory: parts 3, attachments 1, links 1", lines)
        plain = mail_state.render_sheet(self.scan("pass", address=None))
        self.assertIn("holds: none", plain)
        self.assertIn("sender: no single From address", plain)

    def test_a_rule_a_later_list_no_longer_knows_still_renders(self):
        record = dict(self.scan("caution"))
        record["rules"] = [{"rule": "a-rule-of-an-older-list", "class": "caution", "count": 2}]
        self.assertIn("  caution a-rule-of-an-older-list x2\n", mail_state.render_sheet(record))


# --------------------------------------------------------------------------------------
# The schema
# --------------------------------------------------------------------------------------

class Schema(StateCase):
    KEYWORDS = {"$schema", "$id", "title", "description", "$defs", "$ref", "const", "enum", "type", "anyOf",
                "pattern", "maxLength", "minimum", "items", "properties", "required", "propertyNames",
                "additionalProperties"}
    TYPES = {"object", "array", "string", "boolean", "null", "integer", "number"}

    def schema(self):
        return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    def nodes(self, node, path="schema"):
        """Every schema node (a dict that is read as a schema), with where it is."""
        yield path, node
        for name in ("properties", "$defs"):
            for key, child in node.get(name, {}).items():
                yield from self.nodes(child, "%s.%s.%s" % (path, name, key))
        for name in ("items", "propertyNames"):
            if isinstance(node.get(name), dict):
                yield from self.nodes(node[name], "%s.%s" % (path, name))
        if isinstance(node.get("additionalProperties"), dict):
            yield from self.nodes(node["additionalProperties"], path + ".additionalProperties")
        for index, child in enumerate(node.get("anyOf", [])):
            yield from self.nodes(child, "%s.anyOf[%d]" % (path, index))

    def test_the_schema_stays_inside_the_subset_the_interpreter_reads(self):
        schema = self.schema()
        self.assertEqual(schema["$id"], mail_state.SCHEMA_ID)
        count = 0
        for path, node in self.nodes(schema):
            count += 1
            with self.subTest(path=path):
                self.assertIsInstance(node, dict)
                self.assertEqual(set(node) - self.KEYWORDS, set())
                names = node.get("type", [])
                self.assertTrue(set([names] if isinstance(names, str) else names) <= self.TYPES)
                if "$ref" in node:
                    self.assertTrue(node["$ref"].startswith("#/$defs/"))
                    self.assertIn(node["$ref"][len("#/$defs/"):], schema["$defs"])
        self.assertGreater(count, 80)
        text = SCHEMA_FILE.read_text(encoding="utf-8")
        for keyword in ("maximum", "minLength", "maxItems", "minItems", "format", "oneOf", "allOf", "not",
                        "exclusiveMinimum", "uniqueItems", "patternProperties", "if"):
            self.assertNotIn('"%s"' % keyword, text)

    def test_every_object_is_closed_and_no_string_is_free_text(self):
        schema = self.schema()

        def resolved(node):
            while "$ref" in node:
                node = schema["$defs"][node["$ref"][len("#/$defs/"):]]
            return node

        for path, node in self.nodes(schema):
            node = resolved(node)
            with self.subTest(path=path):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                    self.assertEqual(sorted(node["required"]), sorted(node["properties"]))
                if node.get("type") == "string":
                    self.assertIn("pattern", node)
                    self.assertTrue(node["pattern"].startswith("^") and node["pattern"].endswith("$"))
                if "type" not in node and "anyOf" not in node:
                    self.assertTrue("enum" in node or "const" in node, "a value that is not pinned")

    def test_the_schema_and_the_lists_name_the_same_words(self):
        properties = self.schema()["properties"]
        self.assertEqual(tuple(properties["verdict"]["enum"]), mail_lists.VERDICTS)
        self.assertEqual(tuple(properties["reply"]["enum"]), mail_lists.REPLIES)
        self.assertEqual(set(properties["reply_if_released"]["enum"]), set(mail_lists.REPLIES))
        self.assertEqual(tuple(properties["holds"]["items"]["enum"]), mail_lists.HOLD_KINDS)
        self.assertEqual(tuple(properties["gaps"]["items"]["properties"]["class"]["enum"]), mail_lists.GAP_CLASSES)
        self.assertEqual(tuple(properties["gaps"]["items"]["properties"]["effect"]["enum"]), mail_lists.REPLY_EFFECTS)
        self.assertEqual(set(properties["rules"]["items"]["properties"]["class"]["enum"]),
                         set(mail_lists.RULE_CLASSES) - {mail_lists.CLASS_REFUSE})
        counts = properties["view"]["anyOf"][1]["properties"]["counts"]["properties"]
        self.assertEqual(tuple(counts), mail_state.VIEW_COUNT_FIELDS)
        self.assertEqual(mail_state.VIEW_COUNT_FIELDS, mail_view.ViewCounts._fields)
        self.assertEqual(mail_state.VIEW_COUNT_FIELDS, samples.VIEW_COUNT_NAMES)
        self.assertEqual(mail_state.MEDIA_WORDS,
                         mail_parse._KNOWN_MEDIA_TYPES | {mail_lists.MEDIA_TYPE_OTHER} | {
                             main + "/" + mail_lists.MEDIA_TYPE_OTHER for main in mail_lists.MEDIA_MAIN_TYPES})

    def test_every_word_of_the_lists_fits_the_pattern_of_its_place(self):
        import re
        defs = self.schema()["$defs"]
        name, flag, media = (re.compile(defs[key]["pattern"]) for key in ("name", "flag", "media_word"))
        empty = re.compile(defs["name_or_empty"]["pattern"])
        for rule_id, rule in mail_lists.RULES.items():
            if rule.rule_class != mail_lists.CLASS_REFUSE:
                self.assertTrue(name.fullmatch(rule_id), rule_id)
        for words in (mail_lists.GAP_NAMES, mail_lists.AMBIGUOUS_HEADER_NAMES, mail_lists.HEADER_REASONS,
                      mail_lists.PART_ROLES, mail_lists.ATTACHMENT_ROLES, mail_lists.EXTENSION_CLASSES,
                      mail_lists.SIGNATURE_NAMES + (mail_lists.SIGNATURE_NONE,), mail_lists.LINK_KINDS):
            for word in words:
                self.assertTrue(name.fullmatch(word), word)
        for word in mail_lists.GAP_DETAILS + mail_lists.PARSE_BOUND_NAMES + ("",):
            self.assertTrue(empty.fullmatch(word), word)
        for word in mail_lists.LINK_FLAGS:
            self.assertTrue(flag.fullmatch(word), word)
        for word in mail_state.MEDIA_WORDS:
            self.assertTrue(media.fullmatch(word), word)

    def test_the_schema_refuses_a_record_with_an_extra_field(self):
        record = self.scan("several-holds")
        self.assertEqual(mail_state.schema_errors(record), [])
        places = [(), ("subject",), ("inventory",), ("inventory", "parts", 0), ("inventory", "attachments", 0),
                  ("inventory", "links", 0), ("rules", 0), ("gaps", 0), ("header_ambiguous", 0), ("view",),
                  ("view", "counts"), ("versions",)]
        for place in places:
            for key in ("subject_text", "from", "body", "host", "file_name", "reply_target"):
                with self.subTest(place=place, key=key):
                    changed = copy.deepcopy(record)
                    target = changed
                    for step in place:
                        target = target[step]
                    target[key] = "%s text" % MARKER
                    errors = mail_state.schema_errors(changed)
                    self.assertTrue(errors)
                    self.assertNotIn(MARKER, " ".join(errors))
                    self.assert_code("record-invalid", mail_state.store, changed, None, self.root)

    def test_the_schema_refuses_a_missing_field_and_a_value_of_the_wrong_form(self):
        record = self.scan("several-holds")
        for key in record:
            with self.subTest(missing=key):
                changed = {name: value for name, value in record.items() if name != key}
                self.assertTrue(mail_state.schema_errors(changed))
        wrong = {"schema": "intake-verdict.v1", "id": "../../etc/passwd", "time": "today", "sha256": "abc",
                 "subject": {"kind": "skill"}, "sender": "ann@example.org", "verdict": "fine", "reply": "send",
                 "reply_if_released": MARKER, "holds": ["list"], "rules": [{"rule": MARKER, "class": "block",
                                                                           "count": 1}],
                 "gaps": "none", "over_bound": "Bytes Over", "attachment_only": "no", "view": {}, "versions": {},
                 "seal": "0" * 63, "inventory": {"parts": [{"id": "x", "type": "t", "role": "r", "depth": 1}],
                                                 "attachments": [], "links": []}}
        for key, value in wrong.items():
            with self.subTest(wrong=key):
                changed = dict(record, **{key: value})
                self.assertTrue(mail_state.schema_errors(changed))

    def test_the_schema_is_read_with_json_because_the_shared_loader_reads_its_own_only(self):
        with self.assertRaises(Exception):
            mail_reuse.load_schema(str(SCHEMA_FILE))
        self.assertEqual(mail_state.record_schema()["$id"], "mail-verdict.v1")
        self.assertTrue(os.path.samefile(mail_state.SCHEMA_PATH, str(SCHEMA_FILE)))

    def test_without_the_interpreter_nothing_is_built(self):
        with mock.patch.object(mail_reuse, "validate_record", None):
            self.assert_code("schema-unavailable", mail_state.build_record, samples.state_digest(1), None, None,
                             samples.state_decisions()["pass"], None, self.root, NOW)


# --------------------------------------------------------------------------------------
# The root: where it is, modes, the key, atomic writes, ids
# --------------------------------------------------------------------------------------

class Root(StateCase):
    def test_the_root_is_the_argument_then_the_environment_then_the_default(self):
        home = os.environ["HOME"]
        self.assertEqual(mail_state.state_root(self.root), self.root)
        self.assertEqual(mail_state.state_root(Path(self.root)), self.root)
        self.assertEqual(mail_state.state_root(), os.path.join(home, "environment-root"))
        with mock.patch.dict(os.environ, {mail_state.ENV_ROOT: os.path.join(self.tmp, "from-env")}):
            self.assertEqual(mail_state.state_root(), os.path.join(self.tmp, "from-env"))
            self.assertEqual(mail_state.state_root(self.root), self.root)
            record = mail_state.build_record(samples.state_digest(1), None, None, samples.state_decisions()["pass"])
            mail_state.store(record)
            self.assertEqual(mail_state.record_ids(), [record["id"]])
            self.assertEqual(mail_state.load_record(record["id"]), record)
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "from-env", "records", record["id"] + ".json")))
        for empty in ("",):
            with mock.patch.dict(os.environ, {mail_state.ENV_ROOT: empty}):
                self.assertEqual(mail_state.state_root(), os.path.join(home, ".foundry", "mail-scan"))
        environment = {name: value for name, value in os.environ.items() if name != mail_state.ENV_ROOT}
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertEqual(mail_state.state_root(), os.path.join(home, ".foundry", "mail-scan"))
        self.assertEqual(os.listdir(home), [], "naming a root creates nothing")
        for bad in (7, b"bytes", "a\x00b", ["x"]):
            with self.subTest(bad=ascii(bad)):
                self.assert_code("root-unusable", mail_state.state_root, bad)

    def test_the_root_is_0700_and_every_file_0600_whatever_the_umask(self):
        for umask in (0o000, 0o022, 0o077, 0o277, 0o777):
            with self.subTest(umask=oct(umask)):
                root = samples.state_root_dir(self.tmp, "umask-%o" % umask)
                old = os.umask(umask)
                try:
                    record = self.scan("block", root=root)
                    self.override(record, "block", root=root)
                    mail_state.purge(root, NOW)
                finally:
                    os.umask(old)
                self.assertEqual(mode_of(root), 0o700)
                found = set()
                for directory, dirs, names in os.walk(root):
                    for name in dirs:
                        self.assertEqual(mode_of(os.path.join(directory, name)), 0o700, name)
                    for name in names:
                        self.assertEqual(mode_of(os.path.join(directory, name)), 0o600, name)
                        found.add(name if directory == root else os.path.basename(directory))
                self.assertEqual(found, {"key", "lock", "overrides.jsonl", "last-purge", "records", "views", "sheets"})
                self.assertEqual(mail_state.mode_report(root), [])

    def test_a_mode_that_is_too_wide_is_reported_by_a_fixed_label(self):
        record = self.scan("block")
        self.override(record, "block")
        os.chmod(self.root, 0o755)
        os.chmod(os.path.join(self.root, "views"), 0o750)
        os.chmod(os.path.join(self.root, "key"), 0o644)
        os.chmod(self.log_path(), 0o640)
        os.chmod(mail_state.view_path(record["id"], self.root), 0o604)
        os.chmod(mail_state.record_path(record["id"], self.root), 0o660)
        report = mail_state.mode_report(self.root)
        self.assertEqual(sorted(report), sorted([("root", 0o755), ("views", 0o750), ("key", 0o644),
                                                 ("overrides.jsonl", 0o640), ("view-file", 0o604),
                                                 ("record-file", 0o660)]))
        for label, _mode in report:
            self.assertIn(label, mail_state.MODE_LABELS)
        self.assertEqual(mail_state.mode_report(os.path.join(self.tmp, "absent")), [])

    def test_a_directory_that_is_already_there_is_used_and_not_changed(self):
        os.mkdir(self.root, 0o755)
        os.chmod(self.root, 0o755)
        self.scan("pass")
        self.assertEqual(mode_of(self.root), 0o755)
        self.assertEqual(mail_state.mode_report(self.root), [("root", 0o755)])
        blocked = os.path.join(self.tmp, "a-file")
        with open(blocked, "w", encoding="ascii") as handle:
            handle.write("x")
        self.assert_code("root-unusable", mail_state.ensure_root, blocked)
        self.assert_code("root-unusable", mail_state.ensure_root, os.path.join(blocked, "below"))

    def test_the_key_is_made_once_and_is_32_random_bytes(self):
        self.assertFalse(os.path.exists(self.root))
        key = mail_state.state_key(self.root)
        self.assertEqual(len(key), 32)
        path = os.path.join(self.root, "key")
        self.assertEqual(mode_of(path), 0o600)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), key)
        for _ in range(3):
            self.assertEqual(mail_state.state_key(self.root), key)
        self.scan("pass")
        self.assertEqual(mail_state.state_key(self.root, create=False), key)
        self.assertNotEqual(mail_state.state_key(os.path.join(self.tmp, "other")), key)
        absent = os.path.join(self.tmp, "absent")
        self.assert_code("key-unreadable", mail_state.state_key, absent, False)
        self.assertFalse(os.path.exists(absent))

    def test_many_first_uses_at_once_make_one_key(self):
        keys = []
        threads = [threading.Thread(target=lambda: keys.append(mail_state.state_key(self.root))) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(keys), 12)
        self.assertEqual(len(set(keys)), 1)

    def test_a_key_of_another_length_is_not_used_and_not_replaced(self):
        for size in (0, 1, 31, 33, 64, 5000):
            with self.subTest(size=size):
                root = samples.state_root_dir(self.tmp, "key-%d" % size)
                mail_state.ensure_root(root)
                with open(os.path.join(root, "key"), "wb") as handle:
                    handle.write(b"k" * size)
                self.assert_code("key-unreadable", mail_state.state_key, root)
                self.assert_code("key-unreadable", mail_state.sender_hash, "ann@example.org", root)
                with open(os.path.join(root, "key"), "rb") as handle:
                    self.assertEqual(handle.read(), b"k" * size)

    def test_the_sender_hash_is_an_hmac_sha256_of_the_lowercased_address_under_the_key(self):
        value = mail_state.sender_hash("Ann@Example.ORG", self.root)
        with open(os.path.join(self.root, "key"), "rb") as handle:
            key = handle.read()
        self.assertEqual(value, hmac.new(key, b"ann@example.org", hashlib.sha256).hexdigest())
        for same in ("ann@example.org", "ANN@EXAMPLE.ORG", " ann@example.org ", "aNN@eXAMPLE.oRG"):
            self.assertEqual(mail_state.sender_hash(same, self.root), value)
        for other in ("ann@example.net", "an@example.org", "ann@example.org.", "ann+x@example.org"):
            self.assertNotEqual(mail_state.sender_hash(other, self.root), value)
        self.assertNotEqual(mail_state.sender_hash("ann@example.org", os.path.join(self.tmp, "other-root")), value)
        self.assertNotEqual(value, hashlib.sha256(b"ann@example.org").hexdigest())
        for none in (None, "", "   "):
            self.assertIsNone(mail_state.sender_hash(none, self.root))
        for bad in (7, b"ann@example.org", ["ann@example.org"]):
            self.assert_code("sender-invalid", mail_state.sender_hash, bad, self.root)

    def test_a_record_for_a_message_with_no_single_from_has_a_null_sender_and_validates(self):
        raw = samples.from_message(samples.from_values()["two-headers"])
        parsed, view, decision = facts(raw)
        self.assertIsNone(parsed.headers.from_address)
        sender = mail_state.sender_hash(parsed.headers.from_address, self.root)
        self.assertIsNone(sender)
        record = mail_state.build_record(mail_state.raw_digest(raw), parsed, view, decision, sender, self.root, NOW)
        self.assertIsNone(record["sender"])
        self.assertEqual(mail_state.schema_errors(record), [])
        mail_state.store(record, view.framed, self.root)
        self.assertEqual(mail_state.load_record(record["id"], self.root)["sender"], None)
        self.assertEqual(mail_state.earlier_drafts(None, record["sha256"], self.root, NOW), 0)

    def test_a_record_id_is_a_time_stamp_and_eight_random_hex_characters(self):
        import re
        ids = {mail_state.new_record_id(NOW) for _ in range(200)}
        self.assertGreater(len(ids), 195)
        for record_id in ids:
            self.assertTrue(re.fullmatch(r"20261013T120000Z-[0-9a-f]{8}", record_id), record_id)
            self.assertEqual(mail_state.id_time(record_id), NOW)
        self.assertEqual(mail_state.id_time(mail_state.new_record_id(NOW + 0.9)), NOW)
        self.assertLess(abs(mail_state.id_time(mail_state.new_record_id()) - time.time()), 5)
        for impossible in ("20261332T120000Z-0123abcd", "20260230T120000Z-0123abcd", "20261013T250000Z-0123abcd"):
            self.assert_code("id-invalid", mail_state.id_time, impossible)

    def test_nothing_that_is_not_a_record_id_reaches_a_path(self):
        record = self.scan("block")
        outside = os.path.join(self.tmp, "outside.json")
        shutil.copy(mail_state.record_path(record["id"], self.root), outside)
        before = tree_of(self.tmp)
        for bad in samples.bad_record_ids() + ["../../outside", "../outside", os.path.join("..", "..", "outside")]:
            with self.subTest(bad=ascii(bad)):
                for function, args in ((mail_state.load_record, ()), (mail_state.read_view, ()),
                                       (mail_state.record_path, ()), (mail_state.view_path, ()),
                                       (mail_state.sheet_path, ()), (mail_state.effective_record, ()),
                                       (mail_state.id_time, None)):
                    if args is None:
                        self.assert_code("id-invalid", function, bad)
                    else:
                        self.assert_code("id-invalid", function, bad, self.root)
                self.assert_code("id-invalid", mail_state.add_override, bad, "block", "a reason", self.root, NOW)
        self.assertEqual(tree_of(self.tmp), before)

    def test_a_failed_write_leaves_no_partial_file(self):
        self.scan("pass")
        before = tree_of(self.root)
        record = mail_state.build_record(samples.state_digest("second"), samples.state_parsed(), samples.state_view(),
                                         samples.state_decisions()["block"], None, self.root, NOW + 1)
        for name in ("replace", "fsync", "write", "chmod"):
            with self.subTest(fails=name):
                with mock.patch.object(mail_state.os, name, side_effect=OSError("forced")):
                    with self.assertRaises(OSError):
                        mail_state.store(record, samples.state_view()["framed"], self.root)
                self.assertEqual(tree_of(self.root), before)
        # the rename is the last step: a failure of the THIRD write leaves two whole files and no record
        calls = []
        real = os.replace

        def third_fails(source, target):
            calls.append(target)
            if len(calls) == 3:
                raise OSError("forced")
            return real(source, target)

        with mock.patch.object(mail_state.os, "replace", side_effect=third_fails):
            with self.assertRaises(OSError):
                mail_state.store(record, samples.state_view()["framed"], self.root)
        after = tree_of(self.root)
        self.assertEqual(set(after) - set(before), {os.path.join("views", record["id"] + ".txt"),
                                                    os.path.join("sheets", record["id"] + ".txt")})
        self.assertFalse(any(os.path.basename(name).startswith(mail_state.TEMP_PREFIX) for name in after))
        self.assert_code("record-unknown", mail_state.load_record, record["id"], self.root)
        mail_state.store(record, samples.state_view()["framed"], self.root)
        self.assertEqual(mail_state.load_record(record["id"], self.root), record)

    def test_a_failed_rewrite_keeps_the_old_content_whole(self):
        mail_state.purge(self.root, NOW)
        stamp = os.path.join(self.root, "last-purge")
        with open(stamp, "rb") as handle:
            first = handle.read()
        with mock.patch.object(mail_state.os, "replace", side_effect=OSError("forced")):
            with self.assertRaises(OSError):
                mail_state.purge(self.root, NOW + DAY)
        with open(stamp, "rb") as handle:
            self.assertEqual(handle.read(), first)
        self.assertEqual(sorted(os.listdir(self.root)), ["last-purge", "lock", "records", "sheets", "views"])

    def test_a_write_goes_to_a_temporary_file_beside_the_target_and_is_renamed(self):
        seen = []
        real = os.replace

        def watching(source, target):
            seen.append((os.path.dirname(source) == os.path.dirname(target),
                         os.path.basename(source).startswith(mail_state.TEMP_PREFIX), mode_of(source),
                         os.path.exists(target)))
            return real(source, target)

        with mock.patch.object(mail_state.os, "replace", side_effect=watching):
            self.scan("pass")
        self.assertEqual(len(seen), 4)      # the key, the view, the sheet, the record
        self.assertTrue(all(row == (True, True, 0o600, False) for row in seen), seen)

    def test_reading_creates_nothing(self):
        absent = os.path.join(self.tmp, "absent")
        digest = samples.state_digest(1)
        self.assertEqual(mail_state.record_ids(absent), [])
        self.assertEqual(mail_state.read_overrides(absent), mail_state.OverrideLog((), 0))
        self.assertIsNone(mail_state.effective(digest, absent))
        self.assertEqual(mail_state.earlier_drafts("0" * 64, digest, absent, NOW), 0)
        self.assertEqual(mail_state.mode_report(absent), [])
        report = mail_state.retention_report(absent, NOW)
        self.assertEqual((report.records, report.views, report.sheets, report.running), (0, 0, 0, False))
        self.assert_code("record-unknown", mail_state.load_record, "20261013T120000Z-0123abcd", absent)
        self.assert_code("view-unknown", mail_state.read_view, "20261013T120000Z-0123abcd", absent)
        self.assert_code("record-unknown", mail_state.add_override, "20261013T120000Z-0123abcd", "block", "r", absent)
        self.assertFalse(os.path.exists(absent))
        record = self.scan("block")
        before = tree_of(self.root)
        mail_state.record_ids(self.root), mail_state.read_overrides(self.root), mail_state.effective(digest, self.root)
        mail_state.load_record(record["id"], self.root), mail_state.read_view(record["id"], self.root)
        mail_state.effective_record(record["id"], self.root), mail_state.retention_report(self.root, NOW)
        mail_state.earlier_drafts(record["sender"], digest, self.root, NOW), mail_state.mode_report(self.root)
        self.assertEqual(tree_of(self.root), before)

    def test_an_error_carries_one_fixed_word_and_nothing_of_the_input(self):
        for code in mail_state.ERRORS:
            error = StateError(code)
            self.assertEqual((str(error), error.code, error.args), (code, code, (code,)))
        self.assertEqual(len(set(mail_state.ERRORS)), len(mail_state.ERRORS))
        self.assertTrue(set(mail_state.OVERRIDE_REFUSALS) <= set(mail_state.ERRORS))
        record = self.scan("block")
        calls = [
            (mail_state.load_record, ("../%s" % MARKER, self.root)),
            (mail_state.add_override, (record["id"], MARKER, "reason", self.root)),
            (mail_state.add_override, (MARKER, "block", MARKER, self.root)),
            (mail_state.build_record, (MARKER, None, None, {"verdict": MARKER}, None, self.root)),
            (mail_state.sender_hash, ([MARKER], self.root)),
            (mail_state.effective, (MARKER, self.root)),
            (mail_state.store, (record, MARKER, self.root)),
        ]
        for function, args in calls:
            with self.subTest(function=function.__name__):
                with self.assertRaises(StateError) as caught:
                    function(*args)
                self.assertIn(caught.exception.code, mail_state.ERRORS)
                self.assertNotIn(MARKER, repr(caught.exception))
                self.assertIsNone(caught.exception.__cause__)


# --------------------------------------------------------------------------------------
# Storing and reading back
# --------------------------------------------------------------------------------------

class Storing(StateCase):
    def test_store_writes_the_view_the_sheet_and_the_record_under_one_id(self):
        view = samples.state_view()
        record = mail_state.build_record(samples.state_digest(1), samples.state_parsed(), view,
                                         samples.state_decisions()["caution"], None, self.root, NOW)
        self.assertEqual(os.listdir(os.path.join(self.root, "records")), [], "building writes no record")
        stored = mail_state.store(record, view["framed"], self.root)
        name = record["id"]
        self.assertEqual(stored, mail_state.Stored(
            name, os.path.join(self.root, "records", name + ".json"),
            os.path.join(self.root, "views", name + ".txt"), os.path.join(self.root, "sheets", name + ".txt")))
        self.assertEqual((stored.record_path, stored.view_path, stored.sheet_path),
                         (mail_state.record_path(name, self.root), mail_state.view_path(name, self.root),
                          mail_state.sheet_path(name, self.root)))
        with open(stored.view_path, "r", encoding="utf-8", newline="") as handle:
            self.assertEqual(handle.read(), view["framed"])
        with open(stored.record_path, "rb") as handle:
            data = handle.read()
        self.assertTrue(data.isascii() and data.endswith(b"}\n"))
        self.assertEqual(json.loads(data), record)
        self.assertEqual(mail_state.record_ids(self.root), [name])
        self.assertEqual(mail_state.read_view(name, self.root), view["framed"])

    def test_a_view_keeps_text_outside_ascii(self):
        text = "caf" + chr(0xE9) + " " + chr(0x1F3F4) + " " + chr(0x203A) + " quoted"
        framed = mail_frame.frame(text).text
        record = mail_state.build_record(samples.state_digest(1), None, samples.state_view(),
                                         samples.state_decisions()["pass"], None, self.root, NOW)
        mail_state.store(record, framed, self.root)
        self.assertEqual(mail_state.read_view(record["id"], self.root), framed)
        self.assertEqual(mail_frame.content_lines(mail_state.read_view(record["id"], self.root)), [text])

    def test_only_a_framed_view_is_stored_as_a_view(self):
        rng = random.Random(351)
        alphabet = samples.frame_fuzz_alphabet()
        for _ in range(300):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
            self.assertTrue(mail_state.is_frame(mail_frame.frame(text).text), ascii(text))
        _parsed, view, _decision = facts(samples.ordinary_messages()[sorted(samples.ordinary_messages())[0]])
        self.assertTrue(mail_state.is_frame(view.framed))
        record = mail_state.build_record(samples.state_digest(1), None, None, samples.state_decisions()["pass"], None,
                                         self.root, NOW)
        before = tree_of(self.root)
        cases = dict(samples.not_frames(), **{"bytes": b"MAILSCAN-BEGIN-0123456789abcdef\n", "number": 7,
                                              "a list": ["MAILSCAN| x"],
                                              "lone surrogate": samples.state_frame("x" + chr(0xD800))})
        for name, text in cases.items():
            with self.subTest(case=name):
                if name != "lone surrogate":
                    self.assertFalse(mail_state.is_frame(text))
                self.assert_code("view-invalid", mail_state.store, record, text, self.root)
                self.assertEqual(tree_of(self.root), before)
        too_long = samples.state_frame("\n".join(["x" * 180] * 6000))
        self.assertTrue(mail_state.is_frame(too_long))
        self.assert_code("view-invalid", mail_state.store, record, too_long, self.root)
        self.assertEqual(tree_of(self.root), before)

    def test_only_a_record_built_under_this_root_is_stored(self):
        record = mail_state.build_record(samples.state_digest(1), samples.state_parsed(), samples.state_view(),
                                         samples.state_decisions()["block"], None, self.root, NOW)
        before = tree_of(self.root)
        edits = {"holds": [], "verdict": "pass", "reply": "draft", "sha256": samples.state_digest(2),
                 "sender": "0" * 64, "time": "2026-10-13T12:00:01Z", "seal": "0" * 64,
                 "id": "20261013T120000Z-0123abcd"}
        for key, value in edits.items():
            with self.subTest(edited=key):
                self.assert_code("record-invalid", mail_state.store, dict(record, **{key: value}), None, self.root)
        for bad in ({}, {"id": record["id"]}, dict(record, id="../x")):
            with self.subTest(bad=sorted(bad)):
                with self.assertRaises(StateError) as caught:
                    mail_state.store(bad, None, self.root)
                self.assertIn(caught.exception.code, ("record-invalid", "id-invalid"))
        other = samples.state_root_dir(self.tmp, "other")
        foreign = mail_state.build_record(samples.state_digest(1), None, None, samples.state_decisions()["pass"], None,
                                          other, NOW)
        self.assert_code("record-invalid", mail_state.store, foreign, None, self.root)
        self.assertEqual(tree_of(self.root), before)
        mail_state.store(record, None, self.root)
        self.assert_code("record-exists", mail_state.store, record, None, self.root)

    def test_a_record_edited_on_disk_cannot_be_read(self):
        record = self.scan("block")
        path = mail_state.record_path(record["id"], self.root)
        with open(path, "rb") as handle:
            good = handle.read()

        def rewritten(change):
            item = json.loads(good)
            change(item)
            return (json.dumps(item, indent=2, sort_keys=True) + "\n").encode("ascii")

        edits = {
            "holds emptied": rewritten(lambda r: r.update(holds=[])),
            "released": rewritten(lambda r: r.update(holds=[], reply="draft", verdict="pass", rules=[])),
            "verdict": rewritten(lambda r: r.update(verdict="caution")),
            "another digest": rewritten(lambda r: r.update(sha256=samples.state_digest("other"))),
            "another sender": rewritten(lambda r: r.update(sender="0" * 64)),
            "a rule dropped": rewritten(lambda r: r.update(rules=r["rules"][:1])),
            "a count": rewritten(lambda r: r["view"]["counts"].update(hidden_chars=0)),
            "an extra field": rewritten(lambda r: r.update(note="x")),
            "no seal": rewritten(lambda r: r.pop("seal")),
            "cut": good[:len(good) // 2],
            "empty": b"",
            "not json": b"verdict: pass\n",
            "an array": b"[" + good + b"]",
            "a key twice": good.replace(b'{\n', b'{\n  "verdict": "pass",\n', 1),
            "not utf-8": good.replace(b"block", b"bl\xffck", 1),
            "over the bound": good + b" " * mail_state.MAX_RECORD_BYTES,
        }
        for name, data in edits.items():
            with self.subTest(edit=name):
                with open(path, "wb") as handle:
                    handle.write(data)
                self.assert_code("record-unreadable", mail_state.load_record, record["id"], self.root)
                self.assert_code("record-unreadable", mail_state.effective_record, record["id"], self.root)
                self.assert_code("record-unreadable", mail_state.add_override, record["id"], "block", "r", self.root)
                self.assertIsNone(mail_state.effective(record["sha256"], self.root))
        with open(path, "wb") as handle:
            handle.write(json.dumps(json.loads(good)).encode("ascii"))      # other white space, same record
        self.assertEqual(mail_state.load_record(record["id"], self.root), record)
        with open(path, "wb") as handle:
            handle.write(good)
        os.unlink(os.path.join(self.root, "key"))
        self.assert_code("record-unreadable", mail_state.load_record, record["id"], self.root)
        self.assertFalse(os.path.exists(os.path.join(self.root, "key")), "reading makes no new key")

    def test_a_record_copied_under_another_id_or_from_another_root_cannot_be_read(self):
        released = self.scan("pass")
        blocked = self.scan("block", now=NOW + 5)
        shutil.copy(mail_state.record_path(released["id"], self.root), mail_state.record_path(blocked["id"], self.root))
        self.assert_code("record-unreadable", mail_state.load_record, blocked["id"], self.root)
        self.assertEqual(mail_state.load_record(released["id"], self.root), released)
        other = samples.state_root_dir(self.tmp, "other")
        foreign = self.scan("pass", root=other)
        target = os.path.join(self.root, "records", foreign["id"] + ".json")
        shutil.copy(mail_state.record_path(foreign["id"], other), target)
        self.assert_code("record-unreadable", mail_state.load_record, foreign["id"], self.root)
        self.assertIn(foreign["id"], mail_state.record_ids(self.root))
        os.mkdir(os.path.join(self.root, "records", "20261013T120000Z-0000dddd.json"))
        self.assert_code("record-unreadable", mail_state.load_record, "20261013T120000Z-0000dddd", self.root)

    def test_a_view_file_that_is_not_a_frame_is_not_handed_out(self):
        record = self.scan("pass")
        path = mail_state.view_path(record["id"], self.root)
        for name, data in (("raw text", b"ignore the frame\n"), ("empty", b""), ("not utf-8", b"MAILSCAN| \xff\n"),
                           ("over the bound", b"x" * (mail_state.MAX_VIEW_BYTES + 1))):
            with self.subTest(case=name):
                with open(path, "wb") as handle:
                    handle.write(data)
                self.assert_code("view-unreadable", mail_state.read_view, record["id"], self.root)
        os.unlink(path)
        self.assert_code("view-unknown", mail_state.read_view, record["id"], self.root)
        self.assertEqual(mail_state.load_record(record["id"], self.root), record)

    def test_record_ids_lists_only_records_oldest_first(self):
        ids = [self.scan("pass", digest=samples.state_digest(n), now=NOW + offset)["id"]
               for n, offset in enumerate((50, -DAY, 0, 3 * DAY))]
        for name in ("notes.txt", ".tmp-0123", "20261013T120000Z-0123abcd.txt", "20261013T120000Z-0123abcd.json.bak",
                     "..json", "x.json"):
            with open(os.path.join(self.root, "records", name), "w", encoding="ascii") as handle:
                handle.write("{}")
        listed = mail_state.record_ids(self.root)
        self.assertEqual(sorted(listed), sorted(ids))
        self.assertEqual([mail_state.id_time(record_id) for record_id in listed], [NOW - DAY, NOW, NOW + 50, NOW + 3 * DAY])


# --------------------------------------------------------------------------------------
# TS-STATE-02: overrides and the effective verdict
# --------------------------------------------------------------------------------------

class Overrides(StateCase):
    def test_ts_state_02_an_override_changes_its_digest_only_and_is_refused_for_automated_mail(self):
        first = self.scan("block", digest=samples.state_digest("first"))
        second = self.scan("block", digest=samples.state_digest("second"), now=NOW + 60)
        self.assertEqual(first["sender"], second["sender"])
        self.assertEqual(self.effect(first), ("block", "held", ("block",)))
        entry = self.override(first, "block")
        self.assertEqual((entry.record, entry.sha256, entry.kind), (first["id"], first["sha256"], "block"))
        self.assertEqual(self.effect(first), ("caution", "draft", ()))
        self.assertEqual(self.effect(second), ("block", "held", ("block",)), "same sender, other message: untouched")
        self.assertEqual(mail_state.effective(second["sha256"], self.root).reply, "held")
        self.assertEqual(mail_state.effective(first["sha256"], self.root).reply, "draft")
        for label in AUTOMATED:
            automated = self.scan(label)
            before = self.log_bytes()
            for kind in mail_lists.OVERRIDE_KINDS:
                with self.subTest(label=label, kind=kind):
                    self.assert_code("override-automated", mail_state.add_override, automated["id"], kind,
                                     "a reason", self.root, NOW)
            self.assertEqual(self.log_bytes(), before)
            result = mail_state.effective_record(automated["id"], self.root)
            self.assertEqual((result.verdict, result.reply), (automated["verdict"], "none-automated"))

    def test_each_kind_alone_and_together_has_the_effect_of_the_design_table(self):
        self.assertEqual(set(DESIGN_EFFECT) | set(AUTOMATED) | {"several-holds"}, set(samples.state_decisions()))
        for label, table in DESIGN_EFFECT.items():
            for given, expected in table.items():
                with self.subTest(label=label, given=sorted(given)):
                    root = samples.state_root_dir(self.tmp, "%s-%s" % (label, "-".join(sorted(given)) or "none"))
                    record = self.scan(label, root=root)
                    for kind in sorted(given):
                        self.override(record, kind, root=root)
                    result = mail_state.effective_record(record["id"], root)
                    self.assertEqual((result.verdict, result.reply, result.holds), expected)
                    self.assertEqual((result.record_verdict, result.record_reply, result.record_id, result.sha256),
                                     (record["verdict"], record["reply"], record["id"], record["sha256"]))
                    self.assertEqual(result, mail_state.effective(record["sha256"], root))

    def test_a_record_with_several_holds_needs_one_override_per_kind(self):
        kinds = ("block", "budget", "held")
        for size in range(4):
            for given in itertools.combinations(kinds, size):
                with self.subTest(given=given):
                    root = samples.state_root_dir(self.tmp, "several-" + "-".join(given))
                    record = self.scan("several-holds", root=root)
                    for kind in given:
                        self.override(record, kind, root=root)
                    result = mail_state.effective_record(record["id"], root)
                    left = tuple(kind for kind in kinds if kind not in given)
                    self.assertEqual(result.holds, left)
                    self.assertEqual(result.lifted, given)
                    self.assertEqual(result.reply, "held" if left else "draft")
                    self.assertEqual(result.verdict, "caution" if "block" in given else "block")

    def test_an_override_is_refused_for_a_kind_that_is_not_among_the_holds(self):
        refused = 0
        for label, decision in samples.state_decisions().items():
            if label in AUTOMATED:
                continue
            record = self.scan(label, digest=samples.state_digest(label))
            for kind in mail_lists.OVERRIDE_KINDS:
                allowed = decision["reply_if_released"] == "none-list" if kind == "list" else kind in decision["holds"]
                unjudged = decision["reply_if_released"] == "held"
                with self.subTest(label=label, kind=kind):
                    before = self.log_bytes()
                    if allowed and not unjudged:
                        self.override(record, kind)
                        self.assertNotEqual(self.log_bytes(), before)
                    else:
                        self.assert_code("override-not-judged" if unjudged else "kind-not-held",
                                         mail_state.add_override, record["id"], kind, "a reason", self.root, NOW)
                        self.assertEqual(self.log_bytes(), before)
                        refused += 1
        self.assertGreater(refused, 20)

    def test_an_override_is_refused_for_an_unknown_record_an_unknown_kind_and_no_reason(self):
        record = self.scan("block")
        self.assert_code("record-unknown", mail_state.add_override, "20261013T120000Z-0123abcd", "block", "a reason",
                         self.root, NOW)
        for kind in ("", "BLOCK", "Block", "all", "*", "block ", "pass", "draft", None, 7, ["block"], MARKER):
            with self.subTest(kind=ascii(kind)):
                self.assert_code("kind-unknown", mail_state.add_override, record["id"], kind, "a reason", self.root, NOW)
        for reason in ("", " ", "\t\n ", None, 7, b"a reason", ["a reason"]):
            with self.subTest(reason=ascii(reason)):
                self.assert_code("reason-missing", mail_state.add_override, record["id"], "block", reason, self.root,
                                 NOW)
        self.assert_code("time-invalid", mail_state.add_override, record["id"], "block", "a reason", self.root, "now")
        self.assertIsNone(self.log_bytes())
        self.assertEqual(self.effect(record), ("block", "held", ("block",)))
        self.assertEqual(set(mail_lists.OVERRIDE_KINDS), {"block", "list", "budget", "held"})

    def test_the_log_line_holds_the_length_and_hash_of_the_reason_and_not_its_text(self):
        record = self.scan("block")
        reason = "%s said so on the phone, caf%s" % (MARKER, chr(0xE9))
        entry = mail_state.add_override(record["id"], "block", reason, self.root, NOW + 90)
        data = self.log_bytes()
        self.assertTrue(data.isascii() and data.endswith(b"\n") and data.count(b"\n") == 1)
        self.assertNotIn(MARKER.lower().encode("ascii"), data.lower())
        self.assertNotIn(b"phone", data)
        line = json.loads(data)
        self.assertEqual(set(line), {"schema", "time", "record", "sha256", "kind", "reason_length", "reason_sha256",
                                     "user", "basis", "seal"})
        self.assertEqual((line["schema"], line["time"], line["record"], line["sha256"], line["kind"]),
                         ("mail-override.v2", "2026-10-13T12:01:30Z", record["id"], record["sha256"], "block"))
        # what the block override was given for: the block rules of the record, by id
        self.assertEqual(line["basis"], ["hidden-phrase"])
        self.assertEqual(entry.basis, ("hidden-phrase",))
        self.assertEqual(line["reason_length"], len(reason))
        self.assertEqual(line["reason_sha256"], hashlib.sha256(reason.encode("utf-8")).hexdigest())
        self.assertEqual(line["user"], entry.user)
        self.assertRegex(entry.user, r"\A[A-Za-z0-9][A-Za-z0-9._@-]{0,63}\Z")
        self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((entry,), 0))
        for user in ("%s user" % MARKER, "", "a/b", "x" * 65, 7, "new\nline"):
            with self.subTest(user=ascii(user)):
                self.assertEqual(mail_state.add_override(record["id"], "block", "r", self.root, NOW, user).user,
                                 "unknown")
        self.assertNotIn(MARKER.lower().encode("ascii"), self.log_bytes().lower())
        self.assertEqual(mail_state.read_overrides(self.root).ignored, 0)

    def test_the_same_bytes_scanned_again_keep_their_override(self):
        digest = samples.state_digest("same bytes")
        first = self.scan("block", digest=digest)
        self.override(first, "block")
        again = self.scan("block", digest=digest, now=NOW + 600)
        self.assertNotEqual(first["id"], again["id"])
        self.assertEqual(self.effect(again), ("caution", "draft", ()))
        # a later record of the same bytes that is blocked for ANOTHER rule keeps its block
        # (review B F4): the person approved `hidden-phrase`, never `control-token`
        stricter = self.scan("several-holds", digest=digest, now=NOW + 1200)
        self.assertEqual(self.effect(stricter), ("block", "held", ("block", "budget", "held")))
        newest = mail_state.effective(digest, self.root)
        self.assertEqual((newest.record_id, newest.reply, newest.lifted), (stricter["id"], "held", ()))
        # an override given for that record covers it, and the earlier one stays released
        self.override(stricter, "block", now=NOW + 1300)
        self.assertEqual(self.effect(stricter), ("caution", "held", ("budget", "held")))
        self.assertEqual(self.effect(again), ("caution", "draft", ()))

    def test_a_block_override_lifts_only_what_it_was_given_for(self):
        digest = samples.state_digest("one message")
        blocked = self.scan("block", digest=digest)                    # hidden-phrase
        entry = self.override(blocked, "block")
        self.assertEqual(entry.basis, ("hidden-phrase",))
        self.assertEqual(mail_state.block_basis(blocked), ("hidden-phrase",))
        for label, lifted in (("block", True), ("no-single-from", False), ("list-block", False),
                              ("block-budget", False), ("several-holds", False)):
            with self.subTest(later=label):
                later = self.scan(label, digest=digest, now=NOW + 60)
                result = mail_state.effective_record(later["id"], self.root)
                self.assertEqual("block" not in result.holds, lifted)
                self.assertEqual(result.verdict, "caution" if lifted else "block")
                if not lifted:
                    self.assertEqual(result.reply, "held")
        # a basis that covers MORE than the record is blocked for lifts it; one that covers less does not
        both = mail_state.Override(mail_state.time_text(NOW), blocked["id"], digest, "block", 1, "1" * 64, "tester",
                                   ("hidden-phrase", "link-scheme"))
        none = both._replace(basis=())
        other = self.scan("list-block", digest=digest, now=NOW + 120)   # link-scheme
        self.assertEqual(mail_state.effective_of(other, [both]).holds, ())
        self.assertEqual(mail_state.effective_of(other, [none]).holds, ("block",))
        self.assertEqual(mail_state.effective_of(blocked, [none]).holds, ("block",))
        # a block-class gap is part of what a record is blocked for
        self.assertEqual(mail_state.block_basis(samples.state_decisions()["scanner-error"] | {
            "rules": [], "gaps": [{"gap": "scanner-error", "class": "block"}]}), ("scanner-error",))

    def test_an_override_on_a_message_nobody_read_is_refused(self):
        # review B F4: an override given on a scanner-error record lifted a later REAL block of the same bytes
        digest = samples.state_digest("the reviewer's chain")
        error = self.scan("scanner-error", digest=digest, with_view=False)
        before = self.log_bytes()
        for kind in mail_lists.OVERRIDE_KINDS:
            with self.subTest(kind=kind):
                self.assert_code("override-not-judged", mail_state.add_override, error["id"], kind, "transient",
                                 self.root, NOW)
        self.assertEqual(self.log_bytes(), before)
        self.assertIn("override-not-judged", mail_state.OVERRIDE_REFUSALS)
        real = self.scan("several-holds", digest=digest, now=NOW + 60)     # the scan that worked: control-token
        self.assertEqual(self.effect(real), ("block", "held", ("block", "budget", "held")))
        self.assertEqual(self.effect(error), ("block", "held", ("block",)))
        # and a line that claims such an override, sealed by this root with an empty basis, lifts nothing either
        self.append_raw(self.sealed_line(record=error["id"], sha256=digest, kind="block") + b"\n")
        self.assertEqual(mail_state.read_overrides(self.root).ignored, 0)
        self.assertEqual(self.effect(real), ("block", "held", ("block", "budget", "held")))

    def test_a_line_copied_to_another_record_of_the_same_sender_lifts_nothing(self):
        first = self.scan("block", digest=samples.state_digest("first"))
        second = self.scan("block", digest=samples.state_digest("second"), now=NOW + 60)
        self.override(first, "block")
        line = self.log_bytes()
        # typed by hand: the same line with the id, or the digest, of the other record
        self.append_raw(line.replace(first["id"].encode("ascii"), second["id"].encode("ascii")))
        self.append_raw(line.replace(first["sha256"].encode("ascii"), second["sha256"].encode("ascii")))
        self.append_raw(line.replace(first["id"].encode("ascii"), second["id"].encode("ascii")).replace(
            first["sha256"].encode("ascii"), second["sha256"].encode("ascii")))
        self.append_raw(line)       # the good line once more: a repeat changes nothing
        log = mail_state.read_overrides(self.root)
        self.assertEqual((len(log.entries), log.ignored), (2, 3))
        self.assertEqual(self.effect(second), ("block", "held", ("block",)))
        self.assertEqual(self.effect(first), ("caution", "draft", ()))
        # even a line with a GOOD seal that names the second record lifts nothing unless its digest is that record's
        self.append_raw(self.sealed_line(record=second["id"], sha256=first["sha256"]) + b"\n")
        self.assertEqual(mail_state.read_overrides(self.root).ignored, 3)
        self.assertEqual(self.effect(second), ("block", "held", ("block",)))

    def test_a_typed_line_with_a_wrong_digest_or_an_unknown_kind_lifts_nothing(self):
        record = self.scan("several-holds")
        mail_state.state_key(self.root)
        wrong = [
            ("another digest", self.sealed_line(record=record["id"], sha256=samples.state_digest("x")), 0),
            ("a digest one character off", self.sealed_line(
                record=record["id"], sha256=record["sha256"][:-1] + ("0" if record["sha256"][-1] != "0" else "1")), 0),
            ("an unknown kind", self.sealed_line(record=record["id"], sha256=record["sha256"], kind="all"), 1),
            ("a kind in capitals", self.sealed_line(record=record["id"], sha256=record["sha256"], kind="BLOCK"), 1),
            ("an empty kind", self.sealed_line(record=record["id"], sha256=record["sha256"], kind=""), 1),
            ("a digest in capitals", self.sealed_line(record=record["id"], sha256=record["sha256"].upper()), 1),
            ("a reason of no length", self.sealed_line(record=record["id"], sha256=record["sha256"],
                                                       reason_length=0), 1),
            ("a record id that is a path", self.sealed_line(record="../../x", sha256=record["sha256"]), 1),
            ("a time that is none", self.sealed_line(record=record["id"], sha256=record["sha256"],
                                                    time="2026-13-45T99:99:99Z"), 1),
            ("a user of many words", self.sealed_line(record=record["id"], sha256=record["sha256"],
                                                     user="some body"), 1),
        ]
        ignored = 0
        for name, line, counted in wrong:
            with self.subTest(line=name):
                self.append_raw(line + b"\n")
                ignored += counted
                log = mail_state.read_overrides(self.root)
                self.assertEqual(log.ignored, ignored)
                self.assertEqual(self.effect(record), ("block", "held", ("block", "budget", "held")))
        good = self.sealed_line(record=record["id"], sha256=record["sha256"], kind="budget")
        variants = [
            ("no seal", json.dumps({k: v for k, v in json.loads(good).items() if k != "seal"}, sort_keys=True,
                                   separators=(",", ":")).encode("ascii")),
            ("a seal of zeros", good.replace(json.loads(good)["seal"].encode("ascii"), b"0" * 64)),
            ("the seal of another root", self.sealed_line(samples.state_root_dir(self.tmp, "other"),
                                                          record=record["id"], sha256=record["sha256"], kind="budget")),
            ("the seal of another kind", good.replace(b'"kind":"budget"', b'"kind":"block"')),
            ("a record seal", good.replace(json.loads(good)["seal"].encode("ascii"), record["seal"].encode("ascii"))),
            ("other spacing", json.dumps(json.loads(good), sort_keys=True).encode("ascii")),
            ("another key order", json.dumps(dict(reversed(list(json.loads(good).items()))),
                                             separators=(",", ":")).encode("ascii")),
            ("an extra key", good[:-1] + b',"note":"x"}'),
            ("a missing key", json.dumps({k: v for k, v in json.loads(good).items() if k != "user"}, sort_keys=True,
                                         separators=(",", ":")).encode("ascii")),
            ("another schema", good.replace(b"mail-override.v2", b"mail-override.v1")),
            ("a basis on a kind that has none", self.sealed_line(record=record["id"], sha256=record["sha256"],
                                                                 kind="budget", basis=("control-token",))),
            ("a basis that names no block rule", self.sealed_line(record=record["id"], sha256=record["sha256"],
                                                                  kind="block", basis=("reply-budget",))),
            ("a basis out of order", self.sealed_line(record=record["id"], sha256=record["sha256"], kind="block",
                                                      basis=("link-scheme", "control-token"))),
            ("no basis key", json.dumps({k: v for k, v in json.loads(good).items() if k != "basis"}, sort_keys=True,
                                        separators=(",", ":")).encode("ascii")),
            ("leading space", b" " + good),
            ("a carriage return", good + b"\r"),
        ]
        for name, line in variants:
            with self.subTest(line=name):
                self.append_raw(line + b"\n")
                ignored += 1
                self.assertEqual(mail_state.read_overrides(self.root).ignored, ignored)
                self.assertEqual(self.effect(record), ("block", "held", ("block", "budget", "held")))
        self.append_raw(good + b"\n")       # the line itself counts: every refusal above was for its own reason
        self.assertEqual(self.effect(record), ("block", "held", ("block", "held")))
        self.assertEqual(mail_state.read_overrides(self.root).ignored, ignored)

    def test_a_cut_or_malformed_line_fails_closed(self):
        record = self.scan("block-budget")
        self.override(record, "budget")
        self.assertEqual(self.effect(record), ("block", "held", ("block",)))
        block = self.sealed_line(record=record["id"], sha256=record["sha256"], kind="block")
        ignored = 0
        for name, text in samples.bad_log_lines().items():
            with self.subTest(line=name):
                self.append_raw(text.encode("utf-8") + b"\n")
                ignored += 1 if text else 0         # an empty line is nothing at all
                log = mail_state.read_overrides(self.root)
                self.assertEqual((len(log.entries), log.ignored), (1, ignored))
                self.assertEqual(self.effect(record), ("block", "held", ("block",)))
        for name, data in (("not utf-8", b"\xff\xfe" + block), ("a line of 2 MB", b"[" * 2_000_000),
                           ("nested deep", b'{"a":' * 5000), ("a huge number", b'{"reason_length":' + b"9" * 5000)):
            with self.subTest(line=name):
                self.append_raw(data + b"\n")
                ignored += 1
                self.assertEqual(mail_state.read_overrides(self.root).ignored, ignored)
                self.assertEqual(self.effect(record), ("block", "held", ("block",)))
        base = self.log_bytes()
        for cut in range(len(block)):       # the good line, cut at every byte, as the end of the log
            with open(self.log_path(), "wb") as handle:
                handle.write(base + block[:cut])
            log = mail_state.read_overrides(self.root)
            if (len(log.entries), log.ignored) != (1, ignored + (1 if cut else 0)):
                self.fail("a line cut at byte %d was read as %r" % (cut, log))
            if self.effect(record) != ("block", "held", ("block",)):
                self.fail("a line cut at byte %d lifted a hold" % cut)
        for cut in (1, len(block) // 2, len(block) - 1):       # and cut, then closed by a newline
            with open(self.log_path(), "wb") as handle:
                handle.write(base + block[:cut] + b"\n")
            self.assertEqual(mail_state.read_overrides(self.root).ignored, ignored + 1)
            self.assertEqual(self.effect(record), ("block", "held", ("block",)))

    def test_a_whole_line_without_its_newline_does_not_count_and_the_next_append_stays_apart(self):
        record = self.scan("several-holds")
        mail_state.state_key(self.root)
        mail_state.ensure_root(self.root)
        typed = self.sealed_line(record=record["id"], sha256=record["sha256"], kind="held")
        with open(self.log_path(), "wb") as handle:
            handle.write(typed[:-20])               # a line somebody cut short, no newline
        self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((), 1))
        entry = self.override(record, "block")
        data = self.log_bytes()
        self.assertEqual(data.count(b"\n"), 2)
        self.assertTrue(data.startswith(typed[:-20] + b"\n{"))
        self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((entry,), 1))
        self.assertEqual(self.effect(record), ("caution", "held", ("budget", "held")))
        with open(self.log_path(), "ab") as handle:
            handle.write(typed)                     # whole, but not ended: not yet a line
        self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((entry,), 2))
        self.assertEqual(self.effect(record), ("caution", "held", ("budget", "held")))

    def test_a_record_edited_after_its_override_is_not_released_by_it(self):
        target = self.scan("block", digest=samples.state_digest("target"))
        other = self.scan("several-holds", digest=samples.state_digest("other"), now=NOW + 60)
        self.override(target, "block")
        self.assertEqual(self.effect(target), ("caution", "draft", ()))
        path = mail_state.record_path(other["id"], self.root)
        with open(path, "rb") as handle:
            good = handle.read()
        # the other record is edited to carry the digest the override names
        edited = json.loads(good)
        edited["sha256"] = target["sha256"]
        with open(path, "wb") as handle:
            handle.write((json.dumps(edited, indent=2, sort_keys=True) + "\n").encode("ascii"))
        self.assert_code("record-unreadable", mail_state.effective_record, other["id"], self.root)
        self.assertEqual(mail_state.effective(target["sha256"], self.root).record_id, target["id"])
        with open(path, "wb") as handle:
            handle.write(good)
        self.assertEqual(self.effect(other), ("block", "held", ("block", "budget", "held")))
        # the overridden record itself is edited afterwards: it is no longer a record, so nothing is released
        path = mail_state.record_path(target["id"], self.root)
        with open(path, "rb") as handle:
            good = handle.read()
        for name, change in (("holds", lambda r: r.update(holds=[])), ("verdict", lambda r: r.update(verdict="pass")),
                             ("reply", lambda r: r.update(reply="draft", holds=[])),
                             ("released", lambda r: r.update(reply_if_released="none-list"))):
            with self.subTest(edited=name):
                item = json.loads(good)
                change(item)
                with open(path, "wb") as handle:
                    handle.write((json.dumps(item, indent=2, sort_keys=True) + "\n").encode("ascii"))
                self.assert_code("record-unreadable", mail_state.effective_record, target["id"], self.root)
                self.assertIsNone(mail_state.effective(target["sha256"], self.root))
        with open(path, "wb") as handle:
            handle.write(good)
        self.assertEqual(self.effect(target), ("caution", "draft", ()))

    def test_an_override_of_another_root_or_after_a_lost_key_lifts_nothing(self):
        record = self.scan("block")
        other = samples.state_root_dir(self.tmp, "other")
        foreign = self.scan("block", digest=record["sha256"], root=other)
        self.override(foreign, "block", root=other)
        shutil.copy(self.log_path(other), self.log_path())
        self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((), 1))
        self.assertEqual(self.effect(record), ("block", "held", ("block",)))
        os.unlink(self.log_path())
        entry = self.override(record, "block")
        self.assertEqual(mail_state.read_overrides(self.root).entries, (entry,))
        os.unlink(os.path.join(self.root, "key"))
        self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((), 1))
        self.assertFalse(os.path.exists(os.path.join(self.root, "key")))

    def test_a_log_that_cannot_be_read_lifts_nothing(self):
        record = self.scan("block")
        self.override(record, "block")
        with mock.patch.object(mail_state, "MAX_LOG_BYTES", 10):
            self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((), 1))
            self.assertEqual(self.effect(record), ("block", "held", ("block",)))
        os.rename(self.log_path(), self.log_path() + ".kept")
        os.mkdir(self.log_path())
        self.assertEqual(mail_state.read_overrides(self.root), mail_state.OverrideLog((), 1))
        self.assertEqual(self.effect(record), ("block", "held", ("block",)))
        os.rmdir(self.log_path())
        os.rename(self.log_path() + ".kept", self.log_path())
        self.assertEqual(self.effect(record), ("caution", "draft", ()))

    def test_appends_from_many_threads_are_all_whole_lines(self):
        record = self.scan("several-holds")
        errors = []

        def work(number):
            try:
                for index in range(20):
                    mail_state.add_override(record["id"], ("block", "budget", "held")[index % 3],
                                            "reason %d %d" % (number, index), self.root, NOW + index, "tester")
            except Exception as error:      # pragma: no cover - reported below
                errors.append(error)

        threads = [threading.Thread(target=work, args=(number,)) for number in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        log = mail_state.read_overrides(self.root)
        self.assertEqual((len(log.entries), log.ignored), (160, 0))
        data = self.log_bytes()
        self.assertEqual(data.count(b"\n"), 160)
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(len({entry.reason_sha256 for entry in log.entries}), 160)
        self.assertEqual(self.effect(record), ("caution", "draft", ()))

    def test_appends_from_several_processes_are_all_whole_lines(self):
        record = self.scan("block")
        child = ("import sys\n"
                 "sys.path.insert(0, sys.argv[1])\n"
                 "import mail_state\n"
                 "for index in range(25):\n"
                 "    mail_state.add_override(sys.argv[3], 'block', 'reason %s %d' % (sys.argv[4], index),\n"
                 "                            sys.argv[2], None, 'tester')\n")
        children = [subprocess.Popen([sys.executable, "-c", child, str(SCRIPTS), self.root, record["id"], str(number)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for number in range(4)]
        for process in children:
            out, err = process.communicate(timeout=120)
            self.assertEqual((process.returncode, out), (0, b""), err.decode("utf-8", "replace")[-2000:])
        log = mail_state.read_overrides(self.root)
        self.assertEqual((len(log.entries), log.ignored), (100, 0))
        self.assertEqual(len({entry.reason_sha256 for entry in log.entries}), 100)
        self.assertEqual(self.log_bytes().count(b"\n"), 100)

    def test_an_append_waits_for_the_lock_and_a_reader_sees_whole_lines_only(self):
        record = self.scan("block")
        self.override(record, "block")
        done = threading.Event()

        def append():
            self.override(record, "block", "second")
            done.set()

        with mail_state._locked(self.root):
            thread = threading.Thread(target=append)
            thread.start()
            self.assertFalse(done.wait(0.3), "an append went ahead while the lock was held")
            self.assertEqual(self.log_bytes().count(b"\n"), 1)
        thread.join(30)
        self.assertTrue(done.is_set())
        self.assertEqual(len(mail_state.read_overrides(self.root).entries), 2)
        writes = []
        real = os.write

        def watching(fd, data):
            writes.append(bytes(data))
            return real(fd, data)

        with mock.patch.object(mail_state.os, "write", side_effect=watching):
            self.override(record, "block", "third")
        self.assertEqual(len(writes), 1, "one line is one write")
        self.assertTrue(writes[0].startswith(b"{") and writes[0].endswith(b"}\n") and writes[0].count(b"\n") == 1)

    def test_nothing_releases_automated_mail_whatever_a_record_claims(self):
        entries = [mail_state.Override(mail_state.time_text(NOW), "20261013T120000Z-0123abcd", "0" * 64, kind, 1,
                                       "1" * 64, "tester") for kind in mail_lists.OVERRIDE_KINDS]
        # records `build_record` refuses, handed to the pure function as they are
        for verdict, holds, released in (("block", ["block"], "draft"), ("block", [], "none-automated"),
                                         ("pass", ["held", "budget"], "none-list"), ("caution", [], "draft")):
            with self.subTest(verdict=verdict, holds=holds, released=released):
                record = {"id": "20261013T120000Z-0123abcd", "sha256": "0" * 64, "verdict": verdict,
                          "reply": "none-automated", "reply_if_released": released, "holds": holds}
                result = mail_state.effective_of(record, entries)
                self.assertEqual((result.verdict, result.reply, list(result.holds), result.lifted),
                                 (verdict, "none-automated", holds, ()))

    def test_effective_by_digest_reads_the_newest_readable_record(self):
        digest = samples.state_digest("d")
        self.assertIsNone(mail_state.effective(digest, self.root))
        old = self.scan("pass", digest=digest, now=NOW - DAY)
        new = self.scan("block", digest=digest)
        self.scan("pass", digest=samples.state_digest("another"), now=NOW + DAY)
        result = mail_state.effective(digest, self.root)
        self.assertEqual((result.record_id, result.verdict, result.reply), (new["id"], "block", "held"))
        with open(mail_state.record_path(new["id"], self.root), "ab") as handle:
            handle.write(b"x")
        self.assertEqual(mail_state.effective(digest, self.root).record_id, old["id"])
        for bad in ("", "abc", "0" * 63, digest.upper(), None, 7, MARKER):
            with self.subTest(bad=ascii(bad)):
                self.assert_code("digest-invalid", mail_state.effective, bad, self.root)

    def test_no_set_of_overrides_releases_more_than_the_table_allows(self):
        rng = random.Random(3512)
        decisions = samples.state_decisions()
        records = {label: mail_state.build_record(samples.state_digest(label), None, None, decision, None, self.root,
                                                  NOW) for label, decision in decisions.items()}
        severity = {"pass": 0, "caution": 1, "block": 2}
        for _ in range(3000):
            label = rng.choice(sorted(records))
            record = records[label]
            entries = []
            blocked_for = mail_state.block_basis(record)
            for _n in range(rng.randint(0, 6)):
                digest = record["sha256"] if rng.random() < 0.7 else samples.state_digest(rng.randint(0, 5))
                kind = rng.choice(mail_lists.OVERRIDE_KINDS)
                # a block line is given for what this record is blocked for, for something else, or for nothing
                basis = rng.choice((blocked_for, ("link-userinfo",), ())) if kind == "block" else ()
                entries.append(mail_state.Override(mail_state.time_text(NOW), record["id"], digest, kind, 1,
                                                   "0" * 64, "tester", basis))
            result = mail_state.effective_of(record, entries)
            mine = {entry.kind for entry in entries if entry.sha256 == record["sha256"]
                    and (entry.kind != "block" or set(blocked_for) <= set(entry.basis))}
            self.assertIn(result.verdict, mail_lists.VERDICTS)
            self.assertIn(result.reply, mail_lists.REPLIES)
            self.assertTrue(set(result.holds) <= set(record["holds"]))
            self.assertEqual(set(record["holds"]) - set(result.holds), set(record["holds"]) & mine)
            self.assertTrue(set(result.lifted) <= mine)
            if record["reply"] == "none-automated":
                self.assertEqual((result.verdict, result.reply, result.lifted),
                                 (record["verdict"], "none-automated", ()))
            if result.holds:
                self.assertEqual(result.reply, "held")
            if not mine:
                self.assertEqual((result.verdict, result.reply, list(result.holds), result.lifted),
                                 (record["verdict"], record["reply"], record["holds"], ()))
            if result.reply == "draft" and record["reply"] != "draft":
                self.assertTrue(mine, "a draft nobody released")
                self.assertTrue(set(record["holds"]) <= mine)
                if record["reply_if_released"] == "none-list":
                    self.assertIn("list", mine)
                self.assertNotEqual(record["reply_if_released"], "held")
            if result.verdict != record["verdict"]:
                self.assertEqual((record["verdict"], result.verdict), ("block", "caution"))
                self.assertIn("block", mine)
            self.assertGreaterEqual(severity[result.verdict], min(severity[record["verdict"]], 1))


class KeyAndLinks(StateCase):
    """Fix round 1 (reviews B m6, m7 and C F9): a lost key is never replaced; no link leads out of the root."""

    def test_a_root_with_records_and_no_key_is_key_missing_and_gets_no_new_key(self):
        record = self.scan("pass")
        key_file = os.path.join(self.root, mail_state.FILE_KEY)
        old_key = open(key_file, "rb").read()
        os.unlink(key_file)
        self.assertTrue(mail_state.key_missing(self.root))
        for call in (lambda: mail_state.state_key(self.root),
                     lambda: mail_state.sender_hash(samples.STATE_SENDER_ADDRESS, self.root),
                     lambda: self.scan("pass", digest=samples.state_digest("next"))):
            self.assert_code("key-missing", call)
            self.assertFalse(os.path.lexists(key_file), "no key was made")
        self.assert_code("key-unreadable", mail_state.state_key, self.root, False)
        self.assert_code("record-unreadable", mail_state.load_record, record["id"], self.root)
        # the key restored: everything reads again
        with open(key_file, "wb") as handle:
            handle.write(old_key)
        os.chmod(key_file, 0o600)
        self.assertFalse(mail_state.key_missing(self.root))
        self.assertEqual(mail_state.load_record(record["id"], self.root)["id"], record["id"])
        self.assertIn("key-missing", mail_state.ERRORS)

    def test_a_new_root_and_a_root_with_no_record_still_get_their_key(self):
        fresh = samples.state_root_dir(self.tmp, "fresh")
        self.assertFalse(mail_state.key_missing(fresh))
        self.assertEqual(len(mail_state.state_key(fresh)), mail_state.KEY_BYTES)
        emptied = samples.state_root_dir(self.tmp, "emptied")
        record = self.scan("pass", root=emptied)
        os.unlink(mail_state.record_path(record["id"], emptied))
        os.unlink(os.path.join(emptied, mail_state.FILE_KEY))
        self.assertFalse(mail_state.key_missing(emptied))
        self.assertEqual(len(mail_state.state_key(emptied)), mail_state.KEY_BYTES)
        # a file in records/ that is no record of ours is not a reason to refuse
        with open(os.path.join(emptied, mail_state.DIR_RECORDS, "notes.txt"), "w", encoding="utf-8") as handle:
            handle.write("x")
        os.unlink(os.path.join(emptied, mail_state.FILE_KEY))
        self.assertEqual(len(mail_state.state_key(emptied)), mail_state.KEY_BYTES)

    def test_a_directory_of_the_root_that_is_a_link_is_refused(self):
        for name in mail_state.STATE_DIRS:
            with self.subTest(directory=name):
                root = samples.state_root_dir(self.tmp, "linked-%s" % name)
                outside = os.path.join(self.tmp, "outside-%s" % name)
                os.makedirs(outside)
                os.makedirs(root, 0o700)
                os.symlink(outside, os.path.join(root, name))
                self.assert_code("root-unusable", mail_state.ensure_root, root)
                self.assert_code("root-unusable", self.scan, "pass", root=root)
                record_id = mail_state.new_record_id(NOW)
                path = {"records": mail_state.record_path, "views": mail_state.view_path,
                        "sheets": mail_state.sheet_path}[name]
                self.assert_code("root-unusable", path, record_id, root)
                self.assertEqual(os.listdir(outside), [], "nothing was written outside the root")
        # a link made AFTER the root was in use is refused as well
        root = samples.state_root_dir(self.tmp, "linked-later")
        record = self.scan("pass", root=root)
        outside = os.path.join(self.tmp, "outside-later")
        os.rename(os.path.join(root, "views"), outside)
        os.symlink(outside, os.path.join(root, "views"))
        self.assert_code("root-unusable", mail_state.read_view, record["id"], root)
        self.assert_code("root-unusable", self.scan, "pass", digest=samples.state_digest("later"), root=root)
        self.assert_code("root-unusable", mail_state.retention_report, root, NOW)
        self.assertEqual(sorted(os.listdir(outside)), [record["id"] + ".txt"])
        self.assertIn(("views", 0o777), mail_state.mode_report(root))

    def test_the_root_itself_may_be_a_link(self):
        real = os.path.join(self.tmp, "real-root")
        os.makedirs(real, 0o700)
        link = os.path.join(self.tmp, "link-to-root")
        os.symlink(real, link)
        record = self.scan("pass", root=link)
        self.assertEqual(mail_state.load_record(record["id"], link)["id"], record["id"])
        self.assertTrue(os.path.isfile(os.path.join(real, "records", record["id"] + ".json")))


# --------------------------------------------------------------------------------------
# The budget query
# --------------------------------------------------------------------------------------

class Budget(StateCase):
    def count(self, digest, address=samples.STATE_SENDER_ADDRESS, now=NOW):
        return mail_state.earlier_drafts(mail_state.sender_hash(address, self.root), digest, self.root, now)

    def test_the_budget_query_counts_distinct_earlier_drafts_of_one_sender(self):
        asked = samples.state_digest("asked")
        self.assertEqual(self.count(asked), 0)
        for number in range(1, 5):
            self.scan("pass", digest=samples.state_digest(number), now=NOW - number * 3600)
            self.assertEqual(self.count(asked), number)
        # digest 2 arrived two hours ago: only 3 and 4 came before it; 1 came after and does not count
        self.assertEqual(self.count(samples.state_digest(2)), 2, "its own digest and later mail are left out")
        self.scan("pass", digest=samples.state_digest(2), now=NOW - 60)
        self.scan("caution", digest=samples.state_digest(2), now=NOW - 30)
        self.assertEqual(self.count(asked), 4, "the same bytes scanned again count once")
        self.assertEqual(self.count(samples.state_digest(2)), 2, "and are placed by their first record")
        self.assertEqual([self.count(samples.state_digest(number)) for number in (4, 3, 2, 1)], [0, 1, 2, 3])

    def test_mail_that_came_later_never_counts_against_an_earlier_message(self):
        digests = [samples.state_digest("mail %d" % number) for number in range(1, 6)]
        first = [self.count(digest, now=NOW + index) or 0 for index, digest in enumerate(digests[:1])]
        records = []
        counts = []
        for index, digest in enumerate(digests):
            counts.append(self.count(digest, now=NOW + index))
            records.append(self.scan("budget" if counts[-1] >= 3 else "pass", digest=digest, now=NOW + index))
        # mail four was HELD by the budget, so it got no draft and does not count against mail five
        self.assertEqual((first, counts), ([0], [0, 1, 2, 3, 3]))
        # every one scanned again, much later, any number of times: the count of its first scan
        for round_number in range(3):
            later = NOW + 3600 * (round_number + 1)
            again = [self.count(digest, now=later) for digest in digests]
            self.assertEqual(again, [0, 1, 2, 3, 3])
            for index, digest in enumerate(digests):
                self.scan("budget" if again[index] >= 3 else "pass", digest=digest, now=later + index)
        # an override on mail four lifts ITS hold: it is released into a draft, so from now on it
        # counts against the mail that came after it; mail five stays held
        self.override(records[3], "budget")
        self.assertEqual(self.effect(records[3]), ("pass", "draft", ()))
        rescanned = self.scan("budget", digest=digests[3], now=NOW + 9 * 3600)
        self.assertEqual(self.effect(rescanned), ("pass", "draft", ()))
        self.assertEqual([self.count(digest, now=NOW + 10 * 3600) for digest in digests], [0, 1, 2, 3, 4])
        self.assertEqual(self.effect(records[4]), ("pass", "held", ("budget",)))
        # a mail nobody scanned yet comes after all of them: three drafts and the released one
        self.assertEqual(self.count(samples.state_digest("new"), now=NOW + 10 * 3600), 4)

    def test_records_of_one_second_are_ordered_by_their_record_id(self):
        digests = [samples.state_digest("tie %d" % number) for number in range(4)]
        records = [self.scan("pass", digest=digest, now=NOW) for digest in digests]
        self.assertEqual(len({record["time"] for record in records}), 1)
        by_id = sorted(records, key=lambda record: record["id"])
        for _again in range(2):     # stable: the same answer every time
            self.assertEqual([self.count(record["sha256"], now=NOW + 60) for record in by_id], [0, 1, 2, 3])
        # a message with no record yet, asked about in that same second, comes after all four
        self.assertEqual(self.count(samples.state_digest("fifth"), now=NOW), 4)
        self.assertEqual(self.count(samples.state_digest("fifth"), now=NOW - 1), 0)

    def test_the_window_of_a_message_scanned_before_ends_at_its_first_record(self):
        asked = samples.state_digest("asked")
        self.scan("pass", digest=asked, now=NOW - 3 * DAY)
        for label, age in (("too old", 10 * DAY + 1), ("at the edge", 10 * DAY), ("before", 5 * DAY),
                           ("after", 2 * DAY), ("today", 0)):
            self.scan("pass", digest=samples.state_digest(label), now=NOW - age)
        self.assertEqual(self.count(asked), 2)          # at the edge and before
        self.scan("pass", digest=asked, now=NOW)        # scanned again today: still placed three days ago
        self.assertEqual(self.count(asked), 2)

    def test_record_files_are_chosen_by_the_time_in_their_id_before_they_are_opened(self):
        asked = samples.state_digest("asked")
        old = [self.scan("pass", digest=samples.state_digest("old %d" % number), now=NOW - (20 + number) * DAY)
               for number in range(5)]
        recent = [self.scan("pass", digest=samples.state_digest("recent %d" % number), now=NOW - number * 3600)
                  for number in range(3)]
        ahead = self.scan("pass", digest=samples.state_digest("ahead"), now=NOW + DAY)
        opened = []
        real = mail_state.load_record

        def counting(record_id, root=None):
            opened.append(record_id)
            return real(record_id, root)

        with mock.patch.object(mail_state, "load_record", counting):
            self.assertEqual(self.count(asked), 3)
        self.assertEqual(sorted(opened), sorted(record["id"] for record in recent))
        for record in old + [ahead]:
            self.assertNotIn(record["id"], opened)
        # the first record of a message is followed back a week at a time
        chained = samples.state_digest("chained")
        self.scan("pass", digest=chained, now=NOW - 12 * DAY)
        self.scan("pass", digest=chained, now=NOW - 6 * DAY)
        self.scan("pass", digest=samples.state_digest("before the first"), now=NOW - 13 * DAY)
        self.assertEqual(self.count(chained), 1)        # placed twelve days ago: only what came before THAT
        # the price, stated: a message whose records all lie more than two weeks back is placed at now
        lone = samples.state_digest("lone")
        self.scan("pass", digest=lone, now=NOW - 16 * DAY)
        self.assertEqual(self.count(lone), 3)           # the three recent ones: as if it had never been scanned
        self.assertEqual((mail_lists.BUDGET_WINDOW_DAYS, mail_lists.BUDGET_LOOKBACK_DAYS), (7, 14))

    def test_the_budget_window_is_seven_days_by_the_time_of_the_record(self):
        asked = samples.state_digest("asked")
        week = mail_lists.BUDGET_WINDOW_DAYS * DAY
        self.assertEqual(week, 7 * DAY)
        for name, age, counted in (("eight days", 8 * DAY, 0), ("seven days and a second", week + 1, 0),
                                   ("exactly seven days", week, 1), ("a second less", week - 1, 1),
                                   ("now", 0, 1), ("ahead of the clock", -3600, 0)):
            with self.subTest(age=name):
                root = samples.state_root_dir(self.tmp, "age-%d" % age)
                record = self.scan("pass", digest=samples.state_digest(name), now=NOW - age, root=root)
                self.assertEqual(mail_state.earlier_drafts(record["sender"], asked, root, NOW), counted)
        record = self.scan("pass", digest=samples.state_digest("moving"), now=NOW)
        self.assertEqual(mail_state.earlier_drafts(record["sender"], asked, self.root, NOW + week), 1)
        self.assertEqual(mail_state.earlier_drafts(record["sender"], asked, self.root, NOW + week + 1), 0)

    def test_the_budget_query_counts_only_mail_that_was_open_to_a_draft(self):
        asked = samples.state_digest("asked")
        expected = 0
        counted = []
        for label, decision in samples.state_decisions().items():
            self.scan(label, digest=samples.state_digest(label))
            if decision["verdict"] != "block" and decision["reply"] == "draft":
                expected += 1
                counted.append(label)
            with self.subTest(after=label):
                self.assertEqual(self.count(asked), expected)
        # review C F4: blocked and held mail never counts; neither does list or automated mail. Fix round 2
        # (B1, review B N1): a message that GOT a draft counts whatever its sender result was.
        self.assertEqual(counted, ["pass", "caution", "dmarc-fail"])

    def test_three_blocked_or_failed_mails_do_not_silence_a_sender(self):
        # review C F4: three forged mails a week held every real mail of the address they forged
        asked = samples.state_digest("the real question")
        for label in ("block", "no-single-from", "several-holds", "held", "budget", "block-budget"):
            for number in range(3):
                self.scan(label, digest=samples.state_digest("%s %d" % (label, number)), now=NOW - 60 - number)
        self.assertEqual(self.count(asked), 0)
        # fix round 2 (B1): three mails with a DMARC failure that were drafted to (a record of the first fix
        # round) DO count: the budget is the only stop for a reply loop with a forged address
        for number in range(3):
            self.scan("dmarc-fail", digest=samples.state_digest("failed %d" % number), now=NOW - 90 - number)
        self.assertEqual(self.count(asked), 3)
        self.assertEqual(self.count(samples.state_digest("an earlier question"), now=NOW - 100), 0)
        for number in range(3):
            self.scan("pass", digest=samples.state_digest("clean %d" % number), now=NOW - 30 - number)
        self.assertEqual(self.count(asked), 6)

    def test_a_held_mail_counts_once_a_person_released_it_and_a_blocked_one_never_does(self):
        asked = samples.state_digest("asked")
        held = self.scan("held", digest=samples.state_digest("held"), now=NOW - 300)
        budget = self.scan("budget", digest=samples.state_digest("budget"), now=NOW - 290)
        blocked = self.scan("block", digest=samples.state_digest("blocked"), now=NOW - 280)
        listed = self.scan("list-budget", digest=samples.state_digest("listed"), now=NOW - 270)
        self.assertEqual(self.count(asked), 0)
        self.override(held, "held")
        self.assertEqual(self.count(asked), 1)
        self.override(budget, "budget")
        self.assertEqual(self.count(asked), 2)
        self.override(blocked, "block")                 # released, and its recorded verdict was a block
        self.assertEqual(self.effect(blocked), ("caution", "draft", ()))
        self.assertEqual(self.count(asked), 2)
        self.override(listed, "budget")                 # list mail with its hold lifted is still no draft
        self.assertEqual(self.count(asked), 2)
        self.override(listed, "list")
        self.assertEqual(self.count(asked), 3)

    def test_the_budget_query_keeps_senders_apart(self):
        asked = samples.state_digest("asked")
        for number in range(3):
            self.scan("pass", digest=samples.state_digest(number))
        self.scan("pass", digest=samples.state_digest("other"), address=samples.STATE_OTHER_ADDRESS)
        self.scan("pass", digest=samples.state_digest("nobody"), address=None)
        self.assertEqual(self.count(asked), 3)
        self.assertEqual(self.count(asked, "ANN@example.ORG"), 3)
        self.assertEqual(self.count(asked, samples.STATE_OTHER_ADDRESS), 1)
        self.assertEqual(self.count(asked, "carol@example.org"), 0)
        self.assertEqual(mail_state.earlier_drafts(None, asked, self.root, NOW), 0)
        other_root = samples.state_root_dir(self.tmp, "other")
        self.assertEqual(mail_state.earlier_drafts(mail_state.sender_hash(samples.STATE_SENDER_ADDRESS, other_root),
                                                   asked, self.root, NOW), 0)

    def test_the_budget_query_passes_over_a_record_it_cannot_read_and_refuses_bad_input(self):
        asked = samples.state_digest("asked")
        records = [self.scan("pass", digest=samples.state_digest(number)) for number in range(3)]
        with open(mail_state.record_path(records[0]["id"], self.root), "wb") as handle:
            handle.write(b"{}")
        self.assertEqual(self.count(asked), 2)
        sender = records[1]["sender"]
        for bad in ("", "abc", None, 7, MARKER):
            self.assert_code("digest-invalid", mail_state.earlier_drafts, sender, bad, self.root, NOW)
        for bad in ("", "ann@example.org", 7, MARKER):
            self.assert_code("sender-invalid", mail_state.earlier_drafts, bad, asked, self.root, NOW)
        self.assert_code("time-invalid", mail_state.earlier_drafts, sender, asked, self.root, "now")

    def test_the_count_is_what_the_rules_hold_the_fourth_mail_on(self):
        self.assertEqual(mail_lists.BUDGET_EARLIER_DRAFTS, 3)
        outcomes = []
        for number in range(5):
            raw = samples.rules_message(body="Question number %d, please.\r\n" % number)
            parsed = mail_parse.parse(raw)
            view = mail_view.build(parsed, CHECKS)
            sender = mail_state.sender_hash(parsed.headers.from_address, self.root)
            digest = mail_state.raw_digest(raw)
            earlier = mail_state.earlier_drafts(sender, digest, self.root, NOW + number)
            decision = mail_rules.decide(parsed, view, CONFIG, earlier)
            record = mail_state.build_record(digest, parsed, view, decision, sender, self.root, NOW + number)
            mail_state.store(record, view.framed, self.root)
            outcomes.append((earlier, decision.reply))
            if number == 2:     # the third mail scanned again still gets its draft
                again = mail_state.earlier_drafts(sender, digest, self.root, NOW + number)
                self.assertEqual((again, mail_rules.decide(parsed, view, CONFIG, again).reply), (2, "draft"))
        # the fourth is held and so gets no draft: it does not count against the fifth
        self.assertEqual(outcomes, [(0, "draft"), (1, "draft"), (2, "draft"), (3, "held"), (3, "held")])


# --------------------------------------------------------------------------------------
# TS-STATE-03: purge and the retention report
# --------------------------------------------------------------------------------------

class Retention(StateCase):
    def kept(self):
        return tuple(sorted(os.listdir(os.path.join(self.root, name))) for name in ("records", "views", "sheets"))

    def test_ts_state_03_purge_removes_aged_files_and_the_report_says_whether_it_runs(self):
        old = self.scan("pass", digest=samples.state_digest("old"), now=NOW - 100 * DAY)
        middle = self.scan("pass", digest=samples.state_digest("middle"), now=NOW - 30 * DAY)
        new = self.scan("pass", digest=samples.state_digest("new"), now=NOW - DAY)
        report = mail_state.retention_report(self.root, NOW)
        self.assertEqual((report.records, report.views, report.sheets), (3, 3, 3))
        self.assertEqual(report.oldest_view_age, 100 * DAY)
        self.assertEqual((report.last_purge, report.running), (None, False))
        self.assertIn("retention: not running", mail_state.retention_lines(report))
        result = mail_state.purge(self.root, NOW)
        self.assertEqual(result, mail_state.PurgeResult(2, 2, 1, 0, "2026-10-13T12:00:00Z"))
        self.assertEqual(self.kept(), ([middle["id"] + ".json", new["id"] + ".json"], [new["id"] + ".txt"],
                                       [new["id"] + ".txt"]))
        with open(os.path.join(self.root, "last-purge"), "rb") as handle:
            self.assertEqual(handle.read(), b"2026-10-13T12:00:00Z\n")
        report = mail_state.retention_report(self.root, NOW + 3600)
        self.assertEqual(report, mail_state.Retention(2, 1, 1, DAY + 3600, "2026-10-13T12:00:00Z", True))
        self.assertEqual(mail_state.retention_lines(report), [
            "records: 2", "views: 1", "sheets: 1", "oldest view: 1 days", "last purge: 2026-10-13T12:00:00Z",
            "retention: running"])
        self.assert_code("record-unknown", mail_state.load_record, old["id"], self.root)
        self.assert_code("view-unknown", mail_state.read_view, middle["id"], self.root)
        self.assertEqual(mail_state.load_record(middle["id"], self.root), middle)
        late = mail_state.retention_report(self.root, NOW + 2 * DAY + 1)
        self.assertFalse(late.running)
        self.assertEqual(mail_state.retention_lines(late)[-1], "retention: not running")

    def test_purge_deletes_a_view_and_a_sheet_older_than_seven_days_and_not_one_of_seven(self):
        limit = mail_lists.PURGE_VIEW_DAYS * DAY
        self.assertEqual(limit, 7 * DAY)
        for name, age, stays in (("a second less", limit - 1, True), ("exactly seven days", limit, True),
                                 ("a second more", limit + 1, False), ("eight days", 8 * DAY, False),
                                 ("new", 0, True), ("ahead of the clock", -DAY, True)):
            with self.subTest(age=name):
                self.root = samples.state_root_dir(self.tmp, "view-%d" % age)
                record = self.scan("pass", now=NOW - age)
                result = mail_state.purge(self.root, NOW)
                expected = [record["id"] + ".txt"] if stays else []
                self.assertEqual(self.kept(), ([record["id"] + ".json"], expected, expected))
                self.assertEqual((result.views, result.sheets, result.records), (0, 0, 0) if stays else (1, 1, 0))

    def test_purge_deletes_a_record_older_than_ninety_days_and_not_one_of_ninety(self):
        limit = mail_lists.PURGE_RECORD_DAYS * DAY
        self.assertEqual(limit, 90 * DAY)
        for name, age, stays in (("a second less", limit - 1, True), ("exactly ninety days", limit, True),
                                 ("a second more", limit + 1, False), ("a year", 365 * DAY, False)):
            with self.subTest(age=name):
                self.root = samples.state_root_dir(self.tmp, "record-%d" % age)
                record = self.scan("pass", now=NOW - age)
                result = mail_state.purge(self.root, NOW)
                self.assertEqual(self.kept(), ([record["id"] + ".json"] if stays else [], [], []))
                self.assertEqual(result.records, 0 if stays else 1)

    def test_purge_leaves_what_it_did_not_name_and_keeps_the_override_log(self):
        record = self.scan("block", now=NOW - 200 * DAY)
        self.override(record, "block", now=NOW - 200 * DAY)
        log = self.log_bytes()
        with open(os.path.join(self.root, "key"), "rb") as handle:
            key = handle.read()
        foreign = [os.path.join(self.root, "views", "notes.txt"), os.path.join(self.root, "records", "old.json"),
                   os.path.join(self.root, "sheets", "20201013T120000Z-0123abcd.txt.bak"),
                   os.path.join(self.root, "views", "20201013T120000Z-0123ABCD.txt"),
                   os.path.join(self.root, "readme")]
        for path in foreign:
            with open(path, "w", encoding="ascii") as handle:
                handle.write("kept")
        fresh = os.path.join(self.root, "records", mail_state.TEMP_PREFIX + "fresh")
        stale = [os.path.join(self.root, "views", mail_state.TEMP_PREFIX + "stale"),
                 os.path.join(self.root, mail_state.TEMP_PREFIX + "stale")]
        for path in [fresh] + stale:
            with open(path, "w", encoding="ascii") as handle:
                handle.write("half a file")
        os.utime(fresh, (NOW - 3600, NOW - 3600))
        for path in stale:
            os.utime(path, (NOW - 2 * DAY, NOW - 2 * DAY))
        result = mail_state.purge(self.root, NOW)
        self.assertEqual((result.views, result.sheets, result.records, result.temporary), (1, 1, 1, 2))
        for path in foreign + [fresh]:
            self.assertTrue(os.path.isfile(path), path)
        for path in stale:
            self.assertFalse(os.path.exists(path), path)
        self.assertEqual(self.log_bytes(), log)
        with open(os.path.join(self.root, "key"), "rb") as handle:
            self.assertEqual(handle.read(), key)
        report = mail_state.retention_report(self.root, NOW)
        self.assertEqual((report.records, report.views, report.sheets, report.oldest_view_age), (0, 0, 0, None))
        self.assertIn("oldest view: none", mail_state.retention_lines(report))

    def test_purge_on_a_new_root_makes_it_and_writes_the_stamp(self):
        self.assertFalse(os.path.exists(self.root))
        result = mail_state.purge(self.root, NOW)
        self.assertEqual(result, mail_state.PurgeResult(0, 0, 0, 0, "2026-10-13T12:00:00Z"))
        self.assertEqual(sorted(os.listdir(self.root)), ["last-purge", "lock", "records", "sheets", "views"])
        self.assertEqual(mode_of(os.path.join(self.root, "last-purge")), 0o600)
        self.assertTrue(mail_state.retention_report(self.root, NOW).running)
        self.assert_code("time-invalid", mail_state.purge, self.root, "now")
        self.assertLess(abs(mail_state.id_time(mail_state.purge(self.root).time.replace("-", "").replace(":", "")
                                               + "-00000000") - time.time()), 5)

    def test_the_report_says_not_running_for_a_stale_an_absent_and_an_unreadable_stamp(self):
        stale = mail_lists.RETENTION_STALE_DAYS * DAY
        self.assertEqual(stale, 2 * DAY)
        mail_state.purge(self.root, NOW)
        for name, later, running in (("at once", 0, True), ("a day", DAY, True), ("exactly two days", stale, True),
                                     ("two days and a second", stale + 1, False), ("a month", 30 * DAY, False),
                                     ("a clock set back", -1, False)):
            with self.subTest(after=name):
                report = mail_state.retention_report(self.root, NOW + later)
                self.assertEqual(report.running, running)
                self.assertEqual(report.last_purge, "2026-10-13T12:00:00Z")
                self.assertEqual(mail_state.retention_lines(report)[-1],
                                 "retention: running" if running else "retention: not running")
        stamp = os.path.join(self.root, "last-purge")
        for name, data in (("empty", b""), ("words", b"yesterday\n"), ("no newline", b"2026-10-13T12:00:00Z"),
                           ("two lines", b"2026-10-13T12:00:00Z\n2026-10-13T12:00:00Z\n"),
                           ("no such day", b"2026-13-45T12:00:00Z\n"), ("not ascii", b"2026-10-13T12:00:00Z\xff\n"),
                           ("long", b"2" * 5000), ("marker", MARKER.encode("ascii") + b"\n")):
            with self.subTest(stamp=name):
                with open(stamp, "wb") as handle:
                    handle.write(data)
                report = mail_state.retention_report(self.root, NOW)
                self.assertEqual((report.last_purge, report.running), (None, False))
                lines = mail_state.retention_lines(report)
                self.assertEqual(lines[-2:], ["last purge: never", "retention: not running"])
                self.assertNotIn(MARKER, " ".join(lines))
        os.unlink(stamp)
        self.assertFalse(mail_state.retention_report(self.root, NOW).running)
        self.assertEqual(mail_state.RETENTION_NOT_RUNNING, "retention: not running")

    def test_the_report_counts_files_named_by_a_record_id_and_gives_the_oldest_view(self):
        for number, age in enumerate((5 * DAY, 2 * DAY + 7, 60)):
            self.scan("pass", digest=samples.state_digest(number), now=NOW - age)
        self.scan("pass", digest=samples.state_digest("no view"), now=NOW - 6 * DAY, with_view=False)
        with open(os.path.join(self.root, "views", "notes.txt"), "w", encoding="ascii") as handle:
            handle.write("x")
        report = mail_state.retention_report(self.root, NOW)
        self.assertEqual((report.records, report.views, report.sheets, report.oldest_view_age), (4, 3, 4, 5 * DAY))
        self.assertEqual(mail_state.retention_lines(report)[:4],
                         ["records: 4", "views: 3", "sheets: 4", "oldest view: 5 days"])
        self.assertEqual(mail_state.retention_report(self.root, NOW - 10 * DAY).oldest_view_age, 0)


# --------------------------------------------------------------------------------------
# The module itself
# --------------------------------------------------------------------------------------

class Module(unittest.TestCase):
    ALLOWED = {"__future__", "calendar", "contextlib", "fcntl", "getpass", "hashlib", "hmac", "json", "msvcrt", "os",
               "platform", "pwd", "re", "secrets", "stat", "sys", "time", "typing", "mail_lists", "mail_reuse"}
    FORBIDDEN = {"smtplib", "imaplib", "poplib", "ftplib", "socket", "ssl", "http", "asyncio", "subprocess",
                 "multiprocessing", "ctypes", "urllib", "shutil", "tempfile", "pickle", "mail_parse", "mail_view",
                 "mail_frame", "mail_rules", "mail_sender"}

    def tree(self):
        return ast.parse((SCRIPTS / "mail_state.py").read_text(encoding="utf-8"))

    def test_the_state_imports_only_the_standard_library_and_its_one_callee(self):
        imported = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported - self.ALLOWED, set())
        self.assertEqual(imported & self.FORBIDDEN, set())
        self.assertTrue({"mail_lists", "mail_reuse"} <= imported)
        for name in imported - {"mail_lists", "mail_reuse", "fcntl", "msvcrt", "pwd"}:
            self.assertIn(name, sys.stdlib_module_names)

    def test_a_module_of_one_platform_is_imported_only_behind_a_guard(self):
        tree = self.tree()
        top_level = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level |= {alias.name for alias in node.names}
        self.assertEqual(top_level & {"fcntl", "msvcrt", "pwd", "grp", "termios", "resource"}, set())

    def test_the_state_starts_no_process_and_calls_nothing_dangerous(self):
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = node.func.attr
                self.assertFalse(name in ("system", "popen", "fork") or name.startswith(("exec", "spawn")), name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ("eval", "exec", "compile", "__import__"))

    def test_importing_the_state_has_no_side_effects(self):
        home = tempfile.mkdtemp(prefix="mailscan-import-")
        self.addCleanup(shutil.rmtree, home, True)
        code = ("import os, sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "import mail_state\n"
                "print(mail_state.state_root())\n"
                "print(sorted(os.listdir(os.environ['HOME'])))\n")
        environment = {name: value for name, value in os.environ.items() if name != mail_state.ENV_ROOT}
        environment.update(HOME=home, USERPROFILE=home, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], capture_output=True, text=True, env=environment,
                              timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(done.stdout.splitlines(), [os.path.join(home, ".foundry", "mail-scan"), "[]"])
        self.assertEqual(os.listdir(home), [])

    def test_the_sources_are_ascii_with_escapes_for_the_rest(self):
        for path in (SCRIPTS / "mail_state.py", HERE / "test_mail_state.py", HERE / "samples.py", SCHEMA_FILE):
            self.assertTrue(path.read_bytes().isascii(), path.name)
            self.assertNotIn(b"\r", path.read_bytes(), path.name)

    def test_the_manifest_lists_the_builders_of_this_component(self):
        manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, samples.manifest())
        names = manifest["builders"]["mail-state"]
        self.assertEqual(tuple(names), samples.BUILDERS["mail-state"])
        for name in names:
            self.assertTrue(callable(getattr(samples, name)), name)
        self.assertEqual(manifest["stored_sample_files"], [])

    def test_no_test_reached_a_default_root(self):
        home = os.environ["HOME"]
        self.assertEqual(home, _FAKE_HOME[0])
        self.assertEqual(os.listdir(home), [])
        self.assertFalse(os.path.exists(mail_state.state_root()))


if __name__ == "__main__":
    unittest.main()
