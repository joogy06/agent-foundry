"""deps.py -- adapter for the dependency check (#350).

Reuses the `dep-currency-check` skill, found under the tree this skill lives in and then
under the home tree. Two of its parts are used and the rest is deliberately left alone:

    used      manifests.detect_manifests   the manifest and lockfile parsers
              registry.Registry.query_cves_batch   the advisory lookup (api.osv.dev)
              cache.Cache                  pointed at a private temp directory

    NOT used  its command line, its community wrappers (they start other tools inside the
              project directory) and its deprecation helper (it asks a model). None of the
              three is imported here.

This adapter runs OUTSIDE the sandbox because the advisory lookup needs the network. To
keep that safe it never points the helper at the target itself: the manifest and lockfile
files are copied, by name, into a scratch directory of our own, and the helper reads that.
The helper lists files with git when it can, and a target may ship a version-control
directory whose configuration starts programs; in the scratch directory there is none.

Findings:

    H10      block     a dependency has a malicious-package advisory (an id starting MAL-)
    DEP-01   caution   a dependency has any other advisory

H10 is the one block rule that is not in the harness rules, because it needs the network.

"No answer" is never "no advisory". A lookup counts for a dependency only when the helper
stored an answer for it; with no network, an error from the service or a short reply, the
result is the gap `deps-advisory-lookup-failed`. A manifest of a kind the helper does not
read is the gap `deps-manifest-unparsed`.

Dependency names are chosen by the target. They go to the advisory service (that is the
check) and to the triage sheet, and nowhere else.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from . import (BLOCK, CAUTION, ISOLATION_IN_PROCESS, SCANNER_DEPS, Finding, Gap, Report,
               ScanTarget, TargetFile, gap, helper_roots, not_run)

SCANNER = SCANNER_DEPS
HELPER_DIR = "dep-currency-check"
HELPER_PACKAGE = "dep_currency_check"

RULE_MALICIOUS = "H10"
RULE_ADVISORY = "DEP-01"
# Rule id -> (class, our fixed description).
RULES: Dict[str, Tuple[str, str]] = {
    RULE_MALICIOUS: (BLOCK, "a dependency has a malicious-package advisory"),
    RULE_ADVISORY: (CAUTION, "a dependency has a known-vulnerability advisory"),
}
MALICIOUS_PREFIX = "MAL-"

MANIFEST_NAMES = frozenset({
    "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "package.json", "Cargo.toml",
    "go.mod", "Gemfile", "pom.xml", "build.gradle", "build.gradle.kts",
})
LOCK_NAMES = frozenset({"poetry.lock", "package-lock.json", "Cargo.lock", "yarn.lock", "pnpm-lock.yaml"})
_REQUIREMENTS = re.compile(r"^requirements[^/]*\.txt$")
# A hash-locked requirements file under another name (`<tool>.lock.txt`): the shape this
# library's own toolchain locks have. The helper reads it once it is rewritten as plain pins.
_HASH_LOCK = re.compile(r"^[^/]+\.lock\.txt$")
_LOCK_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)[ \t]*==[ \t]*([^\s;\\]+)")
_STAGED_LOCK_NAME = "requirements.txt"
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
BATCH = 400
MAX_TRIAGE_TEXT = 200


class Dep(NamedTuple):
    name: str             # chosen by the target: triage only
    ecosystem: str
    version: str
    file_id: str          # the manifest that declares it
    source: Any = None    # the helper's own dependency object, handed back to it unchanged

    def key(self) -> Tuple[str, str, str]:
        return (self.name, self.ecosystem, self.version)


# lookup(deps) -> (advisory ids by dependency key, the keys the service answered for)
Lookup = Callable[[List[Dep]], Tuple[Dict[Tuple[str, str, str], List[str]], Set[Tuple[str, str, str]]]]


def is_manifest(name: str) -> bool:
    return name in MANIFEST_NAMES or bool(_REQUIREMENTS.match(name)) or is_hash_lock(name)


def is_hash_lock(name: str) -> bool:
    return bool(_HASH_LOCK.match(name)) and not _REQUIREMENTS.match(name)


def plain_pins(text: str) -> Optional[str]:
    """A hash-locked requirements file as plain `name==version` lines, or None when a line
    of it is not a pin (a URL, a bare name, an include): such a file is not read as clean."""
    out: List[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not buffer and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        entry, buffer = (buffer + line).strip(), ""
        match = _LOCK_PIN.match(entry)
        if match is None:
            return None
        out.append("%s==%s" % (match.group(1), match.group(2)))
    if buffer.strip():
        return None
    return "\n".join(out) + "\n"


def find_helper(roots: Optional[Sequence[str]] = None) -> Optional[str]:
    """The directory that holds the helper package, or None when there is none."""
    for root in helper_roots(roots):
        candidate = os.path.join(root, HELPER_DIR)
        if os.path.isfile(os.path.join(candidate, HELPER_PACKAGE, "manifests.py")):
            return candidate
    return None


def load_helper(helper_dir: str) -> Optional[Tuple[Any, Any, Any]]:
    """(manifests, registry, cache) modules of the helper, or None when it will not load."""
    sys.path.insert(0, helper_dir)
    try:
        importlib.invalidate_caches()
        manifests = importlib.import_module(HELPER_PACKAGE + ".manifests")
        registry = importlib.import_module(HELPER_PACKAGE + ".registry")
        cache = importlib.import_module(HELPER_PACKAGE + ".cache")
    except Exception:  # noqa: BLE001 - an unloadable helper is a gap
        return None
    finally:
        try:
            sys.path.remove(helper_dir)
        except ValueError:
            pass
    if not all(hasattr(m, n) for m, n in ((manifests, "detect_manifests"), (registry, "Registry"),
                                          (cache, "Cache"))):
        return None
    return manifests, registry, cache


def stage_manifests(target: ScanTarget, scratch: str) -> Tuple[Dict[str, TargetFile], Set[str]]:
    """Copy the manifest and lockfile files into `scratch`, one numbered directory per
    target directory. Returns ({scratch path: target file}, ids of files too large to copy).

    The numbered directories keep two manifests of the same name apart and keep the
    target's own directory names (which the helper would skip or act on) out of the way.
    """
    staged: Dict[str, TargetFile] = {}
    too_large: Set[str] = set()
    numbers: Dict[str, str] = {}
    for item in target.stored():
        directory, _, name = item.path.rpartition("/")
        if not (is_manifest(name) or name in LOCK_NAMES):
            continue
        if item.size > MAX_MANIFEST_BYTES:
            too_large.add(item.file_id)
            continue
        pins = None
        if is_hash_lock(name):
            try:
                with open(target.full_path(item), "r", encoding="utf-8") as fh:
                    pins = plain_pins(fh.read())
            except (OSError, ValueError):
                pins = None
        # A lock file gets a directory of its own, where it is staged as plain pins under
        # the one name the helper reads. One that is not all pins is staged as it is, which
        # the helper does not read, so it comes back as an unparsed manifest.
        key = directory if pins is None else "%s\x00%s" % (directory, name)
        slot = numbers.setdefault(key, "d%04d" % (len(numbers) + 1))
        os.makedirs(os.path.join(scratch, slot), 0o700, exist_ok=True)
        destination = os.path.join(scratch, slot, name if pins is None else _STAGED_LOCK_NAME)
        try:
            if pins is None:
                shutil.copyfile(target.full_path(item), destination, follow_symlinks=False)
            else:
                with open(destination, "x", encoding="utf-8") as fh:
                    fh.write(pins)
        except OSError:
            too_large.add(item.file_id)
            continue
        staged[os.path.realpath(destination)] = item
    return staged, too_large


def osv_lookup(helper: Tuple[Any, Any, Any], work_dir: str) -> Lookup:
    """The real lookup: the helper's batch query, with an answer counted only when stored.

    The helper returns "no advisories" for a dependency whether the service said so or
    could not be reached. It does store every real answer in its cache, so a fresh private
    cache per call tells the two apart. One (name, ecosystem) per call, because the helper
    keys its results and its cache without the version.
    """
    _manifests, registry_mod, cache_mod = helper

    def lookup(deps: List[Dep]) -> Tuple[Dict[Tuple[str, str, str], List[str]], Set[Tuple[str, str, str]]]:
        advisories: Dict[Tuple[str, str, str], List[str]] = {}
        answered: Set[Tuple[str, str, str]] = set()
        rounds: List[List[Dep]] = []
        for dep in deps:
            for group in rounds:
                if len(group) < BATCH and all((d.name, d.ecosystem) != (dep.name, dep.ecosystem) for d in group):
                    group.append(dep)
                    break
            else:
                rounds.append([dep])
        for number, group in enumerate(rounds):
            cache = cache_mod.Cache(base=Path(work_dir) / ("cache-%04d" % number))
            registry = registry_mod.Registry(cache=cache)
            try:
                result = registry.query_cves_batch([d.source for d in group], no_cache=True)
            except Exception:  # noqa: BLE001 - a failed lookup is a gap for this group
                continue
            if getattr(registry, "host_failures", None):
                continue
            for dep in group:
                if cache.get("vulns", dep.ecosystem, dep.name) is None:
                    continue
                answered.add(dep.key())
                ids: List[str] = []
                for record in result.get((dep.name, dep.ecosystem), ()):
                    for value in (getattr(record, "id", None), getattr(record, "osv_id", None)):
                        if isinstance(value, str) and value and value not in ids:
                            ids.append(value)
                advisories[dep.key()] = ids
        return advisories, answered

    return lookup


def run(target: ScanTarget, *, offline: bool = False, helper_dir: Optional[str] = None,
        roots: Optional[Sequence[str]] = None, lookup: Optional[Lookup] = None,
        work_parent: Optional[str] = None) -> Report:
    """Check the dependencies the target's manifests declare against the advisory service.

    `offline` is the caller saying there is no network: the manifests are still parsed and
    the lookup is recorded as a gap without being tried.
    """
    helper_dir = helper_dir or find_helper(roots)
    if helper_dir is None:
        return not_run(SCANNER, ISOLATION_IN_PROCESS, [gap("deps-helper-missing", SCANNER)])
    helper = load_helper(helper_dir)
    if helper is None:
        return not_run(SCANNER, ISOLATION_IN_PROCESS, [gap("deps-helper-unusable", SCANNER)])

    version = getattr(sys.modules.get(HELPER_PACKAGE), "__version__", None)
    version = version if isinstance(version, str) and re.match(r"^[0-9][0-9A-Za-z.+-]{0,39}$", version) else None
    gaps: List[Gap] = []
    triage: List[Dict[str, Any]] = []
    work = tempfile.mkdtemp(prefix="intake-deps-", dir=work_parent)
    try:
        scratch = os.path.join(work, "manifests")
        os.makedirs(scratch, 0o700)
        staged, too_large = stage_manifests(target, scratch)
        if too_large:
            gaps.append(gap("file-too-large", SCANNER, too_large))
        evidence: Dict[str, Any] = {"manifests": 0, "dependencies": 0, "answered": 0,
                                    "advisories": 0, "malicious": 0}
        if not staged:
            return Report(SCANNER, True, ISOLATION_IN_PROCESS, version, (), (), tuple(sorted(too_large)),
                          tuple(gaps), evidence, ())

        try:
            parsed = helper[0].detect_manifests(Path(scratch))
        except Exception:  # noqa: BLE001
            return not_run(SCANNER, ISOLATION_IN_PROCESS, [gap("deps-helper-unusable", SCANNER)])
        inspected: Set[str] = set()
        deps: List[Dep] = []
        seen: Set[Tuple[str, str, str, str]] = set()
        for manifest in parsed:
            item = staged.get(os.path.realpath(str(manifest.path)))
            if item is None:
                continue
            inspected.add(item.file_id)
            lock = getattr(manifest, "lockfile_path", None)
            lock_item = staged.get(os.path.realpath(str(lock))) if lock else None
            if lock_item is not None:
                inspected.add(lock_item.file_id)
            for dependency in getattr(manifest, "deps", ()):
                dep = Dep(str(dependency.name), str(dependency.ecosystem),
                          str(dependency.declared_version), item.file_id, dependency)
                if dep.key() + (dep.file_id,) in seen:
                    continue
                seen.add(dep.key() + (dep.file_id,))
                deps.append(dep)
        unparsed = sorted(item.file_id for item in staged.values()
                          if item.file_id not in inspected and is_manifest(item.path.rsplit("/", 1)[-1]))
        if unparsed:
            gaps.append(gap("deps-manifest-unparsed", SCANNER, unparsed))
        evidence["manifests"] = len(parsed)
        evidence["dependencies"] = len(deps)

        advisories: Dict[Tuple[str, str, str], List[str]] = {}
        answered: Set[Tuple[str, str, str]] = set()
        if deps and not offline:
            unique: Dict[Tuple[str, str, str], Dep] = {}
            for dep in deps:
                unique.setdefault(dep.key(), dep)
            try:
                advisories, answered = (lookup or osv_lookup(helper, work))(list(unique.values()))
            except Exception:  # noqa: BLE001 - a failed lookup is a gap, never clean
                advisories, answered = {}, set()
        unanswered = sorted({d.file_id for d in deps if d.key() not in answered})
        if unanswered:
            gaps.append(gap("deps-advisory-lookup-failed", SCANNER, unanswered))
        evidence["answered"] = len({d.key() for d in deps if d.key() in answered})

        findings: List[Finding] = []
        found: Set[Tuple[str, str]] = set()
        for dep in deps:
            ids = advisories.get(dep.key(), []) if dep.key() in answered else []
            if not ids:
                continue
            malicious = [i for i in ids if i.upper().startswith(MALICIOUS_PREFIX)]
            evidence["advisories"] += len(ids)
            evidence["malicious"] += len(malicious)
            for rule, hit in ((RULE_MALICIOUS, bool(malicious)), (RULE_ADVISORY, len(malicious) < len(ids))):
                if hit and (rule, dep.file_id) not in found:
                    found.add((rule, dep.file_id))
                    findings.append(Finding(rule, RULES[rule][0], dep.file_id, 0, SCANNER))
            triage.append({"kind": "finding", "file": dep.file_id, "line": 0,
                           "rule": RULE_MALICIOUS if malicious else RULE_ADVISORY,
                           "text": ("%s %s (%s): %s" % (dep.name, dep.version, dep.ecosystem,
                                                         ", ".join(ids)))[:MAX_TRIAGE_TEXT]})
        partial = set(too_large) | set(unparsed)
        return Report(SCANNER, True, ISOLATION_IN_PROCESS, version, tuple(findings),
                      tuple(sorted(inspected - partial)), tuple(sorted(partial)), tuple(gaps),
                      evidence, tuple(triage))
    finally:
        shutil.rmtree(work, ignore_errors=True)
