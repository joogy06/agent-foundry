#!/usr/bin/env python3
"""mail_parse.py -- one raw message, read under hard bounds and a written selection rule (#351).

`parse(raw, bounds)` takes the bytes of one message and returns a `ParsedMessage`: the text
parts a person would see (decoded), the header facts the later steps need, inventories of
parts, attachments and links, and the named gaps. It reads the message with the standard
`email` package under `policy.default` and decides everything else itself. Nothing here
opens a file, a socket or a link.

BOUNDS, CHECKED FIRST. The size is checked before anything is parsed. Then the structure is
walked once, counting: MIME depth, parts, header lines per header block and the length of a
header line after unfolding. Only then is any header value interpreted, so no header longer
than the bound ever reaches the address or parameter parsers. Over a bound is the gap
`structure-over-bound` with the bound as its detail, and NOTHING ELSE is read: the result
holds that gap and no text, no header fact and no inventory. The parser also bounds its own
link inventory (`mail_lists.MAX_LINKS`).

TWO BOUNDS ARE ABOUT TIME. The standard library parses Content-Type, Content-Disposition
and Content-Transfer-Encoding at a cost that grows much faster than their length, and it
does so while it splits the message, before this module can count anything. So the RAW
bytes are searched first for a line that starts with one of those three names, and a value
of more than `mail_lists.MAX_MIME_HEADER_BYTES` bytes after unfolding stops the parse
(`header-length`) before the standard parser is called. The search does not know where a
header block ends, so such a line in a body counts too. Every header the standard parser
does read is parsed once and kept (`_KeepingPolicy`), however often it is asked for. And
the whole scan has a wall-clock budget (`mail_reuse.Budget`, `mail_lists.SCAN_SECONDS`),
checked inside the loops here: when it runs out the result is `structure-over-bound` with
the detail `time`.

HEADERS THAT MUST BE SINGLE. A missing or repeated From, a From in group syntax or with
other than exactly one mailbox, and a repeated Subject, Reply-To, Content-Type, Return-Path
or Auto-Submitted are each reported in `header_ambiguous` (the block rule
`header-ambiguous`), by header name and reason. A part with two Content-Type,
Content-Transfer-Encoding or Content-Disposition headers is reported the same way: two of
those are read differently by different mail readers.

WHICH PARTS ARE SELECTED. Written out here and never taken from `get_body`:

    not multipart     text/plain or text/html is the one selected part. Any other type is
                      attachment-only mail (`attachment_only`), with nothing selected.
    alternative       the last text/html part, else the last text/plain part. A
                      multipart/related child counts as the type of its root part.
    mixed             every inline text/plain and text/html part, in order; a multipart
                      child is read by its own rule.
    related           the root part only: the part the `start` parameter names, else the
                      first. The root is a text part or an alternative. Every other part
                      is a resource and is never selected.
    signed            the first part, read as a child of mixed. The rest are attachments.
    any other         read as mixed, with the gap `multipart-unknown`.

A text/plain or text/html part with the disposition `attachment`, a text part of any other
type, and every part that is not text are attachments. A message/rfc822 part is the gap
`nested-message`; it is inventoried as one item and is not opened.

WHAT IS AMBIGUOUS. `alternative-duplicate-html`: more than one HTML alternative (the last
is selected). `alternative-other-text`: an alternative of another text type (a calendar
invite, `mail_lists.ALTERNATIVE_ATTACHMENT_TYPES`, is an attachment and no gap).
`alternative-ambiguous`: an alternative with no text/html and no text/plain part, or one
that holds a multipart child other than a related with a text root (a mail reader may show
that child, so what a person sees cannot be told), or one whose body, were dispositions
left out of account, would be a text part marked `attachment` (detail `disposition`: some
mail readers show the last alternative they can display whatever its disposition says).
`related-root-invalid`: no part, a `start` parameter that names no part or more than one,
a root that is neither text nor an alternative, or a `start` that names a part other than
the first (detail `start`: a reader that ignores the parameter shows the first). A
Content-Type or Content-Disposition that gives a parameter more than once in any form (in
any letter case; plain, or in a form of RFC 2231), that gives `boundary`, `charset` or
`start` in a form of RFC 2231 or names one of them twice anywhere in its value, or whose
parameter list does not parse as `; name=value` pairs, is reported in `header_ambiguous`
with the reason `parameter`: this parser reads one value and a mail reader may read another. `parse-defect`: a defect the standard parser records on the From header
(unless it is confined to the display name, see below), on a selected part or its Content-Type and Content-Transfer-Encoding headers, on the message
or on a multipart that holds a selected part; a part that declares a multipart type and
cannot be split into parts; a transfer encoding outside the five standard ones on a
selected part; and any failure of the parser itself. Every gap carries the class
and the reply effect `mail_lists.GAPS` gives it.

A DEFECT ON FROM. The rules rely on the one mailbox of From, so a defect blocks only when
it touches that: the header does not yield exactly one mailbox, or the defect is not
confined to the display name. It is confined to the display name when all of these hold:
the address the parser returned, written alone as `<address>`, parses again to the same
address with no defect; and the header is either that bare address, or holds exactly one
`<...>` pair with exactly that address inside it and nothing after it. Then the result is
the fact `from_name_irregular` (the caution `from-name-irregular`, no hold): an unquoted
period in a name, raw eight-bit text in a name. The mailbox is used as it is and the name
is given as far as it could be recovered. Anything that cannot be classified this way is
`parse-defect`. A name that cannot be decoded is `charset-unsupported` as well.

A FROM ADDRESS THAT IS NOT PLAIN. The address of From is what a reply goes to and what
the sender is counted by. A domain with a character outside ASCII, and a local part or a
domain that holds a character no reader sees or a combining mark, or that NFKC writes
differently, is `parse-defect` (detail `from`): two such addresses look alike and are not
the same.

CHARSETS. A selected part is decoded only under the allowlist of `mail_lists`, with the
usual aliases resolved through `codecs.lookup`; no charset parameter means us-ascii. A part
labelled iso-8859-1 is decoded as windows-1252, as mail readers and browsers do: the bytes
0x80 to 0x9F are curly quotes and dashes there, not control characters. Any
other name is the gap `charset-unsupported` and the part has no text. A decode in which
more than 1% of the characters are replacement characters is the same gap. The same holds
for the From and Subject headers: an encoded word in another charset, or a decoded value
with more than 1% replacement characters.

LINKS. The links of the selected parts are inventoried in document order and numbered from
1 across the message. Each has a kind:

    anchor    the `href` of an <a> element of an HTML part, in the order
              `html.parser.HTMLParser` (convert_charrefs on) reports <a> start tags that
              carry an `href` attribute; the first `href` of a tag is the one read
    text      a match of `mail_lists.URL_IN_TEXT`, with trailing punctuation
              (`mail_lists.URL_TRAILING_PUNCTUATION`) cut off: over the whole text of a
              plain part, and over each run of character data of an HTML part that is not
              inside a <script> or <style> element (text inside an anchor included)

and `occurrence`, its index from 0 among the links of that kind in that part. A step that
walks the same part the same way meets the same links in the same order, and labels the
one it meets with the number given here. Each link is read by `mail_reuse.read_url` (a
`www.` host as if it had a web scheme); the flag `text_mismatch` is added when the text of
an anchor names a host other than the host of its `href`.

WHAT MAY BE RECORDED. Every type below lists its fields in `RECORDABLE_FIELDS` or in
`MEMORY_ONLY_FIELDS`. A recordable field holds an id of ours (p1, a1, l1), a number, a
boolean or a word from a fixed list of `mail_lists`. A memory-only field holds text of the
message: a body, a name, an address, a URL, a host, a declared media type, an extension, a
raw header. `recordable(parsed)` returns the recordable fields as plain data and is the
only form of a parsed message that may be written anywhere.

No exception leaves `parse` for any bytes: an unexpected error is the gap `parse-defect`.

Stdlib only; its one callee is `mail_reuse` (with the data of `mail_lists`). Importing this
module has no side effects.
"""
from __future__ import annotations

import codecs
import email.parser
import email.policy
import html.parser
import re
import unicodedata
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import mail_lists
import mail_reuse

GAP_STRUCTURE_OVER_BOUND = "structure-over-bound"
GAP_PARSE_DEFECT = "parse-defect"
GAP_CHARSET_UNSUPPORTED = "charset-unsupported"
GAP_ALTERNATIVE_AMBIGUOUS = "alternative-ambiguous"
GAP_ALTERNATIVE_DUPLICATE_HTML = "alternative-duplicate-html"
GAP_ALTERNATIVE_OTHER_TEXT = "alternative-other-text"
GAP_RELATED_ROOT_INVALID = "related-root-invalid"
GAP_NESTED_MESSAGE = "nested-message"
GAP_MULTIPART_UNKNOWN = "multipart-unknown"
# The gaps this module can report. Each is a name of mail_lists.GAPS.
PARSE_GAPS = (GAP_STRUCTURE_OVER_BOUND, GAP_PARSE_DEFECT, GAP_CHARSET_UNSUPPORTED,
              GAP_ALTERNATIVE_AMBIGUOUS, GAP_ALTERNATIVE_DUPLICATE_HTML, GAP_ALTERNATIVE_OTHER_TEXT,
              GAP_RELATED_ROOT_INVALID, GAP_NESTED_MESSAGE, GAP_MULTIPART_UNKNOWN)

DEFAULT_CHARSET = "us-ascii"
REPLACEMENT_CHARACTER = "\ufffd"


# --------------------------------------------------------------------------------------
# The parsed message
# --------------------------------------------------------------------------------------

class Bounds(NamedTuple):
    max_bytes: int = mail_lists.MAX_BYTES_DEFAULT
    max_depth: int = mail_lists.MAX_MIME_DEPTH
    max_parts: int = mail_lists.MAX_PARTS
    max_header_lines: int = mail_lists.MAX_HEADER_LINES
    max_header_line_bytes: int = mail_lists.MAX_HEADER_LINE_BYTES
    max_links: int = mail_lists.MAX_LINKS
    max_mime_header_bytes: int = mail_lists.MAX_MIME_HEADER_BYTES
    max_seconds: Optional[float] = mail_lists.SCAN_SECONDS      # None: no wall-clock budget


DEFAULT_BOUNDS = Bounds()


class GapItem(NamedTuple):
    name: str               # a name of mail_lists.GAPS
    gap_class: str          # block or caution, from mail_lists.GAPS
    reply_effect: str       # held or none, from mail_lists.GAPS
    detail: str             # a word of mail_lists.GAP_DETAILS: where the gap was met
    count: int


class HeaderAmbiguity(NamedTuple):
    header: str             # a name of mail_lists.AMBIGUOUS_HEADER_NAMES
    reason: str             # a word of mail_lists.HEADER_REASONS
    count: int              # the header blocks in which it was met


class PartItem(NamedTuple):
    part_id: str            # p1, p2, ... in document order
    media_type: str         # the declared type as a word of ours (see _media_type_word)
    role: str               # a word of mail_lists.PART_ROLES
    depth: int              # 1 for the message itself


class AttachmentItem(NamedTuple):
    attachment_id: str      # a1, a2, ...
    part_id: str
    role: str               # a word of mail_lists.ATTACHMENT_ROLES
    media_type: str         # the declared type as a word of ours
    extension_class: str    # a word of mail_lists.EXTENSION_CLASSES
    signature: str          # a name of mail_lists.SIGNATURE_NAMES, or "none"
    size: int               # decoded bytes; 0 for a nested message, which is not opened
    declared_media_type: str    # MEMORY ONLY: the declared type as the sender wrote it
    extension: str          # MEMORY ONLY: the extension of the declared name, lower case, or ""


class LinkItem(NamedTuple):
    link_id: str            # l1, l2, ...
    number: int             # the N of the view's link token, from 1 across the message
    part_id: str            # the selected part that holds it
    kind: str               # a word of mail_lists.LINK_KINDS
    occurrence: int         # from 0 among the links of this kind in this part
    flags: Tuple[str, ...]  # words of mail_lists.LINK_FLAGS
    url: str                # MEMORY ONLY: the link as it was written
    host: str               # MEMORY ONLY: its host, as mail_reuse.read_url read it


class SelectedPart(NamedTuple):
    part_id: str
    subtype: str            # plain or html
    charset: str            # the allowlist name it was decoded under; "" when unsupported
    replaced: int           # replacement characters in the decoded text
    text: str               # MEMORY ONLY: the decoded text; "" when the charset is unsupported


class HeaderFacts(NamedTuple):
    reply_to_present: bool
    return_path: str        # a word of mail_lists.RETURN_PATH_VALUES
    auto_submitted: str     # a word of mail_lists.AUTO_SUBMITTED_VALUES
    auto_response_suppress: bool
    list_id_present: bool
    list_unsubscribe_present: bool
    precedence: str         # a word of mail_lists.PRECEDENCE_VALUES
    authentication_results_count: int
    from_name_irregular: bool   # a defect on From confined to the display name (a caution)
    # MEMORY ONLY from here. The four From fields are None unless the message has exactly
    # one From header naming exactly one mailbox.
    from_name: Optional[str]        # the display name, decoded; "" when there is none
    from_address: Optional[str]     # the address as written (addr-spec)
    from_local: Optional[str]       # its local part, unquoted
    from_domain: Optional[str]      # its domain
    subject: Optional[str]          # decoded; None when absent or repeated
    authentication_results: Tuple[str, ...]     # every such header, in order, unfolded, unparsed


class ParsedMessage(NamedTuple):
    over_bound: str         # "" or the bound (mail_lists.PARSE_BOUND_NAMES) that stopped the parse
    attachment_only: bool   # not multipart and not text: image-only or attachment-only mail
    gaps: Tuple[GapItem, ...]
    header_ambiguous: Tuple[HeaderAmbiguity, ...]
    parts: Tuple[PartItem, ...]
    attachments: Tuple[AttachmentItem, ...]
    links: Tuple[LinkItem, ...]
    selected: Tuple[SelectedPart, ...]      # in document order
    headers: HeaderFacts


# type name -> the fields that hold text of the message and must never be written anywhere.
MEMORY_ONLY_FIELDS: Dict[str, Tuple[str, ...]] = {
    "GapItem": (),
    "HeaderAmbiguity": (),
    "PartItem": (),
    "AttachmentItem": ("declared_media_type", "extension"),
    "LinkItem": ("url", "host"),
    "SelectedPart": ("text",),
    "HeaderFacts": ("from_name", "from_address", "from_local", "from_domain", "subject",
                    "authentication_results"),
    "ParsedMessage": (),
}
_TYPES = (GapItem, HeaderAmbiguity, PartItem, AttachmentItem, LinkItem, SelectedPart, HeaderFacts,
          ParsedMessage)
# type name -> every other field: ids, numbers, booleans and words of ours.
RECORDABLE_FIELDS: Dict[str, Tuple[str, ...]] = {
    cls.__name__: tuple(f for f in cls._fields if f not in MEMORY_ONLY_FIELDS[cls.__name__])
    for cls in _TYPES}

_NO_HEADERS = HeaderFacts(False, mail_lists.VALUE_ABSENT, mail_lists.VALUE_ABSENT, False, False,
                          False, mail_lists.VALUE_ABSENT, 0, False, None, None, None, None, None, ())


def _plain(value: Any) -> Any:
    """`value` as plain data, with the memory-only fields of every item left out."""
    name = type(value).__name__
    if name in RECORDABLE_FIELDS and isinstance(value, tuple):
        return {field: _plain(getattr(value, field)) for field in RECORDABLE_FIELDS[name]}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def recordable(parsed: ParsedMessage) -> Dict[str, Any]:
    """The recordable fields of a parsed message as plain data (dicts, lists, words, numbers).

    It holds no text of the message. This is the only form of a parsed message that may be
    written to a record, a sheet or an output.
    """
    return _plain(parsed)


# --------------------------------------------------------------------------------------
# Small readers
# --------------------------------------------------------------------------------------

_SURROGATES = re.compile("[\ud800-\udfff]")
_CHARSET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+\-]{0,39}")
_EXTENSION = re.compile(r"[a-z0-9]{1,16}")
# An encoded word, as loosely as the standard parser reads one (white space allowed inside).
_ENCODED_WORD = re.compile(r"=\?([^?]*)\?[bBqQ]\?[^?]*\?=")
_LINE_BREAKS = re.compile(r"[\r\n]+")

# codec name (as codecs.lookup reports it) -> the allowlist name
_ALLOWED_CODECS = {codecs.lookup(name).name: name for name in mail_lists.CHARSET_ALLOWLIST}

_KNOWN_MEDIA_TYPES = frozenset(mail_lists.COMMON_MEDIA_TYPES) | frozenset(
    mail_lists.DANGEROUS_MEDIA_TYPES) | frozenset(mail_lists.GENERIC_MEDIA_TYPES) | frozenset(
        mail_lists.ACTIVE_CONTENT_MEDIA_TYPES) | frozenset(
        media for row in mail_lists.SIGNATURES for media in row.media_types)
_KNOWN_EXTENSIONS = frozenset(ext for row in mail_lists.SIGNATURES for ext in row.extensions)
_BODY_TYPES = {"text/plain": mail_lists.SELECTED_PLAIN, "text/html": mail_lists.SELECTED_HTML}
_RAW_TEXT_ELEMENTS = ("script", "style")


def _clean(text: str) -> str:
    """`text` with bytes the header parser could not decode read as UTF-8, else replaced."""
    if not _SURROGATES.search(text):
        return text
    try:
        text = text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeError:
        pass
    return _SURROGATES.sub(REPLACEMENT_CHARACTER, text)


def _unfold(value: str) -> str:
    return _clean(_LINE_BREAKS.sub("", value))


def allowed_charset(name: Any) -> Optional[str]:
    """The allowlist name `name` is an alias of, or None. Never raises."""
    if not isinstance(name, str) or not _CHARSET_NAME.fullmatch(name):
        return None
    try:
        return _ALLOWED_CODECS.get(codecs.lookup(name).name)
    except Exception:  # noqa: BLE001 - a name no codec answers to is not on the list
        return None


def _too_many_replaced(text: str) -> bool:
    return text.count(REPLACEMENT_CHARACTER) > mail_lists.CHARSET_REPLACEMENT_MAX_RATIO * len(text)


def _media_type_word(declared: str) -> str:
    """A declared media type as a word of ours: itself when listed, else its main type, else `other`."""
    if declared in _KNOWN_MEDIA_TYPES:
        return declared
    main = declared.partition("/")[0]
    if main in mail_lists.MEDIA_MAIN_TYPES:
        return main + "/" + mail_lists.MEDIA_TYPE_OTHER
    return mail_lists.MEDIA_TYPE_OTHER


def read_extension(filename: Any) -> Tuple[str, str]:
    """(extension class, extension) of a declared file name. The name itself is not kept.

    Hidden characters, and the trailing dots and spaces a file system drops, are removed
    first; the extension is what follows the last dot.
    """
    if not isinstance(filename, str) or not filename:
        return mail_lists.EXTENSION_NONE, ""
    name = mail_reuse.STRIPPED.strip(_clean(filename))[0].strip().rstrip(". \t\r\n\x00")
    if "." not in name:
        return mail_lists.EXTENSION_NONE, ""
    extension = name.rsplit(".", 1)[1].lower()
    if not _EXTENSION.fullmatch(extension):
        return mail_lists.EXTENSION_OTHER, ""
    if extension in mail_lists.DANGEROUS_EXTENSIONS:
        return mail_lists.EXTENSION_DANGEROUS, extension
    if extension in _KNOWN_EXTENSIONS:
        return mail_lists.EXTENSION_KNOWN, extension
    return mail_lists.EXTENSION_OTHER, extension


def read_signature(data: bytes) -> str:
    """The name of the listed signature `data` starts with, or "none"."""
    for row in mail_lists.SIGNATURES:
        if any(data.startswith(leading) for leading in row.leading):
            return row.name
    return mail_lists.SIGNATURE_NONE


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------

def text_urls(text: str) -> List[str]:
    """Every URL typed in `text`, in order, with trailing punctuation cut off."""
    out = []
    for match in mail_lists.URL_IN_TEXT.finditer(text):
        out.append(match.group(0).rstrip(mail_lists.URL_TRAILING_PUNCTUATION))
    return out


def _read_link(url: str) -> mail_reuse.UrlFacts:
    if url[:4].lower() == "www.":
        return mail_reuse.read_url("http://" + url)
    return mail_reuse.read_url(url)


def _site(host: str) -> str:
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _names_another_host(anchor_text: str, host: str) -> bool:
    """Whether the text of an anchor names a host other than `host`."""
    named = set()
    for url in text_urls(anchor_text):
        facts = _read_link(url)
        if facts.host:
            named.add(_site(facts.host))
    rest = mail_lists.URL_IN_TEXT.sub(" ", anchor_text)
    for match in mail_lists.BARE_HOST.finditer(rest):
        named.add(_site(match.group(0)))
    return any(name != _site(host) for name in named)


class _LinkFinder(html.parser.HTMLParser):
    """Collects the links of one HTML part in document order (see LINKS in the module text)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: List[Tuple[str, str, List[str]]] = []      # (kind, url, anchor text pieces)
        self._anchor: Optional[List[str]] = None
        self._anchor_chars = 0
        self._raw_text: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        if tag in _RAW_TEXT_ELEMENTS:
            self._raw_text = tag
        if tag != "a":
            return
        self._anchor = None
        for name, value in attrs:
            if name == "href":
                self._anchor = []
                self._anchor_chars = 0
                self.found.append((mail_lists.LINK_ANCHOR, value or "", self._anchor))
                break

    def handle_endtag(self, tag: str) -> None:
        if tag == self._raw_text:
            self._raw_text = None
        if tag == "a":
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._raw_text is not None:
            return
        for url in text_urls(data):
            self.found.append((mail_lists.LINK_TEXT, url, []))
        if self._anchor is not None and self._anchor_chars < mail_lists.ANCHOR_TEXT_MAX_CHARS:
            piece = data[:mail_lists.ANCHOR_TEXT_MAX_CHARS - self._anchor_chars]
            self._anchor.append(piece)
            self._anchor_chars += len(piece)


def find_links(subtype: str, text: str) -> List[Tuple[str, str, str]]:
    """(kind, url, anchor text) for every link of one selected part, in document order."""
    if subtype != mail_lists.SELECTED_HTML:
        return [(mail_lists.LINK_TEXT, url, "") for url in text_urls(text)]
    finder = _LinkFinder()
    finder.feed(text)
    finder.close()
    return [(kind, url, "".join(pieces)) for kind, url, pieces in finder.found]


# --------------------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------------------

_MULTIPART = "multipart"
_MESSAGE = "message"
_TEXT = "text"
_LEAF = "leaf"


class _OverBound(Exception):
    def __init__(self, bound: str) -> None:
        Exception.__init__(self, bound)
        self.bound = bound


class _Node:
    __slots__ = ("part", "depth", "parent", "children", "items", "names", "kind", "media_type",
                 "main_type", "subtype", "role", "part_id", "opened")

    def __init__(self, part: Any, depth: int, parent: Optional["_Node"]) -> None:
        self.part = part
        self.depth = depth
        self.parent = parent
        self.children: List[_Node] = []
        self.items: List[Tuple[str, str]] = []      # the raw header lines, unfolding not applied
        self.names: Dict[str, int] = {}             # lower-case header name -> how many
        self.kind = _LEAF
        self.media_type = ""
        self.main_type = ""
        self.subtype = ""
        self.role = ""
        self.part_id = ""
        # False for a part inside a nested message: counted against the bounds, never read.
        self.opened = parent is None

    def raw(self, name: str) -> List[str]:
        """Every value of the header `name`, in order, unfolded."""
        return [_unfold(value) for key, value in self.items if key.lower() == name]


def _param(part: Any, name: str) -> Optional[str]:
    value = part.get_param(name, None)
    if isinstance(value, tuple):
        value = value[2]
    return _clean(value) if isinstance(value, str) else None


def _defect_is_in_the_name_only(raw_value: str, address: str) -> bool:
    """Whether a defective From header is defective only in its display name.

    `raw_value` is the header as written (unfolded) and `address` the addr-spec the parser
    returned for its one mailbox. See A DEFECT ON FROM in the module text.
    """
    again = email.policy.default.header_factory("From", "<" + address + ">")
    found = again.addresses
    if again.defects or len(found) != 1 or found[0].addr_spec != address:
        return False
    value = raw_value.strip()
    if value == address:
        return True
    if value.count("<") != 1 or value.count(">") != 1:
        return False
    opening, closing = value.index("<"), value.index(">")
    return opening < closing and value[opening + 1:closing] == address and not value[closing + 1:].strip()


def _content_id(value: Optional[str]) -> str:
    return (value or "").strip().strip("<>").strip()


# A section suffix of any length (fix round 3, P2: `*00000*` is a section too); one with a
# leading zero other than `0` itself, or of more than SECTION_MAX_DIGITS digits, is ambiguous.
_SECTION = re.compile(r"\*([0-9]+)\*?$|\*$")
SECTION_MAX_DIGITS = 3
_TOKEN = r"[A-Za-z0-9!#$%&'*+.^_`|~-]+"
_PLAIN_TOKEN = re.compile(_TOKEN)
# One parameter: `; name=value`, the value a quoted string or a run with no white space,
# semicolon or quote in it. (A semicolon with nothing after it may end the list.)
_PARAMETER = re.compile(r"[ \t]*;[ \t]*(?:(%s)[ \t]*=[ \t]*(\"(?:[^\"\\]|\\.)*\"|[^ \t;\"]+)[ \t]*)?" % _TOKEN)
# A value that a reader may decode instead of taking as written: an encoded word, or base64
_DECODABLE = re.compile(r"=\?|^[A-Za-z0-9+/]+={1,2}$")
# A deciding parameter named anywhere in the value, inside a quoted string too.
_DECIDING = {name: re.compile(r"(?<![A-Za-z0-9!#$%%&'*+.^_`|~-])%s[ \t]*(?:\*[0-9]*\*?)?[ \t]*=" % name, re.IGNORECASE)
             for name in mail_lists.SINGLE_PARAMETERS}


def _repeated_parameters(value: str) -> Optional[List[str]]:
    """The parameter names a Content-Type or Content-Disposition value gives ambiguously; None
    when its parameter list does not parse as `; name=value` pairs.

    Read from the header as written, without regard to letter case. A name is ambiguous
    when it occurs more than once in any form: plain twice, the plain form beside an RFC
    2231 form (`name*=`, `name*0=`), the same section twice. The sections of one continued
    parameter (`name*0`, `name*1`) are one parameter. A parameter that DECIDES what is read
    (`mail_lists.SINGLE_PARAMETERS`) is ambiguous also in any RFC 2231 form (a reader that
    does not join sections reads another value), and when its name and an equals sign stand
    more than once anywhere in the value, a quoted string included (a reader that does not
    follow a backslash in a quoted string ends the string early).
    """
    value = value.replace("\r", " ").replace("\n", " ")
    position = value.find(";")
    if position < 0:
        position = len(value)
    if '"' in value[:position] or "(" in value[:position] or ")" in value[:position]:
        return None                     # a quote, or a comment, in the media type itself
    seen: Dict[str, List[str]] = {}
    odd: List[str] = []
    while position < len(value):
        match = _PARAMETER.match(value, position)
        if match is None:
            return None
        if match.group(1) is None:
            if value[match.end():].strip(" \t"):
                return None             # a semicolon followed by something that is no parameter
            break
        name = match.group(1).lower()
        section = _SECTION.search(name)
        base = name[:section.start()] if section else name
        # "" the plain form, "*" the extended one, "*N" a section (extended or not)
        seen.setdefault(base, []).append("" if not section else (section.group(0).rstrip("*") or "*"))
        digits = section.group(1) if section else None
        if digits is not None and (len(digits) > SECTION_MAX_DIGITS or (digits.startswith("0") and digits != "0")):
            odd.append(base)            # fix round 3 (P2): a section number no two readers count alike
        written = match.group(2)
        if not written.startswith('"') and ("(" in written or ")" in written):
            return None                 # fix round 3 (P1): a comment in the list is read by some readers only
            # (a parenthesis inside a quoted string is text, as in `filename="Invoice (1).pdf"`)
        if base in mail_lists.SINGLE_PARAMETERS:
            # fix round 3 (P1): a deciding value is a plain token, or a quoted string with no
            # backslash and nothing a reader might decode (an encoded word, base64)
            inner = written[1:-1] if written.startswith('"') else written
            if (not written.startswith('"') and _PLAIN_TOKEN.fullmatch(written) is None) or "\\" in inner or (
                    _DECODABLE.search(inner) is not None):
                odd.append(base)
        position = match.end()
    repeated = sorted(set(odd))
    for name, marks in seen.items():
        if name in repeated:
            continue
        if len(marks) > 1 and (len(set(marks)) != len(marks) or "" in marks or "*" in marks):
            repeated.append(name)
        elif name in mail_lists.SINGLE_PARAMETERS and marks != [""]:
            repeated.append(name)
    for name, pattern in _DECIDING.items():
        if name not in repeated and len(pattern.findall(value)) > 1:
            repeated.append(name)
    return sorted(repeated)


def plain_address(local: Optional[str], domain: Optional[str]) -> bool:
    """Whether a From address is one a reply can safely go to (see the module text)."""
    if not local or not domain or not domain.isascii():
        return False
    for text in (local, domain):
        if unicodedata.normalize("NFKC", text) != text:
            return False
        for char in text:
            if char <= "\x7f":
                if char <= " " or char == "\x7f":
                    return False
            elif char in mail_reuse.INVISIBLE or unicodedata.category(char)[0] in "MZC":
                return False
    return True


class _Reader:
    def __init__(self, bounds: Bounds, budget: Any = mail_reuse.NO_BUDGET) -> None:
        self.bounds = bounds
        self.budget = budget
        self.gaps: Dict[Tuple[str, str], int] = {}
        self.ambiguous: Dict[Tuple[str, str], int] = {}
        self.picked: List[Tuple[_Node, List[_Node]]] = []
        self.attachment_only = False

    def gap(self, name: str, detail: str = mail_lists.DETAIL_NONE, count: int = 1) -> None:
        self.gaps[(name, detail)] = self.gaps.get((name, detail), 0) + count

    def gap_items(self) -> Tuple[GapItem, ...]:
        return tuple(GapItem(name, mail_lists.GAPS[name].gap_class, mail_lists.GAPS[name].reply_effect,
                             detail, count) for (name, detail), count in self.gaps.items())

    # ---- bounds and the tree ----------------------------------------------------------

    def tree(self, message: Any) -> List[_Node]:
        """Every part in document order, or _OverBound. Reads no header value."""
        bounds = self.bounds
        order: List[_Node] = []
        stack = [_Node(message, 1, None)]
        while stack:
            self.budget.check_now()
            node = stack.pop()
            if len(order) >= bounds.max_parts:
                raise _OverBound(mail_lists.BOUND_PARTS)
            if node.depth > bounds.max_depth:
                raise _OverBound(mail_lists.BOUND_DEPTH)
            node.items = [(str(key), str(value)) for key, value in node.part.raw_items()]
            if len(node.items) > bounds.max_header_lines:
                raise _OverBound(mail_lists.BOUND_HEADER_LINES)
            for key, value in node.items:
                unfolded = len(key) + 2 + len(value) - value.count("\r") - value.count("\n")
                if unfolded > bounds.max_header_line_bytes:
                    raise _OverBound(mail_lists.BOUND_HEADER_LENGTH)
                lowered = key.lower()
                if lowered in mail_lists.MIME_HEADER_NAMES and unfolded - len(key) - 2 > bounds.max_mime_header_bytes:
                    raise _OverBound(mail_lists.BOUND_HEADER_LENGTH)
                node.names[lowered] = node.names.get(lowered, 0) + 1
            order.append(node)
            if node.part.is_multipart():
                node.children = [_Node(child, node.depth + 1, node) for child in node.part.get_payload()]
                stack.extend(reversed(node.children))
        return order

    def classify(self, node: _Node) -> None:
        part = node.part
        node.media_type = part.get_content_type()
        node.main_type, _, node.subtype = node.media_type.partition("/")
        has_parts = part.is_multipart()
        if node.parent is not None:
            node.opened = node.parent.opened and node.parent.kind == _MULTIPART
        if node.main_type == "multipart" and has_parts:
            node.kind = _MULTIPART
        elif node.main_type == "message" and node.subtype in mail_lists.NESTED_MESSAGE_SUBTYPES:
            node.kind = _MESSAGE
        elif (not has_parts and node.media_type in _BODY_TYPES
              and (node.parent is None or part.get_content_disposition() != "attachment")):
            node.kind = _TEXT
        else:
            node.kind = _LEAF

    # ---- headers ----------------------------------------------------------------------

    def note_ambiguous(self, header: str, reason: str) -> None:
        self.ambiguous[(header, reason)] = self.ambiguous.get((header, reason), 0) + 1

    def single_headers(self, order: Sequence[_Node]) -> None:
        root = order[0]
        for header in mail_lists.SINGLE_HEADERS:
            if root.names.get(header, 0) > 1:
                self.note_ambiguous(header, mail_lists.HEADER_REPEATED)
        if not root.names.get("from"):
            self.note_ambiguous("from", mail_lists.HEADER_MISSING)
        for node in order:
            if not node.opened:
                continue
            for header in mail_lists.SINGLE_PART_HEADERS:
                if node.names.get(header, 0) > 1 and not (node is root and header in mail_lists.SINGLE_HEADERS):
                    self.note_ambiguous(header, mail_lists.HEADER_REPEATED)
            for header in ("content-type", "content-disposition"):
                for value in node.raw(header):
                    if _repeated_parameters(value) != []:
                        self.note_ambiguous(header, mail_lists.HEADER_PARAMETER)

    def header_charsets(self, root: _Node, texts: Sequence[Optional[str]]) -> None:
        """Encoded words of From and Subject outside the allowlist, and badly decoded values."""
        for header in ("from", "subject"):
            for value in root.raw(header):
                for match in _ENCODED_WORD.finditer(value):
                    if allowed_charset(match.group(1).split("*", 1)[0].strip()) is None:
                        self.gap(GAP_CHARSET_UNSUPPORTED, mail_lists.DETAIL_HEADER)
        for text in texts:
            if text and _too_many_replaced(text):
                self.gap(GAP_CHARSET_UNSUPPORTED, mail_lists.DETAIL_HEADER)

    def header_facts(self, root: _Node) -> HeaderFacts:
        message = root.part
        name = address = local = domain = subject = None
        name_irregular = False
        if root.names.get("from") == 1:
            header = message["from"]
            groups = header.groups
            if any(group.display_name is not None for group in groups):
                self.note_ambiguous("from", mail_lists.HEADER_GROUP)
            else:
                addresses = [entry for group in groups for entry in group.addresses]
                if len(addresses) == 1 and addresses[0].username and addresses[0].domain:
                    name = _clean(addresses[0].display_name or "")
                    address = _clean(addresses[0].addr_spec)
                    local = _clean(addresses[0].username)
                    domain = _clean(addresses[0].domain)
                else:
                    self.note_ambiguous("from", mail_lists.HEADER_MAILBOXES)
            if address is not None and not plain_address(local, domain):
                self.gap(GAP_PARSE_DEFECT, mail_lists.DETAIL_FROM)
            if header.defects:
                values = root.raw("from")
                if address is not None and _defect_is_in_the_name_only(values[0], address):
                    name_irregular = True
                else:
                    self.gap(GAP_PARSE_DEFECT, mail_lists.DETAIL_FROM, len(header.defects))
        if root.names.get("subject") == 1:
            subject = _clean(str(message["subject"]))
        self.header_charsets(root, (name, subject))

        return_paths = ["".join(value.split()) for value in root.raw("return-path")]
        if not return_paths:
            return_path = mail_lists.VALUE_ABSENT
        elif "<>" in return_paths:
            return_path = mail_lists.RETURN_PATH_NULL
        else:
            return_path = mail_lists.RETURN_PATH_ADDRESS
        submitted = [value.split(";", 1)[0].strip().lower() for value in root.raw("auto-submitted")]
        if not submitted:
            auto_submitted = mail_lists.VALUE_ABSENT
        elif all(value == mail_lists.AUTO_SUBMITTED_NO for value in submitted):
            auto_submitted = mail_lists.AUTO_SUBMITTED_NO
        else:
            auto_submitted = mail_lists.AUTO_SUBMITTED_AUTO
        precedences = [value.strip().lower() for value in root.raw("precedence")]
        # what older auto-responders write: a Precedence value, or a header of their own
        if (any(value in mail_lists.AUTO_REPLY_PRECEDENCE_VALUES for value in precedences)
                or any(root.names.get(name) for name in mail_lists.AUTO_REPLY_HEADERS)):
            auto_submitted = mail_lists.AUTO_SUBMITTED_AUTO
        listed = [value for value in precedences if value in mail_lists.LIST_PRECEDENCE_VALUES]
        if not precedences:
            precedence = mail_lists.VALUE_ABSENT
        else:
            precedence = listed[0] if listed else mail_lists.VALUE_OTHER
        results = tuple(value.strip() for value in root.raw("authentication-results"))
        return HeaderFacts(
            reply_to_present=bool(root.names.get("reply-to")),
            return_path=return_path,
            auto_submitted=auto_submitted,
            auto_response_suppress=bool(root.names.get("x-auto-response-suppress")),
            list_id_present=bool(root.names.get("list-id")),
            list_unsubscribe_present=bool(root.names.get("list-unsubscribe")),
            precedence=precedence,
            authentication_results_count=len(results),
            from_name_irregular=name_irregular,
            from_name=name, from_address=address, from_local=local, from_domain=domain,
            subject=subject, authentication_results=results)

    # ---- part selection ---------------------------------------------------------------

    def pick(self, node: _Node, path: List[_Node]) -> None:
        node.role = mail_lists.ROLE_SELECTED
        self.picked.append((node, path))

    def aside(self, node: _Node, text_role: str, leaf_role: str) -> None:
        """Give `node` and everything under it a role without selecting anything."""
        if node.kind == _MULTIPART:
            node.role = mail_lists.ROLE_CONTAINER
            for child in node.children:
                self.aside(child, text_role, leaf_role)
        elif node.kind == _MESSAGE:
            self.gap(GAP_NESTED_MESSAGE)
            node.role = mail_lists.ROLE_NESTED_MESSAGE
        elif node.kind == _TEXT:
            node.role = text_role
        else:
            node.role = leaf_role

    def select(self, node: _Node, path: List[_Node]) -> None:
        """Apply the written rule of the multipart `node`."""
        node.role = mail_lists.ROLE_CONTAINER
        path = path + [node]
        if node.subtype == "alternative":
            self.alternative(node, path)
        elif node.subtype == "related":
            self.related(node, path)
        elif node.subtype == "signed":
            for index, child in enumerate(node.children):
                if index == 0:
                    self.mixed_child(child, path)
                else:
                    self.aside(child, mail_lists.ROLE_ATTACHMENT, mail_lists.ROLE_ATTACHMENT)
        else:
            if node.subtype not in mail_lists.MULTIPART_RULES:
                self.gap(GAP_MULTIPART_UNKNOWN)
            for child in node.children:
                self.mixed_child(child, path)

    def mixed_child(self, child: _Node, path: List[_Node]) -> None:
        if child.kind == _TEXT:
            self.pick(child, path)
        elif child.kind == _MULTIPART:
            self.select(child, path)
        else:
            self.aside(child, mail_lists.ROLE_ATTACHMENT, mail_lists.ROLE_ATTACHMENT)

    def related_root(self, node: _Node) -> Optional[_Node]:
        """The root part of a related: the one `start` names, else the first. None when there is none."""
        if not node.children:
            return None
        start = _param(node.part, "start")
        if start is None:
            return node.children[0]
        wanted = _content_id(start)
        named = [child for child in node.children
                 if wanted and any(_content_id(value) == wanted for value in child.raw("content-id"))]
        if len(named) != 1:
            return None
        if named[0] is not node.children[0]:
            # a mail reader that ignores `start` shows the first part, not this one
            self.gap(GAP_RELATED_ROOT_INVALID, mail_lists.DETAIL_START)
        return named[0]

    def related(self, node: _Node, path: List[_Node]) -> None:
        root = self.related_root(node)
        usable = root is not None and (
            root.kind == _TEXT or (root.kind == _MULTIPART and root.subtype == "alternative"))
        if not usable:
            self.gap(GAP_RELATED_ROOT_INVALID)
        for child in node.children:
            if child is root and usable:
                if child.kind == _TEXT:
                    self.pick(child, path)
                else:
                    self.select(child, path)
            else:
                self.aside(child, mail_lists.ROLE_RESOURCE, mail_lists.ROLE_RESOURCE)

    def alternative(self, node: _Node, path: List[_Node]) -> None:
        candidates: List[Tuple[str, _Node, _Node]] = []     # (plain or html, the child, its text part)
        every: List[Tuple[str, bool]] = []      # (plain or html, marked as an attachment), in order
        ambiguous = False
        for child in node.children:
            if child.kind == _LEAF and child.media_type in _BODY_TYPES and not child.part.is_multipart():
                every.append((_BODY_TYPES[child.media_type], True))
            if child.kind == _TEXT:
                every.append((_BODY_TYPES[child.media_type], False))
                candidates.append((_BODY_TYPES[child.media_type], child, child))
            elif child.kind == _MULTIPART and child.subtype == "related":
                root = self.related_root(child)
                if root is not None and root.kind == _TEXT:
                    every.append((_BODY_TYPES[root.media_type], False))
                    candidates.append((_BODY_TYPES[root.media_type], child, root))
                    continue
                if root is not None and root.kind == _MULTIPART:
                    ambiguous = True
                else:
                    self.gap(GAP_RELATED_ROOT_INVALID)
                self.aside(child, mail_lists.ROLE_RESOURCE, mail_lists.ROLE_RESOURCE)
            elif child.kind == _MULTIPART:
                ambiguous = True
                self.aside(child, mail_lists.ROLE_UNSELECTED, mail_lists.ROLE_ATTACHMENT)
            else:
                if (child.main_type == "text" and child.media_type not in _BODY_TYPES
                        and child.media_type not in mail_lists.ALTERNATIVE_ATTACHMENT_TYPES):
                    self.gap(GAP_ALTERNATIVE_OTHER_TEXT)
                self.aside(child, mail_lists.ROLE_ATTACHMENT, mail_lists.ROLE_ATTACHMENT)
        htmls = [entry for entry in candidates if entry[0] == mail_lists.SELECTED_HTML]
        plains = [entry for entry in candidates if entry[0] == mail_lists.SELECTED_PLAIN]
        if len(htmls) > 1:
            self.gap(GAP_ALTERNATIVE_DUPLICATE_HTML)
        chosen = htmls[-1] if htmls else (plains[-1] if plains else None)
        if chosen is None or ambiguous:
            self.gap(GAP_ALTERNATIVE_AMBIGUOUS)
        # The body a reader would show if it left dispositions out of account: the last
        # HTML alternative, else the last plain one. When that one is marked as an
        # attachment, this parser and such a reader show different bodies.
        wanted = [entry for entry in every if entry[0] == mail_lists.SELECTED_HTML] or every
        if wanted and wanted[-1][1]:
            self.gap(GAP_ALTERNATIVE_AMBIGUOUS, mail_lists.DETAIL_DISPOSITION)
        for entry in candidates:
            _subtype, child, target = entry
            if child is not target:
                child.role = mail_lists.ROLE_CONTAINER
                for other in child.children:
                    if other is not target:
                        self.aside(other, mail_lists.ROLE_RESOURCE, mail_lists.ROLE_RESOURCE)
            if entry is chosen:
                self.pick(target, path if child is target else path + [child])
            else:
                target.role = mail_lists.ROLE_UNSELECTED

    # ---- decoding and inventories -----------------------------------------------------

    def decode(self, node: _Node) -> SelectedPart:
        part = node.part
        encodings = node.raw("content-transfer-encoding")
        encoding = encodings[0].strip().lower() if encodings else mail_lists.TRANSFER_ENCODINGS[0]
        if encoding not in mail_lists.TRANSFER_ENCODINGS:
            self.gap(GAP_PARSE_DEFECT, mail_lists.DETAIL_TRANSFER_ENCODING)
        data = part.get_payload(decode=True)
        if not isinstance(data, bytes):
            data = b""
        declared = _param(part, "charset") if node.names.get("content-type") else None
        charset = allowed_charset(DEFAULT_CHARSET if declared is None else declared)
        subtype = _BODY_TYPES[node.media_type]
        if charset is None:
            self.gap(GAP_CHARSET_UNSUPPORTED, mail_lists.DETAIL_BODY)
            return SelectedPart(node.part_id, subtype, "", 0, "")
        # iso-8859-1 as windows-1252: what every mail reader and browser does with that label
        text = data.decode("cp1252" if charset == "iso-8859-1" else charset, "replace")
        if _too_many_replaced(text):
            self.gap(GAP_CHARSET_UNSUPPORTED, mail_lists.DETAIL_BODY)
        return SelectedPart(node.part_id, subtype, charset, text.count(REPLACEMENT_CHARACTER), text)

    def defects(self, opened: Sequence[_Node]) -> None:
        """Defects the standard parser recorded on the selected parts and on what holds them."""
        root = opened[0]
        structure = {id(root): root}
        on_parts = 0
        for node, path in self.picked:
            for holder in path:
                structure[id(holder)] = holder
            if node is not root:
                on_parts += len(node.part.defects)
            for header in ("content-type", "content-transfer-encoding"):
                if node.names.get(header):
                    on_parts += len(getattr(node.part[header], "defects", ()))
        if on_parts:
            self.gap(GAP_PARSE_DEFECT, mail_lists.DETAIL_PART, on_parts)
        on_structure = sum(len(holder.part.defects) for holder in structure.values())
        # A part that declares a multipart type and could not be split into parts: a mail
        # reader may show what is in it, wherever it stands.
        for node in opened:
            if node.main_type == "multipart" and node.kind != _MULTIPART and id(node) not in structure:
                on_structure += max(1, len(node.part.defects))
        if root.main_type == "multipart" and root.kind != _MULTIPART and not on_structure:
            on_structure = 1
        if on_structure:
            self.gap(GAP_PARSE_DEFECT, mail_lists.DETAIL_STRUCTURE, on_structure)

    def attachment(self, node: _Node, number: int) -> AttachmentItem:
        part = node.part
        data = b""
        if node.kind != _MESSAGE and not part.is_multipart():
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                data = payload
        extension_class, extension = read_extension(part.get_filename())
        return AttachmentItem("a%d" % number, node.part_id, node.role, _media_type_word(node.media_type),
                              extension_class, read_signature(data[:32]), len(data),
                              _clean(node.media_type), extension)

    def links(self, selected: Sequence[SelectedPart]) -> Tuple[LinkItem, ...]:
        out: List[LinkItem] = []
        for part in selected:
            seen = {mail_lists.LINK_ANCHOR: 0, mail_lists.LINK_TEXT: 0}
            for kind, url, anchor_text in find_links(part.subtype, part.text):
                if len(out) >= self.bounds.max_links:
                    raise _OverBound(mail_lists.BOUND_LINKS)
                self.budget.check()
                facts = _read_link(url)
                flags = facts.flags()
                if kind == mail_lists.LINK_ANCHOR and _names_another_host(anchor_text, facts.host):
                    flags += (mail_lists.LINK_TEXT_MISMATCH_FLAG,)
                number = len(out) + 1
                out.append(LinkItem("l%d" % number, number, part.part_id, kind, seen[kind], flags,
                                    url, facts.host))
                seen[kind] += 1
        return tuple(out)

    # ---- the whole message ------------------------------------------------------------

    def read(self, message: Any) -> ParsedMessage:
        order = self.tree(message)
        root = order[0]
        for node in order:
            self.classify(node)
        opened = [node for node in order if node.opened]
        for number, node in enumerate(opened, 1):
            node.part_id = "p%d" % number

        self.single_headers(order)
        headers = self.header_facts(root)

        if root.kind == _MULTIPART:
            self.select(root, [])
        elif root.kind == _TEXT:
            self.pick(root, [])
        else:
            self.attachment_only = True
            self.aside(root, mail_lists.ROLE_ATTACHMENT, mail_lists.ROLE_ATTACHMENT)

        position = {id(node): index for index, node in enumerate(opened)}
        self.picked.sort(key=lambda entry: position[id(entry[0])])
        selected = []
        for node, _path in self.picked:
            self.budget.check_now()
            selected.append(self.decode(node))
        selected = tuple(selected)
        self.defects(opened)
        links = self.links(selected)

        parts = tuple(PartItem(node.part_id, _media_type_word(node.media_type),
                               node.role or mail_lists.ROLE_ATTACHMENT, node.depth) for node in opened)
        attached = [node for node in opened if (node.role or mail_lists.ROLE_ATTACHMENT)
                    in mail_lists.ATTACHMENT_ROLES]
        for node in attached:
            node.role = node.role or mail_lists.ROLE_ATTACHMENT
        attachments = tuple(self.attachment(node, number) for number, node in enumerate(attached, 1))
        ambiguous = tuple(HeaderAmbiguity(header, reason, count)
                          for (header, reason), count in self.ambiguous.items())
        return ParsedMessage("", self.attachment_only, self.gap_items(), ambiguous, parts, attachments,
                             links, selected, headers)


def _stopped(name: str, detail: str, over_bound: str = "") -> ParsedMessage:
    """The result of a parse that read nothing: one gap, no text, no fact, no inventory."""
    gap = mail_lists.GAPS[name]
    return ParsedMessage(over_bound, False, (GapItem(name, gap.gap_class, gap.reply_effect, detail, 1),),
                         (), (), (), (), (), _NO_HEADERS)


# BARE CARRIAGE RETURNS. The standard parser ends a line at CR LF, at LF and at a CR alone.
# A mail server and most mail programs do not end a line at a CR alone, so one header value
# that holds one is, to this parser only, several headers: an Auto-Submitted, a List-Id, a
# second Content-Type that nobody else sees. No header of such a block can be trusted, and
# nothing of the message is read. Mail with LF line ends, with CR LF, and with both mixed is
# ordinary; so is a CR alone in a body, unless it makes this parser see a part there.
_BARE_CR = re.compile(rb"\r(?!\n)")
_RAW_LINE = re.compile(rb"([^\r\n]*)(\r\n|\r|\n|\Z)")


def _bare_cr_in_headers(raw: bytes, message: Any) -> bool:
    """Whether a line of a header block, as the standard parser cut the blocks, ends in a CR alone.

    The blocks are the top of the message and what follows each boundary line of a
    multipart the parser found. The lines of a block run to its first empty line. When the
    boundaries cannot be read, the answer is yes.
    """
    try:
        boundaries = set()
        stack = [message]
        while stack:
            part = stack.pop()
            boundary = part.get_boundary()
            if boundary:
                boundaries.add(b"--" + boundary.encode("ascii", "surrogateescape"))
            if part.is_multipart():
                stack.extend(part.get_payload())
    except Exception:  # noqa: BLE001 - a structure that cannot be walked is not one to trust
        return True
    in_headers = True
    for match in _RAW_LINE.finditer(raw):
        line, end = match.group(1), match.group(2)
        if in_headers:
            if end == b"\r":
                return True
            if not line:
                in_headers = False
        elif line.startswith(b"--") and line.rstrip(b" \t") in boundaries:
            if end == b"\r":
                return True
            in_headers = True
        if not end:
            break
    return False


class _KeepingPolicy(email.policy.EmailPolicy):
    """`policy.default` that parses each header value once and keeps the result.

    The standard policy parses a header again on every read (`get_content_type`,
    `get_param`, `get_boundary`, `msg[name]`), and the parser of the library itself reads
    Content-Type several times per part. A header object is immutable, so the one made
    first is the one every later read gets.
    """

    def header_fetch_parse(self, name: str, value: Any) -> Any:
        if hasattr(value, "name"):
            return value
        kept = self.__dict__.get("kept")
        if kept is None:
            return email.policy.EmailPolicy.header_fetch_parse(self, name, value)
        key = (name.lower(), value)
        found = kept.get(key)
        if found is None:
            found = email.policy.EmailPolicy.header_fetch_parse(self, name, value)
            kept[key] = found
        return found


def _keeping_policy() -> Any:
    policy = _KeepingPolicy(header_factory=email.policy.default.header_factory)
    object.__setattr__(policy, "kept", {})
    return policy


_MIME_HEADER_LINE = re.compile(
    rb"(?:^|(?<=[\r\n]))(?:%s)[ \t]*:" % b"|".join(name.encode("ascii") for name in mail_lists.MIME_HEADER_NAMES),
    re.IGNORECASE)
_LINE_END_BYTE = re.compile(rb"[\r\n]")


def mime_header_over_bound(raw: bytes, limit: int) -> bool:
    """Whether a line of `raw` that starts with a name of MIME_HEADER_NAMES has a value over `limit` bytes.

    The value runs over every continuation line (one that starts with a space or a tab) and
    is counted without its line ends. Read from the raw bytes, before any parser: see TWO
    BOUNDS ARE ABOUT TIME in the module text.
    """
    size = len(raw)
    for match in _MIME_HEADER_LINE.finditer(raw):
        position = match.end()
        while raw[position:position + 1] in (b" ", b"\t"):
            position += 1               # the space after the colon is no part of the value
        length = 0
        while True:
            end = _LINE_END_BYTE.search(raw, position)
            stop = size if end is None else end.start()
            length += stop - position
            if length > limit:
                return True
            if end is None:
                break
            position = end.end()
            if raw[end.start():end.start() + 2] == b"\r\n":
                position = end.start() + 2
            if raw[position:position + 1] not in (b" ", b"\t"):
                break
    return False


def parse(raw: bytes, bounds: Bounds = DEFAULT_BOUNDS, budget: Any = None) -> ParsedMessage:
    """Read one raw message. Never raises for any bytes; `raw` that is not bytes is a TypeError.

    `budget` is the wall-clock budget of the scan this parse is part of (`mail_reuse.Budget`);
    without one, a budget of `bounds.max_seconds` starts here.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError("raw must be bytes")
    raw = bytes(raw)
    if len(raw) > bounds.max_bytes:
        return _stopped(GAP_STRUCTURE_OVER_BOUND, mail_lists.BOUND_BYTES, mail_lists.BOUND_BYTES)
    if budget is None:
        budget = mail_reuse.Budget(bounds.max_seconds)
    try:
        if mime_header_over_bound(raw, bounds.max_mime_header_bytes):
            return _stopped(GAP_STRUCTURE_OVER_BOUND, mail_lists.BOUND_HEADER_LENGTH, mail_lists.BOUND_HEADER_LENGTH)
        try:
            message = email.parser.BytesParser(policy=_keeping_policy()).parsebytes(raw)
        except RecursionError:
            # Multiparts nested deeper than the standard parser can follow.
            return _stopped(GAP_STRUCTURE_OVER_BOUND, mail_lists.BOUND_DEPTH, mail_lists.BOUND_DEPTH)
        budget.check_now()
        if _BARE_CR.search(raw) is not None and _bare_cr_in_headers(raw, message):
            return _stopped(GAP_PARSE_DEFECT, mail_lists.DETAIL_BARE_CR)
        return _Reader(bounds, budget).read(message)
    except _OverBound as over:
        return _stopped(GAP_STRUCTURE_OVER_BOUND, over.bound, over.bound)
    except mail_reuse.TimeUp:
        return _stopped(GAP_STRUCTURE_OVER_BOUND, mail_lists.BOUND_TIME, mail_lists.BOUND_TIME)
    except Exception:  # noqa: BLE001 - a message the parser cannot read is a gap, never a crash
        return _stopped(GAP_PARSE_DEFECT, mail_lists.DETAIL_ERROR)
