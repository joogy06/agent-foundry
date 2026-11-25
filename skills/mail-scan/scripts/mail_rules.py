#!/usr/bin/env python3
"""mail_rules.py -- one verdict and one reply decision for a scanned message (#351).

`decide(parsed, view, config, earlier_drafts)` takes what the parser and the view found and
returns a `Decision`:

    verdict             pass | caution | block
    reply               draft | none-automated | none-list | held
    reply_if_released   the reply the message would have with its holds lifted
    holds               the hold kinds in force: block, budget, held
    rule_hits           (rule id, class, count), ids of `mail_lists.RULES`
    gaps                (name, class, reply effect, detail, count), names of `mail_lists.GAPS`
    sender              what `mail_sender` decided
    reply_target        MEMORY ONLY: the address a reply would go to

It reads what it is given and decides. It parses nothing, builds no view, writes nothing.

THE INPUT.

    parsed            the result of `mail_parse.parse`
    view              the result of `mail_view.build`
    config            a dict; read here: `own_addresses` (a list of addresses),
                      `provider_profile` (absent, or a dict with `authserv_id`) and
                      `reply_to_map` (From address -> reply address). A value of the wrong
                      type is a ValueError with a fixed text.
    earlier_drafts    a whole number, counted by the caller (`mail_state.earlier_drafts`):
                      the earlier messages of the same sender, by sender hash, in the
                      seven days before this one, that really were open to a draft: the
                      recorded verdict was not a block and the reply was `draft` as
                      recorded or after a person's override, whatever its sender result.
                      Mail that was blocked or held never counts. 0 for a
                      message with no single From. The digest of this message is left out.
    extra_gaps        gap names the caller found itself (`catalog-missing`)

THE VERDICT. block when any block rule fires or any block-class gap is present; else
caution when any caution rule fires or any caution-class gap is present; else pass. The
class and the hold of a rule and of a gap are read from the tables of `mail_lists`, never
from the item that reports it, and a gap name the table does not hold is `scanner-error`.

WHERE EACH RULE LOOKS. The phrase lists are matched against text that was PROVEN hidden
and removed, and against nothing else: not against text removed as uncertain and not
against anything a person would see. Visible text gets no phrase rule. The control tokens,
the frame of this skill and the role labels are looked for in the visible text of the
view; the first two also in the Subject and the From name, and in a second reading of each
with compatibility forms folded and characters no reader sees taken out, so a token
written in full-width letters or split by such a character is still found.

WHAT SOME RULES COUNT. `tag-characters`: tag characters anywhere in the selected parts,
the Subject, the From name or a link, EXCEPT inside one of the three flag emoji that are
written with them (`mail_reuse.fold_flags`: the whole sequence and nothing else). `bidi-override`: a bidirectional control in the From
name, the Subject or a link; one in the body is stripped by the view and counted under
`format-characters`, which it is. `attachment-present`: every attachment, nested message
and resource of a related message, except a resource that is an image (a picture the text
shows is part of the text); the dangerous-type and type-mismatch rules judge those images
like any other part. `attachment-dangerous`: a dangerous extension or media type, or
content that STARTS as a program or a script (`mail_lists.DANGEROUS_SIGNATURES`) whatever
its name and declared type say. `attachment-active-content`: an HTML or SVG file that is
not dangerous by the rule before; a caution, because it is never parsed and reaches no
view. `attachment-type-mismatch`: see `_type_disagrees`; a generic media type, a generic
extension (`bin`, `dat`) and a missing name say nothing and agree with anything.
`image-only`: a message that is one part and not text, or fewer visible letters and digits
than the threshold together with an image element or an image part.
`sender-unverified` and `dmarc-fail`: what `mail_sender` says.

THE REPLY. `none-automated` wins over everything: an auto-submitted message, a null return
path, a no-reply sender, a request to suppress automatic responses, and mail from one of
our own addresses never get a draft, are never held, and carry no hold. Otherwise the
holds add up:

    block    any block
    budget   `earlier_drafts` at the budget or over it (the rule reply-budget)
    held     uncertain removal over the threshold, a caution-class gap the table marks
             held, image-only mail

While a hold is in force the reply is `held`. `reply_if_released` is what is left when
they are lifted: `none-list` for list mail, else `draft`.

THE REPLY TARGET is the one From mailbox as a bare address, or the `reply_to_map` entry
keyed by it. A Reply-To header is never read. It lives in memory only: `recordable()`
leaves it out, and that is the only form of a decision that may be written anywhere.

Stdlib only; callees `mail_sender`, `mail_reuse` and the data of `mail_lists`. It imports
no other module of mail-scan. Importing this module has no side effects.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Mapping, NamedTuple, Optional, Sequence, Tuple

import mail_lists
import mail_reuse
import mail_sender

GAP_SCANNER_ERROR = "scanner-error"
GAP_OVER_BOUND = "structure-over-bound"
CONFIG_ERROR = "the config is not in the form mail-scan reads"
INPUT_ERROR = "the earlier-draft count is not a whole number"


class RuleHit(NamedTuple):
    rule_id: str            # an id of mail_lists.RULES
    rule_class: str         # from mail_lists.RULES
    count: int


class GapHit(NamedTuple):
    name: str               # a name of mail_lists.GAPS
    gap_class: str          # from mail_lists.GAPS
    reply_effect: str       # from mail_lists.GAPS
    detail: str             # a word of mail_lists.GAP_DETAILS
    count: int


class Decision(NamedTuple):
    verdict: str            # a word of mail_lists.VERDICTS
    reply: str              # a word of mail_lists.REPLIES
    reply_if_released: str  # draft, none-list or none-automated; held for a message that was not judged
    holds: Tuple[str, ...]  # words of mail_lists.HOLD_KINDS, in that order
    rule_hits: Tuple[RuleHit, ...]      # in the order of mail_lists.RULES
    gaps: Tuple[GapHit, ...]            # in the order of mail_lists.GAP_NAMES
    sender: mail_sender.SenderResult
    reply_target: Optional[str]         # MEMORY ONLY: an address of the message or of the config


MEMORY_ONLY_FIELDS: Dict[str, Tuple[str, ...]] = {
    "RuleHit": (),
    "GapHit": (),
    "SenderResult": (),
    "Decision": ("reply_target",),
}
_TYPES = (RuleHit, GapHit, mail_sender.SenderResult, Decision)
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


def recordable(decision: Decision) -> Dict[str, Any]:
    """The recordable fields of a decision as plain data. It holds no text of the message."""
    return _plain(decision)


# --------------------------------------------------------------------------------------
# The config, as far as the rules read it
# --------------------------------------------------------------------------------------

class _Config(NamedTuple):
    own_addresses: Tuple[str, ...]          # lower case
    authserv_id: Optional[str]
    reply_to_map: Dict[str, str]            # key in lower case -> the reply address


_BARE_ADDRESS = re.compile(r"[^\s<>()\[\]\\,;:\"@]+@[^\s<>()\[\]\\,;:\"@]+")


def _read_config(config: Any) -> _Config:
    if not isinstance(config, Mapping):
        raise ValueError(CONFIG_ERROR)
    own = config.get("own_addresses", [])
    if not isinstance(own, (list, tuple)) or not all(isinstance(item, str) for item in own):
        raise ValueError(CONFIG_ERROR)
    profile = config.get("provider_profile")
    authserv_id = None
    if profile is not None:
        if not isinstance(profile, Mapping) or not isinstance(profile.get("authserv_id"), str):
            raise ValueError(CONFIG_ERROR)
        authserv_id = profile["authserv_id"]
    mapping = config.get("reply_to_map", {})
    if not isinstance(mapping, Mapping):
        raise ValueError(CONFIG_ERROR)
    reply_to: Dict[str, str] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not isinstance(value, str) or not _BARE_ADDRESS.fullmatch(value):
            raise ValueError(CONFIG_ERROR)
        reply_to[key.strip().lower()] = value
    return _Config(tuple(item.strip().lower() for item in own), authserv_id, reply_to)


# --------------------------------------------------------------------------------------
# Reading text
# --------------------------------------------------------------------------------------

_WHITE_SPACE = re.compile(r"\s+")
_QUOTE_MARKS = re.compile(r"^(?:>[ \t]?)+", re.MULTILINE)
# An address inside a display name: anything, an at sign, a dotted name.
_NAME_ADDRESS = re.compile(r"[^\s<>()\[\]\\,;:\"'@]+@([^\s<>()\[\]\\,;:\"'@]+\.[^\s<>()\[\]\\,;:\"'@]+)")
_IMAGE_TYPE_PREFIX = "image/"


def _folded(text: str) -> str:
    """`text` with characters no reader sees taken out and compatibility forms folded.

    Every invisible character goes, the ones a view keeps inside an emoji too: this reading
    is for finding a token, not for showing text. NFKC also writes the stand-in brackets of
    a view (`mail_lists.FRAME_LBRACKET_REPLACEMENT`) as square brackets again.
    """
    if mail_reuse.HIDDEN_UNICODE is not None:
        text = mail_reuse.HIDDEN_UNICODE.sub("", text)
    return unicodedata.normalize("NFKC", mail_reuse.INVISIBLE.strip(text)[0])


def _readings(text: Optional[str]) -> Tuple[str, ...]:
    """The readings of one text a token is looked for in: as it is, and folded."""
    if not text:
        return ()
    folded = _folded(text)
    return (text,) if folded == text else (text, folded)


def _most(counter: Any, texts: Sequence[Optional[str]]) -> int:
    """The hits of `counter` over `texts`: per text the reading with the most, summed."""
    return sum(max((counter(reading) for reading in _readings(text)), default=0) for text in texts)


_HTML_ONLY_TOKENS = tuple(token for token in mail_lists.CONTROL_TOKENS
                          if token not in mail_lists.CONTROL_TOKENS_PLAIN_ONLY)


def _count_control_tokens(text: str) -> int:
    return sum(text.count(token) for token in mail_lists.CONTROL_TOKENS)


def _count_control_tokens_html(text: str) -> int:
    """The same without the tokens that are ordinary markup talk: for a message with no plain part."""
    return sum(text.count(token) for token in _HTML_ONLY_TOKENS)


_SCANNER_LINES = frozenset(mail_lists.SCANNER_LINES)


def _count_frame_forgery(text: str) -> int:
    return len(mail_lists.FRAME_FORGERY.findall(text))


def _without_scanner_lines(text: str) -> str:
    """Visible text without the fixed lines the view wrote itself.

    A line that IS one of them, character for character, is the view's: the text of a
    message reaches a view with other brackets (`mail_frame.escape_content`).
    """
    if "[" not in text:
        return text
    return "\n".join(line for line in text.split("\n") if line not in _SCANNER_LINES)


def _count_phrases(patterns: Sequence[Any], removed: str) -> int:
    """Hits of a phrase list in removed text, read as one line with single spaces."""
    if not removed:
        return 0
    line = _WHITE_SPACE.sub(" ", _folded(removed))
    return sum(len(pattern.findall(line)) for pattern in patterns)


def _name_addresses_elsewhere(name: Optional[str], from_domain: Optional[str]) -> int:
    """Addresses in a display name whose domain is not the domain of the mailbox."""
    if not name or "@" not in _folded(name):
        return 0
    own = mail_sender.plain_domain(from_domain)
    hits = 0
    for match in _NAME_ADDRESS.finditer(_folded(name)):
        if mail_sender.plain_domain(match.group(1)) != own:
            hits += 1
    return hits


# --------------------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------------------

_SIGNATURES = {row.name: row for row in mail_lists.SIGNATURES}
_GENERIC_TYPES = frozenset(mail_lists.GENERIC_MEDIA_TYPES)


def _declared_type(item: Any) -> str:
    declared = getattr(item, "declared_media_type", "") or getattr(item, "media_type", "") or ""
    return declared.strip().lower()


def _is_dangerous(item: Any) -> bool:
    return (item.extension_class == mail_lists.EXTENSION_DANGEROUS
            or (item.extension or "").lower() in mail_lists.DANGEROUS_EXTENSIONS
            or _declared_type(item) in mail_lists.DANGEROUS_MEDIA_TYPES
            or item.signature in mail_lists.DANGEROUS_SIGNATURES)


def _is_active_content(item: Any) -> bool:
    return ((item.extension or "").lower() in mail_lists.ACTIVE_CONTENT_EXTENSIONS
            or _declared_type(item) in mail_lists.ACTIVE_CONTENT_MEDIA_TYPES)


def _type_disagrees(item: Any) -> bool:
    """A declared extension or media type that disagrees with the leading bytes.

    Content that starts with a listed signature under an extension or a media type that is
    not in the row of that signature; or an extension or a media type of a row over content
    that does not start with the signature of that row. A generic media type, a generic
    extension and a missing extension say nothing and agree with anything. A nested message is not opened and is
    not judged here.
    """
    if item.role == mail_lists.ROLE_NESTED_MESSAGE:
        return False
    extension = (item.extension or "").lower()
    if extension in mail_lists.GENERIC_EXTENSIONS:
        extension = ""
    declared = _declared_type(item)
    if declared in _GENERIC_TYPES:
        declared = ""
    found = _SIGNATURES.get(item.signature)
    if found is not None:
        if extension and extension not in found.extensions:
            return True
        if declared and declared not in found.media_types:
            return True
    for row in mail_lists.SIGNATURES:
        if row is found:
            continue
        if extension in row.extensions or declared in row.media_types:
            return True
    return False


def _is_image_resource(item: Any) -> bool:
    return item.role == mail_lists.ROLE_RESOURCE and _declared_type(item).startswith(_IMAGE_TYPE_PREFIX)


# --------------------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------------------

_RULE_ORDER = {rule_id: index for index, rule_id in enumerate(mail_lists.RULES)}
_GAP_ORDER = {name: index for index, name in enumerate(mail_lists.GAP_NAMES)}
_LINK_RULES = dict(mail_lists.LINK_FLAG_RULES)
_LINK_RULES[mail_lists.LINK_TEXT_MISMATCH_FLAG] = mail_lists.LINK_TEXT_MISMATCH_RULE


def _gap_hits(items: Sequence[Any], extra: Sequence[str]) -> Tuple[GapHit, ...]:
    """Every gap once per (name, detail), with the class and effect of the table."""
    counts: Dict[Tuple[str, str], int] = {}
    for item in items:
        name, detail, count = item.name, item.detail, item.count
        if name not in mail_lists.GAPS:
            name, detail = GAP_SCANNER_ERROR, mail_lists.DETAIL_NONE
        if detail not in mail_lists.GAP_DETAILS:
            detail = mail_lists.DETAIL_NONE
        counts[(name, detail)] = counts.get((name, detail), 0) + max(1, int(count))
    for name in extra:
        if name not in mail_lists.GAPS:
            name = GAP_SCANNER_ERROR
        key = (name, mail_lists.DETAIL_NONE)
        counts[key] = counts.get(key, 0) + 1
    out = []
    for (name, detail), count in sorted(counts.items(), key=lambda kv: (_GAP_ORDER[kv[0][0]], kv[0][1])):
        gap = mail_lists.GAPS[name]
        out.append(GapHit(name, gap.gap_class, gap.reply_effect, detail, count))
    return tuple(out)


def _finish(hits: Dict[str, int], gaps: Tuple[GapHit, ...], automated: bool, list_mail: bool,
            extra_held: bool, sender: mail_sender.SenderResult, target: Optional[str]) -> Decision:
    rule_hits = tuple(RuleHit(rule_id, mail_lists.RULES[rule_id].rule_class, count)
                      for rule_id, count in sorted(hits.items(), key=lambda kv: _RULE_ORDER[kv[0]])
                      if count > 0)
    classes = {hit.rule_class for hit in rule_hits} | {gap.gap_class for gap in gaps}
    if mail_lists.CLASS_BLOCK in classes:
        verdict = mail_lists.VERDICT_BLOCK
    elif mail_lists.CLASS_CAUTION in classes:
        verdict = mail_lists.VERDICT_CAUTION
    else:
        verdict = mail_lists.VERDICT_PASS

    if automated:
        return Decision(verdict, mail_lists.REPLY_NONE_AUTOMATED, mail_lists.REPLY_NONE_AUTOMATED, (),
                        rule_hits, gaps, sender, target)
    in_force = {mail_lists.RULES[hit.rule_id].hold for hit in rule_hits}
    in_force |= {mail_lists.GAPS[gap.name].hold for gap in gaps}
    if extra_held:
        in_force.add(mail_lists.HOLD_HELD)
    if verdict == mail_lists.VERDICT_BLOCK:
        in_force.add(mail_lists.HOLD_BLOCK)         # a block always holds the reply
    holds = tuple(kind for kind in mail_lists.HOLD_KINDS if kind in in_force)
    released = mail_lists.REPLY_NONE_LIST if list_mail else mail_lists.REPLY_DRAFT
    reply = mail_lists.REPLY_HELD if holds else released
    return Decision(verdict, reply, released, holds, rule_hits, gaps, sender, target)


def decide(parsed: Any, view: Any, config: Any, earlier_drafts: int = 0,
           extra_gaps: Sequence[str] = (), budget: Any = None) -> Decision:
    """The verdict and the reply decision for one scanned message. See the module text.

    `budget` is the wall-clock budget of the scan (`mail_reuse.Budget`). When it runs out
    here the message was not judged: the decision is the one of `error_decision` with the
    gap `structure-over-bound`, a block that no override turns into a draft.
    """
    settings = _read_config(config)
    if isinstance(earlier_drafts, bool) or not isinstance(earlier_drafts, int) or earlier_drafts < 0:
        raise ValueError(INPUT_ERROR)
    try:
        return _decide(parsed, view, settings, earlier_drafts, extra_gaps,
                       mail_reuse.NO_BUDGET if budget is None else budget)
    except mail_reuse.TimeUp:
        return error_decision(GAP_OVER_BOUND, mail_lists.BOUND_TIME)


def _decide(parsed: Any, view: Any, settings: _Config, earlier_drafts: int, extra_gaps: Sequence[str],
            budget: Any) -> Decision:
    headers = parsed.headers
    counts = view.counts
    hits: Dict[str, int] = {}

    def hit(rule_id: str, count: int) -> None:
        if count > 0:
            hits[rule_id] = hits.get(rule_id, 0) + count

    gaps = _gap_hits(tuple(parsed.gaps) + tuple(view.gaps), extra_gaps)
    header_texts = (headers.from_name, headers.subject)
    link_texts = tuple(link.url for link in parsed.links)

    # ---- block rules -----------------------------------------------------------------
    hit("header-ambiguous", sum(max(1, item.count) for item in parsed.header_ambiguous))
    hit("tag-characters", counts.tag_chars + sum(mail_reuse.TAG.count(mail_reuse.fold_flags(text or "")[0])
                                                 for text in header_texts + link_texts))
    hit("bidi-override", sum(mail_reuse.BIDI.count(text or "") for text in header_texts + link_texts))
    hit("from-name-address", _name_addresses_elsewhere(headers.from_name, headers.from_domain))
    budget.check_now()
    body_text = _without_scanner_lines(view.visible_text)
    # `<s>` and `</s>` in the body count only when a text/plain part was selected
    plain_part = any(part.subtype == mail_lists.SELECTED_PLAIN for part in parsed.selected)
    hit("control-token", _most(_count_control_tokens if plain_part else _count_control_tokens_html, (body_text,))
        + _most(_count_control_tokens, header_texts))
    hit("frame-forgery", _most(_count_frame_forgery, (body_text,) + header_texts))
    budget.check_now()
    hit("attachment-dangerous", sum(1 for item in parsed.attachments if _is_dangerous(item)))
    hit("attachment-active-content", sum(1 for item in parsed.attachments
                                         if _is_active_content(item) and not _is_dangerous(item)))
    hit("attachment-type-mismatch", sum(1 for item in parsed.attachments if _type_disagrees(item)))
    for link in parsed.links:
        for flag in link.flags:
            hit(_LINK_RULES[flag], 1)           # block and caution flags alike
    budget.check_now()
    hit("hidden-phrase", _count_phrases(mail_lists.HIDDEN_PHRASES, view.removed_hidden))
    budget.check_now()

    # ---- caution rules ---------------------------------------------------------------
    if counts.hidden_chars > mail_lists.PREHEADER_ALLOWANCE_CHARS:
        hit("hidden-text", counts.hidden_chars)
    hit("uncertain-removal", counts.uncertain_chars or (1 if view.warning else 0))
    # fix round 3 (S11): a part that lost a large share of its text to doubt holds the reply
    hit("uncertain-share", getattr(view, "uncertain_share_parts", 0))
    # A bidirectional control is a format character too; one in the body is stripped and
    # counted here, one in the From name, the Subject or a link is the block above.
    unseen = getattr(view, "unseen_chars", 0)
    hit("format-characters", counts.format_chars + counts.bidi_chars + unseen
        + sum(len(mail_reuse.invisible_offsets(text or "")) - mail_reuse.TAG.count(text or "")
              - mail_reuse.BIDI.count(text or "") for text in header_texts + link_texts))
    # A few such characters come with ordinary writing; a run of them is a hidden channel.
    if unseen > mail_lists.UNSEEN_HOLD_OVER:
        hit("unseen-characters", unseen)
    sender = mail_sender.verify(headers.authentication_results, headers.from_domain, settings.authserv_id)
    if sender.status != mail_sender.SENDER_VERIFIED:
        hit("sender-unverified", 1)
    if sender.dmarc_fail:
        hit("dmarc-fail", 1)
    if getattr(sender, "header_unread", False):
        hit("auth-header-unreadable", 1)        # fix round 3 (B1)
    if headers.from_name_irregular:
        hit(mail_lists.FROM_NAME_IRREGULAR_RULE, 1)
    # An image a related message shows in its text is part of that text, not an attachment.
    hit("attachment-present", sum(1 for item in parsed.attachments if not _is_image_resource(item)))
    hit("link-unreadable", counts.links_unlisted)
    hit("role-label", len(mail_lists.ROLE_LABEL_LINE.findall(view.visible_text)))
    hit("comment-conditional", counts.conditional_comments)
    hit("hidden-phrase-weak", _count_phrases(mail_lists.HIDDEN_PHRASES_WEAK, view.removed_hidden))
    hit("inbound-secret", counts.secrets_masked)
    image_parts = sum(1 for item in tuple(parsed.attachments) + tuple(parsed.parts)
                      if (getattr(item, "media_type", "") or "").startswith(_IMAGE_TYPE_PREFIX))
    if parsed.attachment_only or (counts.visible_letters < mail_lists.IMAGE_ONLY_MAX_VISIBLE_LETTERS
                                  and (counts.images > 0 or image_parts > 0)):
        hit("image-only", 1)

    # ---- reply rules -----------------------------------------------------------------
    if headers.auto_submitted == mail_lists.AUTO_SUBMITTED_AUTO:
        hit("reply-auto-submitted", 1)
    if headers.return_path == mail_lists.RETURN_PATH_NULL:
        hit("reply-null-return-path", 1)
    if headers.from_local is not None and mail_lists.NO_REPLY_LOCAL_PART.search(headers.from_local.strip()):
        hit("reply-no-reply-sender", 1)
    if headers.auto_response_suppress:
        hit("reply-auto-response-suppress", 1)
    address = headers.from_address.strip() if isinstance(headers.from_address, str) else None
    if address and address.lower() in settings.own_addresses:
        hit("reply-own-address", 1)
    hit("reply-list", int(bool(headers.list_id_present)) + int(bool(headers.list_unsubscribe_present))
        + int(headers.precedence in mail_lists.LIST_PRECEDENCE_VALUES))
    if earlier_drafts >= mail_lists.BUDGET_EARLIER_DRAFTS:
        hit("reply-budget", 1)

    automated = any(mail_lists.RULES[rule_id].reply == mail_lists.REPLY_NONE_AUTOMATED for rule_id in hits)
    extra_held = counts.uncertain_chars > mail_lists.UNCERTAIN_HOLD_CHARS
    target = settings.reply_to_map.get(address.lower(), address) if address else None
    return _finish(hits, gaps, automated, "reply-list" in hits, extra_held, sender, target)


class _TimeGap(NamedTuple):
    name: str
    detail: str
    count: int


def error_decision(gap: str = GAP_SCANNER_ERROR, detail: str = mail_lists.DETAIL_NONE) -> Decision:
    """The decision for a message that could not be judged: a block that no override turns into a draft.

    For the one handler that catches a failure of the scanner, and for a scan whose time
    ran out inside the rules. The verdict is block, the reply is held under the hold
    `block`, and `reply_if_released` is held as well, because nobody read the message:
    lifting the block must not produce a draft.
    """
    gaps = _gap_hits((_TimeGap(gap, detail, 1),), ()) if detail else _gap_hits((), (gap,))
    sender = mail_sender.SenderResult(mail_sender.SENDER_UNVERIFIED, mail_sender.REASON_NO_FROM, False, False)
    return Decision(mail_lists.VERDICT_BLOCK, mail_lists.REPLY_HELD, mail_lists.REPLY_HELD,
                    (mail_lists.HOLD_BLOCK,), (), gaps, sender, None)
