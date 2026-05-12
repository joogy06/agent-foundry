"""manifests.py — 6-ecosystem manifest + lockfile detection and parsing.

Stdlib only (Python 3.10+). No third-party deps.

Public API:
    detect_manifests(project_root: Path) -> list[Manifest]
    Dependency  -- frozen dataclass
    Manifest    -- frozen dataclass
    Ecosystem   -- Literal type

See ~/.claude/skills/dep-currency-check/references/ecosystem-quirks.md for
ecosystem details.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Ecosystem = Literal["python", "js", "rust", "go", "ruby", "java"]
ConstraintType = Literal[
    "exact", "range", "caret", "tilde", "wildcard", "git", "path", "unspecified"
]


@dataclass(frozen=True)
class Dependency:
    name: str
    declared_version: str
    constraint_type: ConstraintType
    ecosystem: Ecosystem
    is_dev: bool = False
    workspace_root: Optional[Path] = None
    is_transitive: bool = False
    transitive_depth: int = 0
    parent_chain: tuple = ()


@dataclass(frozen=True)
class Manifest:
    path: Path
    ecosystem: Ecosystem
    deps: tuple
    has_lockfile: bool
    lockfile_path: Optional[Path]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_constraint(version: str) -> ConstraintType:
    """Classify a version constraint string."""
    if not version or version in ("*", "any"):
        return "unspecified"
    v = version.strip()
    if v.startswith("^"):
        return "caret"
    if v.startswith("~"):
        return "tilde"
    if v.startswith("git+") or "://" in v:
        return "git"
    if v.startswith(("./", "../", "/")) or v.startswith("file:"):
        return "path"
    if "*" in v:
        return "wildcard"
    if any(op in v for op in (">=", "<=", ">", "<", "!=", ",")):
        return "range"
    if v.startswith("="):
        return "exact"
    # Bare versions like "1.2.3" — exact for most ecosystems
    if re.match(r"^\d+(\.\d+)*", v):
        return "exact"
    return "unspecified"


def _gitignored_paths(project_root: Path) -> set:
    """Best-effort gitignore-respecting skip list. Falls back to a static list
    if `git ls-files` is unavailable. Returns paths relative to project_root."""
    static_skips = {
        "node_modules", "vendor", ".venv", "venv", ".git",
        "__pycache__", "target", "build", "dist", ".tox",
    }
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "ls-files", "--others",
             "--ignored", "--exclude-standard", "-z"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            ignored = set()
            for line in proc.stdout.split("\0"):
                if line:
                    # Add top-level dir of ignored paths
                    ignored.add(line.split("/")[0])
            return ignored | static_skips
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return static_skips


def _walk_for_manifests(project_root: Path) -> list:
    """Walk project tree (gitignore-aware), return list of manifest file paths."""
    targets = {
        "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Gemfile",
        "pom.xml", "build.gradle", "build.gradle.kts",
    }
    requirements_re = re.compile(r"^requirements[^/]*\.txt$")
    skip_dirs = _gitignored_paths(project_root)
    found = []
    for p in project_root.rglob("*"):
        try:
            rel_parts = p.relative_to(project_root).parts
        except ValueError:
            continue
        if any(part in skip_dirs or part.startswith(".") and part not in (".",)
               for part in rel_parts[:-1]):
            # Skip files inside gitignored / dot dirs
            continue
        if p.is_file() and (p.name in targets or requirements_re.match(p.name)):
            found.append(p)
    return found


# ---------------------------------------------------------------------------
# Per-ecosystem parsers
# ---------------------------------------------------------------------------


def _parse_pyproject_toml(path: Path) -> Manifest:
    """Parse pyproject.toml (PEP 621 or poetry). Tolerates malformed."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return Manifest(path=path, ecosystem="python", deps=tuple(),
                        has_lockfile=False, lockfile_path=None)
    deps: list = []
    # PEP 621 [project.dependencies]
    for dep_str in data.get("project", {}).get("dependencies", []):
        name, ver = _split_pep508(dep_str)
        if name:
            deps.append(Dependency(
                name=name, declared_version=ver,
                constraint_type=_classify_constraint(ver),
                ecosystem="python", is_dev=False,
            ))
    # PEP 621 [project.optional-dependencies.*]
    for group, dep_list in data.get("project", {}).get("optional-dependencies", {}).items():
        is_dev = group in ("dev", "test", "tests", "lint", "docs", "typing")
        for dep_str in dep_list:
            name, ver = _split_pep508(dep_str)
            if name:
                deps.append(Dependency(
                    name=name, declared_version=ver,
                    constraint_type=_classify_constraint(ver),
                    ecosystem="python", is_dev=is_dev,
                ))
    # Poetry [tool.poetry.dependencies]
    poetry = data.get("tool", {}).get("poetry", {})
    for name, spec in poetry.get("dependencies", {}).items():
        if name == "python":
            continue
        ver = spec if isinstance(spec, str) else spec.get("version", "")
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="python", is_dev=False,
        ))
    # Poetry [tool.poetry.group.*.dependencies] OR legacy [tool.poetry.dev-dependencies]
    for grp_name, grp in poetry.get("group", {}).items():
        is_dev = grp_name in ("dev", "test", "tests", "lint", "docs", "typing")
        for name, spec in grp.get("dependencies", {}).items():
            if name == "python":
                continue
            ver = spec if isinstance(spec, str) else spec.get("version", "")
            deps.append(Dependency(
                name=name, declared_version=ver,
                constraint_type=_classify_constraint(ver),
                ecosystem="python", is_dev=is_dev,
            ))
    for name, spec in poetry.get("dev-dependencies", {}).items():
        ver = spec if isinstance(spec, str) else spec.get("version", "")
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="python", is_dev=True,
        ))

    # Lockfile detection (poetry.lock alongside)
    lockfile = path.parent / "poetry.lock"
    has_lock = lockfile.is_file()
    if has_lock:
        deps.extend(_parse_poetry_lock(lockfile, declared=[d.name for d in deps]))

    return Manifest(path=path, ecosystem="python", deps=tuple(deps),
                    has_lockfile=has_lock,
                    lockfile_path=lockfile if has_lock else None)


def _split_pep508(dep_str: str) -> tuple:
    """Crude PEP 508 split. Returns (name, version_specifier)."""
    s = dep_str.strip()
    # Strip extras: "requests[security]" → "requests"
    m = re.match(r"^([a-zA-Z0-9_\-\.]+)(\[[^\]]+\])?(.*)$", s)
    if not m:
        return ("", "")
    name = m.group(1)
    rest = (m.group(3) or "").strip()
    # Strip markers: ";python_version >= '3.10'"
    rest = rest.split(";", 1)[0].strip()
    return (name, rest)


def _parse_poetry_lock(path: Path, declared: list) -> list:
    """Parse poetry.lock for transitive deps (direct + first-level)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    out = []
    declared_set = set(declared)
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if not name:
            continue
        # If name is in declared, it's direct (handled by manifest parse); skip.
        # If not declared, it's transitive (depth ≥1).
        if name in declared_set:
            continue
        out.append(Dependency(
            name=name, declared_version=version,
            constraint_type="exact",
            ecosystem="python", is_dev=False,
            is_transitive=True, transitive_depth=1, parent_chain=(),
        ))
    return out


def _parse_requirements_txt(path: Path) -> Manifest:
    """Parse requirements*.txt. Lockfile-free; everything is direct."""
    deps: list = []
    is_dev = "dev" in path.name.lower() or "test" in path.name.lower()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name, ver = _split_pep508(line)
            if name:
                deps.append(Dependency(
                    name=name, declared_version=ver,
                    constraint_type=_classify_constraint(ver),
                    ecosystem="python", is_dev=is_dev,
                ))
    except OSError:
        pass
    return Manifest(path=path, ecosystem="python", deps=tuple(deps),
                    has_lockfile=False, lockfile_path=None)


def _parse_package_json(path: Path) -> Manifest:
    """Parse package.json. Handles workspaces."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Manifest(path=path, ecosystem="js", deps=tuple(),
                        has_lockfile=False, lockfile_path=None)
    deps: list = []
    for name, ver in (data.get("dependencies") or {}).items():
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="js", is_dev=False,
        ))
    for name, ver in (data.get("devDependencies") or {}).items():
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="js", is_dev=True,
        ))
    for name, ver in (data.get("optionalDependencies") or {}).items():
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="js", is_dev=False,
        ))

    # Lockfile detection (package-lock.json v3, yarn.lock, pnpm-lock.yaml)
    lock_candidates = [
        path.parent / "package-lock.json",
        path.parent / "yarn.lock",
        path.parent / "pnpm-lock.yaml",
    ]
    lockfile = next((p for p in lock_candidates if p.is_file()), None)
    if lockfile:
        if lockfile.name == "package-lock.json":
            deps.extend(_parse_package_lock_json(lockfile,
                                                 declared=[d.name for d in deps]))

    return Manifest(path=path, ecosystem="js", deps=tuple(deps),
                    has_lockfile=bool(lockfile), lockfile_path=lockfile)


def _parse_package_lock_json(path: Path, declared: list) -> list:
    """Parse package-lock.json v3 for first-level transitive deps."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out = []
    declared_set = set(declared)
    # v3: top-level "packages" object keyed by path
    packages = data.get("packages", {})
    for path_key, info in packages.items():
        if path_key == "":  # root project itself
            continue
        # path_key like "node_modules/foo" or "node_modules/@scope/bar"
        name = "/".join(path_key.split("node_modules/")[-1].split("/"))
        if not name or name in declared_set:
            continue
        version = info.get("version", "")
        out.append(Dependency(
            name=name, declared_version=version,
            constraint_type="exact", ecosystem="js", is_dev=info.get("dev", False),
            is_transitive=True, transitive_depth=1,
        ))
    return out


def _parse_cargo_toml(path: Path) -> Manifest:
    """Parse Cargo.toml. Handles [workspace] members and direct deps."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return Manifest(path=path, ecosystem="rust", deps=tuple(),
                        has_lockfile=False, lockfile_path=None)
    deps: list = []
    for name, spec in (data.get("dependencies") or {}).items():
        ver = spec if isinstance(spec, str) else spec.get("version", "")
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="rust", is_dev=False,
        ))
    for name, spec in (data.get("dev-dependencies") or {}).items():
        ver = spec if isinstance(spec, str) else spec.get("version", "")
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="rust", is_dev=True,
        ))
    # Workspace deps (Cargo workspace inheritance)
    ws = data.get("workspace", {})
    for name, spec in (ws.get("dependencies") or {}).items():
        ver = spec if isinstance(spec, str) else spec.get("version", "")
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="rust", is_dev=False,
            workspace_root=path.parent,
        ))

    lockfile = path.parent / "Cargo.lock"
    has_lock = lockfile.is_file()
    if has_lock:
        deps.extend(_parse_cargo_lock(lockfile, declared=[d.name for d in deps]))
    return Manifest(path=path, ecosystem="rust", deps=tuple(deps),
                    has_lockfile=has_lock,
                    lockfile_path=lockfile if has_lock else None)


def _parse_cargo_lock(path: Path, declared: list) -> list:
    """Parse Cargo.lock for transitive deps."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    out = []
    declared_set = set(declared)
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if not name or name in declared_set:
            continue
        out.append(Dependency(
            name=name, declared_version=version, constraint_type="exact",
            ecosystem="rust", is_dev=False,
            is_transitive=True, transitive_depth=1,
        ))
    return out


def _parse_go_mod(path: Path) -> Manifest:
    """Parse go.mod (simple line-based parser)."""
    deps: list = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return Manifest(path=path, ecosystem="go", deps=tuple(),
                        has_lockfile=False, lockfile_path=None)
    # Parse `require (...)` blocks and standalone `require foo v1.2.3` lines
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("require ("):
            in_block = True
            continue
        if in_block and s == ")":
            in_block = False
            continue
        if in_block:
            # Inside block: just "name version" with optional "// indirect"
            parts = s.split("//", 1)[0].split()
            if len(parts) >= 2:
                deps.append(Dependency(
                    name=parts[0], declared_version=parts[1],
                    constraint_type="exact",
                    ecosystem="go", is_dev=False,
                    is_transitive="// indirect" in line,
                    transitive_depth=1 if "// indirect" in line else 0,
                ))
        elif s.startswith("require "):
            parts = s[len("require "):].split("//", 1)[0].split()
            if len(parts) >= 2:
                deps.append(Dependency(
                    name=parts[0], declared_version=parts[1],
                    constraint_type="exact",
                    ecosystem="go", is_dev=False,
                ))

    lockfile = path.parent / "go.sum"
    return Manifest(path=path, ecosystem="go", deps=tuple(deps),
                    has_lockfile=lockfile.is_file(),
                    lockfile_path=lockfile if lockfile.is_file() else None)


def _parse_gemfile(path: Path) -> Manifest:
    """Parse Gemfile (line-based; gem 'name', '~> 1.2'). Lockfile rich, deferred."""
    deps: list = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return Manifest(path=path, ecosystem="ruby", deps=tuple(),
                        has_lockfile=False, lockfile_path=None)
    is_dev_group = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("group ") and ("dev" in s or "test" in s):
            is_dev_group = True
        elif s == "end":
            is_dev_group = False
        elif s.startswith("gem "):
            # gem 'foo', '~> 1.2.3'
            m = re.match(r"gem\s+['\"]([^'\"]+)['\"]\s*(?:,\s*['\"]([^'\"]+)['\"])?",
                         s)
            if m:
                name = m.group(1)
                version = m.group(2) or ""
                deps.append(Dependency(
                    name=name, declared_version=version,
                    constraint_type=_classify_constraint(version),
                    ecosystem="ruby", is_dev=is_dev_group,
                ))

    lockfile = path.parent / "Gemfile.lock"
    return Manifest(path=path, ecosystem="ruby", deps=tuple(deps),
                    has_lockfile=lockfile.is_file(),
                    lockfile_path=lockfile if lockfile.is_file() else None)


def _parse_pom_xml(path: Path) -> Manifest:
    """Parse pom.xml — minimal stdlib XML parsing."""
    import xml.etree.ElementTree as ET  # stdlib
    deps: list = []
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
    except (ET.ParseError, OSError):
        return Manifest(path=path, ecosystem="java", deps=tuple(),
                        has_lockfile=False, lockfile_path=None)
    # Strip namespace for simpler XPath
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag[: root.tag.index("}") + 1]
    for dep in root.iter(f"{ns}dependency"):
        group = dep.find(f"{ns}groupId")
        artifact = dep.find(f"{ns}artifactId")
        version = dep.find(f"{ns}version")
        scope = dep.find(f"{ns}scope")
        if group is None or artifact is None:
            continue
        name = f"{group.text}:{artifact.text}"
        ver = version.text if version is not None else ""
        is_dev = scope is not None and scope.text in ("test", "provided")
        deps.append(Dependency(
            name=name, declared_version=ver or "",
            constraint_type=_classify_constraint(ver or ""),
            ecosystem="java", is_dev=is_dev,
        ))
    return Manifest(path=path, ecosystem="java", deps=tuple(deps),
                    has_lockfile=False, lockfile_path=None)


def _parse_build_gradle(path: Path) -> Manifest:
    """Parse build.gradle / build.gradle.kts — regex-based; tolerant."""
    deps: list = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return Manifest(path=path, ecosystem="java", deps=tuple(),
                        has_lockfile=False, lockfile_path=None)
    # implementation 'group:artifact:version'  OR  implementation("group:artifact:version")
    pattern = re.compile(
        r"""(?P<scope>implementation|api|compile|testImplementation|"""
        r"""runtimeOnly|compileOnly|annotationProcessor)\s*\(?['"]"""
        r"""(?P<group>[^'":]+):(?P<artifact>[^'":]+):(?P<version>[^'"]+)['"]"""
    )
    for m in pattern.finditer(text):
        scope = m.group("scope")
        name = f"{m.group('group')}:{m.group('artifact')}"
        ver = m.group("version")
        is_dev = scope.startswith("test") or scope in ("compileOnly",)
        deps.append(Dependency(
            name=name, declared_version=ver,
            constraint_type=_classify_constraint(ver),
            ecosystem="java", is_dev=is_dev,
        ))
    return Manifest(path=path, ecosystem="java", deps=tuple(deps),
                    has_lockfile=False, lockfile_path=None)


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def detect_manifests(project_root: Path) -> list:
    """Walk project_root (gitignore-aware), parse every recognized manifest
    + lockfile. Returns list[Manifest]."""
    project_root = project_root.resolve()
    if not project_root.is_dir():
        return []
    out: list = []
    requirements_re = re.compile(r"^requirements[^/]*\.txt$")
    for p in _walk_for_manifests(project_root):
        try:
            if p.name == "pyproject.toml":
                out.append(_parse_pyproject_toml(p))
            elif requirements_re.match(p.name):
                out.append(_parse_requirements_txt(p))
            elif p.name == "package.json":
                out.append(_parse_package_json(p))
            elif p.name == "Cargo.toml":
                out.append(_parse_cargo_toml(p))
            elif p.name == "go.mod":
                out.append(_parse_go_mod(p))
            elif p.name == "Gemfile":
                out.append(_parse_gemfile(p))
            elif p.name == "pom.xml":
                out.append(_parse_pom_xml(p))
            elif p.name in ("build.gradle", "build.gradle.kts"):
                out.append(_parse_build_gradle(p))
            # Pipfile / setup.py / setup.cfg: deferred to v1.1 (less common)
        except Exception:
            # Best-effort parsing — never crash the whole walk
            continue
    return out
