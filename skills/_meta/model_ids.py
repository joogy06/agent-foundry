"""model_ids.py - THE one model-id normaliser for benched-family matching (#291). PURE.

Nothing here reads the roster, checks an invariant, touches the filesystem or imports
another harness module, so importing it cannot fail on a bad roster edit. That is the point:
seat_model.is_benched delegates here, and smart-config's resolver imports this module
DIRECTLY, so a roster that breaks seat_model's import-time invariants (which makes every
seat_model importer fail closed) still leaves the benched refusal working (#291 fix round 1,
finding A). workflows/bob-serial-exec.js carries the JavaScript twin (idTokens /
isBenchedModel); a parity test runs both over the same spellings.

THE RULE (design s3.2, widened in fix round 1, findings F and G, and fix round 2, N4 and N5)
  1. Remove every bracketed or parenthesised group, ANYWHERE in the id, leaving a separator:
     "fable[1m]", "fable[1m][1m]", "claude-fable[1m]-5-1", "fable[1m]5" and "fable(1m)" all
     carry the token "fable" (N4). A group is "[" to the next "]" or "(" to the next ")".
  2. Lowercase ASCII A-Z only, then split on every run of characters outside ASCII [a-z0-9].
     The separator set is EXPLICIT (N5), not "whitespace" as a regex engine or str.strip /
     String.trim defines it: those disagree between Python and JavaScript on BOM, U+0085,
     U+001C and friends. Every such character, and every punctuation mark ("-", "_", ".",
     "/", "@", ":", "+", a stray bracket, ...) is a separator, identically in both twins.
     So "claude-fable-5-1", "claude_fable", "claude.fable.5", "Fable 5.1", "vendor/fable"
     and "\ufefffable" all carry the token "fable". Separating on MORE characters can only
     refuse more; removing bracket groups (step 1) can refuse LESS - "[fable]", "(fable)" and
     "opus[fable]" carry no fable token. That is deliberate: a group is a context suffix, and
     no Claude surface accepts a family spelled inside brackets.
  3. A family is benched in an id when the family's tokens occur as a contiguous run of the
     id's tokens. The LAST family token may carry a version glued straight on, as ASCII
     digits only: "fable5" is the fable family, "fable5x", "fablex", "fables" and "5fable"
     are not. A glued digit suffix is a version; a glued letter makes a different word.
Anything that is not a string is never benched.
"""

import re

#: A bracketed or parenthesised group anywhere, such as a "[1m]" context suffix (N4).
_GROUPS = re.compile(r"\[[^\]]*\]|\([^)]*\)")
#: ASCII-only lowercasing: str.lower() and String.toLowerCase() differ outside ASCII
#: (U+212A KELVIN SIGN lowers to "k" in both, others do not agree), so neither is used.
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
#: Every separator: any run of characters outside ASCII [a-z0-9] (N5).
_SEPARATORS = re.compile(r"[^a-z0-9]+")
#: A version glued onto a family token: ASCII digits only.
_GLUED_VERSION = re.compile(r"[0-9]+")


def id_tokens(model_id):
    """The lowercase ASCII tokens of a model id, every bracketed group removed."""
    if not isinstance(model_id, str):
        return []
    text = _GROUPS.sub(" ", model_id).translate(_ASCII_LOWER)
    return [t for t in _SEPARATORS.split(text) if t]


def _token_matches(have, want, last):
    if have == want:
        return True
    return last and have.startswith(want) and _GLUED_VERSION.fullmatch(have[len(want):]) is not None


def is_benched(model_id, families):
    """True when `model_id` names one of `families` under the rule in the module docstring.

    `families` is required here (an iterable of family strings); the roster default lives in
    seat_model.is_benched, which is the entry point everything but smart-config calls.
    """
    have = id_tokens(model_id)
    if not have:
        return False
    for family in families or ():
        want = id_tokens(family)
        span = len(want)
        if not span:
            continue
        for i in range(len(have) - span + 1):
            if all(_token_matches(have[i + j], want[j], j == span - 1) for j in range(span)):
                return True
    return False
