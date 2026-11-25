"""skillspector.py -- adapter for SkillSpector, pinned and static-only (#350).

SkillSpector is one scanner among four. It runs inside the sandbox with `--no-llm`, on the
whole extracted target, and writes a JSON report that this module turns into the common
report shape.

What the adapter passes, and never passes:

    scan /target --no-llm -f json -o /out/skillspector.json

    never --baseline, --use-shipped-baseline   a suppression list could come from the target
    never --transitive                         it follows references out of the target
    never --fail-on-findings / --fail-on-incomplete   the exit status is evidence, not a verdict

The scanner is started as `<venv>/bin/python -c <three fixed lines>` because the venv is
bound into the sandbox at another path, where its console script's interpreter line no
longer resolves, and the package has no `__main__`.

What the adapter does with the report:

  * Every issue becomes a CAUTION finding, through RULE_IDS. SkillSpector's score, severity
    label, recommendation and exit status are copied into `evidence` and are read by
    nothing: on five of our own trusted skills the tool said "do not install" five times.
  * `components` are the files it looked at. A component path that is not in the inventory
    is a gap.
  * `analysis_completeness` is the source of the gaps: a file inspected in part, an analyzer
    that did not complete, a suppressed finding.
  * Its own advisory lookup needs the network and so always fails in the sandbox. That one
    failure is recorded as `osv-subcheck-not-run`; the dependency adapter covers the ground.
  * The version and the source revision in the report are compared with the pins.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import (CAUTION, ISOLATION_NONE, SCANNER_SKILLSPECTOR, SET_FILE_ID, Finding, Gap, Report,
               ScanTarget, gap, not_run, preflight, read_json_report, read_text_capped,
               sibling, target_relative)

TOOL = "skillspector"
SCANNER = SCANNER_SKILLSPECTOR
RULE_PREFIX = "SS-"
REPORT_NAME = "skillspector.json"
TIMEOUT_S = 600

# The three lines that start the scanner. Fixed text; nothing from a target is in it.
BOOT = "import sys; from skillspector.cli import app; sys.exit(app())"

# Flags that must never reach the command line, whatever a later edit does.
FORBIDDEN_FLAGS = frozenset({
    "--baseline", "-b", "--use-shipped-baseline", "--show-suppressed", "--transitive",
    "--transitive-depth", "--transitive-allow-prefix", "--transitive-deny-prefix",
    "--fail-on-findings", "--fail-on-incomplete", "--yara-rules-dir", "--recursive", "-r",
    "--mcp-registry",
})

# Every rule id of SkillSpector v2.12.0 at the pinned commit. An id that is not here is
# not passed through: it becomes the gap `unknown-rule-id`.
RULE_IDS = frozenset((
    "AE1 AE2 AE3 AE4 AE5 AE6 AE7 AR1 AR2 AR3 AS1 AS2 AS3 AST1 AST2 AST3 AST4 AST5 AST6 AST7 "
    "AST8 AST9 AST10 BH1 BH2 BH3 DS1 DS2 DS3 DS4 E1 E2 E3 E4 E5 EA1 EA2 EA3 EA4 EA5 LP1 LP2 "
    "LP3 LP4 MP1 MP2 MP3 OH1 OH2 OH3 P1 P2 P3 P4 P5 P6 P7 P8 P9 PE1 PE2 PE3 PE4 PE5 RA1 RA2 "
    "RP1 RP2 RP3 SC1 SC2 SC3 SC4 SC5 SC6 SC7 SC8 SC9 SC10 SDI-2 SQP-1 SSD-2 SSR-1 SSRF1 SSRF2 "
    "SSRF3 T3 TM1 TM2 TM3 TM4 TP1 TP2 TP3 TP4 TR1 TR2 TR3 TT1 TT2 TT3 TT4 TT5 TT6 YR1 YR2 "
    "YR3 YR4").split())

# Analyzers that are switched off by --no-llm. "disabled" is expected for these only.
MODEL_ANALYZERS = frozenset({"meta_analyzer", "semantic_developer_intent",
                             "semantic_quality_policy", "semantic_security_discovery"})
ANALYZER_DONE = frozenset({"completed", "not_applicable"})
# The analyzer whose advisory lookup needs the network.
OSV_ANALYZER = "static_patterns_supply_chain"

_WORD = re.compile(r"^[A-Za-z_]{1,40}$")
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+!-]{0,39}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
MAX_TRIAGE_TEXT = 600


def build_argv(target_path: Optional[str] = None, python: Optional[str] = None) -> List[str]:
    """The scanner command, written with in-sandbox paths. Pure: it starts nothing."""
    sandbox = sibling("sandbox")
    argv = [python or (sandbox.TOOLS + "/bin/python"), "-c", BOOT, "scan",
            target_path or sandbox.TARGET, "--no-llm", "-f", "json",
            "-o", "%s/%s" % (sandbox.OUT, REPORT_NAME)]
    if FORBIDDEN_FLAGS.intersection(argv):
        raise AssertionError("a forbidden flag is on the scanner command line")
    return argv


def our_rule_id(scanner_id: Any, rule_ids: Optional[Sequence[str]] = None) -> Optional[str]:
    """Our id for a SkillSpector rule id, or None when the id is not in the table."""
    table = RULE_IDS if rule_ids is None else frozenset(rule_ids)
    if isinstance(scanner_id, str) and scanner_id in table:
        return RULE_PREFIX + scanner_id
    return None


def _word(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _WORD.match(value) else None


def _number(value: Any) -> Optional[float]:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _line(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 10 ** 7 else 0


def _clip(value: Any) -> str:
    return value[:MAX_TRIAGE_TEXT] if isinstance(value, str) else ""


def _revisions(report: Dict[str, Any]) -> Set[str]:
    """Every source revision the report states for itself."""
    found: Set[str] = set()
    metadata = report.get("metadata")
    provenance = metadata.get("llm_provenance") if isinstance(metadata, dict) else None
    analyzers = provenance.get("analyzers") if isinstance(provenance, dict) else None
    for item in analyzers if isinstance(analyzers, list) else []:
        revision = item.get("analyzer_revision") if isinstance(item, dict) else None
        source = revision.get("source_revision") if isinstance(revision, dict) else None
        value = source.get("value") if isinstance(source, dict) else None
        found.add(value.lower() if isinstance(value, str) and _COMMIT.match(value.lower()) else "unknown")
    return found


def _is_osv_exception(item: Dict[str, Any]) -> bool:
    """True for the one expected failure: the advisory lookup had no network."""
    analyzers = item.get("analyzers")
    names = [a for a in analyzers if isinstance(a, str)] if isinstance(analyzers, list) else []
    return (item.get("reason_code") == "analyzer_runtime_error"
            and item.get("fatal") is not True
            and bool(names) and all(n.startswith(OSV_ANALYZER + "_dependencies") for n in names))


def parse_report(report: Any, target: ScanTarget, *, exit_status: Optional[int] = None,
                 isolation: str = ISOLATION_NONE, pin_version: Optional[str] = None,
                 pin_commit: Optional[str] = None, target_prefix: str = "/target",
                 rule_ids: Optional[Sequence[str]] = None) -> Report:
    """Turn one SkillSpector JSON report into the common report shape.

    `report` is the parsed JSON, or anything else when the file was unusable. The score,
    the severity label, the recommendation and the exit status end up in `evidence` and
    nowhere else.
    """
    evidence: Dict[str, Any] = {"exit_status": exit_status}
    if not isinstance(report, dict) or not isinstance(report.get("issues"), list) \
            or not isinstance(report.get("components"), list):
        return not_run(SCANNER, isolation, [gap("scanner-report-unreadable", SCANNER)], evidence)

    by_path = target.by_path()
    gaps: List[Gap] = []
    triage: List[Dict[str, Any]] = []

    # -- evidence: stored, never read by the verdict ------------------------------------
    risk = report.get("risk_assessment") if isinstance(report.get("risk_assessment"), dict) else {}
    evidence["score"] = _number(risk.get("score"))
    evidence["severity"] = _word(risk.get("severity"))
    evidence["recommendation"] = _word(risk.get("recommendation"))
    completeness = report.get("analysis_completeness")
    completeness = completeness if isinstance(completeness, dict) else {}
    evidence["completeness_status"] = _word(completeness.get("status"))
    evidence["coverage_percent"] = _number(completeness.get("coverage_percent"))
    evidence["issues"] = len(report["issues"])

    # -- the tool is the pinned one ------------------------------------------------------
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    version = metadata.get("skillspector_version")
    version = version if isinstance(version, str) and _VERSION.match(version) else None
    if pin_version is not None and version != pin_version:
        gaps.append(gap("tool-version-mismatch", SCANNER))
    if pin_commit is not None and _revisions(report) != {pin_commit}:
        gaps.append(gap("tool-revision-mismatch", SCANNER))
    if metadata.get("llm_requested") not in (False, None) or metadata.get("inference_usage") not in ([], None):
        gaps.append(gap("model-use-reported", SCANNER))
    if report.get("execution_successful") is False or completeness.get("execution_successful") is False:
        gaps.append(gap("scanner-crashed", SCANNER))
    suppressed = report.get("suppressed_count")
    if (isinstance(suppressed, int) and suppressed > 0) or report.get("suppressed"):
        gaps.append(gap("findings-suppressed", SCANNER))

    # -- files inspected ----------------------------------------------------------------
    inspected: Set[str] = set()
    unknown_files = 0
    for component in report["components"]:
        rel = target_relative(component.get("path") if isinstance(component, dict) else None, target_prefix)
        item = by_path.get(rel) if rel else None
        if item is None:
            unknown_files += 1
            triage.append({"kind": "unknown-file", "text": _clip(str(rel))})
        else:
            inspected.add(item.file_id)

    # -- completeness: partial files, analyzers that did not finish ----------------------
    partial: Set[str] = set()
    osv_only = 0
    other_incomplete = 0
    for key in ("ledger_exceptions", "scope_exclusions"):
        rows = completeness.get(key)
        for item in rows if isinstance(rows, list) else []:
            if not isinstance(item, dict):
                other_incomplete += 1
                continue
            if key == "ledger_exceptions" and _is_osv_exception(item):
                osv_only += 1
                continue
            rel = target_relative(item.get("path"), target_prefix)
            found = by_path.get(rel) if rel else None
            if found is not None:
                partial.add(found.file_id)
            else:
                other_incomplete += 1
            triage.append({"kind": key, "file": found.file_id if found else SET_FILE_ID,
                           "text": _clip(item.get("reason_code")) + " " + _clip(item.get("message"))})
    statuses = completeness.get("analyzer_statuses")
    if not isinstance(statuses, list) or not statuses:
        other_incomplete += 1
    for item in statuses if isinstance(statuses, list) else []:
        name = item.get("analyzer_id") if isinstance(item, dict) else None
        status = item.get("status") if isinstance(item, dict) else None
        if status in ANALYZER_DONE or (status == "disabled" and name in MODEL_ANALYZERS):
            continue
        if name == OSV_ANALYZER and status == "degraded" and osv_only and not partial \
                and item.get("failed") in (0, None) and item.get("unaccounted") in (0, None) \
                and item.get("partial") == osv_only:
            continue
        other_incomplete += 1
    if osv_only:
        gaps.append(gap("osv-subcheck-not-run", SCANNER, count=osv_only))
    if partial:
        gaps.append(gap("partially-inspected", SCANNER, partial))
    if other_incomplete:
        gaps.append(gap("analyzer-incomplete", SCANNER, count=other_incomplete))
    if unknown_files:
        gaps.append(gap("unknown-file", SCANNER, count=unknown_files))

    # -- findings: caution, through the table -------------------------------------------
    findings: List[Finding] = []
    seen: Set[Tuple[str, str, int]] = set()
    unknown_rules = 0
    for issue in report["issues"]:
        if not isinstance(issue, dict):
            unknown_rules += 1
            continue
        rule = our_rule_id(issue.get("id"), rule_ids)
        places = issue.get("occurrences")
        places = [p for p in places if isinstance(p, dict)] if isinstance(places, list) else []
        if not places and isinstance(issue.get("location"), dict):
            places = [issue["location"]]
        located: List[Tuple[str, int]] = []
        for place in places or [{}]:
            rel = target_relative(place.get("file"), target_prefix)
            item = by_path.get(rel) if rel else None
            located.append((item.file_id if item else SET_FILE_ID, _line(place.get("start_line"))))
        text = " | ".join(t for t in (_clip(issue.get("pattern")), _clip(issue.get("finding")),
                                      _clip(issue.get("explanation"))) if t)
        if rule is None:
            unknown_rules += 1
            triage.append({"kind": "unknown-rule-id", "file": located[0][0], "line": located[0][1],
                           "text": _clip(str(issue.get("id"))) + ": " + text})
            continue
        for file_id, line in located:
            if (rule, file_id, line) in seen:
                continue
            seen.add((rule, file_id, line))
            findings.append(Finding(rule, CAUTION, file_id, line, SCANNER))
            triage.append({"kind": "finding", "rule": rule, "file": file_id, "line": line, "text": text})
    if unknown_rules:
        gaps.append(gap("unknown-rule-id", SCANNER, count=unknown_rules))

    return Report(SCANNER, True, isolation, version, tuple(findings), tuple(sorted(inspected - partial)),
                  tuple(sorted(partial)), tuple(gaps), evidence, tuple(triage))


def run(target: ScanTarget, *, tool_root: Optional[str] = None, force_none: bool = False,
        work_parent: Optional[str] = None, timeout_s: int = TIMEOUT_S) -> Report:
    """Run SkillSpector on `target` inside the sandbox and return its report.

    Not installed as pinned, or no sandbox: nothing is started and the report carries the
    gaps. A crash, a timeout or an unreadable report is a gap too.
    """
    sandbox = sibling("sandbox")
    toolchain = sibling("toolchain")
    pre = preflight(SCANNER, TOOL, tool_root, force_none)
    if pre.gaps:
        return not_run(SCANNER, pre.isolation, pre.gaps, tool_version=pre.tool_version)
    pin = toolchain.load_pins()[TOOL]
    work = tempfile.mkdtemp(prefix="intake-ss-", dir=work_parent)
    try:
        request = sandbox.SandboxRequest(tuple(build_argv()), target.root, work, pre.venv, None, timeout_s)
        result = sandbox.run(request, bwrap=pre.bwrap)
        if result.gap is not None:
            return not_run(SCANNER, result.isolation, [gap(result.gap, SCANNER)],
                           {"exit_status": result.exit_status}, pre.tool_version)
        raw = read_json_report("%s/%s" % (result.out_dir, REPORT_NAME))
        report = parse_report(raw, target, exit_status=result.exit_status, isolation=result.isolation,
                              pin_version=pin.version, pin_commit=pin.commit, target_prefix=sandbox.TARGET)
        if not report.ran:
            log = read_text_capped(result.stderr_path)
            return report._replace(gaps=(gap("scanner-crashed", SCANNER),) + report.gaps,
                                   triage=({"kind": "scanner-log", "text": log},) if log else ())
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)
