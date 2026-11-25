#!/usr/bin/env python3
"""mail-scan -- test_mail_parse.py (#351 WP-1b, component mail-parse).

One raw message, read under bounds and a written part-selection rule.

    TS-PARSE-01  an alternative with two HTML parts yields the named gap and the last HTML part
    TS-PARSE-02  a related message exposes only its root part; the others are resources
    TS-PARSE-03  an unsupported charset yields charset-unsupported, in a body and in a header
    TS-PARSE-04  a message over each bound is refused with the bound named
    TS-PARSE-05  two From headers, a group-syntax From and a two-mailbox From each yield
                 header-ambiguous

Also: one test per bound, per header that must be single and per message shape; the three
selection rules; every gap with the class the design table gives (THE TABLE IS WRITTEN OUT
HERE as this file's own data); each allowlisted charset; the header facts; the attachment
and link inventories; and a marker string in every field a sender controls, which must
reach no recordable field.

Every message comes from `samples.py`, which builds it at call time. Nothing here stores or
reads a message file.

Stdlib unittest; pytest only runs it.
"""
from __future__ import annotations

import ast
import email.policy
import html.parser
import importlib.util
import json
import random
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mail_lists  # noqa: E402
import mail_parse  # noqa: E402
import mail_reuse  # noqa: E402


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

MARKER = "Zq7Marker9Xk"
E_ACUTE = chr(0xE9)
REPLACED = chr(0xFFFD)       # the replacement character

# gap -> (class, reply effect), as the design table states them, for the gaps a parse can
# report. Compared with what the parser attaches to each gap it raises.
DESIGN_PARSE_GAPS = {
    "charset-unsupported": ("block", "held"),
    "structure-over-bound": ("block", "held"),
    "parse-defect": ("block", "held"),
    "alternative-ambiguous": ("block", "held"),
    "related-root-invalid": ("block", "held"),
    "nested-message": ("caution", "held"),
    "alternative-duplicate-html": ("caution", "held"),
    "alternative-other-text": ("caution", "held"),
    "multipart-unknown": ("caution", "held"),
}
# The headers the design says must be single.
DESIGN_SINGLE_HEADERS = ("from", "subject", "reply-to", "content-type", "return-path", "auto-submitted")
DESIGN_CHARSETS = ("utf-8", "us-ascii", "iso-8859-1", "iso-8859-15", "windows-1252")

ITEM_ID = re.compile(r"^[pal][1-9][0-9]*$")
MEDIA_WORDS = (set(mail_lists.COMMON_MEDIA_TYPES) | set(mail_lists.DANGEROUS_MEDIA_TYPES)
               | set(mail_lists.GENERIC_MEDIA_TYPES)
               | {media for row in mail_lists.SIGNATURES for media in row.media_types}
               | {main + "/other" for main in mail_lists.MEDIA_MAIN_TYPES} | {"other"})


def gaps(parsed):
    """(name, detail) -> count"""
    return {(gap.name, gap.detail): gap.count for gap in parsed.gaps}


def gap_names(parsed):
    return sorted({gap.name for gap in parsed.gaps})


def ambiguities(parsed):
    return sorted((entry.header, entry.reason) for entry in parsed.header_ambiguous)


def texts(parsed):
    return [part.text for part in parsed.selected]


def roles(parsed):
    return [(part.media_type, part.role) for part in parsed.parts]


def record_text(parsed):
    return json.dumps(mail_parse.recordable(parsed), sort_keys=True)


class ParseCase(unittest.TestCase):
    def parse(self, raw, **bounds):
        chosen = mail_parse.DEFAULT_BOUNDS._replace(**bounds) if bounds else mail_parse.DEFAULT_BOUNDS
        parsed = mail_parse.parse(raw, chosen)
        self.assert_recordable_vocabulary(parsed)
        return parsed

    def assert_clean(self, parsed):
        self.assertEqual(parsed.gaps, ())
        self.assertEqual(parsed.header_ambiguous, ())
        self.assertEqual(parsed.over_bound, "")

    def assert_recordable_vocabulary(self, parsed):
        """Every recordable value is an id, a number, a boolean or a word of a fixed list."""
        data = mail_parse.recordable(parsed)
        self.assertEqual(sorted(data), ["attachment_only", "attachments", "gaps", "header_ambiguous",
                                        "headers", "links", "over_bound", "parts", "selected"])
        self.assertIn(data["over_bound"], ("",) + mail_lists.PARSE_BOUND_NAMES)
        self.assertIsInstance(data["attachment_only"], bool)
        for gap in data["gaps"]:
            self.assertEqual(sorted(gap), ["count", "detail", "gap_class", "name", "reply_effect"])
            self.assertIn(gap["name"], mail_parse.PARSE_GAPS)
            self.assertIn(gap["gap_class"], mail_lists.GAP_CLASSES)
            self.assertIn(gap["reply_effect"], mail_lists.REPLY_EFFECTS)
            self.assertIn(gap["detail"], mail_lists.GAP_DETAILS)
            self.assertGreater(gap["count"], 0)
        for entry in data["header_ambiguous"]:
            self.assertEqual(sorted(entry), ["count", "header", "reason"])
            self.assertIn(entry["header"], mail_lists.AMBIGUOUS_HEADER_NAMES)
            self.assertIn(entry["reason"], mail_lists.HEADER_REASONS)
            self.assertGreater(entry["count"], 0)
        for part in data["parts"]:
            self.assertEqual(sorted(part), ["depth", "media_type", "part_id", "role"])
            self.assertRegex(part["part_id"], ITEM_ID)
            self.assertIn(part["media_type"], MEDIA_WORDS)
            self.assertIn(part["role"], mail_lists.PART_ROLES)
            self.assertIsInstance(part["depth"], int)
        for item in data["attachments"]:
            self.assertEqual(sorted(item), ["attachment_id", "extension_class", "media_type", "part_id",
                                            "role", "signature", "size"])
            self.assertRegex(item["attachment_id"], ITEM_ID)
            self.assertRegex(item["part_id"], ITEM_ID)
            self.assertIn(item["role"], mail_lists.ATTACHMENT_ROLES)
            self.assertIn(item["media_type"], MEDIA_WORDS)
            self.assertIn(item["extension_class"], mail_lists.EXTENSION_CLASSES)
            self.assertIn(item["signature"], mail_lists.SIGNATURE_NAMES + (mail_lists.SIGNATURE_NONE,))
            self.assertIsInstance(item["size"], int)
        for link in data["links"]:
            self.assertEqual(sorted(link), ["flags", "kind", "link_id", "number", "occurrence", "part_id"])
            self.assertRegex(link["link_id"], ITEM_ID)
            self.assertRegex(link["part_id"], ITEM_ID)
            self.assertIn(link["kind"], mail_lists.LINK_KINDS)
            self.assertLessEqual(set(link["flags"]), set(mail_lists.LINK_FLAGS))
            self.assertIsInstance(link["number"], int)
            self.assertIsInstance(link["occurrence"], int)
        for part in data["selected"]:
            self.assertEqual(sorted(part), ["charset", "part_id", "replaced", "subtype"])
            self.assertRegex(part["part_id"], ITEM_ID)
            self.assertIn(part["subtype"], mail_lists.SELECTED_SUBTYPES)
            self.assertIn(part["charset"], mail_lists.CHARSET_ALLOWLIST + ("",))
            self.assertIsInstance(part["replaced"], int)
        headers = data["headers"]
        self.assertEqual(sorted(headers), ["authentication_results_count", "auto_response_suppress",
                                           "auto_submitted", "from_name_irregular", "list_id_present",
                                           "list_unsubscribe_present", "precedence", "reply_to_present",
                                           "return_path"])
        for name in ("auto_response_suppress", "from_name_irregular", "list_id_present",
                     "list_unsubscribe_present", "reply_to_present"):
            self.assertIsInstance(headers[name], bool)
        self.assertIsInstance(headers["authentication_results_count"], int)
        self.assertIn(headers["auto_submitted"], mail_lists.AUTO_SUBMITTED_VALUES)
        self.assertIn(headers["return_path"], mail_lists.RETURN_PATH_VALUES)
        self.assertIn(headers["precedence"], mail_lists.PRECEDENCE_VALUES)
        json.dumps(data)


# --------------------------------------------------------------------------------------
# Ordinary messages
# --------------------------------------------------------------------------------------

class OrdinaryMessages(ParseCase):
    def test_a_plain_message_parses_with_no_gap(self):
        parsed = self.parse(samples.plain_message())
        self.assert_clean(parsed)
        self.assertFalse(parsed.attachment_only)
        self.assertEqual([(p.part_id, p.subtype, p.charset, p.replaced) for p in parsed.selected],
                         [("p1", "plain", "utf-8", 0)])
        self.assertEqual(texts(parsed), ["Hello,\r\ncan you tell me your opening hours?\r\n"])
        self.assertEqual(roles(parsed), [("text/plain", "selected")])
        self.assertEqual(parsed.attachments, ())
        self.assertEqual(parsed.links, ())
        self.assertEqual(parsed.headers.from_address, samples.SENDER_ADDRESS)
        self.assertEqual(parsed.headers.subject, "Hello")

    def test_an_ordinary_html_message_parses_with_no_gap(self):
        parsed = self.parse(samples.html_message())
        self.assert_clean(parsed)
        self.assertEqual([p.subtype for p in parsed.selected], ["html"])
        self.assertIn("Hello there", texts(parsed)[0])

    def test_an_ordinary_alternative_parses_with_no_gap(self):
        parsed = self.parse(samples.ordinary_alternative_message())
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["<p>HTML-BODY</p>"])
        self.assertEqual(roles(parsed), [("multipart/alternative", "container"),
                                         ("text/plain", "unselected"), ("text/html", "selected")])

    def test_raw_that_is_not_bytes_is_a_type_error(self):
        for value in ("text", None, 5, ["a"]):
            with self.subTest(value=repr(value)):
                with self.assertRaises(TypeError):
                    mail_parse.parse(value)

    def test_a_bytearray_and_a_memoryview_are_read_like_bytes(self):
        raw = samples.plain_message()
        expected = mail_parse.parse(raw)
        self.assertEqual(mail_parse.parse(bytearray(raw)), expected)
        self.assertEqual(mail_parse.parse(memoryview(raw)), expected)

    def test_parsing_twice_gives_the_same_result(self):
        for raw in (samples.plain_message(), samples.marker_message(MARKER), samples.html_links_message()):
            self.assertEqual(mail_parse.parse(raw), mail_parse.parse(raw))


# --------------------------------------------------------------------------------------
# TS-PARSE-04: bounds
# --------------------------------------------------------------------------------------

class Bounds(ParseCase):
    def assert_over(self, parsed, bound):
        """Refused with the bound named, and nothing else read."""
        self.assertEqual(parsed.over_bound, bound)
        self.assertEqual(gaps(parsed), {("structure-over-bound", bound): 1})
        self.assertEqual(parsed.gaps[0].gap_class, "block")
        self.assertEqual(parsed.gaps[0].reply_effect, "held")
        self.assertEqual(parsed.selected, ())
        self.assertEqual(parsed.parts, ())
        self.assertEqual(parsed.attachments, ())
        self.assertEqual(parsed.links, ())
        self.assertEqual(parsed.header_ambiguous, ())
        self.assertFalse(parsed.attachment_only)
        self.assertIsNone(parsed.headers.from_address)
        self.assertIsNone(parsed.headers.subject)
        self.assertEqual(parsed.headers.authentication_results, ())

    def test_the_default_bounds_are_those_of_the_lists(self):
        self.assertEqual(tuple(mail_parse.DEFAULT_BOUNDS),
                         (mail_lists.MAX_BYTES_DEFAULT, mail_lists.MAX_MIME_DEPTH, mail_lists.MAX_PARTS,
                          mail_lists.MAX_HEADER_LINES, mail_lists.MAX_HEADER_LINE_BYTES, mail_lists.MAX_LINKS,
                          mail_lists.MAX_MIME_HEADER_BYTES, mail_lists.SCAN_SECONDS))
        self.assertEqual((mail_lists.MAX_MIME_HEADER_BYTES, mail_lists.SCAN_SECONDS), (1000, 10.0))
        self.assertEqual(tuple(mail_parse.DEFAULT_BOUNDS), (2000000, 8, 50, 300, 8192, 1000, 1000, 10.0))

    def test_the_byte_bound(self):
        self.assert_clean(self.parse(samples.sized_message(5000), max_bytes=5000))
        self.assert_over(self.parse(samples.sized_message(5001), max_bytes=5000), "bytes")

    def test_the_byte_bound_is_checked_before_anything_is_parsed(self):
        with mock.patch.object(mail_parse.email.parser, "BytesParser") as parser:
            parsed = mail_parse.parse(samples.sized_message(5001), mail_parse.DEFAULT_BOUNDS._replace(max_bytes=5000))
            parser.assert_not_called()
        self.assert_over(parsed, "bytes")
        self.assert_over(self.parse(b"x" * (mail_lists.MAX_BYTES_DEFAULT + 1)), "bytes")

    def test_the_depth_bound(self):
        parsed = self.parse(samples.nested_depth_message(8))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["DEEP-BODY"])
        self.assertEqual(max(part.depth for part in parsed.parts), 8)
        self.assert_over(self.parse(samples.nested_depth_message(9)), "depth")

    def test_nesting_beyond_what_the_standard_parser_can_follow_is_the_depth_bound(self):
        self.assert_over(self.parse(samples.deeply_nested_message()), "depth")

    def test_the_part_bound(self):
        parsed = self.parse(samples.many_parts_message(50))
        self.assert_clean(parsed)
        self.assertEqual(len(parsed.parts), 50)
        self.assert_over(self.parse(samples.many_parts_message(51)), "parts")

    def test_the_parts_of_a_nested_message_count_against_the_bounds(self):
        inner = samples.mail_multipart("mixed", [samples.mail_part("text/plain", "x", "utf-8")] * 4)
        raw = samples.mail_message(samples.mail_multipart("mixed", [
            samples.mail_part("text/plain", "BODY", "utf-8"), samples.mail_part("message/rfc822", inner)]))
        self.assertEqual(len(self.parse(raw).parts), 3)
        self.assert_over(self.parse(raw, max_parts=7), "parts")
        self.assertEqual(self.parse(raw, max_parts=8).over_bound, "")
        self.assert_over(self.parse(raw, max_depth=3), "depth")
        self.assertEqual(self.parse(raw, max_depth=4).over_bound, "")

    def test_the_header_line_bound(self):
        self.assert_clean(self.parse(samples.many_headers_message(mail_lists.MAX_HEADER_LINES)))
        self.assert_over(self.parse(samples.many_headers_message(mail_lists.MAX_HEADER_LINES + 1)), "header-lines")

    def test_a_folded_header_is_one_header_line(self):
        self.assert_clean(self.parse(samples.many_headers_message(mail_lists.MAX_HEADER_LINES, folded=40)))

    def test_the_header_length_bound(self):
        self.assert_clean(self.parse(samples.long_header_message(mail_lists.MAX_HEADER_LINE_BYTES)))
        self.assert_over(self.parse(samples.long_header_message(mail_lists.MAX_HEADER_LINE_BYTES + 1)), "header-length")

    def test_the_header_length_is_measured_after_unfolding(self):
        self.assert_clean(self.parse(samples.long_header_message(mail_lists.MAX_HEADER_LINE_BYTES, folded=True)))
        self.assert_over(self.parse(samples.long_header_message(mail_lists.MAX_HEADER_LINE_BYTES + 1, folded=True)), "header-length")

    def test_the_header_bounds_hold_for_the_headers_of_a_part(self):
        self.assert_clean(self.parse(samples.long_header_message(mail_lists.MAX_HEADER_LINE_BYTES, in_part=True)))
        self.assert_over(self.parse(samples.long_header_message(mail_lists.MAX_HEADER_LINE_BYTES + 1, in_part=True)), "header-length")
        part = samples.mail_part("text/plain", "x", "utf-8", headers=[("X-%d" % n, "v")
                                                                    for n in range(mail_lists.MAX_HEADER_LINES)])
        self.assert_over(self.parse(samples.mail_message(samples.mail_multipart("mixed", [part]))), "header-lines")

    def test_the_link_bound(self):
        for subtype in ("html", "plain"):
            with self.subTest(subtype=subtype):
                parsed = self.parse(samples.many_links_message(mail_lists.MAX_LINKS, subtype))
                self.assert_clean(parsed)
                self.assertEqual(len(parsed.links), mail_lists.MAX_LINKS)
                self.assert_over(self.parse(samples.many_links_message(mail_lists.MAX_LINKS + 1, subtype)), "links")

    def test_a_message_over_a_bound_is_not_parsed_further(self):
        # Two From headers and an unsupported charset: neither is reported, because nothing
        # beyond the bound was read.
        entity = samples.mail_multipart("mixed", [samples.mail_multipart("mixed", [
            samples.mail_part("text/plain", "x", "utf-7")])])
        raw = samples.mail_message(entity, headers=[("From", "second@example.net")])
        self.assertEqual(ambiguities(self.parse(raw)), [("from", "repeated")])
        self.assert_over(self.parse(raw, max_depth=2), "depth")
        self.assert_over(self.parse(raw, max_parts=2), "parts")
        self.assert_over(self.parse(raw, max_header_lines=3), "header-lines")
        self.assert_over(self.parse(raw, max_header_line_bytes=20), "header-length")
        self.assert_over(self.parse(raw, max_bytes=20), "bytes")

    def test_no_header_value_is_interpreted_before_the_bounds_are_checked(self):
        raw = samples.mail_message(sender="ann@example.org " + "(" * 4500 + ")" * 4500)
        with mock.patch.object(mail_parse._Reader, "header_facts", side_effect=AssertionError("read")) as facts:
            self.assert_over(mail_parse.parse(raw), "header-length")
            facts.assert_not_called()

    def test_every_bound_name_is_one_the_lists_name(self):
        self.assertEqual(mail_lists.PARSE_BOUND_NAMES,
                         ("bytes", "depth", "parts", "header-lines", "header-length", "links", "time"))
        self.assertEqual(mail_lists.PARSE_BOUND_NAMES[:5], mail_lists.BOUND_NAMES)


# --------------------------------------------------------------------------------------
# TS-PARSE-05: headers that must be single
# --------------------------------------------------------------------------------------

class SingleHeaders(ParseCase):
    def from_case(self, label):
        return self.parse(samples.from_message(samples.from_values()[label]))

    def assert_no_sender(self, parsed):
        self.assertIsNone(parsed.headers.from_name)
        self.assertIsNone(parsed.headers.from_address)
        self.assertIsNone(parsed.headers.from_local)
        self.assertIsNone(parsed.headers.from_domain)

    def test_two_from_headers_are_header_ambiguous(self):
        for label in ("two-headers", "same-header-twice"):
            with self.subTest(label=label):
                parsed = self.from_case(label)
                self.assertEqual(ambiguities(parsed), [("from", "repeated")])
                self.assert_no_sender(parsed)

    def test_a_missing_from_is_header_ambiguous(self):
        parsed = self.from_case("missing")
        self.assertEqual(ambiguities(parsed), [("from", "missing")])
        self.assert_no_sender(parsed)

    def test_a_group_syntax_from_is_header_ambiguous(self):
        for label in ("group", "empty-group"):
            with self.subTest(label=label):
                parsed = self.from_case(label)
                self.assertEqual(ambiguities(parsed), [("from", "group")])
                self.assert_no_sender(parsed)

    def test_a_two_mailbox_from_is_header_ambiguous(self):
        parsed = self.from_case("two-mailboxes")
        self.assertEqual(ambiguities(parsed), [("from", "mailboxes")])
        self.assert_no_sender(parsed)

    def test_a_from_with_no_mailbox_is_header_ambiguous(self):
        for label in ("empty", "no-domain", "null-address"):
            with self.subTest(label=label):
                parsed = self.from_case(label)
                self.assertEqual(ambiguities(parsed), [("from", "mailboxes")])
                self.assert_no_sender(parsed)

    def test_a_display_name_with_a_comma_is_two_mailboxes(self):
        parsed = self.parse(samples.from_message([b"Example, Ann <ann@example.org>"]))
        self.assertEqual(ambiguities(parsed), [("from", "mailboxes")])
        self.assert_no_sender(parsed)

    def test_a_repeated_subject_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_header_message("Subject"))
        self.assertEqual(ambiguities(parsed), [("subject", "repeated")])
        self.assertIsNone(parsed.headers.subject)

    def test_a_repeated_reply_to_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_header_message("Reply-To"))
        self.assertEqual(ambiguities(parsed), [("reply-to", "repeated")])
        self.assertTrue(parsed.headers.reply_to_present)

    def test_a_repeated_content_type_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_header_message("Content-Type"))
        self.assertEqual(ambiguities(parsed), [("content-type", "repeated")])

    def test_a_repeated_return_path_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_header_message("Return-Path"))
        self.assertEqual(ambiguities(parsed), [("return-path", "repeated")])

    def test_a_repeated_auto_submitted_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_header_message("Auto-Submitted"))
        self.assertEqual(ambiguities(parsed), [("auto-submitted", "repeated")])
        # One of the two says the message is automatic: that is what is reported.
        self.assertEqual(parsed.headers.auto_submitted, "auto")

    def test_a_header_name_is_matched_in_any_letter_case(self):
        raw = samples.mail_message(headers=[("FROM", "second@example.net"), ("SUBJECT", "again")])
        self.assertEqual(ambiguities(self.parse(raw)), [("from", "repeated"), ("subject", "repeated")])

    def test_a_part_with_two_content_type_headers_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_part_header_message("content-type"))
        self.assertEqual(ambiguities(parsed), [("content-type", "repeated")])

    def test_a_part_with_two_transfer_encoding_headers_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_part_header_message("content-transfer-encoding"))
        self.assertEqual(ambiguities(parsed), [("content-transfer-encoding", "repeated")])

    def test_a_part_with_two_disposition_headers_is_header_ambiguous(self):
        parsed = self.parse(samples.repeated_part_header_message("content-disposition"))
        self.assertEqual(ambiguities(parsed), [("content-disposition", "repeated")])

    def test_several_ambiguous_headers_are_each_counted_by_name(self):
        raw = samples.mail_message(sender=None, headers=[
            ("Subject", "again"), ("Reply-To", "a@example.net"), ("Reply-To", "b@example.net")])
        parsed = self.parse(raw)
        self.assertEqual(ambiguities(parsed), [("from", "missing"), ("reply-to", "repeated"),
                                               ("subject", "repeated")])
        self.assertTrue(all(entry.count == 1 for entry in parsed.header_ambiguous))

    def test_a_header_repeated_in_two_parts_is_counted_twice(self):
        part = (b"Content-Type: text/plain\r\nContent-Type: text/html\r\n\r\nx")
        parsed = self.parse(samples.mail_message(samples.mail_multipart("mixed", [part, part])))
        self.assertEqual([tuple(entry) for entry in parsed.header_ambiguous], [("content-type", "repeated", 2)])

    def test_an_ambiguous_header_does_not_stop_the_rest_of_the_parse(self):
        parsed = self.from_case("two-headers")
        self.assertEqual(len(parsed.selected), 1)
        self.assertEqual(parsed.headers.subject, "Hello")

    def test_a_single_from_in_each_usual_form_is_read(self):
        for label, (value, name, address) in samples.single_from_values().items():
            with self.subTest(label=label):
                parsed = self.parse(samples.from_message([value]))
                self.assert_clean(parsed)
                self.assertEqual(parsed.headers.from_name, name)
                self.assertEqual(parsed.headers.from_address, address)
                local, _, domain = address.rpartition("@")
                self.assertEqual((parsed.headers.from_local, parsed.headers.from_domain), (local, domain))

    def test_the_single_headers_are_those_of_the_design(self):
        self.assertEqual(mail_lists.SINGLE_HEADERS, DESIGN_SINGLE_HEADERS)
        self.assertEqual(mail_lists.SINGLE_PART_HEADERS,
                         ("content-type", "content-transfer-encoding", "content-disposition"))
        self.assertEqual(set(mail_lists.AMBIGUOUS_HEADER_NAMES),
                         set(mail_lists.SINGLE_HEADERS) | set(mail_lists.SINGLE_PART_HEADERS))
        self.assertEqual(mail_lists.HEADER_REASONS, ("missing", "repeated", "group", "mailboxes", "parameter"))
        self.assertEqual(mail_lists.SINGLE_PARAMETERS, ("boundary", "charset", "start"))
        self.assertEqual(mail_lists.RULES["header-ambiguous"].rule_class, "block")


# --------------------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------------------

class Shapes(ParseCase):
    def test_a_text_message_that_is_not_multipart_is_its_own_selected_part(self):
        for subtype in ("plain", "html"):
            with self.subTest(subtype=subtype):
                parsed = self.parse(samples.mail_message(samples.mail_part("text/" + subtype, "ONLY-BODY", "utf-8")))
                self.assert_clean(parsed)
                self.assertEqual([(p.part_id, p.subtype, p.text) for p in parsed.selected],
                                 [("p1", subtype, "ONLY-BODY")])
                self.assertFalse(parsed.attachment_only)

    def test_a_one_part_text_message_is_selected_whatever_its_disposition(self):
        raw = samples.mail_message(samples.mail_part("text/plain", "ONLY-BODY", "utf-8",
                                                     disposition="attachment", filename="body.txt"))
        parsed = self.parse(raw)
        self.assertEqual(texts(parsed), ["ONLY-BODY"])
        self.assertEqual(parsed.attachments, ())

    def test_a_message_with_no_content_type_is_plain_text_in_ascii(self):
        parsed = self.parse(samples.mail_message(samples.mail_part(None, "no type at all")))
        self.assert_clean(parsed)
        self.assertEqual([(p.subtype, p.charset, p.text) for p in parsed.selected],
                         [("plain", "us-ascii", "no type at all")])

    def test_a_message_of_another_type_is_attachment_only_mail(self):
        for media_type in ("image/png", "application/pdf", "audio/mpeg", "text/calendar"):
            with self.subTest(media_type=media_type):
                parsed = self.parse(samples.non_text_message(media_type))
                self.assertTrue(parsed.attachment_only)
                self.assertEqual(parsed.selected, ())
                self.assertEqual(parsed.gaps, ())
                self.assertEqual([p.role for p in parsed.parts], ["attachment"])
                self.assertEqual([a.part_id for a in parsed.attachments], ["p1"])

    def test_a_message_that_is_only_a_nested_message_is_attachment_only_mail(self):
        parsed = self.parse(samples.top_level_nested_message())
        self.assertTrue(parsed.attachment_only)
        self.assertEqual(parsed.selected, ())
        self.assertEqual(gap_names(parsed), ["nested-message"])

    def test_a_signed_message_is_its_first_part(self):
        parsed = self.parse(samples.signed_message())
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["SIGNED-BODY"])
        self.assertEqual(roles(parsed), [("multipart/signed", "container"), ("text/plain", "selected"),
                                         ("application/pkcs7-signature", "attachment")])

    def test_only_the_first_part_of_a_signed_message_is_read(self):
        raw = samples.mail_message(samples.mail_multipart("signed", [
            samples.mail_part("text/plain", "FIRST", "utf-8"), samples.mail_part("text/plain", "SECOND", "utf-8"),
            samples.mail_multipart("mixed", [samples.mail_part("text/html", "THIRD", "utf-8")])]))
        parsed = self.parse(raw)
        self.assertEqual(texts(parsed), ["FIRST"])
        self.assertEqual([p.role for p in parsed.parts],
                         ["container", "selected", "attachment", "container", "attachment"])

    def test_a_report_is_read_as_mixed_with_the_gap_multipart_unknown(self):
        parsed = self.parse(samples.unknown_multipart_message("report"))
        self.assertEqual(gaps(parsed), {("multipart-unknown", ""): 1})
        self.assertEqual(texts(parsed), ["UNKNOWN-FIRST"])
        self.assertEqual(roles(parsed)[2], ("message/delivery-status", "attachment"))

    def test_a_digest_is_read_as_mixed_with_the_gap_multipart_unknown(self):
        parsed = self.parse(samples.unknown_multipart_message("digest"))
        self.assertEqual(gap_names(parsed), ["multipart-unknown", "nested-message"])
        self.assertEqual(texts(parsed), ["UNKNOWN-FIRST"])

    def test_an_unknown_multipart_subtype_is_read_as_mixed_with_the_gap_multipart_unknown(self):
        for subtype in ("x-thing", "parallel", "encrypted", "form-data"):
            with self.subTest(subtype=subtype):
                parsed = self.parse(samples.unknown_multipart_message(subtype))
                self.assertEqual(gaps(parsed), {("multipart-unknown", ""): 1})
                self.assertEqual(texts(parsed), ["UNKNOWN-FIRST"])

    def test_the_multipart_types_with_a_written_rule_are_not_unknown(self):
        self.assertEqual(mail_lists.MULTIPART_RULES, ("alternative", "mixed", "related", "signed"))
        for raw in (samples.mixed_message(["plain"]), samples.alternative_message(["plain"]),
                    samples.related_message("first"), samples.signed_message()):
            self.assertNotIn("multipart-unknown", gap_names(self.parse(raw)))

    def test_a_text_part_of_another_type_is_an_attachment(self):
        parsed = self.parse(samples.other_text_message())
        self.assertEqual(texts(parsed), ["BODY-TEXT"])
        self.assertEqual(roles(parsed)[2], ("text/calendar", "attachment"))
        self.assertEqual([(a.part_id, a.media_type) for a in parsed.attachments], [("p3", "text/calendar")])
        self.assertEqual(parsed.gaps, ())

    def test_a_multipart_with_no_boundary_is_not_read_as_text(self):
        parsed = self.parse(samples.broken_multipart_message())
        self.assertEqual(parsed.selected, ())
        self.assertTrue(parsed.attachment_only)
        self.assertEqual(gap_names(parsed), ["parse-defect"])

    def test_part_ids_follow_document_order(self):
        parsed = self.parse(samples.marker_message(MARKER))
        self.assertEqual([part.part_id for part in parsed.parts], ["p%d" % n for n in range(1, 12)])
        self.assertEqual([part.depth for part in parsed.parts], [1, 2, 3, 3, 3, 4, 4, 2, 2, 2, 2])
        self.assertEqual([item.attachment_id for item in parsed.attachments], ["a%d" % n for n in range(1, 7)])


# --------------------------------------------------------------------------------------
# TS-PARSE-01 and TS-PARSE-02: part selection
# --------------------------------------------------------------------------------------

class AlternativeSelection(ParseCase):
    def test_an_alternative_gives_its_last_html_part(self):
        parsed = self.parse(samples.alternative_message(["plain", "html"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["<p>PART-1</p>"])

    def test_an_alternative_gives_html_wherever_it_stands(self):
        parsed = self.parse(samples.alternative_message(["html", "plain", "plain"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["<p>PART-0</p>"])
        self.assertEqual([p.role for p in parsed.parts], ["container", "selected", "unselected", "unselected"])

    def test_an_alternative_with_no_html_gives_its_last_plain_part(self):
        parsed = self.parse(samples.alternative_message(["plain", "plain"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["PART-1"])
        self.assertEqual([p.role for p in parsed.parts], ["container", "unselected", "selected"])

    def test_two_html_alternatives_yield_the_gap_and_the_last_html_part(self):
        """TS-PARSE-01"""
        parsed = self.parse(samples.duplicate_html_alternative())
        self.assertEqual(gaps(parsed), {("alternative-duplicate-html", ""): 1})
        self.assertEqual(texts(parsed), ["<p>PART-2</p>"])
        self.assertEqual([(p.part_id, p.role) for p in parsed.parts],
                         [("p1", "container"), ("p2", "unselected"), ("p3", "unselected"), ("p4", "selected")])
        self.assertEqual(parsed.attachments, ())

    def test_three_html_alternatives_are_one_gap_and_the_last(self):
        parsed = self.parse(samples.alternative_message(["html", "html", "plain", "html"]))
        self.assertEqual(gaps(parsed), {("alternative-duplicate-html", ""): 1})
        self.assertEqual(texts(parsed), ["<p>PART-3</p>"])

    def test_an_alternative_of_another_text_type_is_a_gap_and_an_attachment(self):
        parsed = self.parse(samples.alternative_message(["plain", "enriched", "html"]))
        self.assertEqual(gaps(parsed), {("alternative-other-text", ""): 1})
        self.assertEqual(texts(parsed), ["<p>PART-2</p>"])
        self.assertEqual(roles(parsed)[2], ("text/enriched", "attachment"))

    def test_a_calendar_alternative_is_an_attachment_and_no_gap(self):
        parsed = self.parse(samples.alternative_message(["plain", "html", "calendar"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["<p>PART-1</p>"])
        self.assertEqual(roles(parsed)[3], ("text/calendar", "attachment"))
        self.assertEqual([(a.role, a.media_type) for a in parsed.attachments], [("attachment", "text/calendar")])
        both = self.parse(samples.alternative_message(["plain", "calendar", "enriched", "html"]))
        self.assertEqual(gaps(both), {("alternative-other-text", ""): 1})
        alone = self.parse(samples.alternative_message(["calendar"]))
        self.assertEqual(gaps(alone), {("alternative-ambiguous", ""): 1})

    def test_an_alternative_with_no_html_and_no_plain_part_is_ambiguous(self):
        for kinds in (["image"], ["calendar"], ["image", "rfc822"], ["plain-attachment"]):
            with self.subTest(kinds=kinds):
                parsed = self.parse(samples.alternative_message(kinds))
                self.assertIn(("alternative-ambiguous", ""), gaps(parsed))
                self.assertEqual(parsed.selected, ())

    def test_an_alternative_holding_another_multipart_is_ambiguous(self):
        for kinds, chosen in ((["plain", "mixed-html"], "PART-0"), (["html", "mixed-html"], "<p>PART-0</p>"),
                              (["plain", "alternative"], "PART-0")):
            with self.subTest(kinds=kinds):
                parsed = self.parse(samples.alternative_message(kinds))
                self.assertEqual(gaps(parsed), {("alternative-ambiguous", ""): 1})
                # The written rule still names a part; the text inside the other multipart is not read.
                self.assertEqual(texts(parsed), [chosen])
                self.assertEqual(parsed.parts[-1].role, "unselected")

    def test_an_alternative_whose_only_content_is_a_multipart_selects_nothing(self):
        parsed = self.parse(samples.alternative_message(["mixed-html"]))
        self.assertEqual(gaps(parsed), {("alternative-ambiguous", ""): 1})
        self.assertEqual(parsed.selected, ())

    def test_an_ambiguous_alternative_is_block_class(self):
        parsed = self.parse(samples.alternative_message(["image"]))
        gap = [g for g in parsed.gaps if g.name == "alternative-ambiguous"][0]
        self.assertEqual((gap.gap_class, gap.reply_effect), ("block", "held"))

    def test_a_related_alternative_counts_as_its_root_part(self):
        parsed = self.parse(samples.alternative_message(["plain", "related-html"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["<p>PART-1</p>"])
        self.assertEqual(roles(parsed), [("multipart/alternative", "container"), ("text/plain", "unselected"),
                                         ("multipart/related", "container"), ("text/html", "selected"),
                                         ("image/png", "resource")])

    def test_an_unchosen_related_alternative_keeps_its_parts_out(self):
        parsed = self.parse(samples.alternative_message(["related-html", "html"]))
        self.assertEqual(gaps(parsed), {("alternative-duplicate-html", ""): 1})
        self.assertEqual(texts(parsed), ["<p>PART-1</p>"])
        self.assertEqual([p.role for p in parsed.parts],
                         ["container", "container", "unselected", "resource", "selected"])

    def test_a_related_alternative_with_an_invalid_root_is_a_gap(self):
        parsed = self.parse(samples.alternative_message(["plain", "related-image-root"]))
        self.assertEqual(gaps(parsed), {("related-root-invalid", ""): 1})
        self.assertEqual(texts(parsed), ["PART-0"])

    def test_a_text_part_sent_as_an_attachment_is_not_an_alternative(self):
        parsed = self.parse(samples.alternative_message(["plain-attachment", "html"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["<p>PART-1</p>"])
        self.assertEqual(roles(parsed)[1], ("text/plain", "attachment"))

    def test_a_nested_message_among_alternatives_is_a_gap_and_is_not_selected(self):
        parsed = self.parse(samples.alternative_message(["plain", "rfc822"]))
        self.assertEqual(gaps(parsed), {("nested-message", ""): 1})
        self.assertEqual(texts(parsed), ["PART-0"])


class MixedSelection(ParseCase):
    def test_a_mixed_message_gives_every_inline_text_part_in_order(self):
        parsed = self.parse(samples.mixed_message(["plain", "html", "image", "plain"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["PART-0", "<p>PART-1</p>", "PART-3"])
        self.assertEqual([(p.part_id, p.subtype) for p in parsed.selected],
                         [("p2", "plain"), ("p3", "html"), ("p5", "plain")])

    def test_a_text_part_sent_as_an_attachment_is_not_selected(self):
        parsed = self.parse(samples.mixed_message(["plain", "plain-attachment"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["PART-0"])
        self.assertEqual(roles(parsed)[2], ("text/plain", "attachment"))
        self.assertEqual(len(parsed.attachments), 1)

    def test_an_inline_text_part_with_a_file_name_is_selected(self):
        part = samples.mail_part("text/plain", "INLINE-NAMED", "utf-8", disposition="inline", filename="a.txt")
        parsed = self.parse(samples.mail_message(samples.mail_multipart("mixed", [part])))
        self.assertEqual(texts(parsed), ["INLINE-NAMED"])

    def test_a_multipart_inside_a_mixed_message_is_read_by_its_own_rule(self):
        parsed = self.parse(samples.mixed_message(["plain", "related-html", "alternative", "mixed-html"]))
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["PART-0", "<p>PART-1</p>", "PART-2", "<p>PART-3</p>"])

    def test_the_usual_alternative_with_an_attachment(self):
        raw = samples.mail_message(samples.mail_multipart("mixed", [
            samples.mail_multipart("alternative", [samples.mail_part("text/plain", "P", "utf-8"),
                                                   samples.mail_part("text/html", "<p>H</p>", "utf-8")]),
            samples.attachment_part("report.pdf", "application/pdf", b"%PDF-1.7")]))
        parsed = self.parse(raw)
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["<p>H</p>"])
        self.assertEqual([p.role for p in parsed.parts],
                         ["container", "container", "unselected", "selected", "attachment"])

    def test_a_nested_message_is_a_named_gap_and_is_not_opened(self):
        parsed = self.parse(samples.nested_in_mixed_message())
        self.assertEqual(gaps(parsed), {("nested-message", ""): 1})
        self.assertEqual((parsed.gaps[0].gap_class, parsed.gaps[0].reply_effect), ("caution", "held"))
        self.assertEqual(texts(parsed), ["PART-0"])
        # The message inside is one inventory item; its own parts are not listed.
        self.assertEqual(roles(parsed), [("multipart/mixed", "container"), ("text/plain", "selected"),
                                         ("message/rfc822", "nested-message")])
        self.assertEqual([(a.role, a.size) for a in parsed.attachments], [("nested-message", 0)])
        self.assertNotIn("INNER-BODY", repr(parsed))

    def test_selected_parts_come_in_document_order(self):
        raw = samples.mail_message(samples.mail_multipart("mixed", [
            samples.mail_multipart("related", [samples.mail_part("image/png", samples.png_bytes(), encoding="base64"),
                                               samples.mail_part("text/html", "SECOND", "utf-8",
                                                                 content_id="<r@example.org>")],
                                   params='; start="<r@example.org>"'),
            samples.mail_part("text/plain", "THIRD", "utf-8")]))
        parsed = self.parse(raw)
        self.assertEqual(texts(parsed), ["SECOND", "THIRD"])
        self.assertEqual([p.part_id for p in parsed.selected], ["p4", "p5"])


class RelatedSelection(ParseCase):
    def test_a_related_message_exposes_only_its_root_part(self):
        """TS-PARSE-02"""
        parsed = self.parse(samples.related_message("first"))
        self.assert_clean(parsed)
        self.assertEqual([p.part_id for p in parsed.selected], ["p2"])
        self.assertIn("ROOT-HTML", texts(parsed)[0])
        self.assertEqual(roles(parsed), [("multipart/related", "container"), ("text/html", "selected"),
                                         ("image/png", "resource"), ("text/html", "resource")])
        self.assertEqual([(a.part_id, a.role, a.media_type) for a in parsed.attachments],
                         [("p3", "resource", "image/png"), ("p4", "resource", "text/html")])

    def test_a_related_resource_never_appears_among_the_selected_parts(self):
        for variant in ("first", "start", "start-missing", "start-twice", "image-root", "alternative-root",
                        "mixed-root"):
            with self.subTest(variant=variant):
                parsed = self.parse(samples.related_message(variant))
                resources = {p.part_id for p in parsed.parts if p.role == "resource"}
                self.assertTrue(resources)
                self.assertFalse(resources & {p.part_id for p in parsed.selected})
                self.assertNotIn("RESOURCE-HTML", "".join(texts(parsed)))
                self.assertFalse(resources & {link.part_id for link in parsed.links})

    def test_a_start_parameter_that_names_the_first_part_is_the_ordinary_root(self):
        parsed = self.parse(samples.related_message("start-first"))
        self.assert_clean(parsed)
        self.assertEqual([p.part_id for p in parsed.selected], ["p2"])
        self.assertIn("ROOT-HTML", texts(parsed)[0])

    def test_a_start_parameter_that_names_another_part_than_the_first_is_an_invalid_root(self):
        # review A, F7: a mail reader that ignores `start` shows the first part, not the named one
        parsed = self.parse(samples.related_message("start"))
        self.assertEqual(gaps(parsed), {("related-root-invalid", "start"): 1})
        self.assertEqual((parsed.gaps[0].gap_class, parsed.gaps[0].reply_effect), ("block", "held"))
        self.assertEqual([p.part_id for p in parsed.selected], ["p3"])
        self.assertIn("ROOT-HTML", texts(parsed)[0])
        self.assertEqual([p.role for p in parsed.parts], ["container", "resource", "selected", "resource"])

    def test_a_start_parameter_that_names_no_part_is_an_invalid_root(self):
        parsed = self.parse(samples.related_message("start-missing"))
        self.assertEqual(gaps(parsed), {("related-root-invalid", ""): 1})
        self.assertEqual((parsed.gaps[0].gap_class, parsed.gaps[0].reply_effect), ("block", "held"))
        self.assertEqual(parsed.selected, ())

    def test_a_start_parameter_that_names_two_parts_is_an_invalid_root(self):
        parsed = self.parse(samples.related_message("start-twice"))
        self.assertEqual(gaps(parsed), {("related-root-invalid", ""): 1})
        self.assertEqual(parsed.selected, ())

    def test_a_root_that_is_not_text_is_an_invalid_root(self):
        for variant in ("image-root", "mixed-root"):
            with self.subTest(variant=variant):
                parsed = self.parse(samples.related_message(variant))
                self.assertEqual(gaps(parsed), {("related-root-invalid", ""): 1})
                self.assertEqual(parsed.selected, ())
                self.assertNotIn("selected", [p.role for p in parsed.parts])

    def test_a_related_with_no_part_selects_nothing(self):
        parsed = self.parse(samples.related_message("empty"))
        self.assertEqual(parsed.selected, ())
        self.assertTrue(parsed.gaps)
        self.assertTrue(all(gap.gap_class == "block" for gap in parsed.gaps))

    def test_a_root_that_is_an_alternative_is_read_by_the_alternative_rule(self):
        parsed = self.parse(samples.related_message("alternative-root"))
        self.assert_clean(parsed)
        self.assertEqual([p.part_id for p in parsed.selected], ["p4"])
        self.assertEqual([p.role for p in parsed.parts],
                         ["container", "container", "unselected", "selected", "resource"])

    def test_a_multipart_resource_is_inventoried_and_not_read(self):
        raw = samples.mail_message(samples.mail_multipart("related", [
            samples.mail_part("text/html", "ROOT", "utf-8"),
            samples.mail_multipart("mixed", [samples.mail_part("text/plain", "INSIDE-RESOURCE", "utf-8"),
                                             samples.nested_message_entity()])]))
        parsed = self.parse(raw)
        self.assertEqual(texts(parsed), ["ROOT"])
        self.assertEqual([p.role for p in parsed.parts],
                         ["container", "selected", "container", "resource", "nested-message"])
        self.assertEqual(gaps(parsed), {("nested-message", ""): 1})


class SelectionIsWrittenHere(unittest.TestCase):
    def test_the_module_never_calls_get_body_or_walk(self):
        tree = ast.parse((SCRIPTS / "mail_parse.py").read_text(encoding="utf-8"))
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for forbidden in ("get_body", "iter_attachments", "iter_parts", "walk", "get_content"):
            self.assertNotIn(forbidden, names)

    def test_get_body_is_not_called_while_any_sample_is_parsed(self):
        from email.message import EmailMessage, Message
        messages = [samples.plain_message(), samples.ordinary_alternative_message(),
                    samples.duplicate_html_alternative(), samples.related_message("first"),
                    samples.related_message("alternative-root"), samples.marker_message(MARKER),
                    samples.mixed_message(["plain", "related-html", "alternative"]), samples.signed_message()]
        with mock.patch.object(EmailMessage, "get_body", side_effect=AssertionError("get_body")) as get_body, \
                mock.patch.object(Message, "walk", side_effect=AssertionError("walk")) as walk:
            for raw in messages:
                self.assertTrue(mail_parse.parse(raw).selected)
            get_body.assert_not_called()
            walk.assert_not_called()


# --------------------------------------------------------------------------------------
# Gaps
# --------------------------------------------------------------------------------------

class GapClasses(ParseCase):
    def messages_by_gap(self):
        return {
            "charset-unsupported": samples.charset_message("utf-7", b"hello"),
            "structure-over-bound": samples.nested_depth_message(9),
            "parse-defect": samples.defect_messages()["bad-base64-in-selected-part"],
            "alternative-ambiguous": samples.alternative_message(["image"]),
            "related-root-invalid": samples.related_message("image-root"),
            "nested-message": samples.nested_in_mixed_message(),
            "alternative-duplicate-html": samples.duplicate_html_alternative(),
            "alternative-other-text": samples.alternative_message(["plain", "enriched"]),
            "multipart-unknown": samples.unknown_multipart_message("report"),
        }

    def test_every_gap_carries_the_class_and_reply_effect_of_the_design_table(self):
        messages = self.messages_by_gap()
        self.assertEqual(sorted(messages), sorted(DESIGN_PARSE_GAPS))
        for name, raw in messages.items():
            with self.subTest(gap=name):
                found = [gap for gap in self.parse(raw).gaps if gap.name == name]
                self.assertEqual(len(found), 1)
                self.assertEqual((found[0].gap_class, found[0].reply_effect), DESIGN_PARSE_GAPS[name])

    def test_the_gaps_of_the_parser_are_gaps_of_the_lists(self):
        self.assertEqual(sorted(mail_parse.PARSE_GAPS), sorted(DESIGN_PARSE_GAPS))
        for name in mail_parse.PARSE_GAPS:
            self.assertIn(name, mail_lists.GAPS)
            self.assertEqual((mail_lists.GAPS[name].gap_class, mail_lists.GAPS[name].reply_effect),
                             DESIGN_PARSE_GAPS[name])

    def test_a_gap_met_twice_is_counted_twice(self):
        parsed = self.parse(samples.mixed_message(["plain", "rfc822", "rfc822"]))
        self.assertEqual(gaps(parsed), {("nested-message", ""): 2})


class BareCarriageReturn(ParseCase):
    """A header line ended by a carriage return alone: this parser would read more headers than anybody else."""

    def test_a_carriage_return_alone_in_a_header_block_stops_the_parse(self):
        cases = samples.bare_cr_messages()["smuggled"]
        self.assertGreaterEqual(len(cases), 12)
        for label, raw in cases.items():
            with self.subTest(message=label):
                parsed = self.parse(raw)
                self.assertEqual([(gap.name, gap.gap_class, gap.reply_effect, gap.detail) for gap in parsed.gaps],
                                 [("parse-defect", "block", "held", "bare-cr")])
                # nothing of the message is read: no header is trusted, no part is selected
                headers = parsed.headers
                self.assertEqual((headers.from_address, headers.subject, headers.authentication_results,
                                  headers.auto_submitted, headers.list_id_present),
                                 (None, None, (), "absent", False))
                self.assertEqual((parsed.parts, parsed.selected, parsed.attachments, parsed.links), ((), (), (), ()))
                self.assert_recordable_vocabulary(parsed)

    def test_what_the_standard_parser_would_have_read_from_each_of_them(self):
        # the reason for the rule: without it each smuggled header is one more header of the message
        import email
        import email.policy
        cases = samples.bare_cr_messages()["smuggled"]
        for label, name, value in (("auto-submitted", "Auto-Submitted", "auto-replied"),
                                   ("list-id", "List-Id", "<list.example.org>"),
                                   ("from", "From", "boss@example.com"), ("content-type", "Content-Type", "text/html")):
            message = email.message_from_bytes(cases[label], policy=email.policy.default)
            self.assertEqual(str(message[name]), value, label)
        message = email.message_from_bytes(cases["authentication-results"], policy=email.policy.default)
        self.assertTrue(str(message["Authentication-Results"]).startswith(samples.PROFILE_ID))
        message = email.message_from_bytes(cases["part-made-in-a-body"], policy=email.policy.default)
        self.assertEqual([part.get_content_type() for part in message.get_payload()], ["text/plain", "text/html"])

    def test_ordinary_line_ends_and_a_carriage_return_in_a_body_stay_ordinary(self):
        cases = samples.bare_cr_messages()["ordinary"]
        for label, raw in cases.items():
            with self.subTest(message=label):
                parsed = self.parse(raw)
                self.assert_clean(parsed)
                self.assertEqual(parsed.headers.from_address, samples.SENDER_ADDRESS)
                self.assertEqual(parsed.headers.subject, "Hello")
        same = [mail_parse.recordable(self.parse(cases[label])) for label in ("crlf", "lf-only", "mixed")]
        self.assertEqual(same[0], same[1])
        self.assertEqual(same[0], same[2])
        self.assertEqual(mail_parse.recordable(self.parse(cases["verified-crlf"])),
                         mail_parse.recordable(self.parse(cases["verified-lf-only"])))
        # in a body it is a line break of the text and no header: the From is the real one
        text = self.parse(cases["cr-in-a-body"]).selected[0].text
        self.assertIn("one\rtwo", text)
        self.assertEqual(len(self.parse(cases["cr-in-a-part-body"]).selected), 1)
        self.assertEqual(len(self.parse(cases["lf-only-multipart"]).selected), 2)

    def test_no_other_character_and_no_encoded_word_cuts_a_header_in_two(self):
        cases = samples.header_oddity_messages()
        self.assertEqual(len(cases), 11)
        for label, raw in cases.items():
            with self.subTest(message=label):
                headers = self.parse(raw).headers
                self.assertEqual((headers.auto_submitted, headers.list_id_present), ("absent", False))
                self.assertIn(headers.from_address, (samples.SENDER_ADDRESS, None))
        # an encoded word is text of its own header: decoded in Subject, left as written elsewhere
        self.assertEqual(self.parse(cases["encoded-subject"]).headers.subject, "hi\r\nAuto-Submitted: auto-replied")
        for label in ("encoded-authentication-results", "encoded-line-break-in-authentication-results"):
            values = self.parse(cases[label]).headers.authentication_results
            self.assertEqual(len(values), 1)
            self.assertIn("=?utf-8?q?", values[0])
        # a line break decoded inside the From name is a defect of From: a block
        parsed = self.parse(cases["encoded-from-name"])
        self.assertEqual(gap_names(parsed), ["parse-defect"])
        self.assertIsNone(parsed.headers.from_address)


class ParseDefects(ParseCase):
    def test_each_structural_defect_is_the_gap_parse_defect(self):
        for label, raw in samples.defect_messages().items():
            with self.subTest(label=label):
                parsed = self.parse(raw)
                self.assertEqual(gap_names(parsed), ["parse-defect"])
                self.assertEqual({gap.gap_class for gap in parsed.gaps}, {"block"})
                self.assertLessEqual({gap.detail for gap in parsed.gaps}, {"part", "structure"})

    def test_a_defect_on_a_selected_part_is_reported_for_the_part(self):
        parsed = self.parse(samples.defect_messages()["bad-base64-in-a-mixed-part"])
        self.assertEqual(list(gaps(parsed)), [("parse-defect", "part")])
        parsed = self.parse(samples.defect_messages()["duplicate-charset-parameter"])
        self.assertEqual(list(gaps(parsed)), [("parse-defect", "part")])

    def test_a_defect_on_the_message_or_a_container_is_reported_for_the_structure(self):
        for label in ("no-boundary-parameter", "boundary-never-found", "close-boundary-missing",
                      "no-blank-line-after-headers", "first-line-is-a-continuation"):
            with self.subTest(label=label):
                self.assertEqual(list(gaps(self.parse(samples.defect_messages()[label]))),
                                 [("parse-defect", "structure")])

    def test_a_multipart_that_cannot_be_split_is_a_gap_wherever_it_stands(self):
        broken = b"Content-Type: multipart/mixed\r\n\r\nTEXT-IN-A-BROKEN-MULTIPART\r\n"
        for subtype in ("mixed", "alternative", "related"):
            with self.subTest(subtype=subtype):
                raw = samples.mail_message(samples.mail_multipart(subtype, [
                    samples.mail_part("text/plain", "BODY", "utf-8"), broken]))
                parsed = self.parse(raw)
                self.assertEqual(list(gaps(parsed)), [("parse-defect", "structure")])
                self.assertEqual(texts(parsed), ["BODY"])

    def test_a_defect_on_a_part_that_is_not_selected_is_not_a_gap(self):
        bad = b"Content-Type: application/octet-stream\r\nContent-Transfer-Encoding: base64\r\n\r\naGV$sbG8"
        raw = samples.mail_message(samples.mail_multipart("mixed", [samples.mail_part("text/plain", "B", "utf-8"), bad]))
        self.assert_clean(self.parse(raw))

    def test_a_defect_on_from_outside_the_display_name_is_the_gap_parse_defect(self):
        for label, value in samples.defective_from_values().items():
            with self.subTest(label=label):
                parsed = self.parse(samples.from_message([value]))
                self.assertEqual([key for key in gaps(parsed)], [("parse-defect", "from")])
                self.assertEqual(parsed.gaps[0].gap_class, "block")
                self.assertFalse(parsed.headers.from_name_irregular)
                # The header still names exactly one mailbox, so it is not ambiguous as well.
                self.assertEqual(parsed.header_ambiguous, ())
                self.assertIn("@example.org", parsed.headers.from_address)

    def test_a_defect_confined_to_the_display_name_is_a_caution_and_the_mailbox_is_used(self):
        for label, (value, name, address) in samples.name_irregular_from_values().items():
            with self.subTest(label=label):
                parsed = self.parse(samples.from_message([value]))
                self.assertEqual(parsed.gaps, ())
                self.assertEqual(parsed.header_ambiguous, ())
                self.assertTrue(parsed.headers.from_name_irregular)
                self.assertEqual(parsed.headers.from_address, address)
                self.assertEqual(parsed.headers.from_name, name)
                self.assertTrue(mail_parse.recordable(parsed)["headers"]["from_name_irregular"])

    def test_a_display_name_that_cannot_be_decoded_stays_a_block(self):
        for label, value in samples.undecodable_name_from_values().items():
            with self.subTest(label=label):
                parsed = self.parse(samples.from_message([value]))
                self.assertEqual(gaps(parsed), {("charset-unsupported", "header"): 1})
                self.assertEqual(parsed.gaps[0].gap_class, "block")
                self.assertEqual(parsed.headers.from_address, "ann@example.org")

    def test_an_irregular_name_is_still_given_to_the_rules(self):
        value = b"bank.example Team" + chr(0x202E).encode("utf-8") + b" <ann@example.org>"
        parsed = self.parse(samples.from_message([value]))
        self.assertTrue(parsed.headers.from_name_irregular)
        self.assertIn("bank.example Team", parsed.headers.from_name)
        self.assertEqual(mail_reuse.BIDI.count(parsed.headers.from_name), 1)
        self.assertEqual(parsed.headers.from_domain, "example.org")

    def test_a_from_without_a_defect_is_not_irregular(self):
        self.assertFalse(self.parse(samples.plain_message()).headers.from_name_irregular)
        for label in ("two-headers", "group", "two-mailboxes", "missing"):
            parsed = self.parse(samples.from_message(samples.from_values()[label]))
            self.assertFalse(parsed.headers.from_name_irregular)

    def test_the_caution_for_an_irregular_name_is_a_rule_of_the_lists(self):
        rule = mail_lists.RULES[mail_lists.FROM_NAME_IRREGULAR_RULE]
        self.assertEqual(mail_lists.FROM_NAME_IRREGULAR_RULE, "from-name-irregular")
        self.assertEqual((rule.rule_class, rule.hold, rule.reply), ("caution", "", ""))

    def test_a_from_without_a_defect_is_no_gap(self):
        for label, (value, _name, _address) in samples.single_from_values().items():
            with self.subTest(label=label):
                self.assertEqual(self.parse(samples.from_message([value])).gaps, ())

    def test_each_standard_transfer_encoding_is_read(self):
        bodies = {"7bit": b"hello", "8bit": b"hello", "binary": b"hello", "quoted-printable": b"hel=6Co",
                  "base64": b"aGVsbG8=", "BASE64": b"aGVsbG8=", "Quoted-Printable": b"hel=6Co"}
        self.assertEqual(mail_lists.TRANSFER_ENCODINGS, ("7bit", "8bit", "binary", "quoted-printable", "base64"))
        for encoding, body in bodies.items():
            with self.subTest(encoding=encoding):
                parsed = self.parse(samples.transfer_encoding_message(encoding, body))
                self.assert_clean(parsed)
                self.assertEqual(texts(parsed), ["hello"])

    def test_another_transfer_encoding_on_a_selected_part_is_the_gap_parse_defect(self):
        for encoding in ("x-uuencode", "uuencode", "x-unknown", "gzip"):
            with self.subTest(encoding=encoding):
                parsed = self.parse(samples.transfer_encoding_message(encoding))
                self.assertEqual(gaps(parsed), {("parse-defect", "transfer-encoding"): 1})

    def test_an_unexpected_error_is_the_gap_parse_defect_and_nothing_else(self):
        with mock.patch.object(mail_parse._Reader, "read", side_effect=RuntimeError(MARKER)):
            parsed = mail_parse.parse(samples.plain_message())
        self.assertEqual(gaps(parsed), {("parse-defect", "error"): 1})
        self.assertEqual((parsed.gaps[0].gap_class, parsed.gaps[0].reply_effect), ("block", "held"))
        self.assertEqual(parsed.selected, ())
        self.assertEqual(parsed.parts, ())
        self.assertIsNone(parsed.headers.from_address)
        self.assertNotIn(MARKER, repr(parsed))
        self.assert_recordable_vocabulary(parsed)

    def test_an_error_inside_the_standard_parser_is_the_gap_parse_defect(self):
        with mock.patch.object(mail_parse.email.parser.BytesParser, "parsebytes", side_effect=ValueError("x")):
            parsed = mail_parse.parse(samples.plain_message())
        self.assertEqual(gaps(parsed), {("parse-defect", "error"): 1})

    def test_no_exception_leaves_the_module_for_hostile_bytes(self):
        fixed = [b"", b"\r\n", b"\x00" * 64, b"\xff" * 64, b"From", b"From:", b":\r\n\r\n", b"\r\n\r\nbody",
                 b"Content-Type: multipart/mixed; boundary=\r\n\r\n--\r\n", b"From: =?utf-8?b??= <@>\r\n\r\n",
                 b"Content-Type: text/html; charset=\"\r\n\r\n<a href=", samples.deep_comment_from_message(),
                 b"Content-Type: multipart/related; start=\r\n\r\n", b"From: a@b\r\nContent-Type: message/rfc822\r\n\r\n"]
        for raw in fixed:
            with self.subTest(raw=raw[:30]):
                self.parse(raw)
        rng = random.Random(351)
        seeds = [samples.marker_message(MARKER), samples.html_links_message(), samples.attachments_message(),
                 samples.related_message("start"), samples.duplicate_html_alternative(),
                 samples.header_facts_message(auto_submitted="no", return_path="<>", precedence="list",
                                              authentication_results=samples.authentication_results_values())]
        for case in range(600):
            data = bytearray(rng.choice(seeds))
            for _ in range(rng.randint(1, 8)):
                action = rng.randint(0, 4)
                at = rng.randrange(len(data) + 1)
                if action == 0 and data:
                    data[at % len(data)] = rng.randrange(256)
                elif action == 1:
                    data[at:at] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 6)))
                elif action == 2:
                    del data[at:at + rng.randint(1, 40)]
                elif action == 3:
                    chunk = data[at:at + rng.randint(1, 120)]
                    data[at:at] = chunk
                else:
                    data[at:at] = rng.choice([b"\r\n", b"--", b"\r\n\r\n", b"=?", b"?=", b"<", b";", b":", b"\""])
            with self.subTest(case=case):
                self.parse(bytes(data))


# --------------------------------------------------------------------------------------
# TS-PARSE-03: charsets
# --------------------------------------------------------------------------------------

class Charsets(ParseCase):
    def test_the_allowlist_is_that_of_the_design(self):
        self.assertEqual(mail_lists.CHARSET_ALLOWLIST, DESIGN_CHARSETS)
        for name in DESIGN_CHARSETS:
            self.assertEqual(mail_parse.allowed_charset(name), name)

    def test_each_allowlisted_charset_and_its_aliases_decode(self):
        seen = set()
        for declared, (body, text) in samples.allowlisted_charset_bodies().items():
            with self.subTest(charset=declared):
                parsed = self.parse(samples.charset_message(declared, body))
                self.assert_clean(parsed)
                self.assertEqual(texts(parsed), [text])
                self.assertIn(parsed.selected[0].charset, DESIGN_CHARSETS)
                seen.add(parsed.selected[0].charset)
        self.assertEqual(seen, set(DESIGN_CHARSETS))

    def test_an_allowlisted_charset_decodes_in_an_html_part_and_under_base64(self):
        body, text = samples.allowlisted_charset_bodies()["iso-8859-15"]
        parsed = self.parse(samples.charset_message("ISO-8859-15", body, subtype="html", encoding="base64"))
        self.assert_clean(parsed)
        self.assertEqual([(p.subtype, p.text) for p in parsed.selected], [("html", text)])

    def test_a_charset_outside_the_allowlist_is_charset_unsupported(self):
        """TS-PARSE-03"""
        for declared, body in samples.unsupported_charsets().items():
            if declared in ("", "utf-8 extra"):
                continue        # not a charset parameter at all: see the next test
            with self.subTest(charset=declared[:20]):
                parsed = self.parse(samples.charset_message(declared, body))
                self.assertEqual(gaps(parsed), {("charset-unsupported", "body"): 1})
                self.assertEqual((parsed.gaps[0].gap_class, parsed.gaps[0].reply_effect), ("block", "held"))
                # Nothing is decoded under a charset that is not on the list.
                self.assertEqual([(p.charset, p.text) for p in parsed.selected], [("", "")])

    def test_a_malformed_charset_parameter_is_never_a_clean_parse(self):
        for declared in ("", "utf-8 extra"):
            with self.subTest(charset=declared):
                parsed = self.parse(samples.charset_message(declared, b"hello"))
                self.assertTrue(parsed.gaps)
                self.assertTrue(all(gap.gap_class == "block" for gap in parsed.gaps))

    def test_an_unsupported_charset_in_an_html_part_and_in_a_part_of_a_multipart(self):
        parsed = self.parse(samples.charset_message("utf-7", b"+ADw-b+AD4-", subtype="html"))
        self.assertEqual(gaps(parsed), {("charset-unsupported", "body"): 1})
        raw = samples.mail_message(samples.mail_multipart("mixed", [
            samples.mail_part("text/plain", "fine", "utf-8"), samples.mail_part("text/plain", b"\xc4\xe3", "gb2312")]))
        parsed = self.parse(raw)
        self.assertEqual(gaps(parsed), {("charset-unsupported", "body"): 1})
        self.assertEqual(texts(parsed), ["fine", ""])

    def test_a_charset_on_a_part_that_is_not_selected_is_not_a_gap(self):
        raw = samples.mail_message(samples.mail_multipart("alternative", [
            samples.mail_part("text/plain", b"\xc4\xe3", "gb2312"), samples.mail_part("text/html", "H", "utf-8")]))
        self.assert_clean(self.parse(raw))

    def test_no_charset_parameter_means_ascii(self):
        parsed = self.parse(samples.charset_message(None, b"plain words"))
        self.assert_clean(parsed)
        self.assertEqual(parsed.selected[0].charset, "us-ascii")
        parsed = self.parse(samples.charset_message(None, ("caf" + E_ACUTE + " au lait").encode("utf-8")))
        self.assertEqual(gaps(parsed), {("charset-unsupported", "body"): 1})

    def test_a_decode_with_over_one_percent_replacement_characters_is_charset_unsupported(self):
        for bad, total, over in ((0, 100, False), (1, 100, False), (2, 100, True), (1, 99, True),
                                 (10, 1000, False), (11, 1000, True), (0, 0, False)):
            with self.subTest(bad=bad, total=total):
                parsed = self.parse(samples.charset_message("utf-8", samples.replacement_ratio_body(bad, total)))
                self.assertEqual(gaps(parsed), {("charset-unsupported", "body"): 1} if over else {})
                self.assertEqual(parsed.selected[0].replaced, bad)
                self.assertEqual(parsed.selected[0].text.count(REPLACED), bad)

    def test_the_one_percent_rule_holds_for_every_allowlisted_charset_that_can_fail(self):
        for declared, body in (("us-ascii", b"\xe9" * 5 + b"a" * 95), ("windows-1252", b"\x81" * 5 + b"a" * 95)):
            with self.subTest(charset=declared):
                parsed = self.parse(samples.charset_message(declared, body))
                self.assertEqual(gaps(parsed), {("charset-unsupported", "body"): 1})

    def test_an_encoded_word_in_an_allowlisted_charset_is_read(self):
        for charset in ("utf-8", "UTF-8", "iso-8859-1", "windows-1252", "us-ascii", "utf-8*en"):
            for encoding in ("b", "q"):
                with self.subTest(charset=charset, encoding=encoding):
                    parsed = self.parse(samples.encoded_word_message("Subject", charset, b"hello", encoding))
                    self.assert_clean(parsed)
                    self.assertEqual(parsed.headers.subject, "hello")
                    parsed = self.parse(samples.encoded_word_message("From", charset, b"hello", encoding))
                    self.assert_clean(parsed)
                    self.assertEqual(parsed.headers.from_name, "hello")

    def test_an_encoded_word_charset_outside_the_allowlist_is_charset_unsupported_in_subject(self):
        for charset in ("gb2312", "utf-7", "koi8-r", "rot13", "no-such-charset", "utf-16", ""):
            for encoding in ("b", "q", "B", "Q"):
                with self.subTest(charset=charset, encoding=encoding):
                    parsed = self.parse(samples.encoded_word_message("Subject", charset, b"hello", encoding))
                    self.assertEqual(gaps(parsed), {("charset-unsupported", "header"): 1})
                    self.assertEqual(parsed.gaps[0].gap_class, "block")

    def test_an_encoded_word_charset_outside_the_allowlist_is_charset_unsupported_in_from(self):
        for charset in ("gb2312", "utf-7", "koi8-r", "rot13", "no-such-charset"):
            with self.subTest(charset=charset):
                parsed = self.parse(samples.encoded_word_message("From", charset, b"hello"))
                self.assertIn(("charset-unsupported", "header"), gaps(parsed))

    def test_an_encoded_word_the_standard_parser_reads_loosely_is_still_checked(self):
        # White space inside the word, and a word glued to other text: the parser decodes both.
        for subject in ("=?utf-7?q?+ADw-b +AD4-?=", "x=?gb2312?b?xOO6ww==?=y", "=?utf-8?q?a?= =?utf-7?q?+ADw-?="):
            with self.subTest(subject=subject):
                parsed = self.parse(samples.mail_message(subject=subject))
                self.assertIn(("charset-unsupported", "header"), gaps(parsed))

    def test_undecodable_bytes_in_an_encoded_word_are_charset_unsupported(self):
        parsed = self.parse(samples.encoded_word_message("Subject", "utf-8", b"\xff\xff\xff\xff"))
        self.assertEqual(gaps(parsed), {("charset-unsupported", "header"): 1})
        parsed = self.parse(samples.encoded_word_message("From", "utf-8", b"\xff\xff\xff\xff"))
        self.assertIn(("charset-unsupported", "header"), gaps(parsed))

    def test_raw_bytes_in_a_subject_are_read_as_utf8_or_are_charset_unsupported(self):
        parsed = self.parse(samples.raw_eight_bit_subject_message(("caf" + E_ACUTE).encode("utf-8")))
        self.assert_clean(parsed)
        self.assertEqual(parsed.headers.subject, "Note caf" + E_ACUTE)
        parsed = self.parse(samples.raw_eight_bit_subject_message(b"\xff\xfe\xfd"))
        self.assertEqual(gaps(parsed), {("charset-unsupported", "header"): 1})
        self.assertEqual(parsed.headers.subject, "Note " + REPLACED * 3)

    def test_a_subject_with_text_that_only_looks_like_an_encoded_word_is_no_gap(self):
        for subject in ("What =? is this ?=", "a =?b?= c", "Re: 2+2=? and ?q? why", "=?utf-8?x?abc?="):
            with self.subTest(subject=subject):
                self.assert_clean(self.parse(samples.mail_message(subject=subject)))

    def test_a_charset_name_is_checked_before_any_codec_is_looked_up(self):
        for name in ("", " ", "utf-8\n", "utf-8 ", "a" * 41, "../x", "utf\x008", "caf" + E_ACUTE, None, 5, b"utf-8",
                     "encodings.idna", "idna", "punycode", "hex", "zip", "bz2", "uu", "quopri", "mbcs", "oem",
                     "undefined", "raw_unicode_escape", "utf-16", "utf-32", "utf-8-sig", "cp437", "latin2"):
            with self.subTest(name=repr(name)):
                self.assertIsNone(mail_parse.allowed_charset(name))
        for name, expected in (("UTF-8", "utf-8"), ("utf8", "utf-8"), ("U8", "utf-8"), ("ASCII", "us-ascii"),
                               ("ansi_x3.4-1968", "us-ascii"), ("latin-1", "iso-8859-1"), ("L1", "iso-8859-1"),
                               ("iso8859-15", "iso-8859-15"), ("latin9", "iso-8859-15"), ("cp1252", "windows-1252")):
            with self.subTest(name=name):
                self.assertEqual(mail_parse.allowed_charset(name), expected)


# --------------------------------------------------------------------------------------
# Header facts
# --------------------------------------------------------------------------------------

class HeaderFacts(ParseCase):
    def test_a_message_with_none_of_the_optional_headers(self):
        headers = self.parse(samples.plain_message()).headers
        self.assertEqual(headers[:8], (False, "absent", "absent", False, False, False, "absent", 0))
        self.assertEqual(headers.authentication_results, ())
        self.assertEqual((headers.from_name, headers.from_address, headers.from_local, headers.from_domain,
                          headers.subject), ("Ann Example", "ann@example.org", "ann", "example.org", "Hello"))

    def test_the_headers_the_reply_rules_read(self):
        parsed = self.parse(samples.header_facts_message(
            auto_submitted="auto-replied", return_path="<>", precedence="Bulk", reply_to="other@example.net",
            suppress="All", list_id="<list.example.net>", list_unsubscribe="<mailto:leave@example.net>"))
        self.assert_clean(parsed)
        headers = parsed.headers
        self.assertTrue(headers.reply_to_present)
        self.assertEqual(headers.return_path, "null")
        self.assertEqual(headers.auto_submitted, "auto")
        self.assertTrue(headers.auto_response_suppress)
        self.assertTrue(headers.list_id_present)
        self.assertTrue(headers.list_unsubscribe_present)
        self.assertEqual(headers.precedence, "bulk")

    def test_auto_submitted_values(self):
        for value, expected in (("no", "no"), ("NO", "no"), (" no ", "no"), ("no; x=y", "no"),
                                ("auto-generated", "auto"), ("auto-replied", "auto"), ("auto-notified", "auto"),
                                ("yes", "auto"), ("", "auto"), ("no (really)", "auto"), ("nope", "auto")):
            with self.subTest(value=value):
                headers = self.parse(samples.header_facts_message(auto_submitted=value)).headers
                self.assertEqual(headers.auto_submitted, expected)

    def test_return_path_values(self):
        for value, expected in (("<>", "null"), (" < > ", "null"), ("<ann@example.org>", "address"),
                                ("ann@example.org", "address"), ("", "address")):
            with self.subTest(value=value):
                self.assertEqual(self.parse(samples.header_facts_message(return_path=value)).headers.return_path,
                                 expected)

    def test_a_null_return_path_among_two_is_reported_as_null(self):
        raw = samples.repeated_header_message("Return-Path", ["<ann@example.org>", "<>"])
        self.assertEqual(self.parse(raw).headers.return_path, "null")

    def test_precedence_values(self):
        self.assertEqual(mail_lists.PRECEDENCE_VALUES, ("absent", "bulk", "list", "junk", "other"))
        for value, expected in (("bulk", "bulk"), ("list", "list"), ("junk", "junk"), ("LIST", "list"),
                                (" Junk ", "junk"), ("first-class", "other"), ("", "other"),
                                ("bulk, list", "other")):
            with self.subTest(value=value):
                self.assertEqual(self.parse(samples.header_facts_message(precedence=value)).headers.precedence,
                                 expected)

    def test_every_authentication_results_header_is_kept_in_order_and_unparsed(self):
        values = samples.authentication_results_values()
        parsed = self.parse(samples.header_facts_message(authentication_results=values))
        self.assert_clean(parsed)
        self.assertEqual(parsed.headers.authentication_results,
                         ("mx.example.com; dkim=pass header.d=example.org; spf=pass smtp.mailfrom=example.org",
                          "mx.example.net; dmarc=fail header.from=example.org"))
        self.assertEqual(parsed.headers.authentication_results_count, 2)
        swapped = self.parse(samples.header_facts_message(authentication_results=values[::-1]))
        self.assertEqual(swapped.headers.authentication_results, parsed.headers.authentication_results[::-1])

    def test_a_reply_to_header_is_only_ever_reported_as_present(self):
        parsed = self.parse(samples.header_facts_message(reply_to="%s@example.net" % MARKER))
        self.assertTrue(parsed.headers.reply_to_present)
        self.assertNotIn(MARKER, repr(parsed.headers))

    def test_the_from_parts_of_an_address_with_a_quoted_local_part(self):
        parsed = self.parse(samples.from_message([b'"a@b c" <"odd@local"@example.org>']))
        self.assertEqual(parsed.headers.from_local, "odd@local")
        self.assertEqual(parsed.headers.from_domain, "example.org")
        self.assertEqual(parsed.headers.from_address, '"odd@local"@example.org')
        self.assertEqual(parsed.headers.from_name, "a@b c")

    def test_no_string_of_a_parsed_message_holds_an_unpaired_surrogate(self):
        raw = samples.mail_message(
            samples.mail_part("text/plain", b"body \xff", "utf-8"), sender=b"J\xf6rg \xff <ann@example.org>",
            subject=b"Note \xff\xc3", headers=[("Authentication-Results", b"mx.example.com; \xff\xfe")])
        parsed = self.parse(raw)

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, tuple):
                for item in value:
                    yield from strings(item)
        for text in strings(parsed):
            text.encode("utf-8")


# --------------------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------------------

class Attachments(ParseCase):
    def test_the_attachment_inventory(self):
        parsed = self.parse(samples.attachments_message())
        self.assert_clean(parsed)
        self.assertEqual(texts(parsed), ["BODY-TEXT"])
        self.assertEqual(
            [(a.attachment_id, a.part_id, a.role, a.media_type, a.extension_class, a.signature) for a in
             parsed.attachments],
            [("a1", "p3", "attachment", "application/pdf", "known", "pdf"),
             ("a2", "p4", "attachment", "application/x-msdownload", "dangerous", "mz"),
             ("a3", "p5", "attachment", "application/pdf", "known", "mz"),
             ("a4", "p6", "attachment", "application/octet-stream", "dangerous", "mz"),
             ("a5", "p7", "attachment", "application/octet-stream", "none", "none"),
             ("a6", "p8", "attachment", "text/html", "other", "none")])    # active content: the rules' caution
        self.assertEqual([a.extension for a in parsed.attachments], ["pdf", "exe", "pdf", "exe", "", "html"])
        self.assertEqual([a.declared_media_type for a in parsed.attachments],
                         ["application/pdf", "application/x-msdownload", "application/pdf",
                          "application/octet-stream", "application/octet-stream", "text/html"])

    def test_the_size_is_that_of_the_decoded_content(self):
        parsed = self.parse(samples.attachments_message([
            samples.attachment_part("a.bin", payload=b"x" * 1234),
            samples.mail_part("application/octet-stream", b"12345", disposition="attachment")]))
        self.assertEqual([a.size for a in parsed.attachments], [1234, 5])

    def test_no_file_name_is_kept_anywhere(self):
        parsed = self.parse(samples.attachments_message([samples.attachment_part("%s-name.pdf" % MARKER)]))
        self.assertEqual(parsed.attachments[0].extension, "pdf")
        self.assertNotIn(MARKER, repr(parsed))

    def test_the_extension_is_read_as_a_file_system_would_read_it(self):
        for name, expected in samples.filename_cases().items():
            with self.subTest(name=name):
                self.assertEqual(mail_parse.read_extension(name), expected)
        # Hidden characters are removed before the name is read, so none can hide an extension.
        self.assertEqual(mail_parse.read_extension("setup.exe" + chr(0x200B)), ("dangerous", "exe"))
        self.assertEqual(mail_parse.read_extension("setup.exe." + chr(0xE0041) + " "), ("dangerous", "exe"))
        self.assertEqual(mail_parse.read_extension("setup.e" + chr(0x200B) + "xe"), ("dangerous", "exe"))
        self.assertEqual(mail_parse.read_extension("invoice" + chr(0x202E) + "fdp.exe"), ("dangerous", "exe"))
        for value in (None, "", 5, b"x.exe"):
            self.assertEqual(mail_parse.read_extension(value), ("none", ""))

    def test_every_dangerous_extension_of_the_lists_is_classed_dangerous(self):
        for extension in mail_lists.DANGEROUS_EXTENSIONS:
            self.assertEqual(mail_parse.read_extension("file." + extension.upper()), ("dangerous", extension))

    def test_each_signature_is_read_from_the_leading_bytes(self):
        for row in mail_lists.SIGNATURES:
            for leading in row.leading:
                with self.subTest(signature=row.name):
                    self.assertEqual(mail_parse.read_signature(leading + b"rest"), row.name)
                    parsed = self.parse(samples.attachments_message([
                        samples.attachment_part("file.dat", payload=leading + b"rest")]))
                    self.assertEqual(parsed.attachments[0].signature, row.name)
        for data in (b"", b"plain text", b" MZ", b"mz"):
            self.assertEqual(mail_parse.read_signature(data), "none")

    def test_a_declared_media_type_is_recorded_only_as_a_word_of_ours(self):
        cases = {"application/pdf": "application/pdf", "image/png": "image/png",
                 "application/x-%s" % MARKER.lower(): "application/other", "image/x-new": "image/other",
                 "%s/%s" % (MARKER.lower(), MARKER.lower()): "other", "x-world/x-vrml": "other"}
        for declared, word in cases.items():
            with self.subTest(declared=declared):
                parsed = self.parse(samples.attachments_message([samples.attachment_part("f.bin", declared)]))
                self.assertEqual(parsed.attachments[0].media_type, word)
                self.assertEqual(parsed.attachments[0].declared_media_type, declared)
                self.assertEqual(parsed.parts[-1].media_type, word)

    def test_an_inline_image_is_inventoried_as_an_attachment(self):
        parsed = self.parse(samples.mixed_message(["plain", "image"]))
        self.assertEqual([(a.role, a.media_type, a.signature) for a in parsed.attachments],
                         [("attachment", "image/png", "png")])

    def test_the_roles_are_those_of_the_lists(self):
        self.assertEqual(mail_lists.PART_ROLES, ("container", "selected", "unselected", "resource",
                                                 "attachment", "nested-message"))
        self.assertEqual(mail_lists.ATTACHMENT_ROLES, ("resource", "attachment", "nested-message"))
        self.assertEqual(mail_lists.EXTENSION_CLASSES, ("none", "dangerous", "known", "other"))
        parsed = self.parse(samples.marker_message(MARKER))
        in_inventory = {a.part_id for a in parsed.attachments}
        for part in parsed.parts:
            self.assertEqual(part.part_id in in_inventory, part.role in mail_lists.ATTACHMENT_ROLES)


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------

class _AnchorWalk(html.parser.HTMLParser):
    """An independent walk of an HTML text, as a later step would do it: the href of every
    <a> start tag that has one, in the order the standard parser reports them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href":
                    self.hrefs.append(value or "")
                    break


class Links(ParseCase):
    def test_the_links_of_an_html_part_in_document_order(self):
        parsed = self.parse(samples.html_links_message())
        self.assert_clean(parsed)
        self.assertEqual(
            [(link.link_id, link.number, link.kind, link.occurrence, link.url, link.host, link.flags)
             for link in parsed.links],
            [("l1", 1, "anchor", 0, "https://www.example.com/a", "www.example.com", ()),
             ("l2", 2, "anchor", 1, "https://login.example.net/", "login.example.net", ("text_mismatch",)),
             ("l3", 3, "text", 0, "www.example.com", "www.example.com", ()),
             ("l4", 4, "text", 1, "https://typed.example.org/page", "typed.example.org", ()),
             ("l5", 5, "anchor", 2, "java" + "script:void(0)", "", ("scheme",)),
             ("l6", 6, "anchor", 3, "http://192.0.2.7/x", "192.0.2.7", ("ip_literal",)),
             ("l7", 7, "anchor", 4, "/relative/path", "", ()),
             ("l8", 8, "text", 2, "www.plain.example.com", "www.plain.example.com", ())])
        self.assertEqual({link.part_id for link in parsed.links}, {"p1"})

    def test_text_inside_script_and_style_elements_holds_no_link(self):
        parsed = self.parse(samples.html_links_message())
        hosts = [link.host for link in parsed.links]
        self.assertNotIn("style.example.com", hosts)
        self.assertNotIn("script.example.com", hosts)

    def test_the_anchors_are_numbered_as_an_independent_walk_meets_them(self):
        for raw in (samples.html_links_message(), samples.marker_message(MARKER),
                    samples.many_links_message(40), samples.two_part_links_message()):
            parsed = self.parse(raw)
            for part in parsed.selected:
                if part.subtype != "html":
                    continue
                walk = _AnchorWalk()
                walk.feed(part.text)
                walk.close()
                anchors = [link for link in parsed.links if link.part_id == part.part_id and link.kind == "anchor"]
                self.assertEqual([link.url for link in anchors], walk.hrefs)
                self.assertEqual([link.occurrence for link in anchors], list(range(len(anchors))))

    def test_the_text_links_of_a_plain_part_are_the_matches_of_the_shared_pattern(self):
        parsed = self.parse(samples.plain_links_message())
        self.assert_clean(parsed)
        self.assertEqual([(link.kind, link.occurrence, link.url, link.host, link.flags) for link in parsed.links],
                         [("text", 0, "https://www.example.com/a?b=c", "www.example.com", ()),
                          ("text", 1, "http://user@host.example.net/x", "host.example.net", ("userinfo",)),
                          ("text", 2, "WWW.xn--e1afmkfd.example", "www.xn--e1afmkfd.example", ("punycode",))])
        text = parsed.selected[0].text
        cut = [m.group(0).rstrip(mail_lists.URL_TRAILING_PUNCTUATION) for m in mail_lists.URL_IN_TEXT.finditer(text)]
        self.assertEqual([link.url for link in parsed.links], cut)
        self.assertEqual(mail_parse.text_urls(text), cut)

    def test_links_are_numbered_across_the_selected_parts_and_not_read_from_attachments(self):
        parsed = self.parse(samples.two_part_links_message())
        self.assertEqual([(link.number, link.part_id, link.kind, link.occurrence, link.host) for link in parsed.links],
                         [(1, "p2", "text", 0, "one.example.com"), (2, "p3", "anchor", 0, "two.example.com")])
        self.assertNotIn("three.example.com", repr(parsed.links))

    def test_each_flag_of_the_url_reader_reaches_the_inventory(self):
        for flag, urls in samples.flagged_urls().items():
            for url in urls:
                with self.subTest(flag=flag, url=ascii(url)):
                    body = '<a href="%s">x</a>' % url.replace("&", "&amp;").replace('"', "&quot;")
                    parsed = self.parse(samples.mail_message(samples.mail_part("text/html", body, "utf-8")))
                    self.assertEqual(len(parsed.links), 1)
                    self.assertEqual(parsed.links[0].flags, mail_reuse.read_url(parsed.links[0].url).flags())
                    self.assertIn(flag, parsed.links[0].flags)

    def test_a_link_with_a_bidi_control_keeps_it_in_memory_for_the_rules(self):
        body = '<a href="%s">x</a>' % samples.bidi_url()
        parsed = self.parse(samples.mail_message(samples.mail_part("text/html", body, "utf-8")))
        self.assertEqual(mail_reuse.BIDI.count(parsed.links[0].url), 1)
        self.assertEqual(mail_reuse.STRIPPED.find(record_text(parsed)), [])

    def test_anchor_text_that_names_another_host_is_flagged(self):
        cases = [
            ("https://a.example.com/", "a.example.com", False),
            ("https://a.example.com/", "www.a.example.com", False),
            ("https://www.a.example.com/x", "https://a.example.com/docs/index.html", False),
            ("https://a.example.com/", "Click here", False),
            ("https://a.example.com/", "", False),
            ("https://a.example.com/", "b.example.net", True),
            ("https://a.example.com/", "https://b.example.net/a.example.com", True),
            ("https://a.example.com/", "a.example.com or b.example.net", True),
            ("https://evil.example.net/", "www.A.example.com", True),
            ("/relative", "a.example.com", True),
            ("mailto:ann@example.org", "ann@example.org", False),
        ]
        for href, text, flagged in cases:
            with self.subTest(href=href, text=text):
                body = '<p><a href="%s"><b>%s</b></a> tail b.example.net</p>' % (href, text)
                parsed = self.parse(samples.mail_message(samples.mail_part("text/html", body, "utf-8")))
                anchor = [link for link in parsed.links if link.kind == "anchor"][0]
                self.assertEqual("text_mismatch" in anchor.flags, flagged)

    def test_an_anchor_without_href_is_not_a_link_and_the_first_href_counts(self):
        body = '<a name="x">one</a><a href="https://first.example.com/" href="https://second.example.com/">two</a><a href>three</a>'
        parsed = self.parse(samples.mail_message(samples.mail_part("text/html", body, "utf-8")))
        self.assertEqual([(link.kind, link.url) for link in parsed.links],
                         [("anchor", "https://first.example.com/"), ("anchor", "")])

    def test_character_references_in_an_href_are_decoded(self):
        body = '<a href="https://a.example.com/?x=1&amp;y=2&#x2f;z">x</a>'
        parsed = self.parse(samples.mail_message(samples.mail_part("text/html", body, "utf-8")))
        self.assertEqual(parsed.links[0].url, "https://a.example.com/?x=1&y=2/z")

    def test_a_part_with_an_unsupported_charset_has_no_link(self):
        body = b'<a href="https://a.example.com/">x</a>'
        parsed = self.parse(samples.charset_message("utf-7", body, subtype="html"))
        self.assertEqual(parsed.links, ())

    def test_find_links_is_the_one_way_links_are_found(self):
        for raw in (samples.html_links_message(), samples.plain_links_message()):
            parsed = self.parse(raw)
            part = parsed.selected[0]
            found = mail_parse.find_links(part.subtype, part.text)
            self.assertEqual([(kind, url) for kind, url, _text in found],
                             [(link.kind, link.url) for link in parsed.links])

    def test_the_link_words_are_those_of_the_lists(self):
        self.assertEqual(mail_lists.LINK_KINDS, ("anchor", "text"))
        self.assertEqual(mail_lists.LINK_FLAGS, tuple(flag for flag, _rule in mail_lists.LINK_FLAG_RULES)
                         + ("text_mismatch",))
        self.assertEqual(mail_lists.LINK_TEXT_MISMATCH_RULE, "link-text-mismatch")
        self.assertIn(mail_lists.LINK_TEXT_MISMATCH_RULE, mail_lists.RULES)
        self.assertEqual(mail_lists.RULES[mail_lists.LINK_TEXT_MISMATCH_RULE].rule_class, "caution")

    def test_the_pattern_of_a_url_typed_as_text(self):
        pattern = mail_lists.URL_IN_TEXT
        self.assertEqual(pattern.pattern, mail_lists.URL_IN_TEXT_PATTERN)
        text = ('see https://a.example/x?y=1, and www.b.example. Or <http://c.example> FTP://d.example/q"z '
                "ftps://e.example/ not mailto:x@f.example nor g.example nor wwwx.h.example")
        self.assertEqual(mail_parse.text_urls(text),
                         ["https://a.example/x?y=1", "www.b.example", "http://c.example", "FTP://d.example/q",
                          "ftps://e.example/"])
        for separator in (" ", "\t", "\n", "\r", "\x00", "\x1f", "\x7f", "<", ">", '"', "'", "\x60", chr(0xA0),
                          chr(0x2028)):
            with self.subTest(separator=ascii(separator)):
                self.assertEqual(mail_parse.text_urls("http://a.example/b" + separator + "c"), ["http://a.example/b"])
        self.assertEqual(mail_parse.text_urls("(http://a.example/b)."), ["http://a.example/b"])
        self.assertEqual(mail_parse.text_urls("no link here"), [])


# --------------------------------------------------------------------------------------
# What may be recorded
# --------------------------------------------------------------------------------------

class Recordable(ParseCase):
    def test_every_field_is_either_recordable_or_memory_only(self):
        types = (mail_parse.GapItem, mail_parse.HeaderAmbiguity, mail_parse.PartItem, mail_parse.AttachmentItem,
                 mail_parse.LinkItem, mail_parse.SelectedPart, mail_parse.HeaderFacts, mail_parse.ParsedMessage)
        self.assertEqual(sorted(mail_parse.RECORDABLE_FIELDS), sorted(cls.__name__ for cls in types))
        self.assertEqual(sorted(mail_parse.MEMORY_ONLY_FIELDS), sorted(cls.__name__ for cls in types))
        for cls in types:
            recordable = mail_parse.RECORDABLE_FIELDS[cls.__name__]
            memory = mail_parse.MEMORY_ONLY_FIELDS[cls.__name__]
            self.assertEqual(set(recordable) & set(memory), set())
            self.assertEqual(set(recordable) | set(memory), set(cls._fields))
        self.assertEqual(mail_parse.MEMORY_ONLY_FIELDS["AttachmentItem"], ("declared_media_type", "extension"))
        self.assertEqual(mail_parse.MEMORY_ONLY_FIELDS["LinkItem"], ("url", "host"))
        self.assertEqual(mail_parse.MEMORY_ONLY_FIELDS["SelectedPart"], ("text",))
        self.assertEqual(mail_parse.MEMORY_ONLY_FIELDS["HeaderFacts"],
                         ("from_name", "from_address", "from_local", "from_domain", "subject",
                          "authentication_results"))
        self.assertIn("from_name_irregular", mail_parse.RECORDABLE_FIELDS["HeaderFacts"])

    def test_the_marker_message_really_carries_the_marker_in_memory(self):
        parsed = self.parse(samples.marker_message(MARKER))
        headers = parsed.headers
        for value in (headers.from_name, headers.from_address, headers.from_local, headers.from_domain,
                      headers.subject, headers.authentication_results[0], parsed.selected[0].text,
                      parsed.links[0].url, parsed.links[0].host, parsed.links[1].url):
            self.assertIn(MARKER.lower(), value.lower())
        self.assertTrue(any(MARKER.lower() in a.declared_media_type for a in parsed.attachments))
        self.assertTrue(any(MARKER.lower() == a.extension for a in parsed.attachments))

    def test_a_marker_in_every_field_the_sender_controls_reaches_no_recordable_field(self):
        raw = samples.marker_message(MARKER)
        self.assertGreater(raw.count(MARKER.encode("ascii")), 40)
        parsed = self.parse(raw)
        self.assertEqual(len(parsed.selected), 1)
        self.assertEqual(len(parsed.attachments), 6)
        self.assertEqual(len(parsed.links), 2)
        self.assertNotIn(MARKER.lower(), record_text(parsed).lower())

    def test_the_marker_reaches_no_recordable_field_on_any_early_result(self):
        for label, raw in samples.marker_variants(MARKER).items():
            bounds = {"over-bytes": {"max_bytes": 100}, "over-depth": {"max_depth": 2}}.get(label, {})
            with self.subTest(label=label):
                self.assertIn(MARKER.encode("ascii"), raw)
                parsed = self.parse(raw, **bounds)
                self.assertNotIn(MARKER.lower(), record_text(parsed).lower())
                self.assertTrue(parsed.gaps or parsed.header_ambiguous or parsed.attachment_only)

    def test_the_recordable_form_holds_none_of_the_memory_only_fields(self):
        data = mail_parse.recordable(self.parse(samples.marker_message(MARKER)))
        forbidden = {name for names in mail_parse.MEMORY_ONLY_FIELDS.values() for name in names}

        def keys(value):
            if isinstance(value, dict):
                for key, inner in value.items():
                    yield key
                    yield from keys(inner)
            elif isinstance(value, list):
                for inner in value:
                    yield from keys(inner)
        self.assertEqual(set(keys(data)) & forbidden, set())
        self.assertEqual(data["links"][0], {"link_id": "l1", "number": 1, "part_id": "p6", "kind": "anchor",
                                            "occurrence": 0, "flags": ["text_mismatch"]})

    def test_the_recordable_form_of_a_plain_message(self):
        self.assertEqual(mail_parse.recordable(self.parse(samples.plain_message())), {
            "over_bound": "", "attachment_only": False, "gaps": [], "header_ambiguous": [],
            "parts": [{"part_id": "p1", "media_type": "text/plain", "role": "selected", "depth": 1}],
            "attachments": [], "links": [],
            "selected": [{"part_id": "p1", "subtype": "plain", "charset": "utf-8", "replaced": 0}],
            "headers": {"reply_to_present": False, "return_path": "absent", "auto_submitted": "absent",
                        "auto_response_suppress": False, "list_id_present": False,
                        "list_unsubscribe_present": False, "precedence": "absent",
                        "authentication_results_count": 0, "from_name_irregular": False}})

    def test_the_gap_details_are_words_of_the_lists(self):
        self.assertEqual(mail_lists.GAP_DETAILS,
                         ("", "from", "part", "structure", "transfer-encoding", "error", "body", "header",
                          "bytes", "depth", "parts", "header-lines", "header-length", "links", "time",
                          # the forms of html-ambiguous, added by the view (WP-2)
                          "comment-unclosed", "comment-conditional", "element", "null-byte", "tokens",
                          # a header line ended by a carriage return alone (WP-4b follow-up)
                          "bare-cr",
                          # fix round 1: a related root that is not the first part, an alternative whose body
                          # is marked as an attachment, a style block not tokenised, an outside style sheet
                          "start", "disposition", "style", "external"))


# --------------------------------------------------------------------------------------
# Fix round 1: time (V7), the same body for reader and model (V8), the From address (V9)
# --------------------------------------------------------------------------------------

class MimeHeaderBound(ParseCase):
    """Reviews A F6: a header that decides how a part is read is bounded BEFORE the standard parser runs."""

    def test_a_long_deciding_header_stops_the_parse_and_an_ordinary_one_does_not(self):
        for name, (raw, over) in samples.long_mime_header_messages().items():
            with self.subTest(case=name):
                parsed = self.parse(raw)
                if over:
                    self.assertEqual(parsed.over_bound, "header-length")
                    self.assertEqual(gaps(parsed), {("structure-over-bound", "header-length"): 1})
                    self.assertEqual((parsed.selected, parsed.parts, parsed.headers.from_address), ((), (), None))
                else:
                    self.assertEqual(parsed.over_bound, "")
                    self.assertNotIn("structure-over-bound", gap_names(parsed))
        self.assertEqual(mail_lists.MIME_HEADER_NAMES,
                         ("content-type", "content-disposition", "content-transfer-encoding"))

    def test_the_standard_parser_never_sees_a_message_over_the_bound(self):
        raw = samples.long_mime_header_messages()["semicolons"][0]
        with mock.patch.object(mail_parse.email.parser, "BytesParser", side_effect=AssertionError("parsed")) as parser:
            self.assertEqual(mail_parse.parse(raw).over_bound, "header-length")
            parser.assert_not_called()

    def test_the_bound_is_read_from_the_raw_bytes(self):
        over = mail_parse.mime_header_over_bound
        self.assertFalse(over(b"Content-Type: " + b"a" * 1000 + b"\r\n\r\nx", 1000))
        self.assertTrue(over(b"Content-Type: " + b"a" * 1000 + b"\r\n\r\nx", 1000 - 1))
        self.assertTrue(over(b"X: y\r\ncontent-disposition:" + b"a" * 600 + b"\r\n " + b"b" * 600 + b"\r\n\r\n", 1000))
        self.assertTrue(over(b"X: y\ncontent-type :" + b"a" * 600 + b"\n\t" + b"b" * 600 + b"\n\n", 1000))
        self.assertTrue(over(b"X: y\rContent-Transfer-Encoding:" + b"a" * 1200, 1000))
        self.assertFalse(over(b"Subject: " + b"a" * 5000 + b"\r\n\r\n", 1000))
        self.assertFalse(over(b"X-Content-Type: " + b"a" * 5000 + b"\r\n\r\n", 1000))
        self.assertFalse(over(b"A: b\r\n\r\nsee Content-Type: " + b"a" * 5000, 1000))
        self.assertFalse(over(b"Content-Type: text/plain\r\n\r\n" + b"a" * 5000, 1000))
        self.assertFalse(over(b"", 1000))

    def test_fifty_parts_with_headers_at_the_bound_are_read_quickly(self):
        import time
        header = b"Content-Type: text/plain; " + b";" * 950
        parts = b"".join(b"--BB\r\n" + header + b"\r\n\r\nhi\r\n" for _ in range(48))
        raw = samples.mail_message(b'Content-Type: multipart/mixed; boundary="BB"\r\n\r\n' + parts + b"--BB--\r\n")
        started = time.monotonic()
        parsed = mail_parse.parse(raw)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(parsed.over_bound, "")

    def test_a_header_is_parsed_once_however_often_it_is_read(self):
        policy = mail_parse._keeping_policy()
        calls = []
        real = email.policy.EmailPolicy.header_fetch_parse

        def counting(self, name, value):
            calls.append(name.lower())
            return real(self, name, value)

        with mock.patch.object(email.policy.EmailPolicy, "header_fetch_parse", counting):
            message = email.parser.BytesParser(policy=policy).parsebytes(samples.plain_message())
            for _ in range(5):
                message.get_content_type()
                message.get_param("charset")
                message["from"]
        self.assertEqual(calls.count("content-type"), 1)
        self.assertEqual(calls.count("from"), 1)
        self.assertIs(message["from"], message["from"])
        # two parses share nothing
        self.assertIsNot(mail_parse._keeping_policy().kept, policy.kept)


class ParseTime(ParseCase):
    """V7: the wall-clock budget, checked inside the loops of the parser."""

    def spent(self):
        import time
        budget = mail_reuse.Budget(0.0, every=1)
        time.sleep(0.01)
        return budget

    def test_a_spent_budget_stops_the_parse_with_the_time_bound(self):
        for raw in (samples.plain_message(), samples.ordinary_alternative_message(), samples.html_links_message()):
            parsed = mail_parse.parse(raw, mail_parse.DEFAULT_BOUNDS, self.spent())
            self.assert_recordable_vocabulary(parsed)
            self.assertEqual(parsed.over_bound, "time")
            self.assertEqual(gaps(parsed), {("structure-over-bound", "time"): 1})
            self.assertEqual((parsed.gaps[0].gap_class, parsed.gaps[0].reply_effect), ("block", "held"))
            self.assertEqual((parsed.selected, parsed.parts, parsed.links, parsed.headers.from_address),
                             ((), (), (), None))

    def test_a_parse_starts_its_own_budget_from_the_bounds(self):
        self.assert_clean(self.parse(samples.plain_message()))
        self.assert_clean(self.parse(samples.plain_message(), max_seconds=None))
        self.assert_clean(mail_parse.parse(samples.plain_message(), mail_parse.DEFAULT_BOUNDS, mail_reuse.Budget(60.0)))
        self.assertEqual(mail_parse.DEFAULT_BOUNDS.max_seconds, mail_lists.SCAN_SECONDS)
        self.assertIn("time", mail_lists.PARSE_BOUND_NAMES)

    def test_the_budget_itself(self):
        import time
        never = mail_reuse.Budget(None)
        for _ in range(1000):
            never.check()
        never.check_now()
        live = mail_reuse.Budget(60.0, every=1)
        live.check()
        live.check_now()
        spent = mail_reuse.Budget(0.0, every=4)
        time.sleep(0.01)
        for _ in range(3):
            spent.check()               # the clock is read on every fourth call only
        with self.assertRaises(mail_reuse.TimeUp):
            spent.check()
        with self.assertRaises(mail_reuse.TimeUp):
            spent.check_now()
        self.assertEqual(str(mail_reuse.TimeUp()), "")


class SameBodyForReaderAndModel(ParseCase):
    """Review A F7 (V8): three MIME shapes a mail reader may show another body for."""

    def test_a_deciding_parameter_given_twice_is_header_ambiguous(self):
        for name, (raw, repeated) in samples.repeated_parameter_messages().items():
            with self.subTest(case=name):
                parsed = self.parse(raw)
                found = {(item.header, item.reason): item.count for item in parsed.header_ambiguous}
                if repeated:
                    self.assertEqual(found, {("content-type", "parameter"): 1})
                else:
                    self.assertEqual(found, {})

    def test_a_disposition_parameter_given_twice_is_header_ambiguous(self):
        # fix round 2 (P1): Content-Disposition is read the same way
        for name, (raw, repeated) in samples.repeated_disposition_parameter_messages().items():
            with self.subTest(case=name):
                parsed = self.parse(raw)
                found = {(item.header, item.reason): item.count for item in parsed.header_ambiguous}
                self.assertEqual(found, {("content-disposition", "parameter"): 1} if repeated else {})

    def test_the_parameter_names_are_read_from_the_header_as_written(self):
        names = mail_parse._repeated_parameters
        self.assertEqual(names("multipart/mixed; boundary=a; boundary=b"), ["boundary"])
        self.assertEqual(names("text/plain; charset=a; CharSet=b; boundary=x; BOUNDARY=y"), ["boundary", "charset"])
        self.assertEqual(names("multipart/related; start=a; start=b"), ["start"])
        self.assertEqual(names("text/plain; charset*0=a; charset*0=b"), ["charset"])
        self.assertEqual(names("text/plain; charset*=utf-8''a; charset=b"), ["charset"])
        self.assertEqual(names("text/plain"), [])
        self.assertEqual(names(""), [])
        # fix round 2 (P1, review A N10): every name, every form; a deciding one also in a string
        self.assertEqual(names("text/plain; charset*0=a; charset*1=b"), ["charset"])
        self.assertEqual(names("text/plain; name*0=a; name*1=b"), [])
        self.assertEqual(names("text/plain; name*0=a; name*0=b; format=x; Format=y"), ["format", "name"])
        self.assertEqual(names('text/plain; name="x; charset=a; charset=b"'), ["charset"])
        self.assertEqual(names('text/plain; name="a\\"; charset=x"; charset=y'), ["charset"])
        self.assertEqual(names('text/plain; name="restart=1; start=2"'), [])
        self.assertEqual(names('multipart/mixed; boundary="Apple-Mail=_x"; charset=utf-8;'), [])
        # fix round 3 (P1): a deciding value is a plain token or a quoted string with nothing a reader may decode
        self.assertEqual(names("multipart/mixed; boundary=Apple-Mail=_x; charset=utf-8;"), ["boundary"])
        for value in ('multipart/mixed; boundary="=?utf-8?q?B?="', 'multipart/mixed; boundary="=?utf-8?b?Qg==?="',
                      'multipart/mixed; boundary="Qg=="', 'multipart/mixed; boundary="\\B"', 'text/plain; charset="a=?b"'):
            self.assertEqual(names(value), ["boundary" if "boundary" in value else "charset"], value)
        for value in ('multipart/mixed; boundary="----=_NextPart_000_0012_01DA0A1B.2C3D4E50"',
                      'multipart/alternative; boundary="000000000000a1b2c3d4e5f6"', 'multipart/mixed; boundary=simple-B_1',
                      'multipart/mixed; boundary="_000_DB9PR01MB1234EURP_"', 'text/plain; name="=?utf-8?q?a?="'):
            self.assertEqual(names(value), [], value)
        # ... and a comment anywhere in the list makes it one that does not parse
        for value in ("multipart/mixed; boundary=B(x)", "multipart/mixed; boundary=B (x)", "text/plain (x); charset=a",
                      'text/plain; name="a" (b)', "text/plain; charset=(a)utf-8"):
            self.assertIsNone(names(value), value)
        # ... but a parenthesis inside a quoted string is text, not a comment (re-check F1)
        for value in ('application/pdf; name="Invoice (1).pdf"', 'attachment; filename="Scan (2).jpg"; size=10',
                      'image/jpeg; name="a)b(c.jpg"'):
            self.assertEqual(names(value), [], value)
        # fix round 3 (P2, Codex 6): a section suffix of any length; a leading zero or more than three digits
        self.assertEqual(names("text/plain; name=\"a\"; name*00000*=utf-8''b"), ["name"])
        self.assertEqual(names("text/plain; name*0=a; name*01=b"), ["name"])
        self.assertEqual(names("text/plain; name*0=a; name*1000=b"), ["name"])
        self.assertEqual(names("text/plain; name*0=a; name*999=b"), [])
        self.assertEqual(names("text/plain; name*0=a; name*10=b"), [])
        self.assertEqual(mail_parse.SECTION_MAX_DIGITS, 3)
        for value in ("multipart/mixed; boundary=AAA boundary=BBB", "text/plain; charset=", "text/plain; =x",
                      'text/plain; name="a', "text/plain; charset=a;; format=b", 'text/"plain"; charset=a',
                      "text/plain; charset=a; junk"):
            self.assertIsNone(names(value), value)

    def test_a_body_marked_as_an_attachment_makes_the_alternative_ambiguous(self):
        for name, (raw, ambiguous) in samples.disposition_alternative_messages().items():
            with self.subTest(case=name):
                parsed = self.parse(raw)
                self.assertEqual(("alternative-ambiguous", "disposition") in gaps(parsed), ambiguous)
                if ambiguous:
                    gap = [item for item in parsed.gaps if item.detail == "disposition"][0]
                    self.assertEqual((gap.gap_class, gap.reply_effect), ("block", "held"))
                else:
                    self.assertEqual(gaps(parsed), {})
                    self.assertTrue(parsed.selected)
                # the part marked as an attachment is never the view
                self.assertNotIn("ATTACHED", "".join(texts(parsed)))

    def test_a_related_start_that_is_not_the_first_part(self):
        parsed = self.parse(samples.related_message("start"))
        self.assertEqual(gaps(parsed), {("related-root-invalid", "start"): 1})
        inside = samples.mail_message(samples.mail_multipart("alternative", [
            samples.mail_part("text/plain", "PLAIN", "utf-8"),
            samples.mail_multipart("related", [
                samples.mail_part("image/png", samples.png_bytes(), encoding="base64", content_id="<i@example.org>"),
                samples.mail_part("text/html", "<p>ROOT</p>", "utf-8", content_id="<r@example.org>")],
                params='; start="<r@example.org>"')]))
        parsed = self.parse(inside)
        self.assertEqual(gaps(parsed).get(("related-root-invalid", "start")), 1)
        self.assert_clean(self.parse(samples.related_message("first")))
        self.assert_clean(self.parse(samples.related_message("start-first")))


class FromAddress(ParseCase):
    """Reviews A F10 and C F5 (V9): an address that only looks like another is no address to reply to."""

    def test_an_address_that_is_not_plain_is_a_defect_on_from(self):
        for name, (value, plain) in samples.odd_from_addresses().items():
            with self.subTest(case=name):
                parsed = self.parse(samples.mail_message(sender=None, headers=[(b"From", value)]))
                blocked = ("parse-defect", "from") in gaps(parsed) or bool(parsed.header_ambiguous)
                self.assertEqual(blocked, not plain)
                if plain:
                    self.assertIsNotNone(parsed.headers.from_address)

    def test_what_a_plain_address_is(self):
        plain = mail_parse.plain_address
        self.assertTrue(plain("ann", "example.org"))
        self.assertTrue(plain("ann+tag.x_y", "mail.example.org"))
        self.assertTrue(plain("jos" + chr(0xE9), "example.org"))
        for local, domain in (("ann", "ex" + chr(0x430) + "mple.org"), ("ann", "example.org" + chr(0x200B)),
                              ("a" + chr(0x200D) + "nn", "example.org"), ("ann ", "example.org"),
                              ("a\tnn", "example.org"), ("ann", ""), ("", "example.org"), (None, "example.org"),
                              ("ann" + chr(0x0301), "example.org"), (chr(0xFF41) + "nn", "example.org"),
                              ("ann", "example" + chr(0x3002) + "org"), ("a" + chr(0x3164) + "n", "example.org"),
                              ("ann", None)):
            self.assertFalse(plain(local, domain), ascii((local, domain)))


class Latin1AsWindows1252(ParseCase):
    """Review A F11 (V9): a part labelled iso-8859-1 is decoded as mail readers decode it."""

    def test_the_punctuation_of_windows_1252_is_punctuation_not_a_line_break(self):
        body = b"I don\x92t know \x93why\x94 \x96 thanks \x85"
        for label in ("iso-8859-1", "ISO-8859-1", "latin1", "l1"):
            with self.subTest(charset=label):
                parsed = self.parse(samples.charset_message(label, body))
                self.assertEqual(gaps(parsed), {})
                text = texts(parsed)[0]
                self.assertEqual(text, "I don" + chr(0x2019) + "t know " + chr(0x201C) + "why" + chr(0x201D) + " "
                                 + chr(0x2013) + " thanks " + chr(0x2026))
                self.assertEqual(parsed.selected[0].charset, "iso-8859-1")
        # the same bytes under iso-8859-15, which mail readers do read as itself, stay controls
        other = self.parse(samples.charset_message("iso-8859-15", body))
        self.assertIn(chr(0x92), texts(other)[0])

    def test_ordinary_latin_1_text_reads_as_before(self):
        parsed = self.parse(samples.charset_message("iso-8859-1", b"caf\xe9 na\xefve \xa3 5"))
        self.assertEqual(texts(parsed), ["caf" + chr(0xE9) + " na" + chr(0xEF) + "ve " + chr(0xA3) + " 5"])
        self.assertEqual(parsed.selected[0].replaced, 0)


# --------------------------------------------------------------------------------------
# The module itself
# --------------------------------------------------------------------------------------

STDLIB_ALLOWED = {"__future__", "codecs", "email.parser", "email.policy", "html.parser", "re", "typing",
                  "unicodedata"}
OWN_ALLOWED = {"mail_lists", "mail_reuse"}
# The import guard of the design, by name.
FORBIDDEN_MODULES = {"smtplib", "imaplib", "poplib", "ftplib", "socket", "ssl", "http", "asyncio", "subprocess",
                     "multiprocessing", "ctypes", "urllib", "os", "shutil", "tempfile", "pathlib", "io"}


class ModuleShape(unittest.TestCase):
    def setUp(self):
        self.source = (SCRIPTS / "mail_parse.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def imported(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                names.add(node.module)
        return names

    def test_the_module_imports_only_the_standard_library_and_its_one_callee(self):
        names = self.imported()
        self.assertEqual(names - STDLIB_ALLOWED, OWN_ALLOWED)
        for name in names:
            self.assertNotIn(name.split(".")[0], FORBIDDEN_MODULES)
        for other in ("mail_view", "mail_frame", "mail_rules", "mail_sender", "mail_state", "mail_scan"):
            self.assertNotIn(other, self.source)

    def test_the_module_opens_nothing_and_runs_nothing(self):
        called = {node.func.id for node in ast.walk(self.tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        for name in ("open", "exec", "eval", "compile", "__import__", "print", "input"):
            self.assertNotIn(name, called)

    def test_the_source_is_ascii_with_escapes_for_the_rest(self):
        self.assertTrue((SCRIPTS / "mail_parse.py").read_bytes().isascii())
        self.assertTrue((HERE / "test_mail_parse.py").read_bytes().isascii())
        self.assertTrue((HERE / "samples.py").read_bytes().isascii())
        self.assertTrue((SCRIPTS / "mail_lists.py").read_bytes().isascii())

    def test_the_standard_parser_is_used_with_the_default_policy(self):
        # the default policy, in a subclass that keeps each parsed header (fix round 1): nothing else differs
        self.assertIn("email.parser.BytesParser(policy=_keeping_policy())", self.source)
        self.assertNotIn("compat32", self.source)
        policy = mail_parse._keeping_policy()
        self.assertIsInstance(policy, email.policy.EmailPolicy)
        for name in ("max_line_length", "linesep", "cte_type", "raise_on_defect", "utf8", "refold_source",
                     "header_factory", "content_manager", "mangle_from_"):
            self.assertEqual(getattr(policy, name), getattr(email.policy.default, name), name)
        self.assertIs(policy.header_factory, email.policy.default.header_factory)
        own = [name for name, value in vars(mail_parse._KeepingPolicy).items() if callable(value)]
        self.assertEqual(own, ["header_fetch_parse"])

    def test_the_manifest_lists_the_builders_of_this_component(self):
        manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["builders"]["mail-parse"], list(samples.BUILDERS["mail-parse"]))
        self.assertGreaterEqual(len(manifest["builders"]["mail-parse"]), 40)
        self.assertEqual(manifest["stored_sample_files"], [])

    def test_the_words_the_parser_uses_are_in_the_lists(self):
        self.assertEqual(mail_lists.NESTED_MESSAGE_SUBTYPES, ("rfc822", "global", "news"))
        self.assertEqual(mail_lists.SELECTED_SUBTYPES, ("plain", "html"))
        self.assertEqual(mail_lists.AUTO_SUBMITTED_VALUES, ("absent", "no", "auto"))
        self.assertEqual(mail_lists.RETURN_PATH_VALUES, ("absent", "null", "address"))
        self.assertEqual(mail_lists.MAX_LINKS, 1000)
        self.assertEqual(mail_lists.ANCHOR_TEXT_MAX_CHARS, 500)
        self.assertEqual(len(set(mail_lists.COMMON_MEDIA_TYPES)), len(mail_lists.COMMON_MEDIA_TYPES))
        for media in mail_lists.COMMON_MEDIA_TYPES:
            self.assertRegex(media, r"^[a-z]+/[a-z0-9.+-]+$")
            self.assertIn(media.split("/")[0], mail_lists.MEDIA_MAIN_TYPES)


if __name__ == "__main__":
    unittest.main()
