#!/usr/bin/env python3
"""check_deps.py — dependency doctor for lineage-extract-static.

Highlights the dependency / interpreter situation to the END USER instead of
letting a missing optional library surface as a mid-run ImportError. The skill's
CORE (chunking, accumulation, merge to OpenLineage ndjson/CSV, redaction) is pure
stdlib and ALWAYS runs; the libraries below are OPTIONAL enhancers. This skill
NEVER installs anything at runtime — the doctor only detects and reports.

Run standalone:  python3 scripts/check_deps.py
Exit codes:      0 (always — the doctor never fails on a missing OPTIONAL dep)
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path

# (module, pip_name, unlocks, degradation-when-absent)
ENHANCERS = [
    ("jinja2", "jinja2>=3.0.0", "the self-contained HTML report (report.html) + the 3-tab "
     "L1/L2 view-switcher",
     "report.html is SKIPPED; report.md (Mermaid) is emitted as the air-gap fallback. "
     "L2 column detail is HTML-only, so it is not shown in the Mermaid fallback."),
    ("jsonschema", "jsonschema>=4.21.0", "write-time OpenLineage 2.0.2 schema validation",
     "OL events are still written but NOT schema-validated before write (validate_ol degrades)."),
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
    base = Path(executable).resolve().parent.parent
    for libdir in base.glob("lib/python3*"):
        if (libdir / "EXTERNALLY-MANAGED").exists():
            return True
    return False


def _find_full_deps_interpreter(skip: str) -> str | None:
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
    out.append("lineage-extract-static — dependency check")
    out.append(f"Interpreter : {exe}  (CPython {sys.version.split()[0]})")
    out.append("Core (stdlib): OK — chunking, accumulation, OpenLineage ndjson/CSV merge, "
               "redaction, and view projection (L1/L2) ALWAYS run with zero third-party deps.")
    out.append("")
    out.append("Optional enhancers (absence = graceful degradation):")
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
        out.append("Status: FULLY EQUIPPED — all enhancers present (HTML report available).")
        print("\n".join(out))
        return 0
    out.append(f"Status: RUNNABLE — core works now; {len(missing)} enhancer(s) absent.")
    out.append("")
    out.append("To install the enhancers:")
    req = skill_dir / REQ_FILE
    if _externally_managed(exe):
        out.append(f"  NOTE: {exe} is PEP-668 externally-managed — a bare `pip install` is BLOCKED.")
    out.append(f"  • Recommended (PEP-668-safe venv):")
    out.append(f"      python3 -m venv .venv && .venv/bin/pip install -r {req}")
    out.append(f"      # then run the skill's scripts with  .venv/bin/python")
    out.append(f"  • Per-user (where allowed):   python3 -m pip install --user -r {req}")
    out.append(f"  • Last resort (system py):    python3 -m pip install --break-system-packages -r {req}")
    out.append(f"  • Air-gapped (offline wheels): "
               f"python3 -m pip install --no-index --find-links=<wheel-dir> -r {req}")
    sibling = _find_full_deps_interpreter(skip=exe)
    if sibling:
        out.append("")
        out.append(f"  Detected a full-deps interpreter already on this host:")
        out.append(f"      {sibling}")
        out.append(f"      Run the skill's scripts with it directly to skip the install entirely.")
    print("\n".join(out))
    return 0


def main(argv=None) -> int:
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
