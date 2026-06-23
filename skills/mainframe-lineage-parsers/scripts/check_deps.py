#!/usr/bin/env python3
"""check_deps.py — dependency doctor for mainframe-lineage-parsers.

Highlights the dependency / interpreter situation to the END USER instead of
letting a missing optional library surface as a mid-run ImportError. This skill's
CORE is pure stdlib and ALWAYS runs; the libraries below are OPTIONAL enhancers
(import-if-present, graceful degradation). This skill NEVER installs anything at
runtime (D1 invariant: no runtime pip install, air-gap target) — the doctor only
*detects and reports*; installation is a deliberate user action.

Run standalone:   python3 scripts/check_deps.py
Or via the CLI:   python3 scripts/run_lineage.py --check-deps
Exit codes:       0 = core runnable (always, barring a broken interpreter)
                  (the doctor never fails on a missing OPTIONAL dep — that's the point)
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path

# (module, pip_name, min_version, unlocks, degradation-when-absent)
ENHANCERS = [
    ("jsonschema", "jsonschema>=4.21.0", "write-time OpenLineage 2.0.2 schema validation",
     "emit still runs; events are NOT schema-validated before write (validate_ol degrades)."),
    ("sqlglot", "sqlglot>=23.0.0", "higher-precision embedded EXEC SQL parsing",
     "SQL falls back to the stdlib regex engine (lower precision); a 'sql.engine_degraded' "
     "diagnostic is emitted. NOT a failure."),
    ("networkx", "networkx>=3.0", "graph assembly via networkx",
     "graph assembly uses the stdlib fallback — same output, only slower on very large estates."),
]
REQ_FILE = "requirements-optional.txt"


def _probe(mod: str):
    spec = importlib.util.find_spec(mod)
    if spec is None:
        return (False, None)
    try:
        import importlib.metadata as _md
        ver = _md.version(mod)
    except Exception:
        ver = "?"
    return (True, ver)


def _externally_managed(executable: str) -> bool:
    """True if this interpreter is PEP-668 externally-managed (pip install blocked)."""
    base = Path(executable).resolve().parent.parent
    for libdir in base.glob("lib/python3*"):
        if (libdir / "EXTERNALLY-MANAGED").exists():
            return True
    return False


def _find_full_deps_interpreter(skip: str) -> str | None:
    """Scan common interpreter locations for a sibling python that already has
    every enhancer importable — so we can point the user at it instead of forcing
    a venv. Detection only; we never silently re-exec under it."""
    cands: list[str] = []
    for name in ("python3", "python3.14", "python3.13", "python3.12", "python3.11"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    for d in (Path.home() / ".local/bin", Path("/usr/local/bin"), Path("/usr/bin")):
        cands += [str(p) for p in d.glob("python3*") if p.is_file()]
    seen, mods = set(), [m for m, *_ in ENHANCERS]
    import subprocess
    for c in cands:
        rc = os.path.realpath(c)
        if rc in seen or rc == os.path.realpath(skip):
            continue
        seen.add(rc)
        code = "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in %r) else 1)" % mods
        try:
            if subprocess.run([c, "-c", code], capture_output=True, timeout=10).returncode == 0:
                return c
        except Exception:
            continue
    return None


def report(skill_dir: Path | None = None) -> int:
    skill_dir = skill_dir or Path(__file__).resolve().parent.parent
    exe = sys.executable
    out = []
    out.append("mainframe-lineage-parsers — dependency check")
    out.append(f"Interpreter : {exe}  (CPython {sys.version.split()[0]})")
    out.append("Core (stdlib): OK — Control-M/COBOL/JCL/EXEC-SQL extraction, IR, and "
               "OpenLineage 2.0.2 ndjson ALWAYS run with zero third-party deps.")
    out.append("")
    out.append("Optional enhancers (import-if-present; absence = graceful degradation):")
    missing = []
    for mod, pip_name, unlocks, degraded in ENHANCERS:
        present, ver = _probe(mod)
        if present:
            out.append(f"  {mod:<11} PRESENT ({ver})  — {unlocks}")
        else:
            missing.append(pip_name)
            out.append(f"  {mod:<11} MISSING          — degraded: {degraded}")
    out.append("")
    if not missing:
        out.append("Status: FULLY EQUIPPED — all enhancers present.")
        print("\n".join(out))
        return 0
    out.append(f"Status: RUNNABLE — core works now; {len(missing)} enhancer(s) absent "
               "(see degradation above).")
    out.append("")
    out.append("To install the enhancers:")
    req = skill_dir / REQ_FILE
    if _externally_managed(exe):
        out.append(f"  NOTE: {exe} is PEP-668 externally-managed — a bare `pip install` is BLOCKED.")
    out.append(f"  • Recommended (PEP-668-safe venv):")
    out.append(f"      python3 -m venv .venv && .venv/bin/pip install -r {req}")
    out.append(f"      # then run the skill with  .venv/bin/python scripts/run_lineage.py ...")
    out.append(f"  • Per-user (where allowed):   python3 -m pip install --user -r {req}")
    out.append(f"  • pipx-managed env:           pipx runpip <env> install -r {req}")
    out.append(f"  • Last resort (system py):    python3 -m pip install --break-system-packages -r {req}")
    out.append(f"  • Air-gapped (offline wheels): "
               f"python3 -m pip install --no-index --find-links=<wheel-dir> -r {req}")
    sibling = _find_full_deps_interpreter(skip=exe)
    if sibling:
        out.append("")
        out.append(f"  Detected a full-deps interpreter already on this host:")
        out.append(f"      {sibling}")
        out.append(f"      Run the skill with it directly to skip the install entirely.")
    print("\n".join(out))
    return 0


def main(argv=None) -> int:
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
