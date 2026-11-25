#!/usr/bin/env python3
"""claims_lint.py — find facts that live in more than one skill and have drifted apart.

The decay mode this catches (observed 2026-07-26): the SAME fact about `FAQPage`
lived in three skills in three different states of staleness — one said CRITICAL,
two still described the superseded Aug-2023 position. A review caught one of them.

Duplication alone is not a defect. Duplication that DISAGREES is, and duplication
is what makes disagreement possible — so both are reported, at different severities.

Deterministic, stdlib-only, no network.

`--root` and `--skills` are global options and go BEFORE the subcommand:

    claims_lint.py [--root ~/.claude/skills] [--skills a,b,c] subjects [--min-files 2]
    claims_lint.py [--root ...] [--skills ...] drift [--min-files 2] [--fail-on-drift]
    claims_lint.py [--root ...] [--skills ...] stale [--months 12]
    claims_lint.py [--root ...] [--skills a,b] unsourced [--family seo] [--fail-on-warn]

`unsourced` (added 2026-09-27) catches the decay contradiction-checking cannot: the SAME
unsourced number copied into several skills agrees with itself, so `drift` reports it clean
while every copy is equally stale. A percentage ("12%", "12 percent") or multiplier ("2.3x",
"3×") with no URL, V/I label, `heuristic` or FORECAST marker, or source-like date ("(Ahrefs,
2025)", "Mar 2026", "2026-09", "Q1 2025"; a bare year does not count) on its line is a WARN.
A table row counts as one line, so an adjacent cell sources it. Exit 3 when nothing is
selected or a --skills entry has no SKILL.md.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

#: Backticked identifiers are how these skills name facts (`FAQPage`, `Google-Extended`).
SUBJECT_RE = re.compile(r"`([A-Za-z][A-Za-z0-9_.\-]{2,40})`")

#: Generic words that appear in backticks as formatting, not as named facts.
SUBJECT_STOPWORDS = frozenset({
    "high", "medium", "low", "critical", "priority", "true", "false", "none",
    "null", "yes", "no", "auto", "default", "strict", "advisory", "error",
})

#: Words that make a line a CLAIM about status rather than a passing mention.
STATUS_WORDS = (
    "deprecat", "removed", "retired", "discontinu", "shut down", "sunset",
    "no longer", "restricted", "critical", "high", "medium", "low",
    "still", "supported", "unsupported", "dead", "legacy", "superseded",
)

#: Verdict-bearing tokens, split into two MUTUALLY EXCLUSIVE stances.
#:
#: Naive token-disjointness was wrong in both directions: it called
#: "LOW" vs "deprecated" a contradiction (they agree — low BECAUSE dead), while
#: missing "CRITICAL — still supported" vs "fully deprecated" whenever the two
#: claims shared any other token. What actually contradicts is a subject asserted
#: ALIVE in one place and DEAD in another.
ALIVE_TOKENS = ("critical", "supported", "still supported", "current")
DEAD_TOKENS = (
    "deprecated", "removed", "retired", "discontinued", "dead",
    "unsupported", "sunset", "no longer",
)
#: Priority words carry no aliveness claim on their own — a LOW-priority schema
#: and a deprecated schema are the same statement said two ways.
VERDICT_TOKENS = ALIVE_TOKENS + DEAD_TOKENS

DATE_RE = re.compile(r"\b(20\d{2})[-/ ]?(0[1-9]|1[0-2])?\b")
NOISE = re.compile(r"[^a-z0-9 ]+")


def iter_skills(root: Path, only: set[str] | None):
    for p in sorted(root.glob("*/SKILL.md")):
        if only and p.parent.name not in only:
            continue
        yield p.parent.name, p


#: A line that ROUTES to another skill is the fix for duplication, not an instance
#: of it. Counting pointers as competing claims penalises exactly the structure we
#: want, and made the linter flag its own remediation as a new problem.
POINTER_RE = re.compile(
    r"(?:\bsee\b|\bcanonical\b|\bowner\b|\bowned elsewhere\b|→|->|"
    r"\bdoes not restate\b|\brefer to\b|\bpoints? at\b|\blives? in\b)",
    re.IGNORECASE,
)


def claim_lines(text: str, skill_names: frozenset[str] = frozenset()):
    """Yield (lineno, line) for lines that ASSERT a status about a subject.

    Skips cross-references: a line telling the reader where the fact lives is a
    pointer, not a second owner of it.
    """
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # Blockquotes are commentary — rationale, warnings, history. The normative
        # claim lives in the table row or bullet. Parsing prose as a claim made the
        # linter flag sentences that merely DESCRIBED a past contradiction (e.g. a
        # note explaining that `FAQPage` once read "gov/health only") as a live
        # second owner of the fact.
        if stripped.startswith(">"):
            continue
        low = line.lower()
        if not (any(w in low for w in STATUS_WORDS) and SUBJECT_RE.search(line)):
            continue
        if POINTER_RE.search(line):
            continue
        yield i, stripped


def verdicts(line: str) -> set[str]:
    """Verdict tokens as standalone words only.

    Substring matching produced false positives: "high" inside "high-cardinality",
    "low" inside "below". A verdict must stand alone and must not be the head of a
    hyphenated compound ("high-cardinality" is a property, not a priority).
    """
    low = line.lower()
    found = set()
    for t in VERDICT_TOKENS:
        for m in re.finditer(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", low):
            found.add(t)
            break
    return found


def normalise(line: str) -> str:
    return NOISE.sub(" ", line.lower()).strip()


def collect(root: Path, only: set[str] | None):
    """subject -> [(skill, lineno, line)]"""
    # A SKILL NAME in backticks is a routing target, never a fact under dispute.
    # Without this, `woocommerce-faceted-navigation` and `seo-structure-architect`
    # were themselves reported as duplicated "subjects" purely because several
    # skills correctly referred to them.
    skill_names = frozenset(p.parent.name for p in root.glob("*/SKILL.md"))

    index: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for skill, path in iter_skills(root, only):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in claim_lines(text):
            subjects = {
                s for s in SUBJECT_RE.findall(line)
                if s not in skill_names and s.lower() not in SUBJECT_STOPWORDS
            }
            # A verdict can only be ATTRIBUTED to a subject when the line names
            # exactly one. A sentence mentioning `agy` while stating that a
            # DIFFERENT tool was retired otherwise reads as "agy is retired".
            attributable = len(subjects) == 1
            for subj in subjects:
                index[subj].append((skill, lineno, line, attributable))
    return index


def cmd_subjects(a) -> int:
    index = collect(Path(a.root).expanduser(), set(a.skills.split(",")) if a.skills else None)
    multi = {s: v for s, v in index.items() if len({x[0] for x in v}) >= a.min_files}
    if not multi:
        print("no subject is claimed in more than one skill")
        return 0
    print(f"{len(multi)} subject(s) claimed in >= {a.min_files} skills\n")
    for subj in sorted(multi, key=lambda s: -len({x[0] for x in multi[s]})):
        owners = sorted({x[0] for x in multi[subj]})
        print(f"  {subj:24s} {len(owners)} owners: {', '.join(owners)}")
    return 0


def cmd_drift(a) -> int:
    index = collect(Path(a.root).expanduser(), set(a.skills.split(",")) if a.skills else None)
    drifted, duplicated = [], []

    for subj, entries in sorted(index.items()):
        by_skill: dict[str, list[tuple[int, str]]] = defaultdict(list)
        attributable_lines: set[tuple[str, int]] = set()
        for skill, lineno, line, attributable in entries:
            by_skill[skill].append((lineno, line))
            if attributable:
                attributable_lines.add((skill, lineno))
        seen_verdicts = {sk: set().union(*(verdicts(l) for _, l in v)) for sk, v in by_skill.items()}
        # A subject is contradicted when ANY claim asserts it ALIVE while ANY other
        # asserts it DEAD. Evaluated per LINE and across the whole subject — not
        # pairwise between skills — so a file that contradicts ITSELF (one table
        # "CRITICAL — still supported", another "fully deprecated") is caught too.
        alive_claims, dead_claims = [], []
        for skill, rows in by_skill.items():
            for lineno, line in rows:
                v = verdicts(line)
                if (skill, lineno) not in attributable_lines:
                    continue
                if v & set(ALIVE_TOKENS):
                    alive_claims.append((skill, lineno))
                if v & set(DEAD_TOKENS):
                    dead_claims.append((skill, lineno))
        # A single line carrying BOTH stances is almost always describing a
        # transition ("X retired; Y is current"), not contradicting itself. Require
        # the two stances to come from DIFFERENT lines.
        # Correct rule: an ALIVE claim on one line and a DEAD claim on a DIFFERENT
        # line. Set-subtraction was wrong — a row may legitimately carry both
        # ("CRITICAL ... rich result removed"), and subtracting erased the very
        # contradiction it was meant to find.
        alive_locs, dead_locs = set(alive_claims), set(dead_claims)
        contradiction = any(a != d for a in alive_locs for d in dead_locs)
        # min_files gates the DUPLICATION report only. A contradiction is a defect
        # even inside a single file, so it is never suppressed by owner count.
        if not contradiction and len(by_skill) < a.min_files:
            continue
        norms = {normalise(l) for v in by_skill.values() for _, l in v}
        (drifted if contradiction else duplicated).append((subj, by_skill, seen_verdicts, len(norms)))

    if drifted:
        print("=" * 78)
        print(f"DRIFT — {len(drifted)} subject(s): one fact, multiple owners, DISAGREEING verdicts")
        print("=" * 78)
        for subj, by_skill, sv, _ in drifted:
            print(f"\n  {subj}")
            for skill in sorted(by_skill):
                v = ", ".join(sorted(sv[skill])) or "-"
                for lineno, line in by_skill[skill][:2]:
                    print(f"    [{v}] {skill}:{lineno}")
                    print(f"        {line[:120]}")

    if duplicated and a.show_duplicates:
        print("\n" + "=" * 78)
        print(f"DUPLICATION — {len(duplicated)} subject(s): agreeing today, free to drift tomorrow")
        print("=" * 78)
        for subj, by_skill, _, nvariants in duplicated:
            print(f"  {subj:24s} {len(by_skill)} owners, {nvariants} phrasing(s): {', '.join(sorted(by_skill))}")

    print()
    if drifted:
        print(f"RESULT: {len(drifted)} drifted, {len(duplicated)} duplicated-but-consistent.")
        print("Each drifted subject needs ONE owner; the others must point at it.")
        return 1 if a.fail_on_drift else 0
    print(f"RESULT: no contradictions. {len(duplicated)} subject(s) duplicated without disagreement.")
    return 0


def cmd_stale(a) -> int:
    root = Path(a.root).expanduser()
    today = date.today()
    hits = []
    for skill, path in iter_skills(root, set(a.skills.split(",")) if a.skills else None):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in claim_lines(text):
            for m in DATE_RE.finditer(line):
                yr = int(m.group(1))
                mo = int(m.group(2)) if m.group(2) else 1
                age = (today.year - yr) * 12 + (today.month - mo)
                if age >= a.months:
                    hits.append((age, skill, lineno, line))
                    break
    if not hits:
        print(f"no dated status claims older than {a.months} months")
        return 0
    print(f"{len(hits)} dated status claim(s) older than {a.months} months — re-verify:\n")
    for age, skill, lineno, line in sorted(hits, reverse=True):
        print(f"  {age:3d}mo  {skill}:{lineno}")
        print(f"         {line[:120]}")
    return 0


#: A statistic: a percentage ("15-48%", "+7.3 %", "12 percent", "12 Percent": the words match in
#: any case) or a multiplier ("2.3x",
#: "10X", "3×"). "1200x630px" is a size, not a multiplier: the x must not be followed by a
#: word character.
STAT_RE = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?\s?(?:%|(?i:percent|per\s+cent)\b)"
    r"|(?<![\w.])\d+(?:\.\d+)?[xX\u00d7](?!\w)")
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
#: What sources a statistic on the same line: a URL, a V/I evidence label, a declared
#: operating heuristic, a FORECAST label, or a date in SOURCE-LIKE form. A bare year is not a
#: source ("In 2025 titles earned 33% more"); these are: "(Ahrefs, 2025)", "Mar 2026",
#: "2026-09-27" / "2026-09", "Q1 2025".
SOURCE_RE = re.compile(
    r"https?://|\[(?:V|I)[\],\s]|\bheuristic\b|\bFORECAST\b"
    r"|,\s*(?:19|20)\d{2}\s*\)"
    rf"|\b{_MONTH}\.?\s+(?:19|20)\d{{2}}\b"
    r"|\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])(?:-\d{2})?\b"
    r"|\bQ[1-4]\s+(?:19|20)\d{2}\b")
FAMILY_RE = re.compile(r"^family:\s*(.+?)\s*$", re.M)

# `family` may sit at the top level or under `metadata:` (#344). The shared reader lives
# beside this skill in `_meta`; run from a copy that has no `_meta`, only the top level is read.
sys.path.append(str(Path(__file__).resolve().parents[2] / "_meta"))
try:
    import skill_frontmatter  # noqa: E402
except ImportError:
    skill_frontmatter = None


def declared_family(text: str, path: Path) -> str | None:
    """The family a SKILL.md declares, from either layout; None when it declares none.

    Raises skill_frontmatter.FrontmatterConflict when the two layouts disagree.
    """
    end = text.find("\n---", 3) if text.startswith("---") else -1
    if end <= 0:
        return None
    if skill_frontmatter is not None:
        try:
            found = skill_frontmatter.value(text[3:end], "family", path=path)
            return (found or "").strip() or None
        except skill_frontmatter.FrontmatterUnsupported:
            pass  # a form the reader will not guess at: fall back to the top level
    m = FAMILY_RE.search(text[:end])
    return m.group(1).strip().strip("'\"") if m else None


def family_members(root: Path, family: str) -> set[str]:
    out = set()
    for skill, path in iter_skills(root, None):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if declared_family(text, path) == family:
            out.add(skill)
    return out


def unsourced_stats(text: str):
    """Yield (lineno, line) for prose lines carrying a statistic with no source.

    Skips frontmatter, fenced code and HTML comments (FRESHNESS blocks carry their own
    source_url). A line that is sourced anywhere counts as sourced: in a table the row is
    the unit, so a Source column sources every number in the row.
    """
    lines = text.splitlines()
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1
    in_code = in_comment = False
    for n in range(i, len(lines)):
        line = lines[n]
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if in_comment:
            if "-->" not in s:
                continue
            in_comment = False
            s = s.split("-->", 1)[1].strip()          # prose after the comment still counts
        elif s.startswith("<!--"):
            if "-->" not in s:
                in_comment = True
                continue
            s = s.split("-->", 1)[1].strip()
        if STAT_RE.search(s) and not SOURCE_RE.search(s):
            yield n + 1, s


def cmd_unsourced(a) -> int:
    root = Path(a.root).expanduser()
    wanted: set[str] = set()
    if a.family:
        try:
            wanted |= family_members(root, a.family)
        except ValueError as exc:  # skill_frontmatter.FrontmatterConflict: two copies disagree
            print(f"unsourced: {exc}", file=sys.stderr)
            return 3
    if a.skills:
        named = {s for s in a.skills.split(",") if s}
        missing = sorted(s for s in named if not (root / s / "SKILL.md").is_file())
        if missing:
            print(f"unsourced: no SKILL.md for --skills {', '.join(missing)}", file=sys.stderr)
            return 3
        wanted |= named
    if not wanted:
        print("unsourced: no skills selected (pass --family and/or --skills)", file=sys.stderr)
        return 3
    hits = []
    for skill in sorted(wanted):
        sdir = root / skill
        files = [sdir / "SKILL.md"] + sorted((sdir / "references").glob("*.md"))
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in unsourced_stats(text):
                hits.append((f.relative_to(root).as_posix(), lineno, line))
    for rel, lineno, line in hits:
        print(f"WARN  {rel}:{lineno}  unsourced statistic")
        print(f"         {line[:120]}")
    print(f"unsourced: {len(hits)} warning(s) across {len(wanted)} skill(s)")
    return 1 if (hits and a.fail_on_warn) else 0


def main() -> int:
    p = argparse.ArgumentParser(description="find facts that drifted across skills")
    p.add_argument("--root", default="~/.claude/skills")
    p.add_argument("--skills", help="comma-separated subset")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("subjects", help="subjects claimed by multiple skills")
    s.add_argument("--min-files", type=int, default=2)
    s.set_defaults(func=cmd_subjects)

    d = sub.add_parser("drift", help="multi-owner subjects whose verdicts DISAGREE")
    d.add_argument("--min-files", type=int, default=2)
    d.add_argument("--fail-on-drift", action="store_true")
    d.add_argument("--show-duplicates", action="store_true")
    d.set_defaults(func=cmd_drift)

    t = sub.add_parser("stale", help="dated status claims past a freshness horizon")
    t.add_argument("--months", type=int, default=12)
    t.set_defaults(func=cmd_stale)

    u = sub.add_parser("unsourced", help="statistics with no source or date on their line")
    u.add_argument("--family", help="select skills whose frontmatter declares this family")
    u.add_argument("--fail-on-warn", action="store_true")
    u.set_defaults(func=cmd_unsourced)

    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_meta"))
    try:
        from portable_cli import run_cli  # #251 stream hardening
    except ImportError:                   # installed without _meta: run unhardened
        sys.exit(main())
    sys.exit(run_cli(main))
