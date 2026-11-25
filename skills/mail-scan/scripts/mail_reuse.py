#!/usr/bin/env python3
"""mail_reuse.py -- what mail-scan shares with intake-scan, and its own character classes (#351).

ONE MODULE LOADS WHAT IS SHARED. Nothing else in mail-scan imports from another skill.
Loaded BY PATH from `skills/intake-scan/scripts` (found relative to this file, which is the
same layout in the repo and in an installed tree):

    validate_record, load_schema   the small schema interpreter of `intake_policy`
    HIDDEN_UNICODE                 `harness_rules`: any hidden character
    TOKEN_PATTERN                  `harness_rules`: a private key header or a provider token
    find_catalog, load_checks      `adapters/secrets_catalog`: the loader of the secrets
                                   catalog, which is a file of `skills/secret-scanning`

HOW THEY ARE LOADED. The intake-scan tests, and anything else in the same process, import
these modules by plain name after putting that scripts directory on `sys.path`. So a module
that is already in `sys.modules` under its plain name AND is the same file is used as it is:
one object, whoever asked first. Otherwise the file is loaded under a private name of ours
and no plain name is added, so a later plain import by someone else still finds its own
copy. `sys.path` is never changed here.

A MISSING PIECE IS A NAMED GAP. If intake-scan is not there, the names above are None,
`REUSE_AVAILABLE` is False and importing this module still succeeds. `catalog_checks()`
returns the checks of the secrets catalog or the gap `catalog-missing` (no catalog file, a
file that cannot be loaded, a file of the wrong form, intake-scan absent) and never raises:
a scan with no catalog is a block and a draft check with none is a refusal, decided by the
callers. It is never a silent pass.

MAIL-SCAN'S OWN. Four character classes, kept apart because the rules treat them
differently, and their union:

    TAG        U+E0000 to U+E007F
    BIDI       U+202A to U+202E and U+2066 to U+2069
    FORMAT     Unicode category Cf other than those
    UNSEEN     every other code point no reader sees: the rest of the Unicode property
               Default_Ignorable_Code_Point (variation selectors, Hangul fillers, the
               combining grapheme joiner, the Mongolian selectors, the Khmer inherent
               vowels) and the blank code points of `mail_lists`
    STRIPPED   the first three together ("stripped-class")
    INVISIBLE  all four

`strip_invisible()` is the one function that takes them out of text, for a view and for a
draft alike. It keeps two things, because a reader does see them: a variation selector
directly after an emoji base, and a zero-width joiner between two emoji.

`read_url()` is the one reader of a link: scheme and host through `urllib.parse` only, with
the flags the link rules use. Nothing here fetches, resolves or opens anything.

`Budget` is the wall-clock budget of one scan: the parser, the view and the rules call
`check()` inside their loops, and it raises `TimeUp` once the seconds are spent.

The catalog file itself is another skill's code. `load_checks` runs it to read its table;
it is outside the import guard of mail-scan, which says so by name.

Stdlib only. Importing this module reads the intake-scan modules and has no other effect.
"""
from __future__ import annotations

import importlib
import importlib.util
import ipaddress
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Pattern, Sequence, Tuple

import mail_lists

GAP_CATALOG_MISSING = "catalog-missing"

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
SKILLS_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))
INTAKE_SCRIPTS_DIR = os.path.join(SKILLS_DIR, "intake-scan", "scripts")

# Private names for the copies this module loads itself (see HOW THEY ARE LOADED).
_PRIVATE_PREFIX = "_mail_scan_reuse_"
# plain name -> path under INTAKE_SCRIPTS_DIR. `adapters` is a package.
_MODULE_FILES = {
    "intake_policy": ("intake_policy.py",),
    "harness_rules": ("harness_rules.py",),
    "adapters": ("adapters", "__init__.py"),
}
_CATALOG_SUBMODULE = "secrets_catalog"


# --------------------------------------------------------------------------------------
# Loading the shared modules by path
# --------------------------------------------------------------------------------------

def _is_file_of(module: Any, path: str) -> bool:
    loaded = getattr(module, "__file__", None)
    return isinstance(loaded, str) and os.path.realpath(loaded) == os.path.realpath(path)


def _load(plain: str) -> Any:
    """The intake-scan module `plain`: the one already imported from that file, else our own."""
    path = os.path.join(INTAKE_SCRIPTS_DIR, *_MODULE_FILES[plain])
    for name in (plain, _PRIVATE_PREFIX + plain):
        module = sys.modules.get(name)
        if module is not None and _is_file_of(module, path):
            return module
    name = _PRIVATE_PREFIX + plain
    is_package = os.path.basename(path) == "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[os.path.dirname(path)] if is_package else None)
    if spec is None or spec.loader is None:
        raise ImportError(plain)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _load_all() -> Optional[Dict[str, Any]]:
    try:
        policy = _load("intake_policy")
        rules = _load("harness_rules")
        package = _load("adapters")
        # A relative import inside the module: it loads only as part of its package.
        catalog = importlib.import_module(package.__name__ + "." + _CATALOG_SUBMODULE)
        loaded = {"intake_policy": policy, "harness_rules": rules, "adapters": package,
                  "adapters." + _CATALOG_SUBMODULE: catalog}
        # Read every pinned name now, so a missing one is found here and not in a scan.
        for module, names in ((policy, ("validate_record", "load_schema")),
                              (rules, ("HIDDEN_UNICODE", "TOKEN_PATTERN")),
                              (catalog, ("find_catalog", "load_checks"))):
            for name in names:
                getattr(module, name)
        return loaded
    except Exception:  # noqa: BLE001 - an absent or unusable intake-scan is a gap, not a crash
        return None


_MODULES = _load_all()
REUSE_AVAILABLE = _MODULES is not None

validate_record: Optional[Callable[..., List[str]]] = None
load_schema: Optional[Callable[..., Dict[str, Any]]] = None
HIDDEN_UNICODE: Optional[Pattern[str]] = None
TOKEN_PATTERN: Optional[Pattern[str]] = None
find_catalog: Optional[Callable[..., Optional[str]]] = None
load_checks: Optional[Callable[[str], Optional[List[Any]]]] = None
if _MODULES is not None:
    validate_record = _MODULES["intake_policy"].validate_record
    load_schema = _MODULES["intake_policy"].load_schema
    HIDDEN_UNICODE = _MODULES["harness_rules"].HIDDEN_UNICODE
    TOKEN_PATTERN = _MODULES["harness_rules"].TOKEN_PATTERN
    find_catalog = _MODULES["adapters." + _CATALOG_SUBMODULE].find_catalog
    load_checks = _MODULES["adapters." + _CATALOG_SUBMODULE].load_checks

# The names a test pins and `doctor` re-checks.
PINNED_SYMBOLS = ("validate_record", "load_schema", "HIDDEN_UNICODE", "TOKEN_PATTERN",
                  "find_catalog", "load_checks")


def reused_modules() -> Dict[str, Any]:
    """The intake-scan modules in use, by their plain dotted name. Empty when unavailable."""
    return dict(_MODULES or {})


def reused_module_files() -> List[str]:
    """The files of those modules: what the import guard reads beside our own scripts."""
    return sorted(os.path.realpath(m.__file__) for m in reused_modules().values())


# --------------------------------------------------------------------------------------
# The secrets catalog
# --------------------------------------------------------------------------------------

class Catalog(NamedTuple):
    checks: Tuple[Any, ...]      # the catalog's checks; empty when there is a gap
    gap: Optional[str]           # None, or GAP_CATALOG_MISSING


# The catalog rows used for masking: the credential-shaped ones. The advisory rows (an
# e-mail address, a host name, an IP address) are ordinary content of a message.
SECRET_SEVERITIES = frozenset({"CRITICAL", "HIGH"})
# A line longer than this is read in overlapping windows of this size, so the work on one
# hostile line is bounded and no part of it goes unread.
MASK_WINDOW_CHARS = 4096


def catalog_checks(path: Optional[str] = None) -> Catalog:
    """The checks of the secrets catalog, or the gap `catalog-missing`. Never raises.

    `path` names the catalog file; without it the file is looked for where intake-scan
    looks (the tree this skill lives in, then the home tree).
    """
    try:
        if find_catalog is None or load_checks is None:
            return Catalog((), GAP_CATALOG_MISSING)
        found = path if path is not None else find_catalog()
        if not isinstance(found, str) or not os.path.isfile(found):
            return Catalog((), GAP_CATALOG_MISSING)
        checks = load_checks(found)
        if not checks:
            return Catalog((), GAP_CATALOG_MISSING)
        for check in checks:
            if not hasattr(check.pattern, "finditer") or not isinstance(check.severity, str):
                return Catalog((), GAP_CATALOG_MISSING)
        return Catalog(tuple(checks), None)
    except Exception:  # noqa: BLE001 - whatever went wrong, the result is the gap
        return Catalog((), GAP_CATALOG_MISSING)


def _windows(text: str) -> List[Tuple[int, str]]:
    """(offset, piece) for every line of `text`, a long line in overlapping windows."""
    out: List[Tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        if len(line) <= MASK_WINDOW_CHARS:
            out.append((offset, line))
        else:
            step = MASK_WINDOW_CHARS // 2
            for start in range(0, len(line) - step, step):
                out.append((offset + start, line[start:start + MASK_WINDOW_CHARS]))
        offset += len(line) + 1
    return out


# A private key in the PEM form: the whole block is the secret, not its first line. It runs
# to its END line; without one, over the lines that follow and hold only the characters of
# the encoding (and the quote marks a view puts before a quoted line).
_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----")
_KEY_END = re.compile(r"-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----")
_KEY_BODY_LINE = re.compile(r"[ \t>]*(?:[A-Za-z0-9+/=]{16,}|(?:Proc-Type|DEK-Info|Version|Comment):.*)")
KEY_BLOCK_MAX_CHARS = 16_000


def _key_block_spans(text: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    position = 0
    while True:
        begin = _KEY_BEGIN.search(text, position)
        if begin is None:
            return spans
        limit = min(len(text), begin.end() + KEY_BLOCK_MAX_CHARS)
        end = _KEY_END.search(text, begin.end(), limit)
        if end is not None:
            stop = end.end()
        else:
            stop = begin.end()
            while stop < limit:
                line_end = text.find("\n", stop + 1)
                line_end = limit if line_end < 0 or line_end > limit else line_end
                line = text[stop + 1:line_end]
                if not line.strip() or _KEY_BODY_LINE.fullmatch(line) is None:
                    break
                stop = line_end
        spans.append((begin.start(), stop))
        position = stop


def secret_spans(text: str, checks: Sequence[Any]) -> List[Tuple[int, int]]:
    """Merged (start, end) spans of `text` that a credential-shaped check or TOKEN_PATTERN matches.

    The catalog's own allowlists are not applied: they drop a line that also holds a word
    such as "example", and the sender of a message can add that word to any line.
    """
    spans: List[Tuple[int, int]] = []
    patterns = [c.pattern for c in checks if c.severity in SECRET_SEVERITIES]
    if patterns:
        for offset, piece in _windows(text):
            for pattern in patterns:
                for match in pattern.finditer(piece):
                    if match.end() > match.start():
                        spans.append((offset + match.start(), offset + match.end()))
    if TOKEN_PATTERN is not None:
        spans.extend(m.span() for m in TOKEN_PATTERN.finditer(text) if m.end() > m.start())
    spans.extend(_key_block_spans(text))
    merged: List[Tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def mask_secrets(text: str, checks: Sequence[Any], mask: str = mail_lists.SECRET_MASK) -> Tuple[str, int]:
    """`text` with every secret replaced by `mask`, and how many were replaced."""
    spans = secret_spans(text, checks)
    if not spans:
        return text, 0
    out: List[str] = []
    last = 0
    for start, end in spans:
        out.append(text[last:start])
        out.append(mask)
        last = end
    out.append(text[last:])
    return "".join(out), len(spans)


# --------------------------------------------------------------------------------------
# Character classes
# --------------------------------------------------------------------------------------

TAG_RANGES = ((0xE0000, 0xE007F),)
BIDI_RANGES = ((0x202A, 0x202E), (0x2066, 0x2069))


def _in_ranges(code: int, ranges: Sequence[Tuple[int, int]]) -> bool:
    return any(low <= code <= high for low, high in ranges)


def _is_tag(char: str) -> bool:
    return _in_ranges(ord(char), TAG_RANGES)


def _is_bidi(char: str) -> bool:
    return _in_ranges(ord(char), BIDI_RANGES)


def _is_format(char: str) -> bool:
    return unicodedata.category(char) == "Cf" and not _is_tag(char) and not _is_bidi(char)


class CharClass:
    """A named set of characters with a membership test, a find and a strip."""

    def __init__(self, name: str, member: Callable[[str], bool]) -> None:
        self.name = name
        self._member = member

    def __contains__(self, char: object) -> bool:
        return isinstance(char, str) and len(char) == 1 and self._member(char)

    def __repr__(self) -> str:
        return "CharClass(%r)" % self.name

    def find(self, text: str) -> List[int]:
        """The offsets in `text` of every character of the class."""
        if text.isascii():
            return []
        member = self._member
        return [index for index, char in enumerate(text) if char > "\x7f" and member(char)]

    def count(self, text: str) -> int:
        return len(self.find(text))

    def strip(self, text: str) -> Tuple[str, int]:
        """`text` without the characters of the class, and how many were removed."""
        if text.isascii():
            return text, 0
        member = self._member
        kept = [char for char in text if char <= "\x7f" or not member(char)]
        return "".join(kept), len(text) - len(kept)


_BLANKS = frozenset(mail_lists.BLANK_CODE_POINTS)


def _is_stripped(char: str) -> bool:
    return _is_tag(char) or _is_bidi(char) or _is_format(char)


def _is_unseen(char: str) -> bool:
    code = ord(char)
    return ((_in_ranges(code, mail_lists.DEFAULT_IGNORABLE_RANGES) or code in _BLANKS)
            and not _is_stripped(char))


TAG = CharClass("tag", _is_tag)
BIDI = CharClass("bidi", _is_bidi)
FORMAT = CharClass("format", _is_format)
UNSEEN = CharClass("unseen", _is_unseen)
STRIPPED = CharClass("stripped", _is_stripped)
INVISIBLE = CharClass("invisible", lambda char: _is_stripped(char) or _is_unseen(char))
CHAR_CLASSES = (TAG, BIDI, FORMAT)

_EMOJI_SELECTORS = frozenset(mail_lists.EMOJI_VARIATION_SELECTORS)
_EMOJI_EXTRA = frozenset(mail_lists.EMOJI_EXTRA_BASES)
_JOINER = chr(mail_lists.DRAFT_JOINER_CODE_POINT)
_KEYCAP_BASES = frozenset(code for code in mail_lists.EMOJI_EXTRA_BASES if code < 0x80)
_KEYCAP = chr(0x20E3)


def is_emoji(char: str) -> bool:
    """Whether `char` is an emoji base: in an emoji range of `mail_lists`, or an extra base."""
    code = ord(char)
    return _in_ranges(code, mail_lists.DRAFT_EMOJI_RANGES) or code in _EMOJI_EXTRA


def _is_trailer(char: str) -> bool:
    return _in_ranges(ord(char), mail_lists.DRAFT_EMOJI_TRAILERS)


def kept_invisible(text: str, index: int) -> bool:
    """Whether the invisible character at `index` is one a reader does see the effect of.

    A variation selector (U+FE0E, U+FE0F) directly after an emoji base (after a digit, a
    hash or a star only when the keycap mark U+20E3 follows it); a zero-width joiner
    with an emoji before it (a variation selector or a skin tone may stand between) and an
    emoji after it.
    """
    char = text[index]
    if ord(char) in _EMOJI_SELECTORS:
        if index == 0 or not is_emoji(text[index - 1]):
            return False
        if ord(text[index - 1]) in _KEYCAP_BASES:
            # a digit, a hash or a star is an emoji only as a keycap: the selector, then U+20E3
            return text[index + 1:index + 2] == _KEYCAP
        return True
    if char != _JOINER:
        return False
    before = index - 1
    while before >= 0 and _is_trailer(text[before]):
        before -= 1
    return before >= 0 and is_emoji(text[before]) and index + 1 < len(text) and is_emoji(text[index + 1])


def invisible_offsets(text: str) -> List[int]:
    """The offsets in `text` of every invisible character that is not kept (see `kept_invisible`)."""
    if text.isascii():
        return []
    return [index for index in INVISIBLE.find(text) if not kept_invisible(text, index)]


def strip_invisible(text: str) -> Tuple[str, int, int]:
    """(`text` without its invisible characters, stripped-class ones removed, unseen ones removed).

    The two kept forms of `kept_invisible` stay. A listed flag emoji is the caller's to fold
    first (`fold_flags`): its tag characters are tag characters here.
    """
    if text.isascii():
        return text, 0, 0
    offsets = invisible_offsets(text)
    if not offsets:
        return text, 0, 0
    drop = set(offsets)
    unseen = sum(1 for index in offsets if _is_unseen(text[index]))
    kept = [char for index, char in enumerate(text) if index not in drop]
    return "".join(kept), len(offsets) - unseen, unseen


_FLAG_BASE = chr(mail_lists.FLAG_BASE_CODE_POINT)
_SUBDIVISION_FLAG = re.compile("%s(?:%s)%s" % (
    _FLAG_BASE,
    "|".join("".join(chr(mail_lists.FLAG_TAG_OFFSET + ord(char)) for char in code)
             for code in mail_lists.SUBDIVISION_FLAG_CODES),
    chr(mail_lists.FLAG_CANCEL_CODE_POINT)))


def fold_flags(text: str) -> Tuple[str, int]:
    """`text` with each listed subdivision flag written as the black flag alone, and how many.

    Only a whole sequence is folded: the black flag, the tag letters of one listed code and
    the cancel tag, with nothing between them. Every other tag character stays where it is
    (a tag with no flag before it, another code, a tag added inside or after a sequence),
    for the tag rule to find.
    """
    if _FLAG_BASE not in text:
        return text, 0
    return _SUBDIVISION_FLAG.subn(_FLAG_BASE, text)


def strip_by_class(text: str) -> Tuple[str, Dict[str, int]]:
    """`text` without stripped-class characters, and the count removed per class name."""
    counts = {cls.name: cls.count(text) for cls in CHAR_CLASSES}
    return STRIPPED.strip(text)[0], counts


# --------------------------------------------------------------------------------------
# The URL reader
# --------------------------------------------------------------------------------------

class UrlFacts(NamedTuple):
    scheme: str            # lower case; "" when the text has none
    host: str              # lower case, no port, no brackets; "" when none could be read.
    #                        MESSAGE TEXT: kept in memory, never recorded or printed as it is
    dangerous_scheme: bool  # a scheme of mail_lists.DANGEROUS_LINK_SCHEMES
    userinfo: bool         # user information before the host
    punycode: bool         # a label in the xn-- form
    mixed_script: bool     # letters of more than one script inside one label
    ip_literal: bool       # the host is an IP address, in any spelling a browser accepts
    unreadable: bool       # the host could not be read reliably

    def flags(self) -> Tuple[str, ...]:
        """The flag names that are set, in the order of mail_lists.LINK_FLAG_RULES."""
        values = {"scheme": self.dangerous_scheme, "userinfo": self.userinfo,
                  "punycode": self.punycode, "mixed_script": self.mixed_script,
                  "ip_literal": self.ip_literal, "unreadable": self.unreadable}
        return tuple(name for name, _rule in mail_lists.LINK_FLAG_RULES if values[name])


# Schemes that are followed by a host. One of these without a readable host is unreadable.
_HOST_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "ws", "wss"})
# A host a browser reads as an IPv4 address although it is not in dotted-decimal form.
_NUMERIC_HOST = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)(?:\.(?:0x[0-9a-f]*|[0-9]+)){0,3}\.?$")
_HOST_CHARS = re.compile(r"^[^\x00-\x20\x7f<>\"'\x60\\^{}|/?#@]*$")
# The first word of a character's Unicode name is its script for the scripts that matter
# here; anything else counts as a script of its own name.
_UNREADABLE = UrlFacts("", "", False, False, False, False, False, True)


def _scripts(label: str) -> set:
    scripts = set()
    for char in label:
        if char.isalpha():
            try:
                scripts.add(unicodedata.name(char).split(" ", 1)[0])
            except ValueError:
                scripts.add("UNKNOWN")
    return scripts


def _decode_label(label: str) -> str:
    """A punycode label in its Unicode form; the label itself when it is not one."""
    if not label.startswith("xn--"):
        return label
    try:
        return label[4:].encode("ascii").decode("punycode")
    except (UnicodeError, ValueError):
        return label


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_NUMERIC_HOST.match(host))


def read_url(text: str) -> UrlFacts:
    """What a link says about itself. Reads the text only: nothing is fetched or resolved.

    Never raises. A text whose host cannot be read the way a browser would read it (a
    backslash, a control character or a space inside it, a malformed bracket or port, a
    web scheme with no host) is `unreadable`, never a clean result.
    """
    if not isinstance(text, str):
        return _UNREADABLE
    # What a browser does first: drop surrounding spaces and controls, and every tab and
    # line break inside.
    cleaned = text.strip("".join(chr(c) for c in range(0x21))).translate({9: None, 10: None, 13: None})
    try:
        parts = urllib.parse.urlsplit(cleaned)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        netloc = parts.netloc
        _port = parts.port  # raises ValueError for a port that is not a number
    except ValueError:
        return _UNREADABLE
    unreadable = ("\\" in cleaned or any(ord(c) < 0x20 or ord(c) == 0x7F for c in cleaned)
                  or " " in netloc or not _HOST_CHARS.match(host)
                  or (scheme in _HOST_SCHEMES and not host))
    host = host.rstrip(".") if host != "." else host
    labels = [label for label in host.split(".") if label]
    return UrlFacts(
        scheme=scheme,
        host=host,
        dangerous_scheme=scheme in mail_lists.DANGEROUS_LINK_SCHEMES,
        userinfo="@" in netloc,
        punycode=any(label.startswith("xn--") for label in labels),
        mixed_script=any(len(_scripts(_decode_label(label))) > 1 for label in labels),
        ip_literal=bool(host) and _is_ip(host),
        unreadable=bool(unreadable),
    )



# --------------------------------------------------------------------------------------
# The wall-clock budget of one scan
# --------------------------------------------------------------------------------------

class TimeUp(Exception):
    """The budget of a scan is spent. It carries no text."""


class Budget:
    """So many seconds from now. `check()` raises `TimeUp` once they are spent.

    `check` reads the clock on every `every`-th call only, so it may stand inside a loop
    that runs a million times. A budget of None never runs out.
    """

    __slots__ = ("deadline", "_calls", "_every")

    def __init__(self, seconds: Optional[float] = mail_lists.SCAN_SECONDS, every: int = 256) -> None:
        self.deadline = None if seconds is None else time.monotonic() + seconds
        self._calls = 0
        self._every = max(1, every)

    def check(self) -> None:
        if self.deadline is None:
            return
        self._calls += 1
        if self._calls % self._every == 0 and time.monotonic() > self.deadline:
            raise TimeUp()

    def check_now(self) -> None:
        """The same, reading the clock at once: for a step that is taken a few times only."""
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise TimeUp()


NO_BUDGET = Budget(None)
