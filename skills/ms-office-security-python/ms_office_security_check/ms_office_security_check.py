"""ms_office_security_check — Office-specific security validator.

Stdlib-only Python implementation. Mirrors dep-currency-check's CLI/exit-code
shape. All output is advisory-only; not a security gate. See:

  ~/.claude/skills/ms-office-security-python/SKILL.md          (caller contract)
  ~/.claude/skills/ms-office-security-python/ms_office_security_check/rules.yaml
  ~/.claude/skills/dep-currency-check/dep_currency_check/      (layout precedent)

Architecture:

  CLI -> orchestrator -> scanners (AST / regex / manifest / config) -> findings
                                                                       |
                                                                       v
                                                                   renderer
                                                                   (json|md|sarif)

The 17 v1 rules live in rules.yaml (loaded at startup). E002 is suppressed when
A001 fires on the same import site.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

from . import __version__, __schema_version__

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

# Severity ordering
SEVERITY_RANK = {"info": 0, "medium": 1, "high": 2, "critical": 3}

# File extensions we scan for AST
PY_EXTS = (".py",)
# File extensions we scan via regex
TEXT_EXTS = (".py", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".env",
             ".http", ".md", ".rst", ".txt")
# Default exclusion globs
DEFAULT_EXCLUDES = (
    "**/.venv/**", "**/venv/**", "**/.tox/**", "**/site-packages/**",
    "**/node_modules/**", "**/vendor/**", "**/third_party/**",
    "**/.git/**", "**/.mypy_cache/**", "**/.pytest_cache/**", "**/__pycache__/**",
    "**/build/**", "**/dist/**", "**/.eggs/**",
)
# Graph URL host pattern (for B001 filtering)
GRAPH_HOST_RE = re.compile(r"graph\.microsoft\.(com|us|de)|microsoftgraph\.chinacloudapi\.cn")
# Microsoft Graph scope literal pattern (for C001/C003)
GRAPH_SCOPE_RE = re.compile(
    r'\b[A-Z][a-zA-Z]+\.(?:Read|ReadWrite|ReadBasic|Send|Manage)(?:\.(?:All|Shared))?\b'
)
# Broad scope (.All / .ReadWrite.All)
BROAD_SCOPE_RE = re.compile(r'\b[A-Z][a-zA-Z]+\.(?:ReadWrite\.All|[A-Z][a-zA-Z]*\.All)\b')

INLINE_IGNORE_RE = re.compile(r'#\s*msosec:\s*ignore\s+(.+?)(?:\s*$)', re.IGNORECASE)
INLINE_IGNORE_FILE_RE = re.compile(r'#\s*msosec:\s*ignore\s+file\s*$', re.IGNORECASE)


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------

@dataclass
class Finding:
    rule_id: str
    severity: str
    category: str
    file: str
    line: int
    col: int = 0
    code_excerpt: str = ""
    message: str = ""
    fix_hint: str = ""
    references: list[str] = field(default_factory=list)
    confidence: str = "high"
    detection: str = "ast"
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Suppression:
    rule_id: str
    file: str
    line: int
    reason: str  # "inline-comment" | "config" | "file-comment"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    schema_version: str = __schema_version__
    validator_version: str = __version__
    generated_at: str = ""
    project_root: str = ""
    config_source: str = ""
    files_scanned: int = 0
    rules_loaded: int = 0
    rules_run: int = 0
    rules_skipped: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    suppressions: list[Suppression] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "validator_version": self.validator_version,
            "generated_at": self.generated_at,
            "project_root": self.project_root,
            "config_source": self.config_source,
            "files_scanned": self.files_scanned,
            "rules_loaded": self.rules_loaded,
            "rules_run": self.rules_run,
            "rules_skipped": self.rules_skipped,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "suppressions": [s.to_dict() for s in self.suppressions],
            "advisories": self.advisories,
        }


# ----------------------------------------------------------------------------
# Tiny YAML reader (stdlib-only) — enough to parse rules.yaml
# ----------------------------------------------------------------------------

def _yaml_load_minimal(text: str) -> Any:
    """Minimal YAML parser. Supports the subset we need for rules.yaml:
    - top-level scalars
    - a single top-level list of dicts (rules:)
    - each dict has scalar fields and one optional `references:` list-of-strings
    - in-line `# comment` is stripped (but not inside quoted strings)

    NOT a general YAML implementation. Indentation-aware: list items start at
    col >0 with `- `, and an item's sub-list (e.g. `references:`) is indented
    DEEPER than the `- rule_id` opener.
    """
    def _strip_comment(line: str) -> str:
        out, in_quote = [], None
        for ch in line:
            if in_quote:
                out.append(ch)
                if ch == in_quote:
                    in_quote = None
            elif ch in ('"', "'"):
                in_quote = ch
                out.append(ch)
            elif ch == "#":
                break
            else:
                out.append(ch)
        return "".join(out)

    def _coerce(val: str) -> Any:
        val = val.strip()
        if not val:
            return None
        if val[0] in ('"', "'") and val[-1] == val[0]:
            return val[1:-1]
        if val.lower() in ("true", "yes"):
            return True
        if val.lower() in ("false", "no"):
            return False
        if val.lower() in ("null", "~"):
            return None
        try:
            return int(val)
        except ValueError:
            pass
        try:
            return float(val)
        except ValueError:
            pass
        return val

    def _indent(line: str) -> int:
        i = 0
        for ch in line:
            if ch == " ":
                i += 1
            else:
                break
        return i

    root: dict[str, Any] = {}
    current_list_key: str | None = None
    current_list: list[Any] | None = None
    current_item: dict[str, Any] | None = None
    item_indent: int | None = None         # indent of `- ` opener
    field_list: list[str] | None = None    # active references-like list
    field_list_indent: int | None = None   # indent of items inside field_list

    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = _indent(line)
        stripped = line.strip()

        # Top-level (indent 0)
        if indent == 0:
            current_item = None
            item_indent = None
            field_list = None
            if stripped.endswith(":"):
                # Top-level list head
                current_list_key = stripped[:-1].strip()
                current_list = []
                root[current_list_key] = current_list
            elif ":" in stripped:
                k, _, v = stripped.partition(":")
                root[k.strip()] = _coerce(v)
                current_list_key = None
                current_list = None
            continue

        # Inside a top-level list
        if current_list is None:
            continue

        # New list-item opener (- key: value)
        if stripped.startswith("- ") and (item_indent is None or indent <= item_indent or indent == item_indent):
            item_indent = indent
            field_list = None
            after = stripped[2:]
            current_item = {}
            current_list.append(current_item)
            if ":" in after:
                k, _, v = after.partition(":")
                k = k.strip()
                if v.strip():
                    current_item[k] = _coerce(v)
                else:
                    # Field with list/dict coming on next deeper-indented lines
                    field_list = []
                    current_item[k] = field_list
                    field_list_indent = None
            continue

        # We're inside an item. Are we in an active references-style list?
        if field_list is not None and stripped.startswith("- "):
            if field_list_indent is None:
                field_list_indent = indent
            if indent == field_list_indent:
                value = stripped[2:].strip()
                if value and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                field_list.append(value)
                continue
            # Indent change — fall through to scalar handling
            field_list = None
            field_list_indent = None

        # Scalar field on current item
        if current_item is not None and ":" in stripped and not stripped.startswith("- "):
            k, _, v = stripped.partition(":")
            k = k.strip()
            if v.strip():
                current_item[k] = _coerce(v)
                field_list = None
            else:
                field_list = []
                current_item[k] = field_list
                field_list_indent = None
            continue

    return root


# ----------------------------------------------------------------------------
# Rules loader
# ----------------------------------------------------------------------------

@dataclass
class Rule:
    rule_id: str
    category: str
    severity: str
    confidence: str
    detection: str
    message: str
    fix_hint: str
    pattern_hint: str = ""
    references: list[str] = field(default_factory=list)
    suppressed_by: str | None = None


def load_rules(rules_yaml_path: Path) -> list[Rule]:
    text = rules_yaml_path.read_text(encoding="utf-8")
    data = _yaml_load_minimal(text)
    out: list[Rule] = []
    for entry in data.get("rules", []):
        out.append(Rule(
            rule_id=entry["rule_id"],
            category=entry["category"],
            severity=entry["severity"],
            confidence=entry.get("confidence", "high"),
            detection=entry["detection"],
            message=entry.get("message", ""),
            fix_hint=entry.get("fix_hint", ""),
            pattern_hint=entry.get("pattern_hint", ""),
            references=entry.get("references", []) or [],
            suppressed_by=entry.get("suppressed_by"),
        ))
    return out


# ----------------------------------------------------------------------------
# File walking
# ----------------------------------------------------------------------------

def iter_files(root: Path, extensions: Iterable[str], excludes: Iterable[str]) -> Iterable[Path]:
    """Yield files under `root` matching any of `extensions`, excluding paths
    matched by `excludes` globs.

    Glob semantics:
    - patterns like ``**/<name>/**`` exclude any directory whose basename matches
      ``<name>`` anywhere in the tree.
    - patterns like ``vendor/**`` exclude a directory at the root.
    - patterns are matched against the relative-from-root path.
    """
    root = root.resolve()
    excludes = tuple(excludes)

    # Pre-extract the "meaningful name" from each `**/<name>/**` pattern.
    name_patterns: list[str] = []
    path_patterns: list[str] = []
    for pat in excludes:
        # Strip leading `**/` and trailing `/**` to get the name in the middle.
        core = pat
        if core.startswith("**/"):
            core = core[3:]
        if core.endswith("/**"):
            core = core[:-3]
        if "/" not in core and core not in ("", "*", "**"):
            name_patterns.append(core)
        else:
            path_patterns.append(pat)

    def _excluded_dir(rel_path: str, dirname: str) -> bool:
        # Directory-name exclusion (e.g. `__pycache__`, `.venv`)
        for name in name_patterns:
            if fnmatch.fnmatch(dirname, name):
                return True
        # Path-pattern exclusion
        joined = f"{rel_path}/{dirname}" if rel_path else dirname
        for pat in path_patterns:
            if fnmatch.fnmatch(joined, pat) or fnmatch.fnmatch(joined + "/", pat):
                return True
        return False

    def _excluded_file(rel_path: str) -> bool:
        for pat in path_patterns:
            if fnmatch.fnmatch(rel_path, pat):
                return True
        return False

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        rel_dir = rel_dir.replace("\\", "/")
        # Prune excluded directories in-place
        dirnames[:] = [d for d in dirnames if not _excluded_dir(rel_dir, d)]
        for fn in filenames:
            if not fn.lower().endswith(tuple(extensions)):
                continue
            relstr = f"{rel_dir}/{fn}" if rel_dir else fn
            if _excluded_file(relstr):
                continue
            yield Path(dirpath) / fn


# ----------------------------------------------------------------------------
# Inline suppressions
# ----------------------------------------------------------------------------

def parse_inline_suppressions(text: str) -> tuple[bool, dict[int, set[str]]]:
    """Returns (file_wide_ignore_all, line_ignores). line_ignores maps line N to
    the set of rule IDs to ignore at that line.

    Inline `# msosec: ignore A009` on a line suppresses that rule for THAT line
    AND the next line (matching the dep-currency-check convention).
    Inline `# msosec: ignore file` at top of file suppresses all rules in the file.
    """
    line_ignores: dict[int, set[str]] = {}
    file_wide = False
    for idx, line in enumerate(text.splitlines(), start=1):
        if INLINE_IGNORE_FILE_RE.search(line):
            file_wide = True
            continue
        m = INLINE_IGNORE_RE.search(line)
        if m:
            ids = [s.strip() for s in m.group(1).split(",") if s.strip()]
            for rid in ids:
                # Ignore on the same line AND the next line (handle "comment on line above" convention)
                line_ignores.setdefault(idx, set()).add(rid)
                line_ignores.setdefault(idx + 1, set()).add(rid)
    return file_wide, line_ignores


# ----------------------------------------------------------------------------
# AST visitor — one visitor that fans out to rule handlers
# ----------------------------------------------------------------------------

class AstScanner(ast.NodeVisitor):
    def __init__(self, file: Path, source: str, rules_by_id: dict[str, Rule],
                 enabled: set[str], project_root: Path, scope_allowlist: set[str]):
        self.file = file
        self.source_lines = source.splitlines()
        self.rules = rules_by_id
        self.enabled = enabled
        self.project_root = project_root
        self.scope_allowlist = scope_allowlist
        self.findings: list[Finding] = []
        self.has_msal_import = False
        self.has_office_format_import = False
        self.uses_msal_extensions = False
        self.in_pcc = False  # within a PublicClientApplication instantiation

    def _excerpt(self, line: int) -> str:
        if 1 <= line <= len(self.source_lines):
            return self.source_lines[line - 1].strip()[:200]
        return ""

    def _emit(self, rule_id: str, line: int, col: int = 0, code: str | None = None,
              confidence: str | None = None) -> None:
        if rule_id not in self.enabled:
            return
        rule = self.rules[rule_id]
        self.findings.append(Finding(
            rule_id=rule.rule_id,
            severity=rule.severity,
            category=rule.category,
            file=str(self.file.relative_to(self.project_root)),
            line=line, col=col,
            code_excerpt=(code if code is not None else self._excerpt(line)),
            message=rule.message,
            fix_hint=rule.fix_hint,
            references=list(rule.references),
            confidence=confidence or rule.confidence,
            detection=rule.detection,
            advisory_only=True,
        ))

    # ------- import-level scanners ----------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name.split(".")[0]
            self._check_import(name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            name = node.module.split(".")[0]
            self._check_import(name, node.lineno)
        self.generic_visit(node)

    def _check_import(self, name: str, lineno: int) -> None:
        # MSOSEC-A001 / E002: adal
        if name == "adal":
            self._emit("MSOSEC-A001", lineno)
            # E002 is the deliberate-dup marker; we honour the suppressed_by relation.
        # MSOSEC-E004: requests_kerberos
        elif name == "requests_kerberos":
            self._emit("MSOSEC-E004", lineno)
        # MSOSEC-E005: pymsteams
        elif name == "pymsteams":
            self._emit("MSOSEC-E005", lineno)
        # MSOSEC-E001: exchangelib (unless near an on-prem marker comment)
        elif name == "exchangelib":
            if not self._has_onprem_marker(lineno):
                self._emit("MSOSEC-E001", lineno)
        elif name == "msal":
            self.has_msal_import = True
        elif name == "msal_extensions":
            self.uses_msal_extensions = True
        elif name in ("openpyxl", "docx", "pptx"):
            self.has_office_format_import = True

    def _has_onprem_marker(self, lineno: int) -> bool:
        """Look 2 lines before and on the same line for `on-prem` / `on prem` / `Exchange Server` markers."""
        for cand in range(max(1, lineno - 2), lineno + 1):
            if 1 <= cand <= len(self.source_lines):
                snippet = self.source_lines[cand - 1].lower()
                if "on-prem" in snippet or "on prem" in snippet or "exchange server" in snippet:
                    return True
        return False

    # ------- Call-level scanners ------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        # MSOSEC-A003 / A004: PublicClientApplication / ConfidentialClientApplication
        name = _call_name(node.func)
        if name in ("PublicClientApplication", "msal.PublicClientApplication"):
            self._check_pca(node)
        elif name in ("ConfidentialClientApplication", "msal.ConfidentialClientApplication"):
            self._check_cca(node)
        # MSOSEC-A009/A010/A013: jwt.decode
        elif name in ("jwt.decode", "decode", "PyJWT.decode"):
            self._check_jwt_decode(node)
        # MSOSEC-B001: requests.<verb>(graph URL, verify=False)
        elif _is_http_call(name):
            self._check_http_verify(node, name)
        # MSOSEC-E003: win32com.client.Dispatch("Outlook.Application")
        elif name in ("win32com.client.Dispatch", "Dispatch"):
            self._check_com_dispatch(node)
        # MSOSEC-OFFICE001: openpyxl.load_workbook
        elif name in ("openpyxl.load_workbook", "load_workbook"):
            self._check_openpyxl_load(node)
        # MSOSEC-OFFICE002: lxml.etree.parse / ElementTree.parse on Office paths
        elif name in ("lxml.etree.parse", "etree.parse", "xml.etree.ElementTree.parse",
                      "ElementTree.parse"):
            self._check_xml_parse(node)
        self.generic_visit(node)

    def _check_pca(self, node: ast.Call) -> None:
        has_broker = False
        for kw in node.keywords:
            if kw.arg == "enable_broker_on_windows":
                if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    has_broker = True
        if not has_broker:
            self._emit("MSOSEC-A003", node.lineno)

    def _check_cca(self, node: ast.Call) -> None:
        for kw in node.keywords:
            if kw.arg == "client_credential":
                # Literal string?
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    self._emit("MSOSEC-A004", kw.value.lineno or node.lineno,
                               code=f"client_credential={kw.value.value!r}")

    def _check_jwt_decode(self, node: ast.Call) -> None:
        has_algorithms = False
        has_issuer = False
        verify_disabled = False
        for kw in node.keywords:
            if kw.arg == "algorithms":
                has_algorithms = True
            elif kw.arg == "issuer":
                has_issuer = True
            elif kw.arg == "verify":
                if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    verify_disabled = True
            elif kw.arg == "options" and isinstance(kw.value, ast.Dict):
                for k, v in zip(kw.value.keys, kw.value.values):
                    if (isinstance(k, ast.Constant) and k.value == "verify_signature"
                            and isinstance(v, ast.Constant) and v.value is False):
                        verify_disabled = True
        if verify_disabled:
            self._emit("MSOSEC-A009", node.lineno)
        if not has_algorithms:
            self._emit("MSOSEC-A010", node.lineno)
        if not has_issuer:
            self._emit("MSOSEC-A013", node.lineno)

    def _check_http_verify(self, node: ast.Call, name: str) -> None:
        # First positional arg is usually the URL — check Constant
        url = None
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            url = node.args[0].value
        elif node.args and isinstance(node.args[0], ast.JoinedStr):
            # f-string — try to extract literal pieces
            pieces = [seg.value for seg in node.args[0].values
                      if isinstance(seg, ast.Constant) and isinstance(seg.value, str)]
            url = "".join(pieces)
        # Look for verify=False
        for kw in node.keywords:
            if kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                if url and GRAPH_HOST_RE.search(url):
                    self._emit("MSOSEC-B001", node.lineno,
                               code=f"{name}({url!r}, verify=False)")
                # If URL not detectable, still emit at low confidence on graph-adjacent contexts —
                # but to avoid duplicating bandit B501 we only fire when URL clearly points to Graph.
                return

    def _check_com_dispatch(self, node: ast.Call) -> None:
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "Outlook.Application":
            self._emit("MSOSEC-E003", node.lineno)

    def _check_openpyxl_load(self, node: ast.Call) -> None:
        # Look for keep_vba kwarg
        for kw in node.keywords:
            if kw.arg == "keep_vba":
                return  # explicit — accept developer's choice
        # Not specified — emit MSOSEC-OFFICE001 at low confidence.
        self._emit("MSOSEC-OFFICE001", node.lineno)

    def _check_xml_parse(self, node: ast.Call) -> None:
        # Only emit if this file also imports openpyxl/python-docx/python-pptx
        if self.has_office_format_import:
            # Skip if the import came from defusedxml (handled at import-time, not here)
            # For simplicity in v1, emit at medium confidence — the developer can suppress.
            self._emit("MSOSEC-OFFICE002", node.lineno)


def _call_name(node: ast.AST) -> str:
    """Reconstruct a dotted name from an AST Attribute / Name chain."""
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_http_call(name: str) -> bool:
    if not name:
        return False
    last = name.split(".")[-1]
    if last not in ("get", "post", "put", "delete", "patch", "head", "options", "request"):
        return False
    # Heuristic: only treat as HTTP if dotted with requests/httpx, or top-level call to a session.
    return ("requests" in name or "httpx" in name or "session" in name or name == last)


# ----------------------------------------------------------------------------
# Regex scanners (non-AST rules)
# ----------------------------------------------------------------------------

def scan_text_for_scopes(file: Path, source: str, rules_by_id: dict[str, Rule],
                         enabled: set[str], project_root: Path,
                         scope_allowlist: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    lines = source.splitlines()
    for idx, line in enumerate(lines, start=1):
        # MSOSEC-C001: literal scope NOT in allowlist
        for m in GRAPH_SCOPE_RE.finditer(line):
            scope = m.group(0)
            if scope in scope_allowlist:
                continue
            if "MSOSEC-C001" in enabled:
                rule = rules_by_id["MSOSEC-C001"]
                findings.append(Finding(
                    rule_id=rule.rule_id, severity=rule.severity, category=rule.category,
                    file=str(file.relative_to(project_root)), line=idx, col=m.start(),
                    code_excerpt=line.strip()[:200],
                    message=f"{rule.message} (literal: {scope!r})",
                    fix_hint=rule.fix_hint, references=list(rule.references),
                    confidence=rule.confidence, detection=rule.detection,
                ))
        # MSOSEC-C003: broad scope
        for m in BROAD_SCOPE_RE.finditer(line):
            scope = m.group(0)
            if scope in scope_allowlist:
                continue
            if "MSOSEC-C003" in enabled:
                rule = rules_by_id["MSOSEC-C003"]
                findings.append(Finding(
                    rule_id=rule.rule_id, severity=rule.severity, category=rule.category,
                    file=str(file.relative_to(project_root)), line=idx, col=m.start(),
                    code_excerpt=line.strip()[:200],
                    message=f"{rule.message} (literal: {scope!r})",
                    fix_hint=rule.fix_hint, references=list(rule.references),
                    confidence=rule.confidence, detection=rule.detection,
                ))
    return findings


# ----------------------------------------------------------------------------
# C002 + AST follow-up — .default near PublicClientApplication
# ----------------------------------------------------------------------------

def scan_ast_for_default_in_pca(file: Path, source: str, tree: ast.AST,
                                rules_by_id: dict[str, Rule], enabled: set[str],
                                project_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if "MSOSEC-C002" not in enabled:
        return findings
    # Walk the tree, find PublicClientApplication uses and look for ".default" string literals in the same function
    class V(ast.NodeVisitor):
        def __init__(self):
            self.has_pca = False
            self.default_lines: list[int] = []

        def visit_Call(self, node: ast.Call):
            name = _call_name(node.func)
            if name in ("PublicClientApplication", "msal.PublicClientApplication"):
                self.has_pca = True
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, str) and ".default" in child.value:
                    self.default_lines.append(child.lineno)
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant):
            if isinstance(node.value, str) and ".default" in node.value:
                self.default_lines.append(node.lineno)

    v = V()
    v.visit(tree)
    if v.has_pca and v.default_lines:
        rule = rules_by_id["MSOSEC-C002"]
        # Emit at the first occurrence
        line = min(v.default_lines)
        excerpt = source.splitlines()[line - 1].strip() if 1 <= line <= len(source.splitlines()) else ""
        findings.append(Finding(
            rule_id=rule.rule_id, severity=rule.severity, category=rule.category,
            file=str(file.relative_to(project_root)), line=line, col=0,
            code_excerpt=excerpt[:200],
            message=rule.message, fix_hint=rule.fix_hint,
            references=list(rule.references), confidence=rule.confidence, detection=rule.detection,
        ))
    return findings


# ----------------------------------------------------------------------------
# Manifest scanner (MSOSEC-A002)
# ----------------------------------------------------------------------------

def scan_manifests_for_broker(project_root: Path, rules_by_id: dict[str, Rule],
                              enabled: set[str], py_files_have_msal: bool) -> list[Finding]:
    findings: list[Finding] = []
    if "MSOSEC-A002" not in enabled:
        return findings
    if not py_files_have_msal:
        return findings  # only fire when project code actually imports msal
    # Look for msal extras in pyproject.toml or requirements*.txt
    candidates = list(project_root.glob("pyproject.toml")) + list(project_root.glob("requirements*.txt")) + \
                 list(project_root.glob("**/requirements*.txt"))
    found_msal_broker = False
    msal_seen = False
    for c in candidates:
        try:
            text = c.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "msal" in text.lower():
            msal_seen = True
        if re.search(r'msal\s*\[\s*broker\s*\]|msal-broker', text, re.IGNORECASE):
            found_msal_broker = True
            break
    if msal_seen and not found_msal_broker:
        rule = rules_by_id["MSOSEC-A002"]
        findings.append(Finding(
            rule_id=rule.rule_id, severity=rule.severity, category=rule.category,
            file="(project manifest)", line=0, col=0, code_excerpt="",
            message=rule.message, fix_hint=rule.fix_hint,
            references=list(rule.references), confidence=rule.confidence, detection=rule.detection,
        ))
    return findings


# ----------------------------------------------------------------------------
# Config / project allowlist parsing
# ----------------------------------------------------------------------------

def load_project_config(project_root: Path, explicit: Path | None) -> tuple[dict[str, Any], str]:
    """Return (config_dict, source_label). Supports ms-office-security.yaml at root
    OR a [tool.ms-office-security] table in pyproject.toml.
    """
    if explicit:
        if explicit.suffix in (".yaml", ".yml"):
            return _yaml_load_minimal(explicit.read_text(encoding="utf-8")), str(explicit)
        if explicit.suffix == ".toml":
            return _toml_load(explicit), str(explicit)
    yaml_path = project_root / "ms-office-security.yaml"
    if yaml_path.exists():
        return _yaml_load_minimal(yaml_path.read_text(encoding="utf-8")), str(yaml_path)
    toml_path = project_root / "pyproject.toml"
    if toml_path.exists():
        data = _toml_load(toml_path)
        # nested at [tool.ms-office-security]
        section = data.get("tool", {}).get("ms-office-security", {}) if isinstance(data.get("tool"), dict) else {}
        return section, f"{toml_path}#[tool.ms-office-security]"
    return {}, "(no config file)"


def _toml_load(path: Path) -> dict[str, Any]:
    """Minimal TOML reader — uses tomllib if available (Py 3.11+), else returns empty."""
    try:
        import tomllib  # type: ignore
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ----------------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------------

def scan_project(project_root: Path, rules: list[Rule],
                 selected_rules: set[str] | None,
                 ignored_rules: set[str],
                 changed_files: list[str] | None,
                 scope_allowlist: set[str],
                 excludes: list[str]) -> Report:
    rules_by_id = {r.rule_id: r for r in rules}
    if selected_rules:
        enabled = set(selected_rules)
    else:
        enabled = {r.rule_id for r in rules}
    enabled -= ignored_rules

    report = Report()
    report.project_root = str(project_root.resolve())
    report.generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    report.rules_loaded = len(rules)
    report.rules_run = len(enabled)
    report.rules_skipped = sorted(ignored_rules)

    # File walking
    all_excludes = list(DEFAULT_EXCLUDES) + list(excludes)
    if changed_files:
        target_files = [project_root / f for f in changed_files
                        if (project_root / f).exists()]
    else:
        target_files = list(iter_files(project_root, PY_EXTS, all_excludes))
    report.files_scanned = len(target_files)

    py_files_have_msal = False

    for f in target_files:
        try:
            source = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        file_wide, line_ignores = parse_inline_suppressions(source)
        if file_wide:
            for rid in enabled:
                report.suppressions.append(Suppression(
                    rule_id=rid, file=str(f.relative_to(project_root)),
                    line=0, reason="file-comment"))
            continue

        # Parse AST (skip files that don't parse — emit no findings to avoid noise)
        try:
            tree = ast.parse(source, filename=str(f))
        except SyntaxError:
            continue

        scanner = AstScanner(f, source, rules_by_id, enabled, project_root, scope_allowlist)
        scanner.visit(tree)
        if scanner.has_msal_import:
            py_files_have_msal = True

        # Apply inline suppressions
        for finding in scanner.findings:
            if finding.line in line_ignores and finding.rule_id in line_ignores[finding.line]:
                report.suppressions.append(Suppression(
                    rule_id=finding.rule_id, file=finding.file, line=finding.line,
                    reason="inline-comment"))
                continue
            report.findings.append(finding)

        # C002 .default-near-PCA scan
        for finding in scan_ast_for_default_in_pca(f, source, tree, rules_by_id, enabled, project_root):
            if finding.line in line_ignores and finding.rule_id in line_ignores[finding.line]:
                report.suppressions.append(Suppression(
                    rule_id=finding.rule_id, file=finding.file, line=finding.line,
                    reason="inline-comment"))
                continue
            report.findings.append(finding)

        # Regex scope scan
        for finding in scan_text_for_scopes(f, source, rules_by_id, enabled, project_root, scope_allowlist):
            if finding.line in line_ignores and finding.rule_id in line_ignores[finding.line]:
                report.suppressions.append(Suppression(
                    rule_id=finding.rule_id, file=finding.file, line=finding.line,
                    reason="inline-comment"))
                continue
            report.findings.append(finding)

    # Manifest scan (one-shot, not per-file)
    for finding in scan_manifests_for_broker(project_root, rules_by_id, enabled, py_files_have_msal):
        report.findings.append(finding)

    # Dedup A001 -> suppress E002 if both fire at the same (file, line)
    seen_a001 = {(f.file, f.line) for f in report.findings if f.rule_id == "MSOSEC-A001"}
    report.findings = [f for f in report.findings
                       if not (f.rule_id == "MSOSEC-E002" and (f.file, f.line) in seen_a001)]

    # Summary
    summary = {"critical": 0, "high": 0, "medium": 0, "info": 0, "suppressed": len(report.suppressions)}
    for fnd in report.findings:
        summary[fnd.severity] = summary.get(fnd.severity, 0) + 1
    report.summary = summary

    return report


# ----------------------------------------------------------------------------
# Renderers
# ----------------------------------------------------------------------------

def render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=False)


def render_markdown(report: Report, no_color: bool = False) -> str:
    lines: list[str] = []
    lines.append("# ms-office-security-check report")
    lines.append("")
    lines.append("**Advisory only — not a security gate.** Findings inform reviewer judgement. "
                 "Generic security findings belong to `bandit` / `semgrep` / `gitleaks` / `pip-audit` / `dep-currency-check`.")
    lines.append("")
    lines.append(f"- Generated: {report.generated_at}")
    lines.append(f"- Project root: `{report.project_root}`")
    lines.append(f"- Config source: {report.config_source}")
    lines.append(f"- Files scanned: {report.files_scanned}")
    lines.append(f"- Rules loaded: {report.rules_loaded}, run: {report.rules_run}")
    lines.append(f"- Summary: critical={report.summary.get('critical', 0)}, "
                 f"high={report.summary.get('high', 0)}, "
                 f"medium={report.summary.get('medium', 0)}, "
                 f"info={report.summary.get('info', 0)}, "
                 f"suppressed={report.summary.get('suppressed', 0)}")
    lines.append("")
    if not report.findings:
        lines.append("**No findings at the requested severity threshold.**")
        return "\n".join(lines)
    # Group by file
    by_file: dict[str, list[Finding]] = {}
    for f in report.findings:
        by_file.setdefault(f.file, []).append(f)
    for filepath, fs in sorted(by_file.items()):
        lines.append(f"## `{filepath}`")
        for f in sorted(fs, key=lambda x: (-SEVERITY_RANK.get(x.severity, 0), x.line)):
            lines.append(f"- **{f.severity.upper()} `{f.rule_id}`** (line {f.line}, confidence={f.confidence})")
            lines.append(f"  - {f.message}")
            if f.code_excerpt:
                lines.append(f"  - Code: `{f.code_excerpt}`")
            if f.fix_hint:
                lines.append(f"  - Fix: {f.fix_hint}")
            for ref in f.references:
                lines.append(f"  - Ref: {ref}")
        lines.append("")
    return "\n".join(lines)


def render_sarif(report: Report) -> str:
    """SARIF 2.1.0 emission. Minimal but spec-conformant."""
    rules_used = {f.rule_id for f in report.findings}
    sarif = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "ms-office-security-check",
                    "version": report.validator_version,
                    "informationUri": "https://github.com/your-gh-user/agent-foundry",
                    "rules": [
                        {
                            "id": rid,
                            "name": rid,
                            "shortDescription": {"text": rid},
                            "helpUri": "skill://ms-office-security-python",
                        } for rid in sorted(rules_used)
                    ],
                }
            },
            "results": [
                {
                    "ruleId": f.rule_id,
                    "level": _sarif_level(f.severity),
                    "message": {"text": f.message + (f"\nFix: {f.fix_hint}" if f.fix_hint else "")},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.file},
                            "region": {"startLine": max(f.line, 1), "startColumn": max(f.col, 1)},
                        }
                    }],
                    "properties": {"confidence": f.confidence, "advisory_only": True},
                } for f in report.findings
            ],
            "invocations": [{"executionSuccessful": True}],
        }],
    }
    return json.dumps(sarif, indent=2)


def _sarif_level(severity: str) -> str:
    return {"critical": "error", "high": "error", "medium": "warning", "info": "note"}.get(severity, "note")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ms_office_security_check",
        description="Office-specific security validator (advisory only).",
    )
    p.add_argument("project_root", nargs="?", default=".")
    p.add_argument("--severity", choices=["critical", "high", "medium", "info", "all"],
                   default="high", help="Minimum severity to report (default: high).")
    p.add_argument("--format", choices=["json", "md", "sarif"], default="json",
                   help="Output format. Default: json.")
    p.add_argument("--rule", action="append", default=[],
                   help="Run only this rule (repeatable).")
    p.add_argument("--ignore", action="append", default=[],
                   help="Skip this rule (repeatable).")
    p.add_argument("--config", default=None,
                   help="Path to project config (default: ms-office-security.yaml or pyproject.toml).")
    p.add_argument("--changed-files", default=None,
                   help="Comma-separated list of files to scan (delta mode for pre-commit).")
    p.add_argument("--mode", choices=["advisory", "strict"], default="advisory",
                   help="Blocking criteria for exit code 1.")
    p.add_argument("--rules-yaml", default=None,
                   help="Override the bundled rules YAML.")
    p.add_argument("--output", default=None,
                   help="Write report to file instead of stdout.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress non-finding output.")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI colors in md rendering.")
    p.add_argument("--version", action="store_true",
                   help="Print validator + schema versions and exit 0.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)

    if args.version:
        print(f"ms_office_security_check {__version__} (schema: {__schema_version__})")
        return 0

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        print(f"ms_office_security_check: project root does not exist: {project_root}",
              file=sys.stderr)
        return 3

    # Locate rules.yaml
    if args.rules_yaml:
        rules_yaml_path = Path(args.rules_yaml)
    else:
        rules_yaml_path = Path(__file__).parent / "rules.yaml"
    if not rules_yaml_path.exists():
        print(f"ms_office_security_check: rules.yaml not found: {rules_yaml_path}",
              file=sys.stderr)
        return 3
    try:
        rules = load_rules(rules_yaml_path)
    except Exception as exc:
        print(f"ms_office_security_check: failed to load rules.yaml: {exc}", file=sys.stderr)
        return 3

    # Project config
    config_path = Path(args.config) if args.config else None
    project_config, config_source = load_project_config(project_root, config_path)
    cfg_section = project_config if isinstance(project_config, dict) else {}
    scope_section = cfg_section.get("scopes", {}) if isinstance(cfg_section, dict) else {}
    scope_allowlist_cfg = scope_section.get("allow", []) if isinstance(scope_section, dict) else []
    ignore_cfg = cfg_section.get("ignore", []) if isinstance(cfg_section, dict) else []
    excludes_cfg = cfg_section.get("exclude", []) if isinstance(cfg_section, dict) else []
    scope_allowlist = set(scope_allowlist_cfg or [])

    # Combine ignore lists
    ignored_rules = set(args.ignore or []) | set(ignore_cfg or [])
    selected_rules = set(args.rule or []) if args.rule else None

    # Changed-files mode
    changed = None
    if args.changed_files:
        changed = [s.strip() for s in args.changed_files.split(",") if s.strip()]

    # Scan
    report = scan_project(project_root, rules, selected_rules, ignored_rules,
                          changed, scope_allowlist, excludes_cfg or [])
    report.config_source = config_source

    # Severity filter
    min_rank = SEVERITY_RANK.get(args.severity, 2) if args.severity != "all" else -1
    report.findings = [f for f in report.findings if SEVERITY_RANK.get(f.severity, 0) >= min_rank]
    # Re-summarize after filter
    summary = {"critical": 0, "high": 0, "medium": 0, "info": 0,
               "suppressed": len(report.suppressions)}
    for f in report.findings:
        summary[f.severity] = summary.get(f.severity, 0) + 1
    report.summary = summary

    # Render
    if args.format == "json":
        rendered = render_json(report)
    elif args.format == "md":
        rendered = render_markdown(report, no_color=args.no_color)
    else:  # sarif
        rendered = render_sarif(report)

    if args.output:
        Path(args.output).write_text(rendered + ("\n" if not rendered.endswith("\n") else ""),
                                     encoding="utf-8")
    else:
        if not args.quiet or report.findings:
            print(rendered)

    # Exit code
    if args.mode == "strict":
        if summary["critical"] > 0:
            return 1
        if summary["high"] > 0 or summary["medium"] > 0:
            return 2
        return 0
    # advisory
    if report.findings:
        return 2
    return 0
