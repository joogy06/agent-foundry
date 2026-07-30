#!/usr/bin/env python3
"""skill_overlap.py — S073. Measure description overlap across the skill library.

Skill selection matches a task against the `description:` frontmatter. As the library
grows those descriptions collide, and the selector has no way to tell two near-identical
skills apart. This module measures that collision so it can be managed rather than
discovered by a bad selection.

Two distinct kinds of collision show up, and they need different remedies:

  * Environment-discriminated — e.g. `rhel-web-servers` vs `ubuntu-web-servers` (0.89).
    Near-identical BY DESIGN; the discriminator is a host fact, not text. Remedy is an
    `applies_when:` field the resolver evaluates mechanically. No amount of description
    tuning helps, because the selector is reading the wrong source.
  * Semantic neighbours — e.g. `qa-reviewer` vs `ux-reviewer` (0.50). Remedy is a
    `disambiguation:` line naming the neighbour and the boundary.

The measurement IS the worklist: annotate only the skills with a measured collision,
against their measured neighbour. Not a whole-library metadata project.

Drift control: a baseline file pins the ACCEPTED pairs. Re-running flags only NEW
collisions, so overlap debt cannot silently accumulate. Wire into alf sweeps.

Stdlib only (no numpy/sklearn) — same constraint gates.py and scope_delta.py observe,
so this runs on a minimal environment.

Public API (stable):
    collect_descriptions(skills_root) -> dict[str, str]
    tfidf(docs) -> dict[str, dict[str, float]]
    cosine(va, vb) -> float
    find_pairs(vectors, threshold) -> list[tuple[float, str, str]]
    load_baseline(path) -> set[tuple[str, str]]
    main(argv) -> int

Exit codes (house convention: 0 pass / 2 block):
    0 — no NEW pairs above threshold
    2 — new pairs found (or an unreadable baseline)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

DEFAULT_THRESHOLD = 0.30
DEFAULT_SKILLS_ROOT = Path.home() / ".claude" / "skills"
DEFAULT_BASELINE = Path(__file__).resolve().parent / "skill-overlap-baseline.json"

# Deliberately small. An aggressive stoplist would strip the domain words that carry
# the discriminating signal ("docker", "trading"), so only structural filler is removed.
STOPWORDS = {
    "use", "when", "the", "a", "an", "and", "or", "to", "for", "of", "in", "on",
    "with", "is", "are", "this", "that", "it", "as", "by", "from", "any", "all",
    "be", "can", "not", "you", "your", "also", "trigger", "using", "used", "into",
    "its", "their", "them", "then", "than", "via", "per", "each", "both", "how",
}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)
# description: runs until the next top-level YAML key or end of frontmatter.
_DESCRIPTION_RE = re.compile(r"^description:\s*(.+?)(?=\n[a-zA-Z_-]+:|\Z)", re.S | re.M)
_TOKEN_RE = re.compile(r"[a-z][a-z-]{2,}")


def _read_frontmatter(path: Path) -> str:
    """Return raw frontmatter text, or '' when the file has none."""
    try:
        head = path.read_text(errors="ignore")[:8192]
    except OSError:
        return ""
    m = _FRONTMATTER_RE.match(head)
    return m.group(1) if m else ""


def collect_descriptions(skills_root: Path) -> Dict[str, str]:
    """Map skill-directory-name -> its frontmatter description.

    Skills without frontmatter or without a description are skipped: they carry no
    selection signal, so they cannot collide.
    """
    out: Dict[str, str] = {}
    if not skills_root.is_dir():
        return out
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        fm = _read_frontmatter(skill_md)
        if not fm:
            continue
        m = _DESCRIPTION_RE.search(fm)
        if not m:
            continue
        desc = " ".join(m.group(1).split()).strip().strip("\"'")
        if desc:
            out[skill_md.parent.name] = desc
    return out


def _tokens(text: str) -> List[str]:
    return [w for w in _TOKEN_RE.findall(text.lower()) if w not in STOPWORDS]


def tfidf(docs: Dict[str, str]) -> Dict[str, Dict[str, float]]:
    """L2-normalised tf-idf vectors, one per doc.

    Uses SMOOTHED idf — log((n+1)/(df+1)) + 1 — not the textbook log(n/df). With the
    plain form, a term present in every document gets idf log(n/n) = 0, so on a small
    corpus (n=2, both docs sharing their vocabulary) every weight collapses to zero and
    two near-identical skills score 0.00 — the tool reports clean on exactly the case it
    exists to catch. The +1 smoothing floors idf at 1.0 instead. Harmless at n=197,
    load-bearing on a subset.

    Terms appearing in only one document are dropped: they are absent from the other
    vector, so they contribute zero to every pairwise cosine regardless. That is a speed
    optimisation, not a scoring change.
    """
    counts = {name: Counter(_tokens(text)) for name, text in docs.items()}
    n = len(counts)
    if n == 0:
        return {}
    df: Counter = Counter()
    for c in counts.values():
        df.update(c.keys())

    vectors: Dict[str, Dict[str, float]] = {}
    for name, c in counts.items():
        v = {
            term: (1 + math.log(freq)) * (math.log((n + 1) / (df[term] + 1)) + 1)
            for term, freq in c.items()
            if df[term] > 1
        }
        norm = math.sqrt(sum(x * x for x in v.values()))
        vectors[name] = {t: x / norm for t, x in v.items()} if norm else {}
    return vectors


def cosine(va: Dict[str, float], vb: Dict[str, float]) -> float:
    """Cosine of two L2-normalised sparse vectors (plain dot product)."""
    if len(va) > len(vb):
        va, vb = vb, va
    return sum(x * vb.get(term, 0.0) for term, x in va.items())


def find_pairs(
    vectors: Dict[str, Dict[str, float]], threshold: float = DEFAULT_THRESHOLD
) -> List[Tuple[float, str, str]]:
    """All pairs scoring at or above threshold, highest first."""
    pairs = [
        (score, a, b)
        for a, b in combinations(sorted(vectors), 2)
        if (score := cosine(vectors[a], vectors[b])) >= threshold
    ]
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    return pairs


def _key(a: str, b: str) -> Tuple[str, str]:
    """Order-independent pair key, so a/b and b/a are the same accepted pair."""
    return (a, b) if a <= b else (b, a)


def load_baseline(path: Path) -> Set[Tuple[str, str]]:
    """Accepted pairs. A missing baseline is legal and means 'nothing accepted yet'."""
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    return {_key(p["a"], p["b"]) for p in data.get("accepted_pairs", [])}


def write_baseline(path: Path, pairs: Iterable[Tuple[float, str, str]], threshold: float) -> None:
    payload = {
        "schema": "skill-overlap-baseline.v1",
        "threshold": threshold,
        "_comment": (
            "Accepted description-overlap pairs. Re-running skill_overlap.py flags only "
            "NEW pairs. Adding a pair here asserts the collision is understood and "
            "handled (via applies_when: or disambiguation:), not that it is harmless."
        ),
        "accepted_pairs": [
            {"a": a, "b": b, "score": round(score, 4)} for score, a, b in pairs
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def _has_boundary(skills_root: Path, name: str) -> bool:
    """True when the skill declares something that distinguishes it from a neighbour.

    Deliberately shallow: presence, not quality. `applies_when:` counts because an
    environment-discriminated pair (rhel/ubuntu) is resolved mechanically against the
    env-adoption inventory and needs no prose at all.
    """
    fp = Path(skills_root) / name / "SKILL.md"
    try:
        raw = fp.read_text(encoding="utf-8")
    except OSError:
        return False
    if not raw.startswith("---"):
        return False
    end = raw.find("\n---", 3)
    front = raw[3:end if end > 0 else len(raw)]
    return any(line.startswith(("disambiguation:", "applies_when:")) for line in front.splitlines())


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure skill description overlap.")
    ap.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS_ROOT)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--top", type=int, default=0, help="print only the N highest pairs")
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite the baseline to accept every current pair, then exit 0",
    )
    args = ap.parse_args(argv)

    docs = collect_descriptions(args.skills_root)
    if not docs:
        print(f"skill_overlap: no skills with descriptions under {args.skills_root}", file=sys.stderr)
        return 2

    pairs = find_pairs(tfidf(docs), args.threshold)

    if args.update_baseline:
        # A pair may only be accepted once SOMETHING distinguishes its members. The scanner
        # can verify a `disambiguation:` (or `applies_when:`) EXISTS; it can never judge
        # whether the sentence is any good — that stays a human act. But baselining a pair
        # where neither skill says anything about its neighbour is pure suppression, and a
        # baseline that can absorb undifferentiated pairs silently turns into a snooze
        # button on the exact signal it was built to raise.
        undifferentiated = [
            (a, b) for _, a, b in pairs
            if not (_has_boundary(args.skills_root, a) or _has_boundary(args.skills_root, b))
        ]
        if undifferentiated:
            print(
                f"skill_overlap: refusing to baseline {len(undifferentiated)} pair(s) where neither "
                f"skill declares a boundary. Add `disambiguation:` (or `applies_when:`) first:",
                file=sys.stderr,
            )
            for a, b in undifferentiated:
                print(f"  {a}  <->  {b}", file=sys.stderr)
            return 2
        write_baseline(args.baseline, pairs, args.threshold)
        print(f"skill_overlap: baseline updated — {len(pairs)} pair(s) accepted at >= {args.threshold}")
        return 0

    try:
        accepted = load_baseline(args.baseline)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        # Fail closed: an unreadable baseline must not read as "nothing new".
        print(f"skill_overlap: baseline unreadable ({exc}) — refusing to report clean", file=sys.stderr)
        return 2

    new_pairs = [p for p in pairs if _key(p[1], p[2]) not in accepted]

    if args.json:
        print(json.dumps({
            "skills_scanned": len(docs),
            "threshold": args.threshold,
            "total_pairs": len(pairs),
            "accepted_pairs": len(accepted),
            "new_pairs": [{"a": a, "b": b, "score": round(s, 4)} for s, a, b in new_pairs],
        }, indent=2))
    else:
        shown = pairs[: args.top] if args.top else pairs
        print(f"skills scanned: {len(docs)}   pairs >= {args.threshold}: {len(pairs)}   new: {len(new_pairs)}\n")
        for score, a, b in shown:
            mark = "NEW " if _key(a, b) not in accepted else "    "
            print(f"  {mark}{score:.2f}  {a}  <->  {b}")
        if new_pairs:
            print(
                f"\n{len(new_pairs)} new collision(s). Resolve with `applies_when:` "
                f"(environment-discriminated) or `disambiguation:` (semantic neighbours), "
                f"then re-run with --update-baseline."
            )

    return 2 if new_pairs else 0


if __name__ == "__main__":
    raise SystemExit(main())
