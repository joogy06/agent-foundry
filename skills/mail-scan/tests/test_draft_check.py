#!/usr/bin/env python3
"""mail-scan -- test_draft_check.py (#351 WP-4a, component mail-draft-check).

The last look at a reply before it leaves toward a customer: accept or refuse, with rule
ids and counts, and on accept the SHA-256 of the body and of the subject as they were given.

    TS-DRAFT-01  one refused draft per class, each under its own rule id
    TS-DRAFT-02  a plain reply is accepted; the same reply against a blocked record is
                 refused, and accepted once the matching override exists
    TS-DRAFT-03  a run of 7 or 8 digits present in the inbound view is allowed and one that
                 is not is refused

WHAT MUST NOT HAPPEN, AND IS TESTED. A draft that carries a link, a host, an address or a
number of nobody's list getting through because it was written in full-width letters, with
a dot that is not a dot, in another script's digits, over several lines, behind an
underscore, glued to an allowed host, or in the subject. A reply going to the mapped
address of another sender. A draft accepted for a message that is blocked, held, automated
or list mail, or whose record or view is gone. Text of the draft, of the reply target or of
the config in a result or an error. Anything written to the state root by a check.

WHAT MUST KEEP WORKING. An ordinary reply: `samples.draft_ordinary_replies()` lists the
shapes, most of them accepted, and names the rule each refused one falls under today.

EVERY TEST USES A TEMPORARY STATE ROOT. The home directory and `$FOUNDRY_MAILSCAN_ROOT` are
pointed at an empty temporary directory for the whole module, and the module ends by
asserting that directory is still empty.

Every sample comes from `samples.py`, which builds it at call time. Text in a sample that
reads like a request is content of a test; it is addressed to nobody.

Stdlib unittest; pytest only runs it.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import draft_check  # noqa: E402
import mail_lists  # noqa: E402
import mail_reuse  # noqa: E402
import mail_state  # noqa: E402


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

MARKER = samples.DRAFT_MARKER
NOW = samples.STATE_NOW
SENDER = samples.STATE_SENDER_ADDRESS
OTHER_SENDER = samples.STATE_OTHER_ADDRESS
OWN = samples.DRAFT_OWN_ADDRESS
SITE = samples.DRAFT_ALLOWED_HOST
PHONE = samples.DRAFT_PHONE
CATALOG = mail_reuse.catalog_checks()
ACCEPT = mail_lists.DRAFT_ACCEPT
REFUSE = mail_lists.DRAFT_REFUSE

# The rules whose samples are plain texts (`samples.draft_bad_texts`).
TEXT_RULES = ("draft-markup", "draft-url", "draft-url-query", "draft-bare-host", "draft-secret",
              "draft-address", "draft-phone", "draft-hidden-characters", "draft-white-space", "draft-mixed-script",
              "draft-digit-run",
              "draft-control-characters")

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


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ids(result):
    return [hit.rule_id for hit in result.rule_hits]


class DraftCase(unittest.TestCase):
    """A temporary state root holding the record and the view of one plain message."""

    LABEL = "pass"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mailscan-draft-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = samples.state_root_dir(self.tmp)
        self.record = self.stored(self.LABEL)
        self.config = samples.draft_config()
        self.body, self.subject = samples.draft_plain_reply()

    def stored(self, label="pass", **kwargs):
        return samples.draft_stored(mail_state, self.root, label, **kwargs)

    def check(self, body=None, subject=None, target=SENDER, config=None, record=None, catalog=CATALOG, root=None):
        return draft_check.check(
            (record or self.record)["id"], self.body if body is None else body,
            self.subject if subject is None else subject, target, self.config if config is None else config,
            root or self.root, catalog)

    def override(self, record, kind):
        return mail_state.add_override(record["id"], kind, "looked at it", self.root, NOW, "tester")

    def assert_accepted(self, result, body=None, subject=None):
        self.assertEqual((result.result, result.rule_hits), (ACCEPT, ()))
        self.assertTrue(result.accepted())
        self.assertEqual(result.body_sha256, sha(self.body if body is None else body))
        self.assertEqual(result.subject_sha256, sha(self.subject if subject is None else subject))

    def assert_refused(self, result, *rule_ids):
        """Refused under exactly `rule_ids`, with no digest and hits of the right form."""
        self.assertEqual(result.result, REFUSE)
        self.assertFalse(result.accepted())
        self.assertEqual(ids(result), [rule for rule in mail_lists.REFUSE_RULE_IDS if rule in rule_ids],
                         "wanted %r" % (rule_ids,))
        self.assertEqual(sorted(ids(result)), sorted(rule_ids))
        self.assertEqual((result.body_sha256, result.subject_sha256), (None, None))
        for hit in result.rule_hits:
            self.assertEqual(hit.rule_class, mail_lists.CLASS_REFUSE)
            self.assertIs(type(hit.count), int)
            self.assertGreaterEqual(hit.count, 1)

    def assert_text_rule(self, rule_id):
        """Every sample text of `rule_id` is refused under it alone, as a body and as a subject."""
        texts = samples.draft_bad_texts()[rule_id]
        self.assertGreaterEqual(len(texts), 2)
        for text in texts:
            with self.subTest(where="body", text=ascii(text)):
                self.assert_refused(self.check(body=text), rule_id)
            with self.subTest(where="subject", text=ascii(text)):
                self.assert_refused(self.check(subject=text), rule_id)


# --------------------------------------------------------------------------------------
# TS-DRAFT-02: a plain reply
# --------------------------------------------------------------------------------------

class PlainReply(DraftCase):
    def test_ts_draft_02_a_plain_reply_is_accepted_with_the_digests_of_what_was_given(self):
        # it holds an approved phone number, our own address, an allowed host and a number of the customer
        for piece in (PHONE, OWN, SITE, samples.DRAFT_VIEW_ORDER):
            self.assertIn(piece, self.body)
        before = tree_of(self.root)
        result = self.check()
        self.assert_accepted(result)
        self.assertEqual(result.body_sha256, hashlib.sha256(self.body.encode("utf-8")).hexdigest())
        self.assertRegex(result.body_sha256, r"^[0-9a-f]{64}$")
        self.assertNotEqual(result.body_sha256, result.subject_sha256)
        self.assertEqual(tree_of(self.root), before)

    def test_the_digests_are_of_the_text_as_given_not_of_a_folded_form(self):
        # (fix round 3, D1: one line break may end a text, so the second form ends with none)
        cases = [self.body.replace("\r\n", "\n"), self.body.rstrip("\r\n"), "PS. " + self.body,
                 "Caf%s na%sve %s ok" % (chr(0xE9), "i" + chr(0x0308), chr(0x2026)),
                 "A no-break space%s! and a wide %s letter" % (chr(0xA0), chr(0xFF21)), ""]
        seen = set()
        for body in cases:
            with self.subTest(body=ascii(body)):
                result = self.check(body=body)
                self.assert_accepted(result, body=body)
                seen.add(result.body_sha256)
        self.assertEqual(len(seen), len(cases))
        # a folded form that differs from the text is never what is hashed
        wide = cases[4]
        self.assertNotEqual(unicodedata.normalize("NFKC", wide), wide)
        self.assertNotEqual(self.check(body=wide).body_sha256, sha(unicodedata.normalize("NFKC", wide)))

    def test_an_empty_subject_and_an_empty_body_are_accepted(self):
        self.assert_accepted(self.check(body="", subject=""), body="", subject="")

    def test_ts_draft_02_the_same_reply_against_a_blocked_record_is_refused_until_the_override(self):
        blocked = self.stored("block")
        self.assert_refused(self.check(record=blocked), "draft-record-blocked", "draft-reply-not-allowed")
        self.override(blocked, "block")
        self.assert_accepted(self.check(record=blocked))
        # the override is for that message only
        other = self.stored("block", digest=samples.state_digest("another blocked message"))
        self.assert_refused(self.check(record=other), "draft-record-blocked", "draft-reply-not-allowed")

    def test_ordinary_replies_are_accepted_or_refused_as_the_table_says(self):
        table = samples.draft_ordinary_replies()
        self.assertGreaterEqual(len(table), 50)
        accepted = 0
        for label, (text, expected) in table.items():
            with self.subTest(label=label):
                result = self.check(body=text)
                if expected == ACCEPT:
                    accepted += 1
                    self.assert_accepted(result, body=text)
                else:
                    self.assertIn(expected, mail_lists.REFUSE_RULE_IDS)
                    self.assert_refused(result, expected)
        self.assertGreaterEqual(accepted, 55)
        # the whole of what is refused: unlisted numbers of 9 to 15 digits, a mailto link, two shapes
        # of markup, a typo that ends in a country code, a joiner that joins nothing
        self.assertEqual(tuple(label for label, (_text, expected) in table.items() if expected != ACCEPT),
                         samples.DRAFT_ORDINARY_REFUSED)

    def test_the_ordinary_shapes_the_lead_named_are_accepted(self):
        table = samples.draft_ordinary_replies()
        for label in ("the order number of the customer", "a date in words", "a date with slashes", "a price",
                      "a time", "a postcode", "abbreviations with dots", "a number that ends a paragraph",
                      "an ISO date nobody wrote before", "a dotted date nobody wrote before",
                      "a time range with dots", "a nine digit order number of the customer",
                      "our phone with a trunk zero in brackets", "a price range without a currency sign",
                      "a file name", "no space after a full stop", "a title with no space",
                      "a product name with a dot", "our own domain without the listed host name",
                      "an at sign that is not an address", "an emoji joined with a zero-width joiner",
                      "a flag of a nation of the United Kingdom"):
            self.assertEqual(table[label][1], ACCEPT, label)


# --------------------------------------------------------------------------------------
# TS-DRAFT-01: one test per refusal class
# --------------------------------------------------------------------------------------

class RefusalClasses(DraftCase):
    def test_ts_draft_01_markup(self):
        self.assert_text_rule("draft-markup")

    def test_ts_draft_01_url(self):
        self.assert_text_rule("draft-url")

    def test_ts_draft_01_url_query(self):
        self.assert_text_rule("draft-url-query")

    def test_ts_draft_01_bare_host(self):
        self.assert_text_rule("draft-bare-host")

    def test_ts_draft_01_secret(self):
        self.assert_text_rule("draft-secret")

    def test_ts_draft_01_address(self):
        self.assert_text_rule("draft-address")

    def test_ts_draft_01_phone(self):
        self.assert_text_rule("draft-phone")

    def test_ts_draft_01_hidden_characters(self):
        self.assert_text_rule("draft-hidden-characters")
        for char in (samples.tag_edges()["inside"] + samples.bidi_edges()["inside"]
                     + samples.format_examples()["inside"]):
            with self.subTest(char=ascii(char)):
                self.assert_refused(self.check(body="pl" + char + "ain"), "draft-hidden-characters")

    def test_ts_draft_01_white_space(self):
        # fix round 3 (D4): white space has an id of its own
        self.assert_text_rule("draft-white-space")

    def test_ts_draft_01_mixed_script(self):
        # fix round 3 (D4): so has a word of two scripts
        self.assert_text_rule("draft-mixed-script")

    def test_ts_draft_01_body_too_long(self):
        cap = mail_lists.DRAFT_BODY_MAX_CHARS
        self.assertEqual(cap, 8000)
        at_cap = "word " * (cap // 5 - 1) + "words"
        self.assertEqual(len(at_cap), cap)
        self.assert_accepted(self.check(body=at_cap), body=at_cap)
        self.assert_refused(self.check(body=at_cap + "x"), "draft-body-too-long")
        self.assert_refused(self.check(body="x" * 1_000_000), "draft-body-too-long")
        # a body within the cap as given and over it after NFKC
        grows = chr(0xFDFA) * 500
        self.assertLessEqual(len(grows), cap)
        self.assertGreater(len(unicodedata.normalize("NFKC", grows)), cap)
        self.assert_refused(self.check(body=grows), "draft-body-too-long")
        # the subject cap is not the body cap
        self.assertEqual(self.check(body=at_cap + "x").rule_hits[0].count, 1)

    def test_ts_draft_01_subject_too_long(self):
        cap = mail_lists.DRAFT_SUBJECT_MAX_CHARS
        self.assertEqual(cap, 200)
        at_cap = "word " * (cap // 5 - 1) + "words"
        self.assert_accepted(self.check(subject=at_cap), subject=at_cap)
        self.assert_refused(self.check(subject=at_cap + "x"), "draft-subject-too-long")
        self.assert_refused(self.check(subject=chr(0xFDFA) * 20), "draft-subject-too-long")

    def test_ts_draft_01_digit_run(self):
        self.assert_text_rule("draft-digit-run")

    def test_ts_draft_01_canary(self):
        canary = samples.draft_canary()
        config = samples.draft_config(canary=canary)
        self.assert_accepted(self.check(config=config))
        self.assert_refused(self.check(body="The word is %s." % canary, config=config), "draft-canary")
        self.assert_refused(self.check(subject="Re: %s" % canary, config=config), "draft-canary")

    def test_ts_draft_01_record_missing(self):
        unknown = dict(self.record, id="20261013T120000Z-0123abcd")
        self.assert_refused(self.check(record=unknown), "draft-record-missing")

    def test_ts_draft_01_view_missing(self):
        no_view = self.stored("pass", with_view=False, digest=samples.state_digest("no view"))
        self.assert_refused(self.check(record=no_view), "draft-view-missing")

    def test_ts_draft_01_record_blocked(self):
        # the block is lifted and another hold is not: only the block rule is quiet
        both = self.stored("block-budget")
        self.override(both, "budget")
        self.assert_refused(self.check(record=both), "draft-record-blocked", "draft-reply-not-allowed")
        result = self.check(record=self.stored("block"))
        self.assertIn("draft-record-blocked", ids(result))
        # blocked, and the reply would be a draft: automated mail under a block keeps both refusals,
        # a caution or a pass never raises this one
        for label in ("pass", "caution"):
            self.assertNotIn("draft-record-blocked", ids(self.check(record=self.stored(
                label, digest=samples.state_digest("unblocked %s" % label)))))

    def test_the_newest_record_of_the_message_decides(self):
        # fix round 2 (B3, review B N5): a later scan of the same bytes that blocks refuses a draft
        # checked against the OLDER record id
        digest = samples.state_digest("scanned twice")
        older = self.stored("pass", digest=digest, now=NOW - 600)
        self.assert_accepted(self.check(record=older))
        newer = self.stored("block", digest=digest, now=NOW - 300)
        self.assert_refused(self.check(record=newer), "draft-record-blocked", "draft-reply-not-allowed")
        self.assert_refused(self.check(record=older), "draft-record-blocked", "draft-reply-not-allowed")
        # a record of another message changes nothing, and a still newer clean scan is the one that counts
        self.stored("block", digest=samples.state_digest("another message"), now=NOW - 200)
        self.assert_accepted(self.check())
        self.stored("pass", digest=digest, now=NOW - 100)
        self.assert_accepted(self.check(record=older))
        self.assert_accepted(self.check(record=newer))

    def test_ts_draft_01_reply_not_allowed(self):
        held = self.stored("held")
        self.assert_refused(self.check(record=held), "draft-reply-not-allowed")

    def test_ts_draft_01_reply_target(self):
        self.assert_refused(self.check(target=OTHER_SENDER), "draft-reply-target")

    def test_ts_draft_01_control_characters(self):
        self.assert_text_rule("draft-control-characters")
        # in a subject, a line break of any kind
        for char in ("\n", "\r", "\r\n", chr(0x0B), chr(0x0C), chr(0x85), chr(0x2028), chr(0x2029)):
            with self.subTest(char=ascii(char)):
                self.assert_refused(self.check(subject="Re: Hello%sBcc: someone" % char), "draft-control-characters")
        # in a body, LF or CRLF is ordinary; a lone CR and the two separators are not
        for body in ("one\ntwo\nthree", "one\r\ntwo\r\nthree"):
            self.assert_accepted(self.check(body=body), body=body)
        for char in ("\r", chr(0x2028), chr(0x2029), chr(0x85), chr(0x7F)):
            with self.subTest(body=ascii(char)):
                self.assert_refused(self.check(body="one%stwo" % char), "draft-control-characters")
        # a tab is no control character, but it is white space nobody tells from a space (fix round 2, C1)
        self.assert_refused(self.check(subject="Re:\tHello"), "draft-white-space")

    def test_ts_draft_01_catalog_missing(self):
        missing = mail_reuse.catalog_checks(samples.missing_catalog_path(self.tmp))
        self.assertEqual(missing.gap, mail_reuse.GAP_CATALOG_MISSING)
        self.assert_refused(self.check(catalog=missing), "draft-catalog-missing")

    def test_ts_draft_01_knowledge_pack(self):
        config = samples.draft_config(knowledge_pack=os.path.join(self.tmp, "no-such-pack.txt"))
        self.assert_refused(self.check(config=config), "draft-knowledge-pack")

    def test_every_refusal_class_has_its_one_test(self):
        tested = {name[len("test_ts_draft_01_"):].replace("_", "-") for name in dir(self)
                  if name.startswith("test_ts_draft_01_")}
        self.assertEqual({"draft-" + name for name in tested}, set(mail_lists.REFUSE_RULE_IDS))
        self.assertEqual(set(TEXT_RULES), set(samples.draft_bad_texts()))
        self.assertEqual(len(mail_lists.REFUSE_RULE_IDS), 22)


# --------------------------------------------------------------------------------------
# The record, the view and the effective verdict
# --------------------------------------------------------------------------------------

class RecordAndView(DraftCase):
    def test_a_record_that_is_unknown_invalid_or_unreadable_ends_the_check(self):
        bad_body = "see %s.example.net and call %s" % (MARKER.lower(), samples.DRAFT_OTHER_PHONE)
        for record_id in ("20261013T120000Z-0123abcd", "", "../../etc/passwd", self.record["id"] + "x", None, 7,
                          MARKER, self.record["id"].upper()):
            with self.subTest(record_id=ascii(record_id)):
                # nothing else is judged: there is nothing to judge it against
                self.assert_refused(draft_check.check(record_id, bad_body, self.subject, SENDER, self.config,
                                                      self.root, CATALOG), "draft-record-missing")

    def test_an_edited_record_is_missing(self):
        blocked = self.stored("block")
        path = mail_state.record_path(blocked["id"], self.root)
        with open(path, "r", encoding="ascii") as handle:
            text = handle.read()
        edited = text.replace('"verdict": "block"', '"verdict": "pass"').replace(
            '"reply": "held"', '"reply": "draft"').replace('"block"\n  ]', '"block"\n  ]')
        self.assertNotEqual(edited, text)
        with open(path, "w", encoding="ascii") as handle:
            handle.write(edited)
        self.assert_refused(self.check(record=blocked), "draft-record-missing")

    def test_a_record_of_another_root_and_a_root_without_its_key_are_missing(self):
        other_root = samples.state_root_dir(self.tmp, "other")
        elsewhere = samples.draft_stored(mail_state, other_root)
        self.assert_refused(self.check(record=elsewhere), "draft-record-missing")
        shutil.copy(mail_state.record_path(elsewhere["id"], other_root), mail_state.record_path(elsewhere["id"], self.root))
        self.assert_refused(self.check(record=elsewhere), "draft-record-missing")
        os.remove(os.path.join(self.root, mail_state.FILE_KEY))
        before = tree_of(self.root)
        self.assert_refused(self.check(), "draft-record-missing")
        self.assertEqual(tree_of(self.root), before)        # and no new key was made

    def test_a_root_that_does_not_exist_is_not_created(self):
        nowhere = samples.state_root_dir(self.tmp, "nowhere")
        self.assert_refused(self.check(root=nowhere), "draft-record-missing")
        self.assertFalse(os.path.lexists(nowhere))
        for root in (7, "", b"bytes" + bytes([0]), "a" + chr(0) + "b"):
            with self.subTest(root=ascii(root)):
                self.assert_refused(draft_check.check(self.record["id"], self.body, self.subject, SENDER,
                                                      self.config, root, CATALOG), "draft-record-missing")

    def test_a_view_that_is_purged_or_not_a_frame_is_missing(self):
        path = mail_state.view_path(self.record["id"], self.root)
        self.assert_accepted(self.check())
        with open(path, "rb") as handle:
            good = handle.read()
        for label, data in samples.not_frames().items():
            with self.subTest(label=label):
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(data)
                self.assert_refused(self.check(), "draft-view-missing")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe not text")
        self.assert_refused(self.check(), "draft-view-missing")
        with open(path, "wb") as handle:
            handle.write(good)
        self.assert_accepted(self.check())
        mail_state.purge(self.root, NOW + 8 * samples.DAY)          # views go after seven days
        self.assertFalse(os.path.exists(path))
        self.assert_refused(self.check(), "draft-view-missing")

    def test_with_no_view_the_other_checks_still_run(self):
        no_view = self.stored("pass", with_view=False, digest=samples.state_digest("no view"))
        result = self.check(record=no_view, body="see %s.example.net, call %s, ref 7777777" % (
            MARKER.lower(), samples.DRAFT_OTHER_PHONE))
        # the digit-run rule has nothing to look in and stays quiet; the missing view is the refusal
        self.assert_refused(result, "draft-view-missing", "draft-bare-host", "draft-phone")

    def test_every_decision_is_refused_or_accepted_by_its_effective_reply(self):
        expected = {
            "pass": (), "caution": (),
            "block": ("draft-record-blocked", "draft-reply-not-allowed"),
            "budget": ("draft-reply-not-allowed",),
            "held": ("draft-reply-not-allowed",),
            "block-budget": ("draft-record-blocked", "draft-reply-not-allowed"),
            "several-holds": ("draft-record-blocked", "draft-reply-not-allowed"),
            "none-automated": ("draft-reply-not-allowed",),
            "none-automated-block": ("draft-record-blocked", "draft-reply-not-allowed"),
            "none-list": ("draft-reply-not-allowed",),
            "list-budget": ("draft-reply-not-allowed",),
            "list-block": ("draft-record-blocked", "draft-reply-not-allowed"),
            "scanner-error": ("draft-record-blocked", "draft-reply-not-allowed"),
            "dmarc-fail": (),
            "no-single-from": ("draft-record-blocked", "draft-reply-not-allowed"),
        }
        self.assertEqual(set(expected), set(samples.state_decisions()))
        for label, rules in expected.items():
            with self.subTest(label=label):
                record = self.stored(label, digest=samples.state_digest("decision %s" % label))
                result = self.check(record=record)
                if rules:
                    self.assert_refused(result, *rules)
                else:
                    self.assert_accepted(result)

    def test_each_override_kind_opens_the_draft_only_when_it_is_the_last_hold(self):
        # label -> the kinds a person gives, in order, with what the check says after each
        steps = {
            "block": [("block", ())],
            "budget": [("budget", ())],
            "held": [("held", ())],
            "none-list": [("list", ())],
            "block-budget": [("block", ("draft-reply-not-allowed",)), ("budget", ())],
            "several-holds": [("budget", ("draft-record-blocked", "draft-reply-not-allowed")),
                              ("block", ("draft-reply-not-allowed",)), ("held", ())],
            "list-budget": [("list", ("draft-reply-not-allowed",)), ("budget", ())],
            "list-block": [("block", ("draft-reply-not-allowed",)), ("list", ())],
            "no-single-from": [("block", ())],
        }
        for label, kinds in steps.items():
            address = None if label == "no-single-from" else SENDER
            record = self.stored(label, digest=samples.state_digest("override %s" % label), address=address)
            for kind, rules in kinds:
                with self.subTest(label=label, kind=kind):
                    self.override(record, kind)
                    result = self.check(record=record)
                    if label == "no-single-from":
                        # the block is lifted, and there is still nobody to reply to
                        self.assert_refused(result, "draft-reply-target")
                    elif rules:
                        self.assert_refused(result, *rules)
                    else:
                        self.assert_accepted(result)

    def test_automated_mail_and_an_unjudged_message_never_get_a_draft(self):
        for label in ("none-automated", "none-automated-block"):
            record = self.stored(label, digest=samples.state_digest("automated %s" % label))
            for kind in mail_lists.OVERRIDE_KINDS:
                with self.assertRaises(mail_state.StateError):
                    self.override(record, kind)
            self.assertIn("draft-reply-not-allowed", ids(self.check(record=record)))
        error = self.stored("scanner-error", with_view=False)
        # nobody read the message: no override is taken for it (fix round 1), it stays blocked and held
        with self.assertRaises(mail_state.StateError) as caught:
            self.override(error, "block")
        self.assertEqual(caught.exception.code, "override-not-judged")
        self.assert_refused(self.check(record=error), "draft-view-missing", "draft-record-blocked",
                            "draft-reply-not-allowed")

    def test_a_typed_override_line_opens_nothing(self):
        blocked = self.stored("block")
        line = json.dumps({"kind": "block", "record": blocked["id"], "sha256": blocked["sha256"],
                           "time": mail_state.time_text(NOW), "reason_length": 3, "reason_sha256": "0" * 64,
                           "user": "tester", "seal": "0" * 64, "schema": mail_state.OVERRIDE_SCHEMA_ID},
                          sort_keys=True)
        with open(os.path.join(self.root, mail_state.FILE_OVERRIDES), "a", encoding="ascii") as handle:
            handle.write(line + "\n")
        self.assert_refused(self.check(record=blocked), "draft-record-blocked", "draft-reply-not-allowed")

    def test_a_check_writes_nothing(self):
        blocked = self.stored("block")
        self.override(blocked, "block")
        pack = samples.draft_knowledge_pack(self.tmp)
        config = samples.draft_config(knowledge_pack=pack, canary=samples.draft_canary())
        before = tree_of(self.tmp)
        self.assert_accepted(self.check(config=config))
        self.assert_accepted(self.check(record=blocked, config=config))
        self.assertEqual(self.check(body="see %s.example.net" % MARKER.lower(), target=OTHER_SENDER,
                                    config=config).result, REFUSE)
        after = tree_of(self.tmp)
        # the lock file of the root may be made by reading the override log; nothing else
        after.pop(os.path.join("state", mail_state.FILE_LOCK), None)
        before.pop(os.path.join("state", mail_state.FILE_LOCK), None)
        self.assertEqual(after, before)


# --------------------------------------------------------------------------------------
# The reply target
# --------------------------------------------------------------------------------------

class ReplyTarget(DraftCase):
    MAPPED = samples.DRAFT_MAPPED_ADDRESS
    OTHER_MAPPED = samples.DRAFT_OTHER_MAPPED_ADDRESS

    def mapped_config(self):
        return samples.draft_config(reply_to_map={SENDER: self.MAPPED, OTHER_SENDER: self.OTHER_MAPPED})

    def test_the_sender_of_the_record_is_accepted_in_any_letter_case(self):
        for target in (SENDER, SENDER.upper(), SENDER.title()):
            with self.subTest(target=target):
                self.assert_accepted(self.check(target=target))

    def test_a_target_with_white_space_around_it_or_a_line_break_in_it_is_refused(self):
        # review C F6: a gate that writes the accepted string into a To header ends its header block early
        for target in ("  %s  " % SENDER, " " + SENDER, SENDER + " ", SENDER + "\r\n", SENDER + "\n", "\t" + SENDER,
                       SENDER + "\r\nBcc: other@example.net", SENDER.replace("@", "@\n"), SENDER + chr(0x85),
                       SENDER + chr(0xA0), SENDER.replace("@", " @")):
            with self.subTest(target=ascii(target)):
                self.assert_refused(self.check(target=target), "draft-reply-target")

    def test_the_mapped_address_of_the_sender_is_accepted(self):
        config = self.mapped_config()
        self.assert_accepted(self.check(target=self.MAPPED, config=config))
        self.assert_accepted(self.check(target=self.MAPPED.upper(), config=config))
        # the key of the map is matched as the sender is: by its hash, in any letter case
        upper = samples.draft_config(reply_to_map={SENDER.upper(): self.MAPPED})
        self.assert_accepted(self.check(target=self.MAPPED, config=upper))
        # the From address itself still hashes to the sender
        self.assert_accepted(self.check(target=SENDER, config=config))

    def test_the_mapped_address_of_another_sender_is_refused(self):
        config = self.mapped_config()
        self.assert_refused(self.check(target=self.OTHER_MAPPED, config=config), "draft-reply-target")
        # and the mapped address of this sender is refused for a message of the other one
        other = self.stored("pass", address=OTHER_SENDER, digest=samples.state_digest("from the other sender"))
        self.assert_refused(self.check(record=other, target=self.MAPPED, config=config), "draft-reply-target")
        self.assert_accepted(self.check(record=other, target=self.OTHER_MAPPED, config=config))
        self.assert_accepted(self.check(record=other, target=OTHER_SENDER, config=config))

    def test_a_mapped_address_without_its_entry_is_refused(self):
        self.assert_refused(self.check(target=self.MAPPED), "draft-reply-target")

    def test_any_other_target_is_refused(self):
        for target in (OTHER_SENDER, OWN, "", "   ", None, 7, b"ann@example.org", [SENDER], SENDER + ".evil.example",
                       "x" + SENDER, SENDER + "\nBcc: %s" % OTHER_SENDER, "%s, %s" % (SENDER, OTHER_SENDER),
                       "<%s>" % SENDER, "Ann <%s>" % SENDER, samples.full_width(SENDER),
                       SENDER.replace("a", chr(0x0430), 1), SENDER + chr(0x200B), chr(0xD800)):
            with self.subTest(target=ascii(target)):
                self.assert_refused(self.check(target=target), "draft-reply-target")

    def test_a_target_that_only_lower_cases_to_the_sender_is_refused(self):
        """The Kelvin sign lower-cases to the letter k: such a target would hash as the sender does."""
        address = "mark@example.org"
        record = self.stored("pass", address=address, digest=samples.state_digest("from mark"))
        self.assert_accepted(self.check(record=record, target=address))
        kelvin = address.replace("k", chr(0x212A))
        self.assertEqual(kelvin.lower(), address)
        self.assertEqual(mail_state.sender_hash(kelvin, self.root), record["sender"])
        self.assert_refused(self.check(record=record, target=kelvin), "draft-reply-target")
        mapped = samples.draft_config(reply_to_map={address: "mark.reply@example.org"})
        self.assert_refused(self.check(record=record, target="mar%s.reply@example.org" % chr(0x212A), config=mapped),
                            "draft-reply-target")
        self.assert_accepted(self.check(record=record, target="mark.reply@example.org", config=mapped))

    def test_a_message_with_no_single_from_has_no_reply_target(self):
        record = self.stored("pass", address=None, digest=samples.state_digest("no from"))
        self.assertIsNone(record["sender"])
        for target in (SENDER, "", None):
            self.assert_refused(self.check(record=record, target=target), "draft-reply-target")

    def test_the_reply_target_may_be_named_in_the_draft_and_no_other_address(self):
        config = self.mapped_config()
        names_sender = "We have %s on file." % SENDER
        names_mapped = "We will write to %s." % self.MAPPED
        self.assert_accepted(self.check(body=names_sender), body=names_sender)
        self.assert_accepted(self.check(body=names_sender.upper()), body=names_sender.upper())
        self.assert_accepted(self.check(body=names_mapped, target=self.MAPPED, config=config), body=names_mapped)
        # the target is one address: with the mapped address as the target, the From address is another
        self.assert_refused(self.check(body=names_sender, target=self.MAPPED, config=config), "draft-address")
        self.assert_refused(self.check(body=names_mapped, target=SENDER, config=config), "draft-address")
        # a refused target is not an allowed address either
        self.assert_refused(self.check(body="We have %s on file." % OTHER_SENDER, target=OTHER_SENDER),
                            "draft-reply-target", "draft-address")

    def test_the_host_part_of_an_allowed_address_is_not_a_bare_host(self):
        for text in ("Write to %s." % OWN, "Write to %s, %s." % (OWN, SENDER), "(%s)" % OWN, "<%s>" % SENDER,
                     "%s; %s" % (OWN.upper(), SENDER)):
            with self.subTest(text=text):
                self.assert_accepted(self.check(body=text), body=text)
                self.assert_accepted(self.check(subject=text), subject=text)
        # the host of an address that is not allowed is counted once, as an address
        result = self.check(body="Write to %s." % OTHER_SENDER)
        self.assert_refused(result, "draft-address")
        self.assertEqual(result.rule_hits[0].count, 1)
        # the same host with no address in front of it is a bare host
        self.assert_refused(self.check(body="See %s." % SENDER.split("@")[1]), "draft-bare-host")


# --------------------------------------------------------------------------------------
# TS-DRAFT-03: numbers
# --------------------------------------------------------------------------------------

class Numbers(DraftCase):
    def number_case(self, with_pack):
        record = self.stored("pass", view_text=samples.draft_digit_view(), digest=samples.state_digest("digits"))
        pack = samples.draft_knowledge_pack(self.tmp, samples.draft_digit_pack()) if with_pack else None
        return record, samples.draft_config(knowledge_pack=pack)

    def test_ts_draft_03_seven_or_eight_digits_of_the_view_are_allowed_and_others_refused(self):
        record, config = self.number_case(with_pack=False)
        runs = samples.draft_digit_runs()
        for count in (7, 8):
            in_view, _in_pack, in_neither = runs[count]
            with self.subTest(count=count):
                self.assertEqual(len(in_view), count)
                self.assert_accepted(self.check(body="Number %s." % in_view, record=record, config=config),
                                     body="Number %s." % in_view)
                self.assert_refused(self.check(body="Number %s." % in_neither, record=record, config=config),
                                    "draft-digit-run")
                self.assert_refused(self.check(body="Thanks.", subject="Number %s" % in_neither, record=record,
                                               config=config), "draft-digit-run")
                self.assert_accepted(self.check(body="Thanks.", subject="Number %s" % in_view, record=record,
                                                config=config), body="Thanks.", subject="Number %s" % in_view)

    def test_the_digit_run_edges_with_the_view_the_pack_and_neither(self):
        runs = samples.draft_digit_runs()
        self.assertEqual(sorted(runs), [6, 7, 8, 9, 15, 16, 17])
        # count -> (in the view, only in the pack with the pack configured, only in the pack without it, in neither)
        expected = {
            6: (None, None, None, None),
            7: (None, None, "draft-digit-run", "draft-digit-run"),
            8: (None, None, "draft-digit-run", "draft-digit-run"),
            9: (None, None, "draft-phone", "draft-phone"),
            15: (None, None, "draft-phone", "draft-phone"),
            16: (None, None, "draft-digit-run", "draft-digit-run"),
            17: (None, None, "draft-digit-run", "draft-digit-run"),
        }
        with_pack = self.number_case(with_pack=True)
        without = (with_pack[0], samples.draft_config())
        for count, (view_rule, pack_rule, no_pack_rule, neither_rule) in expected.items():
            in_view, in_pack, in_neither = runs[count]
            cases = ((in_view, with_pack, view_rule), (in_view, without, view_rule), (in_pack, with_pack, pack_rule),
                     (in_pack, without, no_pack_rule), (in_neither, with_pack, neither_rule),
                     (in_neither, without, neither_rule))
            for index, (run, (record, config), rule) in enumerate(cases):
                with self.subTest(count=count, case=index):
                    body = "The number is %s, thanks." % run
                    result = self.check(body=body, record=record, config=config)
                    if rule is None:
                        self.assert_accepted(result, body=body)
                    else:
                        self.assert_refused(result, rule)

    def test_a_run_is_compared_with_its_separators_removed(self):
        order = samples.DRAFT_VIEW_ORDER
        for written in ("1234 5678", "12-34-56-78", "1234.5678", "(1234) 5678", "1 2 3 4 5 6 7 8", "+12345678",
                        samples.full_width(order)):
            with self.subTest(written=ascii(written)):
                self.assertEqual("".join(c for c in unicodedata.normalize("NFKC", written) if c.isdigit()), order)
                self.assert_accepted(self.check(body="Order %s." % written), body="Order %s." % written)
        # the same shapes of a number nobody gave
        for written in ("8765 4321", "87-65-43-21", "8765.4321", "(8765) 4321", "8 7 6 5 4 3 2 1"):
            with self.subTest(written=written):
                self.assert_refused(self.check(body="Order %s." % written), "draft-digit-run")
        # four groups of up to three digits between dots are also an address of a machine
        self.assert_refused(self.check(body="Order 12.34.56.78."), "draft-bare-host")

    def test_a_run_may_be_a_part_of_a_longer_run_of_the_view(self):
        tracking = samples.DRAFT_VIEW_TRACKING.replace(" ", "")
        self.assertEqual(len(tracking), 18)
        for part in (tracking, tracking[:16], tracking[2:], tracking[5:12], tracking[-8:]):
            with self.subTest(part=part):
                self.assert_accepted(self.check(body="Ref %s." % part), body="Ref %s." % part)
        # the digits of two different runs of the view, put together, are not a run of the view
        joined = samples.DRAFT_VIEW_REFERENCE[-4:] + tracking[:4]
        self.assertEqual(len(joined), 8)
        self.assert_refused(self.check(body="Ref %s." % joined), "draft-digit-run")

    def test_a_number_the_view_wraps_over_two_lines_is_found(self):
        record = self.stored("pass", view_text="my number is 5544 3322\n1100 9988 77 thanks",
                             digest=samples.state_digest("wrapped"))
        self.assert_accepted(self.check(body="Ref 5544 3322 1100 9988 77.", record=record),
                             body="Ref 5544 3322 1100 9988 77.")
        self.assert_accepted(self.check(body="Ref 55443322.", record=record), body="Ref 55443322.")

    def test_nine_to_fifteen_digits_need_a_whole_run_of_the_view_the_pack_or_the_approved_list(self):
        long_order = samples.DRAFT_VIEW_LONG_ORDER
        self.assertIn(long_order, samples.DRAFT_VIEW_TEXT)
        for written in (long_order, "123 456 789", "123-456-789", samples.full_width(long_order)):
            self.assert_accepted(self.check(body="Order %s." % written), body="Order %s." % written)
        # a part of a longer run of the view, a run of the view with a digit more or less, two runs
        # of the view put together: none is a whole run of the view
        tracking = samples.DRAFT_VIEW_TRACKING.replace(" ", "")
        for written in (tracking[:10], tracking[4:16], long_order + "7", "7" + long_order, long_order + " 7",
                        long_order[:-1] + "0", samples.DRAFT_VIEW_REFERENCE + samples.DRAFT_VIEW_ORDER[:3],
                        samples.DRAFT_OTHER_PHONE):
            with self.subTest(written=written):
                self.assert_refused(self.check(body="Order %s." % written), "draft-phone")
        # the pack gives whole runs too; a missing view gives none
        pack = samples.draft_knowledge_pack(self.tmp, "Helpline 0333 555 0142 and code 998877665.")
        with_pack = samples.draft_config(knowledge_pack=pack)
        for written in ("0333 555 0142", "03335550142", "998877665"):
            self.assert_accepted(self.check(body="Use %s." % written, config=with_pack), body="Use %s." % written)
            self.assert_refused(self.check(body="Use %s." % written), "draft-phone")
        self.assert_refused(self.check(body="Use 0333 555 014.", config=with_pack), "draft-phone")
        no_view = self.stored("pass", with_view=False, digest=samples.state_digest("no view, long order"))
        self.assert_refused(self.check(body="Order %s." % long_order, record=no_view),
                            "draft-phone", "draft-view-missing")
        approved = samples.draft_config()
        approved["approved_phones"] = [samples.DRAFT_OTHER_PHONE]
        self.assert_accepted(self.check(body="Call %s." % samples.DRAFT_OTHER_PHONE, config=approved),
                             body="Call %s." % samples.DRAFT_OTHER_PHONE)

    def test_a_date_and_a_range_of_amounts_are_not_one_number(self):
        accepted = ("2026-12-25", "25.12.2026", "25/12/2026", "25-12-2026", "1.1.2027", "29.02.2028", "1900-01-01",
                    "2100-12-31", "2026-12-25 2026-12-26", "(2026-12-25)", "9.00-17.30", "10.30 - 11.45",
                    "1299.00 - 1499.00", "0.50-0.75", "09:00-17:30", "2026-12-25 9.00-17.30")
        for written in accepted:
            with self.subTest(accepted=written):
                self.assert_accepted(self.check(body="It is %s here." % written), body="It is %s here." % written)
                self.assert_accepted(self.check(body="Thanks.", subject="It is %s here" % written),
                                     body="Thanks.", subject="It is %s here" % written)
        refused = {"2026-13-25": "draft-digit-run", "2026-02-30": "draft-digit-run", "29.02.2027": "draft-digit-run",
                   "32.12.2026": "draft-digit-run", "00.12.2026": "draft-digit-run", "1899-12-31": "draft-digit-run",
                   "2101-01-01": "draft-digit-run", "25.12-2026": "draft-digit-run", "2026.12.25": "draft-digit-run",
                   "2026-12-25-1": "draft-phone", "1-2026-12-25": "draft-phone", "2026-12-25.5": "draft-phone",
                   "20261225": "draft-digit-run", "2026 12 25": "draft-digit-run",
                   "1299 - 1499": "draft-digit-run", "1299.0 - 1499.0": "draft-phone",
                   "1299.000 - 1499.000": "draft-phone", "12.00-13.00-14.00": "draft-phone",
                   "1299.00 - 1499.00.5": "draft-phone", "0171 55.50 - 19.90": "draft-digit-run",
                   "12345.00 - 67890.00": "draft-digit-run"}
        for written, rule in refused.items():
            with self.subTest(refused=written):
                self.assert_refused(self.check(body="It is %s here." % written), rule)
        # a date does not carry the digits next to it through
        self.assert_refused(self.check(body="On 2026-12-25 call %s." % samples.DRAFT_OTHER_PHONE), "draft-phone")
        self.assert_refused(self.check(body="On 2026-12-25 %s." % "7777777"), "draft-digit-run")

    def test_a_trunk_zero_in_brackets_is_read_out_of_an_approved_number(self):
        for written in ("+44 (0)161 496 0123", "+44 (0) 161 496 0123", "+44(0)1614960123", "+44 (0)161-496-0123"):
            with self.subTest(written=written):
                self.assert_accepted(self.check(body="Call %s today." % written), body="Call %s today." % written)
        for written in ("+7 (0)161 496 0123", "44 (0)161 496 0123", "+44 (0)(0)161 496 0123", "+44 (1)161 496 0123",
                        "+44 (00)161 496 0123", "+44 (0)171 555 0199", "+44 (0)161 496 0123 4"):
            with self.subTest(written=written):
                self.assert_refused(self.check(body="Call %s today." % written), "draft-phone")
        national_only = samples.draft_config()
        national_only["approved_phones"] = [PHONE]
        self.assert_refused(self.check(body="Call +44 (0)161 496 0123.", config=national_only), "draft-phone")

    def test_with_no_approved_number_the_phone_of_the_reply_is_refused(self):
        long_order = samples.DRAFT_VIEW_LONG_ORDER
        # with no approved number at all, every phone-sized run is refused
        nothing = samples.draft_config()
        nothing["approved_phones"] = []
        self.assert_refused(self.check(config=nothing), "draft-phone")

    def test_an_approved_number_is_accepted_in_any_spelling_of_its_digits(self):
        for written in (PHONE, PHONE.replace(" ", ""), PHONE.replace(" ", "-"), PHONE.replace(" ", "."),
                        "(0161) 496 0123", "0161 (496) 0123", samples.DRAFT_PHONE_INTERNATIONAL,
                        samples.DRAFT_PHONE_INTERNATIONAL.replace("+", ""), "+" + PHONE.replace(" ", ""),
                        samples.full_width(PHONE), PHONE.replace(" ", chr(0x2013)), PHONE.replace(" ", chr(0xA0))):
            with self.subTest(written=ascii(written)):
                self.assert_accepted(self.check(body="Call %s today." % written), body="Call %s today." % written)

    def test_an_approved_number_opens_a_run_and_digits_close_to_it_make_another_number(self):
        accepted = ("%s. 24 hours", "%s (9am to 5pm)", "%s - 9 to 5", "%s, 24", "%s, 9 to 5", "%s or %s",
                    "%s / 24")
        for form in accepted:
            body = "Call " + form.replace("%s", PHONE)
            with self.subTest(body=body):
                self.assert_accepted(self.check(body=body), body=body)
        refused = ("%s 4567", "%s-4567", "%s.45", "%s4", "9 %s", "+7 %s", "44 %s", "+7 (%s)", "1 - %s")
        for form in refused:
            body = "Call " + form.replace("%s", PHONE)
            with self.subTest(body=body):
                self.assert_refused(self.check(body=body), "draft-phone")
        # what follows an approved number after a gap is a run of its own
        self.assert_refused(self.check(body="Call %s, %s" % (PHONE, samples.DRAFT_OTHER_PHONE)), "draft-phone")
        self.assert_refused(self.check(body="Call %s - 7777777" % PHONE), "draft-digit-run")
        self.assert_accepted(self.check(body="Call %s - %s" % (PHONE, samples.DRAFT_VIEW_ORDER)),
                             body="Call %s - %s" % (PHONE, samples.DRAFT_VIEW_ORDER))

    def test_a_number_written_over_several_lines_is_one_number(self):
        other = samples.DRAFT_OTHER_PHONE.replace(" ", "")
        for split in ("0171\n555\n0199", "01715\n550199", "0171\r\n555\r\n0199", "0171\n\n555\n\n0199",
                      "0171-\n555-\n0199", "01\n71\n55\n50\n19\n9", "+\n" + other[:5] + "\n" + other[5:]):
            with self.subTest(split=ascii(split)):
                self.assertEqual("".join(c for c in split if c.isdigit()), other)
                ending = "\r\n" if "\r" in split else "\n"
                self.assert_refused(self.check(body="Call%s%s%snow" % (ending, split, ending)), "draft-phone")
        # seven digits nobody gave, over two lines
        self.assert_refused(self.check(body="Ref 7777\n777 is yours"), "draft-digit-run")
        # an approved number over lines stays approved when no piece of it is a number by itself
        self.assert_accepted(self.check(body="Call 01614\n960123 now"), body="Call 01614\n960123 now")

    def test_numbers_on_neighbouring_lines_that_are_each_accounted_for_are_not_joined(self):
        order, reference = samples.DRAFT_VIEW_ORDER, samples.DRAFT_VIEW_REFERENCE
        for body in ("Order %s\n2 items" % order, "Order %s\nReference %s" % (order, reference),
                     "%s\n%s" % (order, reference), "Call %s\n24 hours a day" % PHONE,
                     "Call %s\n%s" % (PHONE, order), "Code 123456.\n\n24 hours",
                     "Code 123456.", "Code 123456.\n24 hours", "123456.\n\n24 hours",
                     "1. Item 12345\n2. Item 67890", "Total 45\n2 items\n3 boxes"):
            with self.subTest(body=body):
                self.assert_accepted(self.check(body=body), body=body)
        # a full stop ends a number at the end of a paragraph or of a line with words, not on a line of digits
        self.assert_refused(self.check(body="123456.\n24 hours"), "draft-digit-run")
        self.assert_refused(self.check(body="Call 0171.\n555.\n0199."), "draft-digit-run")
        self.assert_refused(self.check(body="Call\n0171.\n555.\n0199."), "draft-phone")

    def test_digits_inside_an_allowed_address_are_not_a_number_and_inside_a_url_they_are(self):
        own_with_digits = samples.draft_config()
        own_with_digits["own_addresses"] = ["desk7777777@example.com"]
        body = "Write to desk7777777@example.com."
        self.assert_accepted(self.check(body=body, config=own_with_digits), body=body)
        # the same digits outside it are judged
        self.assert_refused(self.check(body="See 777777777.", config=own_with_digits), "draft-phone")
        # review B F2: an allowed host in front of a number was a cover for it
        for body, rule in (("See %s/orders/777777777 today." % SITE, "draft-phone"),
                           ("See %s/4929123456789012 thanks" % SITE, "draft-digit-run"),
                           ("See https://%s/a/4929-1234-5678-9012 thanks" % SITE, "draft-digit-run"),
                           ("See %s/help#4929123456789012" % SITE, "draft-digit-run"),
                           ("See %s/call/0171.555.0199" % SITE, "draft-phone"),
                           ("See %s/x/7654329" % SITE, "draft-digit-run")):
            with self.subTest(body=body):
                self.assert_refused(self.check(body=body), rule)
        self.assert_refused(self.check(subject="Re: %s/4929123456789012" % SITE), "draft-digit-run")
        # a number the customer wrote, an approved phone, a short number and a date are as fine there as anywhere
        for body in ("See %s/orders/%s today." % (SITE, samples.DRAFT_VIEW_ORDER), "See %s/help/page-2." % SITE,
                     "See %s/news/2026-10-21/" % SITE, "See %s/v2/items/123/456" % SITE):
            with self.subTest(body=body):
                self.assert_accepted(self.check(body=body), body=body)
        # and the path is short
        body = "See %s/%s" % (SITE, "a" * 79)
        self.assert_accepted(self.check(body=body), body=body)
        self.assert_refused(self.check(body="See %s/%s" % (SITE, "a" * 80)), "draft-url")
        self.assert_refused(self.check(body="See %s/a#%s" % (SITE, "b" * 79)), "draft-url")
        self.assertEqual(mail_lists.DRAFT_ALLOWED_URL_TAIL_MAX_CHARS, 80)
        # a path that climbs out of where it stands is not a plain path
        self.assert_refused(self.check(body="See https://%s/a/../../x today" % SITE), "draft-url")
        self.assert_refused(self.check(body="See %s/./x today" % SITE), "draft-url")

    def test_the_knowledge_pack_gives_numbers_and_an_unreadable_one_is_a_refusal(self):
        pack_number = samples.DRAFT_PACK_NUMBER
        body = "The returns reference is %s and the account is %s." % (pack_number, samples.DRAFT_PACK_LONG_NUMBER)
        self.assert_refused(self.check(body=body), "draft-digit-run")
        pack = samples.draft_knowledge_pack(self.tmp)
        self.assert_accepted(self.check(body=body, config=samples.draft_config(knowledge_pack=pack)), body=body)
        # unreadable: a directory, bytes that are not UTF-8, a file over the bound
        os.mkdir(os.path.join(self.tmp, "a-directory"))
        not_text = os.path.join(self.tmp, "not-text.txt")
        with open(not_text, "wb") as handle:
            handle.write(b"reference " + pack_number.encode("ascii") + b" \xff\xfe")
        too_big = os.path.join(self.tmp, "too-big.txt")
        with open(too_big, "wb") as handle:
            handle.write(pack_number.encode("ascii") + b" " * mail_lists.KNOWLEDGE_PACK_MAX_BYTES)
        at_bound = os.path.join(self.tmp, "at-bound.txt")
        with open(at_bound, "wb") as handle:
            handle.write((pack_number + " " + samples.DRAFT_PACK_LONG_NUMBER).encode("ascii").ljust(
                mail_lists.KNOWLEDGE_PACK_MAX_BYTES))
        for path in (os.path.join(self.tmp, "a-directory"), not_text, too_big):
            with self.subTest(path=os.path.basename(path)):
                self.assert_refused(self.check(body=body, config=samples.draft_config(knowledge_pack=path)),
                                    "draft-digit-run", "draft-knowledge-pack")
                self.assert_refused(self.check(config=samples.draft_config(knowledge_pack=path)),
                                    "draft-knowledge-pack")
        self.assert_accepted(self.check(body=body, config=samples.draft_config(knowledge_pack=at_bound)), body=body)


# --------------------------------------------------------------------------------------
# Links, hosts and addresses behind another spelling
# --------------------------------------------------------------------------------------

class Smuggling(DraftCase):
    def test_a_form_that_reads_as_a_link_an_address_or_a_number_is_refused(self):
        table = samples.draft_smuggled()
        self.assertGreaterEqual(len(table), 30)
        for label, (text, rule) in table.items():
            with self.subTest(label=label, where="body"):
                result = self.check(body="Please see: %s thanks" % text)
                self.assertEqual(result.result, REFUSE)
                self.assertIn(rule, ids(result))
            if "\n" not in text:
                with self.subTest(label=label, where="subject"):
                    result = self.check(subject="Re: %s" % text)
                    self.assertEqual(result.result, REFUSE)
                    self.assertIn(rule, ids(result))

    def test_a_compatibility_form_is_refused_as_its_plain_form_is(self):
        for rule in ("draft-markup", "draft-url", "draft-url-query", "draft-bare-host", "draft-address",
                     "draft-phone", "draft-digit-run"):
            for text in samples.draft_bad_texts()[rule]:
                wide = samples.full_width(text)
                with self.subTest(rule=rule, text=ascii(text)):
                    self.assertNotEqual(wide, text)
                    self.assertEqual(unicodedata.normalize("NFKC", wide), text)
                    self.assertIn(rule, ids(self.check(body=wide)))
                    self.assertIn(rule, ids(self.check(subject=wide)))

    def test_every_listed_dot_look_alike_makes_a_host(self):
        for char in mail_lists.DRAFT_DOT_LOOKALIKES + chr(0xFF0E) + chr(0xFE52) + chr(0x2024) + chr(0x0387):
            with self.subTest(char=ascii(char)):
                text = "see %s%sexample%snet now" % (MARKER.lower(), char, char)
                self.assert_refused(self.check(body=text), "draft-bare-host")
                self.assert_refused(self.check(subject=text), "draft-bare-host")
        # an ordinary bullet list is not a host
        bullets = "%s first\n%s second" % (chr(0x2022), chr(0x2022))
        self.assert_accepted(self.check(body=bullets), body=bullets)

    def test_a_host_is_found_whatever_stands_next_to_it(self):
        host = "%s.example.net" % MARKER.lower()
        neighbours = list("_-.,;:!?()[]{}\"'/\\|*~#=+%&$^") + ["", " ", "\t", "\n", "--", "__", "..", chr(0x2014),
                                                              chr(0xA0), chr(0x3000), "1"]
        lefts = neighbours + ["a", chr(0xE9)]        # a letter glued to the END makes another last label
        generator = random.Random(351)
        for _ in range(600):
            left, right = generator.choice(lefts), generator.choice(neighbours)
            text = "see %s%s%s now" % (left, host, right)
            result = self.check(body=text)
            self.assertEqual(result.result, REFUSE, ascii(text))
            self.assertTrue({"draft-bare-host", "draft-url", "draft-address"} & set(ids(result)), ascii(text))
        for left in lefts:
            for right in neighbours:
                self.assertEqual(self.check(body="%s%s%s" % (left, host, right)).result, REFUSE, ascii(left + right))

    def test_the_allowed_host_is_accepted_only_in_its_plain_forms(self):
        accepted = (SITE, "https://" + SITE, "http://" + SITE, "HTTPS://" + SITE.upper() + "/Help", SITE + "/",
                    SITE + "/help", SITE + "/help/returns.html", SITE + "/help#returns", SITE + "/a-b_c~d/e.f",
                    SITE + "/help/", SITE + "/#top", SITE + "#top",
                    "(" + SITE + ")", SITE + ".", SITE + ", and more", "https://" + SITE + "/help?", "'" + SITE + "'",
                    SITE + "/help)", samples.full_width(SITE))
        for text in accepted:
            with self.subTest(accepted=ascii(text)):
                self.assert_accepted(self.check(body="See %s" % text), body="See %s" % text)
                self.assert_accepted(self.check(subject="See %s" % text), subject="See %s" % text)
        refused = {
            SITE + ":443": "draft-url", SITE + ":8080/help": "draft-url", "ftp://" + SITE: "draft-url",
            "https://user@" + SITE: "draft-url", "https://" + SITE + "@evil.example": "draft-url",
            SITE + "/help;x=1": "draft-url", SITE + "/a%2e%2e/b": "draft-url", SITE + "/a\\b": "draft-url",
            SITE + "/a=b": "draft-url", SITE + "/a&b": "draft-url", SITE + "//evil.example": "draft-url",
            SITE + "/a//b": "draft-url", SITE + "/a:b": "draft-url", SITE + "/a@b": "draft-url",
            SITE + "?": None, SITE + "?x": "draft-url-query", SITE + "/?x=1": "draft-url-query",
            SITE + "/help?next=evil.example": "draft-url-query", SITE + "#a?b": "draft-url-query",
            "https://" + SITE + "/help?x=1#y": "draft-url-query", SITE + ".evil.example": "draft-url",
            SITE + "-evil.example": "draft-url", SITE + "evil": "draft-url", "x" + SITE: "draft-bare-host",
            "evil." + SITE: "draft-bare-host", "-" + SITE: "draft-bare-host", "_" + SITE: "draft-bare-host",
            "https:" + SITE: "draft-url", "https:/" + SITE: "draft-url", "//" + SITE + "/x": None,
            "javascript:alert(1)": "draft-url", "data:text/plain,hello": "draft-url",
            "mailto:" + OWN: "draft-url", "hxxps://" + SITE: "draft-url", "://": "draft-url",
        }
        for text, rule in refused.items():
            with self.subTest(refused=text):
                result = self.check(body="See %s today" % text)
                if rule is None:
                    self.assert_accepted(result, body="See %s today" % text)
                else:
                    self.assert_refused(result, rule)

    def test_a_host_is_allowed_only_when_the_config_lists_it(self):
        nothing = samples.draft_config()
        nothing["allowed_hosts"] = []
        self.assert_refused(self.check(config=nothing), "draft-bare-host")
        self.assert_refused(self.check(body="See https://%s/help" % SITE, config=nothing), "draft-url")
        several = samples.draft_config()
        several["allowed_hosts"] = ["Example.COM.", "shop.example.com", "example.com.au", "localhost"]
        for text, rule in (("example.com", None), ("EXAMPLE.com/help", None), ("shop.example.com/a", None),
                           ("example.com.au/a", None), ("https://localhost/a", None),
                           # `www.` in front of a listed host, or left off one, is the same host
                           (SITE, None), ("https://www.shop.example.com/a", None), ("www.example.com.au", None),
                           ("www.www.example.com", "draft-bare-host"), ("ww.example.com", "draft-bare-host"),
                           ("www2.example.com", "draft-bare-host"), ("example.community", "draft-url"),
                           ("example.com.auction", "draft-url"), ("shop.example.com.au", "draft-url"),
                           ("my.shop.example.com", "draft-bare-host"), ("example.org", "draft-bare-host")):
            with self.subTest(text=text):
                result = self.check(body="See %s today" % text, config=several)
                if rule is None:
                    self.assert_accepted(result, body="See %s today" % text)
                else:
                    self.assert_refused(result, rule)

    def test_a_draft_is_accepted_only_when_it_holds_no_hostile_piece(self):
        """Seeded: ordinary pieces and allowed forms in any order are accepted; one hostile piece refuses."""
        ordinary = ["Thanks for your message.", "We are open 9am to 5pm.", "Call %s." % PHONE, "Write to %s." % OWN,
                    "See %s/help." % SITE, "Your order %s has shipped." % samples.DRAFT_VIEW_ORDER,
                    "That is 12.50 in total.", "See you on 21/10/2026 at 9:30.", "Kind regards,", "e.g. at 9 a.m.",
                    "We have %s on file." % SENDER, "- first\n- second"]
        hostile = ([text for texts in samples.draft_bad_texts().values() for text in texts]
                   + [text for text, _rule in samples.draft_smuggled().values()])
        generator = random.Random(4351)
        refused = accepted = 0
        for _ in range(2000):
            pieces = [generator.choice(ordinary) for _ in range(generator.randint(1, 6))]
            bad = generator.random() < 0.5
            if bad:
                pieces.insert(generator.randint(0, len(pieces)), generator.choice(hostile))
            body = generator.choice(["\n", "\n\n", " "]).join(pieces).replace("\r\n", "\n")
            result = self.check(body=body)
            if bad:
                refused += 1
                self.assertEqual(result.result, REFUSE, ascii(body))
            else:
                accepted += 1
                self.assertEqual((result.result, ids(result)), (ACCEPT, []), ascii(body))
        self.assertGreater(min(refused, accepted), 800)


# --------------------------------------------------------------------------------------
# Secrets and the canary
# --------------------------------------------------------------------------------------

class SecretsAndCanary(DraftCase):
    def test_a_secret_is_refused_in_any_form_of_the_text(self):
        token = samples.provider_token()
        for text in (samples.secret_text(token), samples.full_width(token), "x " + samples.private_key_header(),
                     samples.secret_text(samples.catalog_only_secret())):
            with self.subTest(text=len(text)):
                self.assertIn("draft-secret", ids(self.check(body=text)))
                if len(text) <= mail_lists.DRAFT_SUBJECT_MAX_CHARS and "\n" not in text:
                    self.assertIn("draft-secret", ids(self.check(subject=text)))
        self.assert_accepted(self.check(body="The password policy asks for 12 characters."),
                             body="The password policy asks for 12 characters.")

    def test_without_the_catalog_the_draft_is_refused_and_a_token_is_still_found(self):
        for path in [samples.missing_catalog_path(self.tmp), samples.unloadable_catalog(self.tmp),
                     samples.raising_catalog(self.tmp)] + sorted(samples.wrong_form_catalogs(self.tmp).values()):
            missing = mail_reuse.catalog_checks(path)
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual((missing.checks, missing.gap), ((), mail_reuse.GAP_CATALOG_MISSING))
                self.assert_refused(self.check(catalog=missing), "draft-catalog-missing")
                self.assert_refused(self.check(body=samples.secret_text(samples.provider_token()), catalog=missing),
                                    "draft-secret", "draft-catalog-missing")

    def test_the_catalog_is_loaded_when_the_caller_gives_none(self):
        self.assert_accepted(draft_check.check(self.record["id"], self.body, self.subject, SENDER, self.config,
                                               self.root))
        result = draft_check.check(self.record["id"], samples.secret_text(samples.catalog_only_secret()),
                                   self.subject, SENDER, self.config, self.root)
        self.assert_refused(result, "draft-secret")

    def test_the_canary_is_found_in_other_spellings(self):
        canary = samples.draft_canary()
        config = samples.draft_config(canary=canary)
        spellings = (canary, canary.lower(), canary.upper(), canary.replace("-", " "), canary.replace("-", ""),
                     " ".join(canary), samples.full_width(canary), canary.replace("-", chr(0x2013)),
                     "x" + canary + "x", canary.replace("-", "\n"), canary.replace("-", "_"))
        for text in spellings:
            with self.subTest(text=ascii(text)):
                self.assertIn("draft-canary", ids(self.check(body="The word is %s." % text, config=config)))
            if "\n" not in text:
                with self.subTest(subject=ascii(text)):
                    self.assertIn("draft-canary", ids(self.check(subject="Re: %s" % text, config=config)))
        # with no canary configured the same text is nothing special
        body = "The word is %s." % canary.replace("-", " ").replace("7731", "seven")
        self.assert_accepted(self.check(body=body), body=body)
        # a part of it is not the canary
        self.assert_accepted(self.check(body="A pine and a kestrel.", config=config), body="A pine and a kestrel.")

    def test_a_short_canary_is_matched_as_it_is_written_only(self):
        config = samples.draft_config(canary="k-9")
        self.assert_refused(self.check(body="Code k-9 here", config=config), "draft-canary")
        self.assert_refused(self.check(body="Code K-9 here", config=config), "draft-canary")
        # squeezed it would be two characters, and those are in every other word
        self.assert_accepted(self.check(body="The desk 9 is free", config=config), body="The desk 9 is free")


# --------------------------------------------------------------------------------------
# The result and the config
# --------------------------------------------------------------------------------------

class Output(DraftCase):
    def assert_no_marker(self, value):
        self.assertNotIn(MARKER.lower(), json.dumps(value, sort_keys=True, default=repr).lower())

    def test_a_marker_in_the_draft_appears_in_no_field_of_the_result(self):
        texts = [text for texts in samples.draft_bad_texts(MARKER).values() for text in texts]
        texts += [text for text, _rule in samples.draft_smuggled(MARKER).values()]
        self.assertGreater(sum(1 for text in texts if MARKER.lower() in text.lower()), 60)
        target = "%s@%s.example.net" % (MARKER, MARKER)
        config = samples.draft_config(canary=MARKER + "-canary",
                                      reply_to_map={"%s@example.org" % MARKER: "%s-map@example.net" % MARKER})
        config["own_addresses"] = [OWN, "%s-own@example.com" % MARKER]
        config["allowed_hosts"] = [SITE, "%s.example.com" % MARKER.lower()]
        for text in texts:
            for result in (self.check(body=text, target=target, config=config),
                           self.check(subject=text.replace("\n", " "), target=target, config=config),
                           self.check(body=text, subject=text.replace("\n", " "), record={"id": MARKER},
                                      target=target, config=config)):
                self.assertEqual(result.result, REFUSE)
                self.assert_no_marker(draft_check.recordable(result))
                self.assert_no_marker([repr(result), str(result), list(result)])
        accepted = self.check(body="A word: %s" % MARKER, subject="Re: %s" % MARKER)
        self.assertEqual(accepted.result, ACCEPT)
        self.assert_no_marker(draft_check.recordable(accepted))

    def test_the_result_holds_rule_ids_counts_and_digests_only(self):
        result = self.check(body="see one.example.net and two.example.net, call %s" % samples.DRAFT_OTHER_PHONE,
                            subject="Re: three.example.net", target=OTHER_SENDER)
        self.assertEqual([(hit.rule_id, hit.rule_class, hit.count) for hit in result.rule_hits],
                         [("draft-bare-host", "refuse", 3), ("draft-phone", "refuse", 1),
                          ("draft-reply-target", "refuse", 1)])
        plain = draft_check.recordable(result)
        self.assertEqual(plain, {
            "result": "refuse", "body_sha256": None, "subject_sha256": None,
            "rules": [{"rule_id": "draft-bare-host", "rule_class": "refuse", "count": 3},
                      {"rule_id": "draft-phone", "rule_class": "refuse", "count": 1},
                      {"rule_id": "draft-reply-target", "rule_class": "refuse", "count": 1}]})
        self.assertEqual(json.loads(json.dumps(plain)), plain)
        accepted = draft_check.recordable(self.check())
        self.assertEqual(accepted, {"result": "accept", "rules": [], "body_sha256": sha(self.body),
                                    "subject_sha256": sha(self.subject)})
        self.assertEqual(draft_check.DraftResult._fields, ("result", "rule_hits", "body_sha256", "subject_sha256"))
        self.assertEqual(draft_check.RuleHit._fields, ("rule_id", "rule_class", "count"))

    def test_the_hits_come_in_the_order_of_the_rule_table(self):
        order = list(mail_lists.REFUSE_RULE_IDS)
        body = "\n".join(texts[0] for texts in samples.draft_bad_texts().values())
        found = ids(self.check(body=body, target=None))
        self.assertGreaterEqual(len(found), 10)
        self.assertEqual(found, sorted(found, key=order.index))
        self.assertEqual(len(found), len(set(found)))

    def test_a_body_or_a_subject_that_is_not_text_is_an_error_with_a_fixed_text(self):
        for body, subject in ((None, "s"), (b"bytes " + MARKER.encode("ascii"), "s"), ("b", None), ("b", 7),
                              ([MARKER], "s")):
            with self.subTest(body=ascii(body), subject=ascii(subject)):
                with self.assertRaises(ValueError) as caught:
                    draft_check.check(self.record["id"], body, subject, SENDER, self.config, self.root, CATALOG)
                self.assertEqual(str(caught.exception), draft_check.INPUT_ERROR)

    def test_a_config_of_the_wrong_form_is_an_error_with_a_fixed_text(self):
        good = samples.draft_config()
        bad = [None, [], "config", MARKER]
        for name, values in (
                ("own_addresses", ("x", {"a": 1}, [1], [None], [MARKER.encode("ascii")])),
                ("allowed_hosts", ("x", [1], ["https://%s.example" % MARKER], ["a/b"], ["a b"], ["a@b"], ["a?b"], [""],
                                   ["a:8080"], ["  "])),
                ("approved_phones", ("x", [1], ["no digits"], [""], ["+"])),
                ("reply_to_map", ("x", [], {1: "a"}, {"a": 1}, {"a": None})),
                ("knowledge_pack", (1, "", [MARKER])),
                ("canary", (1, "", "   ", [MARKER]))):
            for value in values:
                bad.append(dict(good, **{name: value}))
        for index, config in enumerate(bad):
            with self.subTest(index=index, config=ascii(config)[-80:]):
                with self.assertRaises(ValueError) as caught:
                    draft_check.check(self.record["id"], self.body, self.subject, SENDER, config, self.root, CATALOG)
                self.assertEqual(str(caught.exception), draft_check.CONFIG_ERROR)
                self.assertNotIn(MARKER, str(caught.exception))

    def test_a_config_with_nothing_in_it_allows_nothing(self):
        for config in ({}, {"own_addresses": None, "allowed_hosts": None, "approved_phones": None,
                            "reply_to_map": None, "knowledge_pack": None, "canary": None}):
            self.assert_refused(self.check(config=config), "draft-bare-host", "draft-address", "draft-phone")
            self.assert_accepted(self.check(body="Thanks, we will write again.", config=config),
                                 body="Thanks, we will write again.")

    def test_the_config_of_the_rules_is_read_as_it_is(self):
        """JC-8: the dict the rules take is the dict the draft check takes."""
        config = samples.rules_config(reply_to_map={SENDER: samples.DRAFT_MAPPED_ADDRESS})
        body = "See www.example.com or write to %s." % samples.OWN_ADDRESS
        self.assert_accepted(self.check(body=body, config=config), body=body)
        self.assert_accepted(self.check(body=body, config=config, target=samples.DRAFT_MAPPED_ADDRESS), body=body)


# --------------------------------------------------------------------------------------
# Fix round 1: what reviews B and C got past the draft check (D1 to D3)
# --------------------------------------------------------------------------------------

class FixRoundTwo(DraftCase):
    """The second review of the draft check: white space as a channel (C1), marks of a script (C2)."""

    def test_white_space_and_look_alike_letters_are_no_channel(self):
        for label, text in samples.draft_white_space_texts().items():
            # fix round 3 (D4): each refusal under its own id, so a person sees what to fix
            rule = "draft-mixed-script" if " letter " in label else "draft-white-space"
            with self.subTest(label=label, where="body"):
                self.assert_refused(self.check(body=text), rule)
            if "\n" not in text:
                with self.subTest(label=label, where="subject"):
                    self.assert_refused(self.check(subject=text), rule)

    def test_the_payload_of_the_second_review_is_refused_in_every_coding(self):
        # review B N2: `card 4929123456789012` (21 bytes) hidden in an ordinary reply, all accepted before
        bits = "".join(format(byte, "08b") for byte in b"card 4929123456789012")
        words = ("Hi Ann thanks for your message your order was sent on Monday and it should be with you in three to "
                 "five working days please let us know if it has not arrived by Friday " * 6).split()

        def coded(symbols):
            width = len(symbols).bit_length() - 1
            out, used = [], 0
            for word in words[:-1]:
                out.append(word)
                out.append(symbols[int(bits[used:used + width].ljust(width, "0"), 2)] if used < len(bits) else " ")
                used += width
            self.assertGreaterEqual(used, len(bits))
            return "".join(out) + words[-1]

        for label, symbols in (("space or no-break space", [" ", chr(0xA0)]), ("space or tab", [" ", "\t"]),
                               ("one or two spaces", [" ", "  "]),
                               ("four kinds of space", [" ", chr(0xA0), chr(0x2002), chr(0x2003)])):
            with self.subTest(coding=label):
                self.assert_refused(self.check(body=coded(symbols)), "draft-white-space")
        lines = ["Hi Ann,", "", "Thanks for your message.", "Your order was sent on Monday.", "Kind regards,", "Sam"] * 4
        tails = "\n".join(line + "".join(" " if bit == "0" else "\t" for bit in bits[8 * number:8 * number + 8])
                          for number, line in enumerate(lines))
        self.assert_refused(self.check(body=tails), "draft-white-space")
        endings = "".join(line + ("\r\n" if bits[number] == "1" else "\n") for number, line in enumerate(lines))
        self.assert_refused(self.check(body=endings), "draft-white-space")
        # the same reply with plain spaces and one kind of line ending is accepted
        for ending in ("\n", "\r\n"):
            body = ending.join(line for line in lines[:6])
            self.assert_accepted(self.check(body=body), body=body)

    def test_the_cap_on_combining_marks_is_for_the_general_marks_only(self):
        # review B N4: Hindi, Burmese and Tibetan words were refused
        self.assertEqual(mail_lists.DRAFT_GENERAL_MARK_RANGES,
                         ((0x0300, 0x036F), (0x1AB0, 0x1AFF), (0x1DC0, 0x1DFF), (0x20D0, 0x20FF), (0xFE20, 0xFE2F)))
        for text in ("e" + chr(0x301), "e" + chr(0x301) + chr(0x323),
                     chr(0x915) + chr(0x93C) + chr(0x94B) + chr(0x902) + chr(0x901),        # four marks of Devanagari
                     chr(0xE17) + chr(0xE35) + chr(0xE48) + chr(0xE4D) + chr(0xE47)):       # four marks of Thai
            with self.subTest(text=ascii(text)):
                self.assert_accepted(self.check(body="Word " + text + " here."), body="Word " + text + " here.")
        for text in ("e" + chr(0x301) + chr(0x323) + chr(0x30A), "e" + chr(0x1AB0) * 3, "e" + chr(0x20D0) * 3):
            with self.subTest(text=ascii(text)):
                self.assert_refused(self.check(body="Word " + text + " here."), "draft-hidden-characters")
        # script marks do not reset it (and, since fix round 3, D5, a mark of Devanagari on a Latin letter is
        # a mark on a letter of another script)
        self.assert_refused(self.check(body="Word e" + chr(0x301) + chr(0x93C) + chr(0x302) + chr(0x93C) + chr(0x303)
                                       + " here."), "draft-hidden-characters", "draft-mixed-script")
        # the non-joiner is writing between two Arabic-script letters, and hiding anywhere else
        joiner = chr(0x200C)
        persian = chr(0x645) + chr(0x6CC) + joiner + chr(0x62E) + chr(0x648)
        self.assert_accepted(self.check(body=persian), body=persian)
        for text in ("thanks" + joiner + "Ann", joiner + chr(0x645), chr(0x645) + joiner, chr(0x645) + joiner + "a",
                     chr(0x645) + joiner + joiner + chr(0x62E)):
            with self.subTest(text=ascii(text)):
                self.assert_refused(self.check(body=text), "draft-hidden-characters")


class FixRoundThree(DraftCase):
    """Fix round 3 (D1-D5): reviews rr2-b N2, N3, N6, N7 and Codex 4, 5."""

    def test_each_text_is_accepted_or_refused_as_the_table_says(self):
        for label, (text, expected) in samples.draft_round_three_texts().items():
            with self.subTest(label=label):
                if expected == "accept":
                    self.assert_accepted(self.check(body=text), body=text)
                else:
                    self.assert_refused(self.check(body=text), expected)

    def test_the_lists_of_the_round(self):
        self.assertEqual(mail_lists.DRAFT_UNIT_GREEK, chr(0x3BC) + chr(0x3A9) + chr(0x394))
        self.assertEqual(mail_lists.DRAFT_UNIT_MAX_LATIN, 3)
        self.assertEqual(mail_lists.DRAFT_SCHEME_PREFIX_PATTERNS, (r"ms-[a-z0-9+.\-]*[a-z0-9]", "search-ms"))
        self.assertEqual(mail_lists.DRAFT_IDEOGRAPHIC_DOT, chr(0x3002))
        self.assertEqual(mail_lists.DRAFT_GENERAL_MARK_NAMES, ("COMBINING", "VARIATION"))

    def test_one_bit_a_text_remains_and_no_more(self):
        # the choice of no-break spaces or plain ones before the marks of a whole text is accepted either way
        for space in (" ", chr(0xA0)):
            body = "Bonjour%s! Merci%s? Oui%s; non%s: peut-etre%s!" % ((space,) * 5)
            self.assert_accepted(self.check(body=body), body=body)
        # mixing them inside one text, the channel of review rr2-b N2, is refused
        mixed = "Bonjour%s! Merci ? Oui%s; non : peut-etre%s!" % ((chr(0xA0),) * 3)
        result = self.check(body=mixed)
        self.assert_refused(result, "draft-white-space")
        self.assertEqual({hit.rule_id: hit.count for hit in result.rule_hits}["draft-white-space"], 2)


class FixRoundOne(DraftCase):
    def test_no_character_a_reader_cannot_see_is_accepted(self):
        # review B F1: 168 characters of U+034F and U+17B5 carried a card number through the check
        for code in (0x034F, 0x180B, 0x180C, 0x180D, 0x180F, 0x17B4, 0x17B5, 0x16FE4, 0x2800, 0x1D159, 0x3164,
                     0x115F, 0x1160, 0xFFA0, 0xFE00, 0xFE0E, 0xFE0F, 0xE0100, 0xE01EF, 0xFFF0, 0x200B, 0x00AD, 0x2060):
            with self.subTest(code=hex(code)):
                self.assertIn("draft-hidden-characters", ids(self.check(body="Thanks for your mes%ssage." % chr(code))))
                self.assertIn("draft-hidden-characters", ids(self.check(subject="Re: Hel%slo" % chr(code))))
        payload = "".join(chr(0x034F) if bit == "1" else chr(0x17B5)
                          for byte in b"card 4929123456789012" for bit in format(byte, "08b"))
        self.assertEqual(len(payload), 168)
        result = self.check(body="Thanks for your message." + payload + " We are open 9am to 5pm.")
        # (U+17B5 is a mark of Khmer: since fix round 3, D5, it is also a mark on a letter of another script)
        self.assert_refused(result, "draft-hidden-characters", "draft-mixed-script")
        self.assertEqual({hit.rule_id: hit.count for hit in result.rule_hits}["draft-hidden-characters"], 168)

    def test_what_a_reader_sees_the_effect_of_is_accepted(self):
        for body in ("Thanks! " + chr(0x263A) + chr(0xFE0F), "Thanks " + chr(0x2764) + chr(0xFE0F) + " a lot",
                     "Press 1" + chr(0xFE0F) + chr(0x20E3) + " to confirm",
                     "Thanks! " + chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467),
                     "Hello from " + samples.flag_emoji("gbsct")):
            with self.subTest(body=ascii(body)):
                self.assert_accepted(self.check(body=body), body=body)
        # a selector after a digit with no keycap, and after a letter, carries nothing a reader sees
        self.assert_refused(self.check(body="Your code is 4" + chr(0xFE0F) + "2."), "draft-hidden-characters")
        self.assert_refused(self.check(body="Thanks" + chr(0xFE0F) + "!"), "draft-hidden-characters")

    def test_more_than_two_combining_marks_on_one_character_are_refused(self):
        acute, grave, ring, dot = chr(0x0301), chr(0x0300), chr(0x030A), chr(0x0323)
        for body in ("Cafe" + acute + " is open.", "Vie" + dot + chr(0x0302) + "t Nam", "a" + acute + grave + " b" + ring + dot,
                     chr(0x0E17) + chr(0x0E35) + chr(0x0E48) + chr(0x0E19) + chr(0x0E35) + chr(0x0E48)):
            with self.subTest(body=ascii(body)):
                self.assert_accepted(self.check(body=body), body=body)
        for body in ("Thanks a" + acute + grave + ring + " lot.", "Z" + (acute + grave) * 20 + "algo text",
                     "ok" + acute * 3):
            with self.subTest(body=ascii(body)):
                self.assert_refused(self.check(body=body), "draft-hidden-characters")
        result = self.check(body="a" + acute * 9 + " b" + grave * 3)
        self.assertEqual({hit.rule_id: hit.count for hit in result.rule_hits},
                         {"draft-hidden-characters": 2})        # one for each pile
        self.assertEqual(mail_lists.DRAFT_MAX_COMBINING_MARKS, 2)

    def test_a_host_tag_is_markup(self):
        # review B m1
        self.assert_refused(self.check(body="<%s/x onmouseover=alert(1)>hello" % SITE), "draft-markup")
        self.assert_refused(self.check(body="see <https://%s/x class=a> now" % SITE), "draft-markup")
        for body in ("See <https://%s/help> for more." % SITE, "See <%s> for more." % SITE):
            self.assert_accepted(self.check(body=body), body=body)

    def test_hosts_the_first_check_let_through(self):
        # review C F7
        for body in ("go to evil .com now", "go to evil . com now", "go to evil. com now", "go to evil.\ncom now",
                     "go to evil .co.uk", "go to evil. org today", "visit evil.ltd/login", "visit evil.chat",
                     "visit evil.tools today", "open [::1] now", "open [2001:db8::1]:8080", "open 2001:db8::1 now",
                     "open ::1 now", "open localhost:8080", "open LOCALHOST now", "open \\\\evil\\share now",
                     "open \\\\evil.example\\c$\\x"):
            with self.subTest(body=body):
                result = self.check(body=body)
                self.assertEqual(result.result, REFUSE)
                # a host, or (a name and a port) a word with a colon before text
                self.assertTrue(set(ids(result)) <= {"draft-bare-host", "draft-url"}, ids(result))
                self.assertTrue(set(ids(result)) & {"draft-bare-host", "draft-url"})
        # the shapes of ordinary writing next to them stay accepted
        for body in ("It is done. It works. In the morning. So it goes. To us. Is it? No. Me too.",
                     "The net price incl. net weight etc. to follow.", "Open 10:30:00 to 17:00:00.",
                     "Names such as std::map are not hosts.", "The local host of the event is Ann.",
                     "Notes [1], [a:b] and [10:30].", "Use a \\ or two \\\\ as you like.", "See the list : com, org.",
                     "Done.\nCome by tomorrow."):
            with self.subTest(body=body):
                self.assert_accepted(self.check(body=body), body=body)
        self.assertEqual(mail_lists.DRAFT_SPACED_TLDS, ("com", "org", "io", "biz", "xyz"))

    def test_any_word_and_a_colon_before_text_is_a_scheme(self):
        phone = samples.DRAFT_PHONE.replace(" ", "")
        # fix round 2 (C3): only a LISTED scheme, or any word before `://`
        other = samples.DRAFT_OTHER_PHONE.replace(" ", "")
        for body in ("Call tel:%s now" % other, "Call TEL:+447700900123", "open fax:0161", "see mailto:x", "see sms:hello",
                     "see javascript:alert(1)", "see data:text/plain,hi", "see file:notes", "see ftp:host", "see http:host",
                     "see zoommtg://join", "see whatever://thing", "x-app://open", "Tel:%s or tel:%s" % (phone, other)):
            with self.subTest(body=body):
                self.assert_refused(self.check(body=body), "draft-url")
        self.assert_refused(self.check(body="see //evil/x"), "draft-url")               # C4: the scheme left out
        self.assert_refused(self.check(body="see //evil.example.net/x"), "draft-url", "draft-bare-host")
        self.assert_refused(self.check(body="see 127.1 now"), "draft-bare-host")        # C4: the loopback written short
        self.assert_refused(self.check(body="see 127.0.1/admin"), "draft-bare-host")
        # a label and a colon against a word is ordinary writing; so is a label before OUR address or an approved number
        for body in ("Status:shipped", "Note:closed", "Size:M", "Re:Order", "AW:Bestellung", 'He said:"yes"', "Mon:9-5",
                     "Email:%s" % samples.DRAFT_OWN_ADDRESS, "E-mail: %s" % samples.DRAFT_OWN_ADDRESS,
                     "Tel:%s" % samples.DRAFT_PHONE, "Tel:%s" % phone, "Fax:%s." % samples.DRAFT_PHONE,
                     "see zoommtg:join", "see whatever:thing", "It costs 127.10 in total, or 127.15.", "and/or // a note"):
            with self.subTest(body=body):
                self.assert_accepted(self.check(body=body), body=body)
        self.assert_refused(self.check(body="Email:someone@example.net"), "draft-address")
        self.assert_refused(self.check(body="mailto:%s" % samples.DRAFT_OWN_ADDRESS), "draft-url")
        for body in ("Note: we are closed on Sunday. Tel: %s" % samples.DRAFT_PHONE, "We open at 9:30 and close at 17:00.",
                     "Open 09:00-17:30, Monday to Friday.", "Yes: 9 to 5.", "Re: your order", "Ratio 3:1 or a:b? No, C: is a drive.",
                     "Tracking: %s." % samples.DRAFT_VIEW_TRACKING, "Hours::see below", "Dear Ann:\nthank you."):
            with self.subTest(body=body):
                self.assert_accepted(self.check(body=body), body=body)

    def test_the_doctor_warns_when_the_snapshot_of_top_level_domains_is_old(self):
        import datetime
        import mail_scan
        taken = datetime.date(*(int(part) for part in mail_lists.DRAFT_TLDS_SNAPSHOT_DATE.split("-")))
        self.assertEqual(mail_scan.tlds_age_days(taken), 0)
        fresh = mail_scan.doctor(self.root, taken + datetime.timedelta(days=mail_lists.DRAFT_TLDS_MAX_AGE_DAYS))
        self.assertEqual((fresh.tlds_stale, fresh.tlds_age_days), (False, 366))
        old = mail_scan.doctor(self.root, taken + datetime.timedelta(days=mail_lists.DRAFT_TLDS_MAX_AGE_DAYS + 1))
        self.assertTrue(old.tlds_stale)
        self.assertIn(old.level, ("warn", "fail"))
        self.assertGreaterEqual(mail_scan.doctor(self.root).tlds_age_days, 0)


# --------------------------------------------------------------------------------------
# Bounded work, the lists and the module
# --------------------------------------------------------------------------------------

class Bounds(DraftCase):
    def test_a_draft_built_to_be_slow_is_judged_quickly(self):
        cap = mail_lists.DRAFT_BODY_MAX_CHARS
        shapes = {
            "letters": "a" * cap, "digits": "7" * cap, "phones": (PHONE + " ") * (cap // 14),
            "labels": "a." * (cap // 2), "digit labels": "1." * (cap // 2),
            "hyphens": "a-" * (cap // 2), "at signs": "@" * cap, "spaced digits": "1 " * (cap // 2),
            "brackets": "1" + "(" * (cap - 2) + "1", "schemes": "a:" * (cap // 2), "slashes": "://" * (cap // 3),
            "allowed hosts": (SITE + "/") * (cap // (len(SITE) + 1)), "angles": "<" * cap, "brackets 2": "](" * (cap // 2),
            "ampersands": "&#" * (cap // 2), "lines": "1\n" * (cap // 2), "dots": "." * cap,
            "long label": "a" * (cap - 12) + ".example.net", "marks": ("a" + chr(0x0301)) * (cap // 2),
            "wide": samples.full_width("a.b" * (cap // 3)), "oversize": "a.b@c://1 " * 400_000,
        }
        for label, body in shapes.items():
            with self.subTest(label=label):
                started = time.monotonic()
                result = self.check(body=body)
                self.assertLess(time.monotonic() - started, 5.0)
                self.assertIn(result.result, (ACCEPT, REFUSE))
        self.assert_refused(self.check(body=shapes["long label"]), "draft-bare-host")
        self.assert_refused(self.check(body=shapes["lines"]), "draft-digit-run")

    def test_the_draft_vocabulary_of_the_lists(self):
        self.assertEqual(mail_lists.LISTS_VERSION, "10")
        required = ("com net org info biz io co app dev ai me tv xyz online site shop store tech cloud link "
                    "click top zip mov page email live pro gov edu mil int").split()
        self.assertEqual(set(required) - set(mail_lists.DRAFT_TLDS), set())
        # fix round 1: the names are a dated snapshot of the IANA root zone, not a list made by hand
        self.assertGreater(len(mail_lists.DRAFT_TLDS_SNAPSHOT), 1400)
        self.assertEqual(len(set(mail_lists.DRAFT_TLDS_SNAPSHOT)), len(mail_lists.DRAFT_TLDS_SNAPSHOT))
        self.assertEqual(list(mail_lists.DRAFT_TLDS_SNAPSHOT), sorted(mail_lists.DRAFT_TLDS_SNAPSHOT))
        for name in mail_lists.DRAFT_TLDS_SNAPSHOT:
            self.assertRegex(name, r"^[a-z0-9-]{2,63}$")
        self.assertRegex(mail_lists.DRAFT_TLDS_SNAPSHOT_DATE, r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
        self.assertRegex(mail_lists.DRAFT_TLDS_SNAPSHOT_VERSION, r"^20[0-9]{8}$")
        self.assertEqual(mail_lists.DRAFT_TLDS_SNAPSHOT_VERSION[:8], mail_lists.DRAFT_TLDS_SNAPSHOT_DATE.replace("-", ""))
        for name in ("ltd", "chat", "tools", "community", "limited", "wiki", "top", "icu", "cfd", "sbs"):
            self.assertIn(name, mail_lists.DRAFT_TLDS)       # review C F7: hosts the hand-made list let through
        self.assertEqual(len(set(mail_lists.DRAFT_TLDS_COUNTRY)), len(mail_lists.DRAFT_TLDS_COUNTRY))
        self.assertGreaterEqual(len(mail_lists.DRAFT_TLDS_COUNTRY), 245)
        for code in mail_lists.DRAFT_TLDS_COUNTRY:
            self.assertRegex(code, r"^[a-z]{2}$")
        for code in ("uk", "us", "de", "fr", "it", "io", "ru", "cn", "tk", "ly", "gg", "to", "is", "in", "me"):
            self.assertIn(code, mail_lists.DRAFT_TLDS)
        for word in ("pdf", "js", "regards", "smith", "example", "test", "invalid", "docx", "txt", "html", "png"):
            self.assertNotIn(word, mail_lists.DRAFT_TLDS)
        self.assertEqual(mail_lists.DRAFT_TLDS, frozenset(mail_lists.DRAFT_TLDS_SNAPSHOT + mail_lists.DRAFT_TLDS_SPECIAL))
        self.assertEqual(set(mail_lists.DRAFT_TLDS_GENERIC) | set(mail_lists.DRAFT_TLDS_COUNTRY),
                         set(mail_lists.DRAFT_TLDS_SNAPSHOT))
        self.assertEqual((mail_lists.DRAFT_TRUNK_ZERO, mail_lists.DRAFT_DATE_YEARS, mail_lists.DRAFT_WWW_LABEL,
                          mail_lists.DRAFT_JOINER_CODE_POINT), ("(0)", (1900, 2100), "www.", 0x200D))
        self.assertEqual(tuple(p.pattern for p in mail_lists.DRAFT_DATES), mail_lists.DRAFT_DATE_PATTERNS)
        self.assertEqual(mail_lists.DRAFT_AMOUNT_RANGE.pattern, mail_lists.DRAFT_AMOUNT_RANGE_PATTERN)
        self.assertEqual(mail_lists.REFUSE_RULE_IDS[-3:],
                         ("draft-control-characters", "draft-catalog-missing", "draft-knowledge-pack"))
        self.assertEqual([hex(ord(char)) for char in mail_lists.DRAFT_DOT_LOOKALIKES],
                         ["0xb7", "0x2022", "0x2219", "0x22c5", "0x30fb", "0x6d4", "0x589",
                          "0x2e31", "0x2e33", "0x2027", "0x25e6", "0xa78f", "0x16eb", "0x701", "0x702", "0x2e3c",
                          "0xa4ff"])
        self.assertEqual([hex(ord(char)) for char in mail_lists.DRAFT_THIN_SPACES],
                         ["0x2006", "0x2008", "0x2009", "0x200a", "0x202f", "0x205f"])
        self.assertEqual([hex(ord(char)) for char in mail_lists.DRAFT_DASH_LOOKALIKES], ["0x2212"])
        self.assertEqual(mail_lists.DRAFT_URL_SCHEMES, ("http", "https"))
        for scheme in ("mailto", "javascript", "data", "vbscript", "file", "http", "https", "tel"):
            self.assertIn(scheme, mail_lists.DRAFT_SCHEMES_NO_SLASHES)
        self.assertEqual((mail_lists.DRAFT_PHONE_GAP_CHARS, mail_lists.DRAFT_CANARY_SQUEEZED_MIN_CHARS,
                          mail_lists.KNOWLEDGE_PACK_MAX_BYTES), (2, 6, 2_000_000))
        self.assertEqual(mail_lists.DRAFT_HOST.pattern, mail_lists.DRAFT_HOST_PATTERN)
        self.assertEqual(mail_lists.DRAFT_IPV4.pattern, mail_lists.DRAFT_IPV4_PATTERN)
        self.assertEqual(tuple(p.pattern for p in mail_lists.DRAFT_MARKUP), mail_lists.DRAFT_MARKUP_PATTERNS)
        self.assertEqual(mail_lists.DRAFT_ALLOWED_URL_TAIL.pattern, mail_lists.DRAFT_ALLOWED_URL_TAIL_PATTERN)
        self.assertEqual(sorted(mail_lists.DRAFT_TOKEN_TRAILING), sorted(".,;:!?)]}>\"'"))
        self.assertEqual(sorted(mail_lists.DRAFT_ADDRESS_LEADING), sorted("([{<\"'"))

    def test_a_chain_of_labels_is_a_host_when_a_later_label_is_a_top_level_domain(self):
        def hosts(text):
            return [text[start:end] for start, end in draft_check._host_spans(text)]

        self.assertEqual(hosts("see example.com, _under.example.io, -dash.io- and x.xn--p1ai, shop.example.co.uk"),
                         ["example.com", "under.example.io", "dash.io-", "x.xn--p1ai", "shop.example.co.uk"])
        self.assertEqual(hosts("evil.com.Thanks evil.com-x evil.co1 report.zip Evil.IO a.b.c.d.e.f.g.h.i.j.k.com"),
                         ["evil.com.Thanks", "evil.com-x", "evil.co1", "report.zip", "Evil.IO",
                          "a.b.c.d.e.f.g.h.i.j.k.com"])
        self.assertEqual(hosts("x.%s%s" % (chr(0x0440), chr(0x0444))), ["x.%s%s" % (chr(0x0440), chr(0x0444))])
        for text in ("Thanks. Regards", "at 9 a.m. and 5 p.m.", "wait... what", "12.30pm", "No.12", "1.5kg", "U.S.A.",
                     "invoice.pdf", "Thanks.Regards", "Mr.Smith", "Node.js", "e.g. this", "v1.2", "3.14", "3.5mm", "a.b",
                     "It.was", "io.thanks", "evil.example", "host.test", "report.v2.docx"):
            self.assertEqual(hosts(text), [], text)
        # names the hand-made list of the first build did not hold (review C F7)
        self.assertEqual(hosts("evil.community evil.ltd/login evil.chat evil.tools"),
                         ["evil.community", "evil.ltd", "evil.chat", "evil.tools"])
        # the first label is never the top-level domain; a country code after a full stop is one
        self.assertEqual(hosts("done.It and ok.In and com.thanks"), ["done.It", "ok.In"])
        quad = mail_lists.DRAFT_IPV4
        self.assertEqual(quad.findall("at 203.0.113.5 or 10.0.0.1/8, not 1.2.3 or 1.2.3.4.5 or 12.10.2026"),
                         ["203.0.113.5", "10.0.0.1"])

    def test_fold_reads_a_text_as_a_person_does(self):
        fold = draft_check.fold
        self.assertEqual(fold("plain text 123"), "plain text 123")
        self.assertEqual(fold(samples.full_width("Abc.123")), "Abc.123")
        # fix round 2 (C3): the ideographic full stop ends a sentence; it is not read as a host dot
        self.assertEqual(fold("a" + chr(0x3002) + "b" + chr(0xFF61) + "c" + chr(0xB7) + "d"),
                         "a" + chr(0x3002) + "b" + chr(0x3002) + "c.d")
        self.assertEqual(fold("1" + chr(0x2013) + "2" + chr(0x2014) + "3" + chr(0x2212) + "4" + chr(0x2010) + "5"),
                         "1-2-3-4-5")
        self.assertEqual(fold(chr(0x0661) + chr(0x06F2) + chr(0x0969) + chr(0x1D7D2)), "1234")
        self.assertEqual(fold("a" + chr(0xA0) + "b" + chr(0x2003) + "c" + chr(0x3000) + "d" + chr(0x1680) + "e"),
                         "a b c d e")
        self.assertEqual(fold("x" + chr(0x0301) + "y" + chr(0x034F) + "z"), "xyz")
        self.assertEqual(fold("caf" + chr(0xE9)), "caf" + chr(0xE9))
        self.assertEqual(fold("a\r\nb\rc" + chr(0x2028) + "d" + chr(0x85) + "e"), "a\nb\nc\nd\ne")
        self.assertEqual(fold("a\tb" + chr(0x2009) + "c"), "a b c")
        self.assertEqual(draft_check.digit_reference("a 12 34\n56 b", "x 9-9"), "|1234|123456|56|99|")


class Module(unittest.TestCase):
    ALLOWED = {"__future__", "datetime", "hashlib", "hmac", "ipaddress", "re", "unicodedata", "typing", "mail_lists",
               "mail_reuse", "mail_state"}
    FORBIDDEN = {"smtplib", "imaplib", "poplib", "ftplib", "socket", "ssl", "http", "asyncio", "subprocess",
                 "multiprocessing", "ctypes", "urllib", "shutil", "tempfile", "pickle", "os", "json", "mail_parse",
                 "mail_view", "mail_frame", "mail_rules", "mail_sender", "mail_scan"}

    def tree(self):
        return ast.parse((SCRIPTS / "draft_check.py").read_text(encoding="utf-8"))

    def test_the_draft_check_imports_only_the_standard_library_and_its_callees(self):
        imported = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported - self.ALLOWED, set())
        self.assertEqual(imported & self.FORBIDDEN, set())
        self.assertTrue({"mail_lists", "mail_reuse", "mail_state"} <= imported)
        for name in imported - {"mail_lists", "mail_reuse", "mail_state"}:
            self.assertIn(name, sys.stdlib_module_names)

    def test_the_draft_check_opens_one_file_for_reading_and_calls_nothing_dangerous(self):
        opens = []
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = node.func.attr
                self.assertFalse(name in ("system", "popen", "fork", "remove", "unlink", "rename", "replace_file",
                                          "mkdir", "makedirs", "write") or name.startswith(("exec", "spawn")), name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ("eval", "exec", "compile", "__import__", "print"))
                if node.func.id == "open":
                    opens.append(node)
        # the knowledge pack, read as bytes
        self.assertEqual(len(opens), 1)
        self.assertEqual([ast.literal_eval(arg) for arg in opens[0].args[1:]], ["rb"])

    def test_importing_the_draft_check_has_no_side_effects(self):
        home = tempfile.mkdtemp(prefix="mailscan-import-")
        self.addCleanup(shutil.rmtree, home, True)
        code = ("import os, sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "import draft_check\n"
                "print(sorted(os.listdir(os.environ['HOME'])))\n")
        environment = {name: value for name, value in os.environ.items() if name != mail_state.ENV_ROOT}
        environment.update(HOME=home, USERPROFILE=home, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], capture_output=True, text=True,
                              env=environment, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(done.stdout.splitlines(), ["[]"])
        self.assertEqual(os.listdir(home), [])

    def test_every_refusal_rule_of_the_module_is_a_rule_of_the_lists(self):
        named = {value for name, value in vars(draft_check).items() if name.startswith("RULE_")}
        self.assertEqual(named, set(mail_lists.REFUSE_RULE_IDS))
        for rule_id in named:
            self.assertEqual(mail_lists.RULES[rule_id].rule_class, mail_lists.CLASS_REFUSE)

    def test_the_sources_are_ascii_with_escapes_for_the_rest(self):
        for path in (SCRIPTS / "draft_check.py", SCRIPTS / "mail_lists.py", HERE / "test_draft_check.py",
                     HERE / "samples.py"):
            data = path.read_bytes()
            self.assertTrue(data.isascii(), path.name)
            self.assertNotIn(b"\r", data, path.name)

    def test_the_manifest_lists_the_draft_builders(self):
        with open(HERE / "manifest.json", "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest, samples.manifest())
        builders = manifest["builders"]["mail-draft-check"]
        self.assertEqual(len(builders), 13)       # fix round 3: draft_round_three_texts
        for name in builders:
            self.assertTrue(callable(getattr(samples, name)), name)


if __name__ == "__main__":
    unittest.main()
