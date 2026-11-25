#!/usr/bin/env python3
"""intake_fetch.py -- safe acquisition for intake scanning (#350).

A git URL, a local folder or a zip becomes ONE quarantined tar plus a full inventory:

    <quarantine root>/<bundle id>/source.tar       mode 0600, regular files only
    <quarantine root>/<bundle id>/inventory.json   mode 0600

The quarantine root is `~/.foundry/quarantine` unless the `quarantine_root` argument or
the FOUNDRY_QUARANTINE_ROOT environment variable names another directory. Nothing is ever
unpacked into the repo, and nothing from the target is checked out, built or executed.

    git URL   `git clone --bare` under an isolated configuration (no system or global
              config, hooks path on the null device, no submodule recursion, the LFS filter
              emptied, https the only protocol, no prompt), bounded by time and by size on
              disk. Files are exported by reading raw blobs with `git cat-file --batch`
              from the resolved commit's tree. There is no checkout and no `git archive`,
              so export attributes, filters and hooks in the target have no effect.
    folder    walked without following a symlink, bounded by count, depth and size.
    zip       refused as a whole on any traversal, absolute path, link, device or special
              entry, encrypted entry, duplicate or case-colliding name, nested archive,
              size cap or compression-ratio cap. Every refusal is recorded with its reason.

WHAT IS STORED AND WHAT IS ONLY RECORDED. Every entry of the target gets a row in the
inventory `files` list: path, mode, entry kind, size and SHA-256. Only regular files with a
safe, unambiguous path under the per-file size cap are stored in the tar. Everything else
(a symlink, a submodule entry, a device, an oversize file, an unsafe or colliding path, a
version-control directory such as `.git` or the file that points at one, every file under
a directory that has the LAYOUT of a git repository whatever its name) is recorded with
`stored: false` and listed again under `omissions` with its reason. It is never followed,
fetched or opened (a folder's files are read once, to record their digest). An LFS pointer is an ordinary small file: it is stored
as the pointer text and flagged `lfs_pointer`; the object it names is never fetched.

`iter_bundle_entries()` gives a later stage the file set in the field order of the rule
set's file record (id, path, mode, data, entry, size), with every omitted entry shaped so
that the size and entry-kind rule sees it. This module does not import the rule set.

FAILURE. `fetch()` does not raise for an expected failure. It returns a `FetchResult` with
`ok` false and a named `gap`, and it leaves no bundle and no staging directory behind.
The gap's `rejections` (paths) and `diagnostic` (git's stderr) are text chosen by the
target or the remote: a caller stores them in the quarantine report and prints only the
gap name and the reason codes.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unicodedata
import zipfile
import zlib
from typing import Any, Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import urlsplit

SCHEMA = "intake-inventory.v1"
QUARANTINE_ENV = "FOUNDRY_QUARANTINE_ROOT"
TAR_NAME = "source.tar"
INVENTORY_NAME = "inventory.json"

SOURCE_GIT = "git"
SOURCE_FOLDER = "folder"
SOURCE_ZIP = "zip"

# Entry kinds. The same strings as the rule set's entry kinds (a test holds them equal).
ENTRY_FILE = "file"
ENTRY_SYMLINK = "symlink"
ENTRY_DEVICE = "device"
ENTRY_GITLINK = "gitlink"
ENTRY_OTHER = "other"

# The one protocol a git target may use. Relaxed only by fetch(test_only_protocols=...).
ALLOWED_PROTOCOLS: Tuple[str, ...] = ("https",)

# The git executable. A module attribute so a test can point it at a stand-in.
GIT = "git"

# Gap names: the reason a fetch produced no bundle.
GAP_TARGET_NOT_FOUND = "target-not-found"
GAP_TARGET_TYPE = "target-type-unknown"
GAP_PROTOCOL = "protocol-not-allowed"
GAP_URL = "url-not-accepted"
GAP_REF = "ref-not-accepted"
GAP_GIT_UNAVAILABLE = "git-unavailable"
GAP_CLONE_FAILED = "git-clone-failed"
GAP_CLONE_TIMEOUT = "git-clone-timeout"
GAP_CLONE_SIZE = "git-clone-over-size-cap"
GAP_REF_NOT_FOUND = "git-ref-not-found"
GAP_GIT_READ = "git-read-failed"
GAP_ARCHIVE_UNREADABLE = "archive-unreadable"
GAP_ARCHIVE_REJECTED = "archive-rejected"
GAP_OVER_CAP = "over-cap"
GAP_FOLDER_UNREADABLE = "folder-unreadable"
GAP_QUARANTINE = "quarantine-unwritable"
GAP_INTERNAL = "internal-error"

# Reason codes: why one entry was not stored, or why an archive was refused.
R_SYMLINK = "symlink-not-followed"
R_GITLINK = "submodule-not-fetched"
R_DEVICE = "device-entry"
R_SPECIAL = "special-file"
R_OVERSIZE = "file-over-size-cap"
R_TRAVERSAL = "path-traversal"
R_ABSOLUTE = "absolute-path"
R_CONTROL = "control-character"
R_BACKSLASH = "backslash-in-path"
R_MALFORMED = "malformed-path"
R_EMPTY = "empty-name"
R_TOO_LONG = "path-too-long"
R_NOT_UTF8 = "path-not-utf8"
R_DUPLICATE = "duplicate-name"
R_CASE = "case-colliding-name"
R_CONFLICT = "file-directory-conflict"
R_UNREADABLE = "unreadable"
R_CHANGED = "changed-during-read"
R_OBJECT = "git-object-unreadable"
R_VCS_DIR = "vcs-directory-skipped"
R_VCS_PATH = "vcs-control-path"
R_VCS_LAYOUT = "vcs-repository-layout"
R_TOO_DEEP = "directory-too-deep"
R_NESTED = "nested-archive"
R_ENCRYPTED = "encrypted-entry"
R_RATIO = "compression-ratio-over-cap"
R_TOTAL = "total-over-size-cap"
R_COUNT = "too-many-entries"
R_MISMATCH = "size-mismatch"
R_ENTRY_UNREADABLE = "unreadable-entry"
R_OVERLAP = "overlapping-entries"


class Limits(NamedTuple):
    max_files: int = 20000
    max_file_bytes: int = 5 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_archive_bytes: int = 256 * 1024 * 1024    # the zip file itself
    max_ratio: int = 100                          # uncompressed bytes per compressed byte
    ratio_floor_bytes: int = 1024 * 1024          # the ratio is not judged below this size
    max_clone_bytes: int = 512 * 1024 * 1024      # the bare clone on disk
    clone_timeout_s: float = 300.0
    read_timeout_s: float = 300.0
    max_depth: int = 64
    max_path_chars: int = 1024
    max_rejections: int = 200


DEFAULT_LIMITS = Limits()


class FetchResult(NamedTuple):
    ok: bool
    bundle_id: Optional[str]
    bundle_dir: Optional[str]
    tar_path: Optional[str]
    inventory_path: Optional[str]
    inventory: Optional[Dict[str, Any]]
    gap: Optional[Dict[str, Any]]


class BundleEntry(NamedTuple):
    """One inventory row with its content, in the rule set's file-record field order."""
    file_id: str
    path: str
    mode: int
    data: bytes
    entry: str = ENTRY_FILE
    size: Optional[int] = None


class BundleError(Exception):
    """A bundle on disk does not match its inventory (missing, altered or malformed)."""


class _Gap(Exception):
    def __init__(self, name: str, detail: str, *, rejections: Optional[List[Dict[str, str]]] = None,
                 diagnostic: str = "", internal: bool = False) -> None:
        super().__init__(name)
        self.name = name
        self.detail = detail
        self.rejections = rejections or []
        self.diagnostic = diagnostic
        self.internal = internal

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"gap": self.name, "detail": self.detail, "internal": self.internal}
        if self.rejections:
            out["rejections"] = self.rejections
            out["reasons"] = sorted({r["reason"] for r in self.rejections})
        if self.diagnostic:
            out["diagnostic"] = self.diagnostic
        return out


class _Entry:
    __slots__ = ("path", "mode", "entry", "size", "sha256", "omit", "extra", "handle")

    def __init__(self, path: str, mode: int, entry: str, size: int = 0, handle: Any = None) -> None:
        self.path = path
        self.mode = mode
        self.entry = entry
        self.size = size
        self.sha256 = ""
        self.omit: Optional[str] = None
        self.extra: Dict[str, Any] = {}
        self.handle = handle


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------

_DRIVE = re.compile(r"^[A-Za-z]:")
_HEX_REF = re.compile(r"^[0-9a-fA-F]{7,64}$")
_REF_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}$")
_OID = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_SCP_LIKE = re.compile(r"^[^/\\:]+:[^\\]")
_LFS_PREFIX = b"version https://git-lfs.github.com/spec/"
_ARCHIVE_EXT = (".zip", ".tar", ".tgz", ".tar.gz", ".gz", ".bz2", ".tbz2", ".xz", ".txz",
                ".7z", ".rar", ".jar", ".war", ".whl", ".egg", ".zst", ".lz4", ".cab")
_ARCHIVE_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00",
                  b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07", b"\x28\xb5\x2f\xfd")
_LINK_TARGET_MAX = 4096
# Version-control directories whose config the tool honours as soon as it is started inside
# them (and, for git, the file that points at one). The same test as the rule set's
# `vcs_control_path`; this module does not import the rule set, and a test holds the two equal.
_VCS_NAMES = frozenset({".git", ".hg", ".svn", "git~1", ".bzr", ".jj", ".sl", "_darcs"})
_VCS_IGNORABLE = {code: None for span in ((0x200c, 0x200f), (0x202a, 0x202e), (0x206a, 0x206f),
                                          (0xfeff, 0xfeff))
                  for code in range(span[0], span[1] + 1)}
_CHUNK = 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_id(index: int) -> str:
    return "f%03d" % index


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _display(raw: Any) -> str:
    """A path or message made safe to store: printable ASCII, everything else escaped."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "backslashreplace")
    out = []
    for ch in str(raw):
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif 32 <= code < 127:
            out.append(ch)
        elif code < 0x10000:
            out.append("\\u%04x" % code)
        else:
            out.append("\\U%08x" % code)
    return "".join(out)[:2048]


def _path_problem(path: str, max_chars: int = DEFAULT_LIMITS.max_path_chars) -> Optional[str]:
    """The reason a stored path is unsafe, or None. `path` uses "/" separators."""
    if path == "":
        return R_EMPTY
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        return R_CONTROL
    norm = path.replace("\\", "/")
    if norm.startswith("/") or _DRIVE.match(norm):
        return R_ABSOLUTE
    parts = norm.split("/")
    if ".." in parts:
        return R_TRAVERSAL
    if "\\" in path:
        return R_BACKSLASH
    if "" in parts or "." in parts:
        return R_MALFORMED
    if len(path) > max_chars or any(len(p.encode("utf-8", "replace")) > 255 for p in parts):
        return R_TOO_LONG
    return None


def _vcs_fold(name: str) -> str:
    return name.translate(_VCS_IGNORABLE).casefold().split(":", 1)[0].rstrip(". ")


def _vcs_name(name: str) -> bool:
    return _vcs_fold(name) in _VCS_NAMES


def is_vcs_path(path: str) -> bool:
    """True when a component of `path` names a version-control directory or pointer file,
    compared the way a case-insensitive file system would. Such a path is never stored."""
    return any(_vcs_name(part) for part in path.replace("\\", "/").split("/"))


def _layout_parts(path: str) -> List[str]:
    return [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]


def repo_layout_dirs(paths: Iterable[str]) -> "frozenset[str]":
    """The directories of a file set that have the shape of a git repository, as folded
    "/"-joined paths ("" is the root). Git takes a directory for a repository by what it
    holds, whatever it is called: `HEAD` beside `objects` and `refs`, or beside a
    `commondir` file that says where those are. `HEAD` beside `config`, and `objects`,
    `refs` and `config` together, count too. The same test as the rule set's
    `repo_layout_dirs` (a test holds the two equal)."""
    children: Dict[str, set] = {}
    for path in paths:
        prefix = ""
        for part in _layout_parts(path):
            name = _vcs_fold(part)
            children.setdefault(prefix, set()).add(name)
            prefix = prefix + "/" + name if prefix else name
    found = set()
    for directory, names in children.items():
        if "head" in names:
            hit = ("objects" in names and "refs" in names) or "config" in names or "commondir" in names
        else:
            hit = "objects" in names and "refs" in names and "config" in names
        if hit:
            found.add(directory)
    return frozenset(found)


def in_repo_layout(path: str, dirs: "frozenset[str]") -> bool:
    """True when `path` is a file somewhere under one of `dirs`. Such a file is never stored."""
    if not dirs:
        return False
    if "" in dirs:
        return True
    prefix = ""
    for part in _layout_parts(path)[:-1]:
        name = _vcs_fold(part)
        prefix = prefix + "/" + name if prefix else name
        if prefix in dirs:
            return True
    return False


def _omit_repo_layouts(entries: List["_Entry"], extra_paths: Sequence[str] = ()) -> None:
    """Mark every file under a directory with the layout of a repository as not stored.
    `extra_paths` are names that count toward the layout and are not entries themselves
    (a zip's directory entries)."""
    dirs = repo_layout_dirs([e.path for e in entries] + list(extra_paths))
    if not dirs:
        return
    for entry in entries:
        if in_repo_layout(entry.path, dirs):
            entry.extra.setdefault("path_problem", R_VCS_LAYOUT)
            if entry.entry == ENTRY_FILE and entry.omit is None:
                entry.omit = R_VCS_LAYOUT


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold())


class _Namespace:
    """Tracks accepted paths so a duplicate, a case collision or a file-directory clash
    is caught wherever in the path it occurs. A refused path registers nothing."""

    def __init__(self) -> None:
        self._files: set = set()
        self._dirs: set = set()
        self._spelling: Dict[str, str] = {}

    def add(self, path: str, is_dir: bool = False) -> Optional[str]:
        parts = path.split("/")
        prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
        if not is_dir and path in self._files:
            return R_DUPLICATE
        for prefix in prefixes:
            known = self._spelling.get(_fold(prefix))
            if known is not None and known != prefix:
                return R_CASE
        if any(prefix in self._files for prefix in prefixes[:-1]):
            return R_CONFLICT
        if is_dir and path in self._files:
            return R_CONFLICT
        if not is_dir and path in self._dirs:
            return R_CONFLICT
        for prefix in prefixes:
            self._spelling[_fold(prefix)] = prefix
        self._dirs.update(prefixes[:-1])
        if is_dir:
            self._dirs.add(path)
        else:
            self._files.add(path)
        return None


def _is_archive(name: str, data: bytes) -> bool:
    if name.lower().endswith(_ARCHIVE_EXT):
        return True
    if data.startswith(_ARCHIVE_MAGIC):
        return True
    return data[257:262] == b"ustar"


def _link_escapes(link_path: str, target: str) -> bool:
    """True when a link's target is absolute or resolves (lexically) outside the tree."""
    norm = target.replace("\\", "/")
    if norm.startswith("/") or _DRIVE.match(norm):
        return True
    depth = link_path.count("/")
    for part in norm.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def resolve_quarantine_root(override: Optional[str] = None) -> str:
    """The quarantine root: the argument, else FOUNDRY_QUARANTINE_ROOT, else ~/.foundry/quarantine."""
    chosen = override or os.environ.get(QUARANTINE_ENV)
    if chosen:
        return os.path.abspath(os.path.expanduser(str(chosen)))
    return os.path.join(os.path.expanduser("~"), ".foundry", "quarantine")


# --------------------------------------------------------------------------------------
# Target classification
# --------------------------------------------------------------------------------------

def target_scheme(target: str) -> Optional[str]:
    """The transport a non-local target names ("https", "ssh", "ext", ...), or None."""
    if "://" in target or "::" in target:
        return target.split(":", 1)[0].lower()
    if _SCP_LIKE.match(target) and not _DRIVE.match(target):
        return "ssh"
    return None


def classify_target(target: str) -> Optional[str]:
    """"git", "folder" or "zip" for a target string; None when it is none of them.

    An existing local path is always read as local. Anything that names a transport is a
    git target, whether or not the transport is allowed (fetch() refuses the others).
    """
    if not isinstance(target, str) or not target or "\x00" in target:
        return None
    if os.path.lexists(target):
        if os.path.isdir(target):
            return SOURCE_FOLDER
        if os.path.isfile(target) and zipfile.is_zipfile(target):
            return SOURCE_ZIP
        return None
    if target_scheme(target) is not None:
        return SOURCE_GIT
    return None


def _check_url(url: str, protocols: Sequence[str]) -> None:
    scheme = target_scheme(url)
    if scheme not in protocols or "::" in url.split("://", 1)[0] or "://" not in url:
        raise _Gap(GAP_PROTOCOL, "only these protocols are accepted: %s" % ", ".join(protocols))
    if (len(url) > 2048 or url.startswith("-") or not url.isascii()
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
        raise _Gap(GAP_URL, "the URL has a space, a control or non-ASCII character, or is too long")
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 -- raises ValueError on a malformed port
    except ValueError:
        raise _Gap(GAP_URL, "the URL does not parse")
    if "@" in parts.netloc:
        raise _Gap(GAP_URL, "the URL carries credentials")
    if scheme != "file" and not parts.hostname:
        raise _Gap(GAP_URL, "the URL names no host")


# --------------------------------------------------------------------------------------
# Git: isolated configuration and bounded execution
# --------------------------------------------------------------------------------------

def git_env(home: str) -> Dict[str, str]:
    """The environment every git process runs in. Built from nothing: no GIT_* variable of
    the caller (GIT_DIR, GIT_CONFIG_*, a pre-commit hook's GIT_INDEX_FILE) is inherited."""
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": home,
        "XDG_CONFIG_HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GCM_INTERACTIVE": "never",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "LC_ALL": "C",
        "LANG": "C",
    }
    for name in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR",
                 "https_proxy", "HTTPS_PROXY", "no_proxy", "NO_PROXY", "all_proxy", "ALL_PROXY",
                 "SSL_CERT_FILE", "SSL_CERT_DIR", "GIT_SSL_CAINFO", "GIT_SSL_CAPATH", "CURL_CA_BUNDLE"):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def git_config_args(protocols: Sequence[str] = ALLOWED_PROTOCOLS) -> List[str]:
    """The `-c` settings every git process carries: nothing of the target's is honoured."""
    settings = [
        "core.hooksPath=" + os.devnull,
        "core.attributesFile=" + os.devnull,
        "core.fsmonitor=false",
        "core.symlinks=false",
        "core.askPass=",
        "credential.helper=",
        "submodule.recurse=false",
        "fetch.recurseSubmodules=false",
        "filter.lfs.smudge=",
        "filter.lfs.clean=",
        "filter.lfs.process=",
        "filter.lfs.required=false",
        "transfer.fsckObjects=true",
        "gc.auto=0",
        "maintenance.auto=false",
        "advice.detachedHead=false",
        "protocol.allow=never",
    ]
    settings.extend("protocol.%s.allow=always" % p for p in protocols)
    args: List[str] = []
    for setting in settings:
        args.extend(["-c", setting])
    return args


def git_clone_argv(url: str, dest: str, ref: Optional[str] = None,
                   protocols: Sequence[str] = ALLOWED_PROTOCOLS) -> List[str]:
    """The one command that talks to the remote. Bare, never a working tree."""
    argv = [GIT] + git_config_args(protocols) + [
        "clone", "--bare", "--quiet", "--no-recurse-submodules", "--template="]
    if ref is None:
        argv += ["--depth", "1", "--single-branch", "--no-tags"]
    elif _HEX_REF.match(ref):
        pass        # a commit id cannot be asked for by name: take the history, resolve after
    else:
        argv += ["--depth", "1", "--single-branch", "--no-tags", "--branch", ref]
    return argv + ["--", url, dest]


def _spawn(argv: List[str], **kwargs: Any) -> "subprocess.Popen[bytes]":
    """Every git process starts here (a test replaces this to see each command)."""
    return subprocess.Popen(argv, **kwargs)


def _kill(proc: "subprocess.Popen[bytes]") -> None:
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(proc.pid), 9)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _session_kwargs() -> Dict[str, Any]:
    return {"start_new_session": True} if os.name == "posix" else {}


def _dir_bytes(path: str) -> int:
    total = 0
    for base, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def _tail(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return _display(fh.read()[-600:].strip())
    except OSError:
        return ""


class _Git:
    """A bare clone in a private work directory, read with raw object commands only."""

    def __init__(self, work: str, protocols: Sequence[str], limits: Limits) -> None:
        self.work = work
        self.home = os.path.join(work, "home")
        self.cwd = os.path.join(work, "cwd")
        self.repo = os.path.join(work, "repo.git")
        self.err = os.path.join(work, "git.err")
        os.makedirs(self.home, 0o700)
        os.makedirs(self.cwd, 0o700)
        self.protocols = tuple(protocols)
        self.limits = limits
        self.env = git_env(self.home)
        self.last_rc = 0

    def _start(self, argv: List[str], stdin: Any, stdout: Any) -> "subprocess.Popen[bytes]":
        errfh = open(self.err, "wb")
        try:
            return _spawn(argv, stdin=stdin, stdout=stdout, stderr=errfh, env=self.env,
                          cwd=self.cwd, close_fds=True, **_session_kwargs())
        except FileNotFoundError:
            raise _Gap(GAP_GIT_UNAVAILABLE, "the git executable was not found")
        except OSError as exc:
            raise _Gap(GAP_GIT_UNAVAILABLE, "git could not be started (%s)" % type(exc).__name__)
        finally:
            errfh.close()

    def clone(self, url: str, ref: Optional[str]) -> None:
        argv = git_clone_argv(url, self.repo, ref, self.protocols)
        proc = self._start(argv, subprocess.DEVNULL, subprocess.DEVNULL)
        deadline = time.monotonic() + self.limits.clone_timeout_s
        while True:
            try:
                proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() >= deadline:
                _kill(proc)
                raise _Gap(GAP_CLONE_TIMEOUT, "the clone did not finish within %d seconds"
                           % int(self.limits.clone_timeout_s))
            if _dir_bytes(self.repo) > self.limits.max_clone_bytes:
                _kill(proc)
                raise _Gap(GAP_CLONE_SIZE, "the clone grew past %d bytes" % self.limits.max_clone_bytes)
        if proc.returncode != 0:
            raise _Gap(GAP_CLONE_FAILED, "git clone exited %d" % proc.returncode, diagnostic=_tail(self.err))
        if _dir_bytes(self.repo) > self.limits.max_clone_bytes:
            raise _Gap(GAP_CLONE_SIZE, "the clone is larger than %d bytes" % self.limits.max_clone_bytes)

    def _read_argv(self, *args: str) -> List[str]:
        return [GIT] + git_config_args(self.protocols) + ["--git-dir", self.repo] + list(args)

    @contextlib.contextmanager
    def stream(self, args: Sequence[str], stdin_path: Optional[str] = None,
               check: bool = True) -> Iterator[Any]:
        """Run one read command under a watchdog; yields its stdout."""
        fh = open(stdin_path, "rb") if stdin_path is not None else None
        timed_out: List[bool] = []
        proc: Any = None
        timer = None
        try:
            proc = self._start(self._read_argv(*args), fh if fh is not None else subprocess.DEVNULL,
                               subprocess.PIPE)

            def expire() -> None:
                timed_out.append(True)
                _kill(proc)

            timer = threading.Timer(self.limits.read_timeout_s, expire)
            timer.daemon = True
            timer.start()
            try:
                yield proc.stdout
            except _Gap:
                if timed_out:
                    raise _Gap(GAP_GIT_READ, "git %s timed out" % args[0]) from None
                raise
            proc.stdout.close()
            self.last_rc = proc.wait()
            if timed_out:
                raise _Gap(GAP_GIT_READ, "git %s timed out" % args[0])
            if check and self.last_rc != 0:
                raise _Gap(GAP_GIT_READ, "git %s exited %d" % (args[0], self.last_rc),
                           diagnostic=_tail(self.err))
        finally:
            if timer is not None:
                timer.cancel()
            if proc is not None:
                if proc.poll() is None:
                    _kill(proc)
                if proc.stdout is not None and not proc.stdout.closed:
                    proc.stdout.close()
            if fh is not None:
                fh.close()

    def output(self, *args: str, limit: int = 4096) -> Optional[bytes]:
        """The small output of one read command, or None when it fails."""
        with self.stream(args, check=False) as out:
            data = out.read(limit + 1)
        if self.last_rc != 0 or len(data) > limit:
            return None
        return data


def _read_exact(stream: Any, count: int) -> bytes:
    chunks = []
    left = count
    while left > 0:
        chunk = stream.read(min(left, _CHUNK))
        if not chunk:
            raise _Gap(GAP_GIT_READ, "git cat-file ended early")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def _hash_exact(stream: Any, count: int) -> str:
    digest = hashlib.sha256()
    left = count
    while left > 0:
        chunk = stream.read(min(left, _CHUNK))
        if not chunk:
            raise _Gap(GAP_GIT_READ, "git cat-file ended early")
        digest.update(chunk)
        left -= len(chunk)
    return digest.hexdigest()


def _git_listing(git: _Git, commit: str, limits: Limits) -> List[_Entry]:
    entries: List[_Entry] = []
    pending = b""
    with git.stream(["ls-tree", "-r", "-z", "--full-tree", commit]) as out:
        while True:
            chunk = out.read(_CHUNK)
            if not chunk:
                break
            pending += chunk
            records = pending.split(b"\x00")
            pending = records.pop()
            for record in records:
                meta, _tab, raw_path = record.partition(b"\t")
                fields = meta.split(b" ")
                if len(fields) != 3 or not _tab:
                    raise _Gap(GAP_GIT_READ, "git ls-tree wrote an unexpected line")
                git_mode = fields[0].decode("ascii", "replace")
                oid = fields[2].decode("ascii", "replace")
                if not _OID.match(oid):
                    raise _Gap(GAP_GIT_READ, "git ls-tree wrote an unexpected object id")
                try:
                    path = raw_path.decode("utf-8")
                    bad_name = None
                except UnicodeDecodeError:
                    path = _display(raw_path)
                    bad_name = R_NOT_UTF8
                if git_mode in ("100644", "100664"):
                    entry = _Entry(path, 0o644, ENTRY_FILE, handle=oid)
                elif git_mode == "100755":
                    entry = _Entry(path, 0o755, ENTRY_FILE, handle=oid)
                elif git_mode == "120000":
                    entry = _Entry(path, 0o777, ENTRY_SYMLINK, handle=oid)
                    entry.omit = R_SYMLINK
                elif git_mode == "160000":
                    entry = _Entry(path, 0, ENTRY_GITLINK)
                    entry.omit = R_GITLINK
                    entry.extra["gitlink_commit"] = oid
                else:
                    entry = _Entry(path, 0, ENTRY_OTHER)
                    entry.omit = R_SPECIAL
                entry.extra["git_mode"] = git_mode
                if bad_name:
                    entry.extra["bad_name"] = bad_name
                entries.append(entry)
                if len(entries) > limits.max_files:
                    raise _Gap(GAP_OVER_CAP, "the tree has more than %d entries" % limits.max_files,
                               rejections=[{"path": "(tree)", "reason": R_COUNT}])
    if pending:
        raise _Gap(GAP_GIT_READ, "git ls-tree output was cut short")
    return entries


def _git_sizes(git: _Git, entries: List[_Entry], limits: Limits) -> None:
    """Sizes from `cat-file --batch-check`, before any content is read."""
    wanted = [e for e in entries if e.handle]
    if not wanted:
        return
    oids = os.path.join(git.work, "oids-check.txt")
    with open(oids, "w", encoding="ascii", newline="\n") as fh:
        for entry in wanted:
            fh.write(entry.handle + "\n")
    total = 0
    with git.stream(["cat-file", "--batch-check"], stdin_path=oids) as out:
        for entry in wanted:
            line = out.readline(512).decode("ascii", "replace").split()
            if len(line) == 3 and line[0] == entry.handle and line[1] == "blob" and line[2].isdigit():
                entry.size = int(line[2])
                if entry.entry == ENTRY_FILE:
                    total += entry.size
            else:
                entry.handle = None
                entry.omit = entry.omit or R_OBJECT
                if entry.entry == ENTRY_FILE:
                    entry.entry = ENTRY_OTHER
    if total > limits.max_total_bytes:
        raise _Gap(GAP_OVER_CAP, "the tree holds more than %d bytes" % limits.max_total_bytes,
                   rejections=[{"path": "(tree)", "reason": R_TOTAL}])


def _git_read(git: _Git, entries: List[_Entry], limits: Limits,
              sink: Callable[[_Entry, bytes], None]) -> None:
    """Raw blobs from `cat-file --batch`, in listing order. No filter, no text conversion."""
    wanted = [e for e in entries if e.handle and (e.entry == ENTRY_FILE or e.size <= _LINK_TARGET_MAX)]
    if not wanted:
        return
    oids = os.path.join(git.work, "oids-read.txt")
    with open(oids, "w", encoding="ascii", newline="\n") as fh:
        for entry in wanted:
            fh.write(entry.handle + "\n")
    with git.stream(["cat-file", "--batch"], stdin_path=oids) as out:
        for entry in wanted:
            header = out.readline(512).decode("ascii", "replace").split()
            if len(header) != 3 or header[0] != entry.handle or header[1] != "blob" or header[2] != str(entry.size):
                raise _Gap(GAP_GIT_READ, "git cat-file wrote an unexpected header")
            if entry.entry == ENTRY_SYMLINK:
                target = _read_exact(out, entry.size)
                entry.sha256 = _sha256(target)
                entry.extra["link_target"] = _display(target)
                entry.extra["link_escapes"] = _link_escapes(entry.path, target.decode("utf-8", "replace"))
            elif entry.omit is None and entry.size <= limits.max_file_bytes:
                data = _read_exact(out, entry.size)
                entry.sha256 = _sha256(data)
                sink(entry, data)
            else:
                entry.sha256 = _hash_exact(out, entry.size)
            if out.read(1) != b"\n":
                raise _Gap(GAP_GIT_READ, "git cat-file wrote an unexpected separator")


def _collect_git(url: str, ref: Optional[str], work: str, protocols: Sequence[str], limits: Limits,
                 sink: Callable[[_Entry, bytes], None]) -> Tuple[Dict[str, Any], List[_Entry], List[Dict[str, str]]]:
    _check_url(url, protocols)
    if ref is not None and (not _REF_OK.match(ref) or ".." in ref or ref.endswith("/")):
        raise _Gap(GAP_REF, "the ref has a character or a shape that is not accepted")
    git = _Git(work, protocols, limits)
    git.clone(url, ref)
    spec = ref if (ref is not None and _HEX_REF.match(ref)) else "HEAD"
    commit_raw = git.output("rev-parse", "--verify", "--quiet", "--end-of-options", spec + "^{commit}")
    commit = (commit_raw or b"").decode("ascii", "replace").strip()
    if not _OID.match(commit):
        raise _Gap(GAP_REF_NOT_FOUND, "the ref does not name a commit (or the repository is empty)")
    tree_raw = git.output("rev-parse", "--verify", "--quiet", "--end-of-options", commit + "^{tree}")
    tree = (tree_raw or b"").decode("ascii", "replace").strip()
    if not _OID.match(tree):
        raise _Gap(GAP_GIT_READ, "the commit's tree could not be resolved")
    entries = _git_listing(git, commit, limits)
    entries.sort(key=lambda e: e.path)
    _apply_path_policy(entries, limits)
    _git_sizes(git, entries, limits)
    for entry in entries:
        if entry.entry == ENTRY_FILE and entry.omit is None and entry.size > limits.max_file_bytes:
            entry.omit = R_OVERSIZE
    _git_read(git, entries, limits, sink)
    source = {"type": SOURCE_GIT, "target": url, "ref": ref, "commit": commit, "git_tree": tree}
    return source, entries, []


# --------------------------------------------------------------------------------------
# Path policy shared by the git and folder sources
# --------------------------------------------------------------------------------------

def _apply_path_policy(entries: List[_Entry], limits: Limits) -> None:
    """Mark every entry whose path is unsafe or ambiguous as not stored. Entries must be
    sorted; the first spelling of a colliding name is the one that stays."""
    names = _Namespace()
    for entry in entries:
        problem = entry.extra.pop("bad_name", None) or _path_problem(entry.path, limits.max_path_chars)
        if problem is None and is_vcs_path(entry.path):
            problem = R_VCS_PATH
        if problem is None:
            problem = names.add(entry.path)
        if problem is not None:
            entry.extra["path_problem"] = problem
            if entry.entry == ENTRY_FILE:
                entry.omit = problem
    _omit_repo_layouts(entries)


# --------------------------------------------------------------------------------------
# Folder
# --------------------------------------------------------------------------------------

def _entry_name(name: str) -> Tuple[str, Optional[str]]:
    try:
        name.encode("utf-8")
        return name, None
    except UnicodeEncodeError:
        return _display(name.encode("utf-8", "surrogateescape")), R_NOT_UTF8


def _folder_listing(root: str, limits: Limits) -> Tuple[List[_Entry], List[Dict[str, str]]]:
    entries: List[_Entry] = []
    skipped: List[Dict[str, str]] = []
    stack: List[Tuple[str, str, int]] = [("", root, 0)]
    while stack:
        rel, full, depth = stack.pop()
        try:
            with os.scandir(full) as it:
                children = sorted(it, key=lambda e: e.name)
        except OSError:
            if rel == "":
                raise _Gap(GAP_FOLDER_UNREADABLE, "the folder could not be listed")
            unread = _Entry(rel, 0, ENTRY_OTHER)
            unread.omit = R_UNREADABLE
            entries.append(unread)
            continue
        for child in children:
            name, bad_name = _entry_name(child.name)
            relpath = rel + "/" + name if rel else name
            try:
                st = child.stat(follow_symlinks=False)
            except OSError:
                gone = _Entry(relpath, 0, ENTRY_OTHER)
                gone.omit = R_UNREADABLE
                entries.append(gone)
                continue
            mode = stat.S_IMODE(st.st_mode)
            if rel == "" and child.name == ".git" and (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                # The target's own checkout metadata, not part of what is taken in: a
                # directory, or the file a work tree or a submodule checkout has there.
                skipped.append({"path": ".git", "reason": R_VCS_DIR,
                                "entry": "directory" if stat.S_ISDIR(st.st_mode) else "file"})
                continue
            if stat.S_ISDIR(st.st_mode):
                if not bad_name and _vcs_name(name):
                    # Shipped inside the target: recorded as one entry and never walked.
                    shipped = _Entry(relpath, mode, ENTRY_OTHER)
                    shipped.omit = R_VCS_PATH
                    entries.append(shipped)
                elif bad_name or depth + 1 > limits.max_depth:
                    blocked = _Entry(relpath, mode, ENTRY_OTHER)
                    blocked.omit = bad_name or R_TOO_DEEP
                    entries.append(blocked)
                else:
                    stack.append((relpath, child.path, depth + 1))
                continue
            if stat.S_ISLNK(st.st_mode):
                entry = _Entry(relpath, 0o777, ENTRY_SYMLINK, handle=child.path)
                entry.omit = R_SYMLINK
            elif stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
                entry = _Entry(relpath, mode, ENTRY_DEVICE)
                entry.omit = R_DEVICE
            elif not stat.S_ISREG(st.st_mode):
                entry = _Entry(relpath, mode, ENTRY_OTHER)
                entry.omit = R_SPECIAL
            else:
                entry = _Entry(relpath, mode, ENTRY_FILE, st.st_size, handle=child.path)
            if bad_name:
                entry.extra["bad_name"] = bad_name
            entries.append(entry)
            if len(entries) > limits.max_files:
                raise _Gap(GAP_OVER_CAP, "the folder has more than %d entries" % limits.max_files,
                           rejections=[{"path": "(folder)", "reason": R_COUNT}])
    return entries, skipped


def _open_regular(path: str) -> Optional[int]:
    """Open a file for reading without following a link or blocking on a pipe; None when
    it is not (or is no longer) a regular file."""
    flags = os.O_RDONLY
    for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_BINARY", "O_CLOEXEC", "O_NOCTTY"):
        flags |= getattr(os, name, 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
    except OSError:
        os.close(fd)
        return None
    return fd


def _folder_read(entries: List[_Entry], limits: Limits, sink: Callable[[_Entry, bytes], None]) -> None:
    total = 0
    for entry in entries:
        if entry.entry == ENTRY_SYMLINK and entry.handle:
            try:
                target = os.readlink(entry.handle)
            except OSError:
                continue
            raw = target.encode("utf-8", "surrogateescape")
            entry.size = len(raw)
            entry.sha256 = _sha256(raw)
            entry.extra["link_target"] = _display(raw[:_LINK_TARGET_MAX])
            entry.extra["link_escapes"] = _link_escapes(entry.path, target)
            continue
        if entry.entry != ENTRY_FILE or not entry.handle:
            continue
        fd = _open_regular(entry.handle)
        if fd is None:
            entry.entry = ENTRY_OTHER
            entry.omit = R_CHANGED
            continue
        keep = entry.omit is None and entry.size <= limits.max_file_bytes
        digest = hashlib.sha256()
        chunks: List[bytes] = []
        seen = 0
        with os.fdopen(fd, "rb") as fh:
            while True:
                try:
                    chunk = fh.read(_CHUNK)
                except OSError:
                    entry.omit = R_UNREADABLE
                    keep = False
                    chunks = []
                    digest = None
                    break
                if not chunk:
                    break
                seen += len(chunk)
                total += len(chunk)
                assert digest is not None
                if total > limits.max_total_bytes:
                    raise _Gap(GAP_OVER_CAP, "the folder holds more than %d bytes" % limits.max_total_bytes,
                               rejections=[{"path": "(folder)", "reason": R_TOTAL}])
                digest.update(chunk)
                if keep and seen <= limits.max_file_bytes:
                    chunks.append(chunk)
                else:
                    keep = False
                    chunks = []
        entry.size = seen
        entry.sha256 = digest.hexdigest() if digest is not None else ""
        if entry.omit is None and not keep:
            entry.omit = R_OVERSIZE
        if entry.omit is None:
            sink(entry, b"".join(chunks))


def _collect_folder(target: str, limits: Limits,
                    sink: Callable[[_Entry, bytes], None]) -> Tuple[Dict[str, Any], List[_Entry], List[Dict[str, str]]]:
    root = os.path.realpath(target)
    entries, skipped = _folder_listing(root, limits)
    entries.sort(key=lambda e: e.path)
    _apply_path_policy(entries, limits)
    _folder_read(entries, limits, sink)
    source = {"type": SOURCE_FOLDER, "target": os.path.abspath(target), "ref": None, "commit": None,
              "git_tree": None}
    return source, entries, skipped


# --------------------------------------------------------------------------------------
# Zip
# --------------------------------------------------------------------------------------

def _central_directory_bytes(path: str) -> Optional[int]:
    """The declared size of a zip's central directory, read from its end record."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            span = min(size, 65536 + 22 + 20)
            fh.seek(size - span)
            tail = fh.read(span)
            at = tail.rfind(b"PK\x05\x06")
            if at < 0 or at + 22 > len(tail):
                return None
            declared = struct.unpack("<I", tail[at + 12:at + 16])[0]
            if declared != 0xFFFFFFFF:
                return declared
            loc = tail.rfind(b"PK\x06\x07", 0, at)
            if loc < 0 or loc + 20 > len(tail):
                return None
            offset = struct.unpack("<Q", tail[loc + 8:loc + 16])[0]
            fh.seek(offset)
            record = fh.read(56)
            if len(record) < 56 or record[:4] != b"PK\x06\x06":
                return None
            return struct.unpack("<Q", record[40:48])[0]
    except (OSError, struct.error):
        return None


def _zip_kind(info: zipfile.ZipInfo) -> Tuple[str, int]:
    """(entry kind, permission bits) of a zip member, from its unix mode when it has one."""
    unix = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(unix)
    perm = stat.S_IMODE(unix)
    if kind == stat.S_IFLNK:
        return ENTRY_SYMLINK, perm
    if kind in (stat.S_IFCHR, stat.S_IFBLK):
        return ENTRY_DEVICE, perm
    if kind in (stat.S_IFIFO, stat.S_IFSOCK):
        return ENTRY_OTHER, perm
    return ENTRY_FILE, perm


def _collect_zip(target: str, limits: Limits,
                 sink: Callable[[_Entry, bytes], None]) -> Tuple[Dict[str, Any], List[_Entry], List[Dict[str, str]]]:
    rejections: List[Dict[str, str]] = []

    def reject(path: Any, reason: str) -> None:
        if len(rejections) < limits.max_rejections:
            rejections.append({"path": _display(path), "reason": reason})

    def refuse() -> _Gap:
        return _Gap(GAP_ARCHIVE_REJECTED, "the archive was refused; nothing was extracted",
                    rejections=rejections)

    try:
        archive_size = os.path.getsize(target)
    except OSError:
        raise _Gap(GAP_ARCHIVE_UNREADABLE, "the archive could not be read")
    if archive_size > limits.max_archive_bytes:
        reject("(archive)", R_TOTAL)
        raise refuse()
    directory = _central_directory_bytes(target)
    if directory is not None and directory > limits.max_files * 512 + 65536:
        reject("(archive)", R_COUNT)
        raise refuse()
    try:
        zf = zipfile.ZipFile(target, "r")
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError, EOFError, struct.error):
        raise _Gap(GAP_ARCHIVE_UNREADABLE, "the archive is not a readable zip")
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_files:
            reject("(archive)", R_COUNT)
            raise refuse()
        names = _Namespace()
        entries: List[_Entry] = []
        directories: List[str] = []
        total = 0
        packed = 0
        for info in infos:
            raw_name = info.orig_filename
            is_dir = raw_name.endswith("/") or raw_name.endswith("\\")
            path = raw_name.rstrip("/") if is_dir else raw_name
            problem = _path_problem(path, limits.max_path_chars)
            if problem is None:
                problem = names.add(path, is_dir)
            if problem is not None:
                reject(raw_name, problem)
            kind, perm = _zip_kind(info)
            if kind != ENTRY_FILE:
                reject(raw_name, {ENTRY_SYMLINK: R_SYMLINK, ENTRY_DEVICE: R_DEVICE}.get(kind, R_SPECIAL))
            if info.flag_bits & 0x1:
                reject(raw_name, R_ENCRYPTED)
            if is_dir:
                directories.append(path)
                continue
            packed += info.compress_size
            total += info.file_size
            if info.file_size > limits.max_file_bytes:
                reject(raw_name, R_OVERSIZE)
            if (info.file_size > limits.ratio_floor_bytes
                    and info.file_size > max(info.compress_size, 1) * limits.max_ratio):
                reject(raw_name, R_RATIO)
            if path.lower().endswith(_ARCHIVE_EXT):
                reject(raw_name, R_NESTED)
            mode = 0o755 if (perm & 0o111) else 0o644
            entry = _Entry(path, mode, kind, info.file_size, handle=info)
            if problem is None and is_vcs_path(path):
                entry.omit = R_VCS_PATH        # recorded, never opened, never stored
            entries.append(entry)
        if total > limits.max_total_bytes:
            reject("(archive)", R_TOTAL)
        if total > limits.ratio_floor_bytes and total > max(packed, 1) * limits.max_ratio:
            reject("(archive)", R_RATIO)
        if packed > archive_size:
            reject("(archive)", R_OVERLAP)
        if rejections:
            raise refuse()

        entries.sort(key=lambda e: e.path)
        _omit_repo_layouts(entries, directories)     # recorded, never opened, never stored
        for entry in entries:
            if entry.omit is not None:
                continue
            info = entry.handle
            try:
                with zf.open(info, "r") as fh:
                    data = fh.read(info.file_size + 1)
            except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, OSError,
                    EOFError, ValueError, struct.error):
                reject(info.orig_filename, R_ENTRY_UNREADABLE)
                continue
            if len(data) != info.file_size:
                reject(info.orig_filename, R_MISMATCH)
                continue
            if _is_archive(entry.path, data):
                reject(info.orig_filename, R_NESTED)
                continue
            entry.sha256 = _sha256(data)
            if not rejections:
                sink(entry, data)
        if rejections:
            raise refuse()
    source = {"type": SOURCE_ZIP, "target": os.path.abspath(target), "ref": None, "commit": None,
              "git_tree": None}
    return source, entries, []


# --------------------------------------------------------------------------------------
# The bundle
# --------------------------------------------------------------------------------------

def _mode_text(mode: int) -> str:
    return "%04o" % (mode & 0o7777)


def _exec_bit(entry: _Entry) -> str:
    return "x" if (entry.entry == ENTRY_FILE and entry.mode & 0o111) else "-"


def _tree_digest(entries: List[_Entry]) -> str:
    """One digest for the content of the target: entry kind, executable bit, content digest
    (the submodule commit for a gitlink), size and path of every entry, in path order. It is
    the same for the same content whichever way the target arrived."""
    digest = hashlib.sha256()
    for entry in entries:
        content = entry.extra.get("gitlink_commit") or entry.sha256
        line = "\x00".join((entry.entry, _exec_bit(entry), content, str(entry.size), entry.path))
        digest.update(line.encode("utf-8", "backslashreplace") + b"\n")
    return digest.hexdigest()


def inventory_tree_digest(inventory: Dict[str, Any]) -> str:
    """The tree digest recomputed from an inventory's own rows (see `_tree_digest`). Raises
    BundleError when a row does not carry what the digest is made of."""
    digest = hashlib.sha256()
    try:
        for row in inventory["files"]:
            entry = row["entry"]
            path = row["path"]
            size = row["size"]
            content = row.get("gitlink_commit") or row["sha256"]
            if not (isinstance(entry, str) and isinstance(path, str) and isinstance(content, str)
                    and isinstance(size, int) and not isinstance(size, bool)):
                raise BundleError("inventory row is malformed")
            executable = entry == ENTRY_FILE and int(str(row["mode"]), 8) & 0o111
            line = "\x00".join((entry, "x" if executable else "-", content, str(size), path))
            digest.update(line.encode("utf-8", "backslashreplace") + b"\n")
    except (KeyError, TypeError, ValueError):
        raise BundleError("inventory row is malformed")
    return digest.hexdigest()


def inventory_digest(inventory: Dict[str, Any]) -> str:
    """SHA-256 of the inventory's canonical JSON without its own `inventory_digest` field."""
    body = {k: v for k, v in inventory.items() if k != "inventory_digest"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _sha256(text.encode("ascii"))


def _make_private_dir(path: str) -> None:
    missing = []
    probe = path
    while probe and not os.path.isdir(probe):
        missing.append(probe)
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    os.makedirs(path, 0o700, exist_ok=True)
    for made in missing:
        os.chmod(made, 0o700)


def _remove_tree(path: str) -> None:
    def retry(func: Any, target: str, _exc: Any) -> None:
        try:
            os.chmod(os.path.dirname(target), 0o700)
            os.chmod(target, 0o700)
            func(target)
        except OSError:
            pass

    if os.path.lexists(path):
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=retry)
        else:
            shutil.rmtree(path, onerror=retry)


class _TarSink:
    """Writes stored files to the tar as they arrive. Members are plain regular files with
    a normalised mode and no owner, time or link, so the tar is a function of the content."""

    def __init__(self, path: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        self._fh = os.fdopen(os.open(path, flags, 0o600), "wb")
        self._tar = tarfile.open(fileobj=self._fh, mode="w", format=tarfile.PAX_FORMAT)
        self.stored: List[str] = []
        self.stored_bytes = 0

    def __call__(self, entry: _Entry, data: bytes) -> None:
        info = tarfile.TarInfo(name=entry.path)
        info.size = len(data)
        info.mode = 0o755 if (entry.mode & 0o111) else 0o644
        info.mtime = 0
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.type = tarfile.REGTYPE
        self._tar.addfile(info, io.BytesIO(data))
        self.stored.append(entry.path)
        self.stored_bytes += len(data)

    def close(self) -> None:
        try:
            self._tar.close()
            self._fh.flush()
            os.fsync(self._fh.fileno())
        finally:
            self._fh.close()

    def abort(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


def _hash_file(path: str) -> Tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _build_inventory(bundle_id: str, source: Dict[str, Any], entries: List[_Entry],
                     skipped: List[Dict[str, str]], stored: Sequence[str], limits: Limits,
                     tar_path: str) -> Dict[str, Any]:
    stored_set = set(stored)
    files: List[Dict[str, Any]] = []
    omissions: List[Dict[str, str]] = []
    stored_bytes = 0
    for index, entry in enumerate(entries, 1):
        is_stored = entry.omit is None and entry.entry == ENTRY_FILE and entry.path in stored_set
        if not is_stored and entry.omit is None:
            entry.omit = R_UNREADABLE
        row: Dict[str, Any] = {
            "id": _file_id(index),
            "path": entry.path,
            "mode": _mode_text(entry.mode),
            "entry": entry.entry,
            "size": entry.size,
            "sha256": entry.sha256,
            "stored": is_stored,
        }
        for key in ("link_target", "link_escapes", "gitlink_commit", "git_mode", "path_problem"):
            if key in entry.extra:
                row[key] = entry.extra[key]
        if is_stored:
            stored_bytes += entry.size
            if entry.extra.get("lfs_pointer"):
                row["lfs_pointer"] = True
        else:
            row["omitted"] = entry.omit
            omissions.append({"path": entry.path, "entry": entry.entry, "reason": str(entry.omit)})
        files.append(row)
    omissions.extend(skipped)
    tar_sha, tar_size = _hash_file(tar_path)
    inventory: Dict[str, Any] = {
        "schema": SCHEMA,
        "bundle_id": bundle_id,
        "fetched_at": _now(),
        "source": source,
        "limits": dict(limits._asdict()),
        "tar": {"name": TAR_NAME, "sha256": tar_sha, "size": tar_size},
        "counts": {"entries": len(files), "stored": len(stored_set), "omitted": len(files) - len(stored_set),
                   "stored_bytes": stored_bytes},
        "files": files,
        "omissions": omissions,
        "tree_digest": _tree_digest(entries),
    }
    inventory["inventory_digest"] = inventory_digest(inventory)
    return inventory


def _new_bundle_id() -> str:
    return "q%s-%s" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), secrets.token_hex(4))


def _fetch_into(staging: str, target: str, ref: Optional[str], limits: Limits,
                protocols: Sequence[str], bundle_id: str) -> Dict[str, Any]:
    source_type = classify_target(target)
    if source_type is None:
        if isinstance(target, str) and target and os.path.lexists(target):
            raise _Gap(GAP_TARGET_TYPE, "the target is neither a folder nor a zip")
        raise _Gap(GAP_TARGET_NOT_FOUND, "the target is not an existing path or a git URL")
    if source_type != SOURCE_GIT and ref is not None:
        raise _Gap(GAP_REF, "a ref applies to a git target only")

    tar_path = os.path.join(staging, TAR_NAME)
    sink = _TarSink(tar_path)

    def keep(entry: _Entry, data: bytes) -> None:
        if data.startswith(_LFS_PREFIX):
            entry.extra["lfs_pointer"] = True
        sink(entry, data)

    try:
        if source_type == SOURCE_GIT:
            work = os.path.join(staging, "work")
            os.makedirs(work, 0o700)
            try:
                source, entries, skipped = _collect_git(target, ref, work, protocols, limits, keep)
            finally:
                _remove_tree(work)
        elif source_type == SOURCE_FOLDER:
            source, entries, skipped = _collect_folder(target, limits, keep)
        else:
            source, entries, skipped = _collect_zip(target, limits, keep)
        sink.close()
    except BaseException:
        sink.abort()
        raise
    os.chmod(tar_path, 0o600)
    inventory = _build_inventory(bundle_id, source, entries, skipped, sink.stored, limits, tar_path)
    inv_path = os.path.join(staging, INVENTORY_NAME)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(inv_path, flags, 0o600), "w", encoding="ascii", newline="\n") as fh:
        json.dump(inventory, fh, indent=1, sort_keys=True, ensure_ascii=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(inv_path, 0o600)
    return inventory


def fetch(target: str, *, quarantine_root: Optional[str] = None, ref: Optional[str] = None,
          limits: Limits = DEFAULT_LIMITS,
          test_only_protocols: Optional[Sequence[str]] = None) -> FetchResult:
    """Acquire `target` (a git URL, a folder or a zip) into a new quarantine bundle.

    Returns a FetchResult. On success `ok` is true and the bundle directory holds
    source.tar and inventory.json. On any failure `ok` is false, `gap` names the reason
    and nothing is left on disk. `ref` (git only) is a branch, a tag or a commit id.

    `test_only_protocols` replaces the https-only allow-list. It exists so the tests can
    clone a local repository over file://; production callers never pass it.
    """
    protocols = tuple(test_only_protocols) if test_only_protocols is not None else ALLOWED_PROTOCOLS
    staging = None
    try:
        try:
            target = os.fspath(target)
        except TypeError:
            raise _Gap(GAP_TARGET_NOT_FOUND, "the target is not a path or a URL")
        root = resolve_quarantine_root(quarantine_root)
        try:
            _make_private_dir(root)
            staging = tempfile.mkdtemp(prefix=".staging-", dir=root)
            os.chmod(staging, 0o700)
        except OSError as exc:
            raise _Gap(GAP_QUARANTINE, "the quarantine directory could not be written (%s)"
                       % type(exc).__name__, internal=True)
        bundle_id = _new_bundle_id()
        try:
            inventory = _fetch_into(staging, target, ref, limits, protocols, bundle_id)
            final = os.path.join(root, bundle_id)
            os.rename(staging, final)
        except _Gap:
            raise
        except OSError as exc:
            raise _Gap(GAP_QUARANTINE, "the bundle could not be written (%s)" % type(exc).__name__,
                       internal=True)
        staging = None
        return FetchResult(True, bundle_id, final, os.path.join(final, TAR_NAME),
                           os.path.join(final, INVENTORY_NAME), inventory, None)
    except _Gap as gap:
        return FetchResult(False, None, None, None, None, None, gap.to_dict())
    except Exception as exc:  # noqa: BLE001 -- every failure ends in a named gap
        gap = _Gap(GAP_INTERNAL, "unexpected %s while fetching" % type(exc).__name__, internal=True)
        return FetchResult(False, None, None, None, None, None, gap.to_dict())
    finally:
        if staging is not None:
            _remove_tree(staging)


# --------------------------------------------------------------------------------------
# Reading a bundle back
# --------------------------------------------------------------------------------------

def load_inventory(bundle_dir: str) -> Dict[str, Any]:
    """Read and check a bundle's inventory. Raises BundleError when it is missing,
    malformed, its digest does not match its content, or its tree digest is not the digest
    of the rows it lists."""
    path = os.path.join(bundle_dir, INVENTORY_NAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            inventory = json.load(fh)
    except (OSError, ValueError) as exc:
        raise BundleError("inventory unreadable (%s)" % type(exc).__name__)
    if not isinstance(inventory, dict) or inventory.get("schema") != SCHEMA:
        raise BundleError("inventory has an unknown schema")
    if not isinstance(inventory.get("files"), list) or not isinstance(inventory.get("tar"), dict):
        raise BundleError("inventory is malformed")
    if inventory.get("inventory_digest") != inventory_digest(inventory):
        raise BundleError("inventory digest mismatch")
    if inventory.get("tree_digest") != inventory_tree_digest(inventory):
        raise BundleError("inventory tree digest is not the digest of its rows")
    return inventory


def _checked_tar(bundle_dir: str, inventory: Dict[str, Any]) -> str:
    tar_path = os.path.join(bundle_dir, TAR_NAME)
    try:
        digest, _size = _hash_file(tar_path)
    except OSError as exc:
        raise BundleError("source.tar unreadable (%s)" % type(exc).__name__)
    if digest != inventory["tar"].get("sha256"):
        raise BundleError("source.tar digest mismatch")
    return tar_path


def _stored_members(tar: tarfile.TarFile, inventory: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], bytes]]:
    """(inventory row, content) for every stored file, checked member by member."""
    rows = [row for row in inventory["files"] if row.get("stored")]
    index = 0
    for member in tar:
        if not member.isreg():
            raise BundleError("source.tar holds a member that is not a regular file")
        if index >= len(rows) or member.name != rows[index].get("path"):
            raise BundleError("source.tar holds a member the inventory does not list")
        row = rows[index]
        index += 1
        if _path_problem(member.name, len(member.name) + 1) not in (None, R_TOO_LONG):
            raise BundleError("source.tar holds an unsafe member name")
        if member.size != row.get("size"):
            raise BundleError("source.tar member size mismatch")
        handle = tar.extractfile(member)
        data = handle.read(member.size + 1) if handle is not None else b""
        if len(data) != member.size or _sha256(data) != row.get("sha256"):
            raise BundleError("source.tar member content mismatch")
        yield row, data
    if index != len(rows):
        raise BundleError("source.tar is missing a member the inventory lists")


def iter_bundle_entries(bundle_dir: str) -> Iterator[BundleEntry]:
    """Every inventory row as a BundleEntry, in inventory order, content included.

    A stored file carries its bytes. An oversize file carries no bytes and its size. Every
    other entry that was not stored (a link, a submodule, a device, an unsafe or colliding
    path) carries no bytes and an entry kind that is not "file", so the rule set reports
    it without anything having been read. Raises BundleError on any mismatch.
    """
    inventory = load_inventory(bundle_dir)
    tar_path = _checked_tar(bundle_dir, inventory)
    with tarfile.open(tar_path, "r:") as tar:
        stored = _stored_members(tar, inventory)
        for row in inventory["files"]:
            mode = int(str(row.get("mode", "0")), 8)
            if row.get("stored"):
                pair = next(stored, None)
                if pair is None:
                    raise BundleError("source.tar is missing a member the inventory lists")
                data = pair[1]
                yield BundleEntry(row["id"], row["path"], mode, data, ENTRY_FILE, None)
                continue
            entry = row.get("entry", ENTRY_OTHER)
            if entry == ENTRY_FILE and row.get("omitted") != R_OVERSIZE:
                entry = ENTRY_OTHER
            yield BundleEntry(row["id"], row["path"], mode, b"", entry, int(row.get("size") or 0))
        for _extra in stored:
            pass


@contextlib.contextmanager
def extracted(bundle_dir: str, tmp_parent: Optional[str] = None) -> Iterator[str]:
    """Extract a bundle's stored files into a private 0700 temp directory for scanning.

    Yields the directory and removes it afterwards, whatever happens. Only regular files
    listed in the inventory are written, each checked against its recorded size and
    digest; no link, device or directory member is ever materialised. Raises BundleError
    when the tar and the inventory disagree.
    """
    inventory = load_inventory(bundle_dir)
    tar_path = _checked_tar(bundle_dir, inventory)
    tmp = tempfile.mkdtemp(prefix="intake-scan-", dir=tmp_parent)
    try:
        os.chmod(tmp, 0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with tarfile.open(tar_path, "r:") as tar:
            for row, data in _stored_members(tar, inventory):
                parts = row["path"].split("/")
                parent = os.path.join(tmp, *parts[:-1]) if len(parts) > 1 else tmp
                os.makedirs(parent, 0o700, exist_ok=True)
                executable = int(str(row.get("mode", "0")), 8) & 0o111
                try:
                    fd = os.open(os.path.join(parent, parts[-1]), flags, 0o700 if executable else 0o600)
                except OSError as exc:
                    raise BundleError("a file could not be extracted (%s)" % type(exc).__name__)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
        yield tmp
    finally:
        _remove_tree(tmp)


def remove_bundle(bundle_dir: str) -> None:
    """Delete a whole bundle directory (the tar, the inventory and anything beside them)."""
    _remove_tree(bundle_dir)


# --------------------------------------------------------------------------------------
# Command line (a thin wrapper; `intake.py scan` is the user-facing command)
# --------------------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description="Fetch a git URL, a folder or a zip into a quarantine bundle. Nothing is executed.")
    parser.add_argument("target")
    parser.add_argument("--ref", default=None, help="git only: a branch, a tag or a commit id")
    parser.add_argument("--quarantine-root", default=None,
                        help="default: $%s, else ~/.foundry/quarantine" % QUARANTINE_ENV)
    args = parser.parse_args(argv)
    result = fetch(args.target, quarantine_root=args.quarantine_root, ref=args.ref)
    if result.ok and result.inventory is not None:
        inv = result.inventory
        summary = {"ok": True, "bundle_id": result.bundle_id, "bundle_dir": result.bundle_dir,
                   "source_type": inv["source"]["type"], "commit": inv["source"]["commit"],
                   "counts": inv["counts"], "tree_digest": inv["tree_digest"],
                   "inventory_digest": inv["inventory_digest"]}
        print(json.dumps(summary, indent=1, sort_keys=True))
        return 0
    gap = result.gap or {}
    summary = {"ok": False, "gap": gap.get("gap"), "reasons": gap.get("reasons", []),
               "rejections": len(gap.get("rejections", []))}
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 3 if gap.get("internal") else 2


if __name__ == "__main__":
    sys.exit(main())
