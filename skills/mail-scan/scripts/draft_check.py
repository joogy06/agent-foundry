#!/usr/bin/env python3
"""draft_check.py -- the last look at a reply before it leaves toward a customer (#351).

`check(record_id, body, subject, reply_target, config, root)` reads the record and the view
of the scanned message through `mail_state` and returns a `DraftResult`:

    result           accept | refuse
    rule_hits        (rule id, class, count), ids of `mail_lists.REFUSE_RULE_IDS`
    body_sha256      on accept: the SHA-256 of the body exactly as it was given
    subject_sha256   on accept: the SHA-256 of the subject exactly as it was given

A gate places only a body and a subject whose digests it got back from here. The result
holds rule ids, numbers and the two digests and nothing else: no text of the draft, of the
view, of the config or of an address reaches it.

WHY IT IS STRICT. The model that wrote the draft read a message from a stranger, and the
stranger may have told it what to write. So this check is the control against a reply that
carries data out or sends a customer somewhere: a draft may name our own hosts, our own
addresses, the address it is going to, our approved phone numbers and numbers the customer
or the knowledge pack already gave. Everything else of that kind is refused. The default
is to refuse: a host, an address or a URL is accepted only in the one plain form written
below, and whatever is left after the accepted forms are taken out is searched loosely.

WHAT IS READ. The body and the subject each go through the same checks. Each is read after
NFKC and after `fold()`: combining marks taken out, every decimal digit as its ASCII digit,
the characters a reader takes for a full stop as one, every dash as a hyphen, every space
character and a tab as a space. So a host in full-width letters, a number in another
script's digits and a dot that is not a dot are read as what a person sees. A text holding
a space too thin to see is read a second time with those taken out, and a rule counts
what the reading that found more found.

THE REFUSALS, in the order of `mail_lists.REFUSE_RULE_IDS`:

    draft-markup               an HTML tag, comment or character reference; markdown link,
                               image or reference syntax; a bulletin-board link tag
    draft-url                  a URL with a scheme other than http or https: any word
                               before `://`, and a LISTED scheme followed by a colon and
                               directly by text (`mailto:`, `tel:`, `javascript:`; not
                               `Note:closed`, and not `Tel:` before an approved number);
                               two slashes that open a word (`//host/x`);
                               a URL whose host is not on `allowed_hosts`;
                               an allowed host followed by anything but a plain path and
                               fragment of at most 80 characters (a port, user information,
                               another URL); `://` anywhere else
    draft-url-query            an allowed host with a query string
    draft-bare-host            any other chain of labels with dots in which a label after
                               the first is a top-level domain (mail_lists.DRAFT_TLDS: a
                               dated snapshot of the IANA root zone; the xn-- form; letters
                               of another script); the same with white space before its
                               dot; a dotted quad; an address in colons (in square brackets,
                               or with a double colon); `localhost`; the loopback address
                               written short (`127.1`); a path that starts with two
                               backslashes
    draft-secret               a credential-shaped string (`mail_reuse.secret_spans`)
    draft-address              a token holding an at sign that is not one of
                               `own_addresses` and not the reply target; an at sign
                               standing alone only when a host follows it
    draft-phone                a run of 9 to 15 digits that is not in `approved_phones`
                               and is not one whole run of the view or of the pack
    draft-hidden-characters    every character no reader sees: tag, bidirectional and format
                               characters, the rest of the Unicode property
                               Default_Ignorable_Code_Point (variation selectors, fillers,
                               the combining grapheme joiner), the blank code points, and
                               whatever else the intake pattern HIDDEN_UNICODE finds; and
                               more than two GENERAL combining marks on one character
                               (the marks of a script are its writing). Not a variation
                               selector after an emoji, not a zero-width joiner between
                               two emoji, not a listed flag, not a zero-width non-joiner
                               between two Arabic-script letters.
                               WHITE SPACE USED AS A CHANNEL: any space character other
                               than U+0020 (but a no-break space in French punctuation
                               and between digits), a tab, white space at the start or
                               the end of a line, two spaces in a row, more than two
                               blank lines in a row, line endings of both kinds.
                               A WORD THAT MIXES SCRIPTS: Latin with Cyrillic or Greek
    draft-body-too-long        over 8,000 characters, as given or after NFKC
    draft-subject-too-long     over 200
    draft-digit-run            a run of 7 or 8, or of 16 or more, digits found in neither
                               the inbound view nor the knowledge pack
    draft-canary               the configured canary
    draft-record-missing       no record, or one that cannot be read
    draft-view-missing         no view, or one that cannot be read
    draft-record-blocked       the effective verdict is block
    draft-reply-not-allowed    the effective reply is not draft
    draft-reply-target         the reply target is not the sender of the record, or is
                               written with white space around it or a line break in it
    draft-control-characters   a control, private-use, unassigned or surrogate character,
                               a line or paragraph separator, a lone carriage return; in
                               the subject, any line break
    draft-catalog-missing      the secrets catalog cannot be used
    draft-knowledge-pack       the knowledge pack named in the config cannot be read

NUMBERS. A run is digits with spaces, dots, hyphens and brackets between them and one
leading plus (`mail_lists.DIGIT_RUN`); it is judged by its digits alone. An approved phone
number is accepted as a whole run, or at the START of a run when at least two separator
characters lie between it and the digits after it (those are then judged as a run of their
own). It is never accepted behind other digits: digits in front of a number make another
number. Runs are read line by line and once more ACROSS line breaks, so a number written
over two or three lines is judged as one; a run that is accounted for by itself (found in
the view or the pack, or approved) is left out of that second reading, and a full stop at
the end of a paragraph, or of a line that holds a letter, ends a number there. A run that
starts with a plus and holds one `(0)` is also read without it (a trunk zero). A real
calendar date (YYYY-MM-DD, or day, month, year with dots, hyphens or slashes; years 1900 to
2100) is not a number, and two amounts with two decimal places joined by a hyphen are two
numbers; a date-shaped token that is no date, and digits joined by a hyphen with no decimal
part, stay one run. The path and the fragment of an allowed host are read by these rules like
any other text: the host is no cover for a number. `www.` in front of an allowed host, or left off one, is the same host. "Found" means the
digits are part of the digits of one run of the view or of the pack.

THE REPLY TARGET is accepted when its keyed hash is the sender hash of the record, or when
it is the value of the `reply_to_map` entry whose key hashes to that sender. The mapped
address of another sender, and any other address, is refused. It is compared and never
kept.

THE RECORD. A record that is missing or cannot be read ends the check there: nothing else
can be judged. The verdict and the reply are the EFFECTIVE ones, after the overrides bound
to the raw digest of the record.

WHAT IT DOES NOT CATCH. A host or a number spelled in words, a dot written as a word or in
brackets, digits separated by letters or by a character that is not a separator. The check
narrows what a draft can carry; the person who sends the reply is still the last reader.

Nothing is written, anywhere. The config is a dict (the loader that validates a config file
is `mail_scan`); a value of the wrong type is a ValueError with a fixed text.

Stdlib only; callees `mail_state`, `mail_reuse` and the data of `mail_lists`. It imports no
other module of mail-scan. Importing this module has no side effects.
"""
from __future__ import annotations

import datetime
import hashlib
import ipaddress
import hmac
import re
import unicodedata
from typing import Any, Dict, FrozenSet, List, Mapping, NamedTuple, Optional, Pattern, Sequence, Tuple

import mail_lists
import mail_reuse
import mail_state

CONFIG_ERROR = "the config is not in the form mail-scan reads"
INPUT_ERROR = "the draft body and the draft subject must be text"

RULE_MARKUP = "draft-markup"
RULE_URL = "draft-url"
RULE_URL_QUERY = "draft-url-query"
RULE_BARE_HOST = "draft-bare-host"
RULE_SECRET = "draft-secret"
RULE_ADDRESS = "draft-address"
RULE_PHONE = "draft-phone"
RULE_HIDDEN = "draft-hidden-characters"
RULE_WHITE_SPACE = "draft-white-space"          # fix round 3 (D4): its own id, so a person sees what to fix
RULE_MIXED_SCRIPT = "draft-mixed-script"
RULE_BODY_LONG = "draft-body-too-long"
RULE_SUBJECT_LONG = "draft-subject-too-long"
RULE_DIGIT_RUN = "draft-digit-run"
RULE_CANARY = "draft-canary"
RULE_RECORD_MISSING = "draft-record-missing"
RULE_VIEW_MISSING = "draft-view-missing"
RULE_RECORD_BLOCKED = "draft-record-blocked"
RULE_REPLY_NOT_ALLOWED = "draft-reply-not-allowed"
RULE_REPLY_TARGET = "draft-reply-target"
RULE_CONTROL = "draft-control-characters"
RULE_CATALOG_MISSING = "draft-catalog-missing"
RULE_KNOWLEDGE_PACK = "draft-knowledge-pack"


class RuleHit(NamedTuple):
    rule_id: str            # an id of mail_lists.REFUSE_RULE_IDS
    rule_class: str         # from mail_lists.RULES: refuse
    count: int


class DraftResult(NamedTuple):
    result: str                     # a word of mail_lists.DRAFT_RESULTS
    rule_hits: Tuple[RuleHit, ...]  # in the order of mail_lists.REFUSE_RULE_IDS; empty on accept
    body_sha256: Optional[str]      # on accept only
    subject_sha256: Optional[str]   # on accept only

    def accepted(self) -> bool:
        return self.result == mail_lists.DRAFT_ACCEPT


def recordable(result: DraftResult) -> Dict[str, Any]:
    """The result as plain data: what a caller may print or store."""
    return {
        "result": result.result,
        "rules": [{"rule_id": hit.rule_id, "rule_class": hit.rule_class, "count": hit.count}
                  for hit in result.rule_hits],
        "body_sha256": result.body_sha256,
        "subject_sha256": result.subject_sha256,
    }


# --------------------------------------------------------------------------------------
# Folding
# --------------------------------------------------------------------------------------

_DOTS = frozenset(mail_lists.DRAFT_DOT_LOOKALIKES)
_DASHES = frozenset(mail_lists.DRAFT_DASH_LOOKALIKES)
# Line breaks other than LF, and what a line reader also splits on.
_LINE_BREAKS = re.compile("\\r\\n|[\\r\\x0b\\x0c\\x1c-\\x1e\\x85\\u2028\\u2029]")
_THIN_SPACES = {ord(char): None for char in mail_lists.DRAFT_THIN_SPACES}


def fold(text: str) -> str:
    """`text` as a person reads it: NFKC, then the folds named in the module text.

    Only used to LOOK at a draft. What is accepted, hashed and placed is the text as given.
    """
    text = _LINE_BREAKS.sub("\n", unicodedata.normalize("NFKC", text)).replace("\t", " ")
    if text.isascii():
        return text
    out: List[str] = []
    for char in text:
        if char <= "\x7f":
            out.append(char)
            continue
        category = unicodedata.category(char)
        if category[0] == "M":
            continue
        if category == "Nd":
            out.append(str(unicodedata.decimal(char)))
        elif category == "Pd" or char in _DASHES:
            out.append("-")
        elif category == "Zs":
            out.append(" ")
        elif char in _DOTS:
            out.append(".")
        else:
            out.append(char)
    return "".join(out)


def _folded_word(text: str) -> str:
    return fold(text).strip().lower()


def _digits(text: str) -> str:
    return "".join(char for char in text if "0" <= char <= "9")


# --------------------------------------------------------------------------------------
# The config
# --------------------------------------------------------------------------------------

class _Settings(NamedTuple):
    own_addresses: FrozenSet[str]               # folded, lower case
    allowed_hosts: Tuple[str, ...]              # folded, lower case, longest first
    approved_phones: FrozenSet[str]             # digits only
    reply_to_map: Tuple[Tuple[str, str], ...]   # (From address, reply address) as given
    knowledge_pack: Optional[str]               # a path, or None
    canary: Optional[str]


def _strings(config: Mapping[str, Any], name: str) -> List[str]:
    value = config.get(name)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError(CONFIG_ERROR)
    return list(value)


_HOST_ENTRY = re.compile(r"[^\s/?#@:\\<>\"'|]+")


def _settings(config: Any) -> _Settings:
    if not isinstance(config, Mapping):
        raise ValueError(CONFIG_ERROR)
    hosts = []
    for entry in _strings(config, "allowed_hosts"):
        host = _folded_word(entry).rstrip(".")
        if not _HOST_ENTRY.fullmatch(host):
            raise ValueError(CONFIG_ERROR)
        hosts.append(host)
        www = mail_lists.DRAFT_WWW_LABEL
        hosts.append(host[len(www):] if host.startswith(www) and len(host) > len(www) else www + host)
    phones = []
    for entry in _strings(config, "approved_phones"):
        digits = _digits(fold(entry))
        if not digits:
            raise ValueError(CONFIG_ERROR)
        phones.append(digits)
    mapping = config.get("reply_to_map")
    if mapping is None:
        mapping = {}
    if not isinstance(mapping, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()):
        raise ValueError(CONFIG_ERROR)
    pack = config.get("knowledge_pack")
    canary = config.get("canary")
    if pack is not None and (not isinstance(pack, str) or not pack):
        raise ValueError(CONFIG_ERROR)
    if canary is not None and (not isinstance(canary, str) or not canary.strip()):
        raise ValueError(CONFIG_ERROR)
    return _Settings(
        own_addresses=frozenset(_folded_word(item) for item in _strings(config, "own_addresses")),
        allowed_hosts=tuple(sorted(set(hosts), key=lambda host: (-len(host), host))),
        approved_phones=frozenset(phones),
        reply_to_map=tuple(sorted(mapping.items())),
        knowledge_pack=pack,
        canary=canary,
    )


def _read_pack(path: str) -> Optional[str]:
    """The text of the knowledge pack; None when it cannot be read."""
    limit = mail_lists.KNOWLEDGE_PACK_MAX_BYTES
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except (OSError, ValueError):
        return None
    if len(data) > limit:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# --------------------------------------------------------------------------------------
# The record, the view and the reply target
# --------------------------------------------------------------------------------------

def _view_text(framed: str) -> str:
    """The text of the MESSAGE in a stored view, without the frame and without the lines the
    scanner added (those stand behind another prefix). `mail_state.read_view` vouches for the shape."""
    prefix = mail_lists.FRAME_LINE_PREFIX
    lines = framed[:-1].split("\n")[1:-1]
    return "\n".join(line[len(prefix):] if line.startswith(prefix) else "" for line in lines)


def _same_hash(address: str, sender: str, root: Any) -> bool:
    try:
        hashed = mail_state.sender_hash(address, root)
    except (mail_state.StateError, OSError):
        return False
    return (isinstance(hashed, str) and hashed.isascii() and sender.isascii()
            and hmac.compare_digest(hashed, sender))


def _accepted_target(record: Mapping[str, Any], reply_target: Any, settings: _Settings, root: Any) -> Optional[str]:
    """The reply target in its folded form when it is the sender of `record`; else None."""
    sender = record.get("sender")
    if not isinstance(sender, str) or not isinstance(reply_target, str):
        return None
    address = reply_target.strip()
    # exactly one address and nothing around it: a gate writes this string into a header
    if not address or address != reply_target or any(char.isspace() or ord(char) < 0x20 for char in address):
        return None
    if unicodedata.normalize("NFKC", address) != address:
        return None         # a compatibility form may lower-case to the letters of the sender
    accepted = _same_hash(address, sender, root)
    if not accepted:
        for key, value in settings.reply_to_map:
            if value.strip().lower() == address.lower() and _same_hash(key, sender, root):
                accepted = True
                break
    return _folded_word(address) if accepted else None


# --------------------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------------------

_CONTROL_CATEGORIES = frozenset({"Cc", "Cs", "Co", "Cn", "Zl", "Zp"})


def _hidden_count(text: str) -> int:
    """Characters no reader sees, and piles of combining marks.

    Every invisible character of `mail_reuse` (the stripped classes and the unseen class)
    except the two a reader sees the effect of, whatever else the intake pattern calls
    hidden, and one for each character that carries more than
    `mail_lists.DRAFT_MAX_COMBINING_MARKS` GENERAL combining marks (the marks of a script are
    not capped). A zero-width non-joiner between two Arabic-script letters is writing, not hiding.
    """
    if text.isascii():
        return 0
    text = mail_reuse.fold_flags(text)[0]       # a listed flag is one emoji, as it is inbound
    every = set(mail_reuse.INVISIBLE.find(text))
    written = _written_non_joiners(text)
    count = sum(1 for offset in mail_reuse.invisible_offsets(text) if offset not in written)
    if mail_reuse.HIDDEN_UNICODE is not None:
        count += sum(1 for match in mail_reuse.HIDDEN_UNICODE.finditer(text)
                     if match.start() not in every and match.start() not in written)
    marks = 0
    for index, char in enumerate(text):
        if index in every:
            continue
        if char > "\x7f" and unicodedata.category(char)[0] == "M":
            # only the general combining marks are capped: the marks of a script are its writing
            if _in_ranges(char, mail_lists.DRAFT_GENERAL_MARK_RANGES):
                marks += 1
                if marks == mail_lists.DRAFT_MAX_COMBINING_MARKS + 1:
                    count += 1
        else:
            marks = 0
    return count


def _script_letter(char: str, script: str) -> bool:
    return char.isalpha() and unicodedata.name(char, "").startswith(script)


def _written_non_joiners(text: str) -> FrozenSet[int]:
    """The offsets of each zero-width non-joiner that stands between two letters of the script that is written with it."""
    joiner = chr(mail_lists.DRAFT_NON_JOINER_CODE_POINT)
    script = mail_lists.DRAFT_NON_JOINER_SCRIPT
    found = set()
    position = text.find(joiner)
    while position >= 0:
        if (0 < position < len(text) - 1 and _script_letter(text[position - 1], script)
                and _script_letter(text[position + 1], script)):
            found.add(position)
        position = text.find(joiner, position + 1)
    return frozenset(found)


_SPACE_RUN = re.compile("  +")
_LETTERS = re.compile(r"[^\W\d_]+")


def _typographic_place(text: str, index: int) -> str:
    """Where the space at `index` stands: "mark" (before a listed mark, after an opening guillemet), "digits", or ""."""
    before, after = text[index - 1:index] if index else "", text[index + 1:index + 2]
    if before.isdigit() and after.isdigit():
        return "digits"
    if (after and after in mail_lists.DRAFT_TYPOGRAPHIC_SPACE_BEFORE) or (
            before and before in mail_lists.DRAFT_TYPOGRAPHIC_SPACE_AFTER):
        return "mark"
    return ""


def _white_space_count(text: str) -> int:
    """White space used as a channel (see `mail_lists.DRAFT_MAX_BLANK_LINES`): one for each use."""
    count = text.count("\t")
    kinds = set()
    typographic = set()                 # the places a no-break space was used in
    if not text.isascii():
        for index, char in enumerate(text):
            if char <= "\x7f" or unicodedata.category(char) != "Zs":
                continue
            place = _typographic_place(text, index)
            if char in mail_lists.DRAFT_TYPOGRAPHIC_SPACES and place:
                kinds.add(char)         # French punctuation, grouped digits
                typographic.add(place)
            else:
                count += 1
    count += max(0, len(kinds) - 1)
    # fix round 3 (D3): one use a text. A plain space where a no-break space stood elsewhere is refused.
    if typographic:
        count += sum(1 for index, char in enumerate(text) if char == " " and _typographic_place(text, index) in typographic)
    count += len(_SPACE_RUN.findall(text))
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    both = text.count("\r\n")
    if both and both != len(lines) - 1:
        count += 1                      # line endings of both kinds
    # fix round 3 (D1): lines by their place. One line break may end the text; a blank line may
    # not start it; no more than DRAFT_MAX_BLANK_LINES blank lines stand together anywhere.
    end = len(lines)
    while end > 1 and lines[end - 1] == "":
        end -= 1
    if len(lines) - end > 1:
        count += 1                      # more than one line break at the end
    if len(lines) > 1 and not lines[0].strip():
        count += 1                      # a blank line at the start
    blank = 0
    for number, line in enumerate(lines):
        if line and (line[0].isspace() or line[-1].isspace()):
            count += 1
        if number >= end:
            break                       # the line break that ends the text is no blank line
        blank = blank + 1 if not line.strip() else 0
        if blank == mail_lists.DRAFT_MAX_BLANK_LINES + 1:
            count += 1
    return count


def _words(text: str) -> List[str]:
    """The words of `text`: runs of letters and of the combining marks on them (fix round 3, D2)."""
    words: List[str] = []
    word: List[str] = []
    for char in text:
        if char.isalpha() or (char > "\x7f" and unicodedata.category(char)[0] == "M"):
            word.append(char)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return words


def _is_unit(word: str) -> bool:
    """A unit (fix round 3, D4): Latin letters, at most DRAFT_UNIT_MAX_LATIN, and exactly one of DRAFT_UNIT_GREEK."""
    greek = [char for char in word if char in mail_lists.DRAFT_UNIT_GREEK]
    latin = [char for char in word if char not in mail_lists.DRAFT_UNIT_GREEK]
    return (len(greek) == 1 and len(latin) <= mail_lists.DRAFT_UNIT_MAX_LATIN
            and all("a" <= char.lower() <= "z" for char in latin))


def _script_of(char: str) -> str:
    return unicodedata.name(char, "").split(" ", 1)[0]


def _mixed_script_count(text: str) -> int:
    """Words that mix letters of two of `mail_lists.DRAFT_MIXED_SCRIPTS`, and marks of a script on a letter of another."""
    if text.isascii():
        return 0
    count = 0
    for word in _words(text):
        if word.isascii():
            continue
        scripts = set()
        for char in word:
            if not char.isalpha():
                continue                # a mark: the scripts are judged from the letters
            if char <= "\x7f":
                scripts.add("LATIN")
                continue
            name = unicodedata.name(char, "")
            scripts.update(script for script in mail_lists.DRAFT_MIXED_SCRIPTS if name.startswith(script))
        if len(scripts) > 1 and not _is_unit(word):
            count += 1
    # fix round 3 (D5): a mark of a script only on a letter or a mark of that script
    for index, char in enumerate(text):
        if char <= "\x7f" or unicodedata.category(char)[0] != "M" or _in_ranges(char, mail_lists.DRAFT_GENERAL_MARK_RANGES):
            continue
        script = _script_of(char)
        if script in mail_lists.DRAFT_GENERAL_MARK_NAMES:
            continue
        base = text[index - 1] if index else ""
        if not base or base <= "\x7f" or _script_of(base) != script or not (
                base.isalpha() or unicodedata.category(base)[0] == "M"):
            count += 1
    return count


def _in_ranges(char: str, ranges: Sequence[Tuple[int, int]]) -> bool:
    return any(low <= ord(char) <= high for low, high in ranges)


def _joins_emoji(text: str, index: int) -> bool:
    """Whether the character at `index` is a zero-width joiner with an emoji on each side."""
    if ord(text[index]) != mail_lists.DRAFT_JOINER_CODE_POINT:
        return False
    before = index - 1
    while before >= 0 and _in_ranges(text[before], mail_lists.DRAFT_EMOJI_TRAILERS):
        before -= 1
    return (before >= 0 and _in_ranges(text[before], mail_lists.DRAFT_EMOJI_RANGES)
            and index + 1 < len(text) and _in_ranges(text[index + 1], mail_lists.DRAFT_EMOJI_RANGES))


def _control_count(text: str, single_line: bool) -> int:
    count = 0
    for index, char in enumerate(text):
        if char == "\n" or char == "\r":
            if single_line or (char == "\r" and text[index + 1:index + 2] != "\n"):
                count += 1
        elif char == "\t" or " " <= char <= "~":
            continue
        elif unicodedata.category(char) in _CONTROL_CATEGORIES and char not in mail_reuse.STRIPPED:
            count += 1                  # (an unassigned code point of the tag range is a tag character)
    return count


# --------------------------------------------------------------------------------------
# URLs, addresses, markup and hosts
# --------------------------------------------------------------------------------------

_MASK = " | "       # stands where an accepted or a counted token was: no digit, no letter
_SCHEME = re.compile(r"([a-z][a-z0-9+.\-]{0,31})://")
_NO_SLASH_SCHEME = re.compile(r"(?:%s):" % "|".join(mail_lists.DRAFT_SCHEMES_NO_SLASHES
                                                     + mail_lists.DRAFT_SCHEME_PREFIX_PATTERNS))
_HOST_END = "/?#"


def _url_pattern(hosts: Sequence[str]) -> Pattern[str]:
    starts = [mail_lists.DRAFT_URL_SCHEME_START_PATTERN]
    if hosts:
        starts.append(r"(?<![\w.@-])(?:%s)" % "|".join(re.escape(host) for host in hosts))
    return re.compile("(?:%s)%s" % ("|".join(starts), mail_lists.DRAFT_URL_REST_PATTERN), re.IGNORECASE)


def _mask(text: str, spans: Sequence[Tuple[int, int]]) -> str:
    if not spans:
        return text
    out: List[str] = []
    last = 0
    for start, end in sorted(spans):
        if start < last:
            continue
        out.append(text[last:start])
        out.append(_MASK)
        last = end
    out.append(text[last:])
    return "".join(out)


def _judge_url(token: str, hosts: Sequence[str]) -> Tuple[Optional[str], str]:
    """(None for a URL in the one accepted form, else the rule it breaks; its path and fragment)."""
    rule, tail = _judge_url_form(token, hosts)
    if rule is None and len(tail) > mail_lists.DRAFT_ALLOWED_URL_TAIL_MAX_CHARS:
        return RULE_URL, tail
    return rule, tail


def _judge_url_form(token: str, hosts: Sequence[str]) -> Tuple[Optional[str], str]:
    lowered = token.lower()         # judged in lower case throughout: lowering may change a length
    scheme = _SCHEME.match(lowered)
    if scheme is not None:
        if scheme.group(1) not in mail_lists.DRAFT_URL_SCHEMES:
            return RULE_URL, ""
        rest = lowered[scheme.end():]
    else:
        rest = lowered
    host = next((item for item in hosts
                 if rest.startswith(item) and rest[len(item):len(item) + 1] in tuple(_HOST_END) + ("",)), None)
    if host is None:
        return RULE_URL, ""         # another host, or a word and a colon: a scheme of some kind
    tail = rest[len(host):]
    if mail_lists.DRAFT_ALLOWED_URL_TAIL.fullmatch(tail) is None:
        return (RULE_URL_QUERY if "?" in tail else RULE_URL), ""
    if any(segment in (".", "..") for segment in tail.partition("#")[0].split("/")):
        return RULE_URL, ""         # a path that climbs: where it ends is not what is written
    # The shared reader must agree: the same host, nothing before it, nothing unreadable.
    facts = mail_reuse.read_url(lowered if scheme is not None else "http://" + lowered)
    if facts.unreadable or facts.userinfo or facts.host != host.rstrip("."):
        return RULE_URL, ""
    return None, tail


def _scan_urls(text: str, settings: _Settings, counts: Dict[str, int], reference: Optional[str] = None) -> str:
    """Count every URL that is not in the accepted form; `text` with every URL masked.

    The path and fragment of an accepted URL are read by the number rules here, as text of
    their own: an allowed host in front of a number does not take the number out of sight.
    An opening angle bracket straight before a URL that does not end at the closing one is
    markup with a host for a tag name.
    """
    spans = []
    for match in _url_pattern(settings.allowed_hosts).finditer(text):
        token = match.group(0).rstrip(mail_lists.DRAFT_TOKEN_TRAILING)
        if not token:
            continue
        label, colon, _rest = token.lower().partition(":")
        if colon and label in mail_lists.DRAFT_PHONE_LABEL_SCHEMES:
            # `Tel:` directly before an approved number is a label; the number rules read the number
            run = mail_lists.DIGIT_RUN.match(text, match.start() + len(label) + 1)
            if run is not None and _digits(run.group(0)) in settings.approved_phones:
                continue
        rule, tail = _judge_url(token, settings.allowed_hosts)
        if rule is not None:
            counts[rule] = counts.get(rule, 0) + 1
        elif tail:
            _scan_numbers(tail, settings, reference, counts)
        if text[match.start() - 1:match.start()] == "<" and text[match.end():match.end() + 1] != ">":
            counts[RULE_MARKUP] = counts.get(RULE_MARKUP, 0) + 1
        spans.append((match.start(), match.start() + len(token)))
    masked = _mask(text, spans)
    left = masked.count("://") + len(mail_lists.DRAFT_SCHEMELESS_URL.findall(masked))
    if left:
        counts[RULE_URL] = counts.get(RULE_URL, 0) + left
    return masked


def _scan_addresses(text: str, allowed: FrozenSet[str], counts: Dict[str, int]) -> str:
    """Count every token with an at sign that is not an allowed address; `text` with them masked."""
    spans = []
    position = text.find("@")
    while position >= 0:
        start = position
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        end = position
        while end < len(text) and not text[end].isspace():
            end += 1
        token = text[start:end]
        if token == "@":
            # an at sign standing alone: an address only when a host follows it
            rest = text[end:].lstrip()
            following = rest.split(None, 1)[0] if rest else ""
            if _host_spans(following):
                counts[RULE_ADDRESS] = counts.get(RULE_ADDRESS, 0) + 1
            position = text.find("@", end)
            continue
        address = token.lstrip(mail_lists.DRAFT_ADDRESS_LEADING).rstrip(mail_lists.DRAFT_TOKEN_TRAILING)
        label, colon, rest = address.partition(":")
        if colon and label.isalpha() and label.isascii() and rest.lower() in allowed:
            address = rest              # a label written against an allowed address (`Email:desk@...`)
        if address.lower() not in allowed or address.count("@") != 1:
            counts[RULE_ADDRESS] = counts.get(RULE_ADDRESS, 0) + 1
        spans.append((start, end))
        position = text.find("@", end)
    return _mask(text, spans)


def _is_tld(label: str, last: bool) -> bool:
    if label.startswith("xn--"):
        return True
    if last:
        letters = 0
        while letters < len(label) and label[letters].isalpha():
            letters += 1
        label = label[:letters]
    return label in mail_lists.DRAFT_TLDS or (len(label) >= 2 and label.isalpha() and not label.isascii())


def _host_spans(text: str) -> List[Tuple[int, int]]:
    """The spans of every chain of labels in `text` that is a host (see mail_lists.DRAFT_HOST)."""
    spans = []
    for match in mail_lists.DRAFT_HOST.finditer(text):
        labels = match.group(0).lower().split(".")
        if any(_is_tld(label, number == len(labels) - 1) for number, label in enumerate(labels) if number):
            spans.append(match.span())
    return spans


_SPACED_BEFORE = re.compile(r"[^\W_][\w-]*[ \t\n]+\.[ \t\n]*([^\W\d_]{2,})(?![\w-])")
_SPACED_AFTER = re.compile(r"[^\W_][\w-]*\.[ \t\n]+(%s)(?![\w.-])" % "|".join(mail_lists.DRAFT_SPACED_TLDS),
                           re.IGNORECASE)
_BARE_NAME = re.compile(r"(?<![\w.-])(?:%s)(?![\w-])" % "|".join(mail_lists.DRAFT_BARE_NAMES), re.IGNORECASE)


def _is_ipv6(token: str) -> bool:
    try:
        return ipaddress.ip_address(token.strip("[]").split("%", 1)[0]).version == 6
    except ValueError:
        return False


_IDEOGRAPHIC_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*%s([A-Za-z][A-Za-z0-9-]*)" % mail_lists.DRAFT_IDEOGRAPHIC_DOT)


def _scan_hosts(text: str, counts: Dict[str, int]) -> None:
    # fix round 3 (D5): the ideographic full stop between two ASCII labels, the second a top-level domain
    ideographic = sum(1 for match in _IDEOGRAPHIC_HOST.finditer(text) if _is_tld(match.group(1).lower(), True))
    if ideographic:
        counts[RULE_BARE_HOST] = counts.get(RULE_BARE_HOST, 0) + ideographic
    spans = _host_spans(text)
    left = _mask(text, spans)
    found = len(spans) + sum(1 for _ in mail_lists.DRAFT_IPV4.finditer(left))
    found += sum(1 for _ in mail_lists.DRAFT_SHORT_LOOPBACK.finditer(left))
    # a host with white space at its dot, an address in colons, a machine name, a network path
    found += sum(1 for match in _SPACED_BEFORE.finditer(left) if _is_tld(match.group(1).lower(), True))
    found += sum(1 for _ in _SPACED_AFTER.finditer(left))
    found += sum(1 for match in mail_lists.DRAFT_IPV6_BRACKET.finditer(left) if _is_ipv6(match.group(0)))
    found += sum(1 for match in mail_lists.DRAFT_IPV6_BARE.finditer(left) if _is_ipv6(match.group(0)))
    found += sum(1 for _ in _BARE_NAME.finditer(left))
    found += sum(1 for _ in mail_lists.DRAFT_UNC_PATH.finditer(left))
    if found:
        counts[RULE_BARE_HOST] = counts.get(RULE_BARE_HOST, 0) + found


# --------------------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------------------

_LINE_JOINT = " " * mail_lists.DRAFT_PHONE_GAP_CHARS


def digit_reference(*texts: str) -> str:
    """The digits of every run of `texts`, read line by line and across line breaks, each
    between two bars: what a run of a draft is looked for in, as a part or as a whole run."""
    found = []
    for text in texts:
        folded = fold(text)
        for form in (folded, folded.replace("\n", " ")):
            found.extend(_digits(match.group(0)) for match in mail_lists.DIGIT_RUN.finditer(form))
    return "|%s|" % "|".join(sorted(set(found)))


def _approved_start(run: str, phones: FrozenSet[str]) -> Optional[int]:
    """Where an approved number that opens `run` ends, when a gap follows it; else None."""
    longest = max((len(phone) for phone in phones), default=0)
    digits = ""
    for index, char in enumerate(run):
        if not "0" <= char <= "9":
            continue
        digits += char
        if len(digits) > longest:
            break
        if digits in phones:
            gap = 0
            for later in run[index + 1:]:
                if "0" <= later <= "9":
                    break
                gap += 1
            if gap >= mail_lists.DRAFT_PHONE_GAP_CHARS:
                return index + 1
    return None


def _judge_run(run: str, phones: FrozenSet[str], reference: Optional[str]) -> Tuple[Optional[str], bool]:
    """(the rule a run of digits breaks or None, whether it is accounted for by itself).

    Accounted for: approved, or seven digits or more and found in the reference. A short
    run breaks no rule and is not accounted for: it may be a piece of a longer number.
    """
    trunk = mail_lists.DRAFT_TRUNK_ZERO
    if run.startswith("+") and run.count(trunk) == 1:
        without = _judge_plain_run(run.replace(trunk, ""), phones, reference)
        if without == (None, True):
            return without
    return _judge_plain_run(run, phones, reference)


def _judge_plain_run(run: str, phones: FrozenSet[str], reference: Optional[str]) -> Tuple[Optional[str], bool]:
    while True:
        digits = _digits(run)
        if digits in phones:
            return None, True
        cut = _approved_start(run, phones)
        if cut is None:
            break
        run = run[cut:]
    count = len(digits)
    if count < mail_lists.DIGIT_RUN_MIN_DIGITS:
        return None, False
    if mail_lists.PHONE_MIN_DIGITS <= count <= mail_lists.PHONE_MAX_DIGITS:
        # a number of this length the customer or the pack already gave, as one whole run
        if reference is not None and "|%s|" % digits in reference:
            return None, True
        return RULE_PHONE, False
    if reference is None:
        return None, False          # no view to look in: the missing view is the refusal
    if digits in reference:
        return None, True
    return RULE_DIGIT_RUN, False


def _is_date(match: Any) -> bool:
    low, high = mail_lists.DRAFT_DATE_YEARS
    year = int(match.group("year"))
    if not low <= year <= high:
        return False
    try:
        datetime.date(year, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return False
    return True


def _without_dates_and_ranges(line: str) -> str:
    """`line` with every real calendar date masked and every range of two amounts cut in two."""
    for pattern in mail_lists.DRAFT_DATES:
        line = pattern.sub(lambda match: _MASK if _is_date(match) else match.group(0), line)
    return mail_lists.DRAFT_AMOUNT_RANGE.sub(
        lambda match: match.group(0).replace(match.group("joint"), _MASK, 1), line)


def _scan_numbers(text: str, settings: _Settings, reference: Optional[str], counts: Dict[str, int]) -> None:
    phones = settings.approved_phones
    lines = []
    source = text.split("\n")
    for number, line in enumerate(source):
        spans = []
        line = _without_dates_and_ranges(line)
        for match in mail_lists.DIGIT_RUN.finditer(line):
            rule, accounted = _judge_run(match.group(0), phones, reference)
            if rule is not None:
                counts[rule] = counts.get(rule, 0) + 1
            if rule is not None or accounted:
                spans.append(match.span())      # judged: not read again across lines
        ends_sentence = any(char.isalpha() for char in line)
        line = _mask(line, spans).rstrip()
        if line.endswith(".") and (ends_sentence or not "".join(source[number + 1:number + 2]).strip()):
            line = line[:-1] + _MASK            # a full stop that ends a sentence or a paragraph
        lines.append(line)
    if len(lines) < 2:
        return
    # Across line breaks: only a run that spans one is new here.
    joints = []
    offset = 0
    for line in lines[:-1]:
        offset += len(line)
        joints.append(offset)
        offset += len(_LINE_JOINT)
    joined = _LINE_JOINT.join(lines)
    index = 0
    for match in mail_lists.DIGIT_RUN.finditer(joined):
        while index < len(joints) and joints[index] < match.start():
            index += 1
        if index < len(joints) and joints[index] < match.end():
            rule, _accounted = _judge_run(match.group(0), phones, reference)
            if rule is not None:
                counts[rule] = counts.get(rule, 0) + 1


# --------------------------------------------------------------------------------------
# Secrets and the canary
# --------------------------------------------------------------------------------------

def _squeezed(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())


def _holds_canary(text: str, folded: str, canary: str) -> bool:
    if canary in text:
        return True
    folded_canary = fold(canary).strip()
    if folded_canary and folded_canary.casefold() in folded.casefold():
        return True
    squeezed = _squeezed(folded_canary)
    return len(squeezed) >= mail_lists.DRAFT_CANARY_SQUEEZED_MIN_CHARS and squeezed in _squeezed(folded)


# --------------------------------------------------------------------------------------
# One text: the body or the subject
# --------------------------------------------------------------------------------------

class _Context(NamedTuple):
    settings: _Settings
    addresses: FrozenSet[str]       # own addresses and the accepted reply target
    reference: Optional[str]        # digits of the view and the pack; None with no view
    checks: Tuple[Any, ...]         # the secrets catalog


def _scan_forms(folded: str, context: _Context) -> Dict[str, int]:
    """What one folded reading of a text holds of URLs, addresses, markup, hosts and numbers."""
    counts: Dict[str, int] = {}
    masked = _scan_urls(folded, context.settings, counts, context.reference)
    masked = _scan_addresses(masked, context.addresses, counts)
    markup = sum(1 for pattern in mail_lists.DRAFT_MARKUP for _ in pattern.finditer(masked))
    if markup:
        counts[RULE_MARKUP] = markup
    _scan_hosts(masked, counts)
    _scan_numbers(masked, context.settings, context.reference, counts)
    return counts


def _check_text(text: str, cap: int, cap_rule: str, single_line: bool, context: _Context,
                counts: Dict[str, int]) -> None:
    def add(rule: str, count: int) -> None:
        if count:
            counts[rule] = counts.get(rule, 0) + count

    if len(text) > cap:
        add(cap_rule, 1)
        text = text[:cap]           # what follows is bounded work on the part within the cap
    folded = fold(text)
    if len(folded) > cap:
        add(cap_rule, 1 if cap_rule not in counts else 0)
        folded = folded[:cap]
    add(RULE_HIDDEN, _hidden_count(text))
    add(RULE_WHITE_SPACE, _white_space_count(text))
    add(RULE_MIXED_SCRIPT, _mixed_script_count(text))
    add(RULE_CONTROL, _control_count(text, single_line))
    add(RULE_SECRET, max(len(mail_reuse.secret_spans(text, context.checks)),
                         len(mail_reuse.secret_spans(folded, context.checks))))
    if context.settings.canary is not None and _holds_canary(text, folded, context.settings.canary):
        add(RULE_CANARY, 1)
    found = _scan_forms(folded, context)
    tight = text.translate(_THIN_SPACES)
    if tight != text:
        for rule, count in _scan_forms(fold(tight)[:cap], context).items():
            found[rule] = max(found.get(rule, 0), count)
    for rule, count in found.items():
        add(rule, count)


# --------------------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------------------

def _result(counts: Mapping[str, int], body: str, subject: str) -> DraftResult:
    hits = tuple(RuleHit(rule_id, mail_lists.RULES[rule_id].rule_class, counts[rule_id])
                 for rule_id in mail_lists.REFUSE_RULE_IDS if counts.get(rule_id))
    if hits:
        return DraftResult(mail_lists.DRAFT_REFUSE, hits, None, None)
    return DraftResult(mail_lists.DRAFT_ACCEPT, (),
                       hashlib.sha256(body.encode("utf-8")).hexdigest(),
                       hashlib.sha256(subject.encode("utf-8")).hexdigest())


def check(record_id: Any, body: str, subject: str, reply_target: Any, config: Mapping[str, Any],
          root: Any = None, catalog: Optional[mail_reuse.Catalog] = None) -> DraftResult:
    """Accept or refuse one draft for the message stored under `record_id`.

        record_id      the id `scan` gave the message the draft answers
        body, subject  the draft, as it would be placed
        reply_target   the address the reply would go to: MEMORY ONLY, compared and dropped
        config         a dict; read here: `own_addresses`, `allowed_hosts`,
                       `approved_phones`, `reply_to_map`, `knowledge_pack` (a path, optional)
                       and `canary` (optional)
        root           the state root, as `mail_state` reads it
        catalog        `mail_reuse.catalog_checks()` when the caller already has it

    Raises ValueError with a fixed text for a body or subject that is not text and for a
    config of the wrong form. Everything else is a result. Nothing is written.
    """
    if not isinstance(body, str) or not isinstance(subject, str):
        raise ValueError(INPUT_ERROR)
    settings = _settings(config)
    counts: Dict[str, int] = {}
    try:
        record = mail_state.load_record(record_id, root)
        # The NEWEST record of the same message decides: a later scan that blocks it refuses a
        # draft that names an older record id (fix round 2, review B N5).
        effective = (mail_state.effective(record["sha256"], root)
                     or mail_state.effective_of(record, mail_state.read_overrides(root).entries))
    except (mail_state.StateError, OSError, KeyError, TypeError):
        counts[RULE_RECORD_MISSING] = 1
        return _result(counts, body, subject)
    if effective.verdict == mail_lists.VERDICT_BLOCK:
        counts[RULE_RECORD_BLOCKED] = 1
    if effective.reply != mail_lists.REPLY_DRAFT:
        counts[RULE_REPLY_NOT_ALLOWED] = 1
    target = _accepted_target(record, reply_target, settings, root)
    if target is None:
        counts[RULE_REPLY_TARGET] = 1
    pack = ""
    if settings.knowledge_pack is not None:
        read = _read_pack(settings.knowledge_pack)
        if read is None:
            counts[RULE_KNOWLEDGE_PACK] = 1
        else:
            pack = read
    try:
        reference: Optional[str] = digit_reference(_view_text(mail_state.read_view(record_id, root)), pack)
    except (mail_state.StateError, OSError):
        counts[RULE_VIEW_MISSING] = 1
        reference = None
    if catalog is None:
        catalog = mail_reuse.catalog_checks()
    if catalog.gap is not None:
        counts[RULE_CATALOG_MISSING] = 1
    addresses = settings.own_addresses | ({target} if target is not None else frozenset())
    context = _Context(settings, frozenset(addresses), reference, tuple(catalog.checks))
    _check_text(body, mail_lists.DRAFT_BODY_MAX_CHARS, RULE_BODY_LONG, False, context, counts)
    _check_text(subject, mail_lists.DRAFT_SUBJECT_MAX_CHARS, RULE_SUBJECT_LONG, True, context, counts)
    return _result(counts, body, subject)
