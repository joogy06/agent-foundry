#!/usr/bin/env python3
"""mail_sender.py -- is the sender of a message verified? (#351)

`verify(authentication_results, from_domain, authserv_id)` answers with a `SenderResult`:
verified or unverified, a fixed word saying why, and whether the provider reported a DMARC
failure. It reads text that is already in memory and nothing else.

WHAT COUNTS AS EVIDENCE. An Authentication-Results header is written by whoever handled the
message, and the sender of a message can write one too. So one is evidence only when ALL of
these hold:

    the caller has a provider profile      its `authserv_id` is given; without one every
                                           sender is unverified
    it is the FIRST such header            the one the last server put on top; no later
                                           header is ever read, whatever it says
    it carries the authserv-id of the      compared as a whole, without regard to letter
    profile                                case; another id means unverified
    it can be read                         a header that is not `id; method=result ...` with
                                           balanced comments and quotes is not interpreted

A header with the right id placed BELOW another one is never read. A header with another id
on top makes the sender unverified even when the next one is the provider's.

WHAT "VERIFIED" MEANS, under such a header, for the one domain of From:

    dmarc=pass   with a `header.from` EQUAL to the From domain. The provider did the
                 alignment, with a real public-suffix list; this module only checks that
                 its answer is about the domain in From.
    dkim=pass    with a `header.d` EQUAL to the From domain
    spf=pass     with an `smtp.mailfrom` (an address or a domain) whose domain is EQUAL to it

The last two count only when the header carries NO dmarc result at all: where the provider
gave one, it decides. `dmarc=none`, `temperror`, `permerror` and `bestguesspass` are no
result (`DMARC_NO_RESULT`: the domain has no DMARC record, or the lookup failed). A
`dmarc=fail` is reported on its own (`dmarc_fail`, the caution `dmarc-fail`, which holds
the reply); it is never a block here. So is any other dmarc result word (fix round 3, B1:
`reject` and `quarantine` are written by providers that report the policy they applied):
only `pass`, `fail` and the words of `DMARC_NO_RESULT` are results this module knows.

WHAT IT CANNOT READ (fix round 3, B1). A first header that begins with the authserv-id of
the profile and cannot be read (a comment the provider copied in unbalanced, a stray
bracket) may hide a DMARC failure: it is reported (`header_unread`, the caution
`auth-header-unreadable`, which holds the reply). A first header that does not begin with
that id, the provider's own included when it writes no id at all, is another id or no
evidence: it holds nothing. So a provider whose header carries no authserv-id, or that
splits its results over several headers (only the first is read), gives no DMARC hold.

EQUAL means the same name after ASCII lower-casing and with one trailing dot removed.
There is no relaxed alignment here and no list of public suffixes: a list that misses one
suffix verifies a stranger's domain, and this module ships no list it could keep current.
The price: mail signed by a parent or a sibling domain of From (`mail.shop.example` for
`shop.example`) is unverified unless the provider reports dmarc=pass for the From domain.
A domain that is not letters, digits, hyphens and dots, or has fewer than two labels, is
equal to nothing, itself included: a domain that cannot be read is never proof.

Nothing here resolves a name, opens a socket or checks a signature. It reads what the
provider wrote and decides how far that may be trusted.

Stdlib only; it uses the data of `mail_lists`. Importing this module has no side effects.
"""
from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import mail_lists

SENDER_VERIFIED = "verified"
SENDER_UNVERIFIED = "unverified"
SENDER_STATUSES = (SENDER_VERIFIED, SENDER_UNVERIFIED)

# Why. Each is a fixed word of ours; none holds text of a message.
REASON_DMARC = "dmarc-pass"                  # verified
REASON_DKIM = "dkim-aligned"                 # verified: dkim=pass for the From domain itself, no dmarc result
REASON_SPF = "spf-aligned"                   # verified: spf=pass for the From domain itself, no dmarc result
REASON_NO_PROFILE = "no-profile"             # the config carries no provider profile
REASON_NO_FROM = "no-from"                   # no single From mailbox, or its domain is not a plain name
REASON_NO_HEADER = "no-header"               # the message has no Authentication-Results header
REASON_OTHER_ID = "other-authserv-id"        # the first header is not the provider's
REASON_UNREADABLE = "unreadable-header"      # the first header cannot be read
REASON_DMARC_FAIL = "dmarc-fail"             # the provider reported a DMARC failure
REASON_NO_ALIGNED_PASS = "no-aligned-pass"   # nothing in the header passes for the From domain itself
SENDER_REASONS = (REASON_DMARC, REASON_DKIM, REASON_SPF, REASON_NO_PROFILE, REASON_NO_FROM,
                  REASON_NO_HEADER, REASON_OTHER_ID, REASON_UNREADABLE, REASON_DMARC_FAIL,
                  REASON_NO_ALIGNED_PASS)

METHOD_DMARC = "dmarc"
METHOD_DKIM = "dkim"
METHOD_SPF = "spf"
RESULT_PASS = "pass"
RESULT_FAIL = "fail"
# What a provider writes when it has NO dmarc verdict (a domain with no DMARC record, a
# lookup that failed). It is read as "no dmarc result": the dkim / spf exact-match path applies.
DMARC_NO_RESULT = ("none", "temperror", "permerror", "bestguesspass")
DMARC_KNOWN_RESULTS = (RESULT_PASS, RESULT_FAIL) + DMARC_NO_RESULT
PROPERTY_HEADER_FROM = "header.from"
PROPERTY_HEADER_D = "header.d"
PROPERTY_MAILFROM = "smtp.mailfrom"


class SenderResult(NamedTuple):
    status: str             # a word of SENDER_STATUSES
    reason: str             # a word of SENDER_REASONS
    dmarc_fail: bool        # the provider's own header reports dmarc=fail, or a dmarc result this module does not know
    header_trusted: bool    # the first header carries the authserv-id of the profile and was read
    header_unread: bool = False     # the first header begins with that id and cannot be read (fix round 3, B1)


class Resinfo(NamedTuple):
    method: str                             # lower case, without a version
    result: str                             # lower case
    properties: Tuple[Tuple[str, str], ...]     # (name in lower case, value) in order


class AuthenticationResults(NamedTuple):
    authserv_id: str                        # as written, without quotes
    results: Tuple[Resinfo, ...]


# --------------------------------------------------------------------------------------
# Domains
# --------------------------------------------------------------------------------------

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def plain_domain(domain: object) -> Optional[str]:
    """`domain` in ASCII lower case without one trailing dot, or None when it is not a plain name.

    A plain name has two labels or more, each of letters, digits and hyphens, and its last
    label is not a number. A name in another script, an address literal and an empty label
    give None.
    """
    if not isinstance(domain, str):
        return None
    name = domain.strip()
    if not name.isascii():
        return None
    name = name.lower()
    if name.endswith("."):
        name = name[:-1]
    labels = name.split(".")
    if len(labels) < 2 or len(name) > 253:
        return None
    if not all(_LABEL.fullmatch(label) for label in labels):
        return None
    if labels[-1].isdigit():
        return None                         # an address written with dots, not a name
    return name


def same_domain(first: object, second: object) -> bool:
    """Both are plain names and they are the same name."""
    one = plain_domain(first)
    return one is not None and one == plain_domain(second)


def address_domain(value: str) -> str:
    """The domain of an address, or the value itself when it holds no at sign."""
    return value.rsplit("@", 1)[1] if "@" in value else value


# --------------------------------------------------------------------------------------
# Reading one Authentication-Results header
# --------------------------------------------------------------------------------------

_SPACE = " \t\r\n"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[0-9]+)?")
_VERSION = re.compile(r"[0-9]+")
_NO_RESULT = "none"


def _without_comments(value: str) -> Optional[List[Tuple[str, bool]]]:
    """`value` as (character, inside a quoted string) pairs with every comment replaced by a space.

    None when a comment or a quoted string is not closed, or a closing bracket has no
    opening one. A backslash takes the next character as it is, in a comment and in a
    quoted string.
    """
    out: List[Tuple[str, bool]] = []
    depth = 0
    quoted = False
    index = 0
    length = len(value)
    while index < length:
        char = value[index]
        if char == "\\" and (depth or quoted):
            if index + 1 >= length:
                return None
            if quoted:
                out.append((value[index + 1], True))
            index += 2
            continue
        if quoted:
            if char == '"':
                quoted = False
            else:
                out.append((char, True))
        elif depth:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if not depth:
                    out.append((" ", False))
        elif char == "(":
            depth = 1
        elif char == ")":
            return None
        elif char == '"':
            quoted = True
        else:
            out.append((char, False))
        index += 1
    if depth or quoted:
        return None
    return out


def _segments(chars: Sequence[Tuple[str, bool]]) -> List[List[Tuple[str, int]]]:
    """The header cut at each semicolon outside quotes; each piece as its words.

    A word is a run of characters with no space outside quotes, given as its text (quotes
    removed) and the offset of its first equals sign outside quotes, -1 when it has none.
    """
    out: List[List[Tuple[str, int]]] = [[]]
    current: List[str] = []
    equals = -1
    open_word = False

    def close() -> None:
        nonlocal current, equals, open_word
        if open_word:
            out[-1].append(("".join(current), equals))
        current, equals, open_word = [], -1, False

    for char, quoted in chars:
        if not quoted and char in _SPACE:
            close()
        elif not quoted and char == ";":
            close()
            out.append([])
        else:
            if not quoted and char == "=" and equals < 0:
                equals = len(current)
            current.append(char)
            open_word = True
    close()
    return out


def parse_authentication_results(value: object) -> Optional[AuthenticationResults]:
    """One header value as its authserv-id and results, or None when it cannot be read.

    The form read is `authserv-id [version] *( ; method[/version]=result *( name=value ) )`
    with comments in brackets anywhere and values that may be quoted, and `; none` for no
    result. A value may hold further equals signs (a bounce address often does). Anything
    else (a word with no equals sign among the results, space around an equals sign, a
    name that is not a name, a control character) gives None: a header that is not
    understood is not interpreted in part.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    if any((ord(char) < 0x20 and char not in _SPACE) or ord(char) == 0x7F for char in value):
        return None
    chars = _without_comments(value)
    if chars is None:
        return None
    segments = _segments(chars)
    head = segments[0]
    if not 1 <= len(head) <= 2 or not head[0][0] or head[0][1] >= 0:
        return None
    if len(head) == 2 and not _VERSION.fullmatch(head[1][0]):
        return None
    results: List[Resinfo] = []
    for words in segments[1:]:
        if not words or words == [(_NO_RESULT, -1)]:
            continue                        # a semicolon at the end, two in a row, or no result
        pairs: List[Tuple[str, str]] = []
        for text, equals in words:
            if equals < 0 or not _NAME.fullmatch(text[:equals]):
                return None
            pairs.append((text[:equals].lower(), text[equals + 1:]))
        method, result = pairs[0]
        results.append(Resinfo(method.partition("/")[0], result.strip().lower(), tuple(pairs[1:])))
    return AuthenticationResults(head[0][0], tuple(results))


# --------------------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------------------

def _values(resinfo: Resinfo, name: str) -> List[str]:
    return [value for key, value in resinfo.properties if key == name]


def _all_equal(values: Sequence[str], from_domain: str) -> bool:
    """There is at least one value and the domain of every one is the From domain."""
    return bool(values) and all(same_domain(address_domain(value.strip()), from_domain) for value in values)


def _unverified(reason: str, dmarc_fail: bool = False, trusted: bool = False) -> SenderResult:
    return SenderResult(SENDER_UNVERIFIED, reason, dmarc_fail, trusted)


def verify(authentication_results: Sequence[str], from_domain: Optional[str],
           authserv_id: Optional[str]) -> SenderResult:
    """Whether the sender is verified. See the module text for the rule.

    `authentication_results` is every such header of the message in order, unfolded;
    `from_domain` the domain of the one From mailbox (None when there is none);
    `authserv_id` the id of the provider profile (None when the config has no profile).
    Never raises for any header text.
    """
    if not isinstance(authserv_id, str) or not authserv_id.strip():
        return _unverified(REASON_NO_PROFILE)
    if not authentication_results:
        return _unverified(REASON_NO_HEADER)
    first = authentication_results[0]           # the ONLY header that is ever read
    try:
        parsed = parse_authentication_results(first)
    except Exception:  # noqa: BLE001 - a header that breaks the reader is an unread header
        parsed = None
    if parsed is None:
        # fix round 3 (B1): unread under the provider's own id, it may hide a DMARC failure
        words = first.split(";", 1)[0].split() if isinstance(first, str) else []
        named = bool(words) and words[0].lower() == authserv_id.strip().lower()
        return SenderResult(SENDER_UNVERIFIED, REASON_UNREADABLE, False, False, named)
    if parsed.authserv_id.strip().lower() != authserv_id.strip().lower():
        return _unverified(REASON_OTHER_ID)

    by_method: Dict[str, List[Resinfo]] = {}
    for resinfo in parsed.results:
        by_method.setdefault(resinfo.method, []).append(resinfo)
    dmarc = by_method.get(METHOD_DMARC, [])
    # fix round 3 (B1): a dmarc result word other than the known ones is read as a failure
    dmarc_fail = any(resinfo.result not in DMARC_KNOWN_RESULTS or resinfo.result == RESULT_FAIL for resinfo in dmarc)
    if plain_domain(from_domain) is None:
        return _unverified(REASON_NO_FROM, dmarc_fail, True)
    if dmarc_fail:
        return _unverified(REASON_DMARC_FAIL, True, True)
    dmarc = [resinfo for resinfo in dmarc if resinfo.result not in DMARC_NO_RESULT]

    if dmarc and all(resinfo.result == RESULT_PASS
                     and _all_equal(_values(resinfo, PROPERTY_HEADER_FROM), from_domain)
                     for resinfo in dmarc):
        return SenderResult(SENDER_VERIFIED, REASON_DMARC, False, True)
    if dmarc:
        return _unverified(REASON_NO_ALIGNED_PASS, False, True)     # the provider's dmarc result decides
    for resinfo in by_method.get(METHOD_DKIM, []):
        if resinfo.result == RESULT_PASS and _all_equal(_values(resinfo, PROPERTY_HEADER_D), from_domain):
            return SenderResult(SENDER_VERIFIED, REASON_DKIM, False, True)
    for resinfo in by_method.get(METHOD_SPF, []):
        if resinfo.result == RESULT_PASS and _all_equal(_values(resinfo, PROPERTY_MAILFROM), from_domain):
            return SenderResult(SENDER_VERIFIED, REASON_SPF, False, True)
    return _unverified(REASON_NO_ALIGNED_PASS, False, True)
