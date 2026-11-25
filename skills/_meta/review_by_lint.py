#!/usr/bin/env python3
"""review_by_lint.py -- #281. A dated prose REVIEW-BY marker must have a matching FRESHNESS:v1 anchor.

The freshness engine (freshness.py build_index) harvests deadlines ONLY from FRESHNESS:v1 blocks.
A file that carries just a human-visible prose marker --

    <!-- REVIEW-BY: 2027-01-31 -->
    **REVIEW-BY: 2027-04-06** . verified ...
    REVIEW-BY: 2027-01 (purge/refresh point)

-- has a deadline nothing tracks, and `check-deadlines` then reports "none due", which reads the
same as healthy. 22 such markers had accumulated, UK tax rates among them. Writing "remember to add
a FRESHNESS block" was what produced them, so this is a lint that FAILS instead (lessons.py:
execution_failure -> mechanism). The prose marker stays -- humans read it -- and the lint forces the
two to agree. The harvester keeps ONE parse path: blocks are read with freshness.extract_blocks +
freshness.parse_freshness_yaml, and a block's deadline is freshness.anchor_deadline -- the same
function build_index registers with.

FAIL CLOSED
-----------
A real marker that escapes is the failure #281 exists to prevent; a false positive is cheap
because it has an explicit escape hatch. So the rule is broad on purpose:

  * the keyword `REVIEW-BY` / `REVIEW_BY` / `REVIEW BY` / `REVIEWBY`, any case, joined by any
    hyphen or dash (U+2010, U+2011, en/em dash), NBSP or `&nbsp;`, ANYWHERE on a line (after a
    sentence, in a table cell, after a bold label, inside any HTML comment, ...),
  * followed on the same line -- or, when the keyword ends a line, at the start of the next --
    by optional separators (`:` or a fullwidth colon, spaces, NBSP / `&nbsp;`, markdown
    emphasis, quotes, `|`, `<`, `>`, dashes, an opening bracket), then at most three short
    words or parentheticals (`DATE:`, `(UK rates):`, `on`, `before`, `until`) with no sentence
    end among them, and a DATE-LIKE token. A code span holding only the keyword
    (`` `REVIEW-BY:` 2027-04-06 ``) is unwrapped, and struck-through text (`~~2026-01-01~~`,
    `<del>`, `<s>`) is skipped, so the LAST, live date is the one judged.

A date-like token that is exactly `YYYY-MM-DD` or `YYYY-MM` is a date (a bare `YYYY-MM` means
that month's last day). Any other date-like token (`2027/04/06`, `06 April 2027`, `April 2027`,
`2027`, `2027-4-6`) is E3 "write YYYY-MM-DD" -- never silently ignored. A bare number
(`2027`, `20270406`) or a non-ISO numeric date (`12/10/2027`) counts only when it ends the line
or is followed by punctuation: "review by 2025 McKinsey" and "review by 1000 users" are prose.
A real `YYYY-MM-DD` / `YYYY-MM` counts whatever follows it.

YYYY-MM is month-end on purpose ("REVIEW-BY 2027-01" means by the end of January). The lint only
passes such a marker when an anchor holds the full month-end date, so freshness.py never has to
interpret a bare YYYY-MM taken from these files.

SCOPE: `check` judges only paths whose repo-relative path lies under a root the harvester scans
(freshness.SKILLS_ROOT / AGENTS_ROOT / WORKFLOWS_ROOT by name: skills/, agents/, workflows/).
A FRESHNESS block anywhere else is read by nothing, so demanding one there would block ordinary
commits (tasks.md, history.md, docs/) for no gain; such paths are skipped silently. In a repo
with none of those roots -- a consumer project -- `check` therefore judges nothing.

NOT markers:
  * anything inside a FRESHNESS:v1 block or a fenced code block (CommonMark fences: the closing
    fence uses the opener's character and is at least as long; a blockquoted fence ends with its
    blockquote; an UNCLOSED fence is not a fence, so it cannot hide the rest of the file);
  * the keyword inside an inline code span (`` `REVIEW-BY: 2027-01` `` is talk ABOUT a marker);
  * `REVIEW_BY` with no date-like token after it (prose about the convention);
  * a line carrying the explicit suppression comment `<!-- review-by: mention -->` -- for a
    genuine mention of ANOTHER file's marker only. Never use it on this file's own deadline:
    that is exactly the invisible deadline this lint exists to catch;
  * files whose repo-relative path runs through a `tests/fixtures/` directory.

Rules (E blocks the pre-commit arm, W advises):
  E1  a dated prose marker, and the file has no FRESHNESS:v1 block at all
  E2  a FRESHNESS:v1 block exists, but no anchor's effective deadline (freshness.anchor_deadline)
      equals the marker's (normalized) date
  E3  the marker's date is not a real `YYYY-MM-DD` / `YYYY-MM` calendar date
  E4  a FRESHNESS:v1 block in the file does not parse (the harvester then drops the whole file)
  E5  the file could not be read, or is not UTF-8 and its bytes contain "REVIEW" -- it cannot
      be checked, so it cannot pass
  E6  the lint itself failed on this file (one bad file never hides another's findings)
  W1  the file is not UTF-8 and holds no "REVIEW" text (skipped, not passed)

    check [--staged] [--repo R] [--paths-from F|-] [--] <paths...>
                   only the given .md files under the harvester roots (the pre-commit arm).
                   --staged reads each path's STAGED blob (`git show :<path>`) -- what is being
                   committed, not the working tree. Paths are relative to --repo (default: cwd).
                   --paths-from reads NUL- (or newline-) separated paths from a file or stdin,
                   so a large commit never meets a command-line length limit.
    lint [--root R]    the tree (default: this repo's skills/ and agents/); no-arg = lint

Findings print as `RB-E1 <path>:<line>  <message>` so the hook's regexes cannot collide with the
other arms. Exit: 0 clean . 1 an error finding . 2 bad input . 3 a dependency (freshness.py)
could not be imported -- the linter is unavailable, which is not a finding (RB-W2 says so).
Stdlib only.
"""
from __future__ import annotations

import argparse
import calendar
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import freshness  # noqa: E402 -- the ONE FRESHNESS:v1 parser; never a second one
except Exception as _e:  # missing, skewed or unparseable dependency: unavailable, not broken
    freshness = None
    _IMPORT_ERROR = f"{type(_e).__name__}: {_e}"
else:
    _IMPORT_ERROR = ""

EXIT_UNAVAILABLE = 3

RULES = {
    "E1": "dated prose REVIEW-BY marker, but the file has no FRESHNESS:v1 block",
    "E2": "dated prose REVIEW-BY marker with no FRESHNESS:v1 anchor of the same date",
    "E3": "prose REVIEW-BY marker whose date is not a YYYY-MM-DD / YYYY-MM calendar date",
    "E4": "FRESHNESS:v1 block does not parse",
    "E5": "file could not be read or decoded and may hold a marker",
    "E6": "the lint failed on this file",
    "W1": "file unreadable as UTF-8 and holds no REVIEW text (skipped)",
    "W2": "linter unavailable: freshness.py could not be imported (nothing was checked)",
}

SUPPRESSION = "<!-- review-by: mention -->"
_SUPPRESS_RE = re.compile(r"<!--[ \t]*review-by:[ \t]*mention[ \t]*-->", re.IGNORECASE)

_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_KEYWORD = (r"(?<![A-Za-z0-9])REVIEW(?:[ \t\u00a0_" + _DASHES + r"-]|&nbsp;|&#160;)*BY"
            r"(?![A-Za-z])")
# Between the keyword and the date: punctuation, emphasis, table pipes, quoting, dashes,
# brackets, NBSP in either spelling, and a few inline HTML emphasis tags.
_SEP = (r"(?:[\s\u00a0:\uff1a*_|~<>=(\[\"'\u2018\u2019\u201c\u201d\u00ab\u00bb" + _DASHES + r"-]"
        r"|&nbsp;|&#160;|&lt;|&gt;|&quot;"
        r"|</?(?:b|strong|em|i|u|mark|code)>)*")
# Up to three short words or parentheticals between keyword and date (`DATE:`, `(UK rates):`,
# `on`, `before`). Words are letters only, so no sentence end can sit in the gap.
_GAP = (r"(?:(?:[A-Za-z]{1,12}|\([^()\n]{0,40}\)|\[[^\[\]\n]{0,40}\])" + _SEP + r"){0,3}")
_MONTH = (r"(?:january|february|march|april|may|june|july|august|september|october|november"
          r"|december|sept|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\.?(?![a-z])")
# A bare number or a non-ISO numeric date is a date only at a line end or before punctuation:
# "review by 2025 McKinsey", "review by 1000 users", "by 12/10/2027 standards" are prose.
_NUM_END = r"(?=[ \t\u00a0]*(?:\n|$|[^\w\s]))"
_DATE_LIKE = (
    r"(?P<date>"
    r"\d{4}-\d{2}(?:-\d{2})?(?![\d/.-]*\d)"                           # 2027-04-06 2027-04
    r"|\d{4}(?:[-/.]\d{1,2}){0,2}(?![\d])" + _NUM_END +                 # 2027/4/6 2027
    r"|\d{5,8}(?!\d)" + _NUM_END +                                     # 20270406
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}(?!\d)" + _NUM_END +               # 06/04/2027
    r"|\d{1,2}(?:st|nd|rd|th)?[ \t\u00a0-]+" + _MONTH +
    r"(?:[ \t\u00a0,-]+\d{2,4})?"                                      # 6 April 2027
    r"|" + _MONTH + r"[ \t\u00a0-]+\d{1,4}(?:(?:st|nd|rd|th)?,?[ \t\u00a0]+\d{4})?"  # April 2027
    r"|q[1-4][ \t\u00a0-]+\d{4}"                                       # Q1 2027
    r")"
)
_KEYWORD_RE = re.compile(_KEYWORD, re.IGNORECASE)
_MARKER_RE = re.compile(_KEYWORD + _SEP + _GAP + _DATE_LIKE, re.IGNORECASE)
#: Characters after a keyword that a marker may span (post-review m1: bounds backtracking).
_MATCH_WINDOW = 120
_FULL_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_CODE_SPAN = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)")
_QUOTE_PREFIX = re.compile(r"^(?: {0,3}>[ \t]?)*")
# CommonMark: a fence is indented at most 3 spaces; 4 is an indented code block, not a fence.
_FENCE = re.compile(r"^ {0,3}(?P<f>`{3,}|~{3,})(?P<info>.*)$")
_CLOSER = re.compile(r"^ {0,3}(?P<f>`{3,}|~{3,})[ \t]*$")
_STRUCK = re.compile(r"~~[^~\n]+~~|<(del|s|strike)>.*?</\1>", re.IGNORECASE)


class Marker:
    __slots__ = ("line", "raw", "date")

    def __init__(self, line: int, raw: str, normalized: str | None):
        self.line, self.raw, self.date = line, raw, normalized

    def __repr__(self) -> str:
        return f"Marker(line={self.line}, raw={self.raw!r}, date={self.date!r})"


def normalize(raw: str) -> str | None:
    """`YYYY-MM-DD` -> itself if a real date; `YYYY-MM` -> that month's last day; else None.

    Never raises: an impossible date (`0000-01`, `2027-02-30`) is None, which the caller
    reports as E3 -- an exception here would abort the whole batch.
    """
    try:
        m = _FULL_DATE.match(raw)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        m = _YEAR_MONTH.match(raw)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            if not 1 <= month <= 12:
                return None
            return date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    except (ValueError, OverflowError):
        return None
    return None


def _mask_blocks(text: str) -> str:
    """Blank every FRESHNESS:v1 block, keeping newlines so line numbers survive."""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    return freshness._BLOCK_RE.sub(blank, text)


def _quoted(line: str) -> bool:
    return line.lstrip(" \t").startswith(">")


def _fence_open(line: str):
    """(char, length, quoted) if `line` opens a fence, else None."""
    body = _QUOTE_PREFIX.sub("", line)
    m = _FENCE.match(body)
    if not m:
        return None
    fence = m.group("f")
    if fence[0] == "`" and "`" in m.group("info"):
        return None                      # CommonMark: a backtick info string has no backticks
    return fence[0], len(fence), _quoted(line)


def _fence_closes(line: str, char: str, length: int) -> bool:
    m = _CLOSER.match(_QUOTE_PREFIX.sub("", line))
    return bool(m) and m.group("f")[0] == char and len(m.group("f")) >= length


def fenced_lines(lines: list[str]) -> set[int]:
    """0-based indices of lines inside (or delimiting) a fenced code block.

    An opener with no closer is NOT a fence: CommonMark would run it to EOF, but that would
    let one stray ``` hide every marker below it. Fail closed.

    Linear in practice: an opener that found no closer before EOF records its (char, quoted)
    and length, and a later opener of the same kind at least that long cannot find one either
    (its search space is a suffix of the failed one) -- so 20k stray openers cost one scan.
    """
    fenced: set[int] = set()
    no_closer: dict[tuple[str, bool], int] = {}
    i, n = 0, len(lines)
    while i < n:
        opened = _fence_open(lines[i])
        if not opened:
            i += 1
            continue
        char, length, quoted = opened
        if length >= no_closer.get((char, quoted), n + 4):
            i += 1                       # known unclosed: not a fence
            continue
        end = None
        nxt = None
        for j in range(i + 1, n):
            if quoted and not _quoted(lines[j]):
                end, nxt = j - 1, j      # the blockquote ended, and the fence with it
                break
            if _fence_closes(lines[j], char, length):
                end, nxt = j, j + 1
                break
        if end is None:
            no_closer[(char, quoted)] = min(length, no_closer.get((char, quoted), length))
            i += 1                       # unclosed: not a fence
            continue
        fenced.update(range(i, end + 1))
        i = nxt
    return fenced


def _strip_code_spans(line: str) -> str:
    """Drop an inline code span that holds the keyword AND a digit (a quoted marker: a mention);
    unwrap any other -- so `` `REVIEW-BY:` 2027-04-06 `` (keyword-only span, date outside) is
    still a marker, and `` `REVIEW-BY: 2027-01` `` is talk about one."""
    def repl(m: re.Match) -> str:
        inner = m.group(2)
        if _KEYWORD_RE.search(inner) and re.search(r"\d", inner):
            return " " * len(m.group(0))
        return f" {inner} "
    return _CODE_SPAN.sub(repl, line)


def _strip_struck(line: str) -> str:
    """Blank struck-through text: a superseded date is not the deadline."""
    return _STRUCK.sub(lambda m: " " * len(m.group(0)), line)


def find_markers(text: str) -> list[Marker]:
    """Every dated prose marker in `text`, outside FRESHNESS blocks, fences and code spans."""
    if text.startswith("\ufeff"):
        text = text[1:]
    if not _KEYWORD_RE.search(text):
        return []                        # the common case, and it keeps odd files cheap
    lines = _mask_blocks(text).splitlines()
    fenced = fenced_lines(lines)
    work: list[str | None] = []
    suppressed: list[bool] = []
    for idx, line in enumerate(lines):
        if idx in fenced:
            work.append(None)
            suppressed.append(False)
            continue
        suppressed.append(bool(_SUPPRESS_RE.search(line)))
        work.append(_strip_struck(_strip_code_spans(_SUPPRESS_RE.sub(" ", line))))
    out: list[Marker] = []
    for idx, line in enumerate(work):
        if line is None or suppressed[idx] or not _KEYWORD_RE.search(line):
            continue
        # A hard wrap can put the date on the next line; look across ONE line break.
        nxt = work[idx + 1] if idx + 1 < len(work) else None
        joined = line + ("\n" + nxt if nxt is not None else "")
        # Match from each keyword on THIS line, inside a bounded window: the separator/gap
        # grammar backtracks polynomially on hostile input (hundreds of `<b>` tags), and a
        # pre-commit hook must never hang. A real marker's date sits well inside the window.
        for k in _KEYWORD_RE.finditer(line):
            m = _MARKER_RE.match(joined[k.start():k.start() + _MATCH_WINDOW])
            if m is None:
                continue
            raw = m.group("date").strip()
            out.append(Marker(idx + 1, raw, normalize(raw)))
    return out


def anchor_dates(blocks: list[dict]) -> set[str]:
    """The deadline dates the harvester would register from these parsed blocks."""
    dates = set()
    for parsed in blocks:
        for a in parsed.get("anchors", []):
            d = freshness.anchor_deadline(a)
            if d is not None:
                dates.add(d)
    return dates


def is_exempt(rel: Path | None) -> bool:
    """True for a REPO-RELATIVE path through a tests/fixtures/ directory.

    Only ever the repo-relative path: an absolute path would exempt a whole checkout that
    happens to live under some `tests/fixtures/` directory. No relative path, no exemption.
    """
    if rel is None or rel.is_absolute():
        return False
    parts = rel.parts
    return any(parts[i] == "tests" and parts[i + 1] == "fixtures"
               for i in range(len(parts) - 1))


def lint_text(text: str) -> list[tuple[str, int, str]]:
    """[(code, line, message)] for one document's text -- empty means clean."""
    markers = find_markers(text)
    if not markers:
        return []
    findings: list[tuple[str, int, str]] = []
    bodies = freshness.extract_blocks(text)
    try:
        blocks = [freshness.parse_freshness_yaml(b) for b in bodies]
    except ValueError as e:
        findings.append(("E4", 0, f"{RULES['E4']}: {e}"))
        blocks = []                      # build_index drops the whole file on ValueError
    dates = anchor_dates(blocks)
    for mk in markers:
        if mk.date is None:
            findings.append(("E3", mk.line,
                             f"REVIEW-BY {mk.raw!r} is not a real date -- write YYYY-MM-DD "
                             f"(or YYYY-MM for a month's end)"))
            continue
        if not bodies:
            findings.append(("E1", mk.line,
                             f"prose REVIEW-BY {mk.raw} has no FRESHNESS:v1 block -- add one with "
                             f"an anchor `kind: date_review` / `review_by: \"{mk.date}\"` so "
                             f"freshness.py tracks it"))
        elif mk.date not in dates:
            have = ", ".join(sorted(dates)) or "none"
            findings.append(("E2", mk.line,
                             f"prose REVIEW-BY {mk.raw} (= {mk.date}) has no matching FRESHNESS:v1 "
                             f"anchor (deadlines the index would register: {have}) -- add or "
                             f"correct a `kind: date_review` anchor with `review_by: \"{mk.date}\"`"))
    return findings


def _may_hold_marker(raw: bytes) -> bool:
    return b"review" in raw.replace(b"\x00", b"").lower()


def lint_bytes(raw: bytes, rel: Path | None = None) -> list[tuple[str, int, str]]:
    if is_exempt(rel):
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        if _may_hold_marker(raw):
            return [("E5", 0, f"{RULES['E5']}: not UTF-8 ({e}) and contains REVIEW text")]
        return [("W1", 0, f"{RULES['W1']}: {e}")]
    try:
        return lint_text(text)
    except Exception as e:  # noqa: BLE001 -- fail closed, per file
        return [("E6", 0, f"{RULES['E6']}: {type(e).__name__}: {e}")]


def lint_file(path: Path, rel: Path | None = None) -> list[tuple[str, int, str]]:
    """Lint one file on disk. `rel` is its repo-relative path (exemptions use only that)."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return [("E5", 0, f"{RULES['E5']}: {e}")]
    return lint_bytes(raw, rel)


def report(results: dict[str, list[tuple[str, int, str]]], n_files: int) -> int:
    n_err = 0
    for p in sorted(results):
        for code, line, msg in results[p]:
            print(f"RB-{code} {p}:{line}  {msg}")
            if code.startswith("E"):
                n_err += 1
    n_warn = sum(len(f) for f in results.values()) - n_err
    print(f"review_by_lint: {n_files} file(s) . {n_err} error(s) . {n_warn} warning(s)")
    return 1 if n_err else 0


def default_roots() -> list[Path]:
    skills = _HERE.parent
    roots = [skills]
    for name in ("agents", "workflows"):   # the same roots `check` judges
        extra = skills.parent / name
        if extra.is_dir():
            roots.append(extra)
    return roots


def iter_tree(roots: list[Path]):
    """(path, path relative to its root) for every non-exempt .md under the roots."""
    for root in roots:
        # The exemption prunes inside the walk, so an exempt alias cannot hide a live skill.
        for p in freshness.walk_files(root, ("*.md",), {"tests/fixtures"}):
            rel = p.relative_to(root)
            if p.is_file() and not is_exempt(rel):
                yield p, rel


def cmd_lint(args) -> int:
    roots = args.root or default_roots()
    bad = [r for r in roots if not r.is_dir()]
    if bad:
        print(f"review_by_lint: not a directory: {bad[0]}", file=sys.stderr)
        return 2
    files = list(iter_tree(roots))
    results = {str(p): f for p, rel in files if (f := lint_file(p, rel))}
    return report(results, len(files))


def _staged_blob(repo: Path, rel: str) -> bytes | None:
    try:
        proc = subprocess.run(["git", "-C", str(repo), "show", f":{rel}"],
                              capture_output=True, check=False)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _repo_relative(path: Path, repo: Path) -> Path | None:
    if not path.is_absolute():
        return path
    try:
        return path.resolve().relative_to(repo.resolve())
    except ValueError:
        return None


def scope_roots() -> tuple[str, ...]:
    """The top-level directory names build_index harvests -- taken from freshness, not retyped."""
    names = [getattr(freshness, attr, None) for attr in ("SKILLS_ROOT", "AGENTS_ROOT", "WORKFLOWS_ROOT")]
    got = tuple(r.name for r in names if r is not None)
    return got or ("skills", "agents", "workflows")   # a version-skewed freshness never crashes


def in_scope(rel: Path | None) -> bool:
    """True when the repo-relative path lies under a root the harvester scans."""
    if rel is None or rel.is_absolute() or not rel.parts:
        return False
    return rel.parts[0] in scope_roots()


def _read_paths(source: str) -> list[str]:
    """NUL-separated (or, with no NUL, newline-separated) paths from a file or `-` (stdin)."""
    if source == "-":
        raw = sys.stdin.buffer.read()
    else:
        with open(source, "rb") as fh:
            raw = fh.read()
    text = raw.decode("utf-8", errors="surrogateescape")
    # NUL-separated whenever a NUL is present (the hook always ends the list with one, so a
    # lone path holding a newline is not split); otherwise one path per "\n" line only.
    parts = text.split("\0") if "\0" in text else text.split("\n")
    return [p for p in parts if p]


def _toplevel(cwd: Path) -> Path | None:
    """The git work-tree root containing `cwd`, or None."""
    try:
        out = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def cmd_check(args) -> int:
    repo = args.repo or _toplevel(Path.cwd()) or Path.cwd()
    files = list(args.files)
    if args.paths_from:
        try:
            files += _read_paths(args.paths_from)
        except OSError as e:
            print(f"review_by_lint: cannot read --paths-from {args.paths_from}: {e}",
                  file=sys.stderr)
            return 2
    names = [f for f in files if f.lower().endswith(".md")]
    results: dict[str, list[tuple[str, int, str]]] = {}
    n = 0
    for name in names:
        rel = _repo_relative(Path(name), repo)
        if not in_scope(rel):
            continue                     # outside skills/ agents/ workflows/: read by nothing
        if args.staged:
            raw = _staged_blob(repo, name)
            n += 1
            found = ([("E5", 0, f"{RULES['E5']}: `git show :{name}` failed")]
                     if raw is None else lint_bytes(raw, rel))
        else:
            path = Path(name) if Path(name).is_absolute() else repo / name
            if not path.is_file():
                continue                 # a path deleted in this commit
            n += 1
            found = lint_file(path, rel)
        if found:
            results[name] = found
    if n == 0:
        if names:
            # Say so: from a subdirectory, a wrong --repo makes every file "out of scope".
            print(f"review_by_lint: 0 file(s) in scope ({len(names)} skipped: outside "
                  f"{'/ '.join(scope_roots())}/ of {repo})", file=sys.stderr)
        return 0
    return report(results, n)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="review_by_lint.py",
        description="Fail on a dated prose REVIEW-BY marker with no matching FRESHNESS:v1 anchor.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("lint", help="lint a tree (default: skills/ and agents/)")
    p.add_argument("--root", type=Path, action="append", default=None)
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("check", help="lint only the given files (pre-commit arm)")
    p.add_argument("--staged", action="store_true",
                   help="read each path's staged blob (git show :<path>), not the working tree")
    p.add_argument("--repo", type=Path, default=None,
                   help="the repo the paths are relative to (default: cwd)")
    p.add_argument("--paths-from", default=None, metavar="FILE",
                   help="read NUL/newline-separated paths from FILE, or '-' for stdin")
    p.add_argument("files", nargs="*")
    p.set_defaults(fn=cmd_check)
    args = ap.parse_args(argv)
    if args.cmd is None:
        args = ap.parse_args(["lint", *(argv or [])])
    if freshness is None:
        # Distinct exit: the hook reports "linter unavailable" instead of failing closed.
        print(f"RB-W2 review_by_lint.py:0  {RULES['W2']} ({_IMPORT_ERROR})")
        return EXIT_UNAVAILABLE
    return args.fn(args)


if __name__ == "__main__":
    try:
        from portable_cli import run_cli
    except ImportError:          # a vendored copy without the harness: harden inline
        for _s in (sys.stdout, sys.stderr):
            try:
                _s.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, ValueError):
                pass
        sys.exit(main())
    raise SystemExit(run_cli(main))
