"""adapters -- one module per scanner, one report shape for all of them (#350).

    skillspector     third-party, pinned, static-only; runs inside the sandbox
    bandit           third-party, pinned; runs inside the sandbox; Python files only
    secrets_catalog  in-house regex catalog of the secret-scanning skill; in-process
    deps             dep-currency-check's manifest parsers and advisory lookup; needs network

Every adapter returns a `Report`:

    findings         rule id (ours, through a table), class, opaque file id, line, scanner
    files_inspected  the opaque ids of the files the scanner actually looked at
    files_partial    the ids of files it looked at only in part
    gaps             everything that did not happen, each with a fixed name from GAPS
    evidence         numbers and fixed words about the run (a score, an exit status).
                     Evidence is stored. It is never an input to the verdict.
    triage           free text: scanner messages, snippets, dependency names. This is text
                     chosen by the target or by a third-party tool. It goes to the triage
                     sheet in the quarantine directory and NOWHERE ELSE.

`Report.to_dict()` leaves `triage` out, so the printable form of a report holds rule ids,
classes, opaque file ids, counts and our own fixed words only. A caller that wants the
free text has to ask for it by name.

Three rules hold for every adapter:

  * A scanner's rule id reaches a finding only through the adapter's table. An id that is
    not in the table becomes the gap `unknown-rule-id`; it is never passed through.
  * A tool that is missing, mismatched, crashed, timed out or cut short is a named gap. No
    adapter reports "no findings" for work that did not happen.
  * Nothing in the target switches a check off. Third-party scanners get a trusted config
    and their in-target controls disabled; the in-house ones have none to begin with.

No adapter imports or calls a model, and none starts target code.

Stdlib only. Importing this package has no side effects.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import stat
import sys
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

SCANNER_SKILLSPECTOR = "skillspector"
SCANNER_BANDIT = "bandit"
SCANNER_SECRETS = "secrets-catalog"
SCANNER_DEPS = "deps"
SCANNERS = (SCANNER_SKILLSPECTOR, SCANNER_BANDIT, SCANNER_SECRETS, SCANNER_DEPS)
THIRD_PARTY = (SCANNER_SKILLSPECTOR, SCANNER_BANDIT)

BLOCK = "block"
CAUTION = "caution"
INFO = "info"
CLASSES = (BLOCK, CAUTION, INFO)

ISOLATION_BWRAP = "bwrap"
ISOLATION_NONE = "none"
ISOLATION_IN_PROCESS = "in-process"

KIND_SKILL = "skill"
KIND_REPO = "repo"

ENTRY_FILE = "file"

# A finding about the file set as a whole carries this in place of a file id.
SET_FILE_ID = "-"

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))

# Named gaps. The name is what a record stores and the description is the only text a
# caller may print about it. Both are ours.
GAPS: Dict[str, str] = {
    "toolchain-missing": "the scanner is not installed; run `intake.py toolchain install`",
    "toolchain-mismatch": "the installed scanner does not match the pinned version, revision or lock file",
    "sandbox-unavailable": "bwrap is not available on this host; third-party scanners did not run",
    "sandbox-unusable": "bwrap is installed but could not create a sandbox; third-party scanners did not run",
    "sandbox-request-invalid": "the sandbox request named a missing or unsafe path; nothing was run",
    "scanner-timeout": "the scanner did not finish inside its time limit and was stopped",
    "scanner-start-failed": "the scanner could not be started inside the sandbox",
    "scanner-crashed": "the scanner stopped without a usable result",
    "scanner-report-unreadable": "the scanner's report is missing, too large or not in the expected form",
    "tool-version-mismatch": "the scanner reported a version other than the pinned one",
    "tool-revision-mismatch": "the scanner reported a source revision other than the pinned one",
    "unknown-rule-id": "the scanner reported a rule id that is not in our table; those results are not classified",
    "unknown-file": "the scanner reported a file that is not in the inventory",
    "partially-inspected": "the scanner inspected some files only in part",
    "python-file-not-analysed": "the scanner did not analyse every Python file it was given",
    "analyzer-incomplete": "one or more of the scanner's analyzers did not complete",
    "osv-subcheck-not-run": "the scanner's own advisory lookup cannot run without network; covered by the dependency check",
    "findings-suppressed": "the scanner dropped findings through a suppression list; no suppression list is ever supplied",
    "model-use-reported": "the scanner reported that a model was used; none is ever configured",
    "catalog-missing": "the in-house secrets catalog was not found in the repo or the home tree",
    "catalog-unusable": "the in-house secrets catalog could not be loaded or has an unexpected form",
    "file-too-large": "one or more files are over the size the scanner reads",
    "deps-helper-missing": "the dependency checker was not found in the repo or the home tree",
    "deps-helper-unusable": "the dependency checker could not be loaded or has an unexpected form",
    "deps-manifest-unparsed": "one or more dependency manifests are of a kind or form the dependency checker does not read",
    "deps-advisory-lookup-failed": "the advisory service could not be reached or did not answer for every dependency",
    "internal-error": "the adapter failed; its scanner is counted as not run",
}


class TargetFile(NamedTuple):
    file_id: str          # opaque: f001, f002, ...
    path: str             # as stored in the target, "/" separators. Never printed.
    mode: int
    size: int
    sha256: str
    entry: str = ENTRY_FILE
    stored: bool = True   # False for a link, a device, an oversize or an unsafe entry


class ScanTarget(NamedTuple):
    root: str                       # the private directory the stored files were extracted to
    files: Tuple[TargetFile, ...]
    kind: str = KIND_SKILL

    def stored(self) -> List[TargetFile]:
        return [f for f in self.files if f.stored and f.entry == ENTRY_FILE]

    def by_path(self) -> Dict[str, TargetFile]:
        return {f.path: f for f in self.stored()}

    def full_path(self, item: TargetFile) -> str:
        return os.path.join(self.root, *item.path.split("/"))


class Finding(NamedTuple):
    rule_id: str
    rule_class: str
    file_id: str
    line: int             # 1-based; 0 when the finding is about the file as a whole
    scanner: str

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule_id, "class": self.rule_class, "file": self.file_id,
                "line": self.line, "scanner": self.scanner}


class Gap(NamedTuple):
    gap: str                           # a key of GAPS
    scanner: str
    file_ids: Tuple[str, ...] = ()
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"gap": self.gap, "scanner": self.scanner, "files": list(self.file_ids),
                "count": self.count}


class Report(NamedTuple):
    scanner: str
    ran: bool
    isolation: str
    tool_version: Optional[str]
    findings: Tuple[Finding, ...] = ()
    files_inspected: Tuple[str, ...] = ()
    files_partial: Tuple[str, ...] = ()
    gaps: Tuple[Gap, ...] = ()
    evidence: Dict[str, Any] = {}
    triage: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self, include_triage: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "scanner": self.scanner, "ran": self.ran, "isolation": self.isolation,
            "tool_version": self.tool_version,
            "findings": [f.to_dict() for f in self.findings],
            "files_inspected": list(self.files_inspected),
            "files_partial": list(self.files_partial),
            "gaps": [g.to_dict() for g in self.gaps],
            "evidence": dict(self.evidence),
        }
        if include_triage:
            out["triage"] = [dict(t) for t in self.triage]
        return out

    def gap_names(self) -> List[str]:
        return [g.gap for g in self.gaps]


def describe_gap(name: str) -> str:
    """Our fixed description of a gap. Raises KeyError for a name that is not ours."""
    return GAPS[name]


# Our fixed words for a finding that came from a scanner. The id itself is from the
# adapter's table, so the pair is safe to print.
_FAMILY_DESCRIPTIONS = (
    ("SS-", "a SkillSpector static rule matched"),
    ("BD-", "a bandit test matched"),
    ("SEC-", "the in-house secrets catalog matched"),
)


def describe_rule(rule_id: str) -> str:
    """Our fixed description of an adapter rule id. Raises KeyError for any other id."""
    if rule_id in ("H10", "DEP-01"):
        return importlib.import_module(__name__ + ".deps").RULES[rule_id][1]
    for prefix, text in _FAMILY_DESCRIPTIONS:
        if rule_id.startswith(prefix) and len(rule_id) <= 16 and rule_id[len(prefix):].replace("-", "").isalnum():
            return text
    raise KeyError(rule_id)


def gap(name: str, scanner: str, file_ids: Iterable[str] = (), count: int = 0) -> Gap:
    if name not in GAPS:
        raise KeyError(name)
    ids = tuple(sorted(set(file_ids)))
    return Gap(name, scanner, ids, count or len(ids))


def not_run(scanner: str, isolation: str, gaps: Sequence[Gap],
            evidence: Optional[Dict[str, Any]] = None, tool_version: Optional[str] = None) -> Report:
    return Report(scanner, False, isolation, tool_version, (), (), (), tuple(gaps), dict(evidence or {}), ())


def failed(scanner: str, isolation: str = ISOLATION_NONE) -> Report:
    """What `run_all` records for an adapter that raised: not run, one named gap."""
    return not_run(scanner, isolation, [gap("internal-error", scanner)])


# --------------------------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------------------------

def target_from_inventory(root: str, inventory: Dict[str, Any], kind: str = KIND_SKILL) -> ScanTarget:
    """A scan target from an acquisition inventory and the directory it was extracted to."""
    files: List[TargetFile] = []
    for row in inventory.get("files", []):
        files.append(TargetFile(
            str(row["id"]), str(row["path"]), int(str(row.get("mode", "0")), 8),
            int(row.get("size") or 0), str(row.get("sha256") or ""),
            str(row.get("entry") or ENTRY_FILE), bool(row.get("stored"))))
    return ScanTarget(root, tuple(files), kind)


def target_from_dir(root: str, kind: str = KIND_SKILL) -> ScanTarget:
    """A scan target from a plain directory, read without following a link.

    For a unit of this repo (`scan --local`) and for tests. Ids are f001, f002, ... in
    sorted path order. A link or special file is listed as not stored.
    """
    import hashlib
    rels: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames) + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            rels.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    files: List[TargetFile] = []
    for index, rel in enumerate(sorted(rels), 1):
        full = os.path.join(root, *rel.split("/"))
        st = os.lstat(full)
        mode = stat.S_IMODE(st.st_mode)
        file_id = "f%03d" % index
        if not stat.S_ISREG(st.st_mode):
            entry = "symlink" if stat.S_ISLNK(st.st_mode) else "other"
            files.append(TargetFile(file_id, rel, mode, 0, "", entry, False))
            continue
        with open(full, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        files.append(TargetFile(file_id, rel, mode, st.st_size, digest, ENTRY_FILE, True))
    return ScanTarget(root, tuple(files), kind)


# --------------------------------------------------------------------------------------
# Loading our own sibling modules and helpers by path
# --------------------------------------------------------------------------------------

def sibling(name: str) -> Any:
    """A module of this skill's scripts directory (sandbox, toolchain), loaded once."""
    module = sys.modules.get(name)
    if module is not None:
        return module
    path = os.path.join(SCRIPTS_DIR, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def helper_roots(extra: Optional[Sequence[str]] = None) -> List[str]:
    """Where a sibling skill is looked for: the tree this file lives in, then the home tree.

    In the repo that is `skills/` first and `~/.claude/skills/` second. From an installed
    copy both are the home tree. `extra`, when given, REPLACES the list (tests).
    """
    if extra is not None:
        return [str(p) for p in extra]
    roots = [SKILLS_DIR]
    home = os.path.join(os.path.expanduser("~"), ".claude", "skills")
    if os.path.abspath(home) != os.path.abspath(SKILLS_DIR):
        roots.append(home)
    return roots


def is_text(data: bytes) -> bool:
    """A cheap text test: no NUL byte in the first block."""
    return b"\x00" not in data[:8192]


# --------------------------------------------------------------------------------------
# Shared steps of the two third-party adapters
# --------------------------------------------------------------------------------------

MAX_REPORT_BYTES = 64 * 1024 * 1024


class Preflight(NamedTuple):
    isolation: str
    bwrap: Optional[str]
    venv: Optional[str]            # the tool's venv, when it is installed and matches
    tool_version: Optional[str]    # read from the installed metadata, checked against the pin
    gaps: Tuple[Gap, ...]          # empty when the scanner may run


def preflight(scanner: str, tool: str, tool_root: Optional[str] = None,
              force_none: bool = False) -> Preflight:
    """Is the tool installed as pinned, and is there a sandbox to run it in?

    Both questions are answered without starting anything from the tool. Each "no" is a
    gap; with any gap the scanner must not be started.
    """
    toolchain = sibling("toolchain")
    sandbox = sibling("sandbox")
    gaps: List[Gap] = []
    venv = version = None
    try:
        state = toolchain.check(tool_root, [tool])[tool]
    except toolchain.ToolchainError:
        state = None
    if state is None or state.state in (toolchain.STATE_MISSING, toolchain.STATE_INCOMPLETE):
        gaps.append(gap("toolchain-missing", scanner))
    elif state.state != toolchain.STATE_OK:
        gaps.append(gap("toolchain-mismatch", scanner))
    else:
        venv, version = state.venv, state.version_found
    isolation, bwrap, sandbox_gap = sandbox.isolation(force_none)
    if sandbox_gap is not None:
        gaps.append(gap(sandbox_gap, scanner))
    return Preflight(isolation, bwrap, venv, version, tuple(gaps))


def read_json_report(path: str, max_bytes: int = MAX_REPORT_BYTES) -> Optional[Any]:
    """The scanner's JSON report, or None when it is missing, oversize or not JSON."""
    import json
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > max_bytes:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError, RecursionError):
        return None


def read_text_capped(path: Optional[str], limit: int = 4000) -> str:
    """The head of a scanner log, for the triage sheet only."""
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def target_relative(path: Any, prefix: str) -> Optional[str]:
    """`path` as the scanner reported it, made relative to the in-sandbox target root."""
    if not isinstance(path, str) or not path:
        return None
    text = path.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    root = prefix.rstrip("/") + "/"
    if text.startswith(root):
        text = text[len(root):]
    return text.lstrip("/") or None


# --------------------------------------------------------------------------------------
# Running them all
# --------------------------------------------------------------------------------------

def run_all(target: ScanTarget, *, tool_root: Optional[str] = None, force_none: bool = False,
            offline: bool = False, work_parent: Optional[str] = None,
            scanners: Sequence[str] = SCANNERS) -> List[Report]:
    """Run every adapter over `target` and return one report per scanner, in SCANNERS order.

    An adapter that raises is recorded as not run with the gap `internal-error`: one
    adapter failing never removes another's report, and never reads as clean.
    """
    reports: List[Report] = []
    for scanner in SCANNERS:
        if scanner not in scanners:
            continue
        try:
            if scanner == SCANNER_SKILLSPECTOR:
                module = importlib.import_module(__name__ + ".skillspector")
                report = module.run(target, tool_root=tool_root, force_none=force_none, work_parent=work_parent)
            elif scanner == SCANNER_BANDIT:
                module = importlib.import_module(__name__ + ".bandit")
                report = module.run(target, tool_root=tool_root, force_none=force_none, work_parent=work_parent)
            elif scanner == SCANNER_SECRETS:
                module = importlib.import_module(__name__ + ".secrets_catalog")
                report = module.run(target)
            else:
                module = importlib.import_module(__name__ + ".deps")
                report = module.run(target, offline=offline, work_parent=work_parent)
        except Exception:  # noqa: BLE001 - an adapter failure is a gap, never a crash of the scan
            report = failed(scanner, ISOLATION_IN_PROCESS if scanner not in THIRD_PARTY else ISOLATION_NONE)
        reports.append(report)
    return reports
