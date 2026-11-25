#!/usr/bin/env python3
"""intake.py -- the one command for intake scanning (#350).

    intake.py scan <git URL | folder | zip> [--kind skill|repo] [--ref REF]
    intake.py scan --local <unit>
    intake.py adopt <id> --to <unit path>
    intake.py triage <id> --accept|--reject --reason "..."
    intake.py override <id> --reason "..."
    intake.py except <rule> <path> --reason "..."
    intake.py baseline
    intake.py verify
    intake.py status [--purge]
    intake.py toolchain install|check

A scan is: fetch into the quarantine, extract to a private directory, run the in-house
rules and the secrets catalog in-process, run SkillSpector and bandit through the sandbox,
run the dependency check, reconcile coverage, apply the policy, and write ONE record with
ONE verdict beside the tar, plus the triage sheet for a person.

EXIT CODES. 0 pass (or, for the other commands, done and clean). 1 caution. 2 block, or a
request the ledger refuses. 3 a usage error or an internal error. A scan never exits 0
without a record, and every scan that started ends with a record: one that could not
complete gets a block record that names what is missing. There is no flag that skips a
check or lets an unscanned target through.

WHAT THIS COMMAND PRINTS. Rule ids, counts, our own fixed descriptions, opaque file ids
(f017), record ids, and paths of our own (the quarantine directory, a unit of this repo).
A scan never prints a file name of the target, a line of its content, a scanner's message,
a gap's diagnostic or a rejected path: all of those are text the target chose, and a
reader of this output may be an agent. They are written to `triage.md` in the quarantine
directory, which is for a person to read.

The commands that work on this repo's own tree (`verify`, `status`, `except`, `baseline`)
name files of this repo. A path is printed only when it is made of plain path characters;
any other is shown as "(name withheld)" with its digest. The file names inside a unit that
was adopted were chosen by its source, so such a file shows as its unit and a digest.

No model is called on any path, and nothing from a target is checked out, built, installed
or run. Third-party scanners are started only by the adapters, only inside the sandbox.

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import adapters  # noqa: E402
import harness_rules as hr  # noqa: E402
import intake_fetch  # noqa: E402

il = adapters.sibling("intake_ledger")
ip = adapters.sibling("intake_policy")

EXIT_PASS = 0
EXIT_CAUTION = 1
EXIT_BLOCK = 2
EXIT_ERROR = 3

BASELINE_REPORT_REL = "intake/baseline-report.md"
MAX_PLACES = 8
MAX_LISTED = 40
MAX_TRIAGE_ROWS = 2000
MAX_QUOTE = 240
MAX_DESCRIPTION = 1500

# Rules whose matching line is a credential-shaped value: the sheet names the place only.
_WITHHELD_RULES = ("H9", "C5")


class _Usage(Exception):
    """A command line this program does not accept."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        # argparse's own message repeats what was typed; ours does not.
        raise _Usage("the command line was not understood")


class Options(NamedTuple):
    root: str
    quarantine_root: Optional[str]
    tool_root: Optional[str]
    offline: bool
    force_none: bool


class FileSet(NamedTuple):
    """What a scan runs on, whether it came from a bundle or from a unit of this repo."""
    records: List[Any]                 # hr.FileRecord, every entry
    paths: Dict[str, str]              # file id -> path (text the target chose)
    stored: List[str]                  # ids of the regular files whose content was read
    notes: Dict[str, str]              # file id -> why an entry was not stored


# --------------------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------------------

def _out(line: str = "") -> None:
    print(line)


def _err(line: str) -> None:
    print(line, file=sys.stderr)


def _show_path(path: str, digest: str = "", doc: Optional[Dict[str, Any]] = None) -> str:
    """A path of this repo as it may be printed: plain, or a stand-in that names nothing.
    With the ledger (`doc`), a file inside an adopted unit shows as the unit and a digest."""
    return il.show_path(doc, path, digest)


def _ledger_or_none(root: str) -> Optional[Dict[str, Any]]:
    try:
        return il.load(root)
    except il.LedgerError:
        return None


def _describe_rule(rule_id: str) -> str:
    try:
        return hr.describe(rule_id)
    except KeyError:
        pass
    try:
        return adapters.describe_rule(rule_id)
    except KeyError:
        return "a rule with no description here"


def _describe_gap(policy: Dict[str, Any], name: str) -> str:
    text = ip.describe_gap(policy, name)
    if text:
        return text
    try:
        return adapters.describe_gap(name)
    except KeyError:
        return "a gap with no description here"


_REASON_TEXT = {
    ip.REASON_BLOCK_HIT: "a block rule hit with no matching exception",
    ip.REASON_REQUIRED_GAP: "a scanner required for this kind of target did not give a usable result",
    ip.REASON_BLOCKING_GAP: "the scan is incomplete",
    ip.REASON_CAUTION: "one or more caution findings",
    ip.REASON_INFO: "one or more info findings",
    ip.REASON_OPTIONAL_GAP: "part of the target was not covered",
}


def _print_record(record: Dict[str, Any], policy: Dict[str, Any]) -> None:
    counts = record["counts"]
    files = record["coverage"]["files"]
    _out("id: %s" % record["id"])
    _out("kind: %s" % record["subject"]["kind"])
    _out("verdict: %s" % record["verdict"])
    for reason in record["reasons"]:
        _out("  because: %s (%s)" % (reason, _REASON_TEXT[reason]))
    _out("files: %d stored, %d not stored" % (files["stored"], files["omitted"]))
    _out("isolation: %s" % record["isolation"])
    _out("findings: block %d, caution %d, info %d, excepted %d" % (
        counts["findings"]["block"], counts["findings"]["caution"], counts["findings"]["info"],
        counts["findings"]["excepted"]))
    for row in ip.summary(record)["rules"]:
        label = row["class"] + (" excepted" if row["excepted"] else "")
        _out("  %s  %s  x%d  %s" % (row["rule"], label, row["count"], _describe_rule(row["rule"])))
        places = ["%s:%d" % place for place in row["places"][:MAX_PLACES]]
        more = len(row["places"]) - len(places)
        _out("      at %s%s" % (" ".join(places), " (+%d more)" % more if more > 0 else ""))
    _out("gaps: block %d, caution %d" % (counts["gaps"]["block"], counts["gaps"]["caution"]))
    for gap in record["gaps"]:
        _out("  %s  %s  %s  x%d  %s" % (gap["gap"], gap["scanner"], gap["effect"], gap["count"],
                                         _describe_gap(policy, gap["gap"])))
        for reason in gap.get("reasons", []):
            _out("      reason %s" % reason)
        if gap["files"]:
            shown = gap["files"][:MAX_PLACES]
            more = len(gap["files"]) - len(shown)
            _out("      files %s%s" % (" ".join(shown), " (+%d more)" % more if more > 0 else ""))
    _out("scanners:")
    for row in record["coverage"]["scanners"]:
        _out("  %s  %s  %s  %s  inspected %d" % (
            row["scanner"], row["state"], "required" if row["required"] else "optional",
            row["isolation"], row["files_inspected"]))


# --------------------------------------------------------------------------------------
# Files on disk
# --------------------------------------------------------------------------------------

def _write_private(path: str, data: bytes, mode: int = 0o600) -> None:
    """Write `path` (mode 0600 unless told) through a temp file in the same directory and
    one rename."""
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dump(doc: Any) -> bytes:
    return (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def _norm(path: str) -> str:
    """A repo-relative path with forward slashes and no leading "./"."""
    return "/".join(p for p in str(path).replace("\\", "/").split("/") if p not in ("", "."))


def _private_dir(path: str) -> None:
    os.makedirs(path, 0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _new_id() -> str:
    return "q%s-%s" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), secrets.token_hex(4))


def _local_id(unit: str, digest: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]", ".", unit)[:60].strip(".") or "unit"
    return "u-%s-%s" % (slug, digest[:12])


def find_root(explicit: Optional[str] = None) -> str:
    """The repo root: --root, else the nearest directory above the working directory that
    holds the ledger, else the tree this file lives in, else the working directory."""
    if explicit:
        return os.path.abspath(explicit)
    here = os.path.abspath(os.getcwd())
    probe = here
    while True:
        if os.path.isfile(os.path.join(probe, *il.LEDGER_REL.split("/"))):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    own = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR)))
    if os.path.isfile(os.path.join(own, *il.LEDGER_REL.split("/"))):
        return own
    return here


# --------------------------------------------------------------------------------------
# The triage sheet: the one place text chosen by the target is written
# --------------------------------------------------------------------------------------

def _quote(text: Any, limit: int = MAX_QUOTE) -> str:
    """Target text made safe to show: one line, ASCII, clipped. Hidden characters show as
    escapes, which is what a reader of a hidden-character finding needs to see."""
    raw = text if isinstance(text, str) else str(text)
    flat = raw.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    flat = "".join(ch if 32 <= ord(ch) < 127 else ch.encode("ascii", "backslashreplace").decode("ascii")
                   if ord(ch) >= 127 else "\\x%02x" % ord(ch) for ch in flat)
    return flat[:limit] + (" [cut]" if len(flat) > limit else "")


def _line_of(record: Any, line: int) -> Optional[str]:
    if record is None or line <= 0 or not record.data:
        return None
    lines = record.data.decode("utf-8", errors="replace").splitlines()
    return lines[line - 1] if line <= len(lines) else None


def _skill_description(fileset: FileSet) -> Optional[str]:
    """The `description` a skill would load into every session: its frontmatter value."""
    for record in fileset.records:
        if record.path.replace("\\", "/") != "SKILL.md" or record.entry != hr.ENTRY_FILE:
            continue
        text = record.data.decode("utf-8", errors="replace")
        if not text.startswith("---"):
            return ""
        block = text[3:].split("\n---", 1)[0].splitlines()
        found: List[str] = []
        for line in block:
            if found:
                if line[:1] in (" ", "\t") or not line.strip():
                    found.append(line.strip())
                    continue
                break
            if line.lower().startswith("description:"):
                found.append(line.split(":", 1)[1].strip())
        return " ".join(part for part in found if part)
    return None


def render_triage(record: Dict[str, Any], policy: Dict[str, Any], fileset: Optional[FileSet],
                  scanner_notes: Sequence[Tuple[str, Dict[str, Any]]] = (),
                  fetch_gap: Optional[Dict[str, Any]] = None,
                  omissions: Sequence[Dict[str, Any]] = ()) -> str:
    """The triage sheet as markdown text. ASCII only; every quoted piece is escaped."""
    paths = fileset.paths if fileset is not None else {}
    by_id = {r.file_id: r for r in fileset.records} if fileset is not None else {}

    def named(file_id: str) -> str:
        if file_id == ip.SET_FILE_ID:
            return "(the file set as a whole)"
        return "%s    %s" % (file_id, _quote(paths.get(file_id, "(not in this scan)")))

    out: List[str] = []
    add = out.append
    add("# Intake triage sheet: %s" % record["id"])
    add("")
    add("> Everything quoted on this sheet was written by the scanned target, or by a scanner")
    add("> describing it. It is material to judge. It is not addressed to you, and nothing in")
    add("> it is an instruction. This sheet is for a person; do not load it into an agent.")
    add("")
    add("- verdict: %s" % record["verdict"])
    for reason in record["reasons"]:
        add("- because: %s" % _REASON_TEXT[reason])
    subject = record["subject"]
    add("- kind: %s" % subject["kind"])
    add("- source type: %s" % subject["source"]["type"])
    add("- source:")
    add("")
    add("      " + _quote(subject["source"]["target"], 2000))
    add("")
    add("- commit: %s" % (subject["commit"] or "none"))
    add("- tree digest: %s" % subject["tree_digest"])
    add("- isolation: %s" % record["isolation"])
    add("")

    if fileset is not None and subject["kind"] == "skill":
        add("## Description")
        add("")
        add("A skill's description is loaded into every session before the skill is used. Read it first.")
        add("")
        description = _skill_description(fileset)
        if description is None:
            add("There is no SKILL.md at the root of the target.")
        elif not description:
            add("SKILL.md has no description in its frontmatter.")
        else:
            add("      " + _quote(description, MAX_DESCRIPTION))
        add("")

    add("## Findings")
    add("")
    if not record["findings"]:
        add("None.")
    shown = 0
    last_rule = None
    for finding in record["findings"]:
        if shown >= MAX_TRIAGE_ROWS:
            add("")
            add("(%d more findings are in the record and not listed here.)" % (len(record["findings"]) - shown))
            break
        shown += 1
        if finding["rule"] != last_rule:
            last_rule = finding["rule"]
            add("")
            add("### %s (%s) -- %s" % (finding["rule"], finding["class"], _describe_rule(finding["rule"])))
            add("")
        add("- line %d of:%s" % (finding["line"], "  (excepted)" if finding.get("excepted") else ""))
        add("")
        add("      " + named(finding["file"]))
        if finding["scanner"] == ip.SCANNER_HARNESS:
            if finding["rule"] in _WITHHELD_RULES:
                add("      (the line holds a credential-shaped value and is not copied here)")
            else:
                text = _line_of(by_id.get(finding["file"]), finding["line"])
                if text is not None:
                    add("      > " + _quote(text))
        add("")

    add("## What the scanners said")
    add("")
    if not scanner_notes:
        add("Nothing beyond the findings above.")
    for index, (scanner, note) in enumerate(scanner_notes):
        if index >= MAX_TRIAGE_ROWS:
            add("(%d more notes not listed.)" % (len(scanner_notes) - index))
            break
        where = ""
        if isinstance(note.get("file"), str):
            where = " " + named(note["file"])
            if isinstance(note.get("line"), int):
                where += "  line %d" % note["line"]
        add("- %s / %s / %s:" % (scanner, _quote(note.get("kind", ""), 40), _quote(note.get("rule", "-"), 40)))
        add("")
        if where:
            add("     " + where)
        add("      > " + _quote(note.get("text", "")))
        add("")

    add("## Gaps")
    add("")
    if not record["gaps"]:
        add("None.")
    for gap in record["gaps"]:
        add("- %s (%s, %s): %s" % (gap["gap"], gap["scanner"], gap["effect"], _describe_gap(policy, gap["gap"])))
        for file_id in gap["files"][:200]:
            add("")
            add("      " + named(file_id))
        add("")

    if fetch_gap is not None:
        add("## Acquisition")
        add("")
        add("The target could not be acquired: %s." % _quote(fetch_gap.get("gap", ""), 60))
        add("")
        for item in (fetch_gap.get("rejections") or [])[:MAX_TRIAGE_ROWS]:
            add("- refused entry (%s):" % _quote(item.get("reason", ""), 60))
            add("")
            add("      " + _quote(item.get("path", "")))
            add("")
        if fetch_gap.get("diagnostic"):
            add("What the remote or the tool said:")
            add("")
            for line in str(fetch_gap["diagnostic"]).splitlines()[:40]:
                add("      > " + _quote(line))
            add("")

    if omissions:
        add("## Not stored")
        add("")
        add("These entries of the target were recorded and not stored. They were never opened.")
        add("")
        for item in list(omissions)[:MAX_TRIAGE_ROWS]:
            add("- %s (%s):" % (_quote(item.get("reason", ""), 60), _quote(item.get("entry", ""), 20)))
            add("")
            add("      " + _quote(item.get("path", "")))
            add("")

    if fileset is not None:
        add("## Files")
        add("")
        for record_file in fileset.records[:MAX_TRIAGE_ROWS * 10]:
            note = fileset.notes.get(record_file.file_id)
            add("      %s    %s%s" % (record_file.file_id, _quote(record_file.path),
                                      "    [not stored: %s]" % _quote(note, 60) if note else ""))
        add("")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# One scan of one file set
# --------------------------------------------------------------------------------------

def _harness_report(fileset: FileSet, kind: str) -> Dict[str, Any]:
    """The in-house rules as a report of the same shape the adapters return."""
    base: Dict[str, Any] = {"scanner": ip.SCANNER_HARNESS, "isolation": adapters.ISOLATION_IN_PROCESS,
                            "tool_version": hr.RULES_VERSION, "files_partial": [], "evidence": {}}
    try:
        findings = hr.scan(fileset.records, kind)
    except Exception:  # noqa: BLE001 - the rule set failing is a gap, never a clean result
        base.update(ran=False, findings=[], files_inspected=[],
                    gaps=[{"gap": "internal-error", "scanner": ip.SCANNER_HARNESS, "files": [], "count": 1}])
        return base
    base.update(ran=True, files_inspected=list(fileset.stored), gaps=[],
                findings=[dict(f.to_dict(), scanner=ip.SCANNER_HARNESS, sha256=f.sha256) for f in findings])
    return base


def _python_ids(target: Any) -> Optional[set]:
    try:
        bandit = importlib.import_module("adapters.bandit")
        return {f.file_id for f in bandit.python_files(target)}
    except Exception:  # noqa: BLE001 - fall back to the extension below
        return None


def collect(record_id: str, kind: str, subject: Dict[str, Any], inventory_digest: str,
            fileset: FileSet, target: Any, options: Options,
            excepted: Callable[[str, str, str], bool] = lambda rule, file_id, sha: False,
            extra_gaps: Sequence[Dict[str, Any]] = ()) -> Tuple[Dict[str, Any], List[Tuple[str, Dict[str, Any]]]]:
    """Run every scanner over one file set. Returns (evidence for the policy, the scanner
    notes for the triage sheet). The notes are text chosen by the target or by a scanner."""
    harness = _harness_report(fileset, kind)
    reports = adapters.run_all(target, tool_root=options.tool_root, force_none=options.force_none,
                               offline=options.offline)
    notes: List[Tuple[str, Dict[str, Any]]] = []
    for report in reports:
        notes.extend((report.scanner, dict(item)) for item in report.triage)

    python = _python_ids(target)
    stored = set(fileset.stored)
    rows = []
    for record in fileset.records:
        is_stored = record.file_id in stored
        if python is not None:
            is_python = record.file_id in python
        else:
            is_python = record.path.lower().endswith((".py", ".pyw"))
        rows.append({"id": record.file_id, "stored": is_stored,
                     "executable": bool(is_stored and hr.is_executable(record)),
                     "python": bool(is_stored and is_python)})
    hits = [{"rule": f["rule"], "file": f["file"]} for f in harness["findings"]
            if f["class"] == hr.BLOCK and excepted(f["rule"], f["file"], f.get("sha256", ""))]
    for finding in harness["findings"]:
        finding.pop("sha256", None)
    evidence = {
        "schema": ip.EVIDENCE_SCHEMA,
        "id": record_id,
        "subject": dict(subject, kind=kind),
        "inventory_digest": inventory_digest,
        "rules_version": hr.RULES_VERSION,
        "files": rows,
        "reports": [harness] + [report.to_dict() for report in reports],
        "gaps": list(extra_gaps),
        "excepted": hits,
    }
    return evidence, notes


def _materialise(records: Sequence[Any], parent: Optional[str] = None) -> str:
    """Write the regular files of a unit of this repo into a private 0700 directory, so the
    sandboxed scanners read exactly the bytes the rules read."""
    tmp = tempfile.mkdtemp(prefix="intake-scan-", dir=parent)
    os.chmod(tmp, 0o700)
    for record in records:
        if record.entry != hr.ENTRY_FILE or record.size is not None:
            continue
        parts = record.path.split("/")
        directory = os.path.join(tmp, *parts[:-1]) if len(parts) > 1 else tmp
        os.makedirs(directory, 0o700, exist_ok=True)
        path = os.path.join(directory, parts[-1])
        with open(path, "xb") as fh:       # exclusive: never writes through an existing name
            fh.write(record.data)
        os.chmod(path, 0o700 if record.mode & 0o111 else 0o600)
    return tmp


def _fileset(records: Sequence[Any], notes: Optional[Dict[str, str]] = None) -> FileSet:
    records = list(records)
    stored = [r.file_id for r in records if r.entry == hr.ENTRY_FILE and r.size is None]
    return FileSet(records, {r.file_id: r.path for r in records}, stored, dict(notes or {}))


def _local_target(root_dir: str, records: Sequence[Any], kind: str) -> Any:
    files = []
    for record in records:
        is_stored = record.entry == hr.ENTRY_FILE and record.size is None
        files.append(adapters.TargetFile(
            record.file_id, record.path, record.mode,
            len(record.data) if is_stored else int(record.size or 0),
            hashlib.sha256(record.data).hexdigest() if is_stored else "",
            record.entry, is_stored))
    return adapters.ScanTarget(root_dir, tuple(files), kind)


# --------------------------------------------------------------------------------------
# scan <target>
# --------------------------------------------------------------------------------------

def _finish(record: Dict[str, Any], policy: Dict[str, Any], directory: str, sheet: str,
            internal: bool) -> int:
    """Write the record and the sheet into `directory`, print the summary, give the exit."""
    problems = ip.validate_record(record)
    if problems:
        # A record that breaks its own schema is not written as if it were sound.
        record = ip.incomplete_record(record["id"], record["subject"]["kind"], subject=record["subject"],
                                      policy=policy, now=record["created"])
        internal = True
    written = True
    try:
        _private_dir(directory)
        _write_private(os.path.join(directory, il.RECORD_NAME), _dump(record))
        _write_private(os.path.join(directory, il.TRIAGE_NAME), sheet.encode("ascii", "backslashreplace"))
    except OSError:
        written = False
    _print_record(record, policy)
    if not written:
        _out("record: NOT WRITTEN (the quarantine directory could not be written)")
        return EXIT_ERROR
    _out("record: %s" % os.path.join(directory, il.RECORD_NAME))
    _out("triage sheet (for a person): %s" % os.path.join(directory, il.TRIAGE_NAME))
    if internal:
        _out("result: internal error; the record is a block")
        return EXIT_ERROR
    return ip.exit_code(record["verdict"])


def _no_bundle(target: str, kind: str, gap: Dict[str, Any], policy: Dict[str, Any], options: Options,
               source_type: Optional[str], ref: Optional[str]) -> int:
    """The block record of a scan whose target could not be acquired."""
    record_id = _new_id()
    name = gap.get("gap") if gap.get("gap") in policy["gaps"] else ip.GAP_INCOMPLETE
    subject = {"kind": kind, "source": {"type": source_type or "unknown", "target": target, "ref": ref},
               "commit": None}
    evidence = {"id": record_id, "subject": subject, "files": [], "reports": [],
                "gaps": [{"gap": name, "scanner": ip.STEP_FETCH,
                          "reasons": [r for r in gap.get("reasons", []) if isinstance(r, str)]}]}
    record = ip.build_record(evidence, policy)
    sheet = render_triage(record, policy, None, fetch_gap=gap)
    directory = os.path.join(intake_fetch.resolve_quarantine_root(options.quarantine_root), record_id)
    return _finish(record, policy, directory, sheet, bool(gap.get("internal")))


def scan_bundle(bundle_dir: str, inventory: Dict[str, Any], kind: str, policy: Dict[str, Any],
                options: Options) -> Tuple[Dict[str, Any], str]:
    """Scan a fetched bundle. Returns (record, triage sheet)."""
    notes = {row["id"]: str(row.get("omitted")) for row in inventory["files"] if not row.get("stored")}
    fileset = _fileset([hr.FileRecord(*entry) for entry in intake_fetch.iter_bundle_entries(bundle_dir)], notes)
    source = inventory.get("source", {})
    subject = {"kind": kind,
               "source": {"type": source.get("type"), "target": source.get("target"), "ref": source.get("ref")},
               "commit": source.get("commit"), "tree_digest": inventory.get("tree_digest")}
    extra = []
    if any(item.get("reason") == intake_fetch.R_VCS_DIR for item in inventory.get("omissions", [])):
        extra.append({"gap": "vcs-directory-skipped", "scanner": ip.STEP_COVERAGE})
    with intake_fetch.extracted(bundle_dir) as path:
        target = adapters.target_from_inventory(path, inventory, kind)
        evidence, scanner_notes = collect(inventory["bundle_id"], kind, subject,
                                          inventory.get("inventory_digest", ""), fileset, target,
                                          options, extra_gaps=extra)
    record = ip.build_record(evidence, policy)
    sheet = render_triage(record, policy, fileset, scanner_notes, omissions=inventory.get("omissions", []))
    return record, sheet


def cmd_scan(args: argparse.Namespace, options: Options) -> int:
    if args.local is not None:
        if args.target is not None or args.ref is not None:
            raise _Usage("scan --local takes a unit and nothing else")
        return cmd_scan_local(args.local, options)
    if args.target is None:
        raise _Usage("scan needs a target (a git URL, a folder or a zip) or --local <unit>")
    policy = ip.load_policy()
    target = args.target
    source_type = intake_fetch.classify_target(target)
    _out("intake-scan: scan")
    if options.offline and source_type == intake_fetch.SOURCE_GIT:
        return _no_bundle(target, args.kind, {"gap": "offline-git-target"}, policy, options, source_type, args.ref)
    result = intake_fetch.fetch(target, quarantine_root=options.quarantine_root, ref=args.ref)
    if not result.ok or result.bundle_dir is None or result.inventory is None:
        return _no_bundle(target, args.kind, result.gap or {"gap": ip.GAP_INCOMPLETE, "internal": True},
                          policy, options, source_type, args.ref)
    internal = False
    try:
        record, sheet = scan_bundle(result.bundle_dir, result.inventory, args.kind, policy, options)
    except Exception:  # noqa: BLE001 - a scan that fails still ends in a block record
        internal = True
        source = result.inventory.get("source", {})
        subject = {"kind": args.kind, "commit": source.get("commit"),
                   "tree_digest": result.inventory.get("tree_digest"),
                   "source": {"type": source.get("type"), "target": source.get("target"), "ref": source.get("ref")}}
        record = ip.incomplete_record(str(result.bundle_id), args.kind, subject=subject, policy=policy)
        sheet = render_triage(record, policy, None)
    code = _finish(record, policy, result.bundle_dir, sheet, internal)
    if code in (EXIT_PASS, EXIT_CAUTION, EXIT_BLOCK):
        _out("next: %s" % _next_step(record))
    return code


def _next_step(record: Dict[str, Any]) -> str:
    record_id = record["id"]
    if record["verdict"] == ip.PASS:
        return "intake.py adopt %s --to <unit path>" % record_id
    if record["verdict"] == ip.CAUTION:
        return ("a person reads the triage sheet, then: intake.py triage %s --accept --reason \"...\" "
                "(or --reject), then adopt" % record_id)
    return ("a person reads the triage sheet, then: intake.py override %s --reason \"...\" "
            "or intake.py triage %s --reject --reason \"...\"" % (record_id, record_id))


# --------------------------------------------------------------------------------------
# scan --local <unit> and baseline: units of this repo
# --------------------------------------------------------------------------------------

def scan_unit(root: str, unit: str, records: Sequence[Any], digest: str, policy: Dict[str, Any],
              options: Options, doc: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], str]:
    """The full scan of one unit of this repo. Returns (record, triage sheet).

    `records` are the unit's files with unit-relative paths, as the ledger gives them. A
    block-rule hit that has a matching exception in the ledger is marked excepted.
    """
    fileset = _fileset(records)
    kind = il.RULE_KIND
    is_dir = unit.startswith("skills/")

    def excepted(rule: str, file_id: str, sha256: str) -> bool:
        rel = fileset.paths.get(file_id)
        if doc is None or rel is None or not sha256:
            return False
        return il.exception_matches(doc, rule, unit + "/" + rel if is_dir else unit, sha256)

    record_id = _local_id(unit, digest)
    subject = {"kind": kind, "source": {"type": "local", "target": unit, "ref": None}, "commit": None,
               "tree_digest": digest, "unit": unit}
    tmp = _materialise(fileset.records)
    try:
        target = _local_target(tmp, fileset.records, kind)
        evidence, notes = collect(record_id, kind, subject, "", fileset, target, options, excepted)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    record = ip.build_record(evidence, policy)
    # A unit scanned again at the same digest keeps the decisions already written on it.
    try:
        earlier, _path = il.find_record(root, record_id, options.quarantine_root)
        if earlier["subject"]["tree_digest"] == digest:
            record["review"] = list(earlier.get("review", []))
            if earlier.get("rejected"):
                record["rejected"] = True
                record["verdict"] = ip.BLOCK
    except il.LedgerError:
        pass
    problems = ip.validate_record(record)
    if problems:
        record = ip.incomplete_record(record_id, kind, subject=subject, policy=policy)
    return record, render_triage(record, policy, fileset, notes)


def _write_sheet(record_id: str, sheet: str, options: Options) -> Optional[str]:
    directory = os.path.join(intake_fetch.resolve_quarantine_root(options.quarantine_root), record_id)
    try:
        _private_dir(os.path.dirname(directory))
        _private_dir(directory)
        path = os.path.join(directory, il.TRIAGE_NAME)
        _write_private(path, sheet.encode("ascii", "backslashreplace"))
        return path
    except OSError:
        return None


def cmd_scan_local(unit_arg: str, options: Options) -> int:
    unit = _norm(unit_arg)
    if not il.is_unit(unit):
        raise _Usage("--local takes a unit: skills/<name>, or a file directly under agents/, "
                     "commands/ or workflows/")
    policy = ip.load_policy()
    root = options.root
    items = il.unit_items(root, unit)
    if not items:
        raise _Usage("the unit does not exist or holds no file")
    digest = il.tree_digest(items, unit)
    doc = il.load(root) if il.exists(root) else None
    _out("intake-scan: scan --local")
    _out("unit: %s" % _show_path(unit))
    record, sheet = scan_unit(root, unit, il.to_records(items, unit), digest, policy, options, doc)
    il.write_record(root, record)
    _print_record(record, policy)
    _out("record: %s" % os.path.join(il.RECORDS_REL, record["id"] + ".json"))
    sheet_path = _write_sheet(record["id"], sheet, options)
    _out("triage sheet (for a person): %s" % (sheet_path or "NOT WRITTEN"))
    try:
        entry = il.add_local_entry(root, unit, record)
    except il.LedgerRefused as exc:
        _out("ledger entry: not written (%s: %s)" % (exc.code, exc))
        _print_hits(exc.hits, doc=doc)
        if exc.code == "unexcepted-block-finding":
            # A block finding the in-house rules do not own (H10) takes no exception.
            _out("next: a person reads the triage sheet, then: intake.py override %s --reason \"...\", "
                 "then scan --local again" % record["id"])
        else:
            _out("next: fix each hit, or intake.py except <rule> <path> --reason \"...\", then scan again")
        return EXIT_BLOCK
    except il.LedgerError as exc:
        _out("ledger entry: not written (%s)" % exc)
        return EXIT_ERROR
    _out("ledger entry: written (verdict %s%s)" % (
        entry["verdict"], ", unsigned caution" if entry["unsigned_caution"] else ""))
    return ip.exit_code(record["verdict"])


def _print_hits(hits: Sequence[Any], limit: int = MAX_LISTED, doc: Optional[Dict[str, Any]] = None) -> None:
    for hit in list(hits)[:limit]:
        _out("  %s  %s:%d  %s" % (hit.rule_id, _show_path(hit.path, hit.sha256, doc), hit.line,
                                  _describe_rule(hit.rule_id)))
    if len(hits) > limit:
        _out("  (+%d more)" % (len(hits) - limit))


def cmd_baseline(args: argparse.Namespace, options: Options) -> int:
    policy = ip.load_policy()
    root = options.root
    doc = il.load(root) if il.exists(root) else None
    rule_counts: Dict[Tuple[str, str], int] = {}
    gap_counts: Dict[Tuple[str, str], int] = {}
    rows: List[Tuple[str, str, int, int, int]] = []
    done = [0]

    def one(unit: str, records: List[Any], digest: str) -> Dict[str, Any]:
        record, sheet = scan_unit(root, unit, records, digest, policy, options, doc)
        _write_sheet(record["id"], sheet, options)
        for finding in record["findings"]:
            key = (finding["rule"], finding["class"])
            rule_counts[key] = rule_counts.get(key, 0) + 1
        for gap in record["gaps"]:
            key = (gap["gap"], gap["effect"])
            gap_counts[key] = gap_counts.get(key, 0) + 1
        counts = record["counts"]["findings"]
        rows.append((unit, record["verdict"], counts["block"], counts["caution"], len(record["gaps"])))
        done[0] += 1
        _err("baseline: %d scanned (%s)" % (done[0], record["verdict"]))
        return record

    _out("intake-scan: baseline")
    result = il.baseline(root, one)
    report = _baseline_report(result, rule_counts, gap_counts, rows, _ledger_or_none(root))
    report_path = os.path.join(root, *BASELINE_REPORT_REL.split("/"))
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    _write_private(report_path, report.encode("ascii", "backslashreplace"), 0o644)
    _out("units: %d" % len(result["units"]))
    _out("verdicts: pass %d, caution %d, block %d" % (
        result["verdicts"]["pass"], result["verdicts"]["caution"], result["verdicts"]["block"]))
    _out("block-rule hits in the enforced tree:")
    for rule in sorted(result["block_hits"]):
        _out("  %s  x%d  %s" % (rule, result["block_hits"][rule], _describe_rule(rule)))
    _out("hits with no exception: %d" % len(result["unexcepted"]))
    _print_hits(result["unexcepted"], doc=_ledger_or_none(root))
    _out("report: %s" % BASELINE_REPORT_REL)
    return EXIT_BLOCK if result["unexcepted"] else EXIT_PASS


def _baseline_report(result: Dict[str, Any], rule_counts: Dict[Tuple[str, str], int],
                     gap_counts: Dict[Tuple[str, str], int],
                     rows: Sequence[Tuple[str, str, int, int, int]],
                     doc: Optional[Dict[str, Any]] = None) -> str:
    out: List[str] = ["# Intake baseline of this library", ""]
    add = out.append
    add("Written by `intake.py baseline` on %s. Report-only: every unit below now has a ledger" % il.now_iso()[:10])
    add("entry and a record under `intake/records/`, whatever its verdict.")
    add("")
    add("- units scanned: %d" % len(result["units"]))
    add("- verdicts: pass %d, caution %d, block %d" % (
        result["verdicts"]["pass"], result["verdicts"]["caution"], result["verdicts"]["block"]))
    add("- block-rule hits with no exception: %d" % len(result["unexcepted"]))
    add("")
    add("## Findings per rule")
    add("")
    add("| Rule | Class | Findings | Description |")
    add("|---|---|---|---|")
    for (rule, cls), count in sorted(rule_counts.items(), key=lambda kv: (ip.CLASSES.index(kv[0][1]), kv[0][0])):
        add("| %s | %s | %d | %s |" % (rule, cls, count, _describe_rule(rule)))
    add("")
    add("## Gaps")
    add("")
    add("| Gap | Effect | Units |")
    add("|---|---|---|")
    for (gap, effect), count in sorted(gap_counts.items()):
        add("| %s | %s | %d |" % (gap, effect, count))
    add("")
    add("## Block-rule hits with no exception")
    add("")
    add("Each is fixed, or excepted one by one with `intake.py except <rule> <path> --reason`.")
    add("")
    if not result["unexcepted"]:
        add("None.")
    for hit in result["unexcepted"]:
        add("- %s `%s` line %d" % (hit.rule_id, _show_path(hit.path, hit.sha256, doc), hit.line))
    add("")
    add("## Units")
    add("")
    add("| Unit | Verdict | Block hits | Caution findings | Gaps |")
    add("|---|---|---|---|---|")
    for unit, verdict, blocks, cautions, gaps in sorted(rows):
        add("| %s | %s | %d | %d | %d |" % (_show_path(unit), verdict, blocks, cautions, gaps))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# The ledger commands
# --------------------------------------------------------------------------------------

def _refused(exc: Any) -> int:
    _out("refused: %s (%s)" % (exc.code, exc))
    if exc.hits:
        counts: Dict[str, int] = {}
        for hit in exc.hits:
            counts[hit.rule_id] = counts.get(hit.rule_id, 0) + 1
        for rule in sorted(counts):
            _out("  %s  x%d  %s" % (rule, counts[rule], _describe_rule(rule)))
    return EXIT_BLOCK


def _log_line(line: Dict[str, Any]) -> None:
    _out("logged: %s" % line["action"])
    _out("record: %s" % line["record_id"])
    if line.get("rule_ids"):
        _out("rules: %s" % " ".join(line["rule_ids"]))
    if line.get("gaps"):
        _out("gaps: %s" % " ".join(line["gaps"]))
    _out("time: %s" % line["time"])


def cmd_adopt(args: argparse.Namespace, options: Options) -> int:
    _out("intake-scan: adopt")
    entry = il.adopt(options.root, args.id, args.to, quarantine_root=options.quarantine_root)
    _out("adopted: %s" % _show_path(entry["unit"]))
    _out("record: %s" % entry["record_id"])
    _out("verdict: %s" % entry["verdict"])
    _out("exceptions written: %d" % len(entry.get("exceptions", [])))
    return EXIT_PASS


def cmd_triage(args: argparse.Namespace, options: Options) -> int:
    _out("intake-scan: triage")
    _log_line(il.triage(options.root, args.id, accept=bool(args.accept), reason=args.reason,
                        quarantine_root=options.quarantine_root))
    return EXIT_PASS


def cmd_override(args: argparse.Namespace, options: Options) -> int:
    _out("intake-scan: override")
    _log_line(il.override(options.root, args.id, reason=args.reason, quarantine_root=options.quarantine_root))
    _out("holds: only while the scanned tree is unchanged")
    return EXIT_PASS


def cmd_except(args: argparse.Namespace, options: Options) -> int:
    _out("intake-scan: except")
    exc = il.add_exception(options.root, args.rule, args.path, reason=args.reason)
    _out("logged: except")
    _out("rule: %s  %s" % (exc["rule"], _describe_rule(exc["rule"])))
    _out("path: %s" % _show_path(exc["path"], exc["sha256"], _ledger_or_none(options.root)))
    _out("file sha256: %s" % exc["sha256"])
    _out("holds: only while the file is unchanged")
    return EXIT_PASS


def _listed(title: str, values: Sequence[str], show_all: bool) -> None:
    _out("%s: %d" % (title, len(values)))
    shown = list(values) if show_all else list(values)[:MAX_LISTED]
    for value in shown:
        _out("  %s" % value)
    if len(values) > len(shown):
        _out("  (+%d more; --all lists them)" % (len(values) - len(shown)))


def cmd_verify(args: argparse.Namespace, options: Options) -> int:
    _out("intake-scan: verify")
    result = il.verify(options.root)
    doc = _ledger_or_none(options.root)
    _out("files: %d" % result.files)
    _out("block-rule hits with no exception or override: %d" % len(result.hits))
    _print_hits(result.hits, len(result.hits) if args.all else MAX_LISTED, doc)
    _listed("units with no ledger entry", [_show_path(u) for u in result.missing_entries], args.all)
    _listed("ledger entries whose unit is gone", [_show_path(u) for u in result.orphan_entries], args.all)
    _listed("units entered at a block verdict", [_show_path(u) for u in result.block_entries], args.all)
    _listed("exceptions that no longer match their file",
            ["%s  %s" % (e["rule"], _show_path(e["path"], e["sha256"], doc)) for e in result.stale_exceptions],
            args.all)
    _listed("overrides that no longer match their unit",
            ["%s  %s" % (line["record_id"], _show_path(line.get("unit", ""))) for line in result.stale_overrides],
            args.all)
    _out("result: %s" % ("ok" if result.ok else "FAILED"))
    return EXIT_PASS if result.ok else EXIT_BLOCK


def cmd_status(args: argparse.Namespace, options: Options) -> int:
    _out("intake-scan: status")
    if args.purge:
        removed = il.purge_quarantine(options.quarantine_root)
        _out("purged from the quarantine (closed %d days or more ago): %d" % (il.RETENTION_DAYS, len(removed)))
    state = il.status(options.root, quarantine_root=options.quarantine_root)
    doc = _ledger_or_none(options.root)
    _out("ledger entries: %d" % state["entries"])
    _listed("unsigned cautions", [_show_path(u) for u in state["unsigned_cautions"]], args.all)
    _listed("units entered at a block verdict", [_show_path(u) for u in state["block_entries"]], args.all)
    _listed("exceptions in force",
            ["%s  %s" % (e["rule"], _show_path(e["path"], e["sha256"], doc)) for e in state["exceptions"]], args.all)
    _listed("exceptions that no longer match their file",
            ["%s  %s" % (e["rule"], _show_path(e["path"], e["sha256"], doc)) for e in state["stale_exceptions"]],
            args.all)
    _listed("overrides in force",
            ["%s  %s" % (line["record_id"], _show_path(line["unit"]) if line.get("unit") else "(in the quarantine)")
             for line in state["overrides"]], args.all)
    held = state["quarantine"]
    waiting = [row["id"] for row in held if row["state"] == "open" and row["has_tar"]]
    _listed("quarantine bundles waiting for a decision", waiting, args.all)
    _out("quarantine directories held in all: %d (closed: %d, past retention: %d)" % (
        len(held), sum(1 for row in held if row["state"] != "open"), sum(1 for row in held if row["expired"])))
    return EXIT_PASS


def cmd_toolchain(args: argparse.Namespace, options: Options) -> int:
    toolchain = adapters.sibling("toolchain")
    argv = [args.action]
    if options.tool_root:
        argv += ["--root", options.tool_root]
    for tool in args.tool or []:
        argv += ["--tool", tool]
    code = toolchain.main(argv)
    return {0: EXIT_PASS, 1: EXIT_BLOCK}.get(code, EXIT_ERROR)


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = _Parser(add_help=False)
    common.add_argument("--root", default=None, help="the repo root (default: found from the working directory)")
    common.add_argument("--quarantine-root", default=None,
                        help="default: $%s, else ~/.foundry/quarantine" % intake_fetch.QUARANTINE_ENV)
    common.add_argument("--tool-root", default=None, help="default: $FOUNDRY_INTAKE_TOOLS, else ~/.foundry/intake-tools")

    parser = _Parser(prog="intake.py", description="Intake security scanning: one verdict and one record per scan.")
    sub = parser.add_subparsers(dest="command", parser_class=_Parser)

    scan = sub.add_parser("scan", parents=[common], help="scan a git URL, a folder or a zip, or a unit of this repo")
    scan.add_argument("target", nargs="?", default=None)
    scan.add_argument("--kind", choices=ip.KINDS, default="skill")
    scan.add_argument("--ref", default=None, help="git only: a branch, a tag or a commit id")
    scan.add_argument("--local", default=None, metavar="UNIT", help="scan a unit of this repo and write its ledger entry")
    scan.add_argument("--offline", action="store_true",
                      help="there is no network: a git URL is not tried and the advisory lookup is a gap")
    scan.add_argument("--isolation", choices=("auto", "none"), default="auto",
                      help="none: act as a host with no sandbox. Third-party scanners are then NOT run at all")

    adopt = sub.add_parser("adopt", parents=[common], help="take a scanned bundle into the repo")
    adopt.add_argument("id")
    adopt.add_argument("--to", required=True, metavar="UNIT")

    triage = sub.add_parser("triage", parents=[common], help="record a person's decision on a record")
    triage.add_argument("id")
    decision = triage.add_mutually_exclusive_group(required=True)
    decision.add_argument("--accept", action="store_true")
    decision.add_argument("--reject", action="store_true")
    triage.add_argument("--reason", required=True)

    override = sub.add_parser("override", parents=[common], help="let one block record through, with a reason")
    override.add_argument("id")
    override.add_argument("--reason", required=True)

    exc = sub.add_parser("except", parents=[common], help="one exception for one rule on one file of this repo")
    exc.add_argument("rule")
    exc.add_argument("path")
    exc.add_argument("--reason", required=True)

    baseline = sub.add_parser("baseline", parents=[common], help="scan every unit of this repo from tracked content")
    baseline.add_argument("--offline", action="store_true")
    baseline.add_argument("--isolation", choices=("auto", "none"), default="auto")

    verify = sub.add_parser("verify", parents=[common], help="the block rules and the ledger over the whole tree")
    verify.add_argument("--all", action="store_true", help="list every row")

    status = sub.add_parser("status", parents=[common], help="what is in force and what the quarantine holds")
    status.add_argument("--all", action="store_true", help="list every row")
    status.add_argument("--purge", action="store_true", help="remove quarantine directories past retention")

    toolchain = sub.add_parser("toolchain", parents=[common], help="build or check the pinned scanners")
    toolchain.add_argument("action", choices=("install", "check"))
    toolchain.add_argument("--tool", action="append")
    return parser


_COMMANDS: Dict[str, Callable[[argparse.Namespace, Options], int]] = {
    "scan": cmd_scan, "adopt": cmd_adopt, "triage": cmd_triage, "override": cmd_override,
    "except": cmd_except, "baseline": cmd_baseline, "verify": cmd_verify, "status": cmd_status,
    "toolchain": cmd_toolchain,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = build_parser()
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:      # --help
            return EXIT_PASS if exc.code in (0, None) else EXIT_ERROR
        if args.command is None:
            raise _Usage("a command is required")
        options = Options(find_root(args.root), args.quarantine_root, args.tool_root,
                          bool(getattr(args, "offline", False)),
                          getattr(args, "isolation", "auto") == "none")
        return _COMMANDS[args.command](args, options)
    except _Usage as exc:
        _err("intake.py: usage: %s" % exc)
        _err("intake.py: run with --help for the commands")
        return EXIT_ERROR
    except il.LedgerRefused as exc:
        return _refused(exc)
    except il.LedgerError as exc:
        _out("error: %s" % exc)
        return EXIT_ERROR
    except ip.PolicyError as exc:
        _out("error: %s" % exc)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - never a traceback with target text in it
        _out("error: internal error (%s)" % type(exc).__name__)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
