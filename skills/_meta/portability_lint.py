#!/usr/bin/env python3
"""portability_lint.py — S076 (#251/#249). The rules that make our Python cross-platform.

Python the language is cross-platform. Ours was not, and choosing Python is what made that
easy to miss: every Windows failure found on 2026-07-30 was in pure Python, in a codebase
that was already Python-first.

    #249  ten modules `import fcntl` at module level. Absent on Windows, so they raise
          ModuleNotFoundError at IMPORT, not at use -- bob cannot run there in any host.
    #251  `memory_primer.py` prints an emoji through a cp1252 console, dies, and exits 0
          with no output. A SessionStart digest that never appears looks like a quiet day.
    #244  `write_text()` without `encoding=` used the LOCALE codec, truncated the target
          to 0 bytes, and every `exists()` guard then protected the wreckage forever.

So porting bash to Python only pays if these rules land FIRST. Otherwise the port trades
"needs jq" for "needs fcntl" and reproduces the same class in new files.

    lint     scan a tree; report everything
    check    same, but only the files given on argv (for the pre-commit hook)

Rules:
  P001  E  module-level import of a platform-exclusive module, unguarded
  P002  W  text-mode file I/O with no explicit `encoding=`
  P003  W  a CLI entrypoint that can emit non-ASCII and does not harden its streams

WHY AST AND NOT REGEX, non-negotiable: this repo has been burned twice by text matching.
`test_no_network_or_shell_imports` searched for the substring `pip` and matched an argparse
help string reading *"the skill never pip-installs at runtime"* -- a sentence promising the
module does not shell out was what made the test say it did. Then the `exists()` inventory
guard flagged the prose sentence NAMING the bad pattern. A linter whose own docstring trips
it is worse than no linter, so this file's rules read the parsed tree, and a test asserts
this very file lints clean.

E blocks, W advises. `check` is deliberately staged-files-only so the ~600 pre-existing
P002 sites do not block every commit while new ones are still refused -- stop the bleeding
before draining the wound. Exit: 0 clean · 2 findings · 3 bad input.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Modules that exist on exactly one platform. Importing one at module level makes the
# WHOLE module unimportable on the other -- the failure is at import, so it takes down
# every caller, not just the code path that needed the lock.
POSIX_ONLY = frozenset({"fcntl", "termios", "pwd", "grp", "resource", "posix"})
WINDOWS_ONLY = frozenset({"msvcrt", "winreg", "winsound", "_winapi"})
PLATFORM_ONLY = POSIX_ONLY | WINDOWS_ONLY

# Names whose presence in a module means its entrypoint is hardened.
HARDENERS = frozenset({"run_cli", "make_streams_utf8", "reconfigure"})

SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", "fixtures", "archive",
                       ".pytest_cache", "templates"})


class Finding:
    __slots__ = ("path", "line", "code", "severity", "message")

    def __init__(self, path: Path, line: int, code: str, severity: str, message: str):
        self.path, self.line, self.code = path, line, code
        self.severity, self.message = severity, message

    def __str__(self) -> str:
        return f"{self.severity}{self.code[1:]} {self.path}:{self.line}  {self.message}"


def _is_binary_mode(call: ast.Call) -> bool:
    """True if this `open()` is binary — mode is arg 1 or the `mode=` kwarg."""
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return isinstance(mode, str) and "b" in mode


def _has_kwarg(call: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in call.keywords)


def _guarded_import_lines(tree: ast.Module) -> set[int]:
    """Line numbers of imports that are legitimately platform-conditional.

    Three guards count, because all three make the import survivable:
      - inside `try: ... except ImportError:`
      - inside a function or method (deferred to call time, so import still succeeds)
      - inside any `if` (the sys.platform / os.name test)

    We do NOT try to prove the `if` actually tests the platform. A conditional import is
    already a deliberate act; the failure this rule exists for is the UNCONDITIONAL one.
    """
    guarded: set[int] = set()

    def mark(node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                guarded.add(child.lineno)

    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            handles_import = any(
                h.type is not None
                and (
                    (isinstance(h.type, ast.Name) and h.type.id in
                     ("ImportError", "ModuleNotFoundError", "Exception"))
                    or (isinstance(h.type, ast.Tuple) and any(
                        isinstance(e, ast.Name) and e.id in
                        ("ImportError", "ModuleNotFoundError", "Exception")
                        for e in h.type.elts))
                )
                for h in node.handlers
            )
            if handles_import:
                for stmt in node.body:
                    mark(stmt)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If)):
            for stmt in node.body:
                mark(stmt)
            for stmt in getattr(node, "orelse", []):
                mark(stmt)
    return guarded


def _entrypoint_line(tree: ast.Module) -> int | None:
    """Line of an `if __name__ == "__main__":` block, if the module has one."""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name) and test.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in test.comparators)):
            return node.lineno
    return None


def _first_non_ascii_literal(tree: ast.Module) -> tuple[int, str] | None:
    """First string LITERAL containing a non-ASCII character, with its line.

    Literals only, via the parsed tree — a comment holding an emoji cannot reach stdout
    and must not be flagged. Docstrings DO count: argparse routinely passes `__doc__` as
    `description=`, so a module docstring is printed output on `--help`.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for ch in node.value:
                if ord(ch) > 127:
                    return node.lineno, ch
    return None


def check_source(path: Path, source: str) -> list[Finding]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 1, "P000", "E",
                        f"does not parse: {exc.msg}")]

    findings: list[Finding] = []
    guarded = _guarded_import_lines(tree)

    # ---- P001: unguarded platform-exclusive import ----
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for name in names:
            if name in PLATFORM_ONLY and node.lineno not in guarded:
                other = "Windows" if name in POSIX_ONLY else "POSIX"
                findings.append(Finding(
                    path, node.lineno, "P001", "E",
                    f"module-level `import {name}` is unguarded — ModuleNotFoundError at "
                    f"IMPORT on {other}, which takes down every caller of this module. "
                    f"Guard with try/except ImportError, defer into the function, or "
                    f"branch on sys.platform."))

    # ---- P002: text I/O with no explicit encoding ----
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None)
        if name in ("read_text", "write_text") and not _has_kwarg(node, "encoding"):
            findings.append(Finding(
                path, node.lineno, "P002", "W",
                f"`{name}()` without `encoding=` uses the LOCALE codec — cp1252 on a "
                f"Windows console. This is #244: the write truncated the file, then "
                f"raised."))
        elif name == "open" and not _is_binary_mode(node) and not _has_kwarg(node, "encoding"):
            findings.append(Finding(
                path, node.lineno, "P002", "W",
                "text-mode `open()` without `encoding=` uses the LOCALE codec. Pass "
                "encoding='utf-8', or open in binary mode."))

    # ---- P003: a CLI that can emit non-ASCII and does not harden its streams ----
    entry = _entrypoint_line(tree)
    if entry is not None:
        names_used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names_used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        if not (names_used & HARDENERS):
            hit = _first_non_ascii_literal(tree)
            if hit is not None:
                line, ch = hit
                findings.append(Finding(
                    path, entry, "P003", "W",
                    f"entrypoint does not harden stdout/stderr, and this module emits "
                    f"non-ASCII ({ch!r} at line {line}). On a cp1252 console that raises "
                    f"UnicodeEncodeError — #251's failure was exit 0 with NO output. "
                    f"Wrap with `portable_cli.run_cli(main)`."))

    findings.sort(key=lambda f: (f.line, f.code))
    return findings


def check_path(path: Path) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(path, 1, "P000", "E", f"cannot read: {exc}")]
    return check_source(path, source)


def iter_python(root: Path):
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def report(findings: list[Finding], *, quiet: bool = False) -> int:
    errors = [f for f in findings if f.severity == "E"]
    warns = [f for f in findings if f.severity == "W"]
    if not quiet:
        for f in findings:
            print(f)
    if not findings:
        print("[OK] portability: clean")
        return 0
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    if errors:
        print("E = blocks. W = advisory; new ones are refused at commit time.")
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-platform lint for the harness's Python.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_lint = sub.add_parser("lint", help="scan a tree")
    p_lint.add_argument("root", nargs="?", default=".", type=Path)
    p_lint.add_argument("--errors-only", action="store_true",
                        help="report only E findings (the blocking set)")
    p_lint.add_argument("--summary", action="store_true", help="counts per rule, no detail")

    p_check = sub.add_parser("check", help="check only the given files (pre-commit)")
    p_check.add_argument("paths", nargs="*", type=Path)
    p_check.add_argument("--errors-only", action="store_true")

    args = ap.parse_args()

    if args.cmd == "lint":
        root = args.root
        if not root.exists():
            print(f"! {root} does not exist", file=sys.stderr)
            return 3
        targets = list(iter_python(root)) if root.is_dir() else [root]
    else:
        targets = [p for p in args.paths if p.suffix == ".py" and p.is_file()]
        if not targets:
            return 0

    findings: list[Finding] = []
    for p in targets:
        findings.extend(check_path(p))
    if getattr(args, "errors_only", False):
        findings = [f for f in findings if f.severity == "E"]

    if getattr(args, "summary", False):
        counts: dict[str, int] = {}
        for f in findings:
            counts[f"{f.severity}{f.code[1:]}"] = counts.get(f"{f.severity}{f.code[1:]}", 0) + 1
        print(f"scanned {len(targets)} file(s)")
        for code in sorted(counts):
            print(f"  {code}  {counts[code]}")
        return 2 if findings else 0

    return report(findings)


if __name__ == "__main__":
    from portable_cli import run_cli
    raise SystemExit(run_cli(main))
