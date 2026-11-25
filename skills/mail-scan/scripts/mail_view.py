#!/usr/bin/env python3
"""mail_view.py -- the view of one message that a model may read (#351).

`build(parsed, checks)` takes the parsed message of `mail_parse` (its selected parts and its
link inventory; this module never imports the parser) and returns a `ViewResult`: the
framed view, and IN MEMORY ONLY the visible text and the text that was removed, with
counts and the view's own gaps. It writes no file and prints nothing.

WHAT REACHES A VIEW. Only text a person reading the message would see.

    elements      text is kept only inside the elements of `mail_lists.ELEMENT_ALLOWLIST`.
                  Any other element drops its content, which is counted. `alt` and `title`
                  are dropped. What the standard parser takes for a tag and is no element
                  name (an address or a URL typed between angle brackets) swallows the
                  text after it: that text is removed as UNCERTAIN, so it is counted and
                  the view says it is incomplete.
    style         a style is shown only when it can be PROVEN harmless. A strict reader
                  accepts a small, exactly specified language (the lists and bounds of
                  `mail_lists`, the patterns of `_accept`) and treats everything outside
                  it as uncertain. It does not recover from an error as a browser does,
                  and it never decides that one declaration beats another: an element is
                  judged over the WORST of its `style` attribute and of every rule of a
                  <style> block whose selector could match it. A style block that is not
                  of the language, a <link> to a style sheet and a page that allows a
                  dark colour scheme put EVERY element of the part in doubt: nothing of
                  the part is shown. The presence of a style block stays the gap
                  `css-unresolved`.
    proven hidden display none; visibility hidden or collapse; the `hidden` attribute;
                  `mso-hide`; a height or width under 4px (or of 0) where overflow is
                  clipped; letter spacing of minus half an em or tighter. Summed or
                  multiplied down the ancestors: an opacity below 0.1; offsets, negative
                  margins and a text-indent beyond 500px. And text whose font size is
                  under 6px in every reading, or whose colour has a contrast below 1.5:1
                  with the background in EVERY pair of colours it may get. That text is
                  REMOVED and counted.
    uncertain     a declaration that is not accepted: a property on no list, a value
                  outside its property's pattern (var(), calc(), a viewport unit, a
                  number with no unit, a colour form other than the few accepted, the
                  `font` shorthand, a `background` of more than one colour); a style
                  attribute that cannot be read (an escape, a character outside ASCII
                  outside a string, an unclosed string, comment or url) or is over 2,000
                  characters; an element whose overflow is not `visible`, or that has a
                  height or width under 4px, with all it holds; a table with a column
                  of no width; the band between proven hidden and ordinary (a font size
                  under 8px in some reading; text pulled left or up by more than 8px, or
                  pushed away by more than 100px, in sum; a negative text-indent with no
                  certain left margin or padding to hang in); `position: fixed`; low
                  contrast in SOME pair of colours the text may get, or where a
                  background is an image. An element that is not resolved to visible is
                  dropped: that text is REMOVED, counted apart, and the fixed
                  completeness warning line is put in the view.
    stripped      tag, bidi and format characters, and every other character no reader
                  sees (`mail_reuse.UNSEEN`: variation selectors, fillers, the combining
                  grapheme joiner and the rest of that Unicode property), are removed
                  after transfer and entity decoding and counted. A variation selector
                  directly after an emoji and a joiner between two emoji stay.
    brackets      a square bracket of the message is written as its full-width form, so a
                  square bracket in a view is the scanner's: a link token, the secret
                  mask, or one of its fixed lines.
    links         every link becomes `[link N host=...]` with the number the parser's
                  inventory gave it (see LINKS below) and its host cut to 80 characters.
    secrets       masked through `mail_reuse.mask_secrets`.
    quoted text   a blockquote element, a line starting with `>`, and everything after the
                  first line matching an attribution or divider pattern of `mail_lists`,
                  is labelled as unverified: a label line, then every quoted line behind
                  `mail_lists.QUOTED_VIEW_PREFIX`.
    cap           16,000 characters; a cut is the gap `view-truncated`.
    time          the scan has a wall-clock budget (`mail_reuse.Budget`). When it runs out
                  here nothing is shown: the view is empty and carries the gap
                  `structure-over-bound` with the detail `time`.

The result is framed by `mail_frame`: lines of the message behind `MAILSCAN| `, the fixed
lines of the scanner behind `MAILSCAN# `.

WHAT A BROWSER AND THE STANDARD PARSER READ DIFFERENTLY. HTML is read with `html.parser`.
A browser reads some markup another way, and text may then be hidden from a person and not
from this module. So, per HTML part:

    tokens        the part is also split into tags, comments and text the way the HTML
                  standard says a browser does (`browser_tokens`, written out here). If
                  that split and the standard parser's differ anywhere, NOTHING of the
                  part is shown (gap `html-ambiguous`, detail `tokens`). The same for a
                  null byte and for a failure of the parser.
    elements      <plaintext>, <noscript>, <template>, <svg> and <math> end what is shown:
                  nothing after one of them reaches the view (detail `element`).
    comments      a comment that is never closed is named (detail `comment-unclosed`). A
                  conditional comment in one of its usual forms is no gap: it is counted
                  (`conditional_comments`, the caution `comment-conditional`, no hold). What
                  the hidden form holds is in a comment for both readers: it is not shown,
                  and its text is removed as proven hidden. What the revealed form
                  surrounds is shown, as a browser shows it. A conditional comment in any
                  other form keeps the gap (detail `comment-conditional`).
    structure     elements closed out of order. The reader below follows the rules of the
                  standard that decide which elements a tag closes (scopes, table context,
                  paragraphs, list items, the re-opening of formatting elements), and where
                  an element that carries a hiding style is closed by anything but its own
                  end tag, later text is shown only if it is visible both with and without
                  that style; otherwise it is removed as uncertain (detail `structure`).

Whatever is in doubt is removed, never shown.

LINKS. The parser numbers the links of each selected part in the order `html.parser`
reports them: an <a> start tag that carries an `href` (kind anchor), and a match of
`mail_lists.URL_IN_TEXT` in a run of character data outside <script> and <style>, or
anywhere in a plain part (kind text). This module walks the same events and labels the
link it meets with the number of that occurrence. A link that is hidden is counted and
not shown. A URL that the inventory does not list (one that only forms once hidden
characters are removed, or across two elements) gets the number
`mail_lists.LINK_NUMBER_UNLISTED` and is counted in `links_unlisted`.

WHAT MAY BE RECORDED. `RECORDABLE_FIELDS` and `MEMORY_ONLY_FIELDS` say it per type, as in
the parser: counts, booleans and gap words may be written; the framed view is message text
and goes only where a view is kept; the visible text and the removed text are never
written anywhere. `recordable(result)` is the only form of a result that may be put in a
record, a sheet or an output.

Stdlib only; its callees are `mail_frame` (the same component) and `mail_reuse`, with the
data of `mail_lists`. Importing this module has no side effects.
"""
from __future__ import annotations

import html
import html.parser
import re
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import mail_frame
import mail_lists
import mail_reuse

GAP_HTML_AMBIGUOUS = "html-ambiguous"
GAP_CSS_UNRESOLVED = "css-unresolved"
GAP_VIEW_TRUNCATED = "view-truncated"
GAP_STRUCTURE_OVER_BOUND = "structure-over-bound"   # the wall-clock budget ran out (detail `time`)
# The gaps this module can report. Each is a name of mail_lists.GAPS.
VIEW_GAPS = (GAP_HTML_AMBIGUOUS, GAP_CSS_UNRESOLVED, GAP_VIEW_TRUNCATED, GAP_STRUCTURE_OVER_BOUND)

# Why text was removed.
VISIBLE = ""
HIDDEN = "hidden"           # proven hidden
UNCERTAIN = "uncertain"     # could not be resolved to visible
OTHER = "other"             # inside an element that is not on the allowlist

# Secrets are masked before the cap, on text of at most this length (the mask reads a long
# line in windows, so it is given bounded text).
MASK_INPUT_CHARS = 2 * mail_lists.VIEW_MAX_CHARS


# --------------------------------------------------------------------------------------
# The result
# --------------------------------------------------------------------------------------

class ViewGap(NamedTuple):
    name: str               # a name of mail_lists.GAPS
    gap_class: str          # from mail_lists.GAPS
    reply_effect: str       # from mail_lists.GAPS
    detail: str             # a word of mail_lists.GAP_DETAILS
    count: int


class ViewCounts(NamedTuple):
    hidden_chars: int       # characters of text removed because it was PROVEN hidden
    uncertain_chars: int    # characters removed because visibility was UNCERTAIN
    dropped_chars: int      # characters inside elements that are not on the allowlist
    dropped_elements: int   # such elements
    dropped_attributes: int     # alt and title attributes
    tag_chars: int          # stripped, by class
    bidi_chars: int
    format_chars: int
    links: int              # link tokens written
    links_unlisted: int     # of those, links the inventory does not list
    secrets_masked: int
    quoted_lines: int
    visible_chars: int      # characters of message text shown (our tokens and labels left out)
    visible_letters: int    # of those, the letters and digits
    images: int             # image elements met
    style_blocks: int
    conditional_comments: int   # conditional comments in a usual form (the caution comment-conditional)
    view_chars: int         # the length of the view before framing
    view_lines: int         # content lines of the framed view


class ViewResult(NamedTuple):
    counts: ViewCounts
    gaps: Tuple[ViewGap, ...]
    warning: bool           # the completeness warning line is in the view
    truncated: bool
    # MESSAGE TEXT from here. `framed` goes only where a view is kept; the rest is never written.
    framed: str             # the framed view: the only form a model may be given
    open_marker: str
    close_marker: str
    visible_text: str       # MEMORY ONLY: the view before masking, cap and frame
    removed_hidden: str     # MEMORY ONLY: text that was proven hidden
    removed_uncertain: str  # MEMORY ONLY: text whose visibility was uncertain
    # Characters no reader sees, other than the three stripped classes, that were taken out
    # of the SHOWN text (see mail_reuse.UNSEEN). A number: it may be recorded.
    unseen_chars: int = 0
    # The selected parts whose uncertain removal is at least UNCERTAIN_SHARE_HOLD of their text
    # and at least UNCERTAIN_SHARE_MIN_CHARS characters (fix round 3, S11). A number.
    uncertain_share_parts: int = 0


MEMORY_ONLY_FIELDS: Dict[str, Tuple[str, ...]] = {
    "ViewGap": (),
    "ViewCounts": (),
    "ViewResult": ("framed", "open_marker", "close_marker", "visible_text", "removed_hidden",
                   "removed_uncertain"),
}
_TYPES = (ViewGap, ViewCounts, ViewResult)
RECORDABLE_FIELDS: Dict[str, Tuple[str, ...]] = {
    cls.__name__: tuple(f for f in cls._fields if f not in MEMORY_ONLY_FIELDS[cls.__name__])
    for cls in _TYPES}


def _plain(value: Any) -> Any:
    name = type(value).__name__
    if name in RECORDABLE_FIELDS and isinstance(value, tuple):
        return {field: _plain(getattr(value, field)) for field in RECORDABLE_FIELDS[name]}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def recordable(result: ViewResult) -> Dict[str, Any]:
    """The recordable fields of a view result as plain data. It holds no text of the message."""
    return _plain(result)


# --------------------------------------------------------------------------------------
# Style: the strict reader
# --------------------------------------------------------------------------------------
#
# The question asked of a style is not "does it hide the text?" but "can it be PROVEN
# harmless?". The reader accepts a small, exactly specified language and treats everything
# outside it as UNCERTAIN. It never recovers from an error the way a browser does, and it
# never decides that one declaration beats another.
#
#   tokens        one tokeniser for style attributes and style blocks, in the order of CSS
#                 Syntax: a string and an unquoted `url(` are read before a comment is
#                 looked for. An unterminated string, comment or url, a line break in a
#                 string, a NUL or any other control character, and a character outside
#                 printable ASCII that stands outside a string or a comment make the WHOLE
#                 attribute or block unreadable. A backslash escape is decoded as CSS
#                 decodes it and is tolerated only inside the block of an at-rule that is
#                 passed over (Word writes its bullet there); anywhere else it makes the
#                 attribute or block unreadable.
#   declarations  a declaration is accepted only when its property is on a list of
#                 `mail_lists` AND its value matches that property's own strict pattern
#                 (`_accept`). Anything else makes its element UNCERTAIN.
#   no cascade    an element is judged over the WORST of its style attribute and of every
#                 rule whose selector could match it. A later, a more specific or an inline
#                 value never rescues it.
#   certain       the style attribute applies for certain; so does a rule outside any
#                 at-rule whose selector list is plain and whose one compound selector
#                 matches the element exactly. Only such a source can rule out "the value
#                 comes from the parent", and it never rules out another declaration.

_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}
_CSS_SPACE = " \t\n\r\f"
_CSS_NEWLINE = "\n\r\f"
_CSS_STRUCTURE = "{}()[];:,!"
_HEX_DIGITS = "0123456789abcdefABCDEF"

_BLACK = (0.0, 0.0, 0.0, 1.0)
_WHITE = (255.0, 255.0, 255.0)
_TRANSPARENT = (0.0, 0.0, 0.0, 0.0)

# The named colours of CSS, as `name hex` pairs: the fixed list a colour value may name.
_NAMED_COLOURS = dict(pair.split(":") for pair in (
    "aliceblue:f0f8ff antiquewhite:faebd7 aqua:00ffff aquamarine:7fffd4 azure:f0ffff "
    "beige:f5f5dc bisque:ffe4c4 black:000000 blanchedalmond:ffebcd blue:0000ff "
    "blueviolet:8a2be2 brown:a52a2a burlywood:deb887 cadetblue:5f9ea0 chartreuse:7fff00 "
    "chocolate:d2691e coral:ff7f50 cornflowerblue:6495ed cornsilk:fff8dc crimson:dc143c "
    "cyan:00ffff darkblue:00008b darkcyan:008b8b darkgoldenrod:b8860b darkgray:a9a9a9 "
    "darkgreen:006400 darkgrey:a9a9a9 darkkhaki:bdb76b darkmagenta:8b008b "
    "darkolivegreen:556b2f darkorange:ff8c00 darkorchid:9932cc darkred:8b0000 "
    "darksalmon:e9967a darkseagreen:8fbc8f darkslateblue:483d8b darkslategray:2f4f4f "
    "darkslategrey:2f4f4f darkturquoise:00ced1 darkviolet:9400d3 deeppink:ff1493 "
    "deepskyblue:00bfff dimgray:696969 dimgrey:696969 dodgerblue:1e90ff firebrick:b22222 "
    "floralwhite:fffaf0 forestgreen:228b22 fuchsia:ff00ff gainsboro:dcdcdc ghostwhite:f8f8ff "
    "gold:ffd700 goldenrod:daa520 gray:808080 green:008000 greenyellow:adff2f grey:808080 "
    "honeydew:f0fff0 hotpink:ff69b4 indianred:cd5c5c indigo:4b0082 ivory:fffff0 khaki:f0e68c "
    "lavender:e6e6fa lavenderblush:fff0f5 lawngreen:7cfc00 lemonchiffon:fffacd "
    "lightblue:add8e6 lightcoral:f08080 lightcyan:e0ffff lightgoldenrodyellow:fafad2 "
    "lightgray:d3d3d3 lightgreen:90ee90 lightgrey:d3d3d3 lightpink:ffb6c1 lightsalmon:ffa07a "
    "lightseagreen:20b2aa lightskyblue:87cefa lightslategray:778899 lightslategrey:778899 "
    "lightsteelblue:b0c4de lightyellow:ffffe0 lime:00ff00 limegreen:32cd32 linen:faf0e6 "
    "magenta:ff00ff maroon:800000 mediumaquamarine:66cdaa mediumblue:0000cd "
    "mediumorchid:ba55d3 mediumpurple:9370db mediumseagreen:3cb371 mediumslateblue:7b68ee "
    "mediumspringgreen:00fa9a mediumturquoise:48d1cc mediumvioletred:c71585 "
    "midnightblue:191970 mintcream:f5fffa mistyrose:ffe4e1 moccasin:ffe4b5 "
    "navajowhite:ffdead navy:000080 oldlace:fdf5e6 olive:808000 olivedrab:6b8e23 "
    "orange:ffa500 orangered:ff4500 orchid:da70d6 palegoldenrod:eee8aa palegreen:98fb98 "
    "paleturquoise:afeeee palevioletred:db7093 papayawhip:ffefd5 peachpuff:ffdab9 "
    "peru:cd853f pink:ffc0cb plum:dda0dd powderblue:b0e0e6 purple:800080 "
    "rebeccapurple:663399 red:ff0000 rosybrown:bc8f8f royalblue:4169e1 saddlebrown:8b4513 "
    "salmon:fa8072 sandybrown:f4a460 seagreen:2e8b57 seashell:fff5ee sienna:a0522d "
    "silver:c0c0c0 skyblue:87ceeb slateblue:6a5acd slategray:708090 slategrey:708090 "
    "snow:fffafa springgreen:00ff7f steelblue:4682b4 tan:d2b48c teal:008080 thistle:d8bfd8 "
    "tomato:ff6347 turquoise:40e0d0 violet:ee82ee wheat:f5deb3 white:ffffff "
    "whitesmoke:f5f5f5 yellow:ffff00 yellowgreen:9acd32").split())
# The system colours ordinary mail writes (Word's `windowtext`), read as on a default page.
_NAMED_COLOURS.update(dict(mail_lists.CSS_SYSTEM_COLOURS))

Colour = Tuple[float, float, float, float]
CssToken = Tuple[str, str]
Length = Tuple[str, float]      # ("px", pixels), ("em", times the font size) or ("%", percent)


def _lower(text: str) -> str:
    """ASCII letters in lower case, and nothing else changed (a browser folds no other letter)."""
    return text.translate(_ASCII_LOWER)


# ---- tokens --------------------------------------------------------------------------

def css_tokens(text: str) -> Optional[List[CssToken]]:
    """The tokens of a style attribute or a style block; None when it is unreadable.

    A token is (kind, text). Kinds: " " white space or a comment; "s" a string; "u" an
    unquoted url(...); "w" a word (any run of other printable ASCII); "n" a word that holds
    a letter or a digit outside ASCII (fix round 3, S10: Word writes a family name with no
    fallback unquoted, `font-family:` and two Chinese letters; it is accepted in a family name and nowhere else);
    "e" a word or a string that holds a backslash escape; "<" and ">" the marks `<!--` and
    `-->`; and each of `{ } ( ) [ ] ; : , !` as itself.
    """
    tokens: List[CssToken] = []
    word: List[str] = []
    escaped = False
    foreign = False
    size = len(text)
    index = 0

    def flush() -> None:
        nonlocal escaped, foreign
        if word:
            tokens.append(("e" if escaped else ("n" if foreign else "w"), "".join(word)))
            del word[:]
        escaped = foreign = False

    while index < size:
        char = text[index]
        if char in _CSS_SPACE:
            flush()
            if not tokens or tokens[-1][0] != " ":
                tokens.append((" ", " "))
            index += 1
        elif char == "/" and text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0 or "\x00" in text[index:end]:
                return None
            flush()
            if not tokens or tokens[-1][0] != " ":
                tokens.append((" ", " "))
            index = end + 2
        elif char in "\"'":
            end = index + 1
            inside = False
            while True:
                if end >= size:
                    return None
                at = text[end]
                if at == "\\":
                    if end + 1 >= size or text[end + 1] in _CSS_NEWLINE:
                        return None
                    inside = True
                    end += 2
                    continue
                if at == char:
                    break
                if at < " " and at != "\t" or at == "\x7f":
                    return None         # a line break ends a string badly; no control character is read
                end += 1
            flush()
            tokens.append(("e" if inside else "s", text[index:end + 1]))
            index = end + 1
        elif char == "\\":
            # an escape, decoded as CSS decodes it: it is part of a word
            index += 1
            if index >= size or text[index] in _CSS_NEWLINE or not " " <= text[index] < "\x7f":
                return None
            if text[index] in _HEX_DIGITS:
                end = index
                while end < size and end - index < 6 and text[end] in _HEX_DIGITS:
                    end += 1
                code = int(text[index:end], 16)
                word.append(chr(code) if 0 < code < 0x110000 and not 0xD800 <= code < 0xE000 else "\ufffd")
                index = end + 1 if end < size and text[end] in _CSS_SPACE else end
            else:
                word.append(text[index])
                index += 1
            escaped = True
        elif char > "\x7f" and char.isalnum():
            word.append(char)           # a letter or a digit outside ASCII: a word of kind "n"
            foreign = True
            index += 1
        elif not " " < char < "\x7f":
            return None                 # a control character, or any other one outside ASCII, outside a string
        elif text.startswith("<!--", index):
            flush()
            tokens.append(("<", "<!--"))
            index += 4
        elif text.startswith("-->", index):
            flush()
            tokens.append((">", "-->"))
            index += 3
        elif char == "(" and _lower("".join(word)).endswith("url"):
            if _lower("".join(word)) != "url":
                return None             # whether a browser reads a url token here is not followed
            end = index + 1
            while end < size and text[end] in _CSS_SPACE:
                end += 1
            if end < size and text[end] in "\"'":
                flush()
                tokens.append(("(", "("))       # url("..."): a function around a string
                index += 1
                continue
            close = end
            while close < size and " " < text[close] < "\x7f" and text[close] not in "\"'()\\":
                close += 1
            rest = close
            while rest < size and text[rest] in _CSS_SPACE:
                rest += 1
            if rest >= size or text[rest] != ")":
                return None
            del word[:]
            escaped = False
            tokens.append(("u", text[end:close]))
            index = rest + 1
        elif char in _CSS_STRUCTURE:
            flush()
            tokens.append((char, char))
            index += 1
        else:
            word.append(char)
            index += 1
    flush()
    return tokens


# ---- values --------------------------------------------------------------------------

_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
_UNIT_PX = dict(mail_lists.CSS_ABSOLUTE_UNITS)
_UNIT_EM = dict(mail_lists.CSS_FONT_UNITS)
_MARGIN_ONLY = frozenset(mail_lists.CSS_MARGIN_ONLY_UNITS)
# the units of a plain list; a length (`_LENGTH`) may also be in `ex` or `ch`, which only a margin or a padding takes
_UNITS = "|".join(sorted(list(_UNIT_PX) + list(_UNIT_EM) + ["%"], key=len, reverse=True))
_LENGTH = re.compile("(%s)(%s)|([+-]?0+(?:\\.0+)?)" % (
    _NUMBER, "|".join(sorted(list(_UNIT_PX) + list(_UNIT_EM) + list(_MARGIN_ONLY) + ["%"], key=len, reverse=True))))
_NUMBER_OR_PERCENT = re.compile("(%s)(%%?)" % _NUMBER)
_HEX_COLOUR = re.compile("#(?:[0-9a-f]{3}|[0-9a-f]{6})")
_BYTE = r" ?([0-9]{1,3}) ?"
_RGB = re.compile(r"rgb\(%s,%s,%s\)" % (_BYTE, _BYTE, _BYTE))
_RGBA = re.compile(r"rgba\(%s,%s,%s, ?(0|1|[01]?\.[0-9]+) ?\)" % (_BYTE, _BYTE, _BYTE))
_PROPERTY_NAME = re.compile(r"-{0,2}[a-z_][a-z0-9_-]*")
_INTEGER = re.compile(r"[0-9]{1,6}")
# One atom of a plain list: a word, a number with an optional unit, a colour, a string.
_ATOM_WORD = r"-?[a-z_][a-z0-9_-]*"
_ATOM_NUMBER = r"%s(?:%s)?" % (_NUMBER, _UNITS)
_ATOM_COLOUR = r"#[0-9a-f]{3,8}|rgba?\([0-9., ]{1,40}\)"
_ATOM_STRING = r"\"[^\"\\]*\"|'[^'\\]*'"
_LIST_ATOM = "(?:%s)" % "|".join((_ATOM_STRING, _ATOM_COLOUR, _ATOM_NUMBER, _ATOM_WORD))
_LIST = re.compile("%s(?:(?: ?[,/] ?| )%s)*" % (_LIST_ATOM, _LIST_ATOM))
_WORD_ATOM = "(?:%s)" % "|".join((_ATOM_STRING, _ATOM_COLOUR, _NUMBER, _ATOM_WORD))
_WORDS = re.compile("%s(?:(?: ?, ?| )%s)*" % (_WORD_ATOM, _WORD_ATOM))
_DIMENSION = re.compile("(?<![a-z0-9#._-])(%s)(%s)" % (_NUMBER, _UNITS))

_DISPLAY_SHOWN = frozenset(mail_lists.CSS_DISPLAY_SHOWN)
_DISPLAY_NONE = frozenset(mail_lists.CSS_DISPLAY_NONE)
_OVERFLOW = frozenset({"visible", "hidden", "clip", "scroll", "auto"})
_POSITIONS = ("static", "relative")     # fix round 3 (S3): absolute, fixed and sticky are uncertain
_WHITE_SPACE = {"normal": False, "pre-wrap": False, "pre-line": False, "inherit": False, "nowrap": True, "pre": True}
_TEXT_WRAP = {"wrap": False, "nowrap": True}
_FLOATS = ("none", "left", "right")
_DIRECTIONS = ("ltr", "rtl", "inherit")
_TABLE_LAYOUTS = ("auto", "fixed")
_WIDTH_LISTS = frozenset({"flex", "flex-basis"})     # a length in these sets the width of a flex item
_OFFSETS = ("top", "right", "bottom", "left")
_SIZES = ("height", "max-height", "width", "max-width")
_OVERFLOWS = ("overflow", "overflow-x", "overflow-y")
_MARGINS = ("margin-top", "margin-right", "margin-bottom", "margin-left")
_PADDINGS = ("padding-top", "padding-right", "padding-bottom", "padding-left")
_FONT_KEYWORDS = {"xx-small": 9.0, "x-small": 10.0, "small": 13.0, "medium": 16.0, "large": 18.0,
                  "x-large": 24.0, "xx-large": 32.0, "xxx-large": 48.0}
_FONT_SIZE_PROPERTIES = frozenset({"font-size", "mso-ansi-font-size", "mso-bidi-font-size",
                                   "mso-fareast-font-size", "mso-ascii-font-size", "mso-hansi-font-size"})
_TEXT_COLOUR_PROPERTIES = frozenset({"color", "mso-color-alt"})
# <font size="1".."7">
_FONT_ATTRIBUTE_SIZES = (10.0, 13.0, 16.0, 18.0, 24.0, 32.0, 48.0)
_FONT_ATTRIBUTE = re.compile(r"([+-]?)([0-9]+)")
_DIMENSION_ATTRIBUTE = re.compile(r"([0-9]+(?:\.[0-9]+)?)(%?)")
# The size a browser gives the text of these elements when no style sets one, times its parent's.
_TAG_FONT_FACTORS = dict(mail_lists.ELEMENT_FONT_FACTORS)
_READ = frozenset(mail_lists.CSS_PROPERTIES) | frozenset(mail_lists.CSS_RELATED_PROPERTIES)
_SAFE = frozenset(mail_lists.CSS_SAFE_PROPERTIES)
_WORD_ONLY = frozenset(mail_lists.CSS_WORD_ONLY_PROPERTIES)
_FIXED = {name: frozenset(values) for name, values in mail_lists.CSS_FIXED_VALUE_PROPERTIES}
_UNSAFE_WORD = frozenset(mail_lists.CSS_UNSAFE_WORD_PROPERTIES)
_BGCOLOR_ELEMENTS = frozenset({"body", "table", "thead", "tbody", "tfoot", "tr", "td", "th"})
_TEXT_BLOCKS = frozenset(mail_lists.TEXT_BLOCK_ELEMENTS)


def _hex_colour(digits: str) -> Colour:
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return (float(int(digits[0:2], 16)), float(int(digits[2:4], 16)), float(int(digits[4:6], 16)), 1.0)


def css_colour(value: str) -> Any:
    """A colour value of a style: a Colour, the word "inherit", or None when it is not accepted.

    Accepted, and nothing else: `#rgb`, `#rrggbb`, `rgb(n, n, n)` and `rgba(n, n, n, a)` with
    whole numbers up to 255, `transparent`, `inherit`, and a name of the fixed list.
    """
    value = _lower(value.strip(_CSS_SPACE))
    if value == "inherit":
        return "inherit"
    if value == "transparent":
        return _TRANSPARENT
    if value in _NAMED_COLOURS:
        return _hex_colour(_NAMED_COLOURS[value])
    if _HEX_COLOUR.fullmatch(value):
        return _hex_colour(value[1:])
    match = _RGB.fullmatch(value) or _RGBA.fullmatch(value)
    if match is None:
        return None
    parts = [int(part) for part in match.groups()[:3]]
    if max(parts) > 255:
        return None
    alpha = float(match.group(4)) if match.re is _RGBA else 1.0
    return (float(parts[0]), float(parts[1]), float(parts[2]), min(1.0, alpha))


def legacy_colour(value: str) -> Optional[Colour]:
    """A colour attribute (bgcolor, <font color>, <body text>) as a browser reads it.

    The rule of the HTML standard: any text is read as SOME colour, except the empty text
    and the word transparent, which are ignored (None).
    """
    value = value.strip(" \t\n\r\f")
    if not value or _lower(value) == "transparent":
        return None
    lowered = _lower(value)
    if lowered in _NAMED_COLOURS and lowered not in dict(mail_lists.CSS_SYSTEM_COLOURS):
        return _hex_colour(_NAMED_COLOURS[lowered])
    if len(lowered) == 4 and _HEX_COLOUR.fullmatch(lowered):
        return _hex_colour(lowered[1:])
    text = "".join("00" if ord(char) > 0xFFFF else char for char in lowered)[:128]
    if text.startswith("#"):
        text = text[1:]
    text = "".join(char if char in "0123456789abcdef" else "0" for char in text)
    while not text or len(text) % 3:
        text += "0"
    size = len(text) // 3
    parts = [text[0:size], text[size:2 * size], text[2 * size:]]
    if size > 8:
        parts = [part[size - 8:] for part in parts]
        size = 8
    while size > 2 and all(part[0] == "0" for part in parts):
        parts = [part[1:] for part in parts]
        size -= 1
    red, green, blue = (float(int(part[:2], 16)) for part in parts)
    return (red, green, blue, 1.0)


def _length(value: str, margin: bool = False) -> Optional[Length]:
    """A length: ("px", pixels), ("em", font sizes) or ("%", percent); None when it is not one.

    `margin`: the length of a margin or a padding, which may also be in `ex` or `ch`: it is
    then ("x", the number), at most that many ems where it pushes text and no room at all
    for a hanging indent (`_room_px`).
    """
    match = _LENGTH.fullmatch(value)
    if match is None:
        return None
    if match.group(3) is not None:
        return ("px", 0.0)
    number, unit = float(match.group(1)), match.group(2)
    if unit == "%":
        return ("%", number)
    if unit in _MARGIN_ONLY:
        return ("x", number) if margin else None
    if unit in _UNIT_EM:
        return ("em", number * _UNIT_EM[unit])
    return ("px", number * _UNIT_PX[unit])


def _rough_px(length: Length) -> float:
    """A length in pixels at the default font size (a percentage as that many pixels): for the caps."""
    return length[1] * (mail_lists.DEFAULT_FONT_SIZE_PX if length[0] in ("em", "x") else 1.0)


def _font_attribute(value: str) -> Optional[float]:
    match = _FONT_ATTRIBUTE.fullmatch(value.strip(" \t\n\r\f"))
    if match is None:
        return None
    number = int(match.group(2)[:4])
    if match.group(1) == "+":
        number = 3 + number
    elif match.group(1) == "-":
        number = 3 - number
    return _FONT_ATTRIBUTE_SIZES[max(1, min(7, number)) - 1]


def _attribute_size(value: str) -> Optional[Length]:
    match = _DIMENSION_ATTRIBUTE.fullmatch(value.strip(" \t\n\r\f"))
    if match is None:
        return None
    return ("%" if match.group(2) else "px", float(match.group(1)))


# ---- declarations --------------------------------------------------------------------

class Decls:
    """What one list of declarations (a style attribute, or the block of one rule) says.

    `bad`: a declaration in it is not accepted, or it cannot be read at all. `hidden`: one
    hides the text for certain. `clip`: one clips what overflows. `sized` and `tiny`: one
    sets a size, and a size under the hidden threshold. `values`: property -> the distinct
    values it is given, parsed.
    """

    __slots__ = ("bad", "hidden", "clip", "clip_other", "sized", "tiny", "values", "pinned", "painted",
                 "pulled", "word_table")

    def __init__(self, bad: bool = False) -> None:
        self.bad = bad
        self.hidden = False
        self.clip = False
        self.clip_other = False         # it clips by more than `overflow:hidden` (see A CELL THAT CLIPS)
        self.sized = False
        self.tiny = False
        self.pinned = False             # it sets a margin, a padding or a text-indent with `!important`
        self.painted = False            # it sets a background other than none or transparent
        self.pulled = False             # it sets a negative margin (fix round 3, S6)
        self.word_table = False         # ... and that margin is the one of a Word table (WORD_TABLE_MARGIN_PT)
        self.values: Dict[str, List[Any]] = {}

    def add(self, name: str, value: Any) -> None:
        held = self.values.setdefault(name, [])
        if value not in held:
            if len(held) >= mail_lists.STYLE_MAX_VALUES:
                self.bad = True
            else:
                held.append(value)

    def inert(self) -> bool:
        """It changes nothing a reader sees."""
        return not (self.bad or self.hidden or self.clip or self.sized or self.values or self.painted
                    or self.pulled)


_UNREADABLE = Decls(True)
# The properties of a hanging indent (see THE HANGING INDENT OF ONE STYLE ATTRIBUTE in `own_style`).
_HANGING = frozenset({"text-indent", "margin", "padding", "margin-left", "padding-left"})


def _size(length: Optional[Length], out: Decls, name: str = "height") -> bool:
    if length is None or length[1] < 0:
        return False
    if name in ("width", "min-width"):
        out.add("width", length)        # a width of its own (see RIGHT-ANCHORED OVERFLOW)
    if name == "min-width":
        return True                     # it sets the least width: it makes no box small
    out.sized = True
    if name == "width" and length == ("px", 0.0):
        out.add("zero-width", True)     # tiny, except on a <table> (see `own_style`)
    elif length[1] == 0 or (length[0] != "%" and _rough_px(length) < mail_lists.HIDDEN_BOX_BELOW_PX):
        out.tiny = True
    return True


def _sides(value: str, allow_auto: bool) -> Optional[List[Optional[Length]]]:
    """The four sides (top, right, bottom, left) of a margin or padding; None: not accepted.

    A side is a length, or None for `auto`.
    """
    tokens = value.split(" ")
    if not 1 <= len(tokens) <= 4:
        return None
    read: List[Optional[Length]] = []
    for token in tokens:
        if token == "auto" and allow_auto:
            read.append(None)
            continue
        length = _length(token, margin=True)
        if length is None or _rough_px(length) > mail_lists.HIDDEN_OFFSET_BEYOND_PX:
            return None
        read.append(length)
    if len(read) == 1:
        return read * 4
    if len(read) == 2:
        return [read[0], read[1], read[0], read[1]]
    if len(read) == 3:
        return [read[0], read[1], read[2], read[1]]
    return read


def _accept(name: str, value: str, out: Decls) -> bool:
    """Read one declaration into `out`. False: its property or its value is not accepted.

    `name` and `value` are in ASCII lower case, the value with single spaces. Each property
    has its own pattern here; the lists are in `mail_lists`.
    """
    if name in _FONT_SIZE_PROPERTIES:
        if value in _FONT_KEYWORDS:
            out.add("font", ("px", _FONT_KEYWORDS[value]))
        elif value in ("smaller", "larger", "inherit"):
            out.add("font", ("em", {"smaller": 1 / 1.2, "larger": 1.2, "inherit": 1.0}[value]))
        else:
            length = _length(value)
            if length is None or length[1] < 0:
                return False
            out.add("font", ("em", length[1] / 100.0) if length[0] == "%" else length)
        return True
    if name in _TEXT_COLOUR_PROPERTIES or name in ("background-color", "background"):
        if (name == "background" and value == "none") or (name == "background-color" and value == "initial"):
            found: Any = _TRANSPARENT
        elif name == "color" and value == "initial":
            found = _BLACK                  # the text colour of a default page (fix round 3, S10)
        else:
            found = css_colour(value)
        if found is None:
            return False
        if name in _TEXT_COLOUR_PROPERTIES:
            out.add("color", None if found == "inherit" else found)
        else:
            out.add("background", None if found == "inherit" or found[3] == 0 else found)
            out.painted = out.painted or found == "inherit" or found[3] > 0
        return True
    if name == "display":
        if value in _DISPLAY_NONE:
            out.hidden = True
        elif value in _DISPLAY_SHOWN:
            out.add("display", value)
        return value in _DISPLAY_NONE or value in _DISPLAY_SHOWN
    if name == "visibility":
        if value in ("hidden", "collapse"):
            out.hidden = True
        return value in ("visible", "hidden", "collapse")
    if name == "mso-hide":
        if value != "none":
            out.hidden = True
        return True
    if name == "opacity":
        match = _NUMBER_OR_PERCENT.fullmatch(value)
        if match is None:
            return False
        out.add("opacity", max(0.0, min(1.0, float(match.group(1)) / (100.0 if match.group(2) else 1.0))))
        return True
    if name in _OVERFLOWS:
        tokens = value.split(" ")
        if len(tokens) > (2 if name == "overflow" else 1) or any(token not in _OVERFLOW for token in tokens):
            return False
        if any(token != "visible" for token in tokens):
            out.clip = True
            if name != "overflow" or value != "hidden":
                out.clip_other = True
        return True
    if name in _SIZES or name == "min-width":
        if value in ("none" if name.startswith("max-") else "auto", "inherit"):
            return True
        return _size(_length(value), out, name)
    if name == "position":
        # fix round 3 (S3): only `static`, and `relative` with no offset (see `own_style`)
        if value not in _POSITIONS:
            return False
        out.add("position", value)
        return True
    if name in _OFFSETS or name == "text-indent":
        if value == "auto" and name != "text-indent":
            return True
        length = _length(value)
        if length is None:
            return False
        out.add(name, length)
        return True
    if name == "z-index":
        return value == "auto" or _INTEGER.fullmatch(value) is not None
    if name == "margin" or name in _MARGINS or name == "padding" or name in _PADDINGS:
        margin = name.startswith("margin")
        sides = _sides(value, margin)
        if sides is None or (name not in ("margin", "padding") and " " in value):
            return False
        names = _MARGINS if margin else _PADDINGS
        for side, length in zip(names, sides):
            if name not in ("margin", "padding") and side != name:
                continue
            if length is None:
                length = ("px", 0.0)
            if not margin and length[1] < 0:
                return False
            if margin and length[1] < 0:
                # fix round 3 (S6): a negative margin is uncertain, but for the one of a Word table
                out.pulled = True
                if (name == "margin-left" and value.endswith("pt") and length[0] == "px"
                        and -length[1] <= mail_lists.WORD_TABLE_MARGIN_PT * _UNIT_PX["pt"] + 1e-9):
                    out.word_table = True
            if margin or side == "padding-left":
                out.add(side, length)
        return True
    if name == "padding-inline-start":
        length = _length(value)
        if length is None or length[0] == "%" or length[1] < 0 or _rough_px(length) > mail_lists.HIDDEN_OFFSET_BEYOND_PX:
            return False
        out.add("push", length)         # it pushes the text, and it is never room for an indent
        return True
    if name in ("letter-spacing", "word-spacing"):
        if value == "normal":
            return True
        length = _length(value)
        if length is None or length[0] == "%":
            return False
        if length[1] < 0:
            out.add("spacing", length)
        elif length[1] > 0:
            out.add("spread", length)
        return True
    if name == "float":
        if value == "right":
            out.add("float-right", True)
        return value in _FLOATS
    if name == "direction":
        if value == "rtl":
            out.add("rtl", True)
        return value in _DIRECTIONS
    if name in ("white-space", "text-wrap"):
        kinds = _WHITE_SPACE if name == "white-space" else _TEXT_WRAP
        if kinds.get(value):
            out.add("nowrap", True)
        return value in kinds
    if name == "table-layout":
        if value == "fixed":
            out.add("fixed-layout", True)
        return value in _TABLE_LAYOUTS
    if name == "line-height":
        if value == "normal":
            return True
        if re.fullmatch(_NUMBER, value):
            return 0 <= float(value) <= mail_lists.LINE_HEIGHT_MAX_FACTOR
        length = _length(value)
        return (length is not None and length[1] >= 0
                and _rough_px(length) <= (mail_lists.LINE_HEIGHT_MAX_FACTOR * 100 if length[0] == "%"
                                          else mail_lists.LINE_HEIGHT_MAX_PX))
    if name == "mso-text-raise":
        length = _length(value)
        if (length is None or length[0] != "px"
                or abs(_rough_px(length)) > mail_lists.WORD_TEXT_RAISE_MAX_PX):
            return False
        out.add("raise", length)
        return True
    if name in _FIXED:
        return value in _FIXED[name]
    if name in _WORD_ONLY:
        return _WORDS.fullmatch(value) is not None
    if name in _SAFE:
        dimensions = _DIMENSION.findall(value)
        if name in _WIDTH_LISTS:
            for number, unit in dimensions:
                out.add("width", ("%", float(number)) if unit == "%" else (
                    "em", float(number)) if unit in _UNIT_EM else ("px", float(number) * _UNIT_PX[unit]))
        return (_LIST.fullmatch(value) is not None
                and all(abs(float(number)) * (mail_lists.DEFAULT_FONT_SIZE_PX if unit in _UNIT_EM
                                              else _UNIT_PX.get(unit, 1.0)) <= mail_lists.STYLE_MAX_LENGTH_PX
                        for number, unit in dimensions))
    if (name.startswith(mail_lists.CSS_SAFE_PREFIX) and name not in _UNSAFE_WORD) or name.startswith(
            mail_lists.CSS_CUSTOM_PROPERTY_PREFIX):
        return _LIST.fullmatch(value) is not None
    return False


def _token_text(tokens: Sequence[CssToken]) -> str:
    return "".join(value for _kind, value in tokens).strip(" ")


def _read_declarations(tokens: Sequence[CssToken]) -> Decls:
    """The declarations among `tokens` (the tokens of a style attribute, or between the braces of a rule)."""
    out = Decls()
    pieces: List[List[CssToken]] = [[]]
    depth = 0
    for token in tokens:
        kind = token[0]
        if kind in "{}[]<>eu":
            return _UNREADABLE          # none of these stands in an accepted declaration list
        if kind == "(":
            depth += 1
        elif kind == ")":
            depth -= 1
            if depth < 0:
                return _UNREADABLE
        if kind == ";":
            if depth:
                return _UNREADABLE
            pieces.append([])
        else:
            pieces[-1].append(token)
    if depth:
        return _UNREADABLE
    for piece in pieces:
        while piece and piece[0][0] == " ":
            piece = piece[1:]
        while piece and piece[-1][0] == " ":
            piece = piece[:-1]
        if not piece:
            continue
        colon = 2 if len(piece) > 2 and piece[1][0] == " " else 1
        name = _lower(piece[0][1])
        if (piece[0][0] != "w" or len(piece) <= colon or piece[colon][0] != ":"
                or _PROPERTY_NAME.fullmatch(name) is None):
            out.bad = True              # no declaration: a browser would recover here, this reader does not
            continue
        value = piece[colon + 1:]
        if len(value) >= 2 and value[-1][0] == "w" and _lower(value[-1][1]) == "important":
            mark = value[:-1]
            while mark and mark[-1][0] == " ":
                mark = mark[:-1]
            if mark and mark[-1][0] == "!":
                value = mark[:-1]       # `!important` changes nothing here: no declaration beats another
                if name in _HANGING:
                    out.pinned = True   # (but it takes the hanging indent of a style attribute out of the exception)
        if any(kind in "!:" for kind, _text in value):
            out.bad = True
            continue
        if any(kind == "n" for kind, _text in value):
            if name != "font-family":
                out.bad = True          # a word outside ASCII is a family name, or nothing of this language
                continue
            value = [("w", "x") if kind == "n" else (kind, text) for kind, text in value]
        text = _lower(_token_text(value))
        text = re.sub(r"\( ", "(", re.sub(r" \)", ")", text))
        if not text or not _accept(name, text, out):
            out.bad = True
    return out


_PANOSE = re.compile(r"[0-9]{1,3}(?: [0-9]{1,3}){0,15}")
_FONT_FACE_VALUES = {"font-style": re.compile(r"normal|italic|oblique"),
                     "font-weight": re.compile(r"normal|bold|[1-9]00"), "panose-1": _PANOSE}


def _font_face(tokens: Sequence[CssToken]) -> bool:
    """Whether the block of an `@font-face` is of the language (fix round 3, S2).

    Every descriptor is one of `mail_lists.CSS_FONT_FACE_DESCRIPTORS` or a Word property
    (`mso-*`), each with the value form Outlook writes: a family name (words, strings, a word
    outside ASCII, a string with an escape: Word writes `"\\@Name"` for a vertical face); for
    the rest one of the patterns above, or a plain list. A face with a `src`, a `size-adjust`,
    an `*-override` or a `unicode-range` may draw the glyphs of the family it names small or
    blank: anything but these makes the block UNREADABLE.
    """
    pieces: List[List[CssToken]] = [[]]
    for token in tokens:
        if token[0] in "{}[]()<>u!":
            return False
        if token[0] == ";":
            pieces.append([])
        else:
            pieces[-1].append(token)
    for piece in pieces:
        while piece and piece[0][0] == " ":
            piece = piece[1:]
        while piece and piece[-1][0] == " ":
            piece = piece[:-1]
        if not piece:
            continue
        colon = next((number for number, token in enumerate(piece) if token[0] == ":"), -1)
        if colon < 1 or piece[0][0] != "w" or any(token[0] == ":" for token in piece[colon + 1:]):
            return False
        name = _lower(piece[0][1])
        if any(token[0] != " " for token in piece[1:colon]):
            return False
        value = piece[colon + 1:]
        while value and value[0][0] == " ":
            value = value[1:]
        if not value:
            return False
        if name == "font-family":
            for kind, text in value:
                if kind == "e" and not text.startswith(("'", '"')):
                    return False        # an escape is accepted in a quoted family name only
                if kind not in " wsne,":
                    return False
            continue
        if any(kind in "ne" for kind, _text in value):
            return False
        text = _lower(_token_text(value))
        if name in _FONT_FACE_VALUES:
            if _FONT_FACE_VALUES[name].fullmatch(text) is None:
                return False
        elif not (name.startswith(mail_lists.CSS_SAFE_PREFIX) and _LIST.fullmatch(text) is not None):
            return False
    return True


_STYLE_CACHE: Dict[str, Decls] = {}


def read_style(style: str) -> Decls:
    """What a style attribute says. One that cannot be read, or is over the bound, is `bad`."""
    found = _STYLE_CACHE.get(style)
    if found is None:
        if len(style) > mail_lists.STYLE_MAX_ATTRIBUTE_CHARS:
            found = _UNREADABLE
        else:
            tokens = css_tokens(style)
            found = _UNREADABLE if tokens is None else _read_declarations(tokens)
        if len(_STYLE_CACHE) > 4_000:
            _STYLE_CACHE.clear()
        _STYLE_CACHE[style] = found
    return found


# ---- one element ---------------------------------------------------------------------

class Own(NamedTuple):
    """What the attributes of ONE element, and the rules that could match it, say.

    Nothing here depends on the element's parent: what adds up along the ancestors (font
    size, opacity, offsets) is worked out where the element is opened (`_Element.inherit`).
    """
    state: str                      # VISIBLE, HIDDEN or UNCERTAIN
    fonts: Tuple[Length, ...]       # the sizes it may get: ("px", n), or ("em", n) times its parent's
    font_inherit: bool              # ... or its parent's size
    # (colour, background) the element may get together. None stands for "the parent's".
    combos: Tuple[Tuple[Optional[Colour], Optional[Colour]], ...]
    background_unknown: bool        # it may put an image behind its text
    background_known: bool          # it sets an opaque colour behind its text for certain
    opacity: float                  # the lowest opacity it may get
    moves: Tuple[Tuple[str, Tuple[Length, ...]], ...]   # the lengths that may move its text, by property
    room: Tuple[str, ...]           # which of margin-left, padding-left and text-indent it sets for certain
    shaped: bool                    # a `display` value or a position out of the flow may apply to it
    sets_text_style: bool           # it sets a colour, a size or a background
    # fix round 3: what decides right-anchored overflow (S5), a painted box (S8, S9) and a cell that clips (S10)
    painted: bool = False           # a background other than none or transparent may be behind its text
    rtl: bool = False               # its text may run right to left (dir rtl or auto, direction: rtl)
    right: bool = False             # it is anchored on the right (float: right; align="right" on a listed element)
    nowrap: bool = False            # its text does not wrap (white-space, text-wrap, nowrap, <nobr>, <pre>)
    widths: Tuple[Length, ...] = ()     # the widths of its own it may get (width, min-width, a width attribute)
    cell_clip: bool = False         # a cell that clips by `overflow:hidden` alone and sets no size
    pushes: Tuple[Length, ...] = ()     # what may push its text right: positive margin-left, paddings, indent
    spread: float = 0.0             # the widest positive letter or word spacing it may get, in px at 16px
    fixed_layout: bool = False      # a table laid out `fixed`
    pulls: bool = False             # a negative margin other than a Word table's: it pulls what FOLLOWS it too


_NO_COMBOS: Tuple[Tuple[Optional[Colour], Optional[Colour]], ...] = ((None, None),)
_PLAIN_OWN = Own(VISIBLE, (), True, _NO_COMBOS, False, False, 1.0, (), (), False, False)
_MOVING = _OFFSETS + _MARGINS + ("padding-left", "text-indent", "spacing")
# the keys of `Decls.values` that are flags or lists of their own, not lengths that move text
_FLAG_KEYS = frozenset({"rtl", "float-right", "nowrap", "width", "zero-width", "push", "spread", "fixed-layout",
                        "raise"})


def own_style(tag: str, attrs: Dict[str, str], rules: Sequence[Tuple[Any, bool]] = (),
              link_colours: Sequence[Colour] = (), budget: Any = mail_reuse.NO_BUDGET) -> Own:
    """What the attributes of one element, and the rules that could match it, say about its text.

    `rules` are (rule, it matches for certain) pairs of the style blocks. The element is
    judged over the WORST of all of them and of its style attribute: no source rescues it
    from another.
    """
    hidden = "hidden" in attrs
    uncertain = False
    # (declarations, they apply for certain); the style attribute first
    sources: List[Tuple[Decls, bool]] = []
    style = attrs.get("style", "")
    inline = read_style(style) if style.strip(_CSS_SPACE) else None
    if inline is not None:
        sources.append((inline, True))
    seen = set()
    for rule, certain in rules:
        if id(rule.declarations) not in seen:
            seen.add(id(rule.declarations))
            sources.append((rule.declarations, certain))
    if len(sources) > mail_lists.STYLE_MAX_SOURCES:
        uncertain = True
        sources = sources[:mail_lists.STYLE_MAX_SOURCES]

    def given(name: str) -> bool:
        """The style attribute sets `name`: what an attribute or the browser gives no longer counts."""
        return inline is not None and name in inline.values

    # ---- what the attributes themselves, and the browser, give ---------------------------
    fonts: List[Length] = []
    font_sure = False
    colours: List[Tuple[Optional[Colour], int]] = []        # (value, the number of its source; -1: an attribute)
    backgrounds: List[Tuple[Optional[Colour], int]] = []
    colour_sure = background_sure = False
    image = False
    if not given("font"):
        size = _font_attribute(attrs["size"]) if tag == "font" and attrs.get("size") else None
        if size is not None:
            fonts.append(("px", size))
            font_sure = True
        elif tag in _TAG_FONT_FACTORS:
            fonts.append(("em", _TAG_FONT_FACTORS[tag]))
            font_sure = True
    if not given("color"):
        found: List[Optional[Colour]] = []
        if tag == "font" and attrs.get("color"):
            found.append(legacy_colour(attrs["color"]))
        if tag == "body" and attrs.get("text"):
            found.append(legacy_colour(attrs["text"]))
        if tag == "a" and "href" in attrs:
            found.extend(link_colours or (tuple(float(part) for part in mail_lists.LINK_DEFAULT_COLOUR) + (1.0,),))
        for colour in found:
            if colour is not None:
                colours.append((colour, -1))
                colour_sure = True
    if tag in _BGCOLOR_ELEMENTS:
        if attrs.get("bgcolor") and not given("background"):
            colour = legacy_colour(attrs["bgcolor"])
            if colour is not None:
                backgrounds.append((colour, -1))
                background_sure = True
        if attrs.get("background"):
            image = True

    # ---- every source -----------------------------------------------------------------
    clip = sized = tiny = False
    opacity = 1.0
    positions = set()
    moves: Dict[str, List[Length]] = {}
    room = set()
    shaped = False
    widths: List[Length] = []
    for name in ("height", "width"):
        if attrs.get(name) and tag != "img":
            length = _attribute_size(attrs[name])
            if length is not None:
                sized = True
                tiny = tiny or length[1] == 0 or (length[0] == "px" and length[1] < mail_lists.HIDDEN_BOX_BELOW_PX)
                if name == "width":
                    widths.append(length)
    # fix round 3: what the attributes say of direction, anchoring, wrapping and painting
    rtl = _lower(attrs.get("dir", "")).strip(" \t\n\r\f") in ("rtl", "auto")
    right = (tag in mail_lists.RIGHT_ALIGNED_ELEMENTS
             and _lower(attrs.get("align", "")).strip(" \t\n\r\f") == "right")
    nowrap = "nowrap" in attrs
    painted = any(attrs.get(name, "").strip(" \t\n\r\f") for name in ("bgcolor", "background"))
    painted = painted or any(declarations.painted for declarations, _sure in sources)
    # THE HANGING INDENT OF ONE STYLE ATTRIBUTE (the one exception to "no source rescues
    # another", decided by the lead in fix round 2: a list a person types in Outlook). When
    # the style attribute itself carries a negative text-indent AND a left margin or padding
    # at least as wide, in lengths of one kind, and no rule that could match sets a margin,
    # a padding or a text-indent with `!important`, then what the rules say of those three
    # properties is left out: Word's `p.MsoNormal{margin:0cm}` does not undo the pair.
    # Fix round 3 (S9, Codex 1): only for an element that sets no background, by an attribute,
    # its style or any rule that could match. The indent puts the first words outside the
    # element's own box, onto what stands behind it, so a background of its own is no backdrop
    # of those words; with none, its text is judged against the backdrop it stands on.
    paired = False
    if (inline is not None and not inline.bad and not painted
            and not any(declarations.pinned for declarations, _sure in sources[1:])):
        indents = inline.values.get("text-indent", [])
        rooms = [inline.values[name] for name in ("margin-left", "padding-left") if name in inline.values]
        kinds = {length[0] for group in [indents] + rooms for length in group}
        if indents and rooms and len(kinds) == 1 and "%" not in kinds and min(length[1] for length in indents) < 0:
            paired = sum(max(0.0, min(length[1] for length in group)) for group in rooms) + 1e-6 >= -min(
                length[1] for length in indents)
    clip_other = fixed_layout = zero_width = pulls = False
    pushes: List[Length] = []
    spread = 0.0
    for number, (declarations, certain) in enumerate(sources):
        budget.check()
        hidden = hidden or declarations.hidden
        uncertain = uncertain or declarations.bad
        clip = clip or declarations.clip
        clip_other = clip_other or declarations.clip_other
        sized = sized or declarations.sized
        tiny = tiny or declarations.tiny
        if declarations.pulled and not (declarations.word_table and tag == "table" and declarations is inline):
            uncertain = pulls = True    # fix round 3 (S6): a negative margin, but the one of a Word table
        for name, values in declarations.values.items():
            if name in _FLAG_KEYS:
                if name == "rtl":
                    rtl = True
                elif name == "float-right":
                    right = True
                elif name == "nowrap":
                    nowrap = True
                elif name == "width":
                    widths.extend(values)
                elif name == "zero-width":
                    zero_width = True
                elif name == "push":
                    pushes.extend(values)
                elif name == "spread":
                    spread = max([spread] + [_rough_px(length) for length in values])
                else:
                    fixed_layout = True
                continue
            if name == "font":
                fonts.extend(values)
                font_sure = font_sure or certain
            elif name == "color":
                colours.extend((value, number) for value in values)
                colour_sure = colour_sure or certain
            elif name == "background":
                backgrounds.extend((value, number) for value in values)
                background_sure = background_sure or certain
            elif name == "opacity":
                opacity = min([opacity] + values)
            elif name == "position":
                positions.update(values)
            elif name == "display":
                shaped = True
            elif paired and declarations is not inline and name in ("text-indent", "margin-left", "padding-left"):
                continue
            else:
                moves.setdefault(name, []).extend(values)
                if certain and name in ("margin-left", "padding-left", "text-indent"):
                    room.add(name)
    # what may push the text right, for a cell that clips (A CELL THAT CLIPS)
    pushes.extend(length for name in ("margin-left", "padding-left", "text-indent")
                  for length in moves.get(name, ()) if length[1] > 0)
    if "padding-left" not in room:
        moves.pop("padding-left", None)     # room that may not be there is no room
    if not positions - {"static"}:
        for name in _OFFSETS:
            moves.pop(name, None)           # an offset moves nothing that is not positioned
    else:
        # fix round 3 (S3): `relative` moves its text by its offsets. The one form accepted is
        # Word's raised or lowered text, in one style attribute: `top` the opposite of
        # `mso-text-raise`, in absolute units, at most WORD_TEXT_RAISE_MAX_PX, and no other offset.
        offsets = [(name, length) for name in _OFFSETS for length in moves.get(name, ()) if length[1] != 0]
        raised = (inline is not None and len(offsets) == 1 and offsets[0][0] == "top"
                  and offsets[0][1] in inline.values.get("top", ()) and len(inline.values.get("top", ())) == 1
                  and offsets[0][1][0] == "px" and abs(offsets[0][1][1]) <= mail_lists.WORD_TEXT_RAISE_MAX_PX
                  and inline.values.get("raise") == [("px", -offsets[0][1][1])])
        if offsets and not raised:
            uncertain = True
    for name, lengths in moves.items():
        for kind, amount in lengths:
            # a percentage has no pixel value here: one that pulls text back, or pushes it far, is in doubt
            if kind == "%" and name != "padding-left" and (
                    amount < 0 or amount > mail_lists.UNCERTAIN_OFFSET_BEYOND_PERCENT):
                uncertain = True
    if zero_width and tag != "table":
        tiny = True                         # a width of 0 is no width, except on a table (S10: content width)
    # fix round 3 (S10): `overflow:hidden` alone on a cell that sets no size of its own is
    # accepted; what is in such a cell is judged where it stands (`_Element.inherit`)
    cell_clip = clip and not clip_other and not sized and not tiny and tag in _CELLS
    if cell_clip:
        clip = False
    if clip and tiny:
        hidden = True
    elif clip or tiny:
        # A box that clips may show none of its text (its size comes from elsewhere: a
        # line height, a table, a flex container), and so may a box of no size.
        uncertain = True

    # ---- colours and backgrounds: the pairs that can occur together -----------------------
    distinct_colours = list(dict.fromkeys(value for value, _source in colours))
    distinct_backgrounds = list(dict.fromkeys(value for value, _source in backgrounds))
    combos: Dict[Tuple[Optional[Colour], Optional[Colour]], None] = {}
    if len(distinct_colours) > mail_lists.STYLE_MAX_VALUES or len(distinct_backgrounds) > mail_lists.STYLE_MAX_VALUES:
        uncertain = True
    else:
        for colour in distinct_colours:
            for background in distinct_backgrounds:
                combos[(colour, background)] = None
        with_background = {source for _value, source in backgrounds}
        with_colour = {source for _value, source in colours}
        if not background_sure:
            for colour, source in colours:
                if source not in with_background:
                    combos[(colour, None)] = None
        if not colour_sure:
            for background, source in backgrounds:
                if source not in with_colour:
                    combos[(None, background)] = None
        if not colour_sure and not background_sure:
            combos[(None, None)] = None
    known = (background_sure and not image and bool(distinct_backgrounds)
             and all(value is not None and value[3] >= 1 for value in distinct_backgrounds))
    state = HIDDEN if hidden else (UNCERTAIN if uncertain else VISIBLE)
    return Own(state, tuple(dict.fromkeys(fonts)), not font_sure, tuple(combos) or _NO_COMBOS, image, known,
               opacity, tuple((name, tuple(dict.fromkeys(moves[name]))) for name in _MOVING if moves.get(name)),
               tuple(sorted(room)), shaped, bool(colours or fonts or backgrounds or image),
               painted or image, rtl, right, nowrap, tuple(dict.fromkeys(widths)), cell_clip,
               tuple(dict.fromkeys(pushes)), spread, fixed_layout, pulls)


def _px(length: Length, font_px: float) -> float:
    """A length in pixels where it moves text: an `ex` or a `ch` ("x") as a whole em, the most it may be."""
    return length[1] * font_px if length[0] in ("em", "x") else (0.0 if length[0] == "%" else length[1])


def _room_px(length: Length, font_px: float) -> float:
    """A length in pixels as room for a hanging indent: an `ex` or a `ch` ("x") gives none (fix round 3, S4)."""
    return 0.0 if length[0] == "x" else _px(length, font_px)


def moved(own: Own, font_lo: float, font_hi: float) -> Tuple[float, float, float, str]:
    """(pixels to the left, pixels up, pixels away, state) the element's own style may move its text.

    The worst of the values each property may get is taken. `state` is what its letter
    spacing says: text drawn on top of itself is hidden. A text-indent counts here only
    when it is far; the hanging indent is judged where the element stands (`_Element.inherit`).
    """
    values = dict(own.moves)

    def low(name: str) -> float:
        return min([_px(length, font_hi) for length in values.get(name, ())] + [0.0])

    def high(name: str) -> float:
        return max([_px(length, font_hi) for length in values.get(name, ())] + [0.0])

    left = -low("left") + high("right")      # (a negative left margin is taken from the room: `_Element.inherit`)
    up = -low("margin-top") - low("margin-bottom") - low("top") + high("bottom")
    away = high("left") + high("top") - low("right") - low("bottom")
    state = VISIBLE
    if low("text-indent") < -mail_lists.HIDDEN_OFFSET_BEYOND_PX:
        left += -low("text-indent")
    away += max(0.0, high("text-indent") - mail_lists.HIDDEN_OFFSET_BEYOND_PX)
    for length in values.get("spacing", ()):
        amount = _px(length, font_lo)
        if amount <= mail_lists.HIDDEN_LETTER_SPACING_BELOW_EM * font_lo:
            return left, up, away, HIDDEN
        if (amount < mail_lists.UNCERTAIN_LETTER_SPACING_BELOW_PX
                or amount < mail_lists.UNCERTAIN_LETTER_SPACING_BELOW_EM * font_lo):
            state = UNCERTAIN
    return left, up, away, state


def _channel(value: float) -> float:
    value /= 255.0
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(colour: Sequence[float]) -> float:
    return 0.2126 * _channel(colour[0]) + 0.7152 * _channel(colour[1]) + 0.0722 * _channel(colour[2])


def contrast(first: Sequence[float], second: Sequence[float]) -> float:
    """The contrast ratio of two opaque colours, from 1 (the same) to 21."""
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _over(colour: Colour, backdrop: Sequence[float]) -> Tuple[float, float, float]:
    """`colour` painted over an opaque `backdrop`."""
    alpha = colour[3]
    return (colour[0] * alpha + backdrop[0] * (1 - alpha), colour[1] * alpha + backdrop[1] * (1 - alpha),
            colour[2] * alpha + backdrop[2] * (1 - alpha))


# --------------------------------------------------------------------------------------
# Style blocks
# --------------------------------------------------------------------------------------
#
# A block is READABLE only if every construct in it is of this language:
#
#   rule          selectors `{` declarations `}`. The declarations are read as those of a
#                 style attribute; a rule nested in a rule is not of the language.
#   selector      a comma list of compound selectors joined by white space (descendant) or
#                 `>` (child). A compound selector is a tag name or `*`, then any of
#                 `.class`, `#id`, `[attribute]` and a pseudo-class or pseudo-element with
#                 no brackets. Only the LAST compound selector is compared with an element,
#                 so a rule applies to at least the elements a browser applies it to. A
#                 selector of any other form applies its rule to EVERY element.
#   @media        with a block of rules (and of @media, two deep at most).
#   passed over   `@font-face`, `@page` and Word's `@list`, each with a block that holds no
#                 brace: they hold no rule for an element.
#   comment marks `<!--` as the first thing of a block and `-->` as the last (Word writes
#                 both); anywhere else they are not of the language.
#
# Anything else (another at-rule, `@import` and `@namespace` among them; a stray token; a
# block or a rule that is never closed; more rules or a longer block than the bounds) makes
# the block UNREADABLE, and then nothing of the part is shown.

class Rule(NamedTuple):
    """One selector of one rule of a style block, as far as its LAST compound selector goes."""
    declarations: Decls
    tag: str                        # lower case; "" for any element
    classes: Tuple[str, ...]        # lower case
    ident: str                      # lower case; "" for none
    attributes: Tuple[str, ...]     # attribute names that must be present, lower case
    exact_classes: Tuple[str, ...]  # as written
    exact_ident: str
    certain: bool                   # it applies for certain to an element it matches exactly


_IDENT = r"-?[_a-zA-Z][_a-zA-Z0-9-]*"
_COMPOUND = re.compile(r"(\*|[a-zA-Z][a-zA-Z0-9-]*)?((?:\.%s|#%s|\[ ?%s ?\]|::?%s)*)" % ((_IDENT,) * 4))
_COMPOUND_PART = re.compile(r"\.(%s)|#(%s)|\[ ?(%s) ?\]|(::?)(%s)" % ((_IDENT,) * 4))
_COMBINATOR = re.compile(r" ?> ?| ")
_AT_RULE = re.compile(r"@[a-zA-Z-]+")
_TEXT_PSEUDO_ELEMENTS = frozenset({"first-line", "first-letter"})
_OTHER_PSEUDO_ELEMENTS = frozenset(mail_lists.CSS_OTHER_PSEUDO_ELEMENTS)
_PLAIN_PSEUDO_CLASSES = frozenset(mail_lists.CSS_PLAIN_PSEUDO_CLASSES)


def read_selector(selector: str, declarations: Decls) -> Tuple[Optional[Rule], bool]:
    """(the Rule of one selector, whether the selector is of a form every browser applies).

    The Rule is None for a selector that says nothing about the text of an element (it
    styles generated content, a selection and the like). A selector this cannot read gives
    a Rule for every element.
    """
    everything = Rule(declarations, "", (), "", (), (), "", False)
    compounds = _COMBINATOR.split(selector.strip(" "))
    if any(not compound or _COMPOUND.fullmatch(compound) is None for compound in compounds):
        return everything, False
    plain = True                    # every browser reads the selector as this reader does
    ignored = False
    for compound in compounds:
        for part in _COMPOUND_PART.finditer(compound):
            if part.group(5) is None:
                continue
            name = part.group(5).lower()
            last = compound is compounds[-1] and part.end() == len(compound)
            if name in _OTHER_PSEUDO_ELEMENTS and last:
                ignored = True
            elif name in _TEXT_PSEUDO_ELEMENTS and last:
                plain = False
            elif part.group(4) == ":" and name not in _OTHER_PSEUDO_ELEMENTS and name not in _TEXT_PSEUDO_ELEMENTS:
                plain = plain and name in _PLAIN_PSEUDO_CLASSES
            else:
                return everything, False
    if ignored:
        return None, False
    match = _COMPOUND.fullmatch(compounds[-1])
    tag = "" if match.group(1) in (None, "*") else match.group(1).lower()
    classes: List[str] = []
    ident = ""
    attributes: List[str] = []
    simple = len(compounds) == 1
    for part in _COMPOUND_PART.finditer(compounds[-1]):
        if part.group(1) is not None:
            classes.append(part.group(1))
        elif part.group(2) is not None:
            if ident and ident != part.group(2):
                return everything, False
            ident = part.group(2)
        elif part.group(3) is not None:
            attributes.append(part.group(3).lower())
            simple = False
        else:
            simple = False
    return Rule(declarations, tag, tuple(name.lower() for name in classes), ident.lower(), tuple(attributes),
                tuple(classes), ident, simple), plain


class Sheet:
    """The rules of the style blocks of one HTML part that may change what a reader sees."""

    def __init__(self) -> None:
        self.rules = 0                  # rules that may change what a reader sees
        self.selectors = 0              # every selector read, against the bound
        self.unreadable = False         # a block is not of the language: nothing of the part is shown
        self.external = False           # a style sheet outside the style blocks is named
        self._by_class: Dict[str, List[Rule]] = {}
        self._by_ident: Dict[str, List[Rule]] = {}
        self._by_tag: Dict[str, List[Rule]] = {}
        self._any: List[Rule] = []

    def add(self, rule: Rule) -> None:
        self.rules += 1
        if rule.classes:
            self._by_class.setdefault(rule.classes[0], []).append(rule)
        elif rule.ident:
            self._by_ident.setdefault(rule.ident, []).append(rule)
        elif rule.tag:
            self._by_tag.setdefault(rule.tag, []).append(rule)
        else:
            self._any.append(rule)

    def match(self, tag: str, attrs: Dict[str, str]) -> Tuple[Tuple[Rule, bool], ...]:
        """(rule, it applies for certain) for every rule whose last compound could match the element.

        Class and id values are those of the decoded attribute, split on ASCII white space
        only, and compared without regard to ASCII case (a page in quirks mode does so).
        """
        if not self.rules:
            return ()
        written = [name for name in re.split("[ \t\n\r\f]+", attrs.get("class", "")) if name]
        classes = {_lower(name) for name in written}
        ident = attrs.get("id", "")
        found: List[Rule] = list(self._any) + self._by_tag.get(tag, [])
        for name in classes:
            found.extend(self._by_class.get(name, ()))
        if ident:
            found.extend(self._by_ident.get(_lower(ident), ()))
        out = []
        for rule in found:
            if rule.tag and rule.tag != tag:
                continue
            if rule.ident and rule.ident != _lower(ident):
                continue
            if any(name not in classes for name in rule.classes):
                continue
            if any(name not in attrs for name in rule.attributes):
                continue
            certain = (rule.certain and all(name in written for name in rule.exact_classes)
                       and (not rule.exact_ident or rule.exact_ident == ident))
            out.append((rule, certain))
        return tuple(out)


def _block_close(tokens: Sequence[CssToken], index: int, end: int, nested: bool) -> int:
    """The offset of the `}` that closes the block opened just before `index`; -1: not of the language.

    `nested`: the block may hold blocks of its own (a group of rules).
    """
    depth = 0
    brackets = 0
    while index < end:
        kind = tokens[index][0]
        if kind in "([":
            brackets += 1
        elif kind in ")]":
            brackets -= 1
            if brackets < 0:
                return -1
        elif kind == "{":
            if brackets or not nested:
                return -1
            depth += 1
        elif kind == "}":
            if brackets:
                return -1
            if depth == 0:
                return index
            depth -= 1
        elif kind in "<>":
            return -1
        index += 1
    return -1


def _read_rules(tokens: Sequence[CssToken], index: int, end: int, sheet: Sheet, depth: int, budget: Any) -> bool:
    """Add the rules among tokens[index:end] to `sheet`. False: something there is not of the language."""
    while index < end:
        budget.check()
        kind, value = tokens[index]
        if kind == " ":
            index += 1
            continue
        # the prelude: up to the first `{`
        brace = index
        brackets = 0
        while brace < end and tokens[brace][0] != "{":
            at = tokens[brace][0]
            if at in "([":
                brackets += 1
            elif at in ")]":
                brackets -= 1
            if brackets < 0 or at in "};<>":
                return False
            brace += 1
        if brace >= end or brackets:
            return False
        prelude = tokens[index:brace]
        name = _lower(value[1:]) if kind == "w" and value.startswith("@") else ""
        if kind == "w" and value.startswith("@"):
            if _AT_RULE.fullmatch(value) is None:
                return False
            if name in mail_lists.CSS_GROUP_AT_RULES:
                close = _block_close(tokens, brace + 1, end, True)
                if (close < 0 or depth >= mail_lists.STYLE_MAX_NESTING or any(at in "en" for at, _text in prelude)
                        or not _read_rules(tokens, brace + 1, close, sheet, depth + 1, budget)):
                    return False
            elif name in mail_lists.CSS_PASSED_AT_RULES:
                close = _block_close(tokens, brace + 1, end, False)
                if close < 0 or any(at == "n" for at, _text in tokens[index:close]):
                    return False
            elif name == mail_lists.CSS_FONT_FACE_AT_RULE:
                close = _block_close(tokens, brace + 1, end, False)
                if close < 0 or len(prelude) > 2 or not _font_face(tokens[brace + 1:close]):
                    return False
            else:
                return False            # any other at-rule: not of the language
            index = close + 1
            continue
        close = _block_close(tokens, brace + 1, end, False)
        if close < 0 or any(at in "eun" for at, _text in prelude) or any(
                at == "e" for at, _text in tokens[brace + 1:close]):
            return False
        declarations = _read_declarations(tokens[brace + 1:close])
        index = close + 1
        selectors: List[List[CssToken]] = [[]]
        brackets = 0
        for token in prelude:
            brackets += (token[0] in "([") - (token[0] in ")]")
            if token[0] == "," and not brackets:
                selectors.append([])
            else:
                selectors[-1].append(token)
        read = [read_selector(_token_text(selector), declarations) for selector in selectors]
        plain = all(is_plain for _rule, is_plain in read) and depth == 0
        sheet.selectors += len(read)
        if sheet.selectors > mail_lists.STYLE_MAX_RULES:
            return False
        for rule, _is_plain in read:
            if rule is None or declarations.inert():
                continue
            sheet.add(rule._replace(certain=rule.certain and plain))
    return True


def read_style_block(text: str, sheet: Sheet, budget: Any = mail_reuse.NO_BUDGET) -> None:
    """Add the rules of one style block to `sheet`, or set `sheet.unreadable`."""
    tokens = None if len(text) > mail_lists.STYLE_MAX_BLOCK_CHARS else css_tokens(text)
    if tokens is None:
        sheet.unreadable = True
        return
    start, end = 0, len(tokens)
    while start < end and tokens[start][0] == " ":
        start += 1
    if start < end and tokens[start][0] == "<":
        start += 1
    while end > start and tokens[end - 1][0] == " ":
        end -= 1
    if end > start and tokens[end - 1][0] == ">":
        end -= 1
    if not _read_rules(tokens, start, end, sheet, 0, budget):
        sheet.unreadable = True


class _Styler:
    """Judges the elements of one HTML part against its style blocks, each distinct element once."""

    def __init__(self, sheet: Sheet, budget: Any = mail_reuse.NO_BUDGET) -> None:
        self.sheet = sheet
        self.budget = budget
        self.link_colours: Tuple[Colour, ...] = ()
        self.page_colours: Tuple[Colour, ...] = (_BLACK,)   # the text colours the page itself may have
        self._cache: Dict[Any, Own] = {}

    def own(self, tag: str, attrs: Dict[str, str]) -> Own:
        if not attrs and not self.sheet.rules and tag not in _TAG_FONT_FACTORS:
            return _PLAIN_OWN
        key = (tag, tuple(sorted(attrs.items())))
        found = self._cache.get(key)
        if found is None:
            if len(self._cache) > 20_000:
                self._cache.clear()
            found = own_style(tag, attrs, self.sheet.match(tag, attrs), self.link_colours, self.budget)
            self._cache[key] = found
        return found


_NO_SHEET = Sheet()


# --------------------------------------------------------------------------------------
# The two readings of the markup
# --------------------------------------------------------------------------------------

Token = Tuple[int, int, str, str]       # (start, end, kind, name); kind is start, end, other or lost

_HTML_SPACE = "\t\n\f\r "
_TAG_NAME_END = _HTML_SPACE + "/>"
_ATTRIBUTE_NAME_END = _HTML_SPACE + "/>="
_UNQUOTED_END = _HTML_SPACE + ">"
_SCRIPT_STEP = re.compile(r"<!--|-->|<(/?)script(?=[\t\n\f\r />])", re.IGNORECASE)
_CONDITIONAL = re.compile(r"<!--[\t\n\f\r ]*\[[\t\n\f\r ]*(?:if|else|endif)\b|<!\[", re.IGNORECASE)
_CONDITIONAL_END = "<![endif]"
_TEXT_ELEMENTS = frozenset(mail_lists.RCDATA_ELEMENTS) | frozenset(mail_lists.RAWTEXT_ELEMENTS)


class BrowserReading(NamedTuple):
    tokens: Tuple[Token, ...]
    unclosed_comments: int
    conditional_comments: int


def _tag_end(text: str, index: int) -> int:
    """The offset after the `>` that ends the tag whose name ends at `index`; -1 at end of text."""
    size = len(text)
    while True:
        while index < size and text[index] in _HTML_SPACE + "/":
            index += 1
        if index >= size:
            return -1
        if text[index] == ">":
            return index + 1
        index += 1                      # the first character of a name, whatever it is
        while index < size and text[index] not in _ATTRIBUTE_NAME_END:
            index += 1
        while index < size and text[index] in _HTML_SPACE:
            index += 1
        if index < size and text[index] == "=":
            index += 1
            while index < size and text[index] in _HTML_SPACE:
                index += 1
            if index >= size:
                return -1
            if text[index] in "\"'":
                closing = text.find(text[index], index + 1)
                if closing < 0:
                    return -1
                index = closing + 1
            elif text[index] != ">":
                while index < size and text[index] not in _UNQUOTED_END:
                    index += 1


def _text_element_end(text: str, index: int, name: str) -> int:
    """Where the end tag of the text element `name` starts, from `index`; -1 when there is none."""
    if name != mail_lists.SCRIPT_ELEMENT:
        match = re.compile("</" + re.escape(name) + r"(?=[\t\n\f\r />])", re.IGNORECASE).search(text, index)
        return match.start() if match else -1
    # A script: `<!--` opens an escaped run in which `<script` opens a second level that
    # its `</script` closes without ending the element.
    escaped = False
    doubled = False
    position = index
    while True:
        match = _SCRIPT_STEP.search(text, position)
        if match is None:
            return -1
        found = match.group(0)
        position = match.end()
        if found == "<!--":
            if not escaped:
                escaped = True
                # `<!-->` and `<!--->` close at once
                if text.startswith(">", position) or text.startswith("->", position):
                    escaped = False
        elif found == "-->":
            escaped = False
            doubled = False
        elif match.group(1):
            if doubled:
                doubled = False
            else:
                return match.start()
        elif escaped:
            doubled = True


def browser_tokens(text: str, budget: Any = mail_reuse.NO_BUDGET) -> BrowserReading:
    """`text` split into tags and comments the way the HTML standard says a browser does.

    Each token is (start, end, kind, name): kind `start` or `end` with the tag name in
    lower case, `other` for a comment, a doctype or anything else a browser drops, and
    `lost` for a tag the text ends inside (a browser drops it and what follows).
    """
    tokens: List[Token] = []
    unclosed = 0
    conditional = 0
    size = len(text)
    index = 0
    # Where the next `-->` and `--!>` stand, found once and kept while they are still ahead:
    # a part of a million comments is not searched to its end a million times.
    next_plain = next_bang = -2
    while index < size:
        budget.check()
        opening = text.find("<", index)
        if opening < 0:
            break
        following = text[opening + 1:opening + 2]
        closing_tag = following == "/"
        name_at = opening + (2 if closing_tag else 1)
        first = text[name_at:name_at + 1]
        if first.isascii() and first.isalpha():
            name_end = name_at
            while name_end < size and text[name_end] not in _TAG_NAME_END:
                name_end += 1
            name = text[name_at:name_end].lower()
            end = _tag_end(text, name_end)
            if end < 0:
                tokens.append((opening, size, "lost", ""))
                break
            tokens.append((opening, end, "end" if closing_tag else "start", name))
            index = end
            if closing_tag:
                continue
            if name == "plaintext":
                break
            if name in _TEXT_ELEMENTS or name == mail_lists.SCRIPT_ELEMENT:
                index = _text_element_end(text, end, name)
                if index < 0:
                    break
            continue
        if closing_tag:
            if first == ">":
                tokens.append((opening, opening + 3, "other", ""))
                index = opening + 3
                continue
            if first == "":
                break
        elif following == "!" and text.startswith("<!--", opening):
            if _CONDITIONAL.match(text, opening):
                conditional += 1
            if text.startswith(">", opening + 4):
                end = opening + 5
            elif text.startswith("->", opening + 4):
                end = opening + 6
            else:
                if next_plain != -1 and next_plain < opening + 4:
                    next_plain = text.find("-->", opening + 4)
                if next_bang != -1 and next_bang < opening + 4:
                    next_bang = text.find("--!>", opening + 4)
                plain, bang = next_plain, next_bang
                if plain < 0 and bang < 0:
                    unclosed += 1
                    end = size
                elif bang < 0 or 0 <= plain < bang:
                    end = plain + 3
                else:
                    end = bang + 4
            if _CONDITIONAL_END in text[opening:end].lower() and not _CONDITIONAL.match(text, opening):
                conditional += 1
            tokens.append((opening, end, "other", ""))
            index = end
            continue
        elif following not in ("!", "?"):
            index = opening + 1         # a `<` that opens nothing: text
            continue
        if _CONDITIONAL.match(text, opening):
            conditional += 1
        end = text.find(">", opening)
        end = size if end < 0 else end + 1
        tokens.append((opening, end, "other", ""))
        index = end
    return BrowserReading(tuple(tokens), unclosed, conditional)


Event = Tuple[int, str, str, Any]       # (offset, kind, name, attributes or text)


class _Recorder(html.parser.HTMLParser):
    """Records what `html.parser` reports for one part, each event with its offset."""

    def __init__(self, text: str, budget: Any = mail_reuse.NO_BUDGET) -> None:
        super().__init__(convert_charrefs=True)
        self.events: List[Event] = []
        self._budget = budget
        self._lines = [0]
        position = text.find("\n")
        while position >= 0:
            self._lines.append(position + 1)
            position = text.find("\n", position + 1)

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._lines[line - 1] + column

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        self._budget.check()
        self.events.append((self._offset(), "start", tag, attrs))

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        self.events.append((self._offset(), "startend", tag, attrs))

    def handle_endtag(self, tag: str) -> None:
        self._budget.check()
        self.events.append((self._offset(), "end", tag, None))

    def handle_data(self, data: str) -> None:
        self._budget.check()
        self.events.append((self._offset(), "data", "", data))

    def handle_comment(self, data: str) -> None:
        self._budget.check()
        self.events.append((self._offset(), "other", "", None))

    def handle_decl(self, decl: str) -> None:
        self.events.append((self._offset(), "other", "", None))

    def handle_pi(self, data: str) -> None:
        self.events.append((self._offset(), "other", "", None))

    def unknown_decl(self, data: str) -> None:
        self.events.append((self._offset(), "other", "", None))


def parser_events(text: str, budget: Any = mail_reuse.NO_BUDGET) -> List[Event]:
    """What `html.parser` reports for `text`, in order."""
    recorder = _Recorder(text, budget)
    recorder.feed(text)
    recorder.close()
    return recorder.events


def parser_tokens(events: Sequence[Event], size: int) -> Tuple[Token, ...]:
    """The tags and comments among `events` as tokens. A token ends where the next event starts.

    They end with a <plaintext> start tag, as the tokens of `browser_tokens` do: for a
    browser nothing after it is markup, and the reader shows nothing after it.
    """
    tokens: List[Token] = []
    for index, (offset, kind, name, _payload) in enumerate(events):
        if kind == "data":
            continue
        end = events[index + 1][0] if index + 1 < len(events) else size
        kind = "start" if kind == "startend" else kind
        tokens.append((offset, end, kind, name if kind != "other" else ""))
        if kind == "start" and name == "plaintext":
            break
    return tuple(tokens)


# --------------------------------------------------------------------------------------
# One HTML part
# --------------------------------------------------------------------------------------

_ALLOWED = frozenset(mail_lists.ELEMENT_ALLOWLIST)
_VOID = frozenset(mail_lists.VOID_ELEMENTS)
_AMBIGUOUS = frozenset(mail_lists.HTML_AMBIGUOUS_ELEMENTS)
_FORMATTING = frozenset(mail_lists.FORMATTING_ELEMENTS)
_SPECIAL = frozenset(mail_lists.SPECIAL_ELEMENTS)
_P_CLOSING = frozenset(mail_lists.P_CLOSING_ELEMENTS)
_HEADINGS = frozenset(mail_lists.HEADING_ELEMENTS)
_LISTS = frozenset(mail_lists.LIST_ELEMENTS)
_BLOCKS = frozenset(mail_lists.BLOCK_ELEMENTS)
_CELLS = frozenset(mail_lists.TABLE_CELL_ELEMENTS)
_HEAD = frozenset(mail_lists.HEAD_ELEMENTS)
_PARSER_RAW = (mail_lists.SCRIPT_ELEMENT, mail_lists.STYLE_ELEMENT)
# The elements that bound a search for an open element (the "scope" of the standard).
_SCOPE = frozenset({"td", "th", "table", "caption", "applet", "marquee", "object", "template"})
# Table structure, with how deep each stands in a table.
_TABLE_RANK = {"caption": 1, "colgroup": 1, "col": 1, "tbody": 1, "thead": 1, "tfoot": 1, "tr": 2,
               "td": 3, "th": 3}
_LI_PASSES = frozenset({"address", "div", "p"})
# Table structure that holds no content of its own: what is written straight into it is
# moved by a browser to stand before the table.
_FOSTERING = frozenset({"table", "tbody", "thead", "tfoot", "tr"})
# Table structure that any other table structure closes.
_TABLE_LEAVES = frozenset({"caption", "colgroup"})
_WHITESPACE = re.compile("[ \t\n\r\f]+")
_ROOT_DEPTH = 3                 # the page, <html> and <body>: never closed
# The two limits of the standard's "adoption agency": special elements it works through,
# and formatting elements it keeps between two of them.
_ADOPTION_ROUNDS = 7
_ADOPTION_KEPT = 3
# A browser keeps at most this many formatting elements with the same tag and attributes.
_SAME_FORMATTING = 3
# The tag of an element no tag can reach any more, although what stands in it is still in it.
_STRUCK = "#struck"
# Elements that fence formatting elements in: one opened inside is not opened again outside.
_MARKERS = frozenset({"td", "th", "caption"})
# Start tags before which a browser does NOT open pending formatting elements again.
_NO_REOPEN = (frozenset(mail_lists.P_CLOSING_ELEMENTS) - {"xmp"}) | frozenset(_TABLE_RANK) | frozenset({
    "table", "html", "body", "head", "frameset", "base", "basefont", "bgsound", "link", "meta", "noframes",
    "script", "style", "template", "title", "param", "source", "track", "textarea", "iframe", "noembed",
    "rb", "rtc", "rp", "rt", "form", "plaintext"})


class _Element:
    __slots__ = ("tag", "attrs", "allowed", "named", "own", "state", "pairs", "background_unknown",
                 "font_lo", "font_hi", "opacity", "left", "up", "away", "indent", "room", "quote", "pre",
                 "pending_mark", "serial",
                 "listed", "lines_mark", "style_tag", "styler", "seen", "doubt", "hides",
                 "rtl", "right", "nowrap", "clipped", "push", "columns", "column")

    def __init__(self, tag: str, attrs: Dict[str, str], parent: Optional["_Element"],
                 styler: Optional[_Styler] = None) -> None:
        self.tag = tag
        self.style_tag = tag            # `tag` may be blanked (see `replace_anchor`); this is not
        self.attrs = attrs
        self.pending_mark = 0
        self.doubt = False              # a column of this table may hide its cells (see `doubt_table`)
        self.lines_mark = 0             # how many lines of the view were written when it opened
        self.serial = 0
        # a table: whether a <col> gives each column a width (see A CELL THAT CLIPS), and the
        # column the next cell of the open row starts in
        self.columns: List[bool] = []
        self.column = 0
        # a formatting element a browser will open again if it is closed out of order
        self.listed = False
        self.allowed = (tag in _ALLOWED or tag in mail_lists.TRANSPARENT_ELEMENTS
                        or tag in mail_lists.WORD_ELEMENTS or tag.startswith(mail_lists.WORD_ELEMENT_PREFIXES))
        # what the standard parser took for a tag and is no element name: text between angle brackets
        self.named = mail_lists.ELEMENT_NAME.fullmatch(tag) is not None
        self.seen: Optional[str] = None     # how its own text reads, worked out when first asked
        if parent is None:
            self.styler = styler if styler is not None else _Styler(_NO_SHEET)
            self.own = _PLAIN_OWN
            self.state = VISIBLE
            self.hides = False
            # the (text colour, background) pairs its text may be drawn in
            self.pairs: Tuple[Tuple[Colour, Tuple[float, float, float]], ...] = ((_BLACK, _WHITE),)
            self.background_unknown = False
            # what adds up down the ancestors: the least and the greatest font size the text
            # may have, its opacity, and how far it may be pulled left, pulled up or pushed away
            self.font_lo = self.font_hi = mail_lists.DEFAULT_FONT_SIZE_PX
            self.opacity = 1.0
            self.left = self.up = self.away = 0.0
            # the text-indent in force (it is inherited; 0 or negative), and the room for it
            self.indent = self.room = 0.0
            self.quote = False
            self.pre = False
            # what stands around it: text that may run right to left, a box anchored on the
            # right, text that does not wrap, a cell that clips and how far into it text is pushed
            self.rtl = self.right = self.nowrap = self.clipped = False
            self.push = 0.0
            return
        self.styler = parent.styler
        self.inherit(parent)

    def inherit(self, parent: "_Element") -> None:
        """Work out what this element is, standing in `parent`."""
        own = self.styler.own(self.style_tag, self.attrs)
        self.own = own
        self.seen = None
        if own.fonts:
            low = [amount if kind == "px" else amount * parent.font_lo for kind, amount in own.fonts]
            high = [amount if kind == "px" else amount * parent.font_hi for kind, amount in own.fonts]
            if own.font_inherit:
                low.append(parent.font_lo)
                high.append(parent.font_hi)
            self.font_lo, self.font_hi = min(low), max(high)
        else:
            self.font_lo, self.font_hi = parent.font_lo, parent.font_hi
        self.opacity = parent.opacity * own.opacity
        left, up, away, spaced = moved(own, self.font_lo, self.font_hi) if own.moves else (0.0, 0.0, 0.0, VISIBLE)
        self.left, self.up, self.away = parent.left + left, parent.up + up, parent.away + away
        # the hanging indent: a negative text-indent needs a left margin or padding to hang in
        values = dict(own.moves)
        self.indent = parent.indent
        if "text-indent" in values:
            self.indent = min([min(0.0, _px(length, self.font_hi)) for length in values["text-indent"]]
                              + ([] if "text-indent" in own.room else [parent.indent]))
        # `room`: how far to the right of the edge of the page its lines start FOR CERTAIN.
        # Left margins and paddings that certainly apply to a block add to it; a negative
        # margin that may apply to any element takes from it; below zero it is a pull to the left.
        block = self.style_tag in _TEXT_BLOCKS and not own.shaped
        if block:
            self.room = parent.room + sum(max(0.0, min(_room_px(length, self.font_lo) for length in values[name]))
                                          for name in own.room if name != "text-indent")
        elif own.shaped or "text-indent" in values:
            self.room = min(0.0, parent.room)
        else:
            self.room = parent.room
        for name in ("margin-left", "margin-right"):
            self.room += min([_px(length, self.font_hi) for length in values.get(name, ())] + [0.0])
        hanging = (block or own.shaped) and -self.indent > max(0.0, self.room) + 0.01
        pulled = self.left + max(0.0, -self.room)
        # fix round 3: right-anchored overflow (S5) and a cell that clips (S10). Both are taken
        # from the element itself and everything around it: once inside, never left again.
        self.rtl = parent.rtl or own.rtl
        self.right = parent.right or own.right
        self.nowrap = parent.nowrap or own.nowrap or self.style_tag in mail_lists.NOWRAP_ELEMENTS
        self.clipped = parent.clipped or own.cell_clip
        self.push = (parent.push if parent.clipped else 0.0) + sum(_px(length, self.font_hi) for length in own.pushes)
        wide = any((kind == "%" and amount > 100.0)
                   or (kind != "%" and _px((kind, amount), self.font_hi) > mail_lists.RIGHT_ANCHORED_WIDTH_PX)
                   for kind, amount in own.widths)
        # fix round 3 (S9, Codex 1): a negative indent puts the first words outside the box of
        # the block, where its background is not painted: a block that paints one is uncertain
        painted_hanging = self.indent < 0 and own.painted and (block or own.shaped)
        overflowing = painted_hanging or ((self.rtl and (self.nowrap or bool(own.widths)))
                       or (self.right and (self.nowrap or wide))
                       or (self.clipped and (self.nowrap or bool(own.widths)
                                             or self.push > mail_lists.CELL_CLIP_PUSH_PX
                                             or own.spread > mail_lists.CELL_CLIP_SPACING_PX)))
        # what the element itself does to its text, wherever it stands
        mine = own.state
        if not mine:
            far = mail_lists.HIDDEN_OFFSET_BEYOND_PX
            if (self.opacity < mail_lists.HIDDEN_OPACITY_BELOW or spaced == HIDDEN
                    or pulled > far or self.up > far or self.away > far):
                mine = HIDDEN
            elif (spaced or self.doubt or hanging or overflowing
                  or pulled > mail_lists.UNCERTAIN_NEGATIVE_MARGIN_BEYOND_PX
                  or self.up > mail_lists.UNCERTAIN_UPWARD_SHIFT_BEYOND_PX
                  or self.away > mail_lists.UNCERTAIN_OFFSET_BEYOND_PX):
                mine = UNCERTAIN
        self.hides = bool(mine)
        state = parent.state or mine
        self.state = state or (VISIBLE if self.allowed else (OTHER if self.named else UNCERTAIN))
        around = parent.pairs
        if self.style_tag == "table":
            # A page without a doctype gives the text of a table the colour and the size of the
            # page again, whatever stands around the table: that reading is judged as well.
            around = tuple(dict.fromkeys(around + tuple(
                (colour, background) for colour in self.styler.page_colours for _colour, background in around)))
            self.font_lo = min(self.font_lo, mail_lists.DEFAULT_FONT_SIZE_PX)
            self.font_hi = max(self.font_hi, mail_lists.DEFAULT_FONT_SIZE_PX)
        if own.combos is _NO_COMBOS:
            pairs = around
        else:
            found: Dict[Tuple[Colour, Tuple[float, float, float]], None] = {}
            for colour, background in own.combos:
                for parent_colour, parent_background in around:
                    behind = parent_background if background is None else (
                        background[:3] if background[3] >= 1 else _over(background, parent_background))
                    found[(parent_colour if colour is None else colour, behind)] = None
            pairs = tuple(found)
            if len(pairs) > mail_lists.STYLE_MAX_COLOUR_PAIRS:
                pairs = pairs[:mail_lists.STYLE_MAX_COLOUR_PAIRS]
                if not self.state:
                    self.state = UNCERTAIN
        self.pairs = pairs
        self.background_unknown = own.background_unknown or (parent.background_unknown
                                                             and not own.background_known)
        self.quote = parent.quote or self.style_tag == mail_lists.QUOTE_ELEMENT
        self.pre = parent.pre or self.style_tag == mail_lists.PREFORMATTED_ELEMENT


def _sets_text_style(own: Own) -> bool:
    """Whether an element's own attributes, or a rule for it, set a colour, a size or a background."""
    return own.sets_text_style


def _span(value: Optional[str]) -> int:
    """A `span`, `colspan` or `rowspan` attribute as a number: 1 when absent or not a number, at most 1,000."""
    match = re.match(r"[\t\n\f\r ]*([0-9]{1,6})", value or "")
    return min(1_000, int(match.group(1))) if match else 1


def _first_wins(attrs: Sequence[Tuple[str, Optional[str]]]) -> Dict[str, str]:
    """Attributes as a browser keeps them: the first of a repeated name."""
    out: Dict[str, str] = {}
    for name, value in attrs or ():
        if name not in out:
            out[name] = value or ""
    return out


class _PartView:
    """What one selected part gives the view."""

    def __init__(self) -> None:
        self.lines: List[Tuple[str, bool]] = []     # (text, quoted by markup)
        self.removed: Dict[str, List[str]] = {HIDDEN: [], UNCERTAIN: []}
        self.chars = {HIDDEN: 0, UNCERTAIN: 0, OTHER: 0}
        self.classes = {cls.name: 0 for cls in mail_reuse.CHAR_CLASSES}
        self.gaps: Dict[Tuple[str, str], int] = {}
        self.dropped_elements = 0
        self.dropped_attributes = 0
        self.links = 0
        self.links_unlisted = 0
        self.images = 0
        self.style_blocks = 0
        self.conditional_comments = 0
        self.unseen = 0             # unseen characters taken out of text that was shown

    def gap(self, name: str, detail: str = mail_lists.DETAIL_NONE, count: int = 1) -> None:
        self.gaps[(name, detail)] = self.gaps.get((name, detail), 0) + count

    def count_classes(self, text: str) -> None:
        """Count the stripped-class characters of `text` that a view takes out.

        A listed flag emoji is no tag character, and a joiner between two emoji is part of
        one emoji: neither is counted.
        """
        if text.isascii():
            return
        text = mail_reuse.fold_flags(text)[0]
        for index in mail_reuse.invisible_offsets(text):
            for cls in mail_reuse.CHAR_CLASSES:
                if text[index] in cls:
                    self.classes[cls.name] += 1
                    break

    def remove(self, state: str, text: str) -> None:
        text = _strip(text)
        self.chars[state] += _weight(text)
        if state in self.removed and text.strip():
            self.removed[state].append(text)


def _clean(text: str) -> Tuple[str, int]:
    """(`text` without the characters no reader sees, how many of them were of the unseen class).

    A listed flag emoji is left as its black flag; a variation selector after an emoji and
    a joiner between two emoji stay (`mail_reuse.strip_invisible`).
    """
    if text.isascii():
        return text, 0
    cleaned, _stripped, unseen = mail_reuse.strip_invisible(mail_reuse.fold_flags(text)[0])
    return cleaned, unseen


def _strip(text: str) -> str:
    return _clean(text)[0]


def _shown(text: str, view: _PartView) -> str:
    """Message text as a view shows it: cleaned, counted, and with no square bracket of its own."""
    text, unseen = _clean(text)
    view.unseen += unseen
    return mail_frame.escape_content(text)


def _weight(text: str) -> int:
    """The characters of `text` that are not white space."""
    return len("".join(text.split()))


def shown_host(host: str) -> str:
    """A host as a link token shows it: cut, and with every unusual character replaced."""
    if not host:
        return mail_lists.LINK_HOST_NONE
    return "".join(char if mail_lists.LINK_HOST_SHOWN.fullmatch(char) else mail_lists.LINK_HOST_OTHER
                   for char in host[:mail_lists.LINK_HOST_MAX_CHARS])


def _text_links(text: str) -> List[Tuple[int, int]]:
    """(start, end) of every URL typed in `text`, as the parser's inventory cuts them."""
    out = []
    for match in mail_lists.URL_IN_TEXT.finditer(text):
        url = match.group(0).rstrip(mail_lists.URL_TRAILING_PUNCTUATION)
        out.append((match.start(), match.start() + len(url)))
    return out


class _LinkLabels:
    """The numbers the inventory gave the links of one part."""

    def __init__(self, links: Sequence[Any], part_id: str, view: _PartView) -> None:
        self._listed = {(link.kind, link.occurrence): link for link in links if link.part_id == part_id}
        self._seen = {mail_lists.LINK_ANCHOR: 0, mail_lists.LINK_TEXT: 0}
        self._view = view

    def next(self, kind: str) -> int:
        """Count one link of `kind` and return its occurrence."""
        occurrence = self._seen[kind]
        self._seen[kind] += 1
        return occurrence

    def token(self, kind: str, occurrence: int) -> str:
        link = self._listed.get((kind, occurrence))
        self._view.links += 1
        if link is None:
            self._view.links_unlisted += 1
            return mail_lists.LINK_TOKEN_FORMAT % (mail_lists.LINK_NUMBER_UNLISTED, mail_lists.LINK_HOST_NONE)
        return mail_lists.LINK_TOKEN_FORMAT % (link.number, shown_host(link.host))


class _HtmlReader:
    """Walks the events of one HTML part and keeps the text a person would see.

    It keeps the open elements the way the HTML standard says a browser does ("in body"
    and the table rules), because which element a text stands in decides whether it is
    seen. `stack` is the open elements. `pending` holds elements that were closed by
    something other than their own end tag and may still matter: a formatting element,
    which a browser opens again before the next text (`reopen`), and any other element
    whose own attributes hide it, which is kept as a doubt until the table cell it stood
    in ends.
    """

    def __init__(self, view: _PartView, labels: Optional[_LinkLabels], sheet: Optional[Sheet] = None,
                 budget: Any = mail_reuse.NO_BUDGET) -> None:
        self.view = view
        self.labels = labels
        self.sheet = sheet if sheet is not None else _NO_SHEET
        self.styler = _Styler(self.sheet, budget)
        self.budget = budget
        self.stack: List[_Element] = [_Element("#page", {}, None, self.styler)]
        self.pending: List[_Element] = []
        self.serial = 0
        self.buffer: List[str] = []
        self.buffer_quoted = False
        self.parser_raw: Optional[str] = None   # the <script> or <style> the parser is inside
        self.stopped = False                    # nothing more of this part is shown
        self.pulled = False                     # a negative margin was met: what follows may be pulled anywhere

    # ---- output -----------------------------------------------------------------------

    def flush(self) -> None:
        text = "".join(self.buffer).strip(" \t")
        self.buffer = []
        lines = self.view.lines
        if text or (lines and lines[-1][0]):
            lines.append((text, self.buffer_quoted))

    def emit(self, text: str, element: _Element) -> None:
        text = _shown(text, self.view)
        if not text:
            return
        if self.buffer and self.buffer_quoted != element.quote:
            self.flush()
        self.buffer_quoted = element.quote
        if element.pre:
            pieces = mail_frame.normalize_lines(text).split("\n")
            for number, piece in enumerate(pieces):
                if number:
                    self.flush()
                    self.buffer_quoted = element.quote
                if piece:
                    self.buffer.append(piece)
            return
        text = _WHITESPACE.sub(" ", text)
        if not self.buffer or self.buffer[-1].endswith((" ", "\t")):
            text = text.lstrip(" ")
        if text:
            self.buffer.append(text)

    def token(self, kind: str, occurrence: int, element: _Element) -> None:
        if self.buffer and self.buffer_quoted != element.quote:
            self.flush()
        self.buffer_quoted = element.quote
        if self.buffer and not self.buffer[-1].endswith((" ", "\t")):
            self.buffer.append(" ")
        self.buffer.append(self.labels.token(kind, occurrence) + " ")

    def stop(self, detail: str) -> None:
        """Show nothing more of this part.

        The tags after this point are no longer followed, and one of them may end a
        formatting element across a block, which changes how text already written in
        that block is read (see `close_formatting`). So that text is taken back here.
        """
        if self.stopped:
            return
        self.view.gap(GAP_HTML_AMBIGUOUS, detail)
        for index in range(_ROOT_DEPTH, len(self.stack)):
            element = self.stack[index]
            if element.listed and _sets_text_style(element.own):
                block = next((other for other in self.stack[index + 1:] if other.tag in _SPECIAL), None)
                if block is not None:
                    self.withdraw(block)
                    break
        self.flush()
        self.stopped = True

    # ---- whether text is seen ---------------------------------------------------------

    def reading(self, element: _Element) -> str:
        """How text standing directly in `element` reads, by its size and its colours."""
        if element.seen is None:
            element.seen = self._reading(element)
        return element.seen

    def _reading(self, element: _Element) -> str:
        if element.font_hi < mail_lists.HIDDEN_FONT_SIZE_BELOW_PX:
            return HIDDEN
        # fix round 3 (S7): the opacity down the ancestors blends the text toward its backdrop
        # before the contrast test (opacity alone is judged in `_Element.inherit`)
        faded = min(1.0, max(0.0, element.opacity))
        low = [contrast(_over(_over(colour, background) + (faded,), background), background)
               < mail_lists.HIDDEN_CONTRAST_BELOW for colour, background in element.pairs]
        if all(low) and not element.background_unknown:
            return HIDDEN               # proven: in every colour it may get
        if any(low) or element.font_lo < mail_lists.UNCERTAIN_FONT_SIZE_BELOW_PX:
            return UNCERTAIN
        return VISIBLE

    def foster(self) -> Optional[_Element]:
        """Where a browser puts content written straight into a table: before the table.

        The element such content really stands in, when the innermost open element is
        table structure other than a cell; else None.
        """
        if self.stack[-1].tag not in _FOSTERING:
            return None
        table = self.nearest(("table",))
        return self.stack[table - 1] if table is not None else None

    def text_state(self, element: _Element) -> str:
        if element.state:
            return element.state
        if self.pulled:
            return UNCERTAIN            # fix round 3 (S6): pulled by a negative margin that stood before it
        state = self.reading(element)
        if state:
            return state
        if element is self.stack[-1]:
            foster = self.foster()
            if foster is not None and (foster.state or self.reading(foster)):
                return UNCERTAIN
        if any(waiting.tag not in _FORMATTING for waiting in self.pending):
            return UNCERTAIN            # an element that hides its text may still be open
        return VISIBLE

    # ---- the open elements ------------------------------------------------------------

    def find(self, tag: str, stop_at_special: bool = False, extra: Any = ()) -> Optional[int]:
        """The index of the nearest open `tag` that a tag may reach, or None."""
        for index in range(len(self.stack) - 1, _ROOT_DEPTH - 1, -1):
            element = self.stack[index]
            if element.tag == tag:
                return index
            if element.tag in _SCOPE or element.tag in extra or (stop_at_special and element.tag in _SPECIAL):
                return None
        return None

    def nearest(self, tags: Any) -> Optional[int]:
        return self.nearest_below(len(self.stack), tags)

    def nearest_below(self, limit: int, tags: Any) -> Optional[int]:
        """The index of the innermost open element below `limit` whose tag is in `tags`."""
        for index in range(limit - 1, _ROOT_DEPTH - 1, -1):
            if self.stack[index].tag in tags:
                return index
        return None

    def marker(self) -> Tuple[int, int]:
        """(index, mark): the innermost open element that fences formatting elements in, and
        where `pending` stood when it was opened. (_ROOT_DEPTH - 1, 0) when there is none."""
        index = self.nearest(_MARKERS)
        if index is None:
            return _ROOT_DEPTH - 1, 0
        return index, self.stack[index].pending_mark

    def push(self, tag: str, attrs: Dict[str, str]) -> Optional[_Element]:
        """Open an element in the innermost open one. None when the part is too deep."""
        if len(self.stack) >= mail_lists.VIEW_MAX_ELEMENT_DEPTH:
            self.stop(mail_lists.DETAIL_STRUCTURE)
            return None
        parent = self.stack[-1]
        foster = self.foster() if tag not in _TABLE_RANK and tag != "table" else None
        element = _Element(tag, attrs, parent if foster is None else foster)
        if foster is not None and parent.state and not element.state:
            element.state = parent.state
        element.pending_mark = len(self.pending)
        element.lines_mark = len(self.view.lines) + (1 if self.buffer else 0)
        self.stack.append(element)
        return element

    def withdraw(self, element: _Element) -> None:
        """Take back what was written since `element` opened: it is removed as uncertain."""
        self.flush()
        taken = self.view.lines[element.lines_mark:]
        del self.view.lines[element.lines_mark:]
        text = "\n".join(line for line, _quoted in taken)
        if text.strip():
            self.view.gap(GAP_HTML_AMBIGUOUS, mail_lists.DETAIL_STRUCTURE)
            self.view.remove(UNCERTAIN, text)

    def recompute(self, index: int) -> None:
        """Work the open elements from `index` up out again, after one below them changed."""
        for position in range(index, len(self.stack)):
            element, parent = self.stack[position], self.stack[position - 1]
            fostered = parent.tag in _FOSTERING and element.tag not in _TABLE_RANK and element.tag != "table"
            table = self.nearest_below(position, ("table",)) if fostered else None
            element.inherit(parent if table is None else self.stack[table - 1])
            if table is not None and parent.state and not element.state:
                element.state = parent.state

    def pop_from(self, index: int, target: bool, table: bool = False) -> None:
        """Close the open elements from `index` up.

        `target`: the element at `index` is the one the tag names. `table`: the tag is
        table structure, which closes ordinary elements for a browser too. Of the
        others: a formatting element goes to `pending`, to be opened again; so does any
        other element whose own attributes hide it, as a doubt. What stood in a table
        cell that closes here is over, and so is everything that was pending in it.
        """
        popped = self.stack[index:]
        del self.stack[index:]
        fence = next((number for number, element in enumerate(popped) if element.tag in _MARKERS), None)
        kept: List[_Element] = []
        for number, element in enumerate(popped):
            if (target and number == 0) or (fence is not None and number >= fence):
                continue
            if element.tag in _FORMATTING:
                if element.listed:
                    kept.append(element)
            elif not table and element.hides:
                kept.append(element)
                self.view.gap(GAP_HTML_AMBIGUOUS, mail_lists.DETAIL_STRUCTURE)
        if fence is not None:
            del self.pending[popped[fence].pending_mark:]
        self.pending.extend(kept)
        if len(self.pending) > mail_lists.VIEW_MAX_PENDING_ELEMENTS:
            self.stop(mail_lists.DETAIL_STRUCTURE)
        if any(element.tag in _BLOCKS for element in popped):
            self.flush()

    def reopen(self) -> None:
        """Open the pending formatting elements again, as a browser does before text."""
        _index, mark = self.marker()
        again = [element for element in self.pending[mark:] if element.tag in _FORMATTING]
        if not again:
            return
        self.pending[mark:] = [element for element in self.pending[mark:] if element.tag not in _FORMATTING]
        # in the order they were first opened, which is the order a browser lists them in
        for waiting in sorted(again, key=lambda element: element.serial):
            clone = self.push(waiting.tag, waiting.attrs)
            if clone is None:
                return
            clone.serial = waiting.serial
            clone.listed = True

    def list_formatting(self, element: _Element) -> None:
        """Enter a new formatting element in the list; a fourth of the same kind drops the first."""
        self.serial += 1
        element.serial = self.serial
        element.listed = True
        index, mark = self.marker()
        same = [other for other in self.stack[index + 1:-1] + self.pending[mark:]
                if other.listed and other.tag == element.tag and other.attrs == element.attrs]
        if len(same) >= _SAME_FORMATTING:
            first = min(same, key=lambda other: other.serial)
            first.listed = False
            if any(first is waiting for waiting in self.pending):
                self.pending = [waiting for waiting in self.pending if waiting is not first]

    def close_formatting(self, index: int) -> None:
        """The end of the formatting element at `index` (the "adoption agency" of the standard).

        With no special element open inside it, it closes with everything in it. Else the
        element itself ends and every special element in it stays open; of the elements
        between two of those, a browser keeps only formatting elements, and only the three
        nearest the special element above them; what stands above the last special
        element is closed.
        """
        above = self.stack[index + 1:]
        special = [number for number, element in enumerate(above) if element.tag in _SPECIAL]
        if not special:
            self.pop_from(index, target=True)
            return
        if len(special) > _ADOPTION_ROUNDS:
            self.stop(mail_lists.DETAIL_STRUCTURE)
            return
        if _sets_text_style(self.stack[index].own):
            # A browser now puts what the first special element holds INSIDE a copy of the
            # formatting element, so the colour or size it sets wins over the special
            # element's own: text already written there may be read another way.
            self.withdraw(above[special[0]])
        self.pop_from(index + 1 + special[-1] + 1, target=False)
        kept: List[_Element] = []
        previous = -1
        for number in special:
            between = above[previous + 1:number]
            survivors = [element for distance, element in enumerate(reversed(between), 1)
                         if distance <= _ADOPTION_KEPT and element.tag in _FORMATTING and element.listed]
            kept.extend(reversed(survivors))
            kept.append(above[number])
            previous = number
        self.stack[index:] = kept
        self.recompute(index)

    def end_formatting(self, tag: str) -> None:
        """The end tag of a formatting element: it ends the one a browser entered last."""
        index, mark = self.marker()
        open_ones = [position for position in range(index + 1, len(self.stack))
                     if self.stack[position].tag == tag and self.stack[position].listed]
        waiting = [position for position in range(mark, len(self.pending)) if self.pending[position].tag == tag]
        if not open_ones and not waiting:
            found = self.find(tag, stop_at_special=True)
            if found is not None:
                self.pop_from(found, target=True)
            return
        last_open = max(open_ones, key=lambda position: self.stack[position].serial) if open_ones else None
        last_waiting = max(waiting, key=lambda position: self.pending[position].serial) if waiting else None
        if last_open is None or (last_waiting is not None
                                 and self.pending[last_waiting].serial > self.stack[last_open].serial):
            del self.pending[last_waiting]
            return
        if any(element.tag in _SCOPE for element in self.stack[last_open + 1:]):
            return
        self.close_formatting(last_open)

    def replace_anchor(self) -> None:
        """A new <a> ends the <a> that is still open or pending, wherever it stands."""
        index, mark = self.marker()
        open_ones = [position for position in range(index + 1, len(self.stack))
                     if self.stack[position].tag == "a" and self.stack[position].listed]
        waiting = [position for position in range(mark, len(self.pending)) if self.pending[position].tag == "a"]
        if not open_ones and not waiting:
            return
        last_open = max(open_ones, key=lambda position: self.stack[position].serial) if open_ones else None
        last_waiting = max(waiting, key=lambda position: self.pending[position].serial) if waiting else None
        if last_open is None or (last_waiting is not None
                                 and self.pending[last_waiting].serial > self.stack[last_open].serial):
            del self.pending[last_waiting]
            return
        anchor = self.stack[last_open]
        if not any(element.tag in _SCOPE for element in self.stack[last_open + 1:]):
            self.close_formatting(last_open)
            return
        # A table stands between: a browser strikes the old <a> from its list of open
        # elements, so no tag reaches it any more, but what was put in it stays in it.
        anchor.tag = _STRUCK
        anchor.listed = False

    def place_cell(self, element: _Element) -> None:
        """Count the columns of a row; doubt a fixed-layout table where a cell that clips has no declared width.

        In a table laid out `fixed`, a column takes its width from a <col> or from nothing (a
        cell that sets a width of its own does not clip here). A cell that clips in a column no
        <col> gives a width may be as narrow as nothing: the table is then doubted (A CELL THAT
        CLIPS). A cell that spans rows moves the cells of later rows: once one is met in such a
        table, every clipping cell doubts it.
        """
        table_index = self.nearest(("table",))
        if table_index is None or element.tag == "tr":
            return
        table = self.stack[table_index]
        row = self.stack[-2] if len(self.stack) > table_index + 2 else table
        start = row.column
        row.column += max(1, _span(element.attrs.get("colspan")))
        if _span(element.attrs.get("rowspan")) != 1:
            table.column = -1               # the table itself never counts a column: -1 marks a row span
        if element.own.cell_clip and table.own.fixed_layout and (
                table.column < 0 or not all(table.columns[start:row.column])
                or len(table.columns) < row.column):
            self.doubt_table()

    def doubt_table(self) -> None:
        """A column that is hidden or has no width hides the cells under it: what the table
        still gets is removed as uncertain."""
        table = self.nearest(("table",))
        if table is not None and not self.stack[table].doubt:
            self.stack[table].doubt = True
            self.recompute(table)

    def close_head(self) -> None:
        if self.stack[-1].tag == "head":
            self.pop_from(len(self.stack) - 1, target=True)

    def close_colgroup(self, tag: str = "") -> None:
        """A column group holds columns only: anything else ends it."""
        if self.stack[-1].tag == "colgroup" and tag != "col":
            self.pop_from(len(self.stack) - 1, target=True, table=True)

    def table_context(self, tag: str) -> bool:
        """Make room for the table structure `tag`. False when there is no table to put it in."""
        table = self.nearest(("table",))
        if table is None:
            return False
        rank = _TABLE_RANK[tag]
        for index in range(table + 1, len(self.stack)):
            if _TABLE_RANK.get(self.stack[index].tag, 0) >= rank or self.stack[index].tag in _TABLE_LEAVES:
                self.pop_from(index, target=False, table=True)
                return True
        for index in range(len(self.stack) - 1, table - 1, -1):
            if self.stack[index].tag in _TABLE_RANK or index == table:
                if index + 1 < len(self.stack):
                    self.pop_from(index + 1, target=False, table=True)
                return True
        return True

    def close_item(self, tags: Any) -> None:
        """A new list item (or term, or description) ends the one that is open."""
        for index in range(len(self.stack) - 1, _ROOT_DEPTH - 1, -1):
            element = self.stack[index]
            if element.tag in tags:
                self.pop_from(index, target=True)
                return
            if element.tag in _SPECIAL and element.tag not in _LI_PASSES:
                return

    # ---- events -----------------------------------------------------------------------

    def start(self, tag: str, attr_list: Any, self_closing: bool) -> None:
        attrs = _first_wins(attr_list)
        # the numbering of the parser's inventory, kept whatever is shown
        if tag in _PARSER_RAW:
            self.parser_raw = tag
        occurrence = self.labels.next(mail_lists.LINK_ANCHOR) if tag == "a" and "href" in attrs else None
        if self_closing and tag == self.parser_raw:
            self.parser_raw = None
        if tag == mail_lists.STYLE_ELEMENT:
            self.view.style_blocks += 1
        if tag in mail_lists.IMAGE_ELEMENTS:
            self.view.images += 1
        self.view.dropped_attributes += sum(1 for name in mail_lists.DROPPED_ATTRIBUTES if name in attrs)
        if self.stopped:
            return
        if tag in mail_lists.TRANSPARENT_ELEMENTS:
            if tag == "body":
                self.close_head()
            return
        if tag in _AMBIGUOUS:
            self.stop(mail_lists.DETAIL_ELEMENT)
            return
        if self.stack[-1].tag == "head" and tag not in _HEAD:
            self.close_head()
        self.close_colgroup(tag)

        if tag in _TABLE_RANK:
            if not self.table_context(tag):
                return
            # a row stands in a section and a cell in a row: a browser opens the ones left out
            if tag in _CELLS or tag == "tr":
                if self.stack[-1].tag == "table" and self.push("tbody", {}) is None:
                    return
                if tag in _CELLS and self.stack[-1].tag != "tr" and self.push("tr", {}) is None:
                    return
        elif tag == "table":
            inner = self.nearest(("table", "td", "th", "caption"))
            if inner is not None and self.stack[inner].tag == "table":
                self.pop_from(inner, target=True, table=True)
            if self.find("p", extra=("button",)) is not None:
                # a browser closes the paragraph here, or does not, by the kind of page it
                # shows the message in: what follows has two readings
                self.stop(mail_lists.DETAIL_STRUCTURE)
                return
        if tag == "li":
            self.close_item(("li",))
        elif tag in ("dd", "dt"):
            self.close_item(("dd", "dt"))
        if tag in _P_CLOSING:
            paragraph = self.find("p", extra=("button",))
            if paragraph is not None:
                self.pop_from(paragraph, target=True)
        if tag in _HEADINGS and self.stack[-1].tag in _HEADINGS:
            self.pop_from(len(self.stack) - 1, target=True)
        if tag == "a":
            self.replace_anchor()
        if tag not in _NO_REOPEN:
            self.reopen()
        if self.stopped:
            return

        parent = self.stack[-1]
        if (attrs or self.sheet.rules) and self.styler.own(tag, attrs).pulls:
            # fix round 3 (S6): a negative margin moves what follows it, siblings and their text
            # included, and such pulls add up without a bound: everything after it is in doubt
            self.pulled = True
        if tag in _VOID:
            if tag in ("br", "hr") and not parent.state:
                self.flush()
            if tag == "col":
                own = self.styler.own(tag, attrs)
                group = self.styler.own("colgroup", {}) if parent.tag != "colgroup" else _PLAIN_OWN
                # fix round 3 (S8): a background of a column is behind the text of its cells
                if own.state or own.painted or group.state or group.painted:
                    self.doubt_table()
                table = self.nearest(("table",))
                if table is not None:
                    self.stack[table].columns.extend([bool(own.widths)] * max(1, _span(attrs.get("span"))))
            return
        element = self.push(tag, attrs)
        if element is None:
            return
        if tag == "colgroup" and (element.hides or element.own.painted):
            self.doubt_table()
        if tag == "tr" or tag in _CELLS:
            self.place_cell(element)
        if tag in _FORMATTING:
            self.list_formatting(element)
        if not element.allowed and not parent.state:
            self.view.dropped_elements += 1
        if not element.state:
            if tag in _BLOCKS:
                self.flush()
            if occurrence is not None and not self.text_state(element):
                self.token(mail_lists.LINK_ANCHOR, occurrence, element)

    def end(self, tag: str) -> None:
        if tag == self.parser_raw:
            self.parser_raw = None
        if self.stopped or tag in _VOID or tag in mail_lists.TRANSPARENT_ELEMENTS:
            return
        if tag in _TABLE_RANK or tag == "table":
            index = None
            for position in range(len(self.stack) - 1, _ROOT_DEPTH - 1, -1):
                if self.stack[position].tag == tag:
                    index = position
                    break
                if self.stack[position].tag == "table":
                    break
            if index is None:
                return
            was_cell = tag in _CELLS and not self.stack[index].state
            self.pop_from(index, target=True, table=True)
            if was_cell and self.buffer:
                self.buffer.append("\t")
            return
        if tag in _FORMATTING:
            self.end_formatting(tag)
            return
        if tag in _HEADINGS:
            # the end tag of a heading closes the nearest open heading, of whatever level
            index = None
            for position in range(len(self.stack) - 1, _ROOT_DEPTH - 1, -1):
                if self.stack[position].tag in _HEADINGS:
                    index = position
                    break
                if self.stack[position].tag in _SCOPE:
                    break
        elif tag in _SPECIAL:
            index = self.find(tag, extra=_LISTS if tag == "li" else ("button",) if tag == "p" else ())
        else:
            index = self.find(tag, stop_at_special=True)
        if index is not None:
            self.pop_from(index, target=True)

    def data(self, text: str) -> None:
        if self.parser_raw is not None:
            self.view.chars[OTHER] += _weight(text)
            return
        spans = _text_links(text)
        occurrences = [self.labels.next(mail_lists.LINK_TEXT) for _span in spans]
        self.view.count_classes(text)
        if self.stopped:
            self.view.remove(UNCERTAIN, text)
            return
        blank = not text.strip(_HTML_SPACE)
        if blank and (self.stack[-1].tag == "head" or self.foster() is not None):
            return
        self.close_head()
        if not blank:
            self.close_colgroup()
        self.reopen()
        if self.stopped:
            self.view.remove(UNCERTAIN, text)
            return
        element = self.stack[-1]
        if blank:
            if not element.state:
                if element.pre:
                    self.emit(text, element)
                elif self.buffer and not self.buffer[-1].endswith((" ", "\t")):
                    self.buffer.append(" ")
            return
        state = self.text_state(element)
        if state:
            self.view.remove(state, text)
            return
        position = 0
        for (start, end), occurrence in zip(spans, occurrences):
            self.emit(text[position:start], element)
            self.token(mail_lists.LINK_TEXT, occurrence, element)
            position = end
        self.emit(text[position:], element)

    def run(self, events: Sequence[Event]) -> None:
        # <html> and <body> are one element each, however often their tags are written: a
        # browser gives the element every attribute it does not have yet.
        merged: Dict[str, Dict[str, str]] = {"html": {}, "body": {}}
        for _offset, kind, name, payload in events:
            if kind in ("start", "startend") and name in merged:
                for key, value in _first_wins(payload).items():
                    merged[name].setdefault(key, value)
        links = [legacy_colour(merged["body"][name]) for name in ("link", "vlink", "alink")
                 if merged["body"].get(name)]
        if merged["body"].get("link"):
            self.styler.link_colours = tuple(colour for colour in links if colour is not None)
        elif links:
            default = tuple(float(part) for part in mail_lists.LINK_DEFAULT_COLOUR) + (1.0,)
            self.styler.link_colours = (default,) + tuple(colour for colour in links if colour is not None)
        for tag in ("html", "body"):
            self.stack.append(_Element(tag, merged[tag], self.stack[-1]))
        text = legacy_colour(merged["body"].get("text", ""))
        self.styler.page_colours = tuple(dict.fromkeys(
            (_BLACK,) + ((text,) if text is not None else ()) + tuple(pair[0] for pair in self.stack[-1].pairs)))
        for _offset, kind, name, payload in events:
            self.budget.check()
            if kind == "data":
                self.data(payload)
            elif kind == "start":
                self.start(name, payload, False)
            elif kind == "startend":
                self.start(name, payload, True)
            elif kind == "end":
                self.end(name)
        self.flush()


_CONDITION = r"[\t\n\f\r ]*\[[\t\n\f\r ]*if[\t\n\f\r ][^\]<>]*\]"
# The usual forms. Hidden: <!--[if X]> ... <![endif]-->, one comment for a browser.
_CONDITIONAL_HIDDEN = re.compile("<!--" + _CONDITION + r">(.*)<!\[endif\]-->", re.IGNORECASE | re.DOTALL)
# Revealed: an opening and a closing tag around content a browser shows.
_CONDITIONAL_OPEN = re.compile("(?:<!--" + _CONDITION + r">(?:<!)?[\t\n\f\r -]*-->|<!" + _CONDITION[len(r"[\t\n\f\r ]*"):] + ">)",
                               re.IGNORECASE)
_CONDITIONAL_CLOSE = re.compile(r"(?:<!--[\t\n\f\r ]*<!\[endif\]-->|<!\[endif\]>)", re.IGNORECASE)
_MARKUP = re.compile(r"<[^>]*>")


def conditional_comments(text: str, tokens: Sequence[Token]) -> Tuple[int, int, List[str]]:
    """(usual, malformed, hidden texts) for the conditional comments among `tokens`.

    `usual` counts those in a usual form; `hidden texts` is what each hidden one holds,
    without its markup. Any other comment that looks conditional is `malformed`, and so
    is every revealed one when their opening and closing tags do not pair up.
    """
    usual = malformed = 0
    depth = 0
    unpaired = False
    held: List[str] = []
    for start, end, kind, _name in tokens:
        if kind != "other":
            continue
        token = text[start:end]
        if not _CONDITIONAL.match(token) and _CONDITIONAL_END not in token.lower():
            continue
        hidden = _CONDITIONAL_HIDDEN.fullmatch(token)
        if hidden is not None and "<!--" not in hidden.group(1):
            usual += 1
            held.append(html.unescape(_MARKUP.sub(" ", hidden.group(1))))
        elif _CONDITIONAL_OPEN.fullmatch(token):
            usual += 1
            depth += 1
        elif _CONDITIONAL_CLOSE.fullmatch(token):
            usual += 1
            depth -= 1
            unpaired = unpaired or depth < 0
        else:
            malformed += 1
    if unpaired or depth:
        return 0, usual + malformed, held
    return usual, malformed, held


def _unreadable_whole(events: Sequence[Event]) -> bool:
    """Whether an element of the part puts ALL of it in doubt, what stands before it included.

    An svg or math element changes how a browser splits what follows into tags, so no later
    tag is known. And after any element of `HTML_AMBIGUOUS_ELEMENTS` a browser may drop an
    <html> or <body> tag or apply it, and such a tag restyles the whole page; it may also
    read a <style>, a <script> or another text element as an ordinary tag, and then sees
    tags in it that the standard parser took for text.
    """
    after = False
    for _offset, kind, name, payload in events:
        if kind not in ("start", "startend"):
            continue
        if name in mail_lists.HTML_FOREIGN_ELEMENTS:
            return True
        if after and name in mail_lists.TRANSPARENT_ELEMENTS and payload:
            return True
        if after and (name in _TEXT_ELEMENTS or name == mail_lists.SCRIPT_ELEMENT):
            return True
        if name in _AMBIGUOUS:
            after = True
    return False


def _withheld(view: _PartView, text: str, detail: str) -> None:
    """Nothing of an HTML part is shown: its text is removed as uncertain."""
    view.gap(GAP_HTML_AMBIGUOUS, detail)
    view.count_classes(text)
    view.remove(UNCERTAIN, text)


def _style_sheet(events: Sequence[Event], budget: Any) -> Sheet:
    """The rules of every style block among `events`, read by the strict reader.

    A block that is not of its language sets `unreadable`: so does a <style> tag with an
    attribute other than `type="text/css"` and `style` (a `media` attribute, another type),
    and a page that allows a dark colour scheme (a reader in dark mode then gets a dark page,
    on which dark text is not seen). A <link> to a style sheet, whatever its address, sets `external`: it is
    never fetched, and one in a `data:` address travels in the message.
    """
    sheet = Sheet()
    inside = False
    chunks: List[str] = []

    def flush() -> None:
        try:
            read_style_block("".join(chunks), sheet, budget)
        except mail_reuse.TimeUp:
            raise
        except Exception:  # noqa: BLE001 - a block the reader fails on is one it could not read
            sheet.unreadable = True

    for _offset, kind, name, payload in events:
        if kind in ("start", "startend"):
            if name == mail_lists.STYLE_ELEMENT:
                if inside:
                    flush()
                attrs = _first_wins(payload)
                if any(key not in mail_lists.STYLE_BLOCK_ATTRIBUTES for key in attrs) or attrs.get(
                        "type", mail_lists.STYLE_BLOCK_TYPE) != mail_lists.STYLE_BLOCK_TYPE:
                    sheet.unreadable = True
                inside, chunks = kind == "start", []
            elif name == "link" and "stylesheet" in _lower(_first_wins(payload).get("rel", "")):
                sheet.external = True
            elif name == "meta":
                attrs = _first_wins(payload)
                wanted = _lower(attrs.get("content", ""))
                if (_lower(attrs.get("name", "")).strip() in mail_lists.COLOUR_SCHEME_META_NAMES
                        and "dark" in wanted):
                    sheet.unreadable = True
        elif kind == "end" and name == mail_lists.STYLE_ELEMENT and inside:
            flush()
            inside, chunks = False, []
        elif kind == "data" and inside:
            chunks.append(payload)
    if inside:
        flush()
    return sheet


def _html_part(text: str, links: Sequence[Any], part_id: str, budget: Any = mail_reuse.NO_BUDGET) -> _PartView:
    view = _PartView()
    if "\x00" in text:
        _withheld(view, text, mail_lists.DETAIL_NULL_BYTE)
        return view
    try:
        events = parser_events(text, budget)
        browser = browser_tokens(text, budget)
    except mail_reuse.TimeUp:
        raise
    except Exception:  # noqa: BLE001 - markup the reader fails on is shown to nobody
        _withheld(view, text, mail_lists.DETAIL_ERROR)
        return view
    styled = any(kind != "data" and name == mail_lists.STYLE_ELEMENT for _offset, kind, name, _payload in events)
    if styled:
        view.gap(GAP_CSS_UNRESOLVED)
    if _unreadable_whole(events):
        view.style_blocks = sum(1 for _offset, kind, name, _payload in events
                                if kind in ("start", "startend") and name == mail_lists.STYLE_ELEMENT)
        _withheld(view, "\n".join(payload for _offset, kind, _name, payload in events if kind == "data"),
                  mail_lists.DETAIL_ELEMENT)
        return view
    if parser_tokens(events, len(text)) != browser.tokens:
        view.style_blocks = sum(1 for _offset, kind, name, _payload in events
                                if kind in ("start", "startend") and name == mail_lists.STYLE_ELEMENT)
        _withheld(view, "\n".join(payload for _offset, kind, _name, payload in events if kind == "data"),
                  mail_lists.DETAIL_TOKENS)
        return view
    if browser.unclosed_comments:
        view.gap(GAP_HTML_AMBIGUOUS, mail_lists.DETAIL_COMMENT_UNCLOSED, browser.unclosed_comments)
    usual, malformed, held = conditional_comments(text, browser.tokens)
    view.conditional_comments = usual
    if malformed:
        view.gap(GAP_HTML_AMBIGUOUS, mail_lists.DETAIL_COMMENT_CONDITIONAL, malformed)
    for inside in held:
        view.remove(HIDDEN, inside)
    sheet = _style_sheet(events, budget)
    if sheet.unreadable or sheet.external:
        # Styles this reader cannot read may hide any element: nothing of the part is shown.
        view.gap(GAP_CSS_UNRESOLVED, mail_lists.DETAIL_STYLE if sheet.unreadable else mail_lists.DETAIL_EXTERNAL)
        view.style_blocks = sum(1 for _offset, kind, name, _payload in events
                                if kind in ("start", "startend") and name == mail_lists.STYLE_ELEMENT)
        raw = False
        for _offset, kind, name, payload in events:
            if name in _PARSER_RAW and kind != "data":
                raw = kind == "start"
            elif kind == "data" and not raw:
                view.count_classes(payload)
                view.remove(UNCERTAIN, payload)
        return view
    reader = _HtmlReader(view, _LinkLabels(links, part_id, view), sheet, budget)
    try:
        reader.run(events)
    except mail_reuse.TimeUp:
        raise
    except Exception:  # noqa: BLE001 - as above: in doubt nothing is shown
        fresh = _PartView()
        fresh.gaps = dict(view.gaps)
        _withheld(fresh, "\n".join(payload for _offset, kind, _name, payload in events if kind == "data"),
                  mail_lists.DETAIL_ERROR)
        return fresh
    return view


# --------------------------------------------------------------------------------------
# One plain part
# --------------------------------------------------------------------------------------

def _plain_part(text: str, links: Sequence[Any], part_id: str) -> _PartView:
    view = _PartView()
    labels = _LinkLabels(links, part_id, view)
    view.count_classes(text)
    pieces: List[str] = []
    position = 0
    for start, end in _text_links(text):
        pieces.append(text[position:start])
        pieces.append(" " + labels.token(mail_lists.LINK_TEXT, labels.next(mail_lists.LINK_TEXT)) + " ")
        position = end
    pieces.append(text[position:])
    # every second piece is a link token of ours; the others are text of the message
    shown = "".join(piece if number % 2 else _shown(piece, view) for number, piece in enumerate(pieces))
    for line in mail_frame.normalize_lines(shown).split("\n"):
        view.lines.append((line.rstrip(), False))
    return view


# --------------------------------------------------------------------------------------
# The whole view
# --------------------------------------------------------------------------------------

_TOKEN = r"\[link [0-9]+ host=[A-Za-z0-9._:?\-]*\]"
_OUR_TOKEN = re.compile(_TOKEN)
_TOKEN_OR_URL = re.compile(_TOKEN + "|" + mail_lists.URL_IN_TEXT_PATTERN, re.IGNORECASE)
_BLANK_RUN = re.compile(r"\n{3,}")
_QUOTE_MARKS = mail_lists.QUOTE_LINE_PREFIX + " \t"


def _late_links(line: str, view: _PartView) -> str:
    """Replace a URL that is still in a finished line: one the inventory does not list."""
    def replace(match: Any) -> str:
        found = match.group(0)
        if _OUR_TOKEN.fullmatch(found):
            return found
        url = found.rstrip(mail_lists.URL_TRAILING_PUNCTUATION)
        facts = mail_reuse.read_url("http://" + url if url[:4].lower() == "www." else url)
        view.links += 1
        view.links_unlisted += 1
        return (mail_lists.LINK_TOKEN_FORMAT % (mail_lists.LINK_NUMBER_UNLISTED, shown_host(facts.host))
                + found[len(url):])
    if not mail_lists.URL_IN_TEXT.search(line):
        return line
    return _TOKEN_OR_URL.sub(replace, line)


class _Labelled(NamedTuple):
    lines: List[str]
    quoted_lines: int
    visible_chars: int
    visible_letters: int


def _label(lines: Sequence[Tuple[str, bool]]) -> _Labelled:
    """The lines of the view with quoted text labelled (see the module text)."""
    out: List[str] = []
    quoted_lines = 0
    visible = 0
    letters = 0
    after_attribution = False
    in_run = False
    for text, quoted in lines:
        stripped = text.strip()
        if not stripped:
            out.append("")
            continue
        own = _OUR_TOKEN.sub("", stripped.lstrip(_QUOTE_MARKS))
        visible += _weight(own)
        letters += sum(1 for char in own if char.isalnum())
        if quoted or after_attribution or stripped.startswith(mail_lists.QUOTE_LINE_PREFIX):
            if not in_run:
                out.append(mail_lists.QUOTED_LABEL_LINE)
                in_run = True
            out.append((mail_lists.QUOTED_VIEW_PREFIX + stripped.lstrip(_QUOTE_MARKS)).rstrip())
            quoted_lines += 1
            continue
        in_run = False
        out.append(text.rstrip())
        if any(pattern.search(stripped) for pattern in mail_lists.QUOTE_ATTRIBUTIONS):
            after_attribution = True
    return _Labelled(out, quoted_lines, visible, letters)


def _cut_for_mask(text: str) -> str:
    """`text` cut to the length the mask is given, at white space where there is some."""
    if len(text) <= MASK_INPUT_CHARS:
        return text
    cut = text[:MASK_INPUT_CHARS]
    for index in range(len(cut) - 1, max(0, len(cut) - mail_reuse.MASK_WINDOW_CHARS), -1):
        if cut[index].isspace():
            return cut[:index]
    return cut


def _timed_out() -> ViewResult:
    """The view of a message whose scan ran out of time: nothing of it is shown."""
    gap = mail_lists.GAPS[GAP_STRUCTURE_OVER_BOUND]
    framed = mail_frame.frame("")
    counts = ViewCounts(*([0] * (len(ViewCounts._fields) - 1)), view_lines=framed.lines)
    return ViewResult(counts, (ViewGap(gap.name, gap.gap_class, gap.reply_effect, mail_lists.BOUND_TIME, 1),),
                      False, False, framed.text, framed.open_marker, framed.close_marker, "", "", "", 0, 0)


def build(parsed: Any, checks: Sequence[Any] = (), budget: Any = None) -> ViewResult:
    """The view of a parsed message.

    `parsed` is the result of `mail_parse.parse`: its `selected` parts (part_id, subtype,
    text) and its `links` (part_id, kind, occurrence, number, host) are read. `checks` are
    the checks of the secrets catalog (`mail_reuse.catalog_checks`); without them only the
    token pattern masks. `budget` is the wall-clock budget of the scan (`mail_reuse.Budget`;
    None: no budget): when it runs out, nothing is shown and the view carries the gap
    `structure-over-bound` with the detail `time`. Markup of any kind is read without an
    exception leaving this function: what cannot be read is removed and named in the gaps.
    """
    try:
        return _build(parsed, checks, mail_reuse.NO_BUDGET if budget is None else budget)
    except mail_reuse.TimeUp:
        return _timed_out()


def _build(parsed: Any, checks: Sequence[Any], budget: Any) -> ViewResult:
    parts: List[_PartView] = []
    for part in parsed.selected:
        budget.check_now()
        if part.subtype == mail_lists.SELECTED_HTML:
            parts.append(_html_part(part.text, parsed.links, part.part_id, budget))
        else:
            parts.append(_plain_part(part.text, parsed.links, part.part_id))

    total = _PartView()
    lines: List[Tuple[str, bool]] = []
    share_parts = 0
    for view in parts:
        uncertain = view.chars[UNCERTAIN]
        shown = sum(_weight(text) for text, _quoted in view.lines)
        if (uncertain >= mail_lists.UNCERTAIN_SHARE_MIN_CHARS
                and uncertain >= mail_lists.UNCERTAIN_SHARE_HOLD * (uncertain + shown)):
            share_parts += 1
        for text, quoted in view.lines:
            budget.check()
            for piece in mail_frame.normalize_lines(_late_links(text, view)).split("\n"):
                lines.append((piece, quoted))
        lines.append(("", False))
        for state in (HIDDEN, UNCERTAIN):
            total.removed[state].extend(view.removed[state])
        for state in total.chars:
            total.chars[state] += view.chars[state]
        for name in total.classes:
            total.classes[name] += view.classes[name]
        for key, count in view.gaps.items():
            total.gaps[key] = total.gaps.get(key, 0) + count
        total.dropped_elements += view.dropped_elements
        total.dropped_attributes += view.dropped_attributes
        total.links += view.links
        total.links_unlisted += view.links_unlisted
        total.images += view.images
        total.style_blocks += view.style_blocks
        total.conditional_comments += view.conditional_comments
        total.unseen += view.unseen

    labelled = _label(lines)
    visible_text = _BLANK_RUN.sub("\n\n", "\n".join(labelled.lines)).strip("\n")

    budget.check_now()
    masked, secrets_masked = mail_reuse.mask_secrets(_cut_for_mask(visible_text), checks)
    warning = total.chars[UNCERTAIN] > 0
    body = (mail_lists.COMPLETENESS_WARNING_LINE + "\n\n" if warning else "") + masked
    truncated = len(body) > mail_lists.VIEW_MAX_CHARS or len(visible_text) > MASK_INPUT_CHARS
    if truncated:
        total.gap(GAP_VIEW_TRUNCATED)
        body = body[:mail_lists.VIEW_MAX_CHARS]
        # a line of ours that the cut left half of is no line of ours: it goes
        last = body.rfind("\n") + 1
        if any(line.startswith(body[last:]) and line != body[last:] for line in mail_lists.SCANNER_LINES
               if body[last:]):
            body = body[:last]
    view_chars = len(body)
    if truncated:
        body += "\n" + mail_lists.TRUNCATED_LINE
    framed = mail_frame.frame(body)

    gaps = tuple(ViewGap(name, mail_lists.GAPS[name].gap_class, mail_lists.GAPS[name].reply_effect, detail, count)
                 for (name, detail), count in sorted(total.gaps.items()))
    counts = ViewCounts(
        hidden_chars=total.chars[HIDDEN], uncertain_chars=total.chars[UNCERTAIN],
        dropped_chars=total.chars[OTHER], dropped_elements=total.dropped_elements,
        dropped_attributes=total.dropped_attributes, tag_chars=total.classes["tag"],
        bidi_chars=total.classes["bidi"], format_chars=total.classes["format"], links=total.links,
        links_unlisted=total.links_unlisted, secrets_masked=secrets_masked,
        quoted_lines=labelled.quoted_lines, visible_chars=labelled.visible_chars,
        visible_letters=labelled.visible_letters, images=total.images,
        style_blocks=total.style_blocks, conditional_comments=total.conditional_comments,
        view_chars=view_chars, view_lines=framed.lines)
    return ViewResult(counts, gaps, warning, truncated, framed.text, framed.open_marker, framed.close_marker,
                      visible_text, "\n".join(total.removed[HIDDEN]), "\n".join(total.removed[UNCERTAIN]),
                      total.unseen, share_parts)
