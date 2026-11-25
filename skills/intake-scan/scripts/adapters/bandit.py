"""bandit.py -- adapter for bandit, pinned, Python files only (#350).

Bandit runs inside the sandbox over the Python files of the target. Every way a target
could quieten it is switched off on the command line:

    --ignore-nosec          a `# nosec` comment in the target removes nothing
    --ini /conf/bandit.ini  OUR empty ini. Without it bandit walks the target for a
                            `.bandit` file and takes skips and excludes from it
    -c /conf/bandit.yaml    OUR empty config, so no profile comes from anywhere else
    -x //none//             replaces bandit's default exclude list, which is matched as a
                            substring of the path (a directory named after a version
                            control tool would otherwise hide its files)
    explicit file list      each Python file is named, so nothing depends on bandit's own
                            discovery; a file with a Python interpreter line and no .py
                            suffix is included

The file list is ours, so the adapter can check the answer: a Python file that is missing
from bandit's metrics is the gap `python-file-not-analysed`, and a file bandit could not
parse is `partially-inspected`. Every result becomes a CAUTION finding through RULE_IDS.
Bandit's severity and confidence labels and its exit status are evidence only.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import (CAUTION, ISOLATION_NONE, SCANNER_BANDIT, SET_FILE_ID, Finding, Gap, Report,
               ScanTarget, TargetFile, gap, not_run, preflight, read_json_report,
               read_text_capped, sibling, target_relative)

TOOL = "bandit"
SCANNER = SCANNER_BANDIT
RULE_PREFIX = "BD-"
REPORT_NAME = "bandit.json"
TIMEOUT_S = 300
INI_NAME = "bandit.ini"
CONFIG_NAME = "bandit.yaml"
# A string no target path can contain: inventory paths never hold an empty segment.
NO_EXCLUDE = "//none//"
# Above this the file list goes to bandit as one recursive directory argument instead.
MAX_ARGV_BYTES = 512 * 1024
MAX_TRIAGE_TEXT = 600

PYTHON_EXT = (".py", ".pyw", ".pyi")

FORBIDDEN_FLAGS = frozenset({"--baseline", "-b", "--skip", "-s", "--tests", "-t", "--profile", "-p",
                             "--exit-zero", "--severity-level", "--confidence-level", "-l", "-i"})

# Every test id of bandit 1.9.4. An id that is not here becomes the gap `unknown-rule-id`.
RULE_IDS = frozenset((
    "B101 B102 B103 B104 B105 B106 B107 B108 B110 B112 B113 B201 B202 B301 B302 B303 B304 "
    "B305 B306 B307 B308 B309 B310 B311 B312 B313 B314 B315 B316 B317 B318 B319 B320 B321 "
    "B322 B323 B324 B325 B401 B402 B403 B404 B405 B406 B407 B408 B409 B410 B411 B412 B413 "
    "B414 B415 B501 B502 B503 B504 B505 B506 B507 B508 B509 B601 B602 B603 B604 B605 B606 "
    "B607 B608 B609 B610 B611 B612 B613 B614 B615 B701 B702 B703 B704").split())


def is_python(item: TargetFile, root: str) -> bool:
    """A Python file: by suffix, or by an interpreter line that names python."""
    if item.path.lower().endswith(PYTHON_EXT):
        return True
    if "." in item.path.rsplit("/", 1)[-1]:
        return False
    try:
        with open(os.path.join(root, *item.path.split("/")), "rb") as fh:
            head = fh.read(128)
    except OSError:
        return False
    first = head.split(b"\n", 1)[0]
    return first.startswith(b"#!") and b"python" in first


def python_files(target: ScanTarget) -> List[TargetFile]:
    return [f for f in target.stored() if is_python(f, target.root)]


def build_argv(paths: Sequence[str], python: Optional[str] = None) -> List[str]:
    """The scanner command, written with in-sandbox paths. Pure: it starts nothing.

    `paths` are target-relative. When the list is too long for one command line bandit is
    given the target directory with -r instead, and the caller's reconciliation catches
    whatever its own discovery leaves out.
    """
    sandbox = sibling("sandbox")
    argv = [python or (sandbox.TOOLS + "/bin/python"), "-m", "bandit",
            "--ini", "%s/%s" % (sandbox.CONF, INI_NAME),
            "-c", "%s/%s" % (sandbox.CONF, CONFIG_NAME),
            "--ignore-nosec", "-x", NO_EXCLUDE,
            "-f", "json", "-o", "%s/%s" % (sandbox.OUT, REPORT_NAME), "-q"]
    named = ["%s/%s" % (sandbox.TARGET, p) for p in paths]
    if sum(len(p.encode("utf-8", "surrogateescape")) + 1 for p in named) > MAX_ARGV_BYTES:
        argv += ["-r", "--", sandbox.TARGET]
    else:
        argv += ["--"] + named
    if FORBIDDEN_FLAGS.intersection(argv[:argv.index("--")]):
        raise AssertionError("a forbidden flag is on the scanner command line")
    return argv


def write_trusted_config(conf_dir: str) -> None:
    """Our own, empty bandit ini and config. Nothing here comes from a target."""
    with open(os.path.join(conf_dir, INI_NAME), "w", encoding="utf-8") as fh:
        fh.write("[bandit]\n")
    with open(os.path.join(conf_dir, CONFIG_NAME), "w", encoding="utf-8") as fh:
        fh.write("# trusted and empty: no skips, no excludes, no profile\n{}\n")


def our_rule_id(scanner_id: Any, rule_ids: Optional[Sequence[str]] = None) -> Optional[str]:
    table = RULE_IDS if rule_ids is None else frozenset(rule_ids)
    if isinstance(scanner_id, str) and scanner_id in table:
        return RULE_PREFIX + scanner_id
    return None


def _line(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 10 ** 7 else 0


def _clip(value: Any) -> str:
    return value[:MAX_TRIAGE_TEXT] if isinstance(value, str) else ""


def parse_report(report: Any, target: ScanTarget, expected: Sequence[TargetFile], *,
                 exit_status: Optional[int] = None, isolation: str = ISOLATION_NONE,
                 tool_version: Optional[str] = None, target_prefix: str = "/target",
                 rule_ids: Optional[Sequence[str]] = None) -> Report:
    """Turn one bandit JSON report into the common report shape.

    `expected` is the list of Python files bandit was given; every one of them has to show
    up in its metrics, or the difference is a gap.
    """
    evidence: Dict[str, Any] = {"exit_status": exit_status, "python_files": len(expected)}
    if not isinstance(report, dict) or not isinstance(report.get("results"), list) \
            or not isinstance(report.get("metrics"), dict):
        return not_run(SCANNER, isolation, [gap("scanner-report-unreadable", SCANNER)], evidence, tool_version)

    by_path = target.by_path()
    gaps: List[Gap] = []
    triage: List[Dict[str, Any]] = []

    inspected: Set[str] = set()
    unknown_files = 0
    for name in report["metrics"]:
        if name == "_totals":
            continue
        item = by_path.get(target_relative(name, target_prefix) or "")
        if item is None:
            unknown_files += 1
            triage.append({"kind": "unknown-file", "text": _clip(str(name))})
        else:
            inspected.add(item.file_id)

    partial: Set[str] = set()
    unplaced_errors = 0
    errors = report.get("errors")
    for item in errors if isinstance(errors, list) else []:
        found = by_path.get(target_relative(item.get("filename") if isinstance(item, dict) else None,
                                            target_prefix) or "")
        if found is None:
            unplaced_errors += 1
        else:
            partial.add(found.file_id)
        triage.append({"kind": "scanner-error", "file": found.file_id if found else SET_FILE_ID,
                       "text": _clip(item.get("reason") if isinstance(item, dict) else "")})
    missed = sorted(f.file_id for f in expected if f.file_id not in inspected)
    inspected -= partial

    findings: List[Finding] = []
    seen: Set[Tuple[str, str, int]] = set()
    unknown_rules = 0
    severities: Dict[str, int] = {}
    for result in report["results"]:
        if not isinstance(result, dict):
            unknown_rules += 1
            continue
        rule = our_rule_id(result.get("test_id"), rule_ids)
        item = by_path.get(target_relative(result.get("filename"), target_prefix) or "")
        file_id = item.file_id if item else SET_FILE_ID
        line = _line(result.get("line_number"))
        text = " | ".join(t for t in (_clip(result.get("issue_text")), _clip(result.get("code"))) if t)
        if rule is None:
            unknown_rules += 1
            triage.append({"kind": "unknown-rule-id", "file": file_id, "line": line,
                           "text": _clip(str(result.get("test_id"))) + ": " + text})
            continue
        label = result.get("issue_severity")
        if label in ("LOW", "MEDIUM", "HIGH", "UNDEFINED"):
            severities[label] = severities.get(label, 0) + 1
        if (rule, file_id, line) in seen:
            continue
        seen.add((rule, file_id, line))
        findings.append(Finding(rule, CAUTION, file_id, line, SCANNER))
        triage.append({"kind": "finding", "rule": rule, "file": file_id, "line": line, "text": text})
    evidence["results"] = len(report["results"])
    evidence["severity_counts"] = severities

    if partial:
        gaps.append(gap("partially-inspected", SCANNER, partial))
    if missed:
        gaps.append(gap("python-file-not-analysed", SCANNER, missed))
    if unplaced_errors:
        gaps.append(gap("scanner-crashed", SCANNER, count=unplaced_errors))
    if unknown_files:
        gaps.append(gap("unknown-file", SCANNER, count=unknown_files))
    if unknown_rules:
        gaps.append(gap("unknown-rule-id", SCANNER, count=unknown_rules))
    return Report(SCANNER, True, isolation, tool_version, tuple(findings), tuple(sorted(inspected)),
                  tuple(sorted(partial)), tuple(gaps), evidence, tuple(triage))


def run(target: ScanTarget, *, tool_root: Optional[str] = None, force_none: bool = False,
        work_parent: Optional[str] = None, timeout_s: int = TIMEOUT_S) -> Report:
    """Run bandit on the Python files of `target` inside the sandbox.

    A missing tool and a missing sandbox are gaps even when the target has no Python file:
    the state of the toolchain belongs in every record. With the tool and the sandbox in
    place and no Python file, there is nothing to run and nothing missing.
    """
    sandbox = sibling("sandbox")
    pre = preflight(SCANNER, TOOL, tool_root, force_none)
    expected = python_files(target)
    if pre.gaps:
        return not_run(SCANNER, pre.isolation, pre.gaps, {"python_files": len(expected)}, pre.tool_version)
    if not expected:
        return Report(SCANNER, False, pre.isolation, pre.tool_version, (), (), (), (),
                      {"python_files": 0}, ())
    work = tempfile.mkdtemp(prefix="intake-bd-", dir=work_parent)
    try:
        conf = os.path.join(work, "conf")
        os.makedirs(conf, 0o700)
        write_trusted_config(conf)
        argv = build_argv([f.path for f in expected])
        request = sandbox.SandboxRequest(tuple(argv), target.root, work, pre.venv, conf, timeout_s)
        result = sandbox.run(request, bwrap=pre.bwrap)
        if result.gap is not None:
            return not_run(SCANNER, result.isolation, [gap(result.gap, SCANNER)],
                           {"exit_status": result.exit_status, "python_files": len(expected)},
                           pre.tool_version)
        raw = read_json_report("%s/%s" % (result.out_dir, REPORT_NAME))
        report = parse_report(raw, target, expected, exit_status=result.exit_status,
                              isolation=result.isolation, tool_version=pre.tool_version,
                              target_prefix=sandbox.TARGET)
        if not report.ran:
            log = read_text_capped(result.stderr_path)
            return report._replace(gaps=(gap("scanner-crashed", SCANNER),) + report.gaps,
                                   triage=({"kind": "scanner-log", "text": log},) if log else ())
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)
