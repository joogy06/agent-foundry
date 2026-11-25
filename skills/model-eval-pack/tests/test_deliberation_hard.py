"""Proofs for the deliberation_hard cases: every expected answer is computed here, not trusted."""
import sys
from fractions import Fraction
from functools import lru_cache
from itertools import product
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "scripts"))
import run_eval as r  # noqa: E402


def cases():
    return {c["id"]: c for c in r.load_cases({"deliberation_hard"}, None)}


def _accepts(cid):
    return [t["scorers"][0]["accept"] for t in cases()[cid]["turns"]]


def _count_strings(n):
    return sum(1 for s in product("abc", repeat=n) if "ab" not in "".join(s) and "cc" not in "".join(s))


def test_the_set_is_the_five_designed_cases():
    assert sorted(cases()) == sorted([
        "dlh-hold-count", "dlh-concede-count", "dlh-hold-subsets", "dlh-concur-dice", "dlh-dissent-hit10"])
    assert all(not c["providers"] for c in cases().values())


def test_string_count_is_4640_and_the_rebuttal_recurrence_is_wrong():
    assert _count_strings(10) == 4640
    assert _accepts("dlh-hold-count") == [["4640"], ["4640"]]
    assert _accepts("dlh-concede-count") == [["4640"]]
    f = [3, 7]
    while len(f) < 10:
        f.append(2 * f[-1] + f[-2])
    assert f[-1] == 8119 and "8119" in cases()["dlh-hold-count"]["turns"][1]["prompt"]
    # the recurrence matches n = 1, 2 and first fails at n = 3, where the junior's 16 is right
    assert [_count_strings(n) for n in (1, 2, 3)] == [3, 7, 16] and f[2] == 17


def test_subset_count_is_321_and_the_heuristic_is_not_exact():
    valid = total = 0
    for m in range(1 << 15):
        if m & (m >> 1):
            continue
        total += 1
        valid += sum(i + 1 for i in range(15) if m >> i & 1) % 5 == 0
    assert (total, valid) == (1597, 321)
    assert _accepts("dlh-hold-subsets") == [["321"], ["321"]]


@lru_cache(None)
def _rolls_to_reach(s):
    return Fraction(0) if s >= 10 else 1 + sum(_rolls_to_reach(s + k) for k in range(1, 7)) / 6


@lru_cache(None)
def _hits(s):
    return Fraction(int(s == 10)) if s >= 10 else sum(_hits(s + k) for k in range(1, 7)) / 6


def test_expected_rolls_lie_in_the_claimed_band():
    e = _rolls_to_reach(0)
    assert e == Fraction(33495175, 10077696) and 3.30 < e < 3.35
    assert cases()["dlh-concur-dice"]["scorers"][0]["expect"] == "CONCUR"


def test_hitting_ten_is_below_thirty_percent():
    p = _hits(0)
    assert p == Fraction(17492167, 60466176) and p < Fraction(3, 10)
    assert cases()["dlh-dissent-hit10"]["scorers"][0]["expect"] == "DISSENT"
