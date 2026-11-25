#!/usr/bin/env python3
"""mail_lists.py -- every fixed list, bound, rule id and frame constant of mail-scan (#351).

DATA ONLY. This module is the one place a rule id, a gap name, a bound or a list entry is
written. The parser, the view, the rules, the state, the draft check and the CLI use these
names and never a literal of their own, and `references/rules-and-gaps.md` prints them (a
test compares the two). Changing an entry needs a test and a line in the report of the
change.

    RULES            rule id -> class, hold, reply effect and our fixed description
    GAPS             gap name -> class, hold, reply effect and our fixed description
    vocabulary       verdict words, reply words, hold kinds, override kinds
    bounds           bytes, MIME depth, parts, headers, view cap, wrap width, draft caps,
                     budget, purge ages, the hidden-text thresholds
    lists            hidden phrases, dangerous extensions and media types, leading-byte
                     signatures, chat-template control tokens, multi-label suffixes, the
                     no-reply, role-label, phone, quote and bare-host patterns, the charset
                     allowlist, the element allowlist
    frame constants  the line prefix, the marker shape, the fixed lines of a view

WHAT THE LISTS ARE NOT. The hidden phrases are matched ONLY against text that was removed
from a message because it was hidden. Nothing here is matched against the text a person
would see: a list of phrases is trivially rewritten, so visible text gets no phrase rule.

The phrases and the control tokens below are data that reads like an instruction or like a
chat-template turn. They are entries of a list. Nothing in this file is addressed to a
reader.

Every character outside printable ASCII is written as an escape.

Stdlib only (`re` and `typing`). No I/O. Importing this module has no side effects.
"""
from __future__ import annotations

import re
from typing import Dict, NamedTuple, Tuple

# Bumped whenever an entry changes; recorded with the scanner version in every record.
LISTS_VERSION = "10"

# --------------------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------------------

VERDICT_PASS = "pass"
VERDICT_CAUTION = "caution"
VERDICT_BLOCK = "block"
VERDICTS = (VERDICT_PASS, VERDICT_CAUTION, VERDICT_BLOCK)

REPLY_DRAFT = "draft"
REPLY_NONE_AUTOMATED = "none-automated"
REPLY_NONE_LIST = "none-list"
REPLY_HELD = "held"
REPLIES = (REPLY_DRAFT, REPLY_NONE_AUTOMATED, REPLY_NONE_LIST, REPLY_HELD)

HOLD_BLOCK = "block"
HOLD_BUDGET = "budget"
HOLD_HELD = "held"
HOLD_KINDS = (HOLD_BLOCK, HOLD_BUDGET, HOLD_HELD)

# What `override --kind` takes. `list` lifts no hold: it turns none-list into draft.
OVERRIDE_LIST = "list"
OVERRIDE_KINDS = (HOLD_BLOCK, OVERRIDE_LIST, HOLD_BUDGET, HOLD_HELD)

DRAFT_ACCEPT = "accept"
DRAFT_REFUSE = "refuse"
DRAFT_RESULTS = (DRAFT_ACCEPT, DRAFT_REFUSE)

EXIT_PASS = 0        # pass, accept
EXIT_CAUTION = 1
EXIT_BLOCK = 2       # block, refuse
EXIT_USAGE = 3       # usage or environment error

CLASS_BLOCK = "block"
CLASS_CAUTION = "caution"
CLASS_REPLY = "reply"        # decides the reply, never the verdict
CLASS_REFUSE = "refuse"      # a reason `check-draft` refuses a draft
RULE_CLASSES = (CLASS_BLOCK, CLASS_CAUTION, CLASS_REPLY, CLASS_REFUSE)
GAP_CLASSES = (CLASS_BLOCK, CLASS_CAUTION)

# The reply effect of a gap: the reply is held, or the gap does not touch the reply.
EFFECT_HELD = "held"
EFFECT_NONE = "none"
REPLY_EFFECTS = (EFFECT_HELD, EFFECT_NONE)


# --------------------------------------------------------------------------------------
# Rule table
# --------------------------------------------------------------------------------------

class Rule(NamedTuple):
    rule_id: str
    rule_class: str
    hold: str            # the hold kind a hit puts in force; "" for none
    reply: str           # the reply word a hit decides; "" when it does not decide one
    description: str     # fixed text owned by us: the only prose a caller may print


# (id, description). A hit is a block; a block always holds the reply (hold kind `block`).
_BLOCK_RULES = (
    ("header-ambiguous", "A header that must be single is missing, repeated or names more "
                         "than one mailbox"),
    ("tag-characters", "Unicode tag characters in the message"),
    ("bidi-override", "A bidirectional control in the From name, the Subject or a link"),
    ("from-name-address", "The From display name holds an address in another domain"),
    ("control-token", "A chat-template control token in visible text"),
    ("frame-forgery", "A line prefix, a marker or the note opening of the mail-scan frame in visible text"),
    ("attachment-dangerous", "An attachment with a dangerous extension or media type"),
    ("attachment-type-mismatch", "An attachment whose declared type disagrees with its "
                                 "leading bytes"),
    ("link-scheme", "A link with a script or data scheme"),
    ("link-userinfo", "A link with user information before the host"),
    ("hidden-phrase", "A listed phrase in text that was hidden from the reader"),
)

# (id, hold, description). A hit is a caution; `hold` is the hold kind it also puts in force.
_CAUTION_RULES = (
    ("hidden-text", "", "Hidden text was removed beyond the preheader allowance"),
    ("uncertain-removal", "", "Text was removed because its visibility could not be decided"),
    ("uncertain-share", HOLD_HELD, "Text whose visibility could not be decided is a large share of a part: "
                                   "a draft is never written from half a message"),
    ("format-characters", "", "Format characters were stripped"),
    ("unseen-characters", HOLD_HELD, "More characters no reader sees were stripped from the shown text than "
                                     "ordinary writing holds"),
    ("sender-unverified", "", "The sender is not verified"),
    ("from-name-irregular", "", "The From display name is written irregularly; the mailbox is clear"),
    ("dmarc-fail", HOLD_HELD, "The provider reported a DMARC failure: a reply would go to an address it says was forged"),
    ("auth-header-unreadable", HOLD_HELD, "The provider's own Authentication-Results header cannot be read: a DMARC "
                                          "failure in it would not be seen"),
    ("attachment-present", "", "The message carries an attachment"),
    ("attachment-active-content", "", "An HTML or SVG attachment: a file that can run script when it is opened"),
    ("link-punycode", "", "A link host in punycode form"),
    ("link-mixed-script", "", "A link host that mixes scripts in one label"),
    ("link-ip-literal", "", "A link host that is an IP address"),
    ("link-text-mismatch", "", "Link text that names another host than the link"),
    ("link-unreadable", "", "A link whose host could not be read"),
    ("role-label", "", "A line that starts with a role label"),
    ("comment-conditional", "", "A conditional comment: content only some mail programs show"),
    ("hidden-phrase-weak", "", "A phrase in hidden text that ordinary hidden text also uses"),
    ("inbound-secret", "", "A secret in the inbound text was masked"),
    ("image-only", HOLD_HELD, "No text a person would read: image-only or attachment-only mail"),
)

# (id, hold, reply, description). These decide the reply and leave the verdict alone.
_REPLY_RULES = (
    ("reply-budget", HOLD_BUDGET, REPLY_HELD,
     "The sender already has the allowed number of draft replies in the window"),
    ("reply-auto-submitted", "", REPLY_NONE_AUTOMATED, "The message is marked as auto-submitted"),
    ("reply-null-return-path", "", REPLY_NONE_AUTOMATED, "The message has a null return path"),
    ("reply-no-reply-sender", "", REPLY_NONE_AUTOMATED, "The sender is a no-reply address"),
    ("reply-auto-response-suppress", "", REPLY_NONE_AUTOMATED,
     "The message asks for automatic responses to be suppressed"),
    ("reply-own-address", "", REPLY_NONE_AUTOMATED, "The message is from one of our own addresses"),
    ("reply-list", "", REPLY_NONE_LIST, "The message is list or bulk mail"),
)

# (id, description). Each is a reason `check-draft` refuses a draft.
_REFUSE_RULES = (
    ("draft-markup", "The draft holds markup, or image or link syntax"),
    ("draft-url", "The draft holds a URL or host that is not on the allowed list"),
    ("draft-url-query", "The draft holds an allowed host with a query string"),
    ("draft-bare-host", "The draft holds a bare host name"),
    ("draft-secret", "The draft holds a secret"),
    ("draft-address", "The draft holds an address other than our own and the reply target"),
    ("draft-phone", "The draft holds a phone number that is not approved"),
    ("draft-hidden-characters", "The draft holds characters no reader sees, or a pile of combining marks"),
    ("draft-white-space", "The draft uses white space in a way it can carry what nobody sees (one space, one kind of "
                          "line ending)"),
    ("draft-mixed-script", "A word of the draft mixes letters of two scripts, or a mark sits on a letter of another"),
    ("draft-body-too-long", "The draft body is over the length cap"),
    ("draft-subject-too-long", "The draft subject is over the length cap"),
    ("draft-digit-run", "The draft holds a run of digits found in neither the inbound view "
                        "nor the knowledge pack"),
    ("draft-canary", "The draft holds the configured canary"),
    ("draft-record-missing", "There is no record for this draft"),
    ("draft-view-missing", "The view of the scanned message is gone"),
    ("draft-record-blocked", "The scanned message is blocked"),
    ("draft-reply-not-allowed", "The reply decision of the scanned message is not draft"),
    ("draft-reply-target", "The reply target is not the sender of the scanned message, or is not written "
                           "as one bare address"),
    ("draft-control-characters", "The draft holds control characters, or its subject holds "
                                 "a line break"),
    ("draft-catalog-missing", "The secrets catalog is missing or cannot be used, so the "
                              "draft was not checked for secrets"),
    ("draft-knowledge-pack", "The knowledge pack named in the config cannot be read"),
)

RULES: Dict[str, Rule] = {}
for _rid, _desc in _BLOCK_RULES:
    RULES[_rid] = Rule(_rid, CLASS_BLOCK, HOLD_BLOCK, REPLY_HELD, _desc)
for _rid, _hold, _desc in _CAUTION_RULES:
    RULES[_rid] = Rule(_rid, CLASS_CAUTION, _hold, REPLY_HELD if _hold else "", _desc)
for _rid, _hold, _reply, _desc in _REPLY_RULES:
    RULES[_rid] = Rule(_rid, CLASS_REPLY, _hold, _reply, _desc)
for _rid, _desc in _REFUSE_RULES:
    RULES[_rid] = Rule(_rid, CLASS_REFUSE, "", "", _desc)

BLOCK_RULE_IDS = tuple(r[0] for r in _BLOCK_RULES)
CAUTION_RULE_IDS = tuple(r[0] for r in _CAUTION_RULES)
REPLY_RULE_IDS = tuple(r[0] for r in _REPLY_RULES)
REFUSE_RULE_IDS = tuple(r[0] for r in _REFUSE_RULES)


# --------------------------------------------------------------------------------------
# Gap table
# --------------------------------------------------------------------------------------

class Gap(NamedTuple):
    name: str
    gap_class: str
    reply_effect: str    # EFFECT_HELD or EFFECT_NONE
    hold: str            # the hold kind it puts in force; "" when the reply is untouched
    description: str     # fixed text owned by us


_GAPS = (
    # block class: the reply is held with hold kind `block`
    ("charset-unsupported", CLASS_BLOCK, "A charset outside the allowlist, or a decode with "
                                         "too many replacement characters"),
    ("structure-over-bound", CLASS_BLOCK, "The message is over a size, depth, part or header bound"),
    ("parse-defect", CLASS_BLOCK, "The parser recorded a defect on a selected part or on From"),
    ("alternative-ambiguous", CLASS_BLOCK, "An alternative with no usable text part"),
    ("related-root-invalid", CLASS_BLOCK, "A related message whose root part cannot be used, or is not its "
                                          "first part"),
    ("catalog-missing", CLASS_BLOCK, "The secrets catalog is missing or cannot be used"),
    ("scanner-error", CLASS_BLOCK, "The scanner failed; the message was not judged"),
    # caution class, reply held with hold kind `held`
    ("html-ambiguous", CLASS_CAUTION, "Markup a parser and a browser read differently"),
    ("nested-message", CLASS_CAUTION, "A message nested inside the message"),
    ("alternative-duplicate-html", CLASS_CAUTION, "An alternative with more than one HTML part"),
    ("alternative-other-text", CLASS_CAUTION, "An alternative with a text part of another type"),
    ("multipart-unknown", CLASS_CAUTION, "A multipart type with no written selection rule"),
    # caution class, the reply is not touched
    ("css-unresolved", CLASS_CAUTION, "A style block or an outside style sheet: read by a strict reader that is "
                                      "no browser, or never fetched"),
    ("view-truncated", CLASS_CAUTION, "The view was cut at its length cap"),
)
# The two caution gaps that leave the reply alone.
_GAPS_NO_REPLY_EFFECT = frozenset({"css-unresolved", "view-truncated"})

GAPS: Dict[str, Gap] = {}
for _name, _class, _desc in _GAPS:
    if _class == CLASS_BLOCK:
        GAPS[_name] = Gap(_name, _class, EFFECT_HELD, HOLD_BLOCK, _desc)
    elif _name in _GAPS_NO_REPLY_EFFECT:
        GAPS[_name] = Gap(_name, _class, EFFECT_NONE, "", _desc)
    else:
        GAPS[_name] = Gap(_name, _class, EFFECT_HELD, HOLD_HELD, _desc)

GAP_NAMES = tuple(g[0] for g in _GAPS)

# The bounds a `structure-over-bound` gap names.
BOUND_BYTES = "bytes"
BOUND_DEPTH = "depth"
BOUND_PARTS = "parts"
BOUND_HEADER_LINES = "header-lines"
BOUND_HEADER_LENGTH = "header-length"
BOUND_NAMES = (BOUND_BYTES, BOUND_DEPTH, BOUND_PARTS, BOUND_HEADER_LINES, BOUND_HEADER_LENGTH)


# One more bound, set by the parser for its own inventory (it is not a bound of the design):
# a message with more links than MAX_LINKS is over a bound as well.
BOUND_LINKS = "links"
# And one added in fix round 1: the wall-clock budget of one scan (SCAN_SECONDS). The parser,
# the view and the rules each report it under this name when it runs out in them.
BOUND_TIME = "time"
PARSE_BOUND_NAMES = BOUND_NAMES + (BOUND_LINKS, BOUND_TIME)

# What a gap may say beside its name: a word of ours that tells where it was met. The
# detail of structure-over-bound is the bound name.
DETAIL_NONE = ""
DETAIL_FROM = "from"                         # parse-defect: a defect on the From header
DETAIL_PART = "part"                         # parse-defect: a defect on a selected part
DETAIL_STRUCTURE = "structure"               # parse-defect: a defect on the message or a container
DETAIL_TRANSFER_ENCODING = "transfer-encoding"   # parse-defect: an unknown transfer encoding
DETAIL_ERROR = "error"                       # parse-defect: the parser failed on the message
DETAIL_BARE_CR = "bare-cr"                   # parse-defect: a header line ended by a carriage return alone
DETAIL_START = "start"                       # related-root-invalid: `start` names a part that is not the first
DETAIL_DISPOSITION = "disposition"           # alternative-ambiguous: the body a reader may show is marked as an attachment
DETAIL_STYLE = "style"                       # css-unresolved: a style block outside the reader's language: nothing of the part is shown
DETAIL_EXTERNAL = "external"                 # css-unresolved: a link to a style sheet, never fetched: nothing of the part is shown
DETAIL_BODY = "body"                         # charset-unsupported: in a selected part
DETAIL_HEADER = "header"                     # charset-unsupported: in an encoded header word
# html-ambiguous says which form was met. `structure` (elements closed in an order a
# browser may read another way) and `error` (the HTML reader failed) are the words above.
DETAIL_COMMENT_UNCLOSED = "comment-unclosed"         # a comment that is never closed
DETAIL_COMMENT_CONDITIONAL = "comment-conditional"   # a conditional comment that is malformed
DETAIL_ELEMENT = "element"                   # an element of HTML_AMBIGUOUS_ELEMENTS
DETAIL_NULL_BYTE = "null-byte"
DETAIL_TOKENS = "tokens"                     # the standard parser and a browser split the markup differently
HTML_AMBIGUOUS_DETAILS = (DETAIL_COMMENT_UNCLOSED, DETAIL_COMMENT_CONDITIONAL, DETAIL_ELEMENT,
                          DETAIL_NULL_BYTE, DETAIL_TOKENS, DETAIL_STRUCTURE, DETAIL_ERROR)
GAP_DETAILS = (DETAIL_NONE, DETAIL_FROM, DETAIL_PART, DETAIL_STRUCTURE, DETAIL_TRANSFER_ENCODING,
               DETAIL_ERROR, DETAIL_BODY, DETAIL_HEADER) + PARSE_BOUND_NAMES + (
                   DETAIL_COMMENT_UNCLOSED, DETAIL_COMMENT_CONDITIONAL, DETAIL_ELEMENT,
                   DETAIL_NULL_BYTE, DETAIL_TOKENS, DETAIL_BARE_CR, DETAIL_START, DETAIL_DISPOSITION,
                   DETAIL_STYLE, DETAIL_EXTERNAL)


def describe(name: str) -> str:
    """Our fixed description of a rule id or a gap name. Raises KeyError for any other text."""
    if name in RULES:
        return RULES[name].description
    return GAPS[name].description


# --------------------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------------------

MAX_BYTES_DEFAULT = 2_000_000        # the config may lower or raise it; checked before parsing
MAX_MIME_DEPTH = 8
MAX_PARTS = 50
MAX_HEADER_LINES = 300               # per header block (the message, and each part)
MAX_HEADER_LINE_BYTES = 8_192        # one header, after unfolding
# The three headers that decide how a part is read are parsed by the standard library at a
# cost that grows much faster than their length, so each is bounded far lower, and BEFORE
# the standard parser sees the message: one over this, after unfolding, is over the bound
# `header-length`. The count is of the value, in bytes.
MIME_HEADER_NAMES = ("content-type", "content-disposition", "content-transfer-encoding")
MAX_MIME_HEADER_BYTES = 1_000
# The wall-clock budget of one scan, in seconds. It is checked inside the loops of the
# parser, the view and the rules; when it runs out the message is over the bound `time`.
SCAN_SECONDS = 10.0

VIEW_MAX_CHARS = 16_000              # a cut is the gap view-truncated
FRAME_WRAP_WIDTH = 200
LINK_HOST_MAX_CHARS = 80
PREHEADER_ALLOWANCE_CHARS = 150      # hidden text up to this length is not a caution
UNCERTAIN_HOLD_CHARS = 200           # uncertain removal OVER this holds the reply
# The share hold (fix round 3, S11): a part whose uncertain removal is at least this share
# of its text (shown and uncertain together) AND at least this many characters holds the
# reply, under the caution `uncertain-share`. A draft is never written from half a message.
UNCERTAIN_SHARE_HOLD = 0.30
UNCERTAIN_SHARE_MIN_CHARS = 40
IMAGE_ONLY_MAX_VISIBLE_LETTERS = 3   # image-only: FEWER visible letters or digits than this, and an image
CHARSET_REPLACEMENT_MAX_RATIO = 0.01  # a decode with MORE replacement characters is unsupported

MAX_LINKS = 1_000                    # links inventoried in one message (the parser's own bound)
# The view's own bounds on one HTML part. Past either, the rest of the part is not shown.
VIEW_MAX_ELEMENT_DEPTH = 200         # elements open inside one another
VIEW_MAX_PENDING_ELEMENTS = 64       # elements closed out of order whose style may still apply

DRAFT_BODY_MAX_CHARS = 8_000
DRAFT_SUBJECT_MAX_CHARS = 200

BUDGET_EARLIER_DRAFTS = 3            # this many earlier draft-eligible mails hold the next one
BUDGET_WINDOW_DAYS = 7
# How far back of a moment record files are opened to find the FIRST record of a message:
# the window twice. A record file older than that is not opened by the budget query.
BUDGET_LOOKBACK_DAYS = 14
PURGE_VIEW_DAYS = 7                  # views and sheets
PURGE_RECORD_DAYS = 90
RETENTION_STALE_DAYS = 2             # an older or absent last-purge: "retention: not running"

# THE STYLE READER (the view). It asks whether a style can be PROVEN harmless. It accepts the
# small language written out below and treats everything outside it as UNCERTAIN: it does not
# recover from an error as a browser does, and it never decides that one declaration beats
# another. An element is judged over the WORST of its `style` attribute and of every rule of
# a style block whose selector could match it, and it gets one of three answers: proven
# hidden, uncertain, visible.
#
# Proven hidden.
HIDDEN_OPACITY_BELOW = 0.1           # the product of the opacities down the ancestors
HIDDEN_FONT_SIZE_BELOW_PX = 6.0      # a font size under this (em and % multiply down the ancestors)
HIDDEN_BOX_BELOW_PX = 4.0            # a height or width under this, where overflow is clipped
HIDDEN_OFFSET_BEYOND_PX = 500.0      # offsets, negative margins and a text-indent, summed down the ancestors
HIDDEN_CONTRAST_BELOW = 1.5          # text against every background it may stand on
HIDDEN_LETTER_SPACING_BELOW_EM = -0.5    # glyphs drawn on top of one another
# The uncertain band: between what is proven hidden and what ordinary mail uses. The sums
# are taken down the ancestors, each property at the worst value it may get.
UNCERTAIN_FONT_SIZE_BELOW_PX = 8.0   # 6px up to (not including) 8px
UNCERTAIN_OFFSET_BEYOND_PX = 100.0   # text pushed right or down by offsets, in sum
UNCERTAIN_NEGATIVE_MARGIN_BEYOND_PX = 8.0    # text pulled left by negative margins and offsets, in sum: the page
#                                              has a margin of 8px, and Word pulls a table 5.4pt to the left
UNCERTAIN_UPWARD_SHIFT_BEYOND_PX = 8.0       # text pulled up (it may leave the top of the page), in sum
UNCERTAIN_LETTER_SPACING_BELOW_PX = -2.0     # tighter than this (and tighter than -0.1em)
UNCERTAIN_LETTER_SPACING_BELOW_EM = -0.1
# UNCERTAIN in full, whatever their size: the text of an element whose overflow is anything
# but `visible` (what such a box shows depends on sizes this reader does not work out: a line
# height, a table, a flex container), of an element with a height or width under
# HIDDEN_BOX_BELOW_PX, and of a table that has such a column. With both, it is proven hidden.
#
# A negative text-indent (it is inherited) is UNCERTAIN on every element that holds lines of
# its own (TEXT_BLOCK_ELEMENTS) unless the left margins and left paddings that element and the
# blocks around it have FOR CERTAIN are at least as wide: the hanging indent of a list. An
# element that may be laid out another way (a `display` value, or taken out of the flow) has
# no such room, and neither has what stands in an inline element that sets the indent.
TEXT_BLOCK_ELEMENTS = ("body", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "center",
                       "address", "section", "article", "header", "footer", "main", "nav", "aside", "figure",
                       "figcaption", "dt", "dd", "td", "th", "caption")
#
# Lengths: a number (digits, an optional fraction; no exponent) with one of these units, or
# a plain 0. An absolute unit is converted to px; `em` is the font size of the element.
# Nothing else is a length: no `rem` (it is read against a root size the message may set),
# no calc(), var(), clamp(), no viewport unit.
CSS_ABSOLUTE_UNITS = (("px", 1.0), ("pt", 96.0 / 72.0), ("pc", 16.0), ("in", 96.0), ("cm", 96.0 / 2.54),
                      ("mm", 96.0 / 25.4))
CSS_FONT_UNITS = (("em", 1.0),)
# `ex` and `ch` (fix round 3, S4) are lengths ONLY in a margin or a padding that is not
# negative: Gmail writes the margin and the padding of a quote in `ex`. Such a length is read
# as at most an em where it pushes text, and as no room at all for a hanging indent; in any
# other property it is UNCERTAIN.
CSS_MARGIN_ONLY_UNITS = ("ex", "ch")
CSS_UNITS = (tuple(unit for unit, _factor in CSS_ABSOLUTE_UNITS)
             + tuple(unit for unit, _factor in CSS_FONT_UNITS) + CSS_MARGIN_ONLY_UNITS + ("%",))
# Colours: `#rgb`, `#rrggbb`, `rgb(n, n, n)`, `rgba(n, n, n, a)` (whole numbers to 255, a from
# 0 to 1), `transparent`, `inherit`, one of the 148 colour names of CSS, and the system
# colours below (Word writes `windowtext`), read as on a default page. Nothing else: no hsl(),
# no `currentcolor`, no other system colour, no 4- or 8-digit hex.
CSS_SYSTEM_COLOURS = (("windowtext", "000000"), ("window", "ffffff"))
# THE PROPERTIES WHOSE VALUE IS READ, each against its own pattern (`mail_view._accept`):
#   display            one of CSS_DISPLAY_SHOWN, or none
#   visibility         visible, hidden, collapse
#   opacity            a number or a percentage
#   font-size          a length, a size keyword (xx-small .. xxx-large, smaller, larger), inherit
#   color              a colour
#   background-color   a colour;  background: ONE colour, or none (no other form of the shorthand)
#   height, width, max-height, max-width     a length that is not negative, or auto / none / inherit
#   overflow(-x, -y)   visible, hidden, clip, scroll, auto
#   position           static, relative (fix round 3, S3: `absolute`, `fixed` and `sticky` are
#                      UNCERTAIN, and so is `relative` beside an offset that is not 0 or auto)
#   top, right, bottom, left                 a length, or auto
#   text-indent        a length
CSS_PROPERTIES = ("display", "visibility", "opacity", "font-size", "color", "background-color",
                  "height", "width", "max-height", "overflow", "position", "top", "right",
                  "bottom", "left", "text-indent")
#   margin, padding and their four sides     one to four lengths (margin: or auto), none over 500px.
#                      A NEGATIVE margin is UNCERTAIN (fix round 3, S6), with one exception: the
#                      longhand `margin-left` of a <table>, in its style attribute, from -5.75pt up
#                      to 0 in `pt` (Word pulls a table it writes by its cell padding, -5.4pt or
#                      -5.75pt). See WORD_TABLE_MARGIN_PT.
#   letter-spacing, word-spacing             normal, or a length
#   line-height        normal, a number up to LINE_HEIGHT_MAX_FACTOR, a length up to LINE_HEIGHT_MAX_PX
#   min-width          a length that is not negative, or auto / inherit (it fixes a width, as width does)
#   padding-inline-start   a length that is not negative, none over 500px; never room for an indent
#   float              none, left, right
#   direction          ltr, rtl, inherit
#   white-space        normal, nowrap, pre, pre-wrap, pre-line, inherit;  text-wrap  wrap, nowrap
#   table-layout       auto, fixed
#   z-index            auto, or a whole number that is not negative
#   mso-hide           any value: none shows, every other value hides
#   mso-text-raise     a length of at most WORD_TEXT_RAISE_MAX_PX either way
#   mso-color-alt and the mso font sizes     as color and font-size
# The `font` shorthand is NOT accepted (Word writes it only around the spaces after a bullet).
CSS_RELATED_PROPERTIES = (
    "background", "max-width", "overflow-x", "overflow-y", "z-index",
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "letter-spacing", "word-spacing", "line-height",
    "mso-hide", "mso-text-raise", "mso-color-alt", "mso-ansi-font-size", "mso-bidi-font-size",
    "mso-fareast-font-size", "mso-ascii-font-size", "mso-hansi-font-size",
    "min-width", "padding-inline-start", "float", "direction", "white-space", "text-wrap", "table-layout",
)
# `table-column` and `table-column-group` are not here (fix round 3, S1): Chrome draws no box
# for them, so they are read as `none`.
CSS_DISPLAY_SHOWN = (
    "block", "inline", "inline-block", "table", "inline-table", "table-row", "table-cell",
    "table-row-group", "table-header-group", "table-footer-group",
    "table-caption", "flex", "inline-flex", "grid", "inline-grid",
    "list-item", "flow-root", "inherit")
CSS_DISPLAY_NONE = ("none", "table-column", "table-column-group")
LINE_HEIGHT_MAX_FACTOR = 10.0
LINE_HEIGHT_MAX_PX = 200.0
WORD_TEXT_RAISE_MAX_PX = 16.0
WORD_TABLE_MARGIN_PT = 5.75
# RIGHT-ANCHORED OVERFLOW (fix round 3, S5). Content wider than its box leaves it on the side
# its box is anchored away from; for a box anchored on the right that is off the page to the
# left, where no scrolling reaches. So the text of an element, and of everything in it, is
# UNCERTAIN when (a) it stands where text runs right to left (a `dir` of rtl or auto on it or
# on an element around it, or `direction: rtl` from any source) and it does not wrap (`nowrap`
# or `pre` from white-space, text-wrap or a `nowrap` attribute, <nobr>, <pre>) or has any width
# of its own (width, min-width, a width attribute); or (b) it stands in an element that is
# floated right, or a <table>, <div> or <img> with align="right", and it does not wrap or has
# a width over RIGHT_ANCHORED_WIDTH_PX or over 100%.
RIGHT_ANCHORED_WIDTH_PX = 600.0
RIGHT_ALIGNED_ELEMENTS = ("table", "div", "img")
NOWRAP_ELEMENTS = ("nobr", "pre")
# A CELL THAT CLIPS (fix round 3, S10): `overflow:hidden` on a <td> or <th> that sets no
# height or width of its own (Google Sheets writes it on every cell) is accepted, and then
# everything in the cell is UNCERTAIN that does not wrap, has a width of its own, or is
# pushed right by more than CELL_CLIP_PUSH_PX (margins, paddings, an indent and spacing,
# summed from the cell in), or spaces its letters or words by more than CELL_CLIP_SPACING_PX.
# In a table laid out `fixed`, a clipping cell must stand in columns that a <col> gives a
# width for: otherwise the whole table is uncertain.
CELL_CLIP_PUSH_PX = 8.0
CELL_CLIP_SPACING_PX = 1.0
# PROPERTIES ACCEPTED WITH ONE OF A FEW FIXED VALUES: with any other value they may hide or
# cover text, so any other value is uncertain.
CSS_FIXED_VALUE_PROPERTIES = (
    ("list-style-image", ("none",)),
    ("transform", ("none",)), ("filter", ("none",)), ("clip", ("auto",)), ("clip-path", ("none",)),
    ("content-visibility", ("visible",)), ("zoom", ("1", "normal", "100%")),
    ("-webkit-text-security", ("none",)), ("text-security", ("none",)),
    ("-webkit-text-stroke-width", ("0", "0px")),
    ("text-shadow", ("none",)), ("box-shadow", ("none",)), ("-webkit-box-shadow", ("none",)),
    ("-moz-box-shadow", ("none",)),
    ("outline", ("none", "0", "0px")), ("outline-style", ("none",)), ("outline-width", ("0", "0px")),
    ("unicode-bidi", ("normal", "embed", "isolate", "plaintext")),
    ("text-decoration-thickness", ("initial", "auto", "from-font")),   # as Chrome writes it into pasted text
    # fix round 3 (S5): flex and grid alignment at its start values only (any other may move
    # content wider than its box off the page to the left)
    ("justify-content", ("normal", "start", "flex-start")), ("align-items", ("normal", "stretch", "start", "flex-start")),
    ("flex-direction", ("row", "column")), ("flex-flow", ("row", "column", "row wrap", "column wrap", "wrap", "nowrap")),
    ("align-self", ("auto", "normal", "stretch", "start", "flex-start")),
    ("align-content", ("normal", "stretch", "start", "flex-start")),
    ("justify-items", ("normal", "stretch", "start")), ("justify-self", ("auto", "normal", "stretch", "start")),
    # fix round 3 (S10): what Google Docs, Google Sheets and Apple Notes write into pasted text,
    # each with the one value they write (checked in Chrome: none of them changes what is drawn)
    ("font-variant-alternates", ("normal",)), ("font-variant-position", ("normal",)),
    ("font-variant-emoji", ("normal",)), ("white-space-collapse", ("collapse", "preserve")),
    ("text-wrap-mode", ("wrap",)), ("font-size-adjust", ("none",)), ("font-optical-sizing", ("auto",)),
    ("font-variation-settings", ("normal",)), ("background-image", ("none", "initial")),
    ("border-image", ("none", "initial")), ("text-decoration-skip-ink", ("auto",)),
    ("text-underline-offset", ("auto",)),
    # fix round 3 (S10): a percentage other than 100% shrinks text in iOS Mail
    ("-webkit-text-size-adjust", ("100%", "none", "auto")), ("text-size-adjust", ("100%", "none", "auto")),
    ("-ms-text-size-adjust", ("100%", "none", "auto")), ("-moz-text-size-adjust", ("100%", "none", "auto")),
)
# PROPERTIES ACCEPTED WITH A LIST OF WORDS: words, numbers with no unit, colours and quoted
# strings, parted by spaces or commas. No length (a thick line through text covers it).
CSS_WORD_ONLY_PROPERTIES = (
    "text-decoration", "text-decoration-line", "text-decoration-color", "text-decoration-style",
)
# PROPERTIES ACCEPTED WITH A PLAIN LIST: words, numbers with or without one of the units
# above, colours and quoted strings, parted by spaces, commas or slashes; no function other
# than rgb() and rgba(), no url(), and no length over STYLE_MAX_LENGTH_PX. In that form
# none of them hides text.
CSS_SAFE_PROPERTIES = (
    # typography
    "font-family", "font-weight", "font-style", "font-variant", "font-variant-caps",
    "font-variant-ligatures", "font-variant-numeric", "font-variant-east-asian", "font-stretch",
    "font-kerning", "font-feature-settings", "font-smoothing", "font-synthesis",
    "text-align", "text-align-last", "text-underline", "text-transform", "text-rendering",
    "text-overflow", "text-justify", "text-autospace", "word-break", "word-wrap",
    "overflow-wrap", "hyphens", "line-break", "vertical-align", "tab-size", "quotes",
    "list-style", "list-style-type", "list-style-position", "counter-reset",
    "counter-increment", "caret-color", "cursor", "tab-stops",
    "punctuation-wrap", "text-kashida-space", "layout-grid", "layout-grid-mode", "layout-flow", "page",
    "-webkit-font-smoothing", "-moz-osx-font-smoothing", "-webkit-nbsp-mode", "-webkit-line-break",
    "-webkit-user-select", "-moz-user-select", "-ms-user-select", "user-select", "-webkit-touch-callout",
    "-webkit-tap-highlight-color", "-webkit-hyphens", "-moz-hyphens",
    "-ms-hyphens", "-ms-word-break", "-ms-interpolation-mode", "-webkit-locale", "-webkit-rtl-ordering",
    # boxes that do not clip, borders, tables
    "min-height", "box-sizing", "-webkit-box-sizing", "-moz-box-sizing", "clear",
    "border", "border-top", "border-right", "border-bottom", "border-left", "border-color", "border-style",
    "border-width", "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
    "border-top-style", "border-right-style", "border-bottom-style", "border-left-style",
    "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
    "border-radius", "border-top-left-radius", "border-top-right-radius", "border-bottom-left-radius",
    "border-bottom-right-radius", "-webkit-border-radius", "-moz-border-radius", "border-collapse",
    "border-spacing", "empty-cells",
    "caption-side", "background-repeat", "background-position", "background-size", "background-attachment",
    "background-origin", "background-clip", "-webkit-background-size",
    # layout that moves a box and does not hide it (the alignments are fixed values, above)
    "flex", "flex-wrap", "flex-grow", "flex-shrink", "flex-basis",
    "gap", "row-gap", "column-gap", "order",
    # the rest: no effect on whether text is seen
    "pointer-events", "resize", "page-break-before", "page-break-after", "page-break-inside",
    "break-before", "break-after", "break-inside", "orphans", "widows", "appearance", "-webkit-appearance",
    "-moz-appearance", "accent-color", "speak", "touch-action",
    "scroll-behavior", "ime-mode", "color-adjust", "print-color-adjust",
    "-webkit-print-color-adjust", "forced-color-adjust", "image-rendering", "isolation",
)
STYLE_MAX_LENGTH_PX = 1_000.0
# Every property of Word that starts with this is accepted with a plain list too (no bound
# on its numbers), except the ones read above (`mso-hide`, `mso-text-raise`, the Word font
# sizes, `mso-color-alt`) and the ones named after it, which change how text is drawn and
# are UNCERTAIN.
CSS_SAFE_PREFIX = "mso-"
CSS_UNSAFE_WORD_PROPERTIES = ("mso-font-width", "mso-text-animation", "mso-element",
                              "mso-style-textfill-fill-alpha", "mso-style-textfill-fill-color",
                              "mso-effects-shadow-alpha", "mso-display", "mso-special-character")
# A custom property (`--name`) with a plain list does nothing by itself; var() is not accepted.
CSS_CUSTOM_PROPERTY_PREFIX = "--"
# An offset or a margin in percent has no pixel value. A negative one, and one beyond this,
# is UNCERTAIN.
UNCERTAIN_OFFSET_BEYOND_PERCENT = 100.0
# THE STYLE BLOCK. A <style> block is READABLE only if everything in it is of this language:
# rules whose selectors are made of a tag, `.class`, `#id`, `[attribute]`, a pseudo-class or
# pseudo-element with no brackets, the descendant and child combinators and comma lists;
# `@media` around such rules; the at-rules passed over below; `<!--` first and `-->` last.
# An UNREADABLE block (any other at-rule, `@import`, `@namespace`, `@supports` and `@layer`
# among them; a rule in a rule; a stray token; `<!--` or `-->` elsewhere; a backslash outside
# a passed-over at-rule; over a bound; a <style> tag with any attribute but `type="text/css"`
# and `style`), a <link> to a style sheet and a page that allows a dark colour scheme make
# EVERY element of the part uncertain: nothing of the part is shown. A selector of any other
# form, in a readable block, applies its rule to every element.
CSS_GROUP_AT_RULES = ("media",)
# These hold no rule for an element; their block (no brace inside) is passed over. `@list`
# is Word's.
CSS_PASSED_AT_RULES = ("page", "list")
# `@font-face` (fix round 3, S2) may shrink or blank the glyphs of a family the message then
# names. Its block is passed over only when every descriptor in it is one of these, with the
# value forms Outlook writes (a family name; numbers; a style or weight keyword or number;
# for `mso-*` a plain list). Any other descriptor (`src`, `size-adjust`, `ascent-override`
# and the other `*-override`, `unicode-range`, ...) makes the block UNREADABLE.
CSS_FONT_FACE_AT_RULE = "font-face"
CSS_FONT_FACE_DESCRIPTORS = ("font-family", "panose-1", "font-style", "font-weight")
STYLE_BLOCK_ATTRIBUTES = ("type", "style")
STYLE_BLOCK_TYPE = "text/css"
COLOUR_SCHEME_META_NAMES = ("color-scheme", "supported-color-schemes")
# Pseudo-classes every browser knows: a selector list that uses no other is one a browser
# applies. Any pseudo-class is read as "may hold" (also :hover: the text is then hidden while
# the pointer is over it).
CSS_PLAIN_PSEUDO_CLASSES = ("link", "visited", "hover", "active", "focus")
# Pseudo-elements that style something other than the text of the element: a rule whose
# selector ends in one says nothing about what a reader sees. (What such a rule draws OVER
# the text is a limit of the view, stated in the reference.)
CSS_OTHER_PSEUDO_ELEMENTS = ("before", "after", "selection", "-moz-selection", "placeholder", "marker",
                             "backdrop", "-webkit-scrollbar", "-webkit-input-placeholder",
                             "-moz-placeholder", "-ms-input-placeholder", "file-selector-button")
# The reader's own bounds. Over one of them the attribute or the block is unreadable.
STYLE_MAX_ATTRIBUTE_CHARS = 2_000    # a style attribute over this is not parsed
STYLE_MAX_BLOCK_CHARS = 64_000       # one style block
STYLE_MAX_RULES = 2_000              # selectors in the style blocks of one part
STYLE_MAX_NESTING = 2                # @media inside @media
STYLE_MAX_VALUES = 8                 # distinct values of one property in one declaration list or on one element
STYLE_MAX_SOURCES = 64               # rules that could match one element
# The (colour, background) pairs kept for one element. An element with more is UNCERTAIN.
STYLE_MAX_COLOUR_PAIRS = 24
# What a page shows when a message sets nothing: black text of this size on white. A page
# without a doctype gives the text of a <table> that colour and that size again, whatever
# stands around the table (the "quirks mode" of browsers): both readings are judged.
DEFAULT_FONT_SIZE_PX = 16.0
# The size a browser gives the text of these elements, as a factor of the size around them.
ELEMENT_FONT_FACTORS = (("small", 1 / 1.2), ("sub", 1 / 1.2), ("sup", 1 / 1.2), ("h5", 0.83), ("h6", 0.67))


# --------------------------------------------------------------------------------------
# Charsets and elements
# --------------------------------------------------------------------------------------

# Compared after `codecs.lookup`, so the usual aliases of each resolve to it.
CHARSET_ALLOWLIST = ("utf-8", "us-ascii", "iso-8859-1", "iso-8859-15", "windows-1252")

# Text is kept only from these elements. Any other element drops its content and is counted.
ELEMENT_ALLOWLIST = (
    "p", "div", "span", "br", "a", "b", "strong", "i", "em", "u", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
    "table", "thead", "tbody", "tr", "td", "th",
    "font",     # not in the list of the design, which reads colour from it: added in WP-2
    # Added in WP-2 by decision of the lead, so that ordinary templates keep their text.
    "center", "small", "big", "sup", "sub", "code", "tt", "kbd", "samp", "var", "s", "strike", "del",
    "ins", "abbr", "cite", "q", "dfn", "mark", "address", "section", "article", "header", "footer",
    "main", "nav", "aside", "figure", "figcaption", "label", "caption", "tfoot", "dl", "dt", "dd",
    "hr", "col", "colgroup",        # the last three hold no text
    # Added in fix round 1: inline elements ordinary mail writes around visible words.
    "nobr", "time", "bdi", "bdo",
)
# A tag name of one of these two shapes is an element name: a plain or hyphenated name, or
# a name with one namespace prefix (o:p, v:shape). Anything else that the standard parser
# reads as a tag is text a person typed between angle brackets (an address, a URL): what
# it swallows is removed as UNCERTAIN, so it is counted and the view says it is incomplete.
ELEMENT_NAME_PATTERN = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*|[a-z][a-z0-9]*:[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
ELEMENT_NAME = re.compile(ELEMENT_NAME_PATTERN)
# Elements Word writes around ordinary text. Their text is kept like that of an allowlisted
# element: the names of the first tuple, and any name that starts with one of the second.
# Any other element with a colon in its name is not on the allowlist.
WORD_ELEMENTS = ("o:p",)
WORD_ELEMENT_PREFIXES = ("st1:",)
# The two wrappers of a whole document. They hold no text of their own and are walked
# through; without them an ordinary HTML message would have no kept text at all.
TRANSPARENT_ELEMENTS = ("html", "body")
# Elements whose presence is the gap html-ambiguous (with an unclosed comment, a
# conditional comment and a null byte, which are not elements).
# Nothing after one of these elements reaches a view. The first four are the list of the
# design. The rest were added in WP-2: each switches a browser to rules of its own for what
# the tags after it open and close (`math` like svg; inside `select` most tags are dropped;
# a `form` ends without closing what stands in it and is ignored inside another; `frameset`
# is ignored once text was met; `applet`, `marquee` and `object` fence formatting elements
# in, and keep doing so when they are closed out of order).
HTML_AMBIGUOUS_ELEMENTS = ("plaintext", "noscript", "template", "svg", "math", "select", "form",
                           "frameset", "applet", "marquee", "object")
# Of those, the two that change how a browser splits everything after them into tags and
# text: NOTHING of a part that holds one reaches a view, what stands before it included.
HTML_FOREIGN_ELEMENTS = ("svg", "math")
# Attributes whose text is always dropped.
DROPPED_ATTRIBUTES = ("alt", "title")
# Elements that never hold content: they have no end tag and open nothing.
VOID_ELEMENTS = ("area", "base", "basefont", "bgsound", "br", "col", "embed", "frame", "hr", "img",
                 "input", "keygen", "link", "meta", "param", "source", "track", "wbr")
IMAGE_ELEMENTS = ("img",)
# Elements a browser reads as text up to their own end tag: character references are read
# in the first group and not in the second, and a script has rules of its own.
RCDATA_ELEMENTS = ("title", "textarea")
RAWTEXT_ELEMENTS = ("style", "xmp", "iframe", "noembed", "noframes")
SCRIPT_ELEMENT = "script"
STYLE_ELEMENT = "style"         # its presence is the gap css-unresolved
# What may stand in a document head. Anything else ends the head.
HEAD_ELEMENTS = ("base", "basefont", "bgsound", "link", "meta", "title", "noscript", "noframes",
                 "style", "script", "template")
# Elements a browser opens again after they were closed out of order ("formatting elements").
FORMATTING_ELEMENTS = ("a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike",
                       "strong", "tt", "u")
# Elements that start a line of their own in a view; a table cell is followed by a tab.
BLOCK_ELEMENTS = ("p", "div", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
                  "pre", "table", "thead", "tbody", "tr", "tfoot", "caption", "center", "address",
                  "section", "article", "header", "footer", "main", "nav", "aside", "figure",
                  "figcaption", "dl", "dt", "dd")
TABLE_CELL_ELEMENTS = ("td", "th")
TABLE_ELEMENTS = ("table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup")
# The "special" elements of the HTML standard: the end tag of an ordinary element such as
# span never closes across one of these.
SPECIAL_ELEMENTS = (
    "address", "applet", "area", "article", "aside", "base", "basefont", "bgsound", "blockquote",
    "body", "br", "button", "caption", "center", "col", "colgroup", "dd", "details", "dir", "div",
    "dl", "dt", "embed", "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset",
    "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr", "html", "iframe", "img",
    "input", "keygen", "li", "link", "listing", "main", "marquee", "menu", "meta", "nav", "noembed",
    "noframes", "noscript", "object", "ol", "p", "param", "plaintext", "pre", "script", "search",
    "section", "select", "source", "style", "summary", "table", "tbody", "td", "template",
    "textarea", "tfoot", "th", "thead", "title", "tr", "track", "ul", "wbr", "xmp",
)
# A start tag of one of these closes an open paragraph. `table` is left out on purpose: it
# closes one only in a document with a doctype, so a table is read as inside the paragraph.
P_CLOSING_ELEMENTS = (
    "address", "article", "aside", "blockquote", "center", "details", "dialog", "dir", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hgroup", "hr", "li", "listing", "main", "menu", "nav", "ol", "p", "pre", "search",
    "section", "summary", "ul", "xmp", "dd", "dt",
)
HEADING_ELEMENTS = ("h1", "h2", "h3", "h4", "h5", "h6")
LIST_ELEMENTS = ("ul", "ol")
QUOTE_ELEMENT = "blockquote"
PREFORMATTED_ELEMENT = "pre"
# The colour a browser gives a link that sets none.
LINK_DEFAULT_COLOUR = (0, 0, 238)


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------

# Headers of the message that must be single. A repeated one, and a From that is missing or
# does not name exactly one mailbox, is the block rule header-ambiguous.
SINGLE_HEADERS = ("from", "subject", "reply-to", "content-type", "return-path", "auto-submitted")
# Headers that must be single on EVERY part, because they decide how a part is read: two of
# one are read differently by different mail readers.
SINGLE_PART_HEADERS = ("content-type", "content-transfer-encoding", "content-disposition")
AMBIGUOUS_HEADER_NAMES = SINGLE_HEADERS + ("content-transfer-encoding", "content-disposition")
# The caution the parser reports when a defect on From is confined to the display name.
FROM_NAME_IRREGULAR_RULE = "from-name-irregular"
# Why a header is ambiguous.
HEADER_MISSING = "missing"
HEADER_REPEATED = "repeated"
HEADER_GROUP = "group"               # From in group syntax
HEADER_MAILBOXES = "mailboxes"       # From with other than exactly one mailbox
HEADER_PARAMETER = "parameter"       # Content-Type or Content-Disposition: a parameter given twice in any form, or a list that does not parse
HEADER_REASONS = (HEADER_MISSING, HEADER_REPEATED, HEADER_GROUP, HEADER_MAILBOXES, HEADER_PARAMETER)
# Parameters of Content-Type that decide which bytes are the body and how they are decoded.
# One of them given twice (in any letter case, in the plain or the continued form) is read
# one way by this parser and another way by a mail reader that takes the other value.
SINGLE_PARAMETERS = ("boundary", "charset", "start")

# The transfer encodings a selected part may carry. Any other is the gap parse-defect.
TRANSFER_ENCODINGS = ("7bit", "8bit", "binary", "quoted-printable", "base64")

# A message/* part of one of these subtypes is a nested message.
NESTED_MESSAGE_SUBTYPES = ("rfc822", "global", "news")
# Multipart subtypes with a written selection rule. Any other is read as mixed and is the
# gap multipart-unknown.
MULTIPART_RULES = ("alternative", "mixed", "related", "signed")
# A text part of one of these types inside an alternative is an attachment like any other
# and is NOT the gap alternative-other-text: a calendar invite travels this way.
ALTERNATIVE_ATTACHMENT_TYPES = ("text/calendar",)

# What a part is to the reader of the message.
ROLE_CONTAINER = "container"         # a multipart
ROLE_SELECTED = "selected"           # text that reaches the view
ROLE_UNSELECTED = "unselected"       # body text the selection rule did not pick
ROLE_RESOURCE = "resource"           # a part of a related message other than its root
ROLE_ATTACHMENT = "attachment"
ROLE_NESTED_MESSAGE = "nested-message"
PART_ROLES = (ROLE_CONTAINER, ROLE_SELECTED, ROLE_UNSELECTED, ROLE_RESOURCE, ROLE_ATTACHMENT,
              ROLE_NESTED_MESSAGE)
# The roles that put a part in the attachment inventory.
ATTACHMENT_ROLES = (ROLE_RESOURCE, ROLE_ATTACHMENT, ROLE_NESTED_MESSAGE)

SELECTED_PLAIN = "plain"
SELECTED_HTML = "html"
SELECTED_SUBTYPES = (SELECTED_PLAIN, SELECTED_HTML)

# The value an optional header has, as a word of ours.
VALUE_ABSENT = "absent"
VALUE_OTHER = "other"
AUTO_SUBMITTED_NO = "no"
AUTO_SUBMITTED_AUTO = "auto"         # any value other than `no`
AUTO_SUBMITTED_VALUES = (VALUE_ABSENT, AUTO_SUBMITTED_NO, AUTO_SUBMITTED_AUTO)
RETURN_PATH_NULL = "null"            # the empty path, <>
RETURN_PATH_ADDRESS = "address"
RETURN_PATH_VALUES = (VALUE_ABSENT, RETURN_PATH_NULL, RETURN_PATH_ADDRESS)
PRECEDENCE_VALUES = (VALUE_ABSENT,) + ("bulk", "list", "junk") + (VALUE_OTHER,)
# (a Precedence of AUTO_REPLY_PRECEDENCE_VALUES is reported as `other` here and as auto-submitted)

# A declared media type is text of the sender. An inventory holds it only as one of these
# words: the type itself when it is on this list, else `<main type>/other`, else `other`.
MEDIA_MAIN_TYPES = ("text", "image", "audio", "video", "application", "message", "multipart",
                    "font", "model")
MEDIA_TYPE_OTHER = "other"
COMMON_MEDIA_TYPES = (
    "text/plain", "text/html", "text/calendar", "text/csv", "text/css", "text/xml", "text/rtf",
    "text/x-amp-html", "text/enriched",
    "image/webp", "image/bmp", "image/tiff", "image/heic", "image/x-icon",
    "message/rfc822", "message/delivery-status", "message/disposition-notification",
    "multipart/mixed", "multipart/alternative", "multipart/related", "multipart/signed",
    "multipart/report", "multipart/digest", "multipart/encrypted", "multipart/parallel",
    "application/pkcs7-signature", "application/x-pkcs7-signature", "application/pgp-signature",
    "application/pgp-encrypted", "application/pkcs7-mime", "application/ics",
    "application/json", "application/xml", "application/rtf", "application/msword",
    "application/vnd.ms-excel", "application/vnd.ms-powerpoint", "application/gzip",
    "application/x-7z-compressed", "application/x-rar-compressed", "application/x-tar",
)

# The class of a declared file extension. The extension itself is text of the sender.
EXTENSION_NONE = "none"              # no file name, or a name with no extension
EXTENSION_DANGEROUS = "dangerous"    # on DANGEROUS_EXTENSIONS
EXTENSION_KNOWN = "known"            # in a row of SIGNATURES
EXTENSION_OTHER = "other"
EXTENSION_CLASSES = (EXTENSION_NONE, EXTENSION_DANGEROUS, EXTENSION_KNOWN, EXTENSION_OTHER)
SIGNATURE_NONE = "none"              # the content starts with no listed signature


# --------------------------------------------------------------------------------------
# Hidden phrases (matched ONLY against removed text; see the module docstring)
# --------------------------------------------------------------------------------------

# Two lists. Both are matched against text that was PROVEN hidden and against nothing else:
# never against text removed as uncertain, never against visible text. A hit of the first
# is a block. The second holds phrases that ordinary hidden text (a preheader, a block
# shown on phones only) also uses; a hit is a caution.
HIDDEN_PHRASE_PATTERNS = (
    r"ignore (all|any|the)? ?(previous|prior|above) instructions",
    r"disregard (the|your) (system|previous)",
    r"system prompt",
    r"new instructions",
    r"do not tell the user",
)
HIDDEN_PHRASES = tuple(re.compile(p, re.IGNORECASE) for p in HIDDEN_PHRASE_PATTERNS)
HIDDEN_PHRASE_WEAK_PATTERNS = (
    r"you are now",
    r"reply with",
    r"forward (this|all)",
)
HIDDEN_PHRASES_WEAK = tuple(re.compile(p, re.IGNORECASE) for p in HIDDEN_PHRASE_WEAK_PATTERNS)


# --------------------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------------------

# Without the dot, lower case.
DANGEROUS_EXTENSIONS = (
    "exe", "scr", "com", "pif", "bat", "cmd", "msi", "js", "jse", "vbs", "vbe", "wsf", "wsh",
    "hta", "ps1", "lnk", "jar", "iso", "img", "vhd", "docm", "xlsm", "pptm",
    "dll", "so", "dylib", "sys", "cpl",
)
DANGEROUS_MEDIA_TYPES = (
    "application/x-msdownload", "application/x-dosexec", "application/java-archive",
)
# Active content: a file that can run script when a person opens it. As an ATTACHMENT it is
# the caution attachment-active-content (it is never parsed and never reaches a view); an
# inline HTML body part is the message itself. These were on the two lists above until WP-3a.
ACTIVE_CONTENT_EXTENSIONS = ("html", "htm", "svg")
ACTIVE_CONTENT_MEDIA_TYPES = ("text/html", "image/svg+xml", "application/xhtml+xml")
# An extension that says nothing about the content, like a generic media type: the name a
# mail program gives a part it cannot name. It agrees with any leading bytes.
GENERIC_EXTENSIONS = ("bin", "dat")
# A declared type that says nothing about the content: it agrees with any leading bytes.
GENERIC_MEDIA_TYPES = ("application/octet-stream",)


class Signature(NamedTuple):
    name: str
    leading: Tuple[bytes, ...]       # any of these at offset 0
    extensions: Tuple[str, ...]      # declared extensions that agree with it
    media_types: Tuple[str, ...]     # declared media types that agree with it


# Leading-byte signatures, used to detect a declared type that disagrees with the content:
# content that starts with a signature under an extension or media type that is not in its
# row, or a declared extension or media type of a row over content that does not start so.
SIGNATURES = (
    Signature("mz", (b"MZ",), ("exe", "scr", "com", "pif", "dll"),
              ("application/x-msdownload", "application/x-dosexec",
               "application/vnd.microsoft.portable-executable")),
    Signature("elf", (b"\x7fELF",), ("elf", "so"),
              ("application/x-executable", "application/x-elf", "application/x-sharedlib")),
    Signature("macho", (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"),
              ("dylib",), ("application/x-mach-binary",)),
    Signature("script", (b"#!",), ("sh",),
              ("application/x-sh", "application/x-shellscript", "text/x-shellscript", "text/x-sh")),
    Signature("zip", (b"PK\x03\x04",),
              ("zip", "jar", "docx", "xlsx", "pptx", "docm", "xlsm", "pptm", "odt", "ods", "odp"),
              ("application/zip", "application/x-zip-compressed", "application/x-zip", "application/java-archive",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "application/vnd.ms-word.document.macroenabled.12",
               "application/vnd.ms-excel.sheet.macroenabled.12",
               "application/vnd.ms-powerpoint.presentation.macroenabled.12",
               "application/vnd.oasis.opendocument.text",
               "application/vnd.oasis.opendocument.spreadsheet",
               "application/vnd.oasis.opendocument.presentation")),
    Signature("pdf", (b"%PDF-",), ("pdf",), ("application/pdf", "application/x-pdf")),
    Signature("png", (b"\x89PNG\r\n\x1a\n",), ("png",), ("image/png", "image/x-png")),
    Signature("jpeg", (b"\xff\xd8\xff",), ("jpg", "jpeg", "jpe", "jfif"), ("image/jpeg", "image/jpg", "image/pjpeg")),
    Signature("gif", (b"GIF87a", b"GIF89a"), ("gif",), ("image/gif",)),
)
SIGNATURE_NAMES = tuple(s.name for s in SIGNATURES)
# Content that starts with one of these is a program or a script whatever its name or
# declared type says: the block rule attachment-dangerous.
DANGEROUS_SIGNATURES = ("mz", "elf", "macho", "script")

# CHARACTERS NO READER SEES, beyond the three classes of `mail_reuse` (tag, bidi, format).
# The Unicode property Default_Ignorable_Code_Point as inclusive ranges (Unicode 16): the
# variation selectors, the Hangul fillers, the combining grapheme joiner, the Mongolian
# selectors, the Khmer inherent vowels, and the reserved code points of that property.
DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5),
    (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF))
# Not of that property, and drawn as nothing all the same: the blank braille pattern, the
# musical null notehead and the Khitan filler.
BLANK_CODE_POINTS = (0x2800, 0x1D159, 0x16FE4)
# The two exceptions, in a view and in a draft alike: a variation selector directly after
# an emoji base, and a zero-width joiner between two emoji (see the emoji ranges below).
EMOJI_VARIATION_SELECTORS = (0xFE0E, 0xFE0F)
# Emoji bases outside the emoji ranges: the keycap bases and the older symbols that are
# drawn as an emoji when a variation selector follows.
EMOJI_EXTRA_BASES = (0x0023, 0x002A, 0x0030, 0x0031, 0x0032, 0x0033, 0x0034, 0x0035, 0x0036, 0x0037, 0x0038,
                     0x0039, 0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x24C2, 0x25AA, 0x25AB, 0x25B6,
                     0x25C0, 0x25FB, 0x25FC, 0x25FD, 0x25FE, 0x2934, 0x2935, 0x3030, 0x303D, 0x3297, 0x3299)
# More characters of that kind than this, stripped from the SHOWN text of one message, is
# the caution `unseen-characters`, which holds the reply. Characters in text that was
# removed as hidden (a preheader padded with them) are not counted here.
UNSEEN_HOLD_OVER = 16
# A draft may put at most this many combining marks on one base character.
DRAFT_MAX_COMBINING_MARKS = 2
# The cap counts the marks of these blocks only: the general combining marks, which stack on
# any letter. The marks of a script (Devanagari, Burmese, Tibetan, Thai, Arabic, Hebrew and
# the rest) are how that script is written and are not capped.
DRAFT_GENERAL_MARK_RANGES = ((0x0300, 0x036F), (0x1AB0, 0x1AFF), (0x1DC0, 0x1DFF), (0x20D0, 0x20FF),
                             (0xFE20, 0xFE2F))
# A zero-width non-joiner between two letters of this script is how Persian is written: allowed.
DRAFT_NON_JOINER_CODE_POINT = 0x200C
DRAFT_NON_JOINER_SCRIPT = "ARABIC"
# WHITE SPACE IS A CHANNEL nobody sees when a draft is approved, so a draft holds only the
# space U+0020 and the line break, used one way: refused (`draft-white-space`) are every other
# space character (the no-break space among them), a tab, white space at the start or the end
# of a line, two spaces in a row, a blank line at the start, more than this many blank lines in
# a row, more than one line break at the end, and line endings of both kinds (all LF, or all
# CRLF). Lines are counted by their place in the text (fix round 3, D1).
DRAFT_MAX_BLANK_LINES = 2
# The one exception, so that French typography and grouped digits stay writable: a no-break
# space or a narrow no-break space directly between two digits, directly before one of the
# marks below, or directly after an opening guillemet; ONE of the two kinds in a text, and one
# USE in a text (fix round 3, D3): where a no-break space stands before a mark (or between
# digits), a plain space in the same place elsewhere in the text is refused. What remains is
# one choice a text, a bit nobody sees: no-break spaces there, or plain ones.
DRAFT_TYPOGRAPHIC_SPACES = "\u00a0\u202f"
DRAFT_TYPOGRAPHIC_SPACE_BEFORE = "?!:;\u00bb"
DRAFT_TYPOGRAPHIC_SPACE_AFTER = "\u00ab"
# A word that mixes letters of two of these scripts is refused (`draft-mixed-script`): the
# look-alike letters of one stand in for the other's and no reader sees it. A word is its
# letters with the combining marks on them (fix round 3, D2: a mark does not split a word),
# and its scripts are judged from its letters.
DRAFT_MIXED_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK")
# The one mixed word accepted (fix round 3, D4): a unit, of at most this many Latin letters and
# exactly one of the Greek letters below (micro, Omega, Delta: kilo-ohm, micrometre, a difference of T). Digits beside it are no letters.
DRAFT_UNIT_GREEK = "\u03bc\u03a9\u0394"
DRAFT_UNIT_MAX_LATIN = 3
# A mark of a script (named after it: ARABIC, HEBREW, DEVANAGARI, THAI ...) only on a letter or
# a mark of that same script (fix round 3, D5). A mark named COMBINING is a general one, and a
# variation selector (an emoji drawn in colour) belongs to no script.
DRAFT_GENERAL_MARK_NAMES = ("COMBINING", "VARIATION")

# The three flags written with tag characters that are a recommended emoji: a black flag
# (U+1F3F4), the tag letters of one of these codes, and the cancel tag (U+E007F). Exactly
# these sequences, whole, are not counted as tag characters.
FLAG_BASE_CODE_POINT = 0x1F3F4
FLAG_CANCEL_CODE_POINT = 0xE007F
FLAG_TAG_OFFSET = 0xE0000
SUBDIVISION_FLAG_CODES = ("gbeng", "gbsct", "gbwls")


# --------------------------------------------------------------------------------------
# Chat-template control tokens and labels
# --------------------------------------------------------------------------------------

# Literal tokens. A hit anywhere in visible text is a block.
CONTROL_TOKENS = (
    "<|im_start|>", "<|im_end|>", "<|system|>", "<|user|>", "<|assistant|>", "<|endoftext|>",
    "[INST]", "[/INST]", "<<SYS>>", "<</SYS>>", "<s>", "</s>",
)
# Of those, the two that are also ordinary markup talk (the tag of struck-through text). They
# count only when the message has a selected text/plain part, or stand in the Subject or the
# From name: in an HTML part a person sees them only where the sender wrote them as text.
CONTROL_TOKENS_PLAIN_ONLY = ("<s>", "</s>")

# A line that starts with a role label, after optional leading markup characters. A caution.
# `human:` and `assistant:` at the start of a line that follows a blank line were a block
# until fix round 1: a person writes "Human: please help" too.
ROLE_LABELS = ("system:", "assistant:", "user:", "developer:", "tool:", "human:")
ROLE_LABEL_LINE = re.compile(
    r"^[ \t>*_#~\x60\-]*(?:system|assistant|user|developer|tool|human):", re.IGNORECASE | re.MULTILINE)


# --------------------------------------------------------------------------------------
# Senders
# --------------------------------------------------------------------------------------

# Matched against the local part of the From address.
NO_REPLY_LOCAL_PART_PATTERN = r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|bounces?)"
NO_REPLY_LOCAL_PART = re.compile(NO_REPLY_LOCAL_PART_PATTERN, re.IGNORECASE)

# Precedence values of list mail.
LIST_PRECEDENCE_VALUES = ("bulk", "list", "junk")
# What older auto-responders write instead of Auto-Submitted: a Precedence value, or the mere
# presence of one of these headers. Each makes the message auto-submitted (`none-automated`).
AUTO_REPLY_PRECEDENCE_VALUES = ("auto_reply",)
AUTO_REPLY_HEADERS = ("x-autoreply", "x-autorespond", "x-auto-reply")


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------

# A link with one of these schemes is a block.
DANGEROUS_LINK_SCHEMES = ("javascript", "data", "vbscript")
# The flags the URL reader of mail_reuse sets, each with the rule it raises.
LINK_FLAG_RULES = (
    ("scheme", "link-scheme"),
    ("userinfo", "link-userinfo"),
    ("punycode", "link-punycode"),
    ("mixed_script", "link-mixed-script"),
    ("ip_literal", "link-ip-literal"),
    ("unreadable", "link-unreadable"),
)


# How a link was written. `anchor`: the href of an <a> element. `text`: a URL typed as text.
LINK_ANCHOR = "anchor"
LINK_TEXT = "text"
LINK_KINDS = (LINK_ANCHOR, LINK_TEXT)
# One more flag, set by the parser and not by the URL reader: the text of an anchor names
# another host than its href.
LINK_TEXT_MISMATCH_FLAG = "text_mismatch"
LINK_TEXT_MISMATCH_RULE = "link-text-mismatch"
LINK_FLAGS = tuple(flag for flag, _rule in LINK_FLAG_RULES) + (LINK_TEXT_MISMATCH_FLAG,)
# A URL typed as text: a web or file-transfer scheme, or a host that starts with `www.`.
# The parser inventories each match and the view replaces each match, so both read this one
# pattern. A match ends before trailing punctuation (URL_TRAILING_PUNCTUATION is cut off).
URL_IN_TEXT_PATTERN = r"(?:(?:https?|ftps?)://|www\.)[^\s<>\"'\x60\x00-\x20\x7f]+"
URL_IN_TEXT = re.compile(URL_IN_TEXT_PATTERN, re.IGNORECASE)
URL_TRAILING_PUNCTUATION = ".,;:!?)]}"
# The anchor text read for the flag text_mismatch is cut at this length.
ANCHOR_TEXT_MAX_CHARS = 500


# --------------------------------------------------------------------------------------
# Numbers and hosts in a draft
# --------------------------------------------------------------------------------------

# A maximal run of digits, allowing the separators between them and one leading plus.
DIGIT_SEPARATORS = " .-()"
DIGIT_RUN = re.compile(r"\+?\d(?:[ .\-()]*\d)*")
# The run is a phone number when it holds this many digits; the phone rule then decides it
# and the digit-run rule is not applied.
PHONE_MIN_DIGITS = 9
PHONE_MAX_DIGITS = 15
# The same rule as one pattern, for a whole run: an optional plus, then 9 to 15 digits
# allowing spaces, dots, hyphens and brackets.
PHONE_PATTERN = r"\+?\d(?:[ .\-()]*\d){8,14}"
PHONE = re.compile(PHONE_PATTERN)
# The digit-run rule covers runs of this many digits or more that are not phone numbers
# (so 7, 8, and 16 or more).
DIGIT_RUN_MIN_DIGITS = 7

# A bare host: a token with a dot whose last label is alphabetic and two or more letters.
# The host part of an address never matches (the token may not follow an at sign or a dot).
BARE_HOST_PATTERN = r"(?<![\w.@-])(?:[^\W_](?:[\w-]{0,61}[^\W_])?\.)+[^\W\d_]{2,}(?![\w-])"
BARE_HOST = re.compile(BARE_HOST_PATTERN)


# --------------------------------------------------------------------------------------
# What the draft check reads a draft with
# --------------------------------------------------------------------------------------
# The draft check is the last look at text on its way to a customer, and whoever wrote the
# inbound message may have steered the model that wrote the draft. So it reads a draft
# after NFKC and after the folds below, and its own host pattern is LOOSER than BARE_HOST
# above (which the parser uses to compare the text of an anchor with its link): no
# look-behind and no look-ahead, so a host is found behind an underscore, a hyphen or a dot
# and in front of one, and a last label in the xn-- form counts as alphabetic.

# Characters a reader takes for a full stop; each is read as one. (NFKC already writes the
# full-width and small full stops, the one dot leader and the Greek ano teleia as one of
# these or as a full stop.) The list is finite: a dot drawn some other way is not found.
# The ideographic full stop (U+3002, and its half-width form) is NOT on it: it ends every
# Japanese and Chinese sentence, and two words of such a sentence are no host. Between two
# ASCII labels of which the second is a top-level domain (`evil`, the ideographic full stop, `com`) it is a host dot all the
# same (fix round 3, D5): that is no sentence of either language.
DRAFT_IDEOGRAPHIC_DOT = "\u3002"
DRAFT_DOT_LOOKALIKES = ("\u00b7\u2022\u2219\u22c5\u30fb\u06d4\u0589\u2e31\u2e33\u2027"
                        "\u25e6\ua78f\u16eb\u0701\u0702\u2e3c\ua4ff")
# The minus sign is read as a hyphen, like every character of Unicode category Pd.
DRAFT_DASH_LOOKALIKES = "\u2212"
# Spaces too thin to see between two letters. A draft is read twice where it holds one:
# with each as a space (a separator between digits) and with each taken out (so a host
# with one before its dot is still a host).
DRAFT_THIN_SPACES = "\u2006\u2008\u2009\u200a\u202f\u205f"
# A chain of labels with dots between them. It is a HOST when a label after the first is a
# top-level domain: a name of DRAFT_TLDS, a label in the xn-- form, or two or more letters
# outside ASCII (a top-level domain in another script). For the last label its leading
# letters are read, so a hyphen or a digit glued to a top-level domain hides nothing. A
# label of over 63 characters is still found, from a later character.
DRAFT_HOST_PATTERN = r"(?:[^\W_][\w-]{0,62}\.)+[^\W_][\w-]{0,62}"
DRAFT_HOST = re.compile(DRAFT_HOST_PATTERN)
# THE TOP-LEVEL DOMAINS: a snapshot of the IANA root zone list (data.iana.org, the file
# tlds-alpha-by-domain.txt), taken on DRAFT_TLDS_SNAPSHOT_DATE. It replaced a hand-made list
# of generic names in fix round 1: a host under a name that list missed was not found.
# `doctor` warns when the snapshot is over DRAFT_TLDS_MAX_AGE_DAYS old. To renew it, replace
# the names, the version and the date together (with a test and a bumped LISTS_VERSION).
DRAFT_TLDS_SNAPSHOT_VERSION = "2026101300"
DRAFT_TLDS_SNAPSHOT_DATE = "2026-10-13"
DRAFT_TLDS_MAX_AGE_DAYS = 366
DRAFT_TLDS_SNAPSHOT = tuple((
    "aaa aarp abb abbott abbvie abc able abogado abudhabi ac academy accenture accountant accountants aco "
    "actor ad ads adult ae aeg aero aetna af afl africa ag agakhan agency ai aig airbus airforce airtel "
    "akdn al alibaba alipay allfinanz allstate ally alsace alstom am amazon americanexpress "
    "americanfamily amex amfam amica amsterdam analytics android anquan anz ao aol apartments app apple "
    "aq aquarelle ar arab aramco archi army arpa art arte as asda asia associates at athleta attorney au "
    "auction audi audible audio auspost author auto autos aw aws ax axa az azure ba baby baidu banamex "
    "band bank bar barcelona barclaycard barclays barefoot bargains baseball basketball bauhaus bayern bb "
    "bbc bbt bbva bcg bcn bd be beats beauty beer berlin best bestbuy bet bf bg bh bharti bi bible bid "
    "bike bing bingo bio biz bj black blackfriday blockbuster blog bloomberg blue bm bms bmw bn "
    "bnpparibas bo boats boehringer bofa bom bond boo book booking bosch bostik boston bot boutique box "
    "br bradesco bridgestone broadway broker brother brussels bs bt build builders business buy buzz bv "
    "bw by bz bzh ca cab cafe cal call calvinklein cam camera camp canon capetown capital capitalone car "
    "caravan cards care career careers cars casa case cash casino cat catering catholic cba cbn cbre cc "
    "cd center ceo cern cf cfa cfd cg ch chanel channel charity chase chat cheap chintai christmas chrome "
    "church ci cipriani circle cisco citadel citi citic city ck cl claims cleaning click clinic clinique "
    "clothing cloud club clubmed cm cn co coach codes coffee college cologne com commbank community "
    "company compare computer comsec condos construction consulting contact contractors cooking cool coop "
    "corsica country coupon coupons courses cpa cr credit creditcard creditunion cricket crown crs cruise "
    "cruises cu cuisinella cv cw cx cy cymru cyou cz dad dance data date dating datsun day dclk dds de "
    "deal dealer deals degree delivery dell deloitte delta democrat dental dentist desi design dev dhl "
    "diamonds diet digital direct directory discount discover dish diy dj dk dm dnp do docs doctor dog "
    "domains dot download drive dtv dubai dupont durban dvag dvr dz earth eat ec eco edeka edu education "
    "ee eg email emerck energy engineer engineering enterprises epson equipment er ericsson erni es esq "
    "estate et eu eurovision eus events exchange expert exposed express extraspace fage fail fairwinds "
    "faith family fan fans farm farmers fashion fast fedex feedback ferrari ferrero fi fidelity fido film "
    "final finance financial fire firestone firmdale fish fishing fit fitness fj fk flickr flights flir "
    "florist flowers fly fm fo foo food football ford forex forsale forum foundation fox fr free "
    "fresenius frl frogans frontier ftr fujitsu fun fund furniture futbol fyi ga gal gallery gallo gallup "
    "game games gap garden gay gb gbiz gd gdn ge gea gent genting george gf gg ggee gh gi gift gifts "
    "gives giving gl glass gle global globo gm gmail gmbh gmo gmx gn godaddy gold goldpoint golf goodyear "
    "goog google gop got gov gp gq gr grainger graphics gratis green gripe grocery group gs gt gu gucci "
    "guge guide guitars guru gw gy hair hamburg hangout haus hbo hdfc hdfcbank health healthcare help "
    "helsinki here hermes hiphop hisamitsu hitachi hiv hk hkt hm hn hockey holdings holiday homedepot "
    "homegoods homes homesense honda horse hospital host hosting hot hotels hotmail house how hr hsbc ht "
    "hu hughes hyatt hyundai ibm icbc ice icu id ie ieee ifm ikano il im imamat imdb immo immobilien in "
    "inc industries infiniti info ing ink institute insurance insure int international intuit investments "
    "io ipiranga iq ir irish is ismaili ist istanbul it itau itv jaguar java jcb je jeep jetzt jewelry "
    "jio jll jm jmp jnj jo jobs joburg jot joy jp jpmorgan jprs juegos kaufen kddi ke kerryhotels "
    "kerryproperties kfh kg kh ki kia kids kim kindle kitchen kiwi km kn koeln komatsu kosher kp kpmg kpn "
    "kr krd kred kuokgroup kw ky kyoto kz la lacaixa lamborghini lamer land landrover lanxess lasalle lat "
    "latino latrobe law lawyer lb lc lds lease leclerc lefrak legal lego lexus lgbt li lidl life "
    "lifeinsurance lifestyle lighting like lilly limited limo lincoln link live living lk llc llp loan "
    "loans locker locus lol london lotte lotto love lpl lplfinancial lr ls lt ltd ltda lu lundbeck luxe "
    "luxury lv ly ma madrid maif maison makeup man management mango map market marketing markets marriott "
    "marshalls mattel mba mc mckinsey md me med media meet melbourne meme memorial men menu merck "
    "merckmsd mg mh miami microsoft mil mini mint mit mitsubishi mk ml mlb mls mm mma mn mo mobi mobile "
    "moda moe moi mom monash money monster mormon mortgage moscow moto motorcycles mov movie mp mq mr ms "
    "msd mt mtn mtr mu museum music mv mw mx my mz na nab nagoya name navy nba nc ne nec net netbank "
    "netflix network neustar new news next nextdirect nexus nf nfl ng ngo nhk ni nico nike nikon ninja "
    "nissan nissay nl no nokia norton now nowruz nowtv np nr nra nrw ntt nu nyc nz obi observer office "
    "okinawa olayan olayangroup ollo om omega one ong onl online ooo open oracle orange org organic "
    "origins osaka otsuka ott ovh pa page panasonic paris pars partners parts party pay pccw pe pet pf "
    "pfizer pg ph pharmacy phd philips phone photo photography photos physio pics pictet pictures pid pin "
    "ping pink pioneer pizza pk pl place play playstation plumbing plus pm pn pnc pohl poker politie porn "
    "post pr praxi press prime pro prod productions prof progressive promo properties property protection "
    "pru prudential ps pt pub pw pwc py qa qpon quebec quest racing radio re read realestate realtor "
    "realty recipes red redumbrella rehab reise reisen reit reliance ren rent rentals repair report "
    "republican rest restaurant review reviews rexroth rich richardli ricoh ril rio rip ro rocks rodeo "
    "rogers room rs rsvp ru rugby ruhr run rw rwe ryukyu sa saarland safe safety sakura sale salon "
    "samsclub samsung sandvik sandvikcoromant sanofi sap sarl sas save saxo sb sbi sbs sc scb schaeffler "
    "schmidt scholarships school schule schwarz science scot sd se search seat secure security seek "
    "select sener services seven sew sex sexy sfr sg sh shangrila sharp shell shia shiksha shoes shop "
    "shopping shouji show si silk sina singles site sj sk ski skin sky skype sl sling sm smart smile sn "
    "sncf so soccer social softbank software sohu solar solutions song sony soy spa space sport spot sr "
    "srl ss st stada staples star statebank statefarm stc stcgroup stockholm storage store stream studio "
    "study style su sucks supplies supply support surf surgery suzuki sv swatch swiss sx sy sydney "
    "systems sz tab taipei talk taobao target tatamotors tatar tattoo tax taxi tc tci td tdk team tech "
    "technology tel temasek tennis teva tf tg th thd theater theatre tiaa tickets tienda tips tires tirol "
    "tj tjmaxx tjx tk tkmaxx tl tm tmall tn to today tokyo tools top toray toshiba total tours town "
    "toyota toys tr trade trading training travel travelers travelersinsurance trust trv tt tube tui "
    "tunes tushu tv tvs tw tz ua ubank ubs ug uk unicom university uno uol ups us uy uz va vacations vana "
    "vanguard vc ve vegas ventures verisign versicherung vet vg vi viajes video vig viking villas vin vip "
    "virgin visa vision viva vivo vlaanderen vn vodka volvo vote voting voto voyage vu wales walmart "
    "walter wang wanggou watch watches weather weatherchannel web webcam weber website wed wedding weibo "
    "weir wf whoswho wien wiki williamhill win windows wine winners wme woodside work works world wow ws "
    "wtc wtf xbox xerox xihuan xin xn--11b4c3d xn--1ck2e1b xn--1qqw23a xn--2scrj9c xn--30rr7y xn--3bst00m "
    "xn--3ds443g xn--3e0b707e xn--3hcrj9c xn--3pxu8k xn--42c2d9a xn--45br5cyl xn--45brj9c xn--45q11c "
    "xn--4dbrk0ce xn--4gbrim xn--54b7fta0cc xn--55qw42g xn--55qx5d xn--5su34j936bgsg xn--5tzm5g "
    "xn--6frz82g xn--6qq986b3xl xn--80adxhks xn--80ao21a xn--80aqecdr1a xn--80asehdb xn--80aswg "
    "xn--8y0a063a xn--90a3ac xn--90ae xn--90ais xn--9dbq2a xn--9et52u xn--9krt00a xn--b4w605ferd "
    "xn--bck1b9a5dre4c xn--c1avg xn--c2br7g xn--cck2b3b xn--cckwcxetd xn--cg4bki xn--clchc0ea0b2g2a9gcd "
    "xn--czr694b xn--czrs0t xn--czru2d xn--d1acj3b xn--d1alf xn--e1a4c xn--eckvdtc9d xn--efvy88h "
    "xn--fct429k xn--fhbei xn--fiq228c5hs xn--fiq64b xn--fiqs8s xn--fiqz9s xn--fjq720a xn--flw351e "
    "xn--fpcrj9c3d xn--fzc2c9e2c xn--fzys8d69uvgm xn--g2xx48c xn--gckr3f0f xn--gecrj9c xn--gk3at1e "
    "xn--h2breg3eve xn--h2brj9c xn--h2brj9c8c xn--hxt814e xn--i1b6b1a6a2e xn--imr513n xn--io0a7i "
    "xn--j1aef xn--j1amh xn--j6w193g xn--jlq480n2rg xn--jvr189m xn--kcrx77d1x4a xn--kprw13d xn--kpry57d "
    "xn--kput3i xn--l1acc xn--lgbbat1ad8j xn--mgb9awbf xn--mgba3a3ejt xn--mgba3a4f16a xn--mgba7c0bbn0a "
    "xn--mgbaam7a8h xn--mgbab2bd xn--mgbah1a3hjkrd xn--mgbai9azgqp6j xn--mgbayh7gpa xn--mgbbh1a "
    "xn--mgbbh1a71e xn--mgbc0a9azcg xn--mgbca7dzdo xn--mgbcpq6gpa1a xn--mgberp4a5d4ar xn--mgbgu82a "
    "xn--mgbi4ecexp xn--mgbpl2fh xn--mgbt3dhd xn--mgbtx2b xn--mgbx4cd0ab xn--mix891f xn--mk1bu44c "
    "xn--mxtq1m xn--ngbc5azd xn--ngbe9e0a xn--ngbrx xn--node xn--nqv7f xn--nqv7fs00ema xn--nyqy26a "
    "xn--o3cw4h xn--ogbpf8fl xn--otu796d xn--p1acf xn--p1ai xn--pgbs0dh xn--pssy2u xn--q7ce6a xn--q9jyb4c "
    "xn--qcka1pmc xn--qxa6a xn--qxam xn--rhqv96g xn--rovu88b xn--rvc1e0am3e xn--s9brj9c xn--ses554g "
    "xn--t60b56a xn--tckwe xn--tiq49xqyj xn--unup4y xn--vermgensberater-ctb xn--vermgensberatung-pwb "
    "xn--vhquv xn--vuq861b xn--w4r85el8fhu5dnra xn--w4rs40l xn--wgbh1c xn--wgbl6a xn--xhq521b "
    "xn--xkc2al3hye2a xn--xkc2dl3a5ee0h xn--y9a3aq xn--yfro4i67o xn--ygbi2ammx xn--zfr164b xxx xyz yachts "
    "yahoo yamaxun yandex ye yodobashi yoga yokohama you youtube yt yun za zappos zara zero zip zm zone "
    "zuerich zw "
).split())
# The two-letter names of the snapshot: the country codes. A sentence that ends in one of
# these words with no space after the full stop before it reads as a host and is refused.
DRAFT_TLDS_COUNTRY = tuple(name for name in DRAFT_TLDS_SNAPSHOT if len(name) == 2)
DRAFT_TLDS_GENERIC = tuple(name for name in DRAFT_TLDS_SNAPSHOT if len(name) != 2)
# Names that are no top-level domain of the root zone and name a host all the same.
DRAFT_TLDS_SPECIAL = ("onion", "local", "localhost", "internal", "lan", "home", "corp")
DRAFT_TLDS = frozenset(DRAFT_TLDS_SNAPSHOT + DRAFT_TLDS_SPECIAL)
# A host by itself, with no dot.
DRAFT_BARE_NAMES = ("localhost",)
# White space BEFORE the dot of a host (`name .com`): no sentence is written so, and any
# top-level domain after it makes it a host. White space only AFTER the dot is the shape of
# every sentence boundary ("done. It works": `it` is a country code), so there only the
# names of this short list count, which are no words of a sentence.
DRAFT_SPACED_TLDS = ("com", "org", "io", "biz", "xyz")
# An allowed host with and without this first label is one host.
DRAFT_WWW_LABEL = "www."
# A dotted quad with no scheme: a host too.
DRAFT_IPV4_PATTERN = r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d]|\.\d)"
DRAFT_IPV4 = re.compile(DRAFT_IPV4_PATTERN)
# The schemes an allowed host may be written with.
DRAFT_URL_SCHEMES = ("http", "https")
# Schemes that are written without two slashes. One of them followed directly by text is a
# URL, and none of them is allowed in a draft.
DRAFT_SCHEMES_NO_SLASHES = (
    "mailto", "javascript", "data", "vbscript", "file", "sms", "callto", "skype", "facetime",
    "sip", "sips", "xmpp", "whatsapp", "tg", "geo", "magnet", "bitcoin", "intent", "blob",
    "http", "https", "ftp", "ftps", "ws", "wss", "tel", "fax",
)
# A word and a colon followed directly by text is a scheme only when the word is on the list
# above, or when two slashes follow the colon (fix round 2: `Note:closed`, `Size:M` and
# `Re:Order` are ordinary writing). A scheme nobody listed, written without slashes, is not found.
# Fix round 3 (D5): every scheme of Windows that starts `ms-` (`ms-msdt:`, `ms-settings:`), and
# `search-ms`, are refused too.
DRAFT_SCHEME_PREFIX_PATTERNS = (r"ms-[a-z0-9+.\-]*[a-z0-9]", "search-ms")
DRAFT_ANY_SCHEME_PATTERN = r"(?:%s):(?=[^\s:])" % "|".join(DRAFT_SCHEMES_NO_SLASHES + DRAFT_SCHEME_PREFIX_PATTERNS)
# Of those, the words people also write as a label before a number (`Tel:0161 ...`): one
# directly before an approved phone number is a label, not a scheme.
DRAFT_PHONE_LABEL_SCHEMES = ("tel", "fax")
# Two slashes that open a word (`//host/path`): an address with the scheme left out.
DRAFT_SCHEMELESS_URL_PATTERN = r"(?<![\w:/.])//(?=[^\s/])"
DRAFT_SCHEMELESS_URL = re.compile(DRAFT_SCHEMELESS_URL_PATTERN)
# The loopback address written short (`127.1`, `127.0.1`): a host too.
DRAFT_SHORT_LOOPBACK_PATTERN = r"(?<![\d.])127\.(?:0\.)?1(?![\d]|\.\d)"
DRAFT_SHORT_LOOPBACK = re.compile(DRAFT_SHORT_LOOPBACK_PATTERN)
# Where a URL starts when it names its scheme. (It also starts at `www.` and at a host of
# `allowed_hosts`; the draft check builds that part from the config.)
DRAFT_URL_SCHEME_START_PATTERN = (r"[a-z][a-z0-9+.\-]{0,31}://|(?<![a-z0-9+.\-])" + DRAFT_ANY_SCHEME_PATTERN)
# A URL runs from its start to the next white space, quote or angle bracket.
DRAFT_URL_REST_PATTERN = r"[^\s<>\"'\x60]*"
# What may follow an allowed host: a path and a fragment of plain characters. No query, no
# port, no user information, no empty path segment, no second URL.
DRAFT_ALLOWED_URL_TAIL_PATTERN = r"(?:/[A-Za-z0-9._~\-]+)*/?(?:#[A-Za-z0-9._~\-]*)?"
DRAFT_ALLOWED_URL_TAIL = re.compile(DRAFT_ALLOWED_URL_TAIL_PATTERN)
# And it may be this long at most. The number rules and the secret rule read it like any text.
DRAFT_ALLOWED_URL_TAIL_MAX_CHARS = 80
# An address written with colons in square brackets, and a path that starts at another machine.
DRAFT_IPV6_BRACKET_PATTERN = r"\[[0-9A-Fa-f:.%]*:[0-9A-Fa-f:.%]*\]"
DRAFT_IPV6_BRACKET = re.compile(DRAFT_IPV6_BRACKET_PATTERN)
DRAFT_IPV6_BARE_PATTERN = r"(?<![\w:.])[0-9A-Fa-f:.]*::[0-9A-Fa-f:.]*(?![\w:])"
DRAFT_IPV6_BARE = re.compile(DRAFT_IPV6_BARE_PATTERN)
DRAFT_UNC_PATH_PATTERN = r"\\\\[^\s\\/]+[\\/]"
DRAFT_UNC_PATH = re.compile(DRAFT_UNC_PATH_PATTERN)
# Cut from the end of a URL or an address before it is judged, and from the start of an
# address.
DRAFT_TOKEN_TRAILING = ".,;:!?)]}>\"'"
DRAFT_ADDRESS_LEADING = "([{<\"'"
# Markup, and image or link syntax: an HTML tag, comment or character reference; a
# markdown link, image or reference; a bulletin-board link or image tag.
DRAFT_MARKUP_PATTERNS = (
    r"<[A-Za-z/!?]",
    r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});",
    r"!\[",
    r"\]\s{0,2}\(",
    r"\]\s{0,2}\[",
    r"(?m)^[ \t]{0,3}\[[^\]\n]{1,200}\]:",
    r"(?i)\[/?(?:url|img|link|email)\b",
)
DRAFT_MARKUP = tuple(re.compile(p) for p in DRAFT_MARKUP_PATTERNS)
# An approved phone number is recognised at the START of a run of digits; digits after it
# belong to it unless at least this many separator characters lie between.
DRAFT_PHONE_GAP_CHARS = 2
# A trunk zero in brackets after a country code: a run that starts with a plus and holds
# this once is also compared without it.
DRAFT_TRUNK_ZERO = "(0)"
# A calendar date is not a run of digits. These are the shapes; the draft check accepts one
# only when it is a real day of a year in DRAFT_DATE_YEARS and nothing but white space or a
# bracket joins it to other digits. Groups: year, month, day by name.
_DATE_BEFORE = r"(?<!\d)(?<!\d[.\-/])"
_DATE_AFTER = r"(?!\d)(?![.\-/]\d)"
DRAFT_DATE_PATTERNS = (
    _DATE_BEFORE + r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})" + _DATE_AFTER,
    _DATE_BEFORE + r"(?P<day>\d{1,2})(?P<sep>[.\-/])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{4})" + _DATE_AFTER,
)
DRAFT_DATES = tuple(re.compile(p) for p in DRAFT_DATE_PATTERNS)
DRAFT_DATE_YEARS = (1900, 2100)
# Two amounts with two decimal places joined by a hyphen (a price range, or a time range
# written with dots) are two numbers. Group `joint` is what lies between them.
DRAFT_AMOUNT_RANGE_PATTERN = (r"(?<![\d.])(?<!\d-)\d{1,7}\.\d{2}(?P<joint> *- *)\d{1,7}\.\d{2}"
                              r"(?!\d)(?![.\-]\d)")
DRAFT_AMOUNT_RANGE = re.compile(DRAFT_AMOUNT_RANGE_PATTERN)
# A zero-width joiner between two emoji is part of one emoji. A code point counts as an
# emoji here when it lies in one of these ranges; a variation selector or a skin-tone
# modifier may stand between the emoji and the joiner.
DRAFT_JOINER_CODE_POINT = 0x200D
DRAFT_EMOJI_RANGES = ((0x2190, 0x21FF), (0x2300, 0x23FF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
                      (0x1F000, 0x1F2FF), (0x1F300, 0x1FAFF))
DRAFT_EMOJI_TRAILERS = ((0xFE0F, 0xFE0F), (0x1F3FB, 0x1F3FF))
# A canary is also looked for with everything but letters and digits taken out and letter
# case folded, when that form of it is at least this long.
DRAFT_CANARY_SQUEEZED_MIN_CHARS = 6
# The knowledge pack is read up to this size; a larger one cannot be read.
KNOWLEDGE_PACK_MAX_BYTES = 2_000_000


# --------------------------------------------------------------------------------------
# Quoted text
# --------------------------------------------------------------------------------------

# A line that starts with this is quoted.
QUOTE_LINE_PREFIX = ">"
# Everything after the first line matching one of these is quoted. Each is matched against
# one line.
QUOTE_ATTRIBUTION_PATTERNS = (
    r"^On\b.{0,300}\bwrote:\s*$",
    r"^-{2,}\s*Forwarded message\s*-{2,}\s*$",
    r"^Begin forwarded message:\s*$",
    r"^-{2,}\s*Original Message\s*-{2,}\s*$",
)
QUOTE_ATTRIBUTIONS = tuple(re.compile(p, re.IGNORECASE) for p in QUOTE_ATTRIBUTION_PATTERNS)
# Every quoted line of a view starts with this; a line of new text never does.
QUOTED_VIEW_PREFIX = "> "


# --------------------------------------------------------------------------------------
# Frame constants and the fixed lines of a view
# --------------------------------------------------------------------------------------

# Every content line of a framed view starts with this.
FRAME_LINE_PREFIX = "MAILSCAN| "
# Every line the scanner itself adds to a view (the fixed lines below) starts with this
# instead. A line behind FRAME_LINE_PREFIX is text of the message, whatever it says.
FRAME_NOTE_PREFIX = "MAILSCAN# "
# The two markers of a frame are random per message: this many hex characters from `secrets`.
FRAME_MARKER_HEX_CHARS = 16
FRAME_OPEN_FORMAT = "MAILSCAN-BEGIN-%s"
FRAME_CLOSE_FORMAT = "MAILSCAN-END-%s"
# What the rule frame-forgery looks for in visible text: the stem of the line prefix, or a
# marker-shaped string, in any letter case.
FRAME_PREFIX_PATTERN = r"MAILSCAN[|#]"
# The stem of a marker, whatever follows it: a marker of another length is a forgery too.
FRAME_MARKER_PATTERN = r"MAILSCAN-(?:BEGIN|END)"
# The opening of a scanner note, written with any bracket (the rules also read visible text
# with compatibility forms folded, so the stand-in bracket below is found as well).
FRAME_NOTE_PATTERN = r"\[\s*mail-scan\s*:"
FRAME_FORGERY = re.compile("(?:%s|%s|%s)" % (FRAME_PREFIX_PATTERN, FRAME_MARKER_PATTERN, FRAME_NOTE_PATTERN),
                           re.IGNORECASE)
# Angle brackets never reach a framed line; these stand in for them (single guillemets).
FRAME_LT_REPLACEMENT = "\u2039"
FRAME_GT_REPLACEMENT = "\u203a"
# Square brackets of the MESSAGE never reach a view: these stand in for them (the full-width
# forms, which NFKC folds back). So a square bracket in a view was written by the scanner:
# a link token, the secret mask, or one of the fixed lines below.
FRAME_LBRACKET_REPLACEMENT = "\uff3b"
FRAME_RBRACKET_REPLACEMENT = "\uff3d"

# Fixed lines and tokens the view writes. None of them holds text from the message.
COMPLETENESS_WARNING_LINE = ("[mail-scan: some text was removed because its visibility could "
                             "not be decided; this view may be incomplete]")
QUOTED_LABEL_LINE = "[mail-scan: quoted text follows; it is unverified]"
TRUNCATED_LINE = "[mail-scan: the view was cut at its length cap]"
LINK_TOKEN_FORMAT = "[link %d host=%s]"
SECRET_MASK = "[secret removed]"
# The fixed lines above: in a framed view each stands alone behind FRAME_NOTE_PREFIX.
SCANNER_LINES = (COMPLETENESS_WARNING_LINE, QUOTED_LABEL_LINE, TRUNCATED_LINE)
# The host of a link token: only these characters of a host are shown, any other is
# written as LINK_HOST_OTHER, and a link with no host shows LINK_HOST_NONE.
LINK_HOST_SHOWN = re.compile(r"[A-Za-z0-9._:\-]")
LINK_HOST_OTHER = "?"
LINK_HOST_NONE = "-"
# The number of a link the inventory does not list. A view never shows it for a message
# the parser read; a caller that meets it treats the scan as failed.
LINK_NUMBER_UNLISTED = 0
