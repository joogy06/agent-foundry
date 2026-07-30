#!/usr/bin/env python3
"""optional_deps.py — S075. Optional-dependency readiness across pip AND npm (#240).

    report                what is missing, what it costs, and what would install it
    report --json         machine-readable, for install.py and the session digest
    install-cmd --group X the exact command to run — resolved, not guessed
    merge-inventory       fold readiness into ~/.claude/state/inventory.json
    doctor                which package managers work, and which ones would LIE to you

WHY THIS EXISTS

The harness runs stdlib-only: 225 skills, the gates, the installer and the session hooks all
work with none of this installed. That is exactly why absence goes unnoticed until someone
trips over it — `financial-document-ingestion` routes .xlsx to a skill that cannot run
without openpyxl, eleven `lineage-extract-static` tests fail on one missing jinja2, and
puppeteer-core was absent for so long that the UI verification lane had never once executed.

THE TRAP THIS EXISTS TO STOP — AND IT IS LIVE ON THIS HOST

**`pip3` is not necessarily the pip for the python that will import the package.** Probed
2026-07-29 here: `python3` is 3.13 while `pip3` reports `(python 3.14)`. `pip3 install
openpyxl` would report success, place the package in 3.14's site-packages, and leave the
import failing exactly as before — the worst failure shape there is, because it looks fixed.

So the rule is absolute: **install with `<the interpreter that will import it> -m pip`,
never with a bare `pip` or `pip3`.** `doctor` reports the mismatch rather than silently
working around it, because a user with a genuinely split environment needs to know.

Interpreter discovery for non-python callers: `python3`, `python`, and versioned names like
`python3.13` / `python3.12`, plus the `py -3` launcher on Windows. When this module is
already running, the answer is `sys.executable` and no search is needed.

WHAT IT REFUSES TO DO

**It never installs anything by itself** — it prints the command, and `install.py
--with-extras` runs it on an explicit request. A tool that quietly pip-installs on a
locked-down machine fails in a way nobody can debug.

**It never fails the caller.** A missing optional dependency is a known state, not a defect —
the same rule that says such a dependency must `pytest.skip` rather than fail. Exit is 0
unless `--strict`, which exists for a CI job that has decided a capability IS required.

Stdlib only. Exit: 0 · 1 only with --strict and a gap in scope · 3 bad input.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = "optional-deps.v1"

_CAP_RE = re.compile(r"^#\s*@capability:\s*(?P<v>.+?)\s*$")
_META_RE = re.compile(r"^#\s*@(?P<k>unlocks|skills|without|critical):\s*(?P<v>.+?)\s*$")
_CONT_RE = re.compile(r"^#\s{3,}(?P<v>\S.*?)\s*$")
_IMPORT_RE = re.compile(r"#\s*import:\s*(?P<v>[A-Za-z0-9_.]+)")
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_PYVER_RE = re.compile(r"\(python (\d+\.\d+)\)")

# Versioned interpreters, newest first. A bare `python` may still be 2.x on an old box.
_PY_CANDIDATES = ["python3", "python3.14", "python3.13", "python3.12", "python3.11", "python"]
_NODE_MANAGERS = ["npm", "pnpm", "yarn"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_manifest(kind: str) -> Path:
    name = "requirements-optional.txt" if kind == "python" else "package-optional.json"
    for cand in (_repo_root() / name, Path.home() / ".claude" / name):
        if cand.is_file():
            return cand
    return _repo_root() / name


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def parse_python(path: Path) -> list[dict]:
    """requirements-optional.txt -> capability groups. Ordinary pip syntax; the
    structured comments pip ignores are what carry the meaning."""
    if not path.is_file():
        return []
    groups: list[dict] = []
    cur: dict | None = None
    last_key: str | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _CAP_RE.match(raw)
        if m:
            cur = {"ecosystem": "python", "capability": m.group("v"), "unlocks": "",
                   "skills": "", "without": "", "critical": "", "requirements": []}
            groups.append(cur)
            last_key = None
            continue
        if cur is None:
            continue
        m = _META_RE.match(raw)
        if m:
            cur[m.group("k")] = m.group("v")
            last_key = m.group("k")
            continue
        m = _CONT_RE.match(raw)
        if m and last_key:
            cur[last_key] = f"{cur[last_key]} {m.group('v')}".strip()
            continue
        if raw.startswith("#") or not raw.strip():
            last_key = None
            if raw.startswith("# ---"):
                cur = None
            continue
        spec = raw.split("#")[0].strip()
        nm = _NAME_RE.match(spec) if spec else None
        if not nm:
            continue
        im = _IMPORT_RE.search(raw)
        cur["requirements"].append({
            "spec": spec,
            "name": nm.group(1),
            "probe": im.group("v") if im else nm.group(1).replace("-", "_"),
        })
        last_key = None
    return [g for g in groups if g["requirements"]]


def parse_node(path: Path) -> tuple[list[dict], str]:
    if not path.is_file():
        return [], "~/.claude"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"MANIFEST_UNREADABLE: {path}: {exc}")
    groups = []
    for cap in data.get("capabilities", []):
        groups.append({
            "ecosystem": "node",
            "capability": cap.get("capability", "?"),
            "unlocks": cap.get("unlocks", ""),
            "skills": cap.get("skills", ""),
            "without": cap.get("without", ""),
            "requirements": [{"spec": f"{p['name']}@{p.get('spec','latest')}",
                              "name": p["name"], "probe": p["name"]}
                             for p in cap.get("packages", [])],
        })
    return groups, data.get("install_root", "~/.claude")


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def python_module_present(module: str) -> bool:
    """find_spec, not import — importing to test availability runs module top-level
    code, which is slow and occasionally side-effecting."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError, ModuleNotFoundError):
        return False


def node_package_present(name: str, root: Path) -> bool:
    """Node resolves bare specifiers by walking node_modules upward, so a package at
    the install root is visible to every .mjs beneath it."""
    for base in (root, Path.cwd()):
        if (base / "node_modules" / name).exists():
            return True
    return False


def probe(groups: list[dict], node_root: Path, only: set[str] | None = None) -> dict:
    out = []
    for g in groups:
        if only and g["capability"] not in only:
            continue
        reqs = []
        for r in g["requirements"]:
            present = (python_module_present(r["probe"]) if g["ecosystem"] == "python"
                       else node_package_present(r["probe"], node_root))
            reqs.append({**r, "present": present})
        missing = [r for r in reqs if not r["present"]]
        out.append({**{k: g.get(k, "") for k in ("ecosystem", "capability", "unlocks",
                                                 "skills", "without", "critical")},
                    "requirements": reqs,
                    "missing": [r["name"] for r in missing],
                    "state": "ready" if not missing
                             else ("partial" if len(missing) < len(reqs) else "unavailable")})
    return {
        "schema_version": SCHEMA_VERSION,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "capabilities_total": len(out),
        "capabilities_ready": sum(1 for g in out if g["state"] == "ready"),
        # No manifest is NOT the same as nothing missing. Without this, a machine
        # where the manifests were never installed reports "0/0 capabilities ready"
        # — which reads exactly like success. Absence must never present as a pass;
        # it is the same rule as UNMEASURED in the UX evidence contract and
        # SEARCHED_NOT_FOUND in the probe ledger.
        "manifests_found": bool(out),
        # A CRITICAL group missing is categorically different from an optional one
        # missing: the harness itself misbehaves rather than a capability being
        # unavailable. Consumers must be able to tell those apart without parsing
        # prose.
        "critical_missing": [g["capability"] for g in out
                             if str(g.get("critical", "")).lower() == "true"
                             and g["state"] != "ready"],
        "groups": out,
    }


# ---------------------------------------------------------------------------
# package managers — resolved, never assumed
# ---------------------------------------------------------------------------

def _run(argv: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def resolve_python_interpreter() -> dict:
    """The interpreter that will actually import the package.

    When we are the running process there is nothing to search for — sys.executable is
    the answer, and any other choice risks installing into a different environment.
    """
    return {"path": sys.executable,
            "version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "source": "sys.executable"}


def discover_python_interpreters() -> list[dict]:
    """For callers that are NOT python (a bash probe, a shell hook). Names differ by
    platform and by install: python3, python, python3.13, and `py -3` on Windows."""
    found, seen = [], set()
    cands = list(_PY_CANDIDATES)
    if os.name == "nt":
        cands.append("py")
    for name in cands:
        path = shutil.which(name)
        if not path or path in seen:
            continue
        seen.add(path)
        argv = [path, "-3", "-c"] if name == "py" else [path, "-c"]
        code, out = _run(argv + ["import sys;print('%d.%d'%sys.version_info[:2])"])
        if code == 0 and out.strip():
            found.append({"name": name, "path": path, "version": out.strip()})
    return found


def in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def externally_managed() -> Path | None:
    """PEP 668. Debian, Ubuntu, Fedora and friends ship an EXTERNALLY-MANAGED marker
    that makes `pip install` refuse — including `pip install --user`, which is the
    part people are surprised by.

    Detected rather than discovered: without this, the command we print is one the
    user runs and watches fail, which is exactly the experience #240 exists to end.
    """
    if in_virtualenv():
        return None
    try:
        import sysconfig
        for key in ("stdlib", "platstdlib"):
            p = sysconfig.get_path(key)
            if p and (Path(p) / "EXTERNALLY-MANAGED").is_file():
                return Path(p) / "EXTERNALLY-MANAGED"
    except Exception:
        pass
    return None


def pip_install_flags() -> tuple[list[str], str]:
    """The flags that make an install actually land where this python imports from.

    Returns (flags, explanation). On a PEP 668 system that is
    `--user --break-system-packages`: with `--user` the install goes to the user
    site-packages and does NOT touch the distro-managed tree — the flag only
    overrides the marker's refusal for that user-local install. The alternative is
    a venv, which is cleaner but which the harness cannot adopt on the user's
    behalf, because every skill script runs under whatever python invoked it.
    """
    if in_virtualenv():
        return [], "virtualenv active — installing into it"
    if externally_managed():
        return (["--user", "--break-system-packages"],
                "PEP 668 externally-managed python: installing into your USER site "
                "(~/.local/lib/pythonX.Y). The distro-managed tree is untouched; the flag "
                "only lifts the marker's refusal for a user-local install. A venv is the "
                "tidier alternative, but every skill script runs under whichever python "
                "invoked it, so the harness cannot pick one for you.")
    return ["--user"], "installing into your user site-packages"


def pip_status() -> dict:
    """Does `<our interpreter> -m pip` work, and would a bare pip/pip3 lie to us?"""
    interp = resolve_python_interpreter()
    code, out = _run([interp["path"], "-m", "pip", "--version"])
    ours_ok = code == 0
    ours_ver = None
    m = _PYVER_RE.search(out or "")
    if m:
        ours_ver = m.group(1)

    strays = []
    for name in ("pip3", "pip"):
        path = shutil.which(name)
        if not path:
            continue
        code, out = _run([path, "--version"])
        if code != 0:
            continue
        m = _PYVER_RE.search(out or "")
        ver = m.group(1) if m else None
        if ver and ver != interp["version"]:
            strays.append({"name": name, "path": path, "python": ver})
    flags, why = pip_install_flags()
    em = externally_managed()
    return {
        "command": [interp["path"], "-m", "pip"],
        "available": ours_ok,
        "interpreter": interp["path"],
        "interpreter_version": interp["version"],
        "pip_reports_python": ours_ver,
        "mismatched_shims": strays,
        "install_flags": flags,
        "install_flags_reason": why,
        "externally_managed": str(em) if em else None,
        "virtualenv": in_virtualenv(),
    }


def node_status(install_root: Path) -> dict:
    node = shutil.which("node")
    node_ver = ""
    if node:
        _, node_ver = _run([node, "--version"])
    chosen, alts = None, []
    for name in _NODE_MANAGERS:
        path = shutil.which(name)
        if not path:
            continue
        (alts if chosen else alts).append(name)
        if chosen is None:
            chosen = {"name": name, "path": path}
    return {
        "node": node,
        "node_version": node_ver.strip(),
        "manager": chosen,
        "available_managers": alts,
        "install_root": str(install_root),
    }


def install_command(eco: str, specs: list[str], node_root: Path) -> tuple[list[str] | None, str]:
    """The command to run, or None with the reason it cannot be built."""
    if not specs:
        return None, "nothing missing"
    if eco == "python":
        st = pip_status()
        if not st["available"]:
            return None, (f"pip is not available for {st['interpreter']}. Install python3-pip "
                          f"(or use your distro's package manager), then re-run.")
        return list(st["command"]) + ["install", "--upgrade", *st["install_flags"], *specs], ""
    st = node_status(node_root)
    if not st["node"]:
        return None, "node is not installed — the browser-measurement lane needs it"
    if not st["manager"]:
        return None, ("no npm/pnpm/yarn found. Node is present, so install one of them "
                      "(npm ships with most node distributions).")
    name = st["manager"]["name"]
    verb = ["add"] if name in ("pnpm", "yarn") else ["install"]
    prefix = ["--prefix", str(node_root)] if name == "npm" else ["--dir", str(node_root)]
    if name == "yarn":
        prefix = ["--cwd", str(node_root)]
    return [st["manager"]["path"], *verb, *prefix, *specs], ""


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

_MARK = {"ready": "OK  ", "partial": "PART", "unavailable": "MISS"}


def _no_manifest_text(kind: str = "report") -> str:
    return (f"[optional dependencies] NO MANIFEST FOUND — readiness is UNKNOWN, not clean.\n"
            f"  looked for requirements-optional.txt / package-optional.json in\n"
            f"    {_repo_root()}\n"
            f"    {Path.home() / '.claude'}\n"
            f"  Re-run install.py to place them, or pass --requirements / --package-manifest.")


def render(result: dict, node_root: Path, verbose: bool = False) -> str:
    if not result.get("manifests_found"):
        return _no_manifest_text()
    L = []
    L.append(f"[optional dependencies]  {result['capabilities_ready']}/"
             f"{result['capabilities_total']} capabilities ready · python {result['python']}")
    L.append("")
    for eco in ("python", "node"):
        gs = [g for g in result["groups"] if g["ecosystem"] == eco]
        if not gs:
            continue
        L.append(f"  -- {eco} --")
        for g in gs:
            L.append(f"  {_MARK[g['state']]}  {g['capability']:<20} {g['unlocks']}")
            if g["state"] == "ready" and not verbose:
                continue
            if g["missing"]:
                L.append(f"          missing: {', '.join(g['missing'])}")
            if g["without"] and g["state"] != "ready":
                L.append(f"          without: {g['without']}")
            if g["skills"]:
                L.append(f"          skills:  {g['skills']}")
            L.append("")
        L.append("")

    if result.get("critical_missing"):
        L.append("  " + "!" * 66)
        L.append(f"  ! REQUIRED, not optional: {', '.join(result['critical_missing'])}")
        L.append("  ! These are not a capability you can do without — a SessionStart hook")
        L.append("  ! imports one of them on every session, and the gates use the other for")
        L.append("  ! schema validation, which fails toward 'not checked'.")
        L.append("  " + "!" * 66)
        L.append("")
    gaps = [g for g in result["groups"] if g["state"] != "ready"]
    if not gaps:
        L.append("  every optional capability is available.")
        return "\n".join(L)

    L.append("  Nothing here is required. To install a capability deliberately:")
    L.append(f"    python3 install.py --with-extras={','.join(g['capability'] for g in gaps)}")
    L.append("")
    for eco in ("python", "node"):
        specs = [r["spec"] for g in gaps if g["ecosystem"] == eco
                 for r in g["requirements"] if not r["present"]]
        if not specs:
            continue
        cmd, why = install_command(eco, specs, node_root)
        L.append(f"    {eco}:  {' '.join(cmd) if cmd else 'UNAVAILABLE — ' + why}")
    st = pip_status()
    if st["externally_managed"] or st["virtualenv"]:
        L.append("")
        L.append(f"  note: {st['install_flags_reason']}")
    if st["mismatched_shims"]:
        L.append("")
        L.append("  ! Do NOT use a bare `pip` / `pip3` here — they belong to a different python:")
        for s in st["mismatched_shims"]:
            L.append(f"      {s['name']} -> python {s['python']}, but this harness runs "
                     f"python {st['interpreter_version']}")
        L.append("    Installing with those would report success and change nothing importable.")
    return "\n".join(L)


def digest_line(result: dict) -> str:
    """One line for the SessionStart digest. Capability names, never module names —
    a session banner has no room to be a package manager."""
    if not result.get("manifests_found"):
        return "[extras] readiness UNKNOWN — no optional-dependency manifest found"
    crit = result.get("critical_missing") or []
    if crit:
        return (f"[extras] ⚠ REQUIRED libraries missing: {', '.join(crit)} — the harness "
                f"will misbehave (a SessionStart hook and the gates need these). "
                f"Run `install.py --with-extras=core`.")
    gaps = [g["capability"] for g in result["groups"] if g["state"] != "ready"]
    if not gaps:
        return f"[extras] all {result['capabilities_total']} optional capabilities ready"
    return (f"[extras] {result['capabilities_ready']}/{result['capabilities_total']} ready — "
            f"unavailable: {', '.join(gaps)} (optional; `install.py --with-extras=<name>`)")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _load(args) -> tuple[list[dict], Path, set[str] | None]:
    groups = []
    if args.ecosystem in ("all", "python"):
        groups += parse_python(Path(args.requirements) if args.requirements
                               else default_manifest("python"))
    node_root = Path.home() / ".claude"
    if args.ecosystem in ("all", "node"):
        ng, root = parse_node(Path(args.package_manifest) if args.package_manifest
                              else default_manifest("node"))
        groups += ng
        node_root = Path(os.path.expanduser(root))
    known = {g["capability"] for g in groups}
    only = None
    if getattr(args, "group", None):
        only = {c.strip() for c in args.group.split(",") if c.strip()}
        unknown = only - known
        if unknown:
            sys.stderr.write(f"UNKNOWN_CAPABILITY: {', '.join(sorted(unknown))}\n"
                             f"  known: {', '.join(sorted(known))}\n")
            raise SystemExit(3)
    return groups, node_root, only


def cmd_report(args) -> int:
    groups, node_root, only = _load(args)
    result = probe(groups, node_root, only)
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.digest:
        print(digest_line(result))
    else:
        print(render(result, node_root, verbose=args.verbose))
    if args.strict and result["capabilities_ready"] < result["capabilities_total"]:
        return 1
    return 0


def cmd_install_cmd(args) -> int:
    groups, node_root, only = _load(args)
    result = probe(groups, node_root, only)
    any_out = False
    for eco in ("python", "node"):
        specs = [r["spec"] for g in result["groups"]
                 if g["ecosystem"] == eco and g["state"] != "ready"
                 for r in g["requirements"] if not r["present"]]
        if not specs:
            continue
        cmd, why = install_command(eco, specs, node_root)
        any_out = True
        if cmd is None:
            sys.stderr.write(f"{eco}: UNAVAILABLE — {why}\n")
            continue
        print(json.dumps(cmd) if args.json else " ".join(cmd))
    if not any_out and not args.json:
        print("# nothing missing in scope")
    return 0


def cmd_doctor(args) -> int:
    groups, node_root, _ = _load(args)
    st, nst = pip_status(), node_status(node_root)
    print("[package managers]")
    print(f"  interpreter      {st['interpreter']}  (python {st['interpreter_version']})")
    print(f"  pip              {'OK' if st['available'] else 'NOT AVAILABLE'}"
          f"   via {' '.join(st['command'])}")
    if st["mismatched_shims"]:
        for s in st["mismatched_shims"]:
            print(f"  ! {s['name']:<14} {s['path']} reports python {s['python']} — "
                  f"MISMATCH, do not use it")
        print("    A package installed by those lands where this python cannot import it.")
    else:
        print("  shims            no pip/pip3 mismatch detected")
    if st["virtualenv"]:
        print(f"  virtualenv       active ({sys.prefix})")
    if st["externally_managed"]:
        print(f"  PEP 668          externally managed — marker at {st['externally_managed']}")
        print(f"                   plain `pip install` REFUSES here, and so does `--user`")
    print(f"  install flags    {' '.join(st['install_flags']) or '(none)'}")
    print(f"                   {st['install_flags_reason']}")
    print(f"  node             {nst['node_version'] or 'ABSENT'}")
    print(f"  node manager     {nst['manager']['name'] if nst['manager'] else 'NONE'}"
          f"   (found: {', '.join(nst['available_managers']) or 'none'})")
    print(f"  node install to  {nst['install_root']}")
    if not st["available"] and not nst["manager"]:
        print("\n  Neither ecosystem can install anything here. That is a supported state:")
        print("  the harness runs stdlib-only. Capabilities needing a library stay unavailable.")
    # Other interpreters on PATH are informational, not a problem in themselves.
    others = [i for i in discover_python_interpreters() if i["version"] != st["interpreter_version"]]
    if others:
        print("\n  other pythons on PATH (informational):")
        for i in others:
            print(f"    {i['name']:<12} {i['path']}  python {i['version']}")
    return 0


def cmd_merge_inventory(args) -> int:
    """Fold readiness into the env-adoption manifest so readiness has ONE surface.

    probe.sh overwrites inventory.json wholesale on a real probe and then runs its
    mergers; this is the contract inventory_history.py already runs under, and the
    same discipline: never raise, never block the probe.
    """
    inv_path = (Path(args.inventory).expanduser() if args.inventory
                else Path.home() / ".claude" / "state" / "inventory.json")
    try:
        groups, node_root, only = _load(args)
        result = probe(groups, node_root, only)
        inv = json.loads(inv_path.read_text(encoding="utf-8")) if inv_path.is_file() else {}
        if not isinstance(inv, dict):
            return 0
        inv["optional_deps"] = {
            "schema_version": SCHEMA_VERSION,
            "python": result["python"],
            # A consumer must be able to tell "nothing missing" from "never measured".
            "state": "measured" if result.get("manifests_found") else "unknown_no_manifest",
            "ready": result["capabilities_ready"],
            "total": result["capabilities_total"],
            "unavailable": [g["capability"] for g in result["groups"]
                            if g["state"] == "unavailable"],
            "partial": [g["capability"] for g in result["groups"] if g["state"] == "partial"],
            "missing": sorted({m for g in result["groups"] for m in g["missing"]}),
        }
        inv_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = inv_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, inv_path)
        if not args.quiet:
            print(f"merged optional_deps into {inv_path}")
    except Exception as exc:                       # never break a probe
        if not args.quiet:
            sys.stderr.write(f"optional_deps: merge skipped ({exc})\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="optional_deps.py",
        description="Optional-dependency readiness across pip and npm. Reports; never installs.")
    p.add_argument("--requirements", default=None)
    p.add_argument("--package-manifest", default=None)
    p.add_argument("--ecosystem", default="all", choices=("all", "python", "node"))

    # The same three flags again on every subcommand, with SUPPRESS defaults so an
    # unset one does NOT overwrite the value given before the subcommand.
    #
    # A flag that works in only one position is a trap — it is the exact shape of
    # the agy `-p` flag-order incident, where `agy -p --sandbox "…"` silently ran
    # UNSANDBOXED with the literal prompt `--sandbox`. Here the failure was milder
    # (argparse exits 2) but the principle is the same: accept it where a person
    # would naturally type it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--requirements", default=argparse.SUPPRESS)
    common.add_argument("--package-manifest", default=argparse.SUPPRESS)
    common.add_argument("--ecosystem", default=argparse.SUPPRESS,
                        choices=("all", "python", "node"))

    sub = p.add_subparsers(dest="cmd", required=True, parser_class=argparse.ArgumentParser)

    r = sub.add_parser("report", parents=[common], help="what is missing and what it costs")
    r.add_argument("--group", default=None, help="comma-separated capability names")
    r.add_argument("--json", action="store_true")
    r.add_argument("--digest", action="store_true", help="one line, for a session banner")
    r.add_argument("--verbose", action="store_true")
    r.add_argument("--strict", action="store_true",
                   help="exit 1 if anything in scope is missing (for CI that requires it)")
    r.set_defaults(func=cmd_report)

    i = sub.add_parser("install-cmd", parents=[common], help="print the resolved install command")
    i.add_argument("--group", default=None)
    i.add_argument("--json", action="store_true")
    i.set_defaults(func=cmd_install_cmd)

    d = sub.add_parser("doctor", parents=[common], help="which managers work, and which would lie")
    d.set_defaults(func=cmd_doctor)

    m = sub.add_parser("merge-inventory", parents=[common], help="fold readiness into inventory.json")
    m.add_argument("--group", default=None)
    m.add_argument("--inventory", default=None)
    m.add_argument("--quiet", action="store_true")
    m.set_defaults(func=cmd_merge_inventory)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
