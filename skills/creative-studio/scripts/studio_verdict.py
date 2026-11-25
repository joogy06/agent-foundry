#!/usr/bin/env python3
"""studio_verdict.py -- the studio-verdict.v1 record: its skeleton and its checker (#352).

    studio_verdict.py skeleton --run-id ID --profile NAME --work-kind rendered|text
                               --mode full|light --borrow-max N
                               --variant variant-1=<evidence.json> --variant variant-2=<evidence.json>
                               [--order variant-2,variant-1] --out <record.json>
    studio_verdict.py skeleton --from <record.json> --recapture variant-1=<evidence.json> --out <record.json>
    studio_verdict.py check <record.json> --skeleton <skeleton.json> [--critic-row ROW ...] [--json]

WHO WRITES WHAT. The runner writes the identity fields and the `runner` part: the variants as
unlabelled ids, the order of each read, the floor rows and the evidence references. The critic
fills the `critic` part: tells per variant, the rubric comparison, the outcome, the winner, what
is borrowed, what is rejected, what could not be judged and what is open to the user. `check`
compares the runner part with the skeleton it is given and refuses a record whose floor rows
differ. That is as good as the skeleton it is handed: the caller says where that one comes from.

THE SHAPE is read from ../schemas/studio-verdict.v1.json by a small validator in this file (no
third-party schema library). The rules a schema cannot say are in `semantic_problems`; each is
named in the schema, in the description of the field it guards.

AN EVIDENCE FILE (the input of `--variant` and `--recapture`) is a JSON object with `floor_rows`
(each row: id, blocking, result pass|fail|not_run, and viewport plus element for rendered work
or a text locator for text work; `measured` and `threshold` are optional) and, optionally,
`evidence` (a list of references), `tiles` and `motion_frames` (lists of references, taken as
evidence too) and `direction_contract` (a reference).

EXIT CODES. 0 accepted, or the skeleton was written. 2 refused, or the input was not usable.

WHAT `check` PRINTS. `accepted`, or `refused` and one line per reason: a fixed code of ours
(REASONS below) and, for some, where: a field path of the schema, a variant id or a number.
It never prints text from the record, because a critic wrote that text and a reader of this
output may be an agent.

Stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "studio-verdict.v1"
CHECK_VERSION = "studio-verdict-check.v1"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "studio-verdict.v1.json"

#: The schema keywords `shape_problems` implements. A keyword outside this set would be
#: ignored silently, so a test fails the schema file when it uses one.
SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "$defs", "$ref", "title", "description", "type", "const", "enum", "pattern",
    "minLength", "minimum", "minItems", "items", "properties", "required", "additionalProperties",
})

IDENTITY_FIELDS = ("schema_version", "run_id", "profile", "work_kind", "mode", "borrow_max")
WORK_KINDS = ("rendered", "text")
MODES = ("full", "light")
RESULTS = ("pass", "fail", "not_run")
OUTCOMES = ("winner", "no_award")
BORROW_KINDS = ("fragment", "system", "move")
#: Where a `system` borrow may be anchored, by work kind.
SYSTEM_ANCHORS = {
    "rendered": ("direction_contract", "root_style"),
    "text": ("direction_contract", "outline", "term_set"),
}
#: The fields every borrow may carry, and the ones each kind adds.
BORROW_COMMON = frozenset({"from", "kind", "what", "why"})         # all four are required
BORROW_FIELDS = {"fragment": {"locator"}, "system": {"anchor"}, "move": {"technique", "evidence_region"}}

#: Every reason `check` can give. The text is ours and fixed.
REASONS = {
    "unreadable": "the file could not be read",
    "not_json": "the file is not JSON",
    "skeleton_invalid": "the skeleton is not a usable studio-verdict.v1 skeleton",
    "missing_field": "a required field is absent",
    "unknown_field": "an object holds a field the schema does not have",
    "wrong_type": "a value has the wrong type",
    "bad_value": "a value is outside what the schema allows",
    "runner_part_altered": "the identity fields or the runner part differ from the skeleton",
    "variant_ids": "the variants are not variant-1..variant-N, each once and in sequence",
    "read_order": "a read order is not a permutation of the variants, or the second is not the first reversed",
    "floor_row_variant": "a floor row or a re-capture names a variant the record does not have",
    "floor_row_scope": "a floor row lacks viewport and element (rendered work) or a text locator (text work)",
    "recapture_sequence": "the re-captures are not numbered 1, 2, ... in order",
    "reads_mismatch": "the critic's reads are not one per read order, numbered from 1",
    "read_pick_unknown": "a read picked something that is not a variant",
    "tells_missing": "the tells are not exactly one entry per variant",
    "rubric_empty": "the outcome is winner and the rubric comparison is empty",
    "winner_missing": "the outcome is winner and no winner is named",
    "winner_unknown": "the winner is not a variant of this record",
    "winner_with_no_award": "the outcome is no_award and a winner is named",
    "winner_not_picked": "the winner is not the pick of any read",
    "winner_ineligible": "the winner's latest capture fails a blocking floor row and is not a confirmed repair",
    "winner_not_favoured": "the outcome is winner and no rubric row favours the winner",
    "rubric_favours_unknown": "a rubric row favours a variant the record does not have",
    "no_award_required": "no variant's latest capture passes the blocking floor rows, so the outcome must be no_award",
    "no_award_unexplained": "no_award without its reason: all_fail_blocking, or the line of the brief no variant met",
    "no_award_with_winner": "the outcome is winner and no_award is filled",
    "repair_without_winner": "the outcome is no_award and a repair is recorded",
    "repair_no_recapture": "selected_for_repair without a re-capture of the winner, or not its latest one",
    "repair_recapture_incomplete": "the re-capture lacks a blocking row (id and width) the first capture had",
    "repair_recapture_fails": "the re-capture does not pass every blocking floor row",
    "repair_not_rejudged": "the repaired winner was not re-judged and confirmed",
    "winner_not_rejudged": "the winner was captured or checked again after the verdict opened, and repair does not "
                           "name that latest re-capture as re-judged and confirmed",
    "borrow_over_max": "more borrows than the profile allows",
    "borrow_without_winner": "the outcome is no_award and something is borrowed",
    "borrow_source": "a borrow comes from a variant that is not a losing variant",
    "borrow_locator": "a fragment borrow needs a locator of its kind of work, markup for rendered work and text "
                      "for written work, and nothing else",
    "borrow_anchor": "a system borrow needs an anchor this kind of work allows, and nothing else",
    "borrow_move": "a move borrow needs a technique and an evidence region of its kind of work: evidence the "
                   "runner recorded for rendered work, text for written work, and nothing else",
    "loser_unaccounted": "a losing variant is in neither borrowed nor rejected",
    "loser_in_both": "a losing variant is in both borrowed and rejected",
    "rejected_unknown": "rejected names the winner, a variant twice or something that is not a variant",
    "flip_not_open_to_user": "the reads disagree and open_to_user holds no order_flip entry",
    "first_screen_row_missing": "a variant has no single first-screen entry in its tells",
    "winner_fails_first_screen": "the winner's first-screen entry does not hold",
    "unlisted_statements_row_missing": "a variant has no single unlisted-statements entry in its tells",
    "winner_states_an_unlisted_fact": "the winner's unlisted-statements entry does not hold: the critic found a "
                                      "statement of fact that is on no claim list and not in the truth pack",
}
#: The blocking floor rows a critic fills, where a run has them: row id -> (the code for a variant
#: with no entry, the code for a winner whose entry does not hold). Each is ONE `tells` entry per
#: variant with the row id as its `axis`; `held` true is a pass. Which rows a run has is the
#: runner's to say (its profile); `check_record` is given them.
CRITIC_ROWS = {
    "first-screen": ("first_screen_row_missing", "winner_fails_first_screen"),
    "unlisted-statements": ("unlisted_statements_row_missing", "winner_states_an_unlisted_fact"),
}

_AT_SAFE = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,120}$")

Problem = Tuple[str, str]


class InputError(Exception):
    """An input of ours could not be used. Carries a reason code."""

    def __init__(self, code: str, at: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.at = at


# ---------------------------------------------------------------------------------------------
# shape: a validator for the schema keywords in SUPPORTED_KEYWORDS
# ---------------------------------------------------------------------------------------------

def load_schema(path: Path = SCHEMA_PATH) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _type_ok(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    return False


def _resolve(node: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    while "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        node = schema["$defs"][name]
    return node


def shape_problems(value: Any, node: Dict[str, Any], schema: Dict[str, Any], path: str = "") -> List[Problem]:
    """Problems of `value` against one schema node, as (code, field path) pairs."""
    node = _resolve(node, schema)
    here = path or "record"
    if "const" in node and value != node["const"]:
        return [("bad_value", here)]
    if "type" in node:
        names = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_type_ok(value, n) for n in names):
            return [("wrong_type", here)]
    if "enum" in node and value not in node["enum"]:
        return [("bad_value", here)]
    problems: List[Problem] = []
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0):
            problems.append(("bad_value", here))
        elif "pattern" in node and re.search(re.sub(r"(?<!\\)\$$", r"\\Z", node["pattern"]), value) is None:
            # `$` also matches before a trailing newline; `\Z` does not ("variant-1\n" is not an id).
            problems.append(("bad_value", here))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            problems.append(("bad_value", here))
    elif isinstance(value, list):
        if len(value) < node.get("minItems", 0):
            problems.append(("bad_value", here))
        if "items" in node:
            for i, item in enumerate(value):
                problems.extend(shape_problems(item, node["items"], schema, f"{here}[{i}]"))
    elif isinstance(value, dict):
        props = node.get("properties", {})
        for key in node.get("required", []):
            if key not in value:
                problems.append(("missing_field", f"{path}.{key}" if path else key))
        if node.get("additionalProperties") is False and any(k not in props for k in value):
            # The unknown key is text of the record's author: say where, never what.
            problems.append(("unknown_field", here))
        for key, sub in props.items():
            if key in value:
                problems.extend(shape_problems(value[key], sub, schema, f"{path}.{key}" if path else key))
    return problems


# ---------------------------------------------------------------------------------------------
# the rules a schema cannot say
# ---------------------------------------------------------------------------------------------

def _rows_of(rows: List[Dict[str, Any]], variant: str) -> List[Dict[str, Any]]:
    return [r for r in rows if r["variant"] == variant and r["blocking"]]


def passes_floor(rows: List[Dict[str, Any]], variant: str) -> bool:
    """Every blocking row of the variant passed. No blocking row at all is not a pass."""
    blocking = _rows_of(rows, variant)
    return bool(blocking) and all(r["result"] == "pass" for r in blocking)


def _row_key(row: Dict[str, Any]) -> Tuple[str, Any]:
    """What makes two rows the same measurement: the row id and, for rendered work, the width."""
    return row["id"], row.get("viewport")


def _complete(first: List[Dict[str, Any]], latest: List[Dict[str, Any]], variant: str) -> bool:
    """A re-capture carries every blocking row (id and width) the first capture had."""
    return {_row_key(r) for r in _rows_of(first, variant)} <= {_row_key(r) for r in _rows_of(latest, variant)}


def latest_rows(record: Dict[str, Any], variant: str) -> Optional[List[Dict[str, Any]]]:
    """The floor rows of the variant's LATEST capture: its last re-capture, or its first capture when
    it has none. None when the last re-capture lacks a blocking row the first capture had."""
    runner = record["runner"]
    caps = [c for c in runner["recaptures"] if c["variant"] == variant]
    if not caps:
        return runner["floor_rows"]
    latest = caps[-1]["floor_rows"]
    return latest if _complete(runner["floor_rows"], latest, variant) else None


def eligible_variants(record: Dict[str, Any]) -> List[str]:
    """The variants whose LATEST capture passes every blocking floor row (the schema's rule). A
    variant that passed first and fails after a re-capture is not eligible; neither is one whose
    re-capture is incomplete."""
    out = []
    for variant in record["runner"]["variants"]:
        rows = latest_rows(record, variant["id"])
        if rows is not None and passes_floor(rows, variant["id"]):
            out.append(variant["id"])
    return out


def _runner_problems(record: Dict[str, Any]) -> List[Problem]:
    runner = record["runner"]
    ids = [v["id"] for v in runner["variants"]]
    if ids != [f"variant-{i}" for i in range(1, len(ids) + 1)]:
        return [("variant_ids", "runner.variants")]
    problems: List[Problem] = []
    orders = runner["read_orders"]
    want = 2 if record["mode"] == "full" else 1
    if (len(orders) != want or any(sorted(o) != sorted(ids) for o in orders)
            or (want == 2 and orders[1] != orders[0][::-1])):
        problems.append(("read_order", "runner.read_orders"))
    rendered = record["work_kind"] == "rendered"
    groups = [("runner.floor_rows", runner["floor_rows"])]
    for i, cap in enumerate(runner["recaptures"]):
        if cap["variant"] not in ids:
            problems.append(("floor_row_variant", f"runner.recaptures[{i}]"))
        if cap["sequence"] != i + 1:
            problems.append(("recapture_sequence", f"runner.recaptures[{i}]"))
        groups.append((f"runner.recaptures[{i}].floor_rows", cap["floor_rows"]))
    for where, rows in groups:
        for i, row in enumerate(rows):
            if row["variant"] not in ids:
                problems.append(("floor_row_variant", f"{where}[{i}]"))
            scoped = ("viewport" in row and "element" in row) if rendered else ("locator" in row)
            if not scoped:
                problems.append(("floor_row_scope", f"{where}[{i}]"))
    for i, cap in enumerate(runner["recaptures"]):
        if any(r["variant"] != cap["variant"] for r in cap["floor_rows"]):
            problems.append(("floor_row_variant", f"runner.recaptures[{i}]"))
    return problems


def _repair_problems(record: Dict[str, Any], winner: str) -> List[Problem]:
    """Why a selected_for_repair winner is not yet a confirmed repair. Empty when it is."""
    runner, critic = record["runner"], record["critic"]
    repair = critic["repair"]
    caps = [c for c in runner["recaptures"] if c["variant"] == winner]
    if repair is None or not caps or repair["recapture"] != caps[-1]["sequence"]:
        return [("repair_no_recapture", winner)]
    latest = caps[-1]["floor_rows"]
    problems: List[Problem] = []
    if not _complete(runner["floor_rows"], latest, winner):
        problems.append(("repair_recapture_incomplete", winner))
    if not passes_floor(latest, winner):
        problems.append(("repair_recapture_fails", winner))
    if not (repair["rejudged"] and repair["confirmed"]):
        problems.append(("repair_not_rejudged", winner))
    return problems


def _borrow_problems(record: Dict[str, Any], losers: List[str]) -> List[Problem]:
    runner, critic = record["runner"], record["critic"]
    refs: Dict[str, set] = {v["id"]: set(v["evidence"]) for v in runner["variants"]}
    for cap in runner["recaptures"]:
        refs.setdefault(cap["variant"], set()).update(cap["evidence"])
    problems: List[Problem] = []
    if len(critic["borrowed"]) > record["borrow_max"]:
        problems.append(("borrow_over_max", "critic.borrowed"))
    for i, borrow in enumerate(critic["borrowed"]):
        where = f"critic.borrowed[{i}]"
        if borrow["from"] not in losers:
            problems.append(("borrow_source", where))
            continue
        kind = borrow["kind"]
        extra = set(borrow) - BORROW_COMMON - BORROW_FIELDS[kind]
        # A part is named the way its kind of work can be cut: a selector of a page, a heading and a
        # paragraph of a draft. The other form would pass here and give a card with nothing beside it.
        text = record["work_kind"] == "text"
        if kind == "fragment":
            locator = borrow.get("locator")
            ok = not extra and locator is not None and set(locator) == {"text" if text else "markup"}
            if ok and text:
                ok = locator["text"]["paragraph"] >= 1
            if not ok:
                problems.append(("borrow_locator", where))
        elif kind == "system":
            anchor = borrow.get("anchor")
            if extra or anchor is None or anchor["in"] not in SYSTEM_ANCHORS[record["work_kind"]]:
                problems.append(("borrow_anchor", where))
        else:
            region = borrow.get("evidence_region")
            ok = not extra and "technique" in borrow and region is not None
            if ok:
                if text:
                    ok = set(region) == {"text"}
                else:
                    ok = "text" not in region and region.get("evidence") in refs.get(borrow["from"], set())
            if not ok:
                problems.append(("borrow_move", where))
    return problems


def semantic_problems(record: Dict[str, Any]) -> List[Problem]:
    """The rules beyond the shape. Call only on a record whose shape is clean."""
    problems = _runner_problems(record)
    if problems:
        return problems
    runner, critic = record["runner"], record["critic"]
    ids = [v["id"] for v in runner["variants"]]
    eligible = eligible_variants(record)
    outcome, winner = critic["outcome"], critic["winner"]

    reads = critic["reads"]
    if [r["read"] for r in reads] != list(range(1, len(runner["read_orders"]) + 1)):
        problems.append(("reads_mismatch", "critic.reads"))
    picks = [r["pick"] for r in reads]
    if any(p is not None and p not in ids for p in picks):
        problems.append(("read_pick_unknown", "critic.reads"))
    if len(set(picks)) > 1 and not any(q["kind"] == "order_flip" for q in critic["open_to_user"]):
        problems.append(("flip_not_open_to_user", "critic.open_to_user"))
    if sorted(t["variant"] for t in critic["tells"]) != sorted(ids):
        problems.append(("tells_missing", "critic.tells"))
    if any(row["favours"] not in ids + ["none"] for row in critic["rubric"]):
        problems.append(("rubric_favours_unknown", "critic.rubric"))

    if outcome == "winner":
        if critic["no_award"] is not None:
            problems.append(("no_award_with_winner", "critic.no_award"))
        if not critic["rubric"]:
            problems.append(("rubric_empty", "critic.rubric"))
        if winner is None:
            return problems + [("winner_missing", "critic.winner")]
        if winner not in ids:
            return problems + [("winner_unknown", "critic.winner")]
        if winner not in picks:
            problems.append(("winner_not_picked", winner))
        if critic["rubric"] and not any(row["favours"] == winner for row in critic["rubric"]):
            problems.append(("winner_not_favoured", winner))
        repair = _repair_problems(record, winner) if critic["selected_for_repair"] else []
        repaired = critic["selected_for_repair"] and not repair
        problems.extend(repair)
        if not eligible and not repaired:
            problems.append(("no_award_required", "critic.outcome"))
        if winner not in eligible and not critic["selected_for_repair"]:
            problems.append(("winner_ineligible", winner))
        # A re-capture is newer than any judgement made before it. Whatever the first capture said,
        # a winner that has one is confirmed only by a record that names its LATEST re-capture as
        # re-judged: the record a critic wrote before the repair cannot say that.
        caps = [c for c in runner["recaptures"] if c["variant"] == winner]
        if caps and winner in eligible and not critic["selected_for_repair"]:
            said = critic["repair"]
            if said is None or said["recapture"] != caps[-1]["sequence"] or not (said["rejudged"] and said["confirmed"]):
                problems.append(("winner_not_rejudged", winner))
        losers = [v for v in ids if v != winner]
    else:
        if winner is not None:
            problems.append(("winner_with_no_award", "critic.winner"))
        if critic["selected_for_repair"] or critic["repair"] is not None:
            problems.append(("repair_without_winner", "critic.repair"))
        reason = critic["no_award"]
        if (reason is None or (reason["reason"] == "all_fail_blocking" and eligible)
                or (reason["reason"] == "brief_line_unmet" and "brief_line" not in reason)):
            problems.append(("no_award_unexplained", "critic.no_award"))
        if critic["borrowed"]:
            problems.append(("borrow_without_winner", "critic.borrowed"))
        losers = list(ids)

    if outcome == "winner":
        problems.extend(_borrow_problems(record, losers))
    borrowed_from = {b["from"] for b in critic["borrowed"]} if outcome == "winner" else set()
    rejected = [r["variant"] for r in critic["rejected"]]
    if len(set(rejected)) != len(rejected) or any(v not in losers for v in rejected):
        problems.append(("rejected_unknown", "critic.rejected"))
    for loser in losers:
        if loser in borrowed_from and loser in rejected:
            problems.append(("loser_in_both", loser))
        elif loser not in borrowed_from and loser not in rejected:
            problems.append(("loser_unaccounted", loser))
    return problems


def critic_row_problems(record: Dict[str, Any], rows: Sequence[str]) -> List[Problem]:
    """The floor rows the critic fills: exactly one entry per variant for each row of `rows`, and no
    winner whose entry does not hold. Call only on a record whose shape is clean."""
    problems: List[Problem] = []
    winner = record["critic"]["winner"]
    for row in rows:
        missing, fails = CRITIC_ROWS[row]
        held: Dict[str, bool] = {}
        for entry in record["critic"]["tells"]:
            found = [t for t in entry["tells"] if t["axis"] == row]
            if len(found) == 1:
                held[entry["variant"]] = found[0]["held"]
        problems += [(missing, v["id"]) for v in record["runner"]["variants"] if v["id"] not in held]
        if winner and held.get(winner) is False:
            problems.append((fails, winner))
    return problems


# ---------------------------------------------------------------------------------------------
# skeleton and check
# ---------------------------------------------------------------------------------------------

def blank_critic() -> Dict[str, Any]:
    """The critic part as the runner hands it over. The two null lists must be filled."""
    return {
        "reads": [], "tells": [], "rubric": [], "outcome": None, "winner": None,
        "selected_for_repair": False, "repair": None, "no_award": None,
        "borrowed": [], "rejected": [], "could_not_judge": None, "open_to_user": None,
    }


def skeleton_of(record: Dict[str, Any]) -> Dict[str, Any]:
    """The record with its critic part blanked: what the runner wrote."""
    out = copy.deepcopy(record)
    out["critic"] = blank_critic()
    return out


def skeleton_problems(skeleton: Any, schema: Optional[Dict[str, Any]] = None) -> List[Problem]:
    """Problems of the runner-written half of a skeleton (its critic part is not looked at)."""
    schema = schema or load_schema()
    if not isinstance(skeleton, dict):
        return [("wrong_type", "record")]
    probe = dict(skeleton)
    probe["critic"] = None
    problems = [p for p in shape_problems(probe, schema, schema) if p[1] != "critic"]
    return problems or _runner_problems(skeleton)


def _evidence_parts(variant: str, evidence: Any) -> Tuple[List[str], List[Dict[str, Any]], Optional[str]]:
    if not isinstance(evidence, dict) or not isinstance(evidence.get("floor_rows"), list):
        raise InputError("skeleton_invalid", variant)
    refs: List[str] = []
    for key in ("evidence", "tiles", "motion_frames"):
        got = evidence.get(key, [])
        if not isinstance(got, list) or any(not isinstance(r, str) for r in got):
            raise InputError("skeleton_invalid", variant)
        refs.extend(got)
    rows = []
    for row in evidence["floor_rows"]:
        if not isinstance(row, dict) or row.get("variant", variant) != variant:
            raise InputError("skeleton_invalid", variant)
        rows.append(dict(row, variant=variant))
    return refs, rows, evidence.get("direction_contract")


def build_skeleton(run_id: str, profile: str, work_kind: str, mode: str, borrow_max: int,
                   evidence: Dict[str, Any], order: Optional[List[str]] = None) -> Dict[str, Any]:
    """The record as the runner writes it. `evidence` maps variant id to an evidence file's content."""
    ids = sorted(evidence, key=lambda v: (len(v), v))
    variants, floor_rows = [], []
    for vid in ids:
        refs, rows, contract = _evidence_parts(vid, evidence[vid])
        entry: Dict[str, Any] = {"id": vid, "evidence": refs}
        if contract is not None:
            entry["direction_contract"] = contract
        variants.append(entry)
        floor_rows.extend(rows)
    if order is None:
        order = list(ids)
        random.SystemRandom().shuffle(order)
    orders = [list(order)] + ([list(order[::-1])] if mode == "full" else [])
    record = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "profile": profile, "work_kind": work_kind,
        "mode": mode, "borrow_max": borrow_max,
        "runner": {"variants": variants, "read_orders": orders, "floor_rows": floor_rows, "recaptures": []},
        "critic": blank_critic(),
    }
    problems = skeleton_problems(record)
    if problems:
        raise InputError("skeleton_invalid", problems[0][1])
    return record


def add_recapture(record: Dict[str, Any], variant: str, evidence: Any) -> Dict[str, Any]:
    """The record with one more re-capture of `variant`. The critic part is kept as it is."""
    out = copy.deepcopy(record)
    refs, rows, _ = _evidence_parts(variant, evidence)
    caps = out["runner"]["recaptures"]
    caps.append({"sequence": len(caps) + 1, "variant": variant, "evidence": refs, "floor_rows": rows})
    problems = skeleton_problems(out)
    if problems:
        raise InputError("skeleton_invalid", problems[0][1])
    return out


def check_record(record: Any, skeleton: Any, critic_rows: Sequence[str] = ()) -> List[Problem]:
    """Every reason to refuse `record`. An empty list means accepted. `critic_rows` are the floor
    rows the critic of this run fills (CRITIC_ROWS); they are looked at once the rest is clean."""
    schema = load_schema()
    if skeleton_problems(skeleton, schema):
        return [("skeleton_invalid", "")]
    problems = shape_problems(record, schema, schema)
    if problems:
        return problems
    same = record["runner"] == skeleton["runner"] and all(record[f] == skeleton[f] for f in IDENTITY_FIELDS)
    if not same:
        return [("runner_part_altered", "runner")]
    return semantic_problems(record) or critic_row_problems(record, critic_rows)


def _dedupe(problems: List[Problem]) -> List[Problem]:
    seen, out = set(), []
    for code, at in problems:
        at = at if _AT_SAFE.match(at or "") else ""
        if (code, at) not in seen:
            seen.add((code, at))
            out.append((code, at))
    return out


def check_report(problems: List[Problem]) -> Dict[str, Any]:
    """The studio-verdict-check.v1 document for a list of problems."""
    reasons = [dict({"code": code}, **({"at": at} if at else {})) for code, at in _dedupe(problems)]
    return {"schema_version": CHECK_VERSION, "accepted": not reasons, "reasons": reasons}


def _load(path: str) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise InputError("unreadable") from None
    try:
        return json.loads(text)
    except ValueError:
        raise InputError("not_json") from None


def _write(path: str, record: Dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _pairs(values: Sequence[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for value in values:
        vid, sep, path = value.partition("=")
        if not sep or re.match(r"^variant-[1-9][0-9]?$", vid) is None or vid in out:
            raise InputError("skeleton_invalid")
        out[vid] = _load(path)
    return out


def cmd_skeleton(args: argparse.Namespace) -> int:
    if args.source:
        if len(args.recapture) != 1 or args.variant:
            raise InputError("skeleton_invalid")
        (variant, evidence), = _pairs(args.recapture).items()
        base = _load(args.source)
        if skeleton_problems(base):
            raise InputError("skeleton_invalid")
        record = add_recapture(base, variant, evidence)
    else:
        needed = (args.run_id, args.profile, args.work_kind, args.mode, args.borrow_max)
        if any(v is None for v in needed) or args.recapture:
            raise InputError("skeleton_invalid")
        order = args.order.split(",") if args.order else None
        record = build_skeleton(args.run_id, args.profile, args.work_kind, args.mode, args.borrow_max,
                                _pairs(args.variant), order)
    _write(args.out, record)
    print("skeleton written")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    try:
        skeleton = _load(args.skeleton)
    except InputError:
        problems: List[Problem] = [("skeleton_invalid", "")]
    else:
        try:
            problems = check_record(_load(args.record), skeleton, args.critic_row)
        except InputError as exc:
            problems = [(exc.code, exc.at)]
    report = check_report(problems)
    if args.json:
        print(json.dumps(report, indent=2))
    elif report["accepted"]:
        print("accepted")
    else:
        print("refused")
        for reason in report["reasons"]:
            print(" ".join([reason["code"]] + ([reason["at"]] if "at" in reason else [])))
    return 0 if report["accepted"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio_verdict.py", description="The studio-verdict.v1 skeleton and checker.")
    sub = parser.add_subparsers(dest="command", required=True)
    skel = sub.add_parser("skeleton", help="write the record with the runner's parts and an empty critic part")
    skel.add_argument("--run-id")
    skel.add_argument("--profile")
    skel.add_argument("--work-kind", choices=WORK_KINDS)
    skel.add_argument("--mode", choices=MODES)
    skel.add_argument("--borrow-max", type=int)
    skel.add_argument("--variant", action="append", default=[], metavar="variant-N=EVIDENCE.json")
    skel.add_argument("--order", help="comma-separated variant ids; random when absent")
    skel.add_argument("--from", dest="source", metavar="RECORD.json", help="add a re-capture to this record")
    skel.add_argument("--recapture", action="append", default=[], metavar="variant-N=EVIDENCE.json")
    skel.add_argument("--out", required=True)
    skel.set_defaults(func=cmd_skeleton)
    check = sub.add_parser("check", help="accept or refuse a filled record")
    check.add_argument("record")
    check.add_argument("--skeleton", required=True, help="the record as the runner wrote it")
    check.add_argument("--critic-row", action="append", default=[], choices=sorted(CRITIC_ROWS),
                       help="a blocking floor row the critic of this run fills; repeat for each")
    check.add_argument("--json", action="store_true", help="print a studio-verdict-check.v1 document")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        print(" ".join(["refused", exc.code] + ([exc.at] if _AT_SAFE.match(exc.at or "") else [])))
        return 2


if __name__ == "__main__":
    sys.exit(main())
