"""secrets_catalog.py -- adapter for the in-house secrets catalog (#350).

The catalog is the `CHECKS` table of `skills/secret-scanning/scripts/secrets-scan.py`. It
is reused as it stands, not copied: this module loads that file by path (the tree this
skill lives in first, then the home tree) and applies its patterns in-process to every
text file of the target. It is our own code, so it needs no sandbox, and it is always
available on a host that has the library. When the file is not found the result is the
gap `catalog-missing`, never an empty finding list.

Differences from the pre-push scanner, all of them on purpose:

  * Every text file is read, whatever its suffix. The pre-push scanner reads a list of
    suffixes; an intake target chooses its own file names.
  * No path is exempt. The pre-push scanner skips its own detector documentation by path;
    a target could name a directory to match.
  * For the CRITICAL and HIGH checks the catalog's allowlist is NOT applied. The allowlist
    drops a line that also holds a word such as "example", and a target can add that word
    to any line. It still applies to the MEDIUM and LOW advisory checks, where it only
    removes noise.

Every hit is a finding through RULES: caution for the credential-shaped checks, info for
the advisory ones. The block-class secret rule is H9 in the harness rules, not here. The
matched text goes to the triage sheet with the match itself masked.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import (CAUTION, INFO, ISOLATION_IN_PROCESS, SCANNER_SECRETS, Finding, Gap, Report,
               ScanTarget, gap, helper_roots, is_text, not_run)

SCANNER = SCANNER_SECRETS
CATALOG_REL = ("secret-scanning", "scripts", "secrets-scan.py")
MODULE_NAME = "_intake_secrets_catalog"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_HITS_PER_FILE_AND_RULE = 20
MAX_TRIAGE_TEXT = 200

# Catalog check name -> (our rule id, class). A check that is not here (the catalog gained
# one) is not passed through: it becomes the gap `unknown-rule-id`.
RULES: Dict[str, Tuple[str, str]] = {
    "live API key shapes": ("SEC-01", CAUTION),
    "PEM private-key headers": ("SEC-02", CAUTION),
    "AWS credentials": ("SEC-03", CAUTION),
    "JWT shapes": ("SEC-04", CAUTION),
    "WooCommerce REST consumer key/secret": ("SEC-05", CAUTION),
    "PostgreSQL password exposure": ("SEC-06", CAUTION),
    "inline password/token assignments": ("SEC-07", CAUTION),
    "bearer tokens": ("SEC-08", CAUTION),
    "real-looking emails": ("SEC-09", INFO),
    "internal hostnames": ("SEC-10", INFO),
    "non-RFC1918 IPs": ("SEC-11", INFO),
}
# Severities whose allowlist a target must not be able to use.
STRICT_SEVERITIES = frozenset({"CRITICAL", "HIGH"})


def find_catalog(roots: Optional[Sequence[str]] = None) -> Optional[str]:
    """The catalog file: under the tree this skill lives in, else under the home tree."""
    for root in helper_roots(roots):
        candidate = os.path.join(root, *CATALOG_REL)
        if os.path.isfile(candidate):
            return candidate
    return None


def load_checks(path: str) -> Optional[List[Any]]:
    """The catalog's CHECKS, or None when the file does not have the expected form."""
    try:
        spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - an unloadable catalog is a gap
        return None
    checks = getattr(module, "CHECKS", None)
    if not isinstance(checks, (tuple, list)) or not checks:
        return None
    for check in checks:
        if not all(hasattr(check, name) for name in ("severity", "name", "pattern", "allowlist")):
            return None
    return list(checks)


def _mask(line: str, start: int, end: int) -> str:
    """The line with the matched span masked, for the triage sheet."""
    shown = line[start:start + 4]
    masked = line[:start] + shown + "[masked %d]" % max(0, end - start - len(shown)) + line[end:]
    return masked.strip()[:MAX_TRIAGE_TEXT]


def run(target: ScanTarget, *, catalog_path: Optional[str] = None,
        roots: Optional[Sequence[str]] = None,
        rules: Optional[Dict[str, Tuple[str, str]]] = None) -> Report:
    """Apply the catalog to every text file of `target`."""
    table = RULES if rules is None else rules
    path = catalog_path or find_catalog(roots)
    if path is None:
        return not_run(SCANNER, ISOLATION_IN_PROCESS, [gap("catalog-missing", SCANNER)])
    checks = load_checks(path)
    if checks is None:
        return not_run(SCANNER, ISOLATION_IN_PROCESS, [gap("catalog-unusable", SCANNER)])

    known = [(check, table[check.name]) for check in checks if check.name in table]
    unknown_checks = sorted(check.name for check in checks if check.name not in table)

    findings: List[Finding] = []
    triage: List[Dict[str, Any]] = []
    inspected: Set[str] = set()
    too_large: Set[str] = set()
    unreadable: Set[str] = set()
    capped = 0
    for item in target.stored():
        if item.size > MAX_FILE_BYTES:
            too_large.add(item.file_id)
            continue
        try:
            with open(target.full_path(item), "rb") as fh:
                data = fh.read(MAX_FILE_BYTES + 1)
        except OSError:
            unreadable.add(item.file_id)
            continue
        if not is_text(data):
            continue
        inspected.add(item.file_id)
        lines = data.decode("utf-8", errors="replace").splitlines()
        for check, (rule, rule_class) in known:
            strict = check.severity in STRICT_SEVERITIES
            hits = 0
            for number, line in enumerate(lines, 1):
                match = check.pattern.search(line)
                if match is None:
                    continue
                if not strict and any(a.search(line) for a in check.allowlist):
                    continue
                hits += 1
                if hits > MAX_HITS_PER_FILE_AND_RULE:
                    capped += 1
                    continue
                findings.append(Finding(rule, rule_class, item.file_id, number, SCANNER))
                triage.append({"kind": "finding", "rule": rule, "file": item.file_id, "line": number,
                               "text": _mask(line, match.start(), match.end())})

    gaps: List[Gap] = []
    if too_large:
        gaps.append(gap("file-too-large", SCANNER, too_large))
    if unreadable:
        gaps.append(gap("partially-inspected", SCANNER, unreadable))
    if unknown_checks:
        gaps.append(gap("unknown-rule-id", SCANNER, count=len(unknown_checks)))
    evidence = {"checks": len(known), "unknown_checks": len(unknown_checks), "hits_over_cap": capped}
    return Report(SCANNER, True, ISOLATION_IN_PROCESS, None, tuple(findings), tuple(sorted(inspected)),
                  tuple(sorted(too_large | unreadable)), tuple(gaps), evidence, tuple(triage))
