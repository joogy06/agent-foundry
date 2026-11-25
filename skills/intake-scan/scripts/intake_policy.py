#!/usr/bin/env python3
"""intake_policy.py -- from scan evidence to one verdict and one record (#350).

`build_record(evidence)` takes what a scan collected and returns the `intake-verdict.v1`
record: the verdict, the findings, the coverage, the gaps and the review history. The
rules for getting from one to the other are data, in `policy.json` beside this skill:

    rule id -> class        block, caution or info. A scanner's finding reaches the record
                            only when the id belongs to that scanner in the policy; any
                            other id is the gap `unknown-rule-id`, never a finding.
    required scanners       per target kind. skill: the in-house rules, the secrets catalog
                            and SkillSpector. repo: the in-house rules and the secrets
                            catalog. Everything else is optional.
    gap effects             a gap that means "this scanner's result is absent or cannot be
                            relied on" blocks when the scanner is required and is a caution
                            when it is optional. A gap that means "part of the target was
                            not looked at" is a caution. A gap that means "the scan itself
                            is incomplete" blocks.

THE VERDICT

    block     a block-rule hit with no matching exception, or a blocking gap
    caution   otherwise: a caution or info finding, or any other gap
    pass      otherwise. Pass therefore needs no finding at all and full coverage from the
              required and the optional scanners. The one finding that does not count is a
              block-rule hit with a matching exception: a person already decided on it.

WHAT THE VERDICT IS NOT MADE FROM. Each scanner reports numbers and labels about its own
run. They arrive under the report's `evidence` key and are copied into the record for a
person to read. Nothing in this module looks up a key inside that object: it is copied
whole, value by value, and the only test applied is that a value is a number or a short
plain word. A scanner cannot raise or lower a verdict by what it says about itself.

COVERAGE. Every adapter says which files it inspected. That is reconciled here against the
file list of the scan: a stored file no adapter inspected is the gap `file-not-covered`,
and an executable file that is not Python is the gap `language-not-analysed`, because no
static analyser here reads it. A gap is never reported as clean.

THE RECORD HOLDS NO TEXT FROM THE TARGET. File ids are opaque (f001), rule ids and gap
names come from our own tables, and every string is checked against the schema in
`schemas/intake-verdict.v1.json`. `validate_record()` applies that schema with the small
interpreter below, so the schema file is the authority and needs no third-party library.

This module never raises on bad evidence: a scan that cannot be judged gets a block record
that says so. It reads two files (the policy and the schema) and nothing else.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

SCHEMA = "intake-verdict.v1"
EVIDENCE_SCHEMA = "intake-scan-evidence.v1"
POLICY_SCHEMA = "intake-policy.v1"

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_PATH = os.path.join(SKILL_DIR, "policy.json")
SCHEMA_PATH = os.path.join(SKILL_DIR, "schemas", "intake-verdict.v1.json")

PASS = "pass"
CAUTION = "caution"
BLOCK = "block"
INFO = "info"
VERDICTS = (PASS, CAUTION, BLOCK)
CLASSES = (BLOCK, CAUTION, INFO)
EXIT_CODES = {PASS: 0, CAUTION: 1, BLOCK: 2}

KINDS = ("skill", "repo")

EFFECT_SCANNER = "scanner"
EFFECT_COVERAGE = "coverage"
EFFECT_BLOCK = "block"
EFFECTS = (EFFECT_SCANNER, EFFECT_COVERAGE, EFFECT_BLOCK)

# Steps of the scan that are not scanners. A gap from one of them is always required.
STEP_FETCH = "fetch"
STEP_SCAN = "scan"
STEP_COVERAGE = "coverage"
STEPS = (STEP_FETCH, STEP_SCAN, STEP_COVERAGE)

SCANNER_HARNESS = "harness-rules"

GAP_UNKNOWN_RULE = "unknown-rule-id"
GAP_UNKNOWN_FILE = "unknown-file"
GAP_NOT_RUN = "scanner-not-run"
GAP_NOT_COVERED = "file-not-covered"
GAP_LANGUAGE = "language-not-analysed"
GAP_INCOMPLETE = "scan-incomplete"
GAP_MALFORMED = "evidence-malformed"

REASON_BLOCK_HIT = "block-rule-hit"
REASON_REQUIRED_GAP = "required-scanner-gap"
REASON_BLOCKING_GAP = "blocking-gap"
REASON_CAUTION = "caution-finding"
REASON_OPTIONAL_GAP = "optional-gap"
REASON_INFO = "info-finding"

STATE_RAN = "ran"
STATE_NOT_RUN = "not-run"
STATE_NOT_NEEDED = "not-needed"

ISOLATIONS = ("bwrap", "none", "in-process")
THIRD_PARTY_ISOLATIONS = ("bwrap", "none")
NOT_RUN = "not-run"

SET_FILE_ID = "-"
EMPTY_TREE_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,49}$")
_RULE = re.compile(r"^[A-Z][A-Z0-9]{0,7}(-[A-Za-z0-9][A-Za-z0-9-]{0,23})?$")
_FILE = re.compile(r"^f[0-9]{3,7}$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+!-]{0,39}$")
_UNIT = re.compile(r"^(skills|agents|commands|workflows)/[A-Za-z0-9._@+-]{1,120}$")
_SOURCE_TYPES = ("git", "folder", "zip", "local", "unknown")
_CLASS_ORDER = {BLOCK: 0, CAUTION: 1, INFO: 2}


class PolicyError(Exception):
    """policy.json or the record schema is missing or does not have the expected form."""


# --------------------------------------------------------------------------------------
# The policy file
# --------------------------------------------------------------------------------------

def _read_json(path: str, what: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise PolicyError("%s could not be read (%s)" % (what, type(exc).__name__))


def check_policy(policy: Any) -> Dict[str, Any]:
    """Raise PolicyError unless `policy` has the form this module reads."""
    def bad(why: str) -> PolicyError:
        return PolicyError("the policy is malformed: %s" % why)

    if not isinstance(policy, dict) or policy.get("schema") != POLICY_SCHEMA:
        raise bad("unknown schema")
    if not isinstance(policy.get("version"), str) or not _WORD.match(policy["version"]):
        raise bad("version")
    rules = policy.get("rules")
    families = policy.get("rule_families")
    if not isinstance(rules, dict) or not isinstance(families, dict):
        raise bad("rules")
    for table in (rules, families):
        for key, value in table.items():
            if not isinstance(key, str) or value not in CLASSES:
                raise bad("a rule class")
    for rule_id in rules:
        if not _RULE.match(rule_id):
            raise bad("a rule id")
    scanners = policy.get("scanners")
    if not isinstance(scanners, dict) or not scanners:
        raise bad("scanners")
    for name, spec in scanners.items():
        if not isinstance(name, str) or not _NAME.match(name) or not isinstance(spec, dict):
            raise bad("a scanner")
        if not isinstance(spec.get("rules"), list) or not isinstance(spec.get("families"), list):
            raise bad("a scanner's rules")
        if any(r not in rules for r in spec["rules"]) or any(f not in families for f in spec["families"]):
            raise bad("a scanner names a rule that has no class")
        if spec.get("applies_to") not in ("all", "python"):
            raise bad("a scanner's applies_to")
        for flag in ("owns_block_rules", "counts_for_coverage"):
            if not isinstance(spec.get(flag), bool):
                raise bad("a scanner flag")
    for key in ("required_scanners", "optional_scanners"):
        table = policy.get(key)
        if not isinstance(table, dict) or sorted(table) != sorted(KINDS):
            raise bad(key)
        for names in table.values():
            if not isinstance(names, list) or any(n not in scanners for n in names):
                raise bad(key)
    for kind in KINDS:
        if set(policy["required_scanners"][kind]) & set(policy["optional_scanners"][kind]):
            raise bad("a scanner is both required and optional")
    gaps = policy.get("gaps")
    if not isinstance(gaps, dict):
        raise bad("gaps")
    for name, spec in gaps.items():
        if not isinstance(name, str) or not _NAME.match(name) or not isinstance(spec, dict) \
                or spec.get("effect") not in EFFECTS \
                or not isinstance(spec.get("description", ""), str):
            raise bad("a gap")
    return policy


def load_policy(path: Optional[str] = None) -> Dict[str, Any]:
    return check_policy(_read_json(path or POLICY_PATH, "the policy"))


def load_schema(path: Optional[str] = None) -> Dict[str, Any]:
    schema = _read_json(path or SCHEMA_PATH, "the record schema")
    if not isinstance(schema, dict) or schema.get("$id") != SCHEMA:
        raise PolicyError("the record schema is malformed")
    return schema


def rule_class(policy: Dict[str, Any], scanner: str, rule_id: Any) -> Optional[str]:
    """The class of `rule_id` when `scanner` reports it, or None when the id is not one
    this scanner owns in the policy."""
    spec = policy["scanners"].get(scanner)
    if spec is None or not isinstance(rule_id, str) or not _RULE.match(rule_id):
        return None
    if rule_id in spec["rules"]:
        return policy["rules"][rule_id]
    for prefix in spec["families"]:
        if rule_id.startswith(prefix) and len(rule_id) > len(prefix):
            return policy["rule_families"][prefix]
    return None


def is_required(policy: Dict[str, Any], kind: str, scanner: str) -> bool:
    return scanner in STEPS or scanner in policy["required_scanners"].get(kind, ())


def gap_effect(policy: Dict[str, Any], kind: str, scanner: str, gap_name: str) -> Tuple[str, str]:
    """(effect on the verdict, the reason it gives): block or caution.

    A gap name the policy does not list is handled as the strictest scanner gap: the
    result of that scanner cannot be relied on.
    """
    spec = policy["gaps"].get(gap_name)
    effect = spec["effect"] if spec is not None else EFFECT_SCANNER
    if gap_name == GAP_UNKNOWN_RULE and policy["scanners"].get(scanner, {}).get("owns_block_rules"):
        # An id nobody can class, from a scanner whose ids can block.
        effect = EFFECT_BLOCK
    if effect == EFFECT_BLOCK:
        return BLOCK, REASON_BLOCKING_GAP
    if effect == EFFECT_SCANNER and is_required(policy, kind, scanner):
        return BLOCK, REASON_REQUIRED_GAP
    return CAUTION, REASON_OPTIONAL_GAP


def describe_gap(policy: Dict[str, Any], gap_name: str) -> Optional[str]:
    """The policy's own fixed description of a gap, when it has one."""
    spec = policy["gaps"].get(gap_name)
    text = spec.get("description") if spec is not None else None
    return text or None


def exit_code(verdict: str) -> int:
    """0 pass, 1 caution, 2 block."""
    return EXIT_CODES[verdict]


# --------------------------------------------------------------------------------------
# Reading the evidence
# --------------------------------------------------------------------------------------

def now_iso(now: Optional[str] = None) -> str:
    if now is not None:
        return now
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) < 10 ** 15
    return isinstance(value, float) and math.isfinite(value)


def _copy_run_facts(facts: Any) -> Dict[str, Any]:
    """A report's `evidence` object, copied whole for the record.

    Kept: a number, a boolean, null, a short plain word, or one level of name -> number.
    Anything else is dropped, so no sentence can travel into a record this way. No key is
    looked up by name: what a scanner says about its own run is never read here.
    """
    out: Dict[str, Any] = {}
    if not isinstance(facts, dict):
        return out
    for key in sorted(k for k in facts if isinstance(k, str) and _WORD.match(k)):
        value = facts[key]
        if value is None or isinstance(value, bool) or _plain_number(value):
            out[key] = value
        elif isinstance(value, str):
            if _WORD.match(value):
                out[key] = value
        elif isinstance(value, dict):
            inner = {k: v for k, v in value.items()
                     if isinstance(k, str) and _WORD.match(k) and (v is None or _plain_number(v))}
            out[key] = {k: inner[k] for k in sorted(inner)}
    return out


def _file_ids(values: Any, known: Set[str]) -> Tuple[List[str], int]:
    """(the ids that are files of this scan, how many entries were not)."""
    good: Set[str] = set()
    unknown = 0
    for value in values if isinstance(values, (list, tuple)) else []:
        if isinstance(value, str) and value in known:
            good.add(value)
        else:
            unknown += 1
    return sorted(good), unknown


def _count(value: Any, floor: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10 ** 9:
        return max(value, floor)
    return floor


class _Gaps:
    """The gaps of one record, merged by (name, scanner)."""

    def __init__(self, policy: Dict[str, Any], kind: str) -> None:
        self.policy = policy
        self.kind = kind
        self.rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.reasons: Set[str] = set()

    def add(self, name: Any, scanner: Any, files: Iterable[str] = (), count: int = 0,
            reasons: Iterable[str] = ()) -> None:
        if not isinstance(name, str) or not _NAME.match(name):
            name = GAP_MALFORMED
        if not isinstance(scanner, str) or not _NAME.match(scanner):
            name, scanner = GAP_MALFORMED, STEP_SCAN
        effect, reason = gap_effect(self.policy, self.kind, scanner, name)
        self.reasons.add(reason)
        row = self.rows.setdefault((name, scanner), {"gap": name, "scanner": scanner, "effect": effect,
                                                     "files": set(), "count": 0, "reasons": set()})
        ids = set(files)
        row["files"] |= ids
        row["count"] = max(row["count"] + max(count, 0), len(row["files"]), 1)
        row["reasons"] |= {r for r in reasons if isinstance(r, str) and _NAME.match(r)}

    def listed(self) -> List[Dict[str, Any]]:
        out = []
        for row in self.rows.values():
            item = {"gap": row["gap"], "scanner": row["scanner"], "effect": row["effect"],
                    "files": sorted(row["files"]), "count": row["count"]}
            if row["reasons"]:
                item["reasons"] = sorted(row["reasons"])
            out.append(item)
        out.sort(key=lambda g: (0 if g["effect"] == BLOCK else 1, g["scanner"], g["gap"]))
        return out


def _subject(evidence: Dict[str, Any], kind: str) -> Dict[str, Any]:
    raw = evidence.get("subject") if isinstance(evidence.get("subject"), dict) else {}
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    source_type = source.get("type") if source.get("type") in _SOURCE_TYPES else "unknown"
    target = source.get("target") if isinstance(source.get("target"), str) else ""
    out_source: Dict[str, Any] = {"type": source_type, "target": target[:2000]}
    if isinstance(source.get("ref"), str):
        out_source["ref"] = source["ref"][:200]
    commit = raw.get("commit")
    digest = raw.get("tree_digest")
    subject: Dict[str, Any] = {
        "kind": kind,
        "source": out_source,
        "commit": commit if isinstance(commit, str) and _COMMIT.match(commit) else None,
        "tree_digest": digest if isinstance(digest, str) and _HEX64.match(digest) else EMPTY_TREE_DIGEST,
    }
    if isinstance(raw.get("unit"), str) and _UNIT.match(raw["unit"]):
        subject["unit"] = raw["unit"]
    return subject


# --------------------------------------------------------------------------------------
# The verdict and the record
# --------------------------------------------------------------------------------------

def _build(evidence: Dict[str, Any], policy: Dict[str, Any], record_id: str, kind: str,
           now: str) -> Dict[str, Any]:
    gaps = _Gaps(policy, kind)

    # -- the file list --------------------------------------------------------------
    stored: List[str] = []
    executable_other: List[str] = []
    python: Set[str] = set()
    entries = 0
    rows = evidence.get("files")
    if not isinstance(rows, list):
        rows = []
        gaps.add(GAP_MALFORMED, STEP_SCAN)
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _FILE.match(row["id"]):
            gaps.add(GAP_MALFORMED, STEP_SCAN)
            continue
        entries += 1
        if row.get("stored") is not True:
            continue
        stored.append(row["id"])
        if row.get("python") is True:
            python.add(row["id"])
        elif row.get("executable") is True:
            executable_other.append(row["id"])
    known = set(stored)
    all_ids = {row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)
               and _FILE.match(row["id"])}

    # -- gaps the scan itself recorded (acquisition, a step that failed) ------------
    for item in evidence.get("gaps") if isinstance(evidence.get("gaps"), list) else []:
        if not isinstance(item, dict):
            gaps.add(GAP_MALFORMED, STEP_SCAN)
            continue
        ids, _unknown = _file_ids(item.get("files"), all_ids)
        gaps.add(item.get("gap"), item.get("scanner", STEP_SCAN), ids, _count(item.get("count")),
                 item.get("reasons") if isinstance(item.get("reasons"), list) else ())

    # -- exceptions that match a hit of this scan -----------------------------------
    excepted: Set[Tuple[str, str]] = set()
    for item in evidence.get("excepted") if isinstance(evidence.get("excepted"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("rule"), str) and isinstance(item.get("file"), str):
            excepted.add((item["rule"], item["file"]))

    # -- one report per scanner -----------------------------------------------------
    reports: Dict[str, Dict[str, Any]] = {}
    raw_reports = evidence.get("reports")
    for report in raw_reports if isinstance(raw_reports, list) else []:
        name = report.get("scanner") if isinstance(report, dict) else None
        if not isinstance(name, str) or name not in policy["scanners"] or name in reports:
            gaps.add(GAP_MALFORMED, STEP_SCAN)
            continue
        reports[name] = report

    wanted = list(policy["required_scanners"][kind]) + list(policy["optional_scanners"][kind])
    # When acquisition or the scan itself already failed, that gap says why nothing ran.
    started = not any(g["scanner"] in (STEP_FETCH, STEP_SCAN) and g["effect"] == BLOCK
                      for g in gaps.rows.values())
    findings: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, int, str]] = set()
    coverage_rows: List[Dict[str, Any]] = []
    covered: Set[str] = set()
    partial_all: Set[str] = set()
    tools: Dict[str, Optional[str]] = {}
    run_facts: Dict[str, Dict[str, Any]] = {}
    third_party: Set[str] = set()

    for name in wanted:
        spec = policy["scanners"][name]
        required = is_required(policy, kind, name)
        report = reports.get(name)
        if report is None:
            if started:
                gaps.add(GAP_NOT_RUN, name)
            coverage_rows.append({"scanner": name, "state": STATE_NOT_RUN, "required": required,
                                  "isolation": NOT_RUN, "files_inspected": 0, "files_partial": 0})
            continue
        ran = report.get("ran") is True
        isolation = report.get("isolation") if report.get("isolation") in ISOLATIONS else NOT_RUN
        if isolation in THIRD_PARTY_ISOLATIONS:
            third_party.add(isolation)
        version = report.get("tool_version")
        if name != SCANNER_HARNESS and isinstance(version, str) and _VERSION.match(version):
            tools[name] = version
        facts = _copy_run_facts(report.get("evidence"))
        if facts:
            run_facts[name] = facts

        report_gaps = report.get("gaps") if isinstance(report.get("gaps"), list) else []
        for item in report_gaps:
            if not isinstance(item, dict):
                gaps.add(GAP_MALFORMED, STEP_SCAN)
                continue
            ids, _unknown = _file_ids(item.get("files"), known)
            gaps.add(item.get("gap"), name, ids, _count(item.get("count")))

        inspected, unknown_a = _file_ids(report.get("files_inspected"), known)
        partial, unknown_b = _file_ids(report.get("files_partial"), known)
        if unknown_a or unknown_b:
            gaps.add(GAP_UNKNOWN_FILE, name, count=unknown_a + unknown_b)
        if spec["counts_for_coverage"]:
            covered |= set(inspected) | set(partial)
        partial_all |= set(partial)

        needed = bool(stored) if spec["applies_to"] == "all" else bool(python)
        if ran:
            state = STATE_RAN
        elif report_gaps:
            state = STATE_NOT_RUN
        elif not needed:
            state = STATE_NOT_NEEDED
        else:
            state = STATE_NOT_RUN
            gaps.add(GAP_NOT_RUN, name)
        coverage_rows.append({"scanner": name, "state": state, "required": required,
                              "isolation": isolation, "files_inspected": len(inspected),
                              "files_partial": len(partial)})

        unknown_rules = 0
        unknown_files = 0
        for item in report.get("findings") if isinstance(report.get("findings"), list) else []:
            cls = rule_class(policy, name, item.get("rule")) if isinstance(item, dict) else None
            if cls is None:
                unknown_rules += 1
                continue
            file_id = item.get("file")
            if file_id != SET_FILE_ID and file_id not in all_ids:
                unknown_files += 1
                file_id = SET_FILE_ID
            line = _count(item.get("line"))
            key = (item["rule"], file_id, line, name)
            if key in seen:
                continue
            seen.add(key)
            finding: Dict[str, Any] = {"rule": item["rule"], "class": cls, "file": file_id,
                                       "line": line, "scanner": name}
            if cls == BLOCK and (item["rule"], file_id) in excepted:
                finding["excepted"] = True
            findings.append(finding)
        if unknown_rules:
            gaps.add(GAP_UNKNOWN_RULE, name, count=unknown_rules)
        if unknown_files:
            gaps.add(GAP_UNKNOWN_FILE, name, count=unknown_files)

    # -- coverage reconciliation ----------------------------------------------------
    uncovered = sorted(set(stored) - covered)
    if uncovered:
        gaps.add(GAP_NOT_COVERED, STEP_COVERAGE, uncovered)
    language_gap = sorted(executable_other)
    if language_gap:
        gaps.add(GAP_LANGUAGE, STEP_COVERAGE, language_gap)

    # -- the verdict ----------------------------------------------------------------
    findings.sort(key=lambda f: (_CLASS_ORDER[f["class"]], f["rule"], f["file"], f["line"], f["scanner"]))
    live_blocks = [f for f in findings if f["class"] == BLOCK and not f.get("excepted")]
    cautions = [f for f in findings if f["class"] == CAUTION]
    gap_list = gaps.listed()
    reasons_found = set(gaps.reasons)
    if live_blocks:
        reasons_found.add(REASON_BLOCK_HIT)
    if cautions:
        reasons_found.add(REASON_CAUTION)
    if any(f["class"] == INFO for f in findings):
        reasons_found.add(REASON_INFO)
    order = (REASON_BLOCK_HIT, REASON_REQUIRED_GAP, REASON_BLOCKING_GAP, REASON_CAUTION, REASON_INFO,
             REASON_OPTIONAL_GAP)
    reasons = [r for r in order if r in reasons_found]
    if reasons_found & {REASON_BLOCK_HIT, REASON_REQUIRED_GAP, REASON_BLOCKING_GAP}:
        verdict = BLOCK
    elif reasons:
        verdict = CAUTION
    else:
        verdict = PASS

    if "none" in third_party:
        isolation_used = "none"
    elif "bwrap" in third_party:
        isolation_used = "bwrap"
    else:
        isolation_used = NOT_RUN
    digest = evidence.get("inventory_digest")
    rules_version = evidence.get("rules_version")
    return {
        "schema": SCHEMA,
        "id": record_id,
        "created": now,
        "verdict": verdict,
        "reasons": reasons,
        "subject": _subject(evidence, kind),
        "inventory_digest": digest if isinstance(digest, str) and _HEX64.match(digest) else "",
        "versions": {
            "rules": rules_version if isinstance(rules_version, str) and _WORD.match(rules_version) else "unknown",
            "policy": policy["version"],
            "tools": {name: tools[name] for name in sorted(tools)},
        },
        "isolation": isolation_used,
        "findings": findings,
        "coverage": {
            "files": {"entries": entries, "stored": len(stored), "omitted": entries - len(stored)},
            "uncovered": uncovered,
            "partial": sorted(partial_all),
            "language_gap": language_gap,
            "scanners": coverage_rows,
        },
        "gaps": gap_list,
        "evidence": run_facts,
        "counts": {
            "findings": {
                "block": len(live_blocks),
                "caution": len(cautions),
                "info": sum(1 for f in findings if f["class"] == INFO),
                "excepted": sum(1 for f in findings if f.get("excepted")),
            },
            "gaps": {
                "block": sum(1 for g in gap_list if g["effect"] == BLOCK),
                "caution": sum(1 for g in gap_list if g["effect"] == CAUTION),
            },
        },
        "review": [],
    }


def incomplete_record(record_id: str, kind: str, *, gap_name: str = GAP_INCOMPLETE,
                      scanner: str = STEP_SCAN, subject: Optional[Dict[str, Any]] = None,
                      policy: Optional[Dict[str, Any]] = None, now: Optional[str] = None) -> Dict[str, Any]:
    """The block record of a scan that could not be judged at all."""
    evidence = {"id": record_id, "subject": dict(subject or {}), "files": [], "reports": [],
                "gaps": [{"gap": gap_name, "scanner": scanner}]}
    evidence["subject"]["kind"] = kind
    return build_record(evidence, policy, now=now)


def build_record(evidence: Any, policy: Optional[Dict[str, Any]] = None, *,
                 now: Optional[str] = None) -> Dict[str, Any]:
    """The `intake-verdict.v1` record for one scan.

    Never raises for bad evidence. Evidence that cannot be read at all gives a block
    record with the gap `evidence-malformed`; a failure in here gives one with the gap
    `scan-incomplete`. PolicyError is the one exception: without a policy there is no
    verdict to give, and the caller reports an internal error.
    """
    if policy is None:
        policy = load_policy()
    moment = now_iso(now)
    data = evidence if isinstance(evidence, dict) else {}
    record_id = data.get("id") if isinstance(data.get("id"), str) and _ID.match(data["id"]) else "invalid-id"
    subject = data.get("subject") if isinstance(data.get("subject"), dict) else {}
    kind = subject.get("kind") if subject.get("kind") in KINDS else "skill"
    if data is not evidence or record_id == "invalid-id" or subject.get("kind") not in KINDS:
        data = {"subject": subject, "files": [], "reports": [],
                "gaps": [{"gap": GAP_MALFORMED, "scanner": STEP_SCAN}]}
    try:
        return _build(data, policy, record_id, kind, moment)
    except Exception:  # noqa: BLE001 - a scan that cannot be judged is a block, never a crash
        fallback = {"subject": subject, "files": [], "reports": [],
                    "gaps": [{"gap": GAP_INCOMPLETE, "scanner": STEP_SCAN}]}
        return _build(fallback, policy, record_id, kind, moment)


# --------------------------------------------------------------------------------------
# Checking a record against the schema file
# --------------------------------------------------------------------------------------

def _type_ok(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _check(node: Any, value: Any, where: str, root: Dict[str, Any], errors: List[str]) -> None:
    """A small interpreter for the subset of JSON Schema the record schema uses."""
    if len(errors) >= 50 or not isinstance(node, dict):
        return
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        _check(root.get("$defs", {}).get(ref[len("#/$defs/"):]), value, where, root, errors)
    if "const" in node and value != node["const"]:
        errors.append("%s: not the expected value" % where)
    if "enum" in node and value not in node["enum"]:
        errors.append("%s: not an allowed value" % where)
    if "type" in node:
        names = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_type_ok(value, n) for n in names):
            errors.append("%s: wrong type" % where)
            return
    if "anyOf" in node:
        for option in node["anyOf"]:
            trial: List[str] = []
            _check(option, value, where, root, trial)
            if not trial:
                break
        else:
            errors.append("%s: matches no allowed form" % where)
    if isinstance(value, str):
        if "pattern" in node and re.search(node["pattern"], value) is None:
            errors.append("%s: does not match its pattern" % where)
        if "maxLength" in node and len(value) > node["maxLength"]:
            errors.append("%s: too long" % where)
    if _type_ok(value, "number") and "minimum" in node and value < node["minimum"]:
        errors.append("%s: below the minimum" % where)
    if isinstance(value, list) and "items" in node:
        for index, item in enumerate(value):
            _check(node["items"], item, "%s[%d]" % (where, index), root, errors)
    if isinstance(value, dict):
        properties = node.get("properties", {})
        for key in node.get("required", []):
            if key not in value:
                errors.append("%s: missing %s" % (where, key))
        names = node.get("propertyNames")
        extra = node.get("additionalProperties")
        for index, key in enumerate(sorted(value)):
            # A key is named in an error only when the schema lists it; any other key is
            # text this module did not choose.
            if key in properties:
                _check(properties[key], value[key], "%s.%s" % (where, key), root, errors)
                continue
            here = "%s.<key %d>" % (where, index)
            if names is not None:
                _check(names, key, here, root, errors)
            if extra is False:
                errors.append("%s: not an allowed key" % here)
            elif isinstance(extra, dict):
                _check(extra, value[key], here, root, errors)


def validate_record(record: Any, schema: Optional[Dict[str, Any]] = None) -> List[str]:
    """The ways `record` breaks the record schema. Empty when it is valid."""
    root = schema if schema is not None else load_schema()
    errors: List[str] = []
    _check(root, record, "record", root, errors)
    return errors


def summary(record: Dict[str, Any]) -> Dict[str, Any]:
    """Counts by rule and by gap: what a caller may print about a record."""
    by_rule: Dict[Tuple[str, str, str, bool], Dict[str, Any]] = {}
    for finding in record.get("findings", []):
        key = (finding["class"], finding["rule"], finding["scanner"], bool(finding.get("excepted")))
        row = by_rule.setdefault(key, {"class": key[0], "rule": key[1], "scanner": key[2],
                                       "excepted": key[3], "count": 0, "places": []})
        row["count"] += 1
        row["places"].append((finding["file"], finding["line"]))
    rows = sorted(by_rule.values(), key=lambda r: (_CLASS_ORDER[r["class"]], r["rule"], r["excepted"]))
    return {"rules": rows, "gaps": list(record.get("gaps", []))}


def render_verdict_table(policy: Optional[Dict[str, Any]] = None) -> List[str]:
    """The required and optional scanners per kind, as printable lines."""
    policy = policy or load_policy()
    lines = []
    for kind in KINDS:
        lines.append("%s: required %s; optional %s" % (
            kind, ", ".join(policy["required_scanners"][kind]),
            ", ".join(policy["optional_scanners"][kind])))
    return lines


def known_gap_names(policy: Optional[Dict[str, Any]] = None) -> Sequence[str]:
    return sorted((policy or load_policy())["gaps"])
