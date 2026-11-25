#!/usr/bin/env python3
"""mail_frame.py -- the frame around a view, which its content cannot close or imitate (#351).

A view is text a stranger wrote. `frame(text)` puts it between two marker lines and gives
every line of it a fixed prefix, so a reader can tell, line by line, what is content and
what the scanner added:

    MAILSCAN-BEGIN-<16 hex>
    MAILSCAN# [mail-scan: quoted text follows; it is unverified]
    MAILSCAN| first line of the content
    MAILSCAN| second line
    MAILSCAN-END-<16 hex>

TWO PREFIXES. A line behind `MAILSCAN| ` is text of the message, whatever it says. A line
behind `MAILSCAN# ` is one of the fixed lines of `mail_lists.SCANNER_LINES`, written by the
scanner: `frame` gives that prefix to a line that IS one of them, character for character,
and to no other. The message cannot write such a line, because `escape_content` (which the
view applies to every piece of message text) replaces its square brackets and every fixed
line starts with one.

WHAT THE FRAME GUARANTEES, whatever the content holds:

    one line stays one line   every control character except LF and TAB, the line separator
                              and the paragraph separator become LF BEFORE anything else, so
                              nothing a line reader splits on (`str.splitlines` and the
                              like) is left inside a content line
    every line is marked      each content line starts with the prefix, a wrapped line too;
                              a line is wrapped so that it is no longer than
                              `mail_lists.FRAME_WRAP_WIDTH` with its prefix
    the markers are ours      the 16 hex characters are drawn from `secrets` for each
                              message AFTER the content is known, and drawn again if the
                              content holds them, so neither marker line can be in it
    no markup                 `<` and `>` are replaced by two other characters
    our lines are ours        only a fixed line of the scanner stands behind the note
                              prefix; the same words in the message, in other brackets,
                              stand behind the content prefix

Content can still CONTAIN the prefix or a marker-shaped string of its own making. It then
stands inside a content line, behind the real prefix: it marks nothing. The rule
`frame-forgery` blocks such a message; that is the rules' work, not the frame's.

`content_lines(framed)` reads a frame back and refuses a text that is not one; it returns
the lines of the message only. `frame_lines(framed)` returns every line with its kind.

Stdlib only; its data is `mail_lists`. Nothing here opens a file. Importing this module has
no side effects.
"""
from __future__ import annotations

import re
import secrets
from typing import List, NamedTuple, Tuple

import mail_lists

# The content of one line: the wrap width less the prefix every line carries. (The two
# prefixes are of one length.)
CONTENT_WIDTH = mail_lists.FRAME_WRAP_WIDTH - len(mail_lists.FRAME_LINE_PREFIX)
# A wrapped line is broken at a space when there is one in its second half.
_WRAP_SEARCH_FROM = CONTENT_WIDTH // 2
# How often a marker is drawn again when the content holds it. One draw is enough unless
# the content was written knowing the marker, which it cannot be.
_MARKER_DRAWS = 64

_LINE_END = re.compile("\r\n")
# Every control character (C0, DEL, C1) except LF and TAB, and the line and paragraph
# separators. This covers everything `str.splitlines` splits on.
_BREAKING = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f\\u2028\\u2029]")
# A code point that cannot be written as UTF-8.
_SURROGATE = re.compile("[\\ud800-\\udfff]")
_REPLACEMENT_CHARACTER = chr(0xFFFD)


LINE_CONTENT = "content"
LINE_NOTE = "note"
_NOTES = frozenset(mail_lists.SCANNER_LINES)
_BRACKETS = {ord("["): mail_lists.FRAME_LBRACKET_REPLACEMENT, ord("]"): mail_lists.FRAME_RBRACKET_REPLACEMENT}


def escape_content(text: str) -> str:
    """Message text with its square brackets replaced, so no line of it can read as ours."""
    return text.translate(_BRACKETS) if "[" in text or "]" in text else text


class Framed(NamedTuple):
    text: str               # MESSAGE TEXT inside our frame: the only form a model may be given
    open_marker: str        # the first line
    close_marker: str       # the last line
    lines: int              # lines between the two, the scanner's own included


def normalize_lines(text: str) -> str:
    """`text` with LF as its only line break and TAB as its only other control character.

    A CRLF pair is one line break. Every other control character, and the line and
    paragraph separators, become LF. A lone surrogate becomes the replacement character.
    """
    text = _LINE_END.sub("\n", text)
    text = _BREAKING.sub("\n", text)
    return _SURROGATE.sub(_REPLACEMENT_CHARACTER, text)


def _wrap(line: str) -> List[str]:
    """`line` in pieces of at most CONTENT_WIDTH characters."""
    if len(line) <= CONTENT_WIDTH:
        return [line]
    pieces = []
    while len(line) > CONTENT_WIDTH:
        cut = line.rfind(" ", _WRAP_SEARCH_FROM, CONTENT_WIDTH + 1)
        if cut < 0:
            pieces.append(line[:CONTENT_WIDTH])
            line = line[CONTENT_WIDTH:]
        else:
            pieces.append(line[:cut])
            line = line[cut + 1:]
    pieces.append(line)
    return pieces


def _marker(content: str) -> str:
    """Hex characters for the two markers that `content` does not hold."""
    lowered = content.lower()
    for _ in range(_MARKER_DRAWS):
        drawn = secrets.token_hex(mail_lists.FRAME_MARKER_HEX_CHARS // 2)
        if drawn not in lowered:
            return drawn
    raise RuntimeError("no free frame marker")


def frame(text: str) -> Framed:
    """`text` inside a frame. See the module text for what the frame guarantees."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    content = normalize_lines(text)
    content = content.replace("<", mail_lists.FRAME_LT_REPLACEMENT).replace(">", mail_lists.FRAME_GT_REPLACEMENT)
    lines: List[str] = []
    for line in content.split("\n"):
        if line in _NOTES:
            lines.append(mail_lists.FRAME_NOTE_PREFIX + line)
        else:
            lines.extend(mail_lists.FRAME_LINE_PREFIX + piece for piece in _wrap(line))
    while lines and lines[-1] == mail_lists.FRAME_LINE_PREFIX:
        lines.pop()
    drawn = _marker(content)
    opening = mail_lists.FRAME_OPEN_FORMAT % drawn
    closing = mail_lists.FRAME_CLOSE_FORMAT % drawn
    out = [opening]
    out.extend(lines)
    out.append(closing)
    return Framed("\n".join(out) + "\n", opening, closing, len(lines))


_OPEN = re.compile("^" + re.escape(mail_lists.FRAME_OPEN_FORMAT).replace(
    "%s", "([0-9a-f]{%d})" % mail_lists.FRAME_MARKER_HEX_CHARS) + "$")


def frame_lines(framed: str) -> List[Tuple[str, str]]:
    """(kind, text) of every line of a framed text, without its prefix: LINE_CONTENT or LINE_NOTE.

    Raises ValueError for a text that is not a frame of ours: no opening marker, a closing
    marker that is not its pair, a line with neither prefix, a note line that is not one of
    the fixed lines, or anything after the frame.
    """
    if not isinstance(framed, str) or not framed.endswith("\n"):
        raise ValueError("not a frame")
    lines = framed[:-1].split("\n")
    opened = _OPEN.match(lines[0]) if lines else None
    if opened is None or len(lines) < 2:
        raise ValueError("not a frame")
    if lines[-1] != mail_lists.FRAME_CLOSE_FORMAT % opened.group(1):
        raise ValueError("not a frame")
    prefix, note = mail_lists.FRAME_LINE_PREFIX, mail_lists.FRAME_NOTE_PREFIX
    out: List[Tuple[str, str]] = []
    for line in lines[1:-1]:
        if line.startswith(prefix):
            out.append((LINE_CONTENT, line[len(prefix):]))
        elif line.startswith(note) and line[len(note):] in _NOTES:
            out.append((LINE_NOTE, line[len(note):]))
        else:
            raise ValueError("not a frame")
    return out


def content_lines(framed: str) -> List[str]:
    """The lines of the MESSAGE in a framed text, without their prefix. The scanner's own
    lines are left out. Raises ValueError as `frame_lines` does."""
    return [text for kind, text in frame_lines(framed) if kind == LINE_CONTENT]
