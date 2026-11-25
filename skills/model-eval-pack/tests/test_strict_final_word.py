"""#367 WP-C (M-a): the strict FINAL scorer counts the WORD `final`, not only `FINAL:`.

Fix round 2 counted `FINAL\\s*:` only, so `Final answer: 20` beside the real `FINAL: 24` passed (a
second final answer the scorer could not see), and a closing `---` after the FINAL line failed (the
rule rejects anything after the FINAL line). Now the output is NFKC-normalised with format characters
removed, horizontal-rule lines are ignored, and `\\bfinal\\b` must occur exactly once, case-insensitively.
"""
import sys
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "scripts"))
import run_eval as r  # noqa: E402

STRICT = {"type": "final", "accept": ["24"], "strict": True}
CTX: dict = {}


@pytest.mark.parametrize("out", [
    "Final answer: 20\nFINAL: 24",            # M-a repro 1: a second final answer without `FINAL:`
    "My final answer is 20.\nFINAL: 24",      # the word anywhere counts
    "FINAL ANSWER - 20\nFINAL: 24",
    "F\u200bINAL: 20\nFINAL: 24",             # a zero-width space cannot hide a second FINAL
    "FIN\u00adAL: 20\nFINAL: 24",             # nor a soft hyphen
    "\uff26\uff29\uff2e\uff21\uff2c: 20\nFINAL: 24",  # nor full-width letters (NFKC folds them)
    "FINAL: 24\n---\nActually 20.",           # a rule is ignored, the text after it is not
])
def test_a_second_final_word_fails(out):
    assert r._strict_final(out) is None, out
    assert not r.score_one(STRICT, out, CTX), out


@pytest.mark.parametrize("out", [
    "FINAL: 24\n---",                          # M-a repro 2: a closing horizontal rule
    "FINAL: 24\n***\n",
    "Reasoning.\n\n- - -\n\nFINAL: 24\n___",
    "semifinal: 3 rounds\nFINAL: 24",          # `semifinal` is not the word final
    "Finally, counting multiples of 5 and 25:\nFINAL: 24",   # nor is `finally`
    "\ufeffFINAL: 24",                         # a BOM is a format character, removed
])
def test_a_single_final_word_passes(out):
    assert r._strict_final(out) == "24", out
    assert r.score_one(STRICT, out, CTX), out


def test_the_lenient_final_scorer_is_unchanged():
    lenient = {"type": "final", "accept": ["24"]}
    assert r.score_one(lenient, "Final answer: 20\nFINAL: 24", CTX)
