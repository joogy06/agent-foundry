#!/usr/bin/env python3
"""studio_axes.py -- #352: read the axis table and the refuse list of a doctrine file.

A doctrine (a visual house, a copy school) and every maker's direction contract fill ONE shared
shape: a fixed list of named axes with one value per axis. Two rivals are different when their
values differ on enough axes. This module is the one reader of that shape; the runner's distance
check and the doctrine test both import it.

THE AXIS TABLE (the contract a doctrine file or a direction contract keeps)
  * It sits in the section whose heading starts with "Axis table" (any heading level), up to the
    next heading of the same or a higher level.
  * It is the first markdown table of that section. Columns are found by NAME, in any order:
      Axis           the axis id (required)
      Value          the one value chosen on that axis (required)
      Also allowed   optional: other values a maker under this house may move to when the brief
                     asks for it; a comma-separated list. An empty cell, a dash or the bare
                     word none means "nothing more". A part in backticks is always a value, so
                     a house whose vocabulary has a value called none permits it as `none`.
    Any further column (for example "In practice") is prose and is not read.
  * A cell may be wrapped in backticks. Ids and values are lower-case words joined by hyphens.

THE REFUSE LIST
  * The section whose heading starts with "Refuse", up to the next heading of the same or a higher
    level. Its rows are the list items and, in a table, the first cell of each data row. This is
    the same contract skills/design-critique/tests/test_design_critique.py reads.

DISTANCE
  * differing_axes(a, b): the axes on which the two CHOSEN values differ.
  * disjoint_axes(a, b): the axes on which nothing one side permits (value plus "also allowed")
    is permitted by the other. Two houses that are disjoint on N axes cannot be brought closer
    than N axes by any pair of makers who stay inside their house.
  * pair_problems(a, b): empty when the two tables fill the same axes from the vocabulary and
    both counts reach `minimum` (MIN_DISTANCE, three).

CLI
  studio_axes.py parse FILE [--set visual|copy|angle] [--json]          exit 0 a valid table, 2 problems
  studio_axes.py distance FILE_A FILE_B [--min N] [--set ...] [--json]  exit 0 far enough, 2 problems
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: Two rival doctrines differ on at least this many axes.
MIN_DISTANCE = 3

#: The visual axes, in the order every table lists them, each with its closed vocabulary.
VISUAL_AXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("type", ("one-family", "two-roles", "display-led")),
    ("colour", ("neutral-accent", "tonal", "colour-field")),
    ("density", ("airy", "compact", "clustered")),
    ("motion", ("still", "feedback", "authored")),
    ("layout", ("single-column", "column-grid", "broken-grid")),
    ("imagery", ("content-only", "supporting", "art-directed")),
    ("ornament", ("none", "structural", "thematic")),
)

#: The copy axes: how a piece of writing is told. None of them is about whether a statement is
#: true, the outline or the length: those bind both schools alike.
COPY_AXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("opening", ("answer-first", "context-first", "scene-first")),
    ("claims", ("figure-led", "qualified", "verdict-led")),
    ("rhythm", ("even", "varied", "staccato")),
    ("person", ("impersonal", "second-person", "first-person")),
    ("proof-placement", ("beside-claim", "after-argument", "in-story")),
    ("call-to-action", ("up-front", "at-each-step", "at-close")),
)

#: One axis for rivals who share a skill and a voice and differ only in what each line leads with.
ANGLE_AXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("angle", ("impact-led", "scope-led", "craft-led")),
)

#: Named axis sets. A profile's function names one in `axis_set`.
AXIS_SETS = {"visual": VISUAL_AXES, "copy": COPY_AXES, "angle": ANGLE_AXES}

_WORD = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_NONE = {"", "none", "-", "—", "–"}
_RULE = re.compile(r":?-{3,}:?")
_BACKTICKED = re.compile(r"`[^`]+`")


class AxisError(ValueError):
    """The text holds no readable axis table."""


def _section(text: str, starts_with: str) -> list[str] | None:
    """The lines under the first heading whose text starts with `starts_with`, or None."""
    lines, level = [], 0
    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if level and len(heading.group(1)) <= level:
                return lines
            if not level and heading.group(2).strip().lower().startswith(starts_with):
                level = len(heading.group(1))
            continue
        if level:
            lines.append(line)
    return lines if level else None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _plain(cell: str) -> str:
    return cell.strip().strip("`").strip().lower()


def axis_table(text: str) -> dict[str, dict]:
    """The axis table of `text` as {axis: {"value": str, "also": [str, ...]}}, in table order.

    Raises AxisError when there is no "Axis table" section, no table in it, no Axis or Value
    column, an empty axis or value cell, or an axis listed twice. It does not check the
    vocabulary: that is table_problems.
    """
    section = _section(text, "axis table")
    if section is None:
        raise AxisError("no section whose heading starts with 'Axis table'")
    header, rows, ruled = None, [], False
    for line in section:
        if not line.lstrip().startswith("|"):
            if ruled:
                break
            header = None
            continue
        cells = _cells(line)
        if header is None:
            header = [c.lower() for c in cells]
        elif not ruled:
            if not all(_RULE.fullmatch(c) for c in cells):
                raise AxisError("the axis table has no rule line under its header")
            ruled = True
        else:
            rows.append(cells)
    if header is None or not ruled:
        raise AxisError("the 'Axis table' section holds no table")
    for column in ("axis", "value"):
        if column not in header:
            raise AxisError(f"the axis table has no '{column.capitalize()}' column")
    at_axis, at_value = header.index("axis"), header.index("value")
    at_also = header.index("also allowed") if "also allowed" in header else None
    table: dict[str, dict] = {}
    for cells in rows:
        cells = cells + [""] * (len(header) - len(cells))
        axis, value = _plain(cells[at_axis]), _plain(cells[at_value])
        if not axis or not value:
            raise AxisError("an axis table row has an empty axis or value")
        if axis in table:
            raise AxisError(f"axis '{axis}' is listed twice")
        also = []
        if at_also is not None:
            for part in cells[at_also].split(","):
                # `none` in backticks is the value none; the bare word (or a dash) is an empty cell.
                if _BACKTICKED.fullmatch(part.strip()) or _plain(part) not in _NONE:
                    also.append(_plain(part))
        table[axis] = {"value": value, "also": also}
    if not table:
        raise AxisError("the axis table has no rows")
    return table


def table_problems(table: dict[str, dict], axes=VISUAL_AXES) -> list[str]:
    """What is wrong with a parsed table against an axis set. Empty is a pass."""
    problems = []
    vocabulary = dict(axes)
    for axis in vocabulary:
        if axis not in table:
            problems.append(f"axis-missing:{axis}")
    for axis, row in table.items():
        if axis not in vocabulary:
            problems.append(f"axis-unknown:{axis}")
            continue
        for kind, values in (("value", [row["value"]]), ("also", row["also"])):
            for value in values:
                if not _WORD.match(value) or value not in vocabulary[axis]:
                    problems.append(f"{kind}-unknown:{axis}={value}")
        if row["value"] in row["also"]:
            problems.append(f"also-repeats-value:{axis}")
    if not problems and list(table) != list(vocabulary):
        problems.append("axis-order")
    return problems


def permitted(table: dict[str, dict]) -> dict[str, set[str]]:
    """Per axis, every value a maker under this table may hold."""
    return {axis: {row["value"], *row["also"]} for axis, row in table.items()}


def differing_axes(a: dict[str, dict], b: dict[str, dict]) -> list[str]:
    """The axes both tables name on which the chosen values differ, in the order of `a`."""
    return [axis for axis in a if axis in b and a[axis]["value"] != b[axis]["value"]]


def disjoint_axes(a: dict[str, dict], b: dict[str, dict]) -> list[str]:
    """The axes on which the two tables permit no common value, in the order of `a`."""
    allowed_a, allowed_b = permitted(a), permitted(b)
    return [axis for axis in a if axis in b and not allowed_a[axis] & allowed_b[axis]]


def pair_problems(a: dict[str, dict], b: dict[str, dict], axes=VISUAL_AXES,
                  minimum: int = MIN_DISTANCE) -> list[str]:
    """Why two tables are not a rival pair. Empty is a pass."""
    problems = [f"a:{p}" for p in table_problems(a, axes)] + [f"b:{p}" for p in table_problems(b, axes)]
    if set(a) != set(b):
        problems.append("axes-not-shared")
    differing, disjoint = differing_axes(a, b), disjoint_axes(a, b)
    if len(differing) < minimum:
        problems.append(f"too-close:{len(differing)}<{minimum}")
    if len(disjoint) < minimum:
        problems.append(f"too-close-permitted:{len(disjoint)}<{minimum}")
    return problems


def contract_problems(contract: dict[str, dict], house: dict[str, dict], axes=VISUAL_AXES) -> list[str]:
    """Why a maker's direction contract does not fit its house. Empty is a pass."""
    problems = table_problems(contract, axes)
    allowed = permitted(house)
    for axis, row in contract.items():
        if axis in allowed and row["value"] not in allowed[axis]:
            problems.append(f"outside-house:{axis}={row['value']}")
    return problems


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def refuse_rows(text: str) -> list[str]:
    """The rows of a doctrine's refuse list, lower-cased with punctuation dropped."""
    section = _section(text, "refuse")
    rows, ruled = [], False
    for line in section or []:
        item = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$", line)
        if item:
            rows.append(_normalise(item.group(1)))
        elif line.lstrip().startswith("|"):
            cells = _cells(line)
            if all(_RULE.fullmatch(c) for c in cells):
                ruled = True
            elif ruled:
                rows.append(_normalise(cells[0]))
    return [row for row in rows if row]


def _read(path: str) -> dict[str, dict]:
    return axis_table(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    # A problem line can carry text from the file that was read; never die on the console's encoding.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Read and compare doctrine axis tables.")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("parse", help="read one axis table")
    one.add_argument("file")
    two = commands.add_parser("distance", help="compare two axis tables")
    two.add_argument("file_a")
    two.add_argument("file_b")
    two.add_argument("--min", type=int, default=MIN_DISTANCE, dest="minimum")
    for command in (one, two):
        command.add_argument("--set", default="visual", choices=sorted(AXIS_SETS), dest="axis_set")
        command.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    axes = AXIS_SETS[args.axis_set]
    try:
        if args.command == "parse":
            table = _read(args.file)
            report = {"table": table, "problems": table_problems(table, axes)}
        else:
            a, b = _read(args.file_a), _read(args.file_b)
            report = {"differing": differing_axes(a, b), "disjoint": disjoint_axes(a, b),
                      "minimum": args.minimum, "problems": pair_problems(a, b, axes, args.minimum)}
    except (AxisError, OSError, UnicodeDecodeError) as exc:
        report = {"problems": [f"unreadable:{exc}"]}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            if key != "problems":
                print(f"{key}: {json.dumps(value, sort_keys=True)}")
        print("problems: " + (", ".join(report["problems"]) or "none"))
    return 2 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
