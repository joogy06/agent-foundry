#!/usr/bin/env python3
"""intake_ledger.py -- the intake ledger, the committed records and the override log (#350).

Three files under the repo root, all written atomically:

    skills/_meta/intake-ledger.json   one entry per unit: record id, content digest at
                                      entry time, verdict, unsigned-caution flag and the
                                      unit's per-hit exceptions
    intake/records/<id>.json          the scan record a ledger entry points at
    intake/overrides.jsonl            append-only: every override, triage and except call

WHAT A UNIT IS. A directory directly under `skills/` (except `skills/_meta/`), or a file
directly under `agents/`, `commands/` or `workflows/` (except `README.md`). Everything else
under those four roots (`skills/_meta/`, a loose file under `skills/`, a nested file under
`agents/`) is covered by the block rules but needs no entry; an exception for such a path
lives in the ledger's top-level `exceptions` list.

WHAT GETS PAST A BLOCK HIT. Only two things, and both are keyed to a digest:

    exception   one rule on one file, keyed to the file's SHA-256. It stops matching when
                the file changes and is renewed with `add_exception`. H7 and H8 take none,
                and neither does H11 on a markdown file (the line can be wrapped).
                A version-control path (`.git` and the like, or any file under a directory
                with the layout of a git repository) takes none and no override either: it
                is never adopted and never passes the hook.
    override    one block record, keyed to the tree digest it was scanned at. It stops
                matching when the tree changes. `adopt` turns it into per-hit exceptions on
                the adopted files, so the unit is then governed like any other.

There is no path exemption, no wholesale rule demotion and no bypass flag.

WHO CALLS THIS. `intake.py` (adopt, triage, override, except, baseline, verify, status),
arm 6 of the pre-commit hook and the `install.py` check. The hook and the installer load
this file by path, repo first and then the home tree; the rule set and the fetch module are
loaded lazily from this file's own directory, so importing this module does nothing.

WHAT A RECORD MUST CARRY for the functions here (the record schema itself belongs to the
policy module): `id`, `verdict` (pass, caution or block), `subject.kind`,
`subject.tree_digest`, and `findings` as a list of `{rule, class, ...}`. A record waiting
for adoption is `<quarantine>/<id>/record.json`, beside the tar it describes.

A malformed ledger or override log raises `LedgerMalformed`; a missing ledger raises
`LedgerMissing`. Neither is ever read as an empty ledger: callers fail closed. A request
the rules do not allow raises `LedgerRefused` with a stable `code`. Messages are fixed text
of ours and never carry a file name or content chosen by a scan target.

Stdlib only.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

SCHEMA = "intake-ledger.v1"
LEDGER_REL = "skills/_meta/intake-ledger.json"
RECORDS_REL = "intake/records"
OVERRIDES_REL = "intake/overrides.jsonl"

ENFORCED_ROOTS = ("skills", "agents", "commands", "workflows")
_FILE_UNIT_ROOTS = ("agents", "commands", "workflows")
_NO_UNIT_DIR = "_meta"
_NO_UNIT_FILE = "README.md"

VERDICTS = ("pass", "caution", "block")
ORIGINS = ("adopt", "local", "baseline")

# Every unit, whatever its root, is judged as a skill: H2 is then by presence.
RULE_KIND = "skill"
# Rules `add_exception` refuses: a hit is fixed, never excepted.
NO_EXCEPTION_RULES = ("H7", "H8")
# Refused on a markdown file only: a line the patterns never read may hold the grant itself,
# and a markdown line can always be wrapped. A script that cannot be re-wrapped takes one.
NO_MARKDOWN_EXCEPTION_RULES = ("H11",)

ACTION_OVERRIDE = "override"
ACTION_ACCEPT = "triage-accept"
ACTION_REJECT = "triage-reject"
ACTION_EXCEPT = "except"
ACTIONS = (ACTION_OVERRIDE, ACTION_ACCEPT, ACTION_REJECT, ACTION_EXCEPT)

# Record states (see record_state).
STATE_PASS = "pass"
STATE_SIGNED = "signed-caution"
STATE_UNSIGNED = "unsigned-caution"
STATE_OVERRIDDEN = "overridden-block"
STATE_BLOCK = "block"
STATE_REJECTED = "rejected"
ADOPTABLE = (STATE_PASS, STATE_SIGNED, STATE_OVERRIDDEN)

# File sources.
SOURCE_INDEX = "index"          # blobs in the git index: tracked and staged content
SOURCE_WORKTREE = "worktree"    # tracked plus untracked-and-not-ignored files, from disk
SOURCE_WALK = "walk"            # every file on disk; for a tree that is not a git checkout
SOURCE_AUTO = "auto"            # worktree in a git checkout, else walk

# Quarantine layout beside the tar and the inventory the fetch module writes.
QUARANTINE_ENV = "FOUNDRY_QUARANTINE_ROOT"
RECORD_NAME = "record.json"
TRIAGE_NAME = "triage.md"
CLOSED_NAME = "closed.json"
TAR_NAME = "source.tar"
RETENTION_DAYS = 90

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------

class LedgerError(Exception):
    """Base class. A caller that enforces (the hook, the installer) fails closed on it."""


class LedgerMissing(LedgerError):
    """The ledger file does not exist."""


class LedgerMalformed(LedgerError):
    """The ledger, a record or the override log is unreadable or breaks its schema."""


_REFUSALS = {
    "bad-id": "the record id is not a valid id",
    "bad-reason": "a written reason is required",
    "bad-path": "the path is not a relative path inside an enforced root",
    "bad-record": "the record does not carry the fields the ledger needs",
    "record-not-found": "no record with this id is in the quarantine or under intake/records",
    "bundle-invalid": "the quarantine bundle is missing, altered or already closed",
    "record-does-not-match": "the record was made for a different tree than the one present",
    "rejected": "the record was rejected at triage",
    "block-not-overridden": "the record is a block with no override for this tree",
    "caution-not-signed": "the record is a caution with no recorded sign-off for this tree",
    "not-a-block": "only a block record takes an override",
    "not-a-caution": "only a caution record is signed off",
    "destination-not-a-unit": "the destination is not a unit path",
    "destination-exists": "the destination already exists",
    "not-a-single-file": "a file unit takes a bundle of exactly one file",
    "nothing-to-adopt": "the bundle holds no file",
    "block-hit-in-content": "the content has a block-rule hit the record does not account for",
    "unknown-rule": "the rule id is not a block rule of the in-house rule set",
    "rule-takes-no-exception": "this rule takes no exception: the hit is fixed, not excepted",
    "file-not-found": "the path is not a regular file",
    "no-such-hit": "the rule has no hit on this file",
    "unit-not-found": "the unit does not exist or holds no file",
    "unexcepted-block-hit": "the unit has a block-rule hit with no matching exception or override",
    "unexcepted-block-finding": "the record holds a block finding with no exception, and the unit "
                                "has no override for this tree",
    "vcs-control-path": "the bundle holds a version-control directory (by its name or by its layout) or "
                        "pointer file, which is never adopted",
    "kind-not-skill": "a unit under skills, agents, commands or workflows takes a record scanned as kind skill",
}


class LedgerRefused(LedgerError):
    """A request the rules do not allow. `code` is stable; `hits` lists block hits, if any."""

    def __init__(self, code: str, hits: Sequence["Hit"] = ()) -> None:
        super().__init__(_REFUSALS[code])
        self.code = code
        self.hits = list(hits)


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------

class Item(NamedTuple):
    """One file of the enforced tree: its repo-relative path and what the rules read."""
    path: str
    mode: int
    data: bytes          # b"" for a non-regular entry or a file over the per-file cap
    entry: str
    size: int
    sha256: str          # "" for a non-regular entry


class Hit(NamedTuple):
    rule_id: str
    path: str            # repo-relative; "-" for a finding about the file set as a whole
    line: int
    sha256: str


def _sibling(name: str) -> Any:
    """A module of this file's own directory (the rule set, the fetch module), loaded once."""
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS_DIR, name + ".py"))
    if spec is None or spec.loader is None:
        raise LedgerError("helper module %s is missing" % name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _rules() -> Any:
    return _sibling("harness_rules")


def _fetch() -> Any:
    return _sibling("intake_fetch")


def now_iso(now: Optional[str] = None) -> str:
    if now is not None:
        if not _TIME.match(now):
            raise ValueError("time must look like 2026-01-31T12:00:00Z")
        return now
    return datetime.datetime.now(datetime.timezone.utc).strftime(_TIME_FORMAT)


def _parse_time(text: str) -> datetime.datetime:
    return datetime.datetime.strptime(text, _TIME_FORMAT).replace(tzinfo=datetime.timezone.utc)


def _norm(path: str) -> str:
    """A repo-relative path with forward slashes and no leading "./"."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p not in ("", ".")]
    return "/".join(parts)


def _safe_rel(path: str) -> bool:
    raw = str(path).replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return False
    return ".." not in raw.split("/") and not any(ord(c) < 32 for c in raw)


def _full(root: str, rel: str) -> str:
    return os.path.join(root, *rel.split("/"))


def _reason(reason: Any) -> str:
    text = " ".join(str(reason).split()) if isinstance(reason, str) else ""
    if not text:
        raise LedgerRefused("bad-reason")
    return text


def _check_id(record_id: Any) -> str:
    if not isinstance(record_id, str) or not _ID.match(record_id):
        raise LedgerRefused("bad-id")
    return record_id


def _atomic_write(path: str, data: bytes) -> None:
    """Write `data` to `path` through a temp file in the same directory and one rename."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dump(doc: Any) -> bytes:
    return (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def _read_json(path: str, what: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise LedgerMalformed("%s is unreadable (%s)" % (what, type(exc).__name__))


# --------------------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------------------

def is_enforced(path: str) -> bool:
    """True for a path under one of the four enforced roots."""
    parts = _norm(path).split("/")
    return len(parts) >= 2 and parts[0] in ENFORCED_ROOTS


def is_unit(unit: str) -> bool:
    """True when `unit` is spelled like a unit: `skills/<dir>` or `<root>/<file>`."""
    parts = _norm(unit).split("/")
    if len(parts) != 2 or not _safe_rel(unit):
        return False
    if parts[0] == "skills":
        return parts[1] != _NO_UNIT_DIR
    return parts[0] in _FILE_UNIT_ROOTS and parts[1] != _NO_UNIT_FILE


def unit_for_path(path: str) -> Optional[str]:
    """The unit a FILE path belongs to, or None when the path needs no ledger entry."""
    parts = _norm(path).split("/")
    if len(parts) >= 3 and parts[0] == "skills" and parts[1] != _NO_UNIT_DIR:
        return "skills/" + parts[1]
    if len(parts) == 2 and parts[0] in _FILE_UNIT_ROOTS and parts[1] != _NO_UNIT_FILE:
        return "/".join(parts)
    return None


# What a reader of our output (who may be an agent) is shown in place of a name.
_PLAIN_PATH = re.compile(r"^[A-Za-z0-9._/@+-]{1,200}$")
WITHHELD = "(name withheld)"


def show_path(doc: Optional[Dict[str, Any]], path: str, sha256: str = "") -> str:
    """How a path of the enforced tree is shown by `verify`, `status`, `except`, the commit
    hook and the install check.

    The file names inside a unit that was ADOPTED were chosen by its source, and plain
    characters are enough to write a sentence. So for a file of such a unit only the unit
    (named by the person who adopted it) is shown, with the file's digest. Any other path is
    shown when it is made of plain path characters, and withheld when it is not. A unit stays
    adopted when it is scanned again in place (see `is_adopted`).
    """
    path = _norm(path)
    digest = " sha256 " + sha256[:12] if sha256 else ""
    unit = unit_for_path(path)
    entry = None
    if isinstance(doc, dict) and unit is not None:
        entry = next((e for e in doc.get("entries", []) if isinstance(e, dict) and e.get("unit") == unit), None)
    if entry is not None and is_adopted(entry) and path != unit:
        return "%s/%s%s" % (unit if _PLAIN_PATH.match(unit) else WITHHELD, WITHHELD, digest)
    if _PLAIN_PATH.match(path):
        return path
    return WITHHELD + digest


def is_adopted(entry: Any) -> bool:
    """True for the entry of a unit that came in through `adopt`, however often it has been
    scanned in place since: `scan --local` rewrites `origin`, the `adopted` mark stays."""
    return isinstance(entry, dict) and (entry.get("adopted") is True or entry.get("origin") == "adopt")


def _is_dir_unit(unit: str) -> bool:
    return unit.startswith("skills/")


def _unit_relative(unit: str, path: str) -> str:
    """A file's path inside its unit: relative to a skill directory, the name of a file unit."""
    return path[len(unit) + 1:] if _is_dir_unit(unit) else path.split("/")[-1]


# --------------------------------------------------------------------------------------
# The ledger file
# --------------------------------------------------------------------------------------

def ledger_path(root: str) -> str:
    return _full(root, LEDGER_REL)


def exists(root: str) -> bool:
    return os.path.isfile(ledger_path(root))


def empty() -> Dict[str, Any]:
    return {"schema": SCHEMA, "entries": [], "exceptions": []}


def _check_exception(exc: Any, where: str) -> None:
    if not isinstance(exc, dict):
        raise LedgerMalformed("%s: an exception is not an object" % where)
    for key in ("rule", "path", "reason", "time"):
        if not isinstance(exc.get(key), str) or not exc[key]:
            raise LedgerMalformed("%s: an exception has no %s" % (where, key))
    if not isinstance(exc.get("sha256"), str) or not _HEX64.match(exc["sha256"]):
        raise LedgerMalformed("%s: an exception has no file digest" % where)
    if not _safe_rel(exc["path"]) or not is_enforced(exc["path"]):
        raise LedgerMalformed("%s: an exception path is outside the enforced roots" % where)


def validate(doc: Any) -> Dict[str, Any]:
    """Check a ledger document. Returns it; raises LedgerMalformed on any defect."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise LedgerMalformed("the ledger has an unknown schema")
    entries = doc.get("entries")
    loose = doc.get("exceptions")
    if not isinstance(entries, list) or not isinstance(loose, list):
        raise LedgerMalformed("the ledger has no entries or exceptions list")
    seen = set()
    for number, entry in enumerate(entries, 1):
        where = "entry %d" % number
        if not isinstance(entry, dict):
            raise LedgerMalformed("%s is not an object" % where)
        unit = entry.get("unit")
        if not isinstance(unit, str) or not is_unit(unit) or unit != _norm(unit):
            raise LedgerMalformed("%s names no unit" % where)
        if unit in seen:
            raise LedgerMalformed("%s repeats a unit" % where)
        seen.add(unit)
        if entry.get("kind") not in _rules().KINDS:
            raise LedgerMalformed("%s has an unknown kind" % where)
        if not isinstance(entry.get("record_id"), str) or not _ID.match(entry["record_id"]):
            raise LedgerMalformed("%s has no record id" % where)
        if not isinstance(entry.get("digest"), str) or not _HEX64.match(entry["digest"]):
            raise LedgerMalformed("%s has no content digest" % where)
        if entry.get("verdict") not in VERDICTS:
            raise LedgerMalformed("%s has an unknown verdict" % where)
        if not isinstance(entry.get("unsigned_caution"), bool):
            raise LedgerMalformed("%s has no unsigned-caution flag" % where)
        if entry.get("origin") not in ORIGINS:
            raise LedgerMalformed("%s has an unknown origin" % where)
        if "adopted" in entry and not isinstance(entry["adopted"], bool):
            raise LedgerMalformed("%s has an adopted mark that is not true or false" % where)
        if not isinstance(entry.get("time"), str) or not _TIME.match(entry["time"]):
            raise LedgerMalformed("%s has no time" % where)
        if not isinstance(entry.get("exceptions"), list):
            raise LedgerMalformed("%s has no exceptions list" % where)
        for exc in entry["exceptions"]:
            _check_exception(exc, where)
            if unit_for_path(exc["path"]) != unit:
                raise LedgerMalformed("%s holds an exception for a file outside the unit" % where)
    for exc in loose:
        _check_exception(exc, "top-level exceptions")
    return doc


def load(root: str) -> Dict[str, Any]:
    """Read and validate the ledger. LedgerMissing when absent, LedgerMalformed when bad."""
    path = ledger_path(root)
    if not os.path.isfile(path):
        raise LedgerMissing("the ledger file %s does not exist" % LEDGER_REL)
    return validate(_read_json(path, "the ledger"))


def save(root: str, doc: Dict[str, Any]) -> None:
    """Validate and write the ledger atomically, entries and exceptions in a stable order."""
    doc = dict(doc)
    doc["entries"] = sorted(doc.get("entries", []), key=lambda e: e.get("unit", ""))
    for entry in doc["entries"]:
        entry["exceptions"] = sorted(entry.get("exceptions", []), key=_exception_order)
    doc["exceptions"] = sorted(doc.get("exceptions", []), key=_exception_order)
    _atomic_write(ledger_path(root), _dump(validate(doc)))


def _exception_order(exc: Dict[str, Any]) -> Tuple[str, str]:
    return (str(exc.get("path", "")), str(exc.get("rule", "")))


def get_entry(doc: Dict[str, Any], unit: str) -> Optional[Dict[str, Any]]:
    unit = _norm(unit)
    for entry in doc["entries"]:
        if entry["unit"] == unit:
            return entry
    return None


def has_entry(doc: Dict[str, Any], unit: str) -> bool:
    return get_entry(doc, unit) is not None


def units_missing_entry(doc: Dict[str, Any], paths: Iterable[str]) -> List[str]:
    """The units among `paths` (file paths) that have no ledger entry, sorted."""
    missing = set()
    for path in paths:
        unit = unit_for_path(path)
        if unit is not None and not has_entry(doc, unit):
            missing.add(unit)
    return sorted(missing)


def iter_exceptions(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every exception in the ledger: each entry's, then the top-level list."""
    out: List[Dict[str, Any]] = []
    for entry in doc["entries"]:
        out.extend(entry["exceptions"])
    out.extend(doc["exceptions"])
    return out


def exception_matches(doc: Dict[str, Any], rule_id: str, path: str, sha256: str) -> bool:
    """True when the ledger holds an exception for this rule on this file AT THIS DIGEST.

    The digest is the file's current SHA-256, so the answer turns false as soon as the
    file changes. An empty digest (a link, an entry with no content) never matches.
    """
    if not sha256:
        return False
    path = _norm(path)
    for exc in iter_exceptions(doc):
        if exc["rule"] == rule_id and exc["path"] == path and exc["sha256"] == sha256:
            return True
    return False


def _put_exception(doc: Dict[str, Any], exc: Dict[str, Any]) -> None:
    """Add or renew an exception: inside its unit's entry when there is one, else top level."""
    key = (exc["rule"], exc["path"])
    entry = None
    unit = unit_for_path(exc["path"])
    if unit is not None:
        entry = get_entry(doc, unit)
    for holder in [e["exceptions"] for e in doc["entries"]] + [doc["exceptions"]]:
        holder[:] = [e for e in holder if (e["rule"], e["path"]) != key]
    (entry["exceptions"] if entry is not None else doc["exceptions"]).append(exc)


def add_entry(root: str, unit: str, *, kind: str, record_id: str, digest: str, verdict: str,
              unsigned_caution: bool, origin: str, now: Optional[str] = None,
              doc: Optional[Dict[str, Any]] = None, write: bool = True) -> Dict[str, Any]:
    """Add or replace the entry for `unit`. The unit's exceptions are kept, and any
    top-level exception for a file of the unit moves into the entry. An entry that was
    adopted, now or before, carries `adopted: true` from then on. Returns the ledger."""
    unit = _norm(unit)
    if not is_unit(unit):
        raise LedgerRefused("destination-not-a-unit")
    if doc is None:
        doc = load(root)
    old = get_entry(doc, unit)
    kept = list(old["exceptions"]) if old is not None else []
    kept.extend(e for e in doc["exceptions"] if unit_for_path(e["path"]) == unit)
    doc["exceptions"] = [e for e in doc["exceptions"] if unit_for_path(e["path"]) != unit]
    doc["entries"] = [e for e in doc["entries"] if e["unit"] != unit]
    entry = {
        "unit": unit, "kind": kind, "record_id": record_id, "digest": digest, "verdict": verdict,
        "unsigned_caution": bool(unsigned_caution), "origin": origin, "time": now_iso(now),
        "exceptions": kept,
    }
    if origin == "adopt" or is_adopted(old):
        entry["adopted"] = True
    doc["entries"].append(entry)
    validate(doc)
    if write:
        save(root, doc)
    return doc


# --------------------------------------------------------------------------------------
# The override log
# --------------------------------------------------------------------------------------

def overrides_path(root: str) -> str:
    return _full(root, OVERRIDES_REL)


def read_overrides(root: str) -> List[Dict[str, Any]]:
    """Every line of the override log, oldest first. A missing log is an empty one; a line
    that is not one of ours raises LedgerMalformed."""
    path = overrides_path(root)
    if not os.path.isfile(path):
        return []
    lines: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, ValueError) as exc:
        raise LedgerMalformed("the override log is unreadable (%s)" % type(exc).__name__)
    for number, text in enumerate(raw.split("\n"), 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except ValueError:
            raise LedgerMalformed("override log line %d is not JSON" % number)
        if (not isinstance(line, dict) or line.get("action") not in ACTIONS
                or not isinstance(line.get("record_id"), str)
                or not isinstance(line.get("tree_digest"), str)
                or not isinstance(line.get("rule_ids"), list)
                or not isinstance(line.get("reason"), str) or not line["reason"]
                or not isinstance(line.get("time"), str) or not _TIME.match(line["time"])):
            raise LedgerMalformed("override log line %d is malformed" % number)
        lines.append(line)
    return lines


def _append_override(root: str, line: Dict[str, Any]) -> Dict[str, Any]:
    """Append one line to the log with a single write on an append-mode descriptor."""
    path = overrides_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = (json.dumps(line, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return line


# --------------------------------------------------------------------------------------
# Records and the quarantine
# --------------------------------------------------------------------------------------

def resolve_quarantine_root(override: Optional[str] = None) -> str:
    """The argument, else $FOUNDRY_QUARANTINE_ROOT, else ~/.foundry/quarantine."""
    if override:
        return os.path.abspath(os.fspath(override))
    env = os.environ.get(QUARANTINE_ENV)
    if env:
        return os.path.abspath(env)
    return os.path.join(os.path.expanduser("~"), ".foundry", "quarantine")


def bundle_dir(record_id: str, quarantine_root: Optional[str] = None) -> str:
    return os.path.join(resolve_quarantine_root(quarantine_root), _check_id(record_id))


def record_path(root: str, record_id: str) -> str:
    return os.path.join(_full(root, RECORDS_REL), _check_id(record_id) + ".json")


def check_record(record: Any, record_id: Optional[str] = None) -> Dict[str, Any]:
    """The fields the ledger reads from a record. Raises LedgerRefused("bad-record")."""
    subject = record.get("subject") if isinstance(record, dict) else None
    ok = (isinstance(record, dict) and isinstance(record.get("id"), str) and _ID.match(record["id"])
          and record.get("verdict") in VERDICTS and isinstance(subject, dict)
          and subject.get("kind") in _rules().KINDS
          and isinstance(subject.get("tree_digest"), str) and _HEX64.match(subject["tree_digest"])
          and isinstance(record.get("findings", []), list)
          and isinstance(record.get("review", []), list))
    if not ok or (record_id is not None and record["id"] != record_id):
        raise LedgerRefused("bad-record")
    return record


def write_record(root: str, record: Dict[str, Any]) -> str:
    """Write a record to intake/records/<id>.json. Returns the path."""
    check_record(record)
    path = record_path(root, record["id"])
    _atomic_write(path, _dump(record))
    return path


def find_record(root: str, record_id: str, quarantine_root: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """(record, path). The quarantine copy is read first: it is the one still open."""
    _check_id(record_id)
    for path in (os.path.join(bundle_dir(record_id, quarantine_root), RECORD_NAME),
                 record_path(root, record_id)):
        if os.path.isfile(path):
            try:
                record = _read_json(path, "the record")
            except LedgerMalformed:
                raise LedgerRefused("bad-record")
            return check_record(record, record_id), path
    raise LedgerRefused("record-not-found")


def _block_rule_ids(record: Dict[str, Any]) -> List[str]:
    return sorted({str(f.get("rule")) for f in record.get("findings", [])
                   if isinstance(f, dict) and f.get("class") == "block" and f.get("rule")})


def _other_rule_ids(record: Dict[str, Any]) -> List[str]:
    return sorted({str(f.get("rule")) for f in record.get("findings", [])
                   if isinstance(f, dict) and f.get("class") != "block" and f.get("rule")})


def _gap_names(record: Dict[str, Any]) -> List[str]:
    gaps = record.get("gaps", [])
    names = set()
    for gap in gaps if isinstance(gaps, list) else []:
        name = gap.get("gap") if isinstance(gap, dict) else gap
        if isinstance(name, str) and name:
            names.add(name)
    return sorted(names)


def record_state(record: Dict[str, Any], overrides: Sequence[Dict[str, Any]],
                 tree_digest: Optional[str] = None) -> str:
    """Where a record stands, from its verdict and the override log.

    `tree_digest` is the digest of the tree as it is NOW (default: the one the record was
    made at). A sign-off or an override counts only when it was given for that digest, so
    both are void once the tree changes.
    """
    digest = record["subject"]["tree_digest"] if tree_digest is None else tree_digest
    mine = [line for line in overrides if line["record_id"] == record["id"]]
    if record.get("rejected") or any(line["action"] == ACTION_REJECT for line in mine):
        return STATE_REJECTED
    current = {line["action"] for line in mine if line["tree_digest"] == digest}
    if digest != record["subject"]["tree_digest"]:
        current = set()
    if record["verdict"] == "pass":
        return STATE_PASS
    if record["verdict"] == "caution":
        return STATE_SIGNED if ACTION_ACCEPT in current else STATE_UNSIGNED
    return STATE_OVERRIDDEN if ACTION_OVERRIDE in current else STATE_BLOCK


def _review(record: Dict[str, Any], path: str, action: str, reason: str, time: str) -> None:
    """Append one item to the record's review history and rewrite the record in place."""
    record.setdefault("review", []).append({"action": action, "reason": reason, "time": time})
    _atomic_write(path, _dump(record))


def close_bundle(record_id: str, state: str, *, quarantine_root: Optional[str] = None,
                 now: Optional[str] = None) -> bool:
    """Retention: delete the bundle's tar and mark the bundle closed. The human report
    beside it stays until `purge_quarantine` removes the directory. False when no bundle."""
    directory = bundle_dir(record_id, quarantine_root)
    if not os.path.isdir(directory):
        return False
    try:
        os.unlink(os.path.join(directory, TAR_NAME))
    except FileNotFoundError:
        pass
    _atomic_write(os.path.join(directory, CLOSED_NAME), _dump({"state": state, "time": now_iso(now)}))
    return True


def list_quarantine(quarantine_root: Optional[str] = None, now: Optional[str] = None) -> List[Dict[str, Any]]:
    """What the quarantine holds: one row per bundle with its state and expiry."""
    base = resolve_quarantine_root(quarantine_root)
    rows: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return rows
    moment = _parse_time(now_iso(now))
    for name in names:
        directory = os.path.join(base, name)
        if not _ID.match(name) or not os.path.isdir(directory) or os.path.islink(directory):
            continue
        row: Dict[str, Any] = {"id": name, "state": "open", "closed_at": None, "expired": False,
                               "has_tar": os.path.isfile(os.path.join(directory, TAR_NAME)),
                               "has_triage": os.path.isfile(os.path.join(directory, TRIAGE_NAME))}
        closed = os.path.join(directory, CLOSED_NAME)
        if os.path.isfile(closed):
            try:
                mark = _read_json(closed, "the closed marker")
                when = _parse_time(mark["time"])
                row["state"] = str(mark["state"])
                row["closed_at"] = mark["time"]
                row["expired"] = (moment - when).days >= RETENTION_DAYS
            except (LedgerMalformed, KeyError, TypeError, ValueError):
                row["state"] = "closed-unreadable"
        rows.append(row)
    return rows


def purge_quarantine(quarantine_root: Optional[str] = None, now: Optional[str] = None) -> List[str]:
    """Remove every bundle closed RETENTION_DAYS or more ago. Returns the ids removed."""
    base = resolve_quarantine_root(quarantine_root)
    removed = []
    for row in list_quarantine(quarantine_root, now):
        if row["expired"]:
            shutil.rmtree(os.path.join(base, row["id"]), ignore_errors=True)
            removed.append(row["id"])
    return removed


# --------------------------------------------------------------------------------------
# Reading the enforced tree
# --------------------------------------------------------------------------------------

def _git(root: str, args: Sequence[str], stdin: Optional[bytes] = None) -> bytes:
    try:
        proc = subprocess.run(["git", "-C", root, "-c", "core.quotepath=off"] + list(args),
                              input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise LedgerError("git could not be started (%s)" % type(exc).__name__)
    if proc.returncode != 0:
        raise LedgerError("git %s failed" % args[0])
    return proc.stdout


def _resolve_source(root: str, source: str) -> str:
    if source == SOURCE_AUTO:
        return SOURCE_WORKTREE if os.path.lexists(os.path.join(root, ".git")) else SOURCE_WALK
    if source not in (SOURCE_INDEX, SOURCE_WORKTREE, SOURCE_WALK):
        raise ValueError("unknown source %r" % (source,))
    return source


def _under(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def _disk_item(root: str, rel: str) -> Optional[Item]:
    hr = _rules()
    full = _full(root, rel)
    try:
        st = os.lstat(full)
    except OSError:
        return None          # listed by git but gone from disk: a staged deletion
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISLNK(st.st_mode):
        return Item(rel, mode, b"", hr.ENTRY_SYMLINK, 0, "")
    if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
        return Item(rel, mode, b"", hr.ENTRY_DEVICE, 0, "")
    if not stat.S_ISREG(st.st_mode):
        return Item(rel, mode, b"", hr.ENTRY_OTHER, 0, "")
    with open(full, "rb") as fh:
        data = fh.read()
    return _file_item(rel, mode, data)


def _file_item(rel: str, mode: int, data: bytes) -> Item:
    hr = _rules()
    digest = hashlib.sha256(data).hexdigest()
    size = len(data)
    if size > hr.MAX_FILE_BYTES:
        data = b""
    return Item(rel, mode, data, hr.ENTRY_FILE, size, digest)


def _index_items(root: str, prefixes: Sequence[str]) -> List[Item]:
    hr = _rules()
    listing = _git(root, ["ls-files", "-s", "-z", "--"] + list(prefixes))
    rows: List[Tuple[str, str, str]] = []
    for chunk in listing.split(b"\x00"):
        if not chunk:
            continue
        meta, _tab, raw = chunk.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or fields[2] != b"0":
            raise LedgerError("the git index holds an unmerged or unreadable entry")
        rows.append((raw.decode("utf-8", "surrogateescape"), fields[0].decode("ascii"),
                     fields[1].decode("ascii")))
    blobs = [oid for _path, mode, oid in rows if hr.entry_for_git_mode(mode) == hr.ENTRY_FILE]
    content: Dict[str, bytes] = {}
    if blobs:
        out = _git(root, ["cat-file", "--batch"], ("\n".join(blobs) + "\n").encode("ascii"))
        at = 0
        for oid in blobs:
            end = out.index(b"\n", at)
            header = out[at:end].split()
            if len(header) != 3 or header[1] != b"blob":
                raise LedgerError("a blob in the git index could not be read")
            size = int(header[2])
            content[oid] = out[end + 1:end + 1 + size]
            at = end + 1 + size + 1
    items: List[Item] = []
    for path, mode, oid in rows:
        entry = hr.entry_for_git_mode(mode)
        if entry == hr.ENTRY_FILE:
            items.append(_file_item(path, 0o755 if mode == "100755" else 0o644, content[oid]))
        else:
            items.append(Item(path, 0, b"", entry, 0, ""))
    return items


def _walk_paths(root: str, prefixes: Sequence[str]) -> List[str]:
    out: List[str] = []
    for prefix in prefixes:
        top = _full(root, prefix)
        if os.path.islink(top) or not os.path.isdir(top):
            if os.path.lexists(top):
                out.append(prefix)
            continue
        for current, dirs, files in os.walk(top, followlinks=False):
            rel_dir = os.path.relpath(current, root).replace(os.sep, "/")
            for name in list(dirs):
                if os.path.islink(os.path.join(current, name)):
                    dirs.remove(name)
                    out.append(rel_dir + "/" + name)
            for name in files:
                out.append(rel_dir + "/" + name)
    return out


def read_items(root: str, source: str = SOURCE_AUTO, prefixes: Sequence[str] = ENFORCED_ROOTS) -> List[Item]:
    """The files under `prefixes` (repo-relative; default: the four enforced roots), sorted
    by path.

        index      blobs in the git index: what is tracked and staged, never the disk
        worktree   tracked plus untracked-and-not-ignored files, read from disk
        walk       every file on disk (a tree that is not a git checkout)
        auto       worktree when `root` is a git checkout, else walk

    No link is followed: a link is one item with no content.
    """
    source = _resolve_source(root, source)
    prefixes = [_norm(p) for p in prefixes]
    if source == SOURCE_INDEX:
        items = _index_items(root, prefixes)
    else:
        if source == SOURCE_WORKTREE:
            listing = _git(root, ["ls-files", "-c", "-o", "--exclude-standard", "-z", "--"] + prefixes)
            paths = [p.decode("utf-8", "surrogateescape") for p in listing.split(b"\x00") if p]
        else:
            paths = _walk_paths(root, prefixes)
        found = (_disk_item(root, rel) for rel in sorted(set(paths)))
        items = [item for item in found if item is not None]
    return sorted((i for i in items if _under(i.path, prefixes)), key=lambda i: i.path)


def list_units(items: Iterable[Item]) -> List[str]:
    """The units that own at least one of `items`, sorted."""
    return sorted({u for u in (unit_for_path(i.path) for i in items) if u is not None})


def unit_items(root: str, unit: str, source: str = SOURCE_AUTO) -> List[Item]:
    """The files of one unit, with repo-relative paths."""
    unit = _norm(unit)
    if not is_unit(unit):
        raise LedgerRefused("destination-not-a-unit")
    return [i for i in read_items(root, source, [unit]) if unit_for_path(i.path) == unit]


def tree_digest(items: Iterable[Item], unit: Optional[str] = None) -> str:
    """One digest for a file set: entry kind, executable bit, content digest, size and path
    of every entry, in path order. With `unit`, paths are taken relative to the unit, which
    gives the same value the fetch module records for the same files fetched as a folder."""
    hr = _rules()
    rows = []
    for item in items:
        path = _unit_relative(unit, item.path) if unit is not None else item.path
        bit = "x" if (item.entry == hr.ENTRY_FILE and item.mode & 0o111) else "-"
        rows.append((path, "\x00".join((item.entry, bit, item.sha256, str(item.size), path))))
    digest = hashlib.sha256()
    for _path, line in sorted(rows):
        digest.update(line.encode("utf-8", "backslashreplace") + b"\n")
    return digest.hexdigest()


def unit_tree_digest(root: str, unit: str, source: str = SOURCE_AUTO) -> str:
    return tree_digest(unit_items(root, unit, source), _norm(unit))


def to_records(items: Sequence[Item], unit: Optional[str] = None) -> List[Any]:
    """Rule-set file records for `items`, ids f001.. in the given order. With `unit`, paths
    are relative to the unit: the shape a scan of that unit as a target expects."""
    hr = _rules()
    records = []
    for index, item in enumerate(items, 1):
        path = _unit_relative(unit, item.path) if unit is not None else item.path
        oversize = item.entry == hr.ENTRY_FILE and item.size > hr.MAX_FILE_BYTES
        records.append(hr.FileRecord(hr.make_file_id(index), path, item.mode, item.data, item.entry,
                                     item.size if oversize else None))
    return records


# --------------------------------------------------------------------------------------
# Block rules against the ledger
# --------------------------------------------------------------------------------------

def block_hits(items: Sequence[Item], context_paths: Iterable[str] = ()) -> List[Hit]:
    """Every block-rule hit (H1 to H9, H11) on `items`, excepted or not. `context_paths` are
    repo-relative paths of the same tree that are not among `items`: they count toward the
    repository-layout check (H7) and get no hit of their own."""
    hr = _rules()
    records = to_records(items)
    by_id = {record.file_id: item for record, item in zip(records, items)}
    hits = []
    for finding in hr.scan_blocks(records, RULE_KIND, context_paths):
        item = by_id.get(finding.file_id)
        hits.append(Hit(finding.rule_id, item.path if item is not None else hr.SET_FILE_ID,
                        finding.line, item.sha256 if item is not None else ""))
    return hits


def override_matches(overrides: Sequence[Dict[str, Any]], unit: str, digest: str) -> bool:
    """True when a unit scanned in place has an override given at exactly this tree digest."""
    if not unit or not digest:
        return False
    rejected = {line["record_id"] for line in overrides if line["action"] == ACTION_REJECT}
    return any(line["action"] == ACTION_OVERRIDE and line.get("unit") == unit
               and line["tree_digest"] == digest and line["record_id"] not in rejected
               for line in overrides)


def unexcepted_hits(doc: Dict[str, Any], items: Sequence[Item], *,
                    overrides: Sequence[Dict[str, Any]] = (),
                    unit_digest: Optional[Callable[[str], str]] = None,
                    context_paths: Iterable[str] = ()) -> List[Hit]:
    """The block-rule hits on `items` that nothing in the ledger lets through.

    A hit is let through by an exception for that rule on that file at its current digest,
    or, when `unit_digest` is given, by an override on the file's unit at the unit's current
    tree digest. `unit_digest(unit)` must digest the WHOLE unit, not just `items`. A hit on a
    version-control path (`.git` and the like, or a file under a directory with the layout
    of a git repository) is let through by neither.

    When `items` is part of a tree (the files one commit stages), `context_paths` are the
    other paths of that tree: a staged `HEAD` is judged beside the `config` already there.
    """
    hr = _rules()
    out = []
    covered: Dict[str, bool] = {}
    context = list(context_paths)
    layout = hr.repo_layout_dirs([item.path for item in items] + context)
    for hit in block_hits(items, context):
        if hit.rule_id == "H7" and (hr.vcs_control_path(hit.path) or hr.in_repo_layout(hit.path, layout)):
            out.append(hit)          # never excepted and never overridden, whatever the ledger says
            continue
        if exception_matches(doc, hit.rule_id, hit.path, hit.sha256):
            continue
        unit = unit_for_path(hit.path) if hit.path != _rules().SET_FILE_ID else None
        if unit is not None and unit_digest is not None and overrides:
            if unit not in covered:
                covered[unit] = override_matches(overrides, unit, unit_digest(unit))
            if covered[unit]:
                continue
        out.append(hit)
    return out


# --------------------------------------------------------------------------------------
# except, override, triage
# --------------------------------------------------------------------------------------

def add_exception(root: str, rule_id: str, path: str, *, reason: str, now: Optional[str] = None,
                  source: str = SOURCE_AUTO) -> Dict[str, Any]:
    """`except`: one exception for one rule on one file, keyed to the file's digest now.

    Refused for H7 and H8, for H11 on a markdown file, for a rule that does not hit the
    file, and without a reason.
    An exception already held for the same rule and file is replaced (a renewal). Appends
    one line to the override log. Returns the exception.
    """
    hr = _rules()
    text = _reason(reason)
    if rule_id not in hr.BLOCK_RULE_IDS:
        raise LedgerRefused("unknown-rule")
    if rule_id in NO_EXCEPTION_RULES:
        raise LedgerRefused("rule-takes-no-exception")
    rel = _norm(path)
    if not _safe_rel(path) or not is_enforced(rel):
        raise LedgerRefused("bad-path")
    if rule_id in NO_MARKDOWN_EXCEPTION_RULES and hr.is_markdown(rel):
        raise LedgerRefused("rule-takes-no-exception")
    doc = load(root)
    items = [i for i in read_items(root, source, [rel]) if i.path == rel and i.entry == hr.ENTRY_FILE]
    if not items:
        raise LedgerRefused("file-not-found")
    item = items[0]
    if not any(hit.rule_id == rule_id for hit in block_hits([item])):
        raise LedgerRefused("no-such-hit")
    time = now_iso(now)
    unit = unit_for_path(rel)
    entry = get_entry(doc, unit) if unit is not None else None
    exc = {"rule": rule_id, "path": rel, "sha256": item.sha256, "reason": text, "time": time,
           "origin": ACTION_EXCEPT, "record_id": entry["record_id"] if entry is not None else ""}
    _put_exception(doc, exc)
    save(root, doc)
    _append_override(root, {
        "action": ACTION_EXCEPT, "record_id": exc["record_id"], "tree_digest": "",
        "rule_ids": [rule_id], "path": rel, "file_sha256": item.sha256, "reason": text, "time": time,
    })
    return exc


def override(root: str, record_id: str, *, reason: str, quarantine_root: Optional[str] = None,
             now: Optional[str] = None) -> Dict[str, Any]:
    """`override`: let one block record through, with a written reason. It holds only while
    the tree digest in the record is the digest of the tree. Returns the log line."""
    text = _reason(reason)
    record, path = find_record(root, record_id, quarantine_root)
    lines = read_overrides(root)
    if record_state(record, lines) == STATE_REJECTED:
        raise LedgerRefused("rejected")
    if record["verdict"] != "block":
        raise LedgerRefused("not-a-block")
    time = now_iso(now)
    line = {"action": ACTION_OVERRIDE, "record_id": record_id,
            "tree_digest": record["subject"]["tree_digest"], "rule_ids": _block_rule_ids(record),
            "gaps": _gap_names(record), "reason": text, "time": time}
    unit = record["subject"].get("unit")
    if isinstance(unit, str) and is_unit(unit):
        line["unit"] = _norm(unit)
    _append_override(root, line)
    _review(record, path, ACTION_OVERRIDE, text, time)
    return line


def triage(root: str, record_id: str, *, accept: bool, reason: str,
           quarantine_root: Optional[str] = None, now: Optional[str] = None) -> Dict[str, Any]:
    """`triage`: the recorded human decision on a record.

    accept   signs off a caution record at its tree digest (adoption then goes ahead, and a
             ledger entry made from the record stops being listed as an unsigned caution).
    reject   marks the record block, for good: the bundle's tar is deleted and no override
             brings it back.

    Returns the log line.
    """
    text = _reason(reason)
    record, path = find_record(root, record_id, quarantine_root)
    lines = read_overrides(root)
    if record_state(record, lines) == STATE_REJECTED:
        raise LedgerRefused("rejected")
    if accept and record["verdict"] != "caution":
        raise LedgerRefused("not-a-caution")
    time = now_iso(now)
    action = ACTION_ACCEPT if accept else ACTION_REJECT
    rule_ids = _other_rule_ids(record) if accept else sorted(set(_block_rule_ids(record) + _other_rule_ids(record)))
    line = {"action": action, "record_id": record_id, "tree_digest": record["subject"]["tree_digest"],
            "rule_ids": rule_ids, "gaps": _gap_names(record), "reason": text, "time": time}
    _append_override(root, line)
    if not accept:
        record["verdict"] = "block"
        record["rejected"] = True
    _review(record, path, action, text, time)
    if exists(root):
        doc = load(root)
        changed = False
        for entry in doc["entries"]:
            if entry["record_id"] != record_id:
                continue
            if accept and entry["unsigned_caution"] and entry["digest"] == record["subject"]["tree_digest"]:
                entry["unsigned_caution"] = False
                changed = True
            if not accept and (entry["verdict"] != "block" or entry["unsigned_caution"]):
                entry["verdict"] = "block"
                entry["unsigned_caution"] = False
                changed = True
        if changed:
            save(root, doc)
    if not accept:
        close_bundle(record_id, STATE_REJECTED, quarantine_root=quarantine_root, now=time)
    return line


# --------------------------------------------------------------------------------------
# adopt
# --------------------------------------------------------------------------------------

def _override_reason(overrides: Sequence[Dict[str, Any]], record: Dict[str, Any]) -> str:
    digest = record["subject"]["tree_digest"]
    for line in reversed(list(overrides)):
        if (line["action"] == ACTION_OVERRIDE and line["record_id"] == record["id"]
                and line["tree_digest"] == digest):
            return line["reason"]
    return ""


def adopt(root: str, record_id: str, dest: str, *, quarantine_root: Optional[str] = None,
          now: Optional[str] = None) -> Dict[str, Any]:
    """`adopt`: take a scanned bundle into the repo as the unit `dest`.

    Refused unless the record is a pass, a signed caution or an overridden block, unless
    it was scanned as kind skill, and unless the bundle on disk is still the tree the record
    (and any sign-off or override) was made for: the tree digest is recomputed from the
    inventory rows and both it and the inventory digest are compared with the record.
    Refused, override or not, when a stored path is a version-control path or lies under a
    directory with the layout of a git repository (acquisition stores neither).

    Writes exactly the scanned bytes: the regular files stored in the quarantine tar,
    checked member by member against the inventory; nothing else of the target is written. Copies the record to intake/records/, adds the ledger entry, and,
    for an overridden block, writes one exception per block-rule hit on the adopted files
    with the override's reason. Then the tar is deleted. Returns the ledger entry.
    """
    hr = _rules()
    fetch = _fetch()
    directory = bundle_dir(record_id, quarantine_root)
    unit = _norm(dest)
    if not _safe_rel(dest) or not is_unit(unit):
        raise LedgerRefused("destination-not-a-unit")
    record_file = os.path.join(directory, RECORD_NAME)
    if not os.path.isfile(record_file):
        raise LedgerRefused("record-not-found")
    try:
        record = check_record(_read_json(record_file, "the record"), record_id)
    except LedgerMalformed:
        raise LedgerRefused("bad-record")
    if record["subject"]["kind"] != RULE_KIND:
        # Kind repo makes the skill scanner optional; every unit root is judged as a skill.
        raise LedgerRefused("kind-not-skill")
    doc = load(root)
    lines = read_overrides(root)
    if record_state(record, lines) == STATE_REJECTED:
        raise LedgerRefused("rejected")
    try:
        inventory = fetch.load_inventory(directory)     # also recomputes the tree digest
        entries = list(fetch.iter_bundle_entries(directory))
    except fetch.BundleError:
        raise LedgerRefused("bundle-invalid")
    if inventory.get("tree_digest") != record["subject"]["tree_digest"]:
        raise LedgerRefused("record-does-not-match")
    scanned = record.get("inventory_digest")
    if isinstance(scanned, str) and scanned and scanned != inventory.get("inventory_digest"):
        raise LedgerRefused("record-does-not-match")
    state = record_state(record, lines, inventory["tree_digest"])
    if state == STATE_UNSIGNED:
        raise LedgerRefused("caution-not-signed")
    if state not in ADOPTABLE:
        raise LedgerRefused("block-not-overridden")

    stored = [e for e in entries if e.entry == hr.ENTRY_FILE and e.size is None]
    if not stored:
        raise LedgerRefused("nothing-to-adopt")
    layout = hr.repo_layout_dirs([e.path for e in entries])
    if any(hr.vcs_control_path(e.path) or hr.in_repo_layout(e.path, layout) for e in stored):
        # Not something an override covers: git would honour the config the target shipped.
        raise LedgerRefused("vcs-control-path")
    is_dir = _is_dir_unit(unit)
    if not is_dir and len(stored) != 1:
        raise LedgerRefused("not-a-single-file")
    target = _full(root, unit)
    if os.path.lexists(target):
        raise LedgerRefused("destination-exists")
    items = []
    for entry in stored:
        if not _safe_rel(entry.path):
            raise LedgerRefused("bundle-invalid")
        rel = unit + "/" + entry.path if is_dir else unit
        items.append(_file_item(rel, 0o755 if entry.mode & 0o111 else 0o644, entry.data))

    # The rules run again on the bytes about to be written, under the paths they will have.
    hits = unexcepted_hits(doc, items)
    time = now_iso(now)
    if hits and state != STATE_OVERRIDDEN:
        raise LedgerRefused("block-hit-in-content", hits)
    reason = _override_reason(lines, record)
    for key in sorted({(h.rule_id, h.path, h.sha256) for h in hits if h.sha256}):
        _put_exception(doc, {"rule": key[0], "path": key[1], "sha256": key[2], "reason": reason,
                             "time": time, "origin": ACTION_OVERRIDE, "record_id": record_id})
    add_entry(root, unit, kind=record["subject"]["kind"], record_id=record_id,
              digest=tree_digest(items, unit), verdict=record["verdict"], unsigned_caution=False,
              origin="adopt", now=time, doc=doc, write=False)

    os.makedirs(os.path.dirname(target), exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".intake-adopt-", dir=root)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for entry, item in zip(stored, items):
            out = os.path.join(staging, "unit", *entry.path.split("/")) if is_dir else os.path.join(staging, "unit")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with os.fdopen(os.open(out, flags, 0o644), "wb") as fh:
                fh.write(entry.data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(out, item.mode)
        os.rename(os.path.join(staging, "unit"), target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    try:
        record.setdefault("review", []).append({"action": "adopt", "reason": unit, "time": time})
        write_record(root, record)
        save(root, doc)
    except BaseException:
        # Nothing half-adopted stays behind: without its entry the unit must not exist.
        if is_dir:
            shutil.rmtree(target, ignore_errors=True)
        else:
            try:
                os.unlink(target)
            except OSError:
                pass
        raise
    close_bundle(record_id, "adopted", quarantine_root=quarantine_root, now=time)
    entry_out = get_entry(doc, unit)
    assert entry_out is not None
    return entry_out


# --------------------------------------------------------------------------------------
# Units written here: scan --local and the baseline
# --------------------------------------------------------------------------------------

def add_local_entry(root: str, unit: str, record: Dict[str, Any], *, source: str = SOURCE_AUTO,
                    now: Optional[str] = None) -> Dict[str, Any]:
    """`scan --local`: the entry for a unit written in this repo, at ANY verdict, unless the
    unit has a block-rule hit with no matching exception or override, or the record holds a
    block finding of any scanner (H10 from the dependency check takes no exception) that is
    not excepted and the unit has no override at this digest. A block verdict that comes
    from a gap alone is entered, and `status` and `verify` list it.

    The record must have been made for the unit as it is now (`subject.tree_digest` equal
    to `unit_tree_digest`). A caution verdict is entered as an unsigned caution until it
    is signed with `triage`. The record is written to intake/records/. Returns the entry.
    """
    unit = _norm(unit)
    check_record(record)
    doc = load(root)
    items = unit_items(root, unit, source)
    if not items:
        raise LedgerRefused("unit-not-found")
    digest = tree_digest(items, unit)
    if record["subject"]["tree_digest"] != digest:
        raise LedgerRefused("record-does-not-match")
    lines = read_overrides(root)
    hits = unexcepted_hits(doc, items, overrides=lines, unit_digest=lambda _unit: digest)
    if hits:
        raise LedgerRefused("unexcepted-block-hit", hits)
    state = record_state(record, lines, digest)
    overridden = state == STATE_OVERRIDDEN or override_matches(lines, unit, digest)
    if not overridden and any(isinstance(f, dict) and f.get("class") == "block" and not f.get("excepted")
                              for f in record.get("findings", [])):
        raise LedgerRefused("unexcepted-block-finding")
    write_record(root, record)
    add_entry(root, unit, kind=record["subject"]["kind"], record_id=record["id"], digest=digest,
              verdict=record["verdict"], unsigned_caution=(state == STATE_UNSIGNED), origin="local",
              now=now, doc=doc)
    entry = get_entry(doc, unit)
    assert entry is not None
    return entry


def baseline(root: str, scan_unit: Callable[[str, List[Any], str], Dict[str, Any]], *,
             source: str = SOURCE_INDEX, now: Optional[str] = None) -> Dict[str, Any]:
    """`baseline`: one record and one ledger entry for every existing unit. Report-only:
    no verdict and no block hit stops an entry here; the hits are returned to be fixed or
    excepted one by one.

    `scan_unit(unit, records, tree_digest)` is the caller's full scan of one unit: it gets
    the unit's rule-set file records (paths relative to the unit) and returns the record.
    The default source is the git index, so files git does not track never appear.

    Returns {"units", "verdicts": {verdict: count}, "block_hits": {rule: count},
    "unexcepted": [Hit]} for the whole enforced tree.
    """
    doc = load(root) if exists(root) else empty()
    items = read_items(root, source)
    by_unit: Dict[str, List[Item]] = {}
    for item in items:
        unit = unit_for_path(item.path)
        if unit is not None:
            by_unit.setdefault(unit, []).append(item)
    lines = read_overrides(root)
    verdicts = {verdict: 0 for verdict in VERDICTS}
    time = now_iso(now)
    for unit in sorted(by_unit):
        digest = tree_digest(by_unit[unit], unit)
        record = check_record(scan_unit(unit, to_records(by_unit[unit], unit), digest))
        if record["subject"]["tree_digest"] != digest:
            raise LedgerRefused("record-does-not-match")
        write_record(root, record)
        verdicts[record["verdict"]] += 1
        add_entry(root, unit, kind=record["subject"]["kind"], record_id=record["id"], digest=digest,
                  verdict=record["verdict"],
                  unsigned_caution=(record_state(record, lines, digest) == STATE_UNSIGNED),
                  origin="baseline", now=time, doc=doc, write=False)
    save(root, doc)
    counts: Dict[str, int] = {}
    for hit in block_hits(items):
        counts[hit.rule_id] = counts.get(hit.rule_id, 0) + 1
    return {"units": sorted(by_unit), "verdicts": verdicts, "block_hits": counts,
            "unexcepted": unexcepted_hits(doc, items)}


# --------------------------------------------------------------------------------------
# verify and status
# --------------------------------------------------------------------------------------

class VerifyResult(NamedTuple):
    ok: bool                              # no unexcepted hit and no unit without an entry
    files: int
    hits: List[Hit]                       # block-rule hits nothing in the ledger lets through
    missing_entries: List[str]            # units on disk with no ledger entry
    orphan_entries: List[str]             # entries whose unit is gone
    stale_exceptions: List[Dict[str, Any]]   # the file changed or is gone: no longer matching
    stale_overrides: List[Dict[str, Any]]    # in-place overrides whose unit changed
    block_entries: List[str] = []         # units entered at a block verdict (listed, not a failure)


def _live_exceptions(doc: Dict[str, Any], digests: Dict[str, str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    live, stale = [], []
    for exc in iter_exceptions(doc):
        (live if digests.get(exc["path"]) == exc["sha256"] else stale).append(exc)
    return live, stale


def _unit_overrides(doc: Dict[str, Any], lines: Sequence[Dict[str, Any]],
                    digest_of: Callable[[str], str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """In-place overrides (those naming a unit), split into matching and void."""
    rejected = {line["record_id"] for line in lines if line["action"] == ACTION_REJECT}
    live, stale = [], []
    for line in lines:
        if line["action"] != ACTION_OVERRIDE or not line.get("unit") or line["record_id"] in rejected:
            continue
        (live if digest_of(line["unit"]) == line["tree_digest"] else stale).append(line)
    return live, stale


def _block_entries(doc: Dict[str, Any]) -> List[str]:
    return sorted(e["unit"] for e in doc["entries"] if e["verdict"] == "block")


def verify(root: str, *, source: str = SOURCE_AUTO) -> VerifyResult:
    """`verify`: what the hook and the install check do, over the whole enforced tree.

    Runs the block rules on every file, checks each hit against the exceptions and
    overrides at their CURRENT digests, and checks every unit has an entry. Raises
    LedgerMissing or LedgerMalformed rather than report a tree it cannot judge.
    """
    doc = load(root)
    lines = read_overrides(root)
    items = read_items(root, source)
    by_unit: Dict[str, List[Item]] = {}
    for item in items:
        unit = unit_for_path(item.path)
        if unit is not None:
            by_unit.setdefault(unit, []).append(item)

    def digest_of(unit: str) -> str:
        return tree_digest(by_unit[unit], unit) if unit in by_unit else ""

    hits = unexcepted_hits(doc, items, overrides=lines, unit_digest=digest_of)
    missing = [unit for unit in sorted(by_unit) if not has_entry(doc, unit)]
    orphans = sorted(e["unit"] for e in doc["entries"] if e["unit"] not in by_unit)
    _live, stale = _live_exceptions(doc, {i.path: i.sha256 for i in items})
    _matching, void = _unit_overrides(doc, lines, digest_of)
    return VerifyResult(not hits and not missing, len(items), hits, missing, orphans, stale, void,
                        _block_entries(doc))


def status(root: str, *, quarantine_root: Optional[str] = None, source: str = SOURCE_AUTO,
           now: Optional[str] = None) -> Dict[str, Any]:
    """`status`: what a person should know is in force.

        entries             number of ledger entries
        unsigned_cautions   units entered at a caution nobody has signed
        block_entries       units entered at a block verdict (a gap, an override, a rejection)
        exceptions          exceptions that match their file now
        stale_exceptions    exceptions whose file changed or is gone
        overrides           overrides in force: a block record still waiting in the
                            quarantine, or a unit overridden in place and unchanged since
        quarantine          what the quarantine holds (see list_quarantine)
    """
    doc = load(root)
    lines = read_overrides(root)
    digests: Dict[str, str] = {}
    for exc in iter_exceptions(doc):
        if exc["path"] not in digests:
            found = [i for i in read_items(root, source, [exc["path"]]) if i.path == exc["path"]]
            digests[exc["path"]] = found[0].sha256 if found else ""
    live, stale = _live_exceptions(doc, digests)
    unit_cache: Dict[str, str] = {}

    def digest_of(unit: str) -> str:
        if unit not in unit_cache:
            items = unit_items(root, unit, source) if is_unit(unit) else []
            unit_cache[unit] = tree_digest(items, unit) if items else ""
        return unit_cache[unit]

    active, _void = _unit_overrides(doc, lines, digest_of)
    held = list_quarantine(quarantine_root, now)
    open_ids = {row["id"] for row in held if row["state"] == "open" and row["has_tar"]}
    rejected = {line["record_id"] for line in lines if line["action"] == ACTION_REJECT}
    for line in lines:
        if (line["action"] == ACTION_OVERRIDE and not line.get("unit")
                and line["record_id"] in open_ids and line["record_id"] not in rejected):
            active.append(line)
    return {
        "entries": len(doc["entries"]),
        "unsigned_cautions": sorted(e["unit"] for e in doc["entries"] if e["unsigned_caution"]),
        "block_entries": _block_entries(doc),
        "exceptions": live,
        "stale_exceptions": stale,
        "overrides": sorted(active, key=lambda line: (line["time"], line["record_id"])),
        "quarantine": held,
    }
