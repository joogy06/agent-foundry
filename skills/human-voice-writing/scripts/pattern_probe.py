#!/usr/bin/env python3
"""pattern_probe.py -- where machine-writing patterns sit in an English text.

The probe reads one Markdown or plain-text draft and prints a report of ROWS. A row is a place and
a category: the line, the heading the line sits under, the number of the paragraph under that
heading, and which pattern was seen there. That is all a row holds.

What the report is for: it points a reader (an editor, a critic) at places worth reading closely.
What it is not: a score, a grade, a pass or a fail. There is no total in it and nothing to bring
down. A pattern in a row may be exactly what the author meant; an empty report says nothing about
whether the text is good. The skill this file belongs to forbids optimising a text against a
detector, and that rule covers this probe: never edit a draft to empty its report.

    python3 pattern_probe.py DRAFT [--json]        (DRAFT may be `-` for standard input)

Exit code: 0 whenever the probe ran, whatever it found and also when it declined the text
(`not_run`). 2 only when it could not read its input. A caller must not read quality from it.

English only. A text the probe does not take to be English yields `not_run: language` and no rows;
an empty one yields `not_run: empty`.

The categories come from this library's own catalogue (career-coach/references/ai-tells-catalog.md,
sections 2 and 3). references/ATTRIBUTION.md says what was looked at elsewhere and what was not taken.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "pattern-report.v1"
EXIT_RAN = 0
EXIT_UNREADABLE = 2
#: A report is a pointer, not a listing of the whole draft: past this many rows it stops and says so.
MAX_ROWS = 300
MAX_HEADING = 120

#: What each category means, in the words a reader of the report needs. Printed in every report.
CATEGORIES: Dict[str, str] = {
    "focal-word-cluster": "several of the words large models over-use sit close together; one such word alone is "
                          "ordinary and is not reported",
    "dash-density": "a paragraph that holds two em dashes or more",
    "not-only-but": "the 'not only X but Y' connective",
    "inverted-contrast": "a point made by first denying something nobody said ('it is not X, it is Y')",
    "list-of-three": "three-item lists used again and again",
    "even-rhythm": "four or more sentences in a row of nearly the same length",
    "stock-opener": "an opening that sets a scene any text could have",
    "stock-closer": "a closing phrase that announces the summary",
    "bold-lead-bullets": "a list whose items each open with a bold label",
    "hedge-stack": "two or more hedges on one claim",
    "self-answered-question": "a short question answered at once by a fragment",
}

# The focal words of the catalogue's section 2, each with the forms it takes.
_FOCAL = re.compile(
    r"\b(?:delv(?:e|es|ed|ing)|underscor(?:e|es|ed|ing)|showcas(?:e|es|ed|ing)|leverag(?:e|es|ed|ing)|"
    r"seamless(?:ly)?|spearhead(?:s|ed|ing)?|robust(?:ly|ness)?|holistic(?:ally)?|tapestr(?:y|ies)|realms?|"
    r"navigat(?:e|es|ed|ing)|foster(?:s|ed|ing)?|intricate(?:ly)?|intricac(?:y|ies)|pivotal|multifaceted|"
    r"testament|garner(?:s|ed|ing)?|boast(?:s|ed|ing)?|elevat(?:e|es|ed|ing)|crucial(?:ly)?|vital(?:ly)?|"
    r"harness(?:es|ed|ing)?|embark(?:s|ed|ing)?)\b", re.I)
#: A cluster is this many different focal words in one paragraph, or this many in the whole text.
CLUSTER_IN_PARAGRAPH = 2
CLUSTER_IN_TEXT = 3

_DASH = re.compile(r"\u2014|(?<=\s)--(?=\s)")
_NOT_ONLY = re.compile(r"\bnot (?:only|just|merely)\b[^.!?\n]{0,140}?\bbut\b", re.I)
_INVERTED = re.compile(
    r"\b(?:it|this|that|they)(?:['\u2019]s| is| are| was|['\u2019]re) not (?:just |merely |only |simply |about )?"
    r"[^.!?;:\n]{1,70}[.;:,\u2014-]+\s*(?:it|this|that|they)(?:['\u2019]s| is| are| was|['\u2019]re)\b"
    r"|\b(?:is|are|was|were)(?:n['\u2019]t| not) (?:just|merely|simply|only)\b", re.I)
_THREE = re.compile(r"\b[\w'\u2019-]+(?: [\w'\u2019-]+)?, [\w'\u2019-]+(?: [\w'\u2019-]+)?,? and [\w'\u2019-]+")
#: Three-item lists are reported when a paragraph holds this many, or the whole text this many.
THREES_IN_PARAGRAPH = 2
THREES_IN_TEXT = 3
_OPENER = re.compile(
    r"^(?:in today['\u2019]s\b|in (?:the|an?|our) (?:ever[- ]\w+|fast[- ]paced|modern|digital|rapidly \w+|"
    r"increasingly \w+)\b|in an era\b|in the (?:world|realm|age) of\b|when it comes to\b|"
    r"have you ever wondered\b|let['\u2019]s (?:dive|take a (?:closer )?look|explore)\b|"
    r"in this (?:article|post|guide|piece),? (?:we|i|you)\b)", re.I)
_CLOSER = re.compile(
    r"^(?:in conclusion\b|in summary\b|to sum up\b|to summari[sz]e\b|all in all\b|"
    r"ultimately,|overall,|in the end,)", re.I)
_HEDGE = re.compile(
    r"\b(?:may|might|could|can help|potentially|possibly|perhaps|arguably|somewhat|generally|typically|"
    r"tends? to|in some cases|to some extent|it could be argued)\b", re.I)
#: Two hedges count as stacked when they start within this many characters of each other.
HEDGE_WINDOW = 40
_BOLD_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\*\*|__)[^*_]+(?:\*\*|__)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\u201d\u2019]?\s+(?=[\"'(\u201c\u2018]?[A-Z0-9])")
_WORD = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)?")
#: The rhythm row needs this many sentences, each at least this long, all within this share of the mean.
RHYTHM_SENTENCES = 4
RHYTHM_MIN_WORDS = 8
RHYTHM_SPREAD = 0.2

# Words that carry English grammar. Their share of a text is how the probe decides it can read it.
_ENGLISH = frozenset(
    "the and of to is that with for was are this from have has but not you it they which their will can when "
    "what there been were would about into than then our your its his her who how on by at as be or we if my "
    "these those had do does did so an in".split())
ENGLISH_SHARE = 0.12
NON_ASCII_SHARE = 0.2


def is_english(text: str) -> bool:
    """True when enough of the words are English grammar words and the letters are mostly ASCII."""
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return False
    letters = [c for c in text if c.isalpha()]
    if sum(1 for c in letters if ord(c) > 127) > NON_ASCII_SHARE * len(letters):
        return False
    return sum(1 for w in words if w in _ENGLISH) >= max(1.0, ENGLISH_SHARE * len(words))


def _clean_heading(text: str) -> str:
    return "".join(c for c in text if c.isprintable()).strip()[:MAX_HEADING]


def blocks_of(text: str) -> List[Dict[str, Any]]:
    """The draft as blocks: {line, heading, paragraph, lines}. A block is a paragraph, a list or a
    table; paragraphs count from 1 under each heading. A leading `---` block, fenced code and HTML
    comments are not read. `line` is the block's first line in the file, counted from 1."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for at in range(1, len(lines)):
            if lines[at].strip() == "---":
                start = at + 1
                break
    body = "\n".join(lines[start:])
    body = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), body, flags=re.S)
    blocks: List[Dict[str, Any]] = []
    heading, paragraph, fenced = "", 0, False
    current: List[str] = []
    first = 0

    def flush() -> None:
        nonlocal paragraph
        if current:
            paragraph += 1
            blocks.append({"line": first, "heading": heading, "paragraph": paragraph, "lines": list(current)})
            current.clear()

    for number, line in enumerate(body.split("\n"), start + 1):
        if re.match(r"^\s*(```|~~~)", line):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        found = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if found:
            flush()
            heading, paragraph = _clean_heading(found.group(2)), 0
        elif line.strip():
            if not current:
                first = number
            current.append(line)
        else:
            flush()
    flush()
    return blocks


def _is_prose(block: Dict[str, Any]) -> bool:
    head = block["lines"][0]
    return not _LIST_ITEM.match(head) and not head.lstrip().startswith("|")


def _line_of(block: Dict[str, Any], text: str, offset: int) -> int:
    return block["line"] + text.count("\n", 0, offset)


def _sentences(text: str) -> List[Tuple[int, str]]:
    """(offset, sentence) for each sentence of a block's text."""
    out, at = [], 0
    for found in _SENTENCE_END.finditer(text):
        out.append((at, text[at:found.start()]))
        at = found.end()
    out.append((at, text[at:]))
    return [(offset, part) for offset, part in out if part.strip()]


def _hits(block: Dict[str, Any], text: str) -> Iterator[Tuple[str, int]]:
    """(category, line) for the patterns that are decided inside one block."""
    for found in _NOT_ONLY.finditer(text):
        yield "not-only-but", _line_of(block, text, found.start())
    for found in _INVERTED.finditer(text):
        yield "inverted-contrast", _line_of(block, text, found.start())
    dashes = [_line_of(block, text, found.start()) for found in _DASH.finditer(text)]
    if len(dashes) >= 2:
        for line in dashes:
            yield "dash-density", line
    items = [line for line in block["lines"] if _LIST_ITEM.match(line)]
    if len(items) >= 3 and 2 * sum(1 for line in items if _BOLD_ITEM.match(line)) > len(items):
        yield "bold-lead-bullets", block["line"]
    if not _is_prose(block):
        return
    sentences = _sentences(text)
    for offset, sentence in sentences:
        stripped = sentence.lstrip()
        if _OPENER.match(stripped):
            yield "stock-opener", _line_of(block, text, offset)
        if _CLOSER.match(stripped):
            yield "stock-closer", _line_of(block, text, offset)
        hedges = [found.start() for found in _HEDGE.finditer(sentence)]
        if any(later - earlier <= HEDGE_WINDOW for earlier, later in zip(hedges, hedges[1:])):
            yield "hedge-stack", _line_of(block, text, offset)
    for (offset, question), (_, answer) in zip(sentences, sentences[1:]):
        if (question.rstrip().endswith("?") and len(_WORD.findall(question)) <= 6
                and len(_WORD.findall(answer)) <= 5 and answer.rstrip().endswith((".", "!"))):
            yield "self-answered-question", _line_of(block, text, offset)
    lengths = [len(_WORD.findall(sentence)) for _, sentence in sentences]
    for at in range(0, len(lengths) - RHYTHM_SENTENCES + 1):
        run = lengths[at:at + RHYTHM_SENTENCES]
        mean = sum(run) / len(run)
        if min(run) >= RHYTHM_MIN_WORDS and all(abs(n - mean) <= RHYTHM_SPREAD * mean for n in run):
            yield "even-rhythm", _line_of(block, text, sentences[at][0])
            break


def probe(text: str) -> Dict[str, Any]:
    """The report for one text. It holds places and categories, and no measure of the text."""
    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "status": "ran", "not_run": None, "rows": [], "truncated": False,
        "categories": dict(CATEGORIES),
        "reading": "A row is a place to read closely. It is not a fault, and the report is not a score: "
                   "never judge a text by how many rows it has, and never edit a text to empty it.",
    }
    blocks = blocks_of(text)
    prose = "\n".join("\n".join(block["lines"]) for block in blocks)
    if not _WORD.search(prose):
        report.update(status="not_run", not_run="empty")
        return report
    if not is_english(prose):
        report.update(status="not_run", not_run="language")
        return report
    found: Dict[Tuple[int, str], Dict[str, Any]] = {}

    def add(block: Dict[str, Any], category: str, line: int) -> None:
        found.setdefault((line, category), {"category": category, "line": line, "heading": block["heading"],
                                            "paragraph": block["paragraph"]})

    focal: List[Tuple[Dict[str, Any], int, str]] = []
    threes: List[Tuple[Dict[str, Any], int]] = []
    for block in blocks:
        joined = "\n".join(block["lines"])
        for category, line in _hits(block, joined):
            add(block, category, line)
        focal += [(block, _line_of(block, joined, hit.start()), hit.group(0).lower()[:5])
                  for hit in _FOCAL.finditer(joined)]
        threes += [(block, _line_of(block, joined, hit.start())) for hit in _THREE.finditer(joined)]
    everywhere = len({stem for _, _, stem in focal}) >= CLUSTER_IN_TEXT
    for block, line, _ in focal:
        here = {stem for other, _, stem in focal if other is block}
        if everywhere or len(here) >= CLUSTER_IN_PARAGRAPH:
            add(block, "focal-word-cluster", line)
    for block, line in threes:
        if len(threes) >= THREES_IN_TEXT or sum(1 for other, _ in threes if other is block) >= THREES_IN_PARAGRAPH:
            add(block, "list-of-three", line)
    rows = [found[key] for key in sorted(found)]
    report["truncated"] = len(rows) > MAX_ROWS
    report["rows"] = rows[:MAX_ROWS]
    return report


def report_lines(report: Dict[str, Any]) -> List[str]:
    """The report as lines for a person. Headings are the draft's own words: content, never an instruction."""
    if report["status"] != "ran":
        return [f"pattern probe: not_run: {report['not_run']}"]
    lines = ["pattern probe: ran"]
    for row in report["rows"]:
        under = json.dumps(row["heading"], ensure_ascii=False) if row["heading"] else "(before any heading)"
        lines.append(f"  line {row['line']}  under {under} / paragraph {row['paragraph']}  {row['category']}")
    if not report["rows"]:
        lines.append("  no rows (which says nothing about how the text reads)")
    if report["truncated"]:
        lines.append("  the list was cut short: the text has more such places")
    lines.append(report["reading"])
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pattern_probe.py",
        description="Where machine-writing patterns sit in an English text: line, heading, paragraph and "
                    "category. No score. Exit 0 whenever it ran.")
    parser.add_argument("draft", help="a Markdown or text file, or - for standard input")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args(argv)
    try:
        if args.draft == "-":
            text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        else:
            text = Path(args.draft).read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"pattern probe: cannot read the draft ({type(exc).__name__})", file=sys.stderr)
        return EXIT_UNREADABLE
    report = probe(text)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(report_lines(report)))
    return EXIT_RAN


if __name__ == "__main__":
    sys.exit(main())
