#!/usr/bin/env python3
"""mail-scan -- rules_reference.py (#351 WP-5, component mail-scan-wiring).

Writes `references/rules-and-gaps.md` FROM the scripts, so the reference cannot drift from
them: every rule id and gap of `mail_lists.py` as a table, the override table, and every
public constant of `mail_lists.py` (and the fixed words of the other scripts) in a form
`parse()` reads back. `test_mail_wiring.py` holds the file equal to `render()` and compares
what `parse()` reads with the modules, value by value.

    python3 skills/mail-scan/tests/rules_reference.py --write     rewrite the reference
    python3 skills/mail-scan/tests/rules_reference.py --check     exit 1 when it is stale

HOW A VALUE IS PRINTED. As JSON, ASCII only: a character outside printable ASCII is written
as a backslash-u escape, and so are the two angle brackets, so no hidden character, no tag
and no chat-template token stands in the reference as itself. Bytes are {"bytes": hex}, a
compiled pattern {"regex": text, "flags": [names]}, a set {"set": [sorted]}, a named tuple an
object of its fields. `plain()` is that form; a test compares `plain()` of the live value with
what the reference holds.

Phrases and tokens in the lists read like an instruction or like a chat-template turn. They
are entries of a list, printed as data. Nothing this file writes is addressed to a reader.

Stdlib only. It reads the scripts and writes the one reference file; nothing else.
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
import tokenize
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
REFERENCE = os.path.join(SKILL, "references", "rules-and-gaps.md")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import mail_lists  # noqa: E402
import mail_reuse  # noqa: E402
import mail_scan  # noqa: E402
import mail_sender  # noqa: E402
import mail_state  # noqa: E402
import mailscan  # noqa: E402

LINE_WIDTH = 110
BACKSLASH_U = chr(0x5C) + "u"
FENCE = "`" * 3
BANNER = re.compile(r"^# -{20,}$")
ENTRY = re.compile(r"^([A-Z][A-Z0-9_]*) = (.*)$")
# The two tables of mail_lists that are printed as tables of their own, not as entries.
TABLE_NAMES = ("RULES", "GAPS")

# The fixed words of the other scripts: (module, heading, names). Each name is printed like
# an entry of mail_lists.
OTHER_MODULES: Tuple[Tuple[Any, str, Tuple[str, ...]], ...] = (
    (mail_reuse, "Character classes (`mail_reuse.py`)", ("TAG_RANGES", "BIDI_RANGES", "PINNED_SYMBOLS",
                                                         "KEY_BLOCK_MAX_CHARS")),
    (mail_sender, "Sender words (`mail_sender.py`)", ("SENDER_STATUSES", "SENDER_REASONS")),
    (mail_state, "State words (`mail_state.py`)", (
        "SCHEMA_ID", "OVERRIDE_SCHEMA_ID", "SCANNER_VERSION", "ENV_ROOT", "DEFAULT_ROOT_PARTS", "STATE_DIRS",
        "FILE_OVERRIDES", "FILE_KEY", "FILE_LAST_PURGE", "FILE_LOCK", "MODE_DIR", "MODE_FILE", "KEY_BYTES",
        "ERRORS", "OVERRIDE_REFUSALS", "MODE_LABELS", "RETENTION_RUNNING", "RETENTION_NOT_RUNNING")),
    (mail_scan, "Library words (`mail_scan.py`)", (
        "CONFIG_SCHEMA_ID", "CONFIG_KEYS", "PROFILE_KEYS", "MAX_BYTES_LIMIT", "CONFIG_MAX_FILE_BYTES",
        "CONFIG_MAX_ENTRIES", "ADDRESS_MAX_CHARS", "HOST_MAX_CHARS", "PHONE_MAX_CHARS",
        "AUTHSERV_ID_MAX_CHARS", "PACK_PATH_MAX_CHARS", "CANARY_MAX_CHARS", "CONFIG_CODES",
        "CONFIG_KEY_WORDS", "INPUT_CODES", "SCAN_FAILURES", "CALIBRATE_SUFFIX", "CALIBRATE_MAX_FILES",
        "FORBIDDEN_MODULES", "FORBIDDEN_MODULES_MORE", "URLLIB_ALLOWED", "FORBIDDEN_OS_NAMES",
        "FORBIDDEN_OS_PREFIXES", "GUARD_KINDS", "GUARD_OUT_OF_SCOPE", "DOCTOR_LEVELS", "PINNED_PYTHON")),
    (mailscan, "Command words (`mailscan.py`)", (
        "PROGRAM", "COMMANDS", "HELP_FLAGS", "STANDARD_INPUT", "LABELS", "WITHHELD", "NONE",
        "ERROR_INTERNAL", "ERROR_INTERRUPTED", "ERROR_NOT_LOADED", "DRAFT_FILE_MAX_BYTES",
        "TARGET_FILE_MAX_BYTES")),
)

# The override table of the design: kind -> (what it lifts, the result when it is the last hold).
OVERRIDE_TABLE: Tuple[Tuple[str, str, str], ...] = (
    ("block", "the hold `block`; the effective verdict becomes `caution`", "reply = `reply_if_released`"),
    ("list", "`none-list`", "reply = `draft`"),
    ("budget", "the hold `budget`", "reply = `reply_if_released`"),
    ("held", "the hold `held`", "reply = `reply_if_released`"),
)

RULE_CLASS_NOTES = (
    ("block", "Block rules", "A hit makes the verdict `block`. A block always holds the reply (hold kind "
              "`block`)."),
    ("caution", "Caution rules", "A hit makes the verdict at least `caution`. Only a rule with a hold "
                "touches the reply."),
    ("reply", "Reply rules", "These decide the reply and leave the verdict alone."),
    ("refuse", "Draft refusal rules", "Each is a reason `check-draft` refuses a draft. They never appear in "
               "a scan record."),
)

INTRO = """# mail-scan: rules, gaps and fixed lists

GENERATED from the scripts by `tests/rules_reference.py`. Do not edit this file by hand: change
`scripts/mail_lists.py` (with a test and a bumped `LISTS_VERSION`) and run

    python3 skills/mail-scan/tests/rules_reference.py --write

A test holds this file equal to what that command writes, and compares every value below with
the scripts.

- Lists version: `%(lists_version)s`. Scanner version: `%(scanner_version)s`. Both are recorded in every record.
- The phrases and tokens printed below are DATA: entries of lists the scanner matches. They are
  addressed to nobody. In a printed value an angle bracket, every character outside printable ASCII,
  and one character of each control token and of the frame prefix is a backslash-u escape, so no
  token, no frame line, no marker stem, no note of the scanner and no hidden character stands in
  this file as itself.
- Nothing here is matched against the text a person would see, except where an entry says so. The
  hidden phrases are matched only against text that was removed because it was proven hidden.

## Contents

1. Verdict, reply and holds
2. Rule tables (block, caution, reply, draft refusal)
3. Gap table
4. Override table
5. How the rules read a message (as built)
6. How the draft check reads a draft (as built)
7. Fixed lists of `mail_lists.py`
8. Fixed words of the other scripts

## 1. Verdict, reply and holds

A scan gives two results. The **verdict** is one of %(verdicts)s. The **reply decision** is one of
%(replies)s. A hold kind in force is one of %(holds)s; while any hold is in force the reply is
`held`, and `reply_if_released` is the reply the message gets once every hold is lifted. An
automated message (`none-automated`) carries no holds and can never be released into a draft.

Exit codes of the command: %(exit_pass)d pass or accept, %(exit_caution)d caution, %(exit_block)d block or refuse,
%(exit_usage)d usage or environment error. Any exit other than %(exit_pass)d or %(exit_caution)d means no draft; and the reply
decision, not the exit code, says whether a draft may be written at all.
"""

AS_BUILT_SCAN = """## 5. How the rules read a message (as built)

These are the readings the tables above cannot show. Where they differ from the first design
text, this is what the code does.

- **Bounds.** At most %(max_depth)d levels of MIME nesting, %(max_parts)d parts, %(max_header_lines)d header lines per
  header block and %(max_header_bytes)d bytes per header after unfolding, %(max_links)d links; the byte bound comes from
  the config (default %(max_bytes)d). Over a bound is the gap `structure-over-bound` with the bound named,
  and nothing more of the message is read.
- **Time.** A Content-Type, Content-Disposition or Content-Transfer-Encoding value of more than
  %(max_mime_header)d bytes, on the message or on any part, is over the bound `header-length`: it is found in
  the raw bytes before the standard parser runs (so a body line that starts with one of those names
  and runs that long counts too). One scan has %(scan_seconds)d seconds for the parse, the view and the rules
  together; when they are spent the message is over the bound `time` and is a block. A message the
  scanner reads in time is judged as usual, however large.
- **From.** A missing or repeated From, group syntax, or other than exactly one mailbox is the
  block rule `header-ambiguous`. A defect that touches the mailbox itself is the gap `parse-defect`
  (detail `from`). A defect confined to the display name is the caution `from-name-irregular`, with
  no hold: the mailbox is used. An address whose domain is not ASCII, or whose local part or domain
  holds a character no reader sees, a combining mark or a compatibility form, is `parse-defect`
  (detail `from`) as well: it only looks like the address it imitates.
- **A carriage return alone** that ends a line of a header block or a boundary line is the gap
  `parse-defect`, detail `bare-cr`: the message is blocked whole and nothing of it is read.
- **Part headers.** A repeated Content-Type, Content-Transfer-Encoding or Content-Disposition on any
  part is `header-ambiguous`. So is (reason `parameter`) a Content-Type or Content-Disposition that
  gives ANY parameter more than once in any form (any letter case; plain, or `name*=`, `name*0=`
  beside the plain form; the sections of one continued parameter are one; a section number of any
  length is read, and one with a leading zero other than `0` itself or of more than three digits is
  ambiguous), that gives one of `SINGLE_PARAMETERS` in an RFC 2231 form or names it twice anywhere
  in the value (a quoted string included), whose `SINGLE_PARAMETERS` value is not a plain token or a
  quoted string free of a backslash and of anything a reader may decode (an encoded word `=?`,
  base64), or whose parameter list does not parse as `; name=value` pairs (a comment anywhere in it
  is such a list). An unknown transfer encoding, or a multipart that cannot be split, is
  `parse-defect`.
- **Alternatives.** The last HTML part is selected, else the last plain part. Any multipart child of
  an alternative other than a related part with a text root is `alternative-ambiguous`. A text part
  marked `attachment` is an attachment and never the body; when it is the part a reader that leaves
  dispositions out of account would show, the alternative is `alternative-ambiguous` (detail
  `disposition`). A calendar part in an alternative is an attachment, not the gap
  `alternative-other-text`.
- **Related.** The root is the part `start` names, else the first. A `start` that names another
  part than the first is `related-root-invalid` (detail `start`), a block: a reader that ignores the
  parameter shows the first part.
- **Charsets.** A part labelled iso-8859-1 is decoded as windows-1252, as mail readers do.
- **Hidden text.** Text proven hidden is removed and counted; over %(preheader)d characters it is the
  caution `hidden-text`. Text whose visibility could not be decided is removed with a warning line;
  over %(uncertain)d characters the reply is held. So is the reply of a message one of whose parts lost
  at least %(share)d%% of its text (shown and uncertain together) and at least %(share_chars)d characters to doubt:
  the caution `uncertain-share`, kind `held`. A draft is never written from half a message. Text
  after the first attribution line is labelled unverified.
- **Styles: proven harmless, or not shown.** The view does not imitate a browser, and it does not
  show only what a reader sees: it catches the common hiding tricks. A strict reader judges one
  element at a time; it accepts a small, exactly specified style language, cut down in fix round 3
  to what person-written mail uses, and treats everything outside it as uncertain:
  the text of that element is removed and counted. It does not recover from an error the way a
  browser does, and it never decides that one declaration beats another. An element is judged over
  the WORST of its `style` attribute and of every style-block rule whose selector could match it; a
  later, a more specific, an `!important` or an inline value rescues nothing.
- **The language: tokens.** One tokeniser reads style attributes and style blocks, in the order of
  CSS Syntax (a string and an unquoted `url(` before a comment). An unterminated string, comment or
  url, a line break in a string, a NUL or other control character, any character outside printable
  ASCII that stands outside a string or a comment (but a letter or a digit: Word writes a family
  name with no fallback unquoted; such a word is accepted in `font-family` and nowhere else), and a
  backslash escape make the WHOLE attribute or block unreadable. (Exceptions: an escape inside the
  block of an at-rule that is passed over, where Word writes the bullet of a list, and in a quoted
  family name of an `@font-face`.) A style attribute of more than %(style_attribute)d characters is
  unreadable without being parsed.
- **The language: declarations.** A declaration is accepted only when its property is on one of the
  lists below AND its value matches that property's own pattern: the properties read
  (`CSS_PROPERTIES`, `CSS_RELATED_PROPERTIES`; the patterns are written out above those entries),
  the properties with fixed values (`CSS_FIXED_VALUE_PROPERTIES`), with a list of words
  (`CSS_WORD_ONLY_PROPERTIES`), with a plain list (`CSS_SAFE_PROPERTIES`, and the `mso-`
  properties not named in `CSS_UNSAFE_WORD_PROPERTIES`). A length is a number with one of
  `CSS_UNITS`, or a plain 0; no `rem`, and `ex` and `ch` (`CSS_MARGIN_ONLY_UNITS`) only in a margin or
  a padding that is not negative (Gmail's quote), where they count as at most an em of push and as
  no room for a hanging indent. A colour is `#rgb`, `#rrggbb`, `rgb(n, n, n)`, `rgba(n, n, n, a)`,
  `transparent`, `inherit`, a colour name of CSS, or `windowtext` / `window` (and `initial`, as
  pasted text writes it: black for `color`, none for `background-color`). No `var()`, `calc()`,
  `currentcolor`, `hsl()`, no other system colour. Of the shorthands only `margin`, `padding` and
  the borders are read, and `background` with ONE colour; `font` is not accepted. Anything else
  makes its element uncertain.
- **Thresholds.** Proven hidden: `display: none`, `visibility: hidden`, the `hidden` attribute,
  `mso-hide`, `display: table-column` and `table-column-group` (no box is drawn); a height or width
  under %(box_hidden)gpx (or of 0) where the element clips; a font size under %(font_hidden)gpx; contrast under
  %(contrast)g:1 in every pair of colours the text may get, after the opacity of the element and its
  ancestors has blended the text toward its backdrop (plain black on white is removed at an opacity
  of .173 and below); and, taken as the product or the sum down the ancestors (each property at the
  worst value it may get), an opacity under %(opacity)g and a push beyond %(offset_hidden)gpx. Uncertain: a font size
  under %(font_uncertain)gpx in some reading (`em` and `%%` multiply down the ancestors; `small`, `sub`, `sup`
  count); text pulled up by more than %(up_uncertain)gpx, or pushed away by more than %(offset_uncertain)gpx, in sum; a negative
  text-indent on an element with lines of its own, unless the left margins and paddings that element
  and the blocks around it have for certain are at least as wide (the hanging indent of a list); a
  negative text-indent on a block that paints a background; low contrast in some pair of colours.
- **Position and margins (fix round 3).** Only `position: static`, and `relative` with every offset
  absent, `auto` or 0, are read; `absolute`, `fixed` and `sticky` are uncertain, and so is `relative`
  beside any other offset. The one form accepted is Word's raised or lowered text: in one style
  attribute, `top` the opposite of `mso-text-raise`, in absolute units, at most %(raise)gpx, and no other
  offset. A NEGATIVE margin is uncertain, and so is all the text that FOLLOWS it in the part (it
  pulls its siblings, and such pulls add up without a bound), with one exception: the `margin-left`
  of a <table>, in its own style attribute, from -%(word_table)gpt up to 0 in `pt` (Word pulls a table
  by its cell padding).
- **Right-anchored overflow (fix round 3).** Content wider than its box leaves it on the side its
  box is anchored away from; for a box anchored on the right that is off the page to the left. So
  the text of an element, and of everything in it, is uncertain when it stands where text runs right
  to left (a `dir` of rtl or auto on it or around it, or `direction: rtl`) and it does not wrap
  (`nowrap` or `pre` from `white-space`, `text-wrap` or the `nowrap` attribute, <nobr>, <pre>) or has
  a width of its own (`width`, `min-width`, a length in `flex` or `flex-basis`, a width attribute);
  or when it stands in an element floated right, or a <table>, <div> or <img> with `align="right"`,
  and does not wrap or has a width over %(right_width)gpx or over 100%%. Flex and grid alignment is read
  at its start values only (`justify-content`, `align-items`, `flex-direction` and the rest are
  fixed values). Hebrew and Arabic mail as a person writes it (right to left, wrapping, no width)
  keeps its text; a table with a width in such mail does not.
- **Boxes that clip.** The text of an element whose overflow is anything but `visible` is uncertain
  IN FULL, with everything inside it, whatever its size; so is the text of an element with a height
  or width under %(box_hidden)gpx (a `width:0px` on a <table> is no size: the table is laid out by its
  content or its columns), and of a table with a column of no width or a column (`col`, `colgroup`)
  with any background. One exception: `overflow:hidden` alone on a <td> or <th> that sets no size of
  its own (Google Sheets writes it on every cell). Inside such a cell, what does not wrap, has a width
  of its own, is pushed right by more than %(clip_push)gpx in sum or spaced by more than %(clip_spacing)gpx is uncertain;
  and in a table laid out `fixed`, such a cell must stand in columns a <col> gives a width, and no
  cell of the table may span rows, or the whole table is uncertain.
- **Style blocks.** A block is readable only if everything in it is of the language: rules whose
  selectors are made of a tag, `.class`, `#id`, `[attribute]`, a pseudo-class or pseudo-element with
  no brackets, the descendant and child combinators and comma lists; `@media` around such rules (two
  deep at most); `@page` and Word's `@list`, which are passed over; `@font-face` with only the
  descriptors of `CSS_FONT_FACE_DESCRIPTORS` and Word's `mso-*`, in the value forms Outlook writes
  (any `src`, `size-adjust`, `*-override`, `unicode-range` or other descriptor makes the block
  unreadable: a face may draw the glyphs of a family small or blank); `<!--` as the
  first thing and `-->` as the last. Only the LAST compound selector is compared with an element
  (classes and ids without regard to ASCII letter case, split on the white space of HTML only), so
  a rule applies to at least the elements a browser applies it to; a pseudo-class is read as "may
  hold" (also `:hover`). A selector of any other form applies its rule to EVERY element. A rule
  applies FOR CERTAIN only when it stands outside any at-rule, every selector of its list is plain,
  and its one compound selector matches the element exactly: only such a rule, or the style
  attribute, rules out "the value comes from the parent", and neither rules out another declaration.
- **Unreadable blocks.** Any other at-rule (`@import`, `@namespace`, `@supports`, `@layer`,
  `@keyframes` among them), a rule in a rule, a stray token before a rule, `<!--` or `-->`
  elsewhere, more than %(style_rules)d selectors, a block over %(style_block)d characters, a <style> tag
  with an attribute other than `type="text/css"` and `style`, a <link> to a style sheet whatever its
  address, and a page that allows a dark colour scheme: each makes EVERY element of the part
  uncertain. Nothing of the part is shown (gap `css-unresolved`, detail `style` or `external`), and
  over %(uncertain)d characters the reply is held. The gap itself stays a caution with no hold.
- **What this costs.** Mail a person writes in Outlook, Gmail, Apple Mail, Thunderbird, Yahoo or
  Outlook on the web is inside the language and keeps its text (the tests hold one sample of each,
  and text pasted from Google Docs, Google Sheets and Apple Notes). A marketing or notification
  template usually is not: it loses text, often all of it, and its reply is held by
  `uncertain-share` (or, over %(uncertain)d characters, by the hold of `uncertain-removal`). That is
  accepted: such mail is normally list mail, which gets no draft anyway.
- **What it does not catch (the layout residue).** A reader that judges one element at a time
  cannot prove a layout harmless. Still shown although a reader may not see it: text covered by
  another element (also by generated content of `::before` or `::after`); text in a font with blank
  glyphs outside the `@font-face` forms above; text pushed right, where it can be scrolled to, by
  paddings, word spacing and letter spacing summed; one unbreakable run that overflows a
  right-anchored box or a clipping cell (the part past the box); the reversed order of
  `<bdo dir="rtl">`; what engines other than Chrome do, a reader-imposed dark mode, and
  `-webkit-text-size-adjust` beyond its accepted values in iOS Mail.
- **The one exception: the hanging indent of one style attribute.** A negative text-indent is
  visible when the SAME style attribute also carries a left margin or left padding at least as
  wide (lengths of one kind), no rule that could match the element sets a margin, a padding or a
  text-indent with `!important`, and the element sets no background (by an attribute, its style
  or any rule that could match): its first words stand outside its own box, on the backdrop it
  stands on, against which its text colour is judged. What such rules say of those three
  properties without `!important` is then left out (Word's `p.MsoNormal{margin:0cm}` under a list a
  person typed). No other property is treated this way.
- **Characters no reader sees.** Beside the tag, bidi and format classes, every other code point of
  the Unicode property Default_Ignorable_Code_Point and the blank ones of `BLANK_CODE_POINTS` are
  taken out of the view. A variation selector directly after an emoji, and a joiner between two
  emoji, stay and are not counted. More than %(unseen)d of them in the SHOWN text of one message is the
  caution `unseen-characters`, which holds the reply; any number counts under `format-characters`.
- **The scanner's own lines.** In a framed view a line of the message stands behind the line prefix
  and a fixed line of the scanner (`SCANNER_LINES`) behind the note prefix. A square bracket of the
  message is written as its full-width form, so a square bracket in a view is the scanner's: a link
  token, the secret mask, or one of those lines.
- **Text between angle brackets** that the standard parser reads as a tag and that is no element
  name (an address, a URL) swallows what follows it: that text is removed as uncertain and counted.
- **Hidden phrases.** Two lists, both matched against proven-hidden removed text only: never
  against text removed as uncertain and never against visible text. `HIDDEN_PHRASE_PATTERNS` is the
  block rule `hidden-phrase`; `HIDDEN_PHRASE_WEAK_PATTERNS` is the caution `hidden-phrase-weak`.
- **Conditional comments.** One in a usual form is the caution `comment-conditional`, no hold.
  A malformed, unpaired or unclosed one is the gap `html-ambiguous` (held).
- **Elements.** Text is kept only from `ELEMENT_ALLOWLIST` (with the Word elements and the two
  document wrappers). An element of `HTML_AMBIGUOUS_ELEMENTS` is `html-ambiguous`; a part holding
  one of `HTML_FOREIGN_ELEMENTS` reaches no view at all. The view also withholds a part whose markup
  the standard tokeniser and this reader split differently (detail `tokens`).
- **Control tokens and frame forgery** are looked for in the visible text, the Subject and the From
  name, and once more after compatibility folding with unseen characters taken out. The two tokens
  of `CONTROL_TOKENS_PLAIN_ONLY` count in the body only when a text/plain part was selected. A turn
  label at the start of a line is the caution `role-label` (it was a block in the first build).
  `frame-forgery` finds either line prefix, the stem of a marker with anything after it, and the
  opening of a scanner note in any bracket; the view's own fixed lines are left out first.
- **Tag characters.** The three subdivision flags of `SUBDIVISION_FLAG_CODES`, written whole, are
  shown as a plain black flag and are not tag characters. Any other tag character blocks.
- **Format characters** counted by `format-characters` include bidirectional controls stripped from
  the body; a bidirectional control in the From name, the Subject or a link is the block rule.
- **Attachments.** Never parsed. A dangerous extension or media type, or leading bytes of
  `DANGEROUS_SIGNATURES` whatever the name or declared type says, is `attachment-dangerous`. A
  declared type that disagrees with the leading bytes is `attachment-type-mismatch`; the generic
  extensions and media types and the listed aliases agree with anything. An HTML or SVG attachment is
  the caution `attachment-active-content`, no hold. An image that is a resource of a related message
  is not counted by `attachment-present`.
- **Image-only.** Fewer than %(image_letters)d visible letters or digits and an image element or image part
  (or a message that is one non-text part): caution, reply held.
- **Sender.** Only the FIRST Authentication-Results header is read, and only when the config has a
  provider profile whose `authserv_id` equals the id of that header. Verified needs `dmarc=pass` with
  a `header.from` EQUAL to the From domain; or, when the header carries no dmarc result at all
  (`dmarc=none`, `temperror`, `permerror` and `bestguesspass` are no result: the domain has no DMARC
  record), `dkim=pass` with a `header.d` equal to it or `spf=pass` with an `smtp.mailfrom` domain
  equal to it; and no `dmarc=fail`. A `dmarc=fail` in that header is the caution `dmarc-fail` and
  HOLDS the reply (kind `held`): the reply would go to an address the provider says was forged; so
  does any dmarc result word other than `pass`, `fail` and the no-result words (`reject`,
  `quarantine`). A first header that begins with the profile's id and cannot be read is the caution
  `auth-header-unreadable` and holds the reply too. A provider whose header carries no authserv-id,
  or that splits its results over several headers, gives no DMARC hold: only the first header is
  read. Equal means the same name in ASCII lower case with one trailing dot removed.
  There is no relaxed alignment and no list of public suffixes: the provider did the alignment for
  its dmarc result, and a signature of a parent, a subdomain or a sibling domain proves nothing here.
  With no profile every sender is unverified, so every message is at least a caution.
  `from-name-address` compares whole domains the same way.
- **Reply.** `none-automated` wins over everything, a block included, and such a record has no holds.
  The budget hold is put on list mail as well. The reply target is the From mailbox or its
  `reply_to_map` entry; a Reply-To header is never used; the target is never stored or printed.
- **Automated mail.** Auto-Submitted other than `no`, a null return path, a no-reply sender, a
  request to suppress automatic responses and mail from an own address are `none-automated`. So is
  what older auto-responders write: a Precedence of `AUTO_REPLY_PRECEDENCE_VALUES`, or the presence
  of a header of `AUTO_REPLY_HEADERS`.
- **Budget.** A message is placed by its FIRST record. Counted are other raw digests of the same
  sender hash that REALLY were open to a draft: the recorded verdict was not a block and the reply
  was `draft` as recorded or after an override of a person, whatever the sender check said;
  and whose first such record lies before that moment and no more than %(budget_days)d days before it. At
  %(budget_count)d or more the reply is held (kind `budget`). Blocked and held mail never counts; mail
  with a reported DMARC failure is held, so it does not count either. Later mail never counts against an earlier message, so a re-scan within the week gives
  the same answer as the first scan. Mails first scanned in the same second are ordered by record
  id. Record files are chosen by the time in their names before they are opened: the last
  %(budget_lookback)d days, and further back only while an earlier record of the same message turns up.
- **Overrides.** An override is refused for a record of a message that was not judged
  (`override-not-judged`). A `block` override records the block rule ids and block-class gap names
  of its record, and lifts a later record of the same digest only when everything that record is
  blocked for is among them.
- **The key.** A state root that holds records and no key is the error `key-missing`: a scan is a
  block with no record, and no key is made. A directory of the root that is a symbolic link is
  refused.
- **Any failure of the scanner** is a block record with the gap `scanner-error`; lifting that block
  gives no draft (its `reply_if_released` is `held`). The same holds for a scan whose time ran out
  inside the rules. A missing or unusable secrets catalog is the
  block-class gap `catalog-missing`.
"""

AS_BUILT_DRAFT = """## 6. How the draft check reads a draft (as built)

The body and the subject are read after compatibility folding (NFKC) and the folds of the
`DRAFT_*` entries below. A refusal names rule ids and counts only.

- **Record and view.** A missing or unreadable record is `draft-record-missing` alone. A missing
  view is `draft-view-missing`. The effective verdict must not be `block` and the effective reply
  must be `draft`, after overrides: of the NEWEST record of the same message (the same raw
  digest), so a later scan that blocks it refuses a draft that names an older record id.
- **Reply target.** Accepted when its keyed hash is the sender hash of the record, or when it is the
  `reply_to_map` value of that sender. It must be its own NFKC form, and exactly the address: white
  space around it, or a line break in it, is a refusal.
- **Hosts and URLs.** An allowed host is accepted only as an optional `http` or `https` scheme, the
  host, a plain path and a plain fragment (`DRAFT_ALLOWED_URL_TAIL_PATTERN`) of at most %(url_tail)d
  characters together; `www.` in front is the same host. That path and fragment are read by the
  number rules like any other text, and by the secret rule. A query is `draft-url-query`; a port,
  user information, a percent sign, an empty or climbing path segment is `draft-url`; so is any
  word before `://`, a scheme of `DRAFT_SCHEMES_NO_SLASHES` followed by a colon and directly by
  text (`mailto:`, `tel:`, `javascript:`), and two slashes that open a word (`//host/x`). A word
  that is not on that list is a label: `Note:closed`, `Size:M` and `Re:Order` pass, and so do
  `Email:` before one of our own addresses and `Tel:` or `Fax:` before an approved number. A
  chain of labels is a bare host when a label after the first is a top-level domain of
  `DRAFT_TLDS` (the IANA root zone as of `DRAFT_TLDS_SNAPSHOT_DATE`; `doctor` warns when that is
  over a year old), a label in the `xn--` form, or two or more letters outside ASCII. White space
  BEFORE the dot does not hide a host; white space only after it does, except before the few names
  of `DRAFT_SPACED_TLDS` (it is the shape of every sentence boundary). A dotted quad, an address
  in colons (in square brackets, or with a double colon), `localhost`, the loopback address written
  short (`127.1`) and a path that starts with two backslashes are hosts. The ideographic full stop
  is not read as a host dot (it ends every Japanese and Chinese sentence), except between two ASCII
  labels of which the second is a top-level domain. Every scheme of `DRAFT_SCHEME_PREFIX_PATTERNS`
  (`ms-*`, `search-ms`) is refused like a listed one. An opening angle bracket before a URL that
  does not end at the closing one is `draft-markup`.
- **Addresses.** Any at sign outside our own addresses and the reply target is `draft-address`. An at
  sign standing alone is one only when a host follows it.
- **Numbers.** A run of digits is read across the separators of `DIGIT_SEPARATORS` and across line
  breaks. A real calendar date (`DRAFT_DATE_PATTERNS`, years `DRAFT_DATE_YEARS`) is not a run. Two
  amounts with two decimals joined by a hyphen are two numbers. A run of %(phone_min)d to %(phone_max)d digits is
  accepted when its digits are an entry of `approved_phones` or equal one WHOLE run of the inbound view
  or the knowledge pack; a trunk zero in brackets after a plus is also read without it. A run of 7,
  8, or 16 and more digits is accepted when its digits are part of a run of the view or the pack.
  Phone numbers are compared by digits only.
- **Characters.** Every character no reader sees is `draft-hidden-characters`: tag, bidirectional
  and format characters, the rest of Default_Ignorable_Code_Point, the blank code points; and more
  than `DRAFT_MAX_COMBINING_MARKS` GENERAL combining marks on one character
  (`DRAFT_GENERAL_MARK_RANGES`; the marks of Devanagari, Burmese, Tibetan, Thai, Arabic, Hebrew and
  every other script are its writing and are not capped). A variation selector after an emoji, a
  zero-width joiner between two emoji, the three subdivision flags and a zero-width non-joiner
  between two Arabic-script letters are allowed.
- **White space is a channel** nobody sees when a draft is approved, so it is refused under its
  own rule, `draft-white-space`: every space character other than U+0020, a tab, white space at the
  start or the end of a line, two spaces in a row, a blank line at the start, more than
  `DRAFT_MAX_BLANK_LINES` blank lines in a row, more than one line break at the end, and line endings
  of both kinds (a draft is all LF or all CRLF); lines are counted by their place. One exception
  keeps French typography and grouped digits writable: a no-break space or a narrow no-break space
  directly between two digits, before `?`, `!`, `:`, `;` or a closing guillemet, or after an opening
  one; one of the two kinds in a text, and one USE in a text (a plain space where a no-break space
  stood elsewhere is refused). That leaves one choice a text, one bit nobody sees: white space is
  narrowed to that, not closed.
- **Mixed scripts.** A word (its letters and the combining marks on them) that mixes letters of two
  of `DRAFT_MIXED_SCRIPTS` (a Cyrillic `a` in a Latin word) is `draft-mixed-script`, but for a unit of
  at most `DRAFT_UNIT_MAX_LATIN` Latin letters and one of `DRAFT_UNIT_GREEK` (kilo-ohm, micrometre, a
  difference of T); so is a mark of a script that stands on anything but a letter or a mark of that
  script. A control,
  private-use or unassigned character, a line or paragraph separator, a carriage return alone, and
  any line break in the subject is `draft-control-characters`.
- **Caps.** The body is at most %(draft_body)d characters and the subject %(draft_subject)d.
- **Secrets, canary, pack.** A secret is `draft-secret`; with no usable catalog the draft is refused
  (`draft-catalog-missing`). The canary is also looked for squeezed to letters and digits. A knowledge
  pack that is named and cannot be read (missing, a folder, not UTF-8, over `KNOWLEDGE_PACK_MAX_BYTES`)
  refuses every draft (`draft-knowledge-pack`).
"""


# --------------------------------------------------------------------------------------
# Values as JSON
# --------------------------------------------------------------------------------------

def plain(value: Any) -> Any:
    """`value` in the form the reference prints: JSON types only."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, re.Pattern):
        flags = [flag.name for flag in re.RegexFlag if flag in re.RegexFlag(value.flags)
                 and flag is not re.UNICODE and flag.name]
        return {"regex": value.pattern, "flags": sorted(flags)}
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return {field: plain(getattr(value, field)) for field in value._fields}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return {"set": sorted(plain(item) for item in value)}
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    raise TypeError("a value the reference cannot print: %s" % type(value).__name__)


# What the rule frame-forgery finds: none of these stands in the reference as itself.
FRAME_STRINGS = (mail_lists.FRAME_LINE_PREFIX.strip(), mail_lists.FRAME_NOTE_PREFIX.strip(),
                 (mail_lists.FRAME_OPEN_FORMAT % "").rstrip("-"), (mail_lists.FRAME_CLOSE_FORMAT % "").rstrip("-"),
                 mail_lists.QUOTED_LABEL_LINE.split(" ")[0])


def escaped(char: str) -> str:
    return BACKSLASH_U + "%04x" % ord(char)


def never_as_itself() -> List[Tuple[str, str]]:
    """(text as JSON prints it, the same with one character escaped) for every string that must
    not stand in the reference as itself: each control token, the two line prefixes of the
    frame, the stem of its two markers and the opening of a note of the scanner."""
    out = []
    for token in mail_lists.CONTROL_TOKENS + FRAME_STRINGS:
        inner = json.dumps(token, ensure_ascii=True)[1:-1]
        marks = [index for index, char in enumerate(inner) if not char.isalnum() and char not in "<>"]
        if "<" in inner or ">" in inner or not marks:
            continue            # the angle brackets are escaped everywhere already
        index = marks[0]
        out.append((inner, inner[:index] + escaped(inner[index]) + inner[index + 1:]))
    return out


def dumps(value: Any) -> str:
    """Compact ASCII JSON; the angle brackets, and one character of each control token and of
    the frame prefix, are written as escapes."""
    text = json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
    for inner, safe in never_as_itself():
        text = text.replace(inner, safe)
    return text.replace("<", escaped("<")).replace(">", escaped(">"))


def wrapped(name: str, value: Any) -> List[str]:
    """The lines of one entry: `NAME = <json>`, a long list or object over several lines."""
    first = "%s = %s" % (name, dumps(value))
    if len(first) <= LINE_WIDTH:
        return [first]
    if isinstance(value, list) and value:
        lines, current = ["%s = [" % name], "   "
        for index, item in enumerate(value):
            piece = dumps(item) + ("," if index < len(value) - 1 else "")
            if len(current) + 1 + len(piece) > LINE_WIDTH and current.strip():
                lines.append(current)
                current = "   "
            current += " " + piece
        lines.append(current)
        lines.append("]")
        return lines
    if isinstance(value, dict) and value:
        lines = ["%s = {" % name]
        keys = list(value)
        for index, key in enumerate(keys):
            inner = wrapped(json.dumps(key), value[key])
            inner[0] = inner[0].replace(" = ", ": ", 1)
            inner[-1] += "," if index < len(keys) - 1 else ""
            lines.extend("    " + line for line in inner)
        lines.append("}")
        return lines
    return [first]


# --------------------------------------------------------------------------------------
# The module as sections of entries
# --------------------------------------------------------------------------------------

def module_source(module: Any) -> str:
    with open(module.__file__, "r", encoding="utf-8") as fh:
        return fh.read()


def public_names(module: Any) -> List[str]:
    """Every public constant of a module: an upper-case name bound at the top level."""
    return sorted(name for name in vars(module) if not name.startswith("_") and name == name.upper()
                  and any(char.isalpha() for char in name))


def sections() -> List[Tuple[str, List[Tuple[str, List[str]]]]]:
    """mail_lists.py as [(section title, [(name, comment lines)])], in the order of the file.

    A section starts at a banner (a rule line, a title line, a rule line). The comment lines of
    a name are the comment lines right above its assignment and the comment on its first line.
    """
    source = module_source(mail_lists)
    lines = source.splitlines()
    comments: Dict[int, str] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments[token.start[0]] = token.string
    titles: Dict[int, str] = {}
    for index in range(len(lines) - 2):
        if BANNER.match(lines[index]) and BANNER.match(lines[index + 2]) and lines[index + 1].startswith("# "):
            titles[index + 2] = lines[index + 1][2:].strip()
    banner_lines = set()
    for number in titles:
        banner_lines.update((number - 1, number, number + 1))
    wanted = set(public_names(mail_lists))
    out: List[Tuple[str, List[Tuple[str, List[str]]]]] = [("Version", [])]
    seen = set()
    for node in ast.parse(source).body:
        while titles and min(titles) < node.lineno:
            out.append((titles.pop(min(titles)), []))
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for name in targets:
            if name not in wanted or name in seen:
                continue
            seen.add(name)
            above: List[str] = []
            number = node.lineno - 1
            while number >= 1 and lines[number - 1].lstrip().startswith("#") and number not in banner_lines:
                above.insert(0, lines[number - 1].strip())
                number -= 1
            inline = comments.get(node.lineno, "")
            if inline and not lines[node.lineno - 1].lstrip().startswith("#"):
                above.append(inline.strip())
            out[-1][1].append((name, above))
    missing = wanted - seen
    if missing:
        raise RuntimeError("public names with no top-level assignment: %s" % ", ".join(sorted(missing)))
    return [(title, entries) for title, entries in out if entries]


def entry_block(module: Any, names_with_comments: List[Tuple[str, List[str]]]) -> List[str]:
    lines = [FENCE + "text"]
    spaced = False      # the entry before this one had comments or ran over several lines
    for index, (name, comment_lines) in enumerate(names_with_comments):
        body = wrapped(name, plain(getattr(module, name)))
        if index and (comment_lines or spaced):
            lines.append("")
        lines.extend(comment_lines)
        lines.extend(body)
        spaced = bool(comment_lines) or len(body) > 1
    lines.append(FENCE)
    return lines


# --------------------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------------------

def cell(text: str) -> str:
    if "|" in text or "\n" in text:
        raise ValueError("a table cell may hold neither a bar nor a line break")
    return text if text else "-"


def code(word: str) -> str:
    return "`%s`" % word if word else "-"


def rule_tables() -> List[str]:
    lines = ["## 2. Rule tables", "",
             "%d rules. The description is fixed text of ours: the only prose about a hit that a caller "
             "may print." % len(mail_lists.RULES), ""]
    for rule_class, title, note in RULE_CLASS_NOTES:
        rows = [rule for rule in mail_lists.RULES.values() if rule.rule_class == rule_class]
        lines += ["### %s (%d)" % (title, len(rows)), "", note, "",
                  "| Rule id | Class | Hold | Reply | Description |", "|---|---|---|---|---|"]
        for rule in rows:
            lines.append("| %s | %s | %s | %s | %s |" % (code(rule.rule_id), code(rule.rule_class), code(rule.hold),
                                                        code(rule.reply), cell(rule.description)))
        lines.append("")
    return lines


def gap_table() -> List[str]:
    lines = ["## 3. Gap table", "",
             "A gap is something the scanner could not read with certainty. %d gaps. A gap may carry one "
             "word of `GAP_DETAILS` saying where it was met; for `structure-over-bound` that word is the "
             "bound." % len(mail_lists.GAPS), "",
             "| Gap | Class | Reply effect | Hold | Description |", "|---|---|---|---|---|"]
    for gap in mail_lists.GAPS.values():
        lines.append("| %s | %s | %s | %s | %s |" % (code(gap.name), code(gap.gap_class), code(gap.reply_effect),
                                                    code(gap.hold), cell(gap.description)))
    lines.append("")
    return lines


def override_table() -> List[str]:
    lines = ["## 4. Override table", "",
             "An override names one record and is bound to the raw digest of its message. It is refused "
             "for a record whose reply is `none-automated`, for an unknown or unreadable record, for a "
             "kind that is not among the holds of the record (for `list`: a record whose "
             "`reply_if_released` is not `none-list`) and for an empty reason. A record with several holds "
             "needs one override per kind; while any hold remains the effective reply is `held`. Overrides "
             "never expire, and `purge` keeps the log.", "",
             "| Kind | Lifts | Effective result when it is the last hold |", "|---|---|---|"]
    for kind, lifts, result in OVERRIDE_TABLE:
        lines.append("| %s | %s | %s |" % (code(kind), lifts, result))
    lines.append("")
    return lines


# --------------------------------------------------------------------------------------
# The whole reference
# --------------------------------------------------------------------------------------

def words(group: Tuple[str, ...]) -> str:
    return ", ".join("`%s`" % word for word in group)


def render() -> str:
    """The text `references/rules-and-gaps.md` must hold for the scripts as they are now."""
    facts = {
        "lists_version": mail_lists.LISTS_VERSION, "scanner_version": mail_state.SCANNER_VERSION,
        "verdicts": words(mail_lists.VERDICTS), "replies": words(mail_lists.REPLIES),
        "holds": words(mail_lists.HOLD_KINDS),
        "exit_pass": mail_lists.EXIT_PASS, "exit_caution": mail_lists.EXIT_CAUTION,
        "exit_block": mail_lists.EXIT_BLOCK, "exit_usage": mail_lists.EXIT_USAGE,
        "max_depth": mail_lists.MAX_MIME_DEPTH, "max_parts": mail_lists.MAX_PARTS,
        "max_header_lines": mail_lists.MAX_HEADER_LINES, "max_header_bytes": mail_lists.MAX_HEADER_LINE_BYTES,
        "max_links": mail_lists.MAX_LINKS, "max_bytes": mail_lists.MAX_BYTES_DEFAULT,
        "preheader": mail_lists.PREHEADER_ALLOWANCE_CHARS, "uncertain": mail_lists.UNCERTAIN_HOLD_CHARS,
        "max_mime_header": mail_lists.MAX_MIME_HEADER_BYTES, "scan_seconds": mail_lists.SCAN_SECONDS,
        "font_hidden": mail_lists.HIDDEN_FONT_SIZE_BELOW_PX, "font_uncertain": mail_lists.UNCERTAIN_FONT_SIZE_BELOW_PX,
        "box_hidden": mail_lists.HIDDEN_BOX_BELOW_PX, "opacity": mail_lists.HIDDEN_OPACITY_BELOW,
        "offset_hidden": mail_lists.HIDDEN_OFFSET_BEYOND_PX, "offset_uncertain": mail_lists.UNCERTAIN_OFFSET_BEYOND_PX,
        "margin_uncertain": mail_lists.UNCERTAIN_NEGATIVE_MARGIN_BEYOND_PX,
        "up_uncertain": mail_lists.UNCERTAIN_UPWARD_SHIFT_BEYOND_PX, "style_attribute": mail_lists.STYLE_MAX_ATTRIBUTE_CHARS,
        "style_rules": mail_lists.STYLE_MAX_RULES, "style_block": mail_lists.STYLE_MAX_BLOCK_CHARS,
        "contrast": mail_lists.HIDDEN_CONTRAST_BELOW, "unseen": mail_lists.UNSEEN_HOLD_OVER,
        "image_letters": mail_lists.IMAGE_ONLY_MAX_VISIBLE_LETTERS,
        "budget_days": mail_lists.BUDGET_WINDOW_DAYS, "budget_count": mail_lists.BUDGET_EARLIER_DRAFTS,
        "budget_lookback": mail_lists.BUDGET_LOOKBACK_DAYS,
        "phone_min": mail_lists.PHONE_MIN_DIGITS, "phone_max": mail_lists.PHONE_MAX_DIGITS,
        "draft_body": mail_lists.DRAFT_BODY_MAX_CHARS, "draft_subject": mail_lists.DRAFT_SUBJECT_MAX_CHARS,
        "url_tail": mail_lists.DRAFT_ALLOWED_URL_TAIL_MAX_CHARS,
        # fix round 3
        "share": round(mail_lists.UNCERTAIN_SHARE_HOLD * 100), "share_chars": mail_lists.UNCERTAIN_SHARE_MIN_CHARS,
        "raise": mail_lists.WORD_TEXT_RAISE_MAX_PX, "word_table": mail_lists.WORD_TABLE_MARGIN_PT,
        "right_width": mail_lists.RIGHT_ANCHORED_WIDTH_PX, "clip_push": mail_lists.CELL_CLIP_PUSH_PX,
        "clip_spacing": mail_lists.CELL_CLIP_SPACING_PX,
    }
    lines = (INTRO % facts).splitlines() + [""]
    lines += rule_tables() + gap_table() + override_table()
    lines += (AS_BUILT_SCAN % facts).splitlines() + [""]
    lines += (AS_BUILT_DRAFT % facts).splitlines() + [""]
    lines += ["## 7. Fixed lists of `mail_lists.py`", "",
              "Every public constant of the module but the two tables above, in the order of the file. "
              "Lines that start with `#` are the comments of the module.", ""]
    for title, entries in sections():
        kept = [(name, comment_lines) for name, comment_lines in entries if name not in TABLE_NAMES]
        if kept:
            lines += ["### %s" % title, ""] + entry_block(mail_lists, kept) + [""]
    lines += ["## 8. Fixed words of the other scripts", "",
              "`mailscan.VOCABULARY`, the whole set a value of an output line may be, is the union of the "
              "word lists of sections 7 and 8.", ""]
    for module, title, names in OTHER_MODULES:
        lines += ["### %s" % title, ""] + entry_block(module, [(name, []) for name in names]) + [""]
    text = "\n".join(lines).rstrip("\n") + "\n"
    text.encode("ascii")
    return text


# --------------------------------------------------------------------------------------
# Reading it back
# --------------------------------------------------------------------------------------

def parse_entries(text: str) -> Dict[str, Dict[str, Any]]:
    """{heading: {name: value}} for every entry of every fenced block under a `###` heading."""
    out: Dict[str, Dict[str, Any]] = {}
    heading, inside, name, buffer = "", False, "", []

    def close() -> None:
        if name:
            out.setdefault(heading, {})[name] = json.loads(" ".join(buffer))

    for line in text.splitlines():
        if not inside:
            if line.startswith("### "):
                heading = line[4:]
            elif line == FENCE + "text":
                inside, name, buffer = True, "", []
            continue
        if line == FENCE:
            close()
            inside, name, buffer = False, "", []
            continue
        if line.startswith("#") or not line.strip():
            continue
        match = ENTRY.match(line)
        if match:
            close()
            name, buffer = match.group(1), [match.group(2)]
        else:
            buffer.append(line.strip())
    return out


def parse_table(text: str, heading: str) -> List[List[str]]:
    """The rows of the first table under the heading `heading`, cells stripped of code marks."""
    rows: List[List[str]] = []
    lines = text.splitlines()
    start = lines.index(heading)
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        if line.startswith("| ") and not line.startswith("|---"):
            cells = [part.strip() for part in line.strip().strip("|").split("|")]
            rows.append(["" if part == "-" else part.strip("`") if part.startswith("`") and part.endswith("`")
                         and part.count("`") == 2 else part for part in cells])
        elif rows and not line.strip():
            break
    return rows[1:]


def main(argv: List[str]) -> int:
    if argv == ["--write"]:
        os.makedirs(os.path.dirname(REFERENCE), exist_ok=True)
        with open(REFERENCE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render())
        return 0
    if argv == ["--check"]:
        try:
            with open(REFERENCE, "r", encoding="utf-8", newline="") as fh:
                current = fh.read()
        except OSError:
            current = ""
        if current == render():
            return 0
        sys.stderr.write("rules-and-gaps.md is stale: run rules_reference.py --write\n")
        return 1
    sys.stderr.write("usage: rules_reference.py --write | --check\n")
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
