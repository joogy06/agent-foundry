#!/usr/bin/env python3
"""harness_rules.py -- the in-house rule set for intake scanning (#350).

One rule set decides what may enter the library. `intake.py scan`, arm 6 of the pre-commit
hook and the `install.py` check all call `scan()` here, so a file is judged the same way
whether it arrives from outside, is staged for commit, or is about to be installed.

    block rules    H1 to H9, H11   a hit stops adoption, a commit and an install
    caution rules  C1 to C10       reported; the user signs them off before adoption

H10 (a dependency with a malicious-package advisory) is NOT here: it needs the network and
belongs to the dependency adapter.

BOUNDED WORK. A line longer than MAX_LINE_CHARS is not given to the line patterns (H3, H4,
H5 and the cautions): the file gets H11 when it is an executable or a markdown file, and C9
otherwise, so an unchecked line is never reported as clean. H1, H2, H6 and H9 read the whole
text: each is linear in its length. The "A, then B later on the same line" checks are done
by position (`_Then`), not by a pattern that rescans the rest of the line from every A.

Input is an iterable of `FileRecord` (opaque id, path, mode, bytes, entry kind) plus the
target kind. Output is a list of `Finding` (rule id, class, opaque file id, line). The
caller owns the mapping from file id to path, so nothing this module returns carries text
chosen by the target: a caller may print a finding and `describe()` and nothing else.

WHAT THIS MODULE DELIBERATELY DOES NOT HAVE: an inline ignore marker, a target config file,
a path exemption. Nothing inside the scanned content can switch a rule off. The only way
past a block hit is a per-hit exception in the ledger, keyed by `exception_key()` (rule id
plus the SHA-256 of the file), which stops matching when the file changes.

The rule tables below are written in escaped form (`\\uXXXX` escapes, quantifiers in place
of repeated characters) so that this file does not trip the rules it defines. A test
asserts the file is pure ASCII and scans clean under its own block rules.

Every check but one works on one file at a time and on single lines. "Download, then run"
spread over several lines, and a lifecycle script that calls a local file which then reaches
the network, are not detected here; those are caught, if at all, by the third-party scanners
and by the human read of the triage sheet.

THE ONE SET-LEVEL CHECK is the repository layout (H7). Git takes a directory for a
repository by what it HOLDS, whatever it is called: `HEAD` beside `objects` and `refs`. A
command started there then reads that directory's `config` and runs what it names. So
`repo_layout_dirs()` looks at the names in every directory of the file set, and every file
under a directory with that shape is an H7 hit. A caller that scans part of a tree (the
commit hook) passes the rest of the tree's paths as `context_paths`.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import stat
from typing import Any, Dict, Iterable, Iterator, List, NamedTuple, Optional, Sequence, Tuple

# Bumped whenever a rule's behaviour changes; recorded in every scan record.
RULES_VERSION = "3"

BLOCK = "block"
CAUTION = "caution"

KIND_SKILL = "skill"
KIND_REPO = "repo"
KINDS = (KIND_SKILL, KIND_REPO)

# Entry kinds. Anything but a regular file is an H7 hit and gets no content rules.
ENTRY_FILE = "file"
ENTRY_SYMLINK = "symlink"
ENTRY_DEVICE = "device"
ENTRY_GITLINK = "gitlink"      # a submodule entry in a git tree
ENTRY_OTHER = "other"          # fifo, socket, anything else that is not a regular file
ENTRIES = (ENTRY_FILE, ENTRY_SYMLINK, ENTRY_DEVICE, ENTRY_GITLINK, ENTRY_OTHER)

# H7 size caps. A file over the per-file cap is reported and its content is not inspected.
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 20000
# A longer line is not given to the line patterns; see BOUNDED WORK in the module docstring.
MAX_LINE_CHARS = 4096

# The file id carried by a finding about the whole file set (the two set-level size caps).
SET_FILE_ID = "-"


class Rule(NamedTuple):
    rule_id: str
    rule_class: str
    description: str     # fixed text owned by us: the only prose a caller may print
    fix: str             # remedy text; empty for block rules


class FileRecord(NamedTuple):
    file_id: str         # opaque, chosen by the caller (see make_file_id)
    path: str            # as stored in the target; "/" or "\\" separators
    mode: int            # permission bits; only the execute bits are read
    data: bytes          # full content; b"" for a non-regular entry or an unread oversize file
    entry: str = ENTRY_FILE
    size: Optional[int] = None   # real size when `data` was not read; else len(data) is used


class Finding(NamedTuple):
    rule_id: str
    rule_class: str
    file_id: str
    line: int            # 1-based; 0 when the finding is about the file as a whole
    sha256: str          # SHA-256 of the file content; "" when there is no content

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule_id, "class": self.rule_class,
                "file": self.file_id, "line": self.line}


# --------------------------------------------------------------------------------------
# Rule table
# --------------------------------------------------------------------------------------

_BLOCK_RULES = (
    ("H1", "Hidden, bidirectional, tag or zero-width unicode in a text file"),
    ("H2", "Shipped harness config: settings, MCP servers, hooks, permissions or a "
           "harness dot-directory"),
    ("H3", "Frontmatter that grants unscoped tools"),
    ("H4", "Load-time shell block in a skill, agent or command file"),
    ("H5", "Fetch-and-execute in an executable file"),
    ("H6", "Install-time auto-execution: a path-configuration file, a site customisation "
           "module, or a lifecycle script that reaches the network"),
    ("H7", "Symlink, device file, path traversal, submodule, version-control directory "
           "(by its name or by its layout), LFS pointer, nested archive or a size cap exceeded"),
    ("H8", "Opaque binary, including compiled Python"),
    ("H9", "A private key header or a provider-prefixed token"),
    ("H11", "A line too long to pattern-check in an executable or markdown file"),
)

# The eight patterns moved from skills/skill-intake/scripts/assess.py SECURITY_PATTERNS:
# (id, regex, label, fix). Label and fix text are kept word for word.
_CAUTION_RULES = (
    ("C1", None, "curl piped into a shell",
     "name the URL as a reference; let a human fetch and review it"),
    ("C2", r"\b(curl|wget)\s+https?://(?!example\.|localhost)", "network fetch to a live host",
     "move the fact into a version-stamped reference file with a REVIEW_BY date"),
    ("C3", r"\beval\s*\(", "dynamic evaluation", "replace with an explicit dispatch"),
    ("C4", r"\bbase64\s+-d\b|\bbase64\.b64decode", "base64 decode of embedded data",
     "inline the content readably, or reference a file"),
    ("C5", r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][A-Za-z0-9/+=_-]{16,}[\"']",
     "credential-shaped literal", "use an obvious placeholder such as <API_KEY>"),
    ("C6", r"/(home|Users)/[a-z][a-z0-9_-]{2,}/", "absolute path to a developer machine",
     "use a relative path or an environment variable"),
    ("C7", r"(?i)\b(disable|bypass|skip|turn off)\s+(the\s+)?(security|scanner|check|gate|verification)\b",
     "instruction to disable a safety control", "remove it; a workaround here is a permanent hole"),
    ("C8", r"(?i)\bchmod\s+777\b", "world-writable permissions", "use the narrowest mode that works"),
)

# C9 has no pattern: it marks a file with a line the patterns above were not run on.
_UNCHECKED_LINE_CAUTION = ("C9", "a line too long to pattern-check",
                           "break the line up, or move the data into a file of its own")

# C10 goes by the file's name alone: one finding per file, whatever it holds.
_AUTO_LOADED_CAUTION = ("C10", "a file a developer tool loads or runs by itself inside this directory",
                        "read it before working or running tests in the unit; drop it if it is not needed")
_C10_NAMES = frozenset({"conftest.py", "pytest.ini", "tox.ini", "noxfile.py", ".envrc", ".mise.toml"})
_C10_IN_DIR = {".vscode": frozenset({"tasks.json", "launch.json"})}
_C10_DIRS = frozenset({".idea", ".devcontainer"})


class _Then(NamedTuple):
    """`first`, then `last` later on the same line with none of `stops` in between.

    The same check as the pattern first + "[^stops]*" + last, done by position so that a
    line holding many `first` matches is read once and not once per match.
    """
    first: "re.Pattern[str]"
    last: "re.Pattern[str]"
    stops: str = ""


RULES: Dict[str, Rule] = {}
for _rid, _desc in _BLOCK_RULES:
    RULES[_rid] = Rule(_rid, BLOCK, _desc, "")
for _rid, _pat, _label, _fix in _CAUTION_RULES:
    RULES[_rid] = Rule(_rid, CAUTION, _label, _fix)
for _extra in (_UNCHECKED_LINE_CAUTION, _AUTO_LOADED_CAUTION):
    RULES[_extra[0]] = Rule(_extra[0], CAUTION, *_extra[1:])

BLOCK_RULE_IDS = tuple(r[0] for r in _BLOCK_RULES)
CAUTION_RULE_IDS = (tuple(r[0] for r in _CAUTION_RULES)
                    + (_UNCHECKED_LINE_CAUTION[0], _AUTO_LOADED_CAUTION[0]))

# A pattern runs on a file only when one of its gate words is in the lowercased text. The
# gates are plain substring tests, which is what keeps a pass over the whole library fast;
# every gate is implied by its pattern, so a gate never hides a match.
_CAUTION_GATES = {
    "C1": ("curl",), "C2": ("curl", "wget"), "C3": ("eval",), "C4": ("base64",),
    "C5": ("key", "secret", "token", "password"), "C6": ("/home/", "/users/"),
    "C7": ("disable", "bypass", "skip", "turn off"), "C8": ("chmod",),
}
_C1 = _Then(re.compile(r"\bcurl\b"), re.compile(r"\|\s*(?:ba)?sh"), "|")
_CAUTION_COMPILED = tuple(
    (rid, _CAUTION_GATES[rid], _C1 if pat is None else re.compile(pat))
    for rid, pat, _l, _f in _CAUTION_RULES)


def describe(rule_id: str) -> str:
    """The fixed description of a rule. Raises KeyError for an id this module does not own."""
    return RULES[rule_id].description


def rule_class(rule_id: str) -> str:
    return RULES[rule_id].rule_class


# --------------------------------------------------------------------------------------
# Patterns (escaped form: see the module docstring)
# --------------------------------------------------------------------------------------

# H1. Soft hyphen, Arabic letter mark, Hangul fillers, Mongolian vowel separator, zero-width
# and directional marks, bidirectional embeddings/overrides/isolates, invisible operators,
# the byte-order mark, interlinear annotation, tag characters, supplementary variation
# selectors. One ordinary variation selector is normal after an emoji; a run of them is not.
_H1 = re.compile(
    "[\u00ad\u061c\u115f\u1160\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069"
    "\u3164\ufeff\uffa0\ufff9-\ufffb\U000e0000-\U000e007f\U000e0100-\U000e01ef]"
    "|[\ufe00-\ufe0f]{2,}"
)
# Public name of the same object, for a sibling skill that needs "any hidden character"
# (mail-scan). An alias only: H1 behaves as before.
HIDDEN_UNICODE = _H1

# H2.
_H2_NAMES = frozenset({"settings.json", "settings.local.json", ".mcp.json", "hooks.json"})
_H2_DIRS = frozenset({".claude", ".codex", ".cursor", ".gemini"})
_H2_PLUGIN_DIR = ".claude-plugin"
_H2_KEYS = ("hooks", "mcpServers", "mcp_servers", "permissions")
_H2_KEY_LINE = re.compile(
    r"(?m)^[ \t]*\[?[\"']?(?:hooks|mcpServers|mcp_servers|permissions)[\"']?[ \t]*[:=.\]]")

# H3.
_MARKDOWN_EXT = frozenset({".md", ".mdc", ".mdx", ".markdown"})
_H3_GRANT_KEYS = frozenset({"allowed-tools", "allowed_tools", "allowedtools"})
_H3_TOOL_KEYS = _H3_GRANT_KEYS | frozenset({"tools"})
_H3_KEY = re.compile(r"^([A-Za-z_][\w.-]*)[ \t]*:(.*)$")
_H3_OPEN = re.compile(r"^---[ \t]*$")
# Every character a YAML reader may take as a line break, beside the line feed itself.
_H3_BREAKS = re.compile("\r\n?|[\x85\u2028\u2029]")
_H3_OPEN_INLINE = re.compile(r"^---[ \t]+[^\s#]")
# A tool name is read only where one can start, so a long run of name characters is read once.
_H3_UNSCOPED = re.compile(r"(?<![\w-])[A-Za-z_][\w-]*\([\s*:]*\*[\s*:]*\)")
_H3_SCOPED = re.compile(r"(?<![\w-])[A-Za-z_][\w-]*\([^()]*\)")
_H3_SPLIT = re.compile(r"[\s,\[\]\"']+")
_H3_TOOL_NAME = re.compile(r"^[A-Za-z_][\w.-]*$")
_H3_BLOCK_SCALAR = re.compile(r"^[|>][+-]?[1-9]?[+-]?$")

# H4. An exclamation mark directly before an inline code span, or a fence opened with one.
# _h4() keeps a candidate when the mark follows whitespace or starts the line, or when the
# backtick after it OPENS a span (an even number of backticks before it on the line). A
# mark that sits inside a code span, as in prose that quotes the character, is not a hit.
_H4 = re.compile(r"!\x60[^\x60\n]+\x60")
_H4_FENCE = re.compile(r"(?m)^[ \t]*\x60{3}!")

# H5.
_CODE_EXT = frozenset({
    ".sh", ".bash", ".zsh", ".ksh", ".fish", ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts",
    ".rb", ".pl", ".php", ".ps1", ".psm1", ".bat", ".cmd", ".lua", ".awk",
})
_CODE_NAMES = frozenset({"makefile", "dockerfile", "justfile", "rakefile"})
_FETCH = r"(?:curl|wget)"
_SHELL = r"(?:sudo\s+)?(?:ba|z|da|k)?sh\b"
# Split literals: the two halves of a cradle must not sit whole on one line of this file.
_PS_FETCH = "(?:iw" "r|ir" "m|invoke-web" "request|invoke-rest" "method)"
_PS_EVAL = "(?:ie" "x|invoke-express" "ion)"
_FETCH_WORD = re.compile(r"\b" + _FETCH + r"\b")
_PS_FETCH_WORD = re.compile(r"(?i)\b" + _PS_FETCH + r"\b")
_PS_EVAL_WORD = re.compile(r"(?i)\b" + _PS_EVAL + r"\b")
# (gate words, checks). A check is a pattern, or a `_Then` pair for "A ... B on one line".
_H5 = (
    (("curl", "wget"), (
        # fetch piped into an interpreter
        _Then(_FETCH_WORD, re.compile(
            r"\|\s*(?:" + _SHELL + r"|(?:sudo\s+)?(?:python[0-9.]*|perl|ruby|node)\b)"), "|;&"),
        # an interpreter fed by process or command substitution of a fetch
        re.compile("|".join((
            r"\b(?:ba|z)?sh\s+(?:-\w+\s+)*<\(\s*" + _FETCH + r"\b",
            r"\b(?:source|eval|exec)\s+[\"']?(?:<\(|\$\(|\x60)\s*" + _FETCH + r"\b",
            r"\b(?:ba|z)?sh\s+-c\s+[\"']?\$\(\s*" + _FETCH + r"\b",
        ))),
        # fetch to a file, then run it, on one line
        _Then(_FETCH_WORD, re.compile(r"(?:&&|;)\s*" + _SHELL + r"\s+[^\s-]")),
    )),
    # PowerShell download cradles
    (("iex", "invoke-expression"), (
        _Then(_PS_FETCH_WORD, re.compile(r"(?i)\|\s*" + _PS_EVAL + r"\b"), "|"),
        _Then(_PS_EVAL_WORD, re.compile(r"(?i)\b(?:" + _PS_FETCH + r"|downloadstring)\b")),
    )),
    # dynamic evaluation of a download, on one line
    (("urlopen", "urlretrieve", "requests.", "httpx."), (
        _Then(re.compile(r"\b(?:exec|eval)\s*\("), re.compile(
            r"\b(?:urlopen|urlretrieve|requests\.(?:get|post)|httpx\.(?:get|post))\b")),
    )),
    (("fetch", ".get", "axios"), (
        _Then(re.compile(r"\b(?:eval|Function)\s*\("), re.compile(
            r"\b(?:fetch\s*\(|https?\.get\s*\(|axios\b)")),
    )),
)

# H6.
_H6_SITE_NAMES = frozenset({"sitecustomize.py", "usercustomize.py"})
_H6_LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "prepublish",
                 "preuninstall", "postuninstall")
_H6_NET = re.compile(
    r"(?i)\b(?:curl|wget|npx|nc|ncat|invoke-webrequest)\b|\bgit\s+clone\b|\b(?:https?|ftp)://")
_H6_SETUP_NET = re.compile(
    r"\b(?:urlopen|urlretrieve|requests\.(?:get|post)|httpx\.(?:get|post)|http\.client|socket\.socket)\b"
    r"|\b(?:curl|wget)\s")

# H7.
_ARCHIVE_EXT = (".zip", ".tar", ".tgz", ".tar.gz", ".gz", ".bz2", ".tbz2", ".xz", ".txz",
                ".7z", ".rar", ".whl", ".egg", ".jar", ".war", ".apk", ".zst")
_ARCHIVE_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00",
                  b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07", b"\x28\xb5\x2f\xfd")
_LFS_PREFIX = b"version https://git-lfs.github.com/spec/"
_DRIVE = re.compile(r"^[A-Za-z]:")
# Version-control directories whose config the tool honours (and so runs commands from) as
# soon as it is started inside them. Compared the way a case-insensitive file system and
# git itself compare: case folded, trailing dots and spaces dropped, ignorable code points
# dropped, an alternate-stream suffix dropped, and the short 8.3 name of ".git" included.
_VCS_NAMES = frozenset({".git", ".hg", ".svn", "git~1", ".bzr", ".jj", ".sl", "_darcs"})
_VCS_IGNORABLE = {code: None for span in ((0x200c, 0x200f), (0x202a, 0x202e), (0x206a, 0x206f),
                                          (0xfeff, 0xfeff))
                  for code in range(span[0], span[1] + 1)}

# H8.
_COMPILED_EXT = frozenset({
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".class", ".wasm", ".o", ".a",
    ".node", ".bin", ".msi", ".com",
})
_BINARY_MAGIC = (b"\x7fELF", b"MZ", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                 b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\x00asm")
# Raster images are the one binary shape let through, and only when the extension and the
# leading bytes agree. Everything else that is not text is opaque.
_IMAGE_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
}

# H9. A private key header, or a token with a provider prefix. Every match is a hit:
# whether a value is "an example" cannot be decided mechanically, so that is a per-hit
# exception in the ledger, never a heuristic here.
_NOT_WORD_BEFORE = r"(?<![A-Za-z0-9_-])"
_H9 = re.compile(
    r"-{5}BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-{5}"
    r"|" + _NOT_WORD_BEFORE + r"(?:"
    r"A[KS]IA[0-9A-Z]{16}(?![0-9A-Z])"
    r"|gh[pousr]_[A-Za-z0-9]{36,}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|sk-(?:ant|proj|svcacct)-[A-Za-z0-9_-]{20,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|[sr]k_live_[A-Za-z0-9]{24,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|npm_[A-Za-z0-9]{36}"
    r"|hf_[A-Za-z0-9]{34,}"
    r"|SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}"
    r")"
)
# Public name of the same object ("a private key header or a provider token"), for a
# sibling skill (mail-scan). An alias only: H9 behaves as before.
TOKEN_PATTERN = _H9


_H9_GATES = ("private key", "akia", "asia", "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
             "github_pat_", "glpat-", "xox", "sk-", "k_live_", "aiza", "npm_", "hf_", "sg.")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def make_file_id(index: int) -> str:
    """The opaque id for the index-th file of a set (1-based): f001, f002, ..."""
    return "f%03d" % index


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exception_key(rule_id: str, file_sha256: str) -> str:
    """The ledger key of a per-hit exception: the rule plus the file's content digest."""
    if rule_id not in RULES:
        raise KeyError(rule_id)
    return "%s:%s" % (rule_id, file_sha256)


def finding_exception_key(finding: Finding) -> str:
    return exception_key(finding.rule_id, finding.sha256)


def entry_for_git_mode(git_mode: str) -> str:
    """Map a git tree mode ("100644", "120000", "160000", ...) to an entry kind."""
    if git_mode in ("100644", "100755", "100664"):
        return ENTRY_FILE
    if git_mode == "120000":
        return ENTRY_SYMLINK
    if git_mode == "160000":
        return ENTRY_GITLINK
    return ENTRY_OTHER


def record_from_path(root: str, relpath: str, file_id: str) -> FileRecord:
    """Build a record for a file in a directory tree WITHOUT following a symlink.

    A symlink, device or other non-regular entry is recorded as such with no content. A
    file over MAX_FILE_BYTES is recorded with its size and no content.
    """
    full = os.path.join(root, relpath)
    st = os.lstat(full)
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISLNK(st.st_mode):
        return FileRecord(file_id, relpath, mode, b"", ENTRY_SYMLINK)
    if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
        return FileRecord(file_id, relpath, mode, b"", ENTRY_DEVICE)
    if not stat.S_ISREG(st.st_mode):
        return FileRecord(file_id, relpath, mode, b"", ENTRY_OTHER)
    if st.st_size > MAX_FILE_BYTES:
        return FileRecord(file_id, relpath, mode, b"", ENTRY_FILE, st.st_size)
    with open(full, "rb") as fh:
        return FileRecord(file_id, relpath, mode, fh.read(), ENTRY_FILE)


def records_from_paths(root: str, relpaths: Iterable[str]) -> Iterator[FileRecord]:
    """Records for `relpaths` under `root`, with ids f001, f002, ... in the given order."""
    for index, relpath in enumerate(relpaths, 1):
        yield record_from_path(root, relpath, make_file_id(index))


def _parts(path: str) -> List[str]:
    return [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]


def _ext(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _decode(data: bytes) -> Optional[str]:
    """The text of a file, or None when it is not UTF-8 text."""
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class _Lines:
    """Line numbers for match offsets, computed once per file and only when needed."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._starts: Optional[List[int]] = None

    def of(self, offset: int) -> int:
        if self._starts is None:
            self._starts = [m.end() for m in re.finditer("\n", self._text)]
        return bisect.bisect_right(self._starts, offset) + 1


def is_executable(record: FileRecord) -> bool:
    """True for a file the host could run: an execute bit, a shebang or a script extension."""
    if record.entry != ENTRY_FILE:
        return False
    parts = _parts(record.path)
    name = parts[-1].lower() if parts else ""
    if _ext(name) in _CODE_EXT or name in _CODE_NAMES:
        return True
    if record.data[:2] == b"#!":
        return True
    return bool(record.mode & 0o111)


# --------------------------------------------------------------------------------------
# Block rules, one function per rule. Each returns the lines it hit (0 = whole file).
# --------------------------------------------------------------------------------------

def _match_lines(pattern: "re.Pattern[str]", text: str, lines: _Lines) -> List[int]:
    out: List[int] = []
    for m in pattern.finditer(text):
        n = lines.of(m.start())
        if not out or out[-1] != n:
            out.append(n)
    return out


def _then_lines(pair: _Then, text: str, lines: _Lines) -> List[int]:
    """The lines where `pair.first` is followed by `pair.last` (see `_Then`)."""
    lasts = [m.start() for m in pair.last.finditer(text)]
    if not lasts:
        return []
    firsts = [(m.start(), m.end()) for m in pair.first.finditer(text)]
    if not firsts:
        return []
    ends = [end for _start, end in firsts]
    out: List[int] = []
    for at in lasts:
        # The earliest `first` that ends after the last stop (or line break) before `at`.
        floor = text.rfind("\n", 0, at) + 1
        for stop in pair.stops:
            floor = max(floor, text.rfind(stop, floor, at) + 1)
        index = bisect.bisect_left(ends, floor)
        if index < len(ends) and ends[index] <= at:
            n = lines.of(firsts[index][0])
            if not out or out[-1] != n:
                out.append(n)
    return out


def _check_lines(check: Any, text: str, lines: _Lines) -> List[int]:
    if isinstance(check, _Then):
        return _then_lines(check, text, lines)
    return _match_lines(check, text, lines)


def _cap_lines(text: str) -> Tuple[str, int]:
    """(the text with every line longer than MAX_LINE_CHARS emptied, the number of the first
    such line or 0). Line numbers are the same in both texts."""
    if len(text) <= MAX_LINE_CHARS:
        return text, 0
    pieces = text.split("\n")
    first = 0
    for index, piece in enumerate(pieces):
        if len(piece) > MAX_LINE_CHARS:
            pieces[index] = ""
            first = first or index + 1
    if not first:
        return text, 0
    return "\n".join(pieces), first


def _vcs_fold(name: str) -> str:
    """One path component as a case-insensitive file system and git itself compare it."""
    return name.translate(_VCS_IGNORABLE).casefold().split(":", 1)[0].rstrip(". ")


def vcs_control_path(path: str) -> bool:
    """True when a component of `path` names a version-control directory (or, for git, the
    file that points at one). Such a path is never stored, adopted, excepted or overridden."""
    for part in _parts(path):
        if _vcs_fold(part) in _VCS_NAMES:
            return True
    return False


def _git_dir_shape(names: Iterable[str]) -> bool:
    """True when a directory holding these (folded) names is, or is half of, what git takes
    for a repository.

    Git's own test (`is_git_directory`): `objects` and `refs` it can enter, and a valid
    `HEAD`; with a `commondir` file, `objects` and `refs` are looked for in the directory
    that file names instead. `config` is not part of git's test, but it is the file that
    does the harm, so `HEAD` beside `config` counts, and so does the shared half a
    `commondir` points at (`objects`, `refs` and `config` with no `HEAD`). Names only:
    whether `HEAD` reads as valid, or `objects` is a directory, is not asked.
    """
    names = set(names)
    if "head" in names:
        return ("objects" in names and "refs" in names) or "config" in names or "commondir" in names
    return "objects" in names and "refs" in names and "config" in names


def repo_layout_dirs(paths: Iterable[str]) -> "frozenset[str]":
    """The directories of a file set that have the shape of a git repository (see
    `_git_dir_shape`), as folded "/"-joined paths; "" is the root of the set. Every path
    counts by its names alone, whatever kind of entry it is."""
    children: Dict[str, set] = {}
    for path in paths:
        prefix = ""
        for part in _parts(path):
            name = _vcs_fold(part)
            children.setdefault(prefix, set()).add(name)
            prefix = prefix + "/" + name if prefix else name
    return frozenset(d for d, names in children.items() if _git_dir_shape(names))


def in_repo_layout(path: str, dirs: "frozenset[str]") -> bool:
    """True when `path` is a file somewhere under one of `dirs` (from `repo_layout_dirs`).
    Such a path is never stored, adopted, excepted or overridden."""
    if not dirs:
        return False
    if "" in dirs:
        return True
    prefix = ""
    for part in _parts(path)[:-1]:
        name = _vcs_fold(part)
        prefix = prefix + "/" + name if prefix else name
        if prefix in dirs:
            return True
    return False


def is_markdown(path: str) -> bool:
    """True for a markdown file, by its extension: the files H3 and H4 are read in."""
    parts = _parts(path)
    return bool(parts) and _ext(parts[-1].lower()) in _MARKDOWN_EXT


def _auto_loaded(parts: Sequence[str]) -> bool:
    """C10: a file a test runner, a shell hook or an editor picks up without being asked."""
    lowered = [p.lower() for p in parts]
    if not lowered:
        return False
    if lowered[-1] in _C10_NAMES or any(p in _C10_DIRS for p in lowered[:-1]):
        return True
    return len(lowered) >= 2 and lowered[-1] in _C10_IN_DIR.get(lowered[-2], ())


def _gated(lower: str, gates: Sequence[str]) -> bool:
    for gate in gates:
        if gate in lower:
            return True
    return False


def _h4(text: str, lines: _Lines) -> List[int]:
    out = _match_lines(_H4_FENCE, text, lines)
    for m in _H4.finditer(text):
        at = m.start()
        line_start = text.rfind("\n", 0, at) + 1
        before = text[line_start:at]
        if before[-1:].strip() == "" or before.count("\x60") % 2 == 0:
            out.append(lines.of(at))
    return sorted(set(out))


def _h2(parts: Sequence[str], text: Optional[str], lines: Optional[_Lines], kind: str) -> List[int]:
    # Lower-cased: on a case-insensitive file system ".CLAUDE/Settings.json" is the same file.
    parts = [p.lower() for p in parts]
    name = parts[-1]
    in_harness_dir = any(p in _H2_DIRS for p in parts[:-1])
    plugin_manifest = (name == "plugin.json" and len(parts) >= 2 and parts[-2] == _H2_PLUGIN_DIR)
    by_name = name in _H2_NAMES or in_harness_dir or plugin_manifest
    if by_name and kind == KIND_SKILL:
        return [0]
    if not (by_name or name == "plugin.json"):
        return []
    # By content: does the file declare hooks, MCP servers or permissions?
    if text is None or lines is None:
        return []
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict):
        hit = [k for k in _H2_KEYS if k in doc]
        if not hit:
            return []
        at = text.find('"%s"' % hit[0])
        return [lines.of(at) if at >= 0 else 0]
    if doc is not None:
        return []
    return _match_lines(_H2_KEY_LINE, text, lines)[:1]


def _h3_frontmatter(text: str) -> Optional[Tuple[int, List[str]]]:
    """(number of the first line after the opening mark, the lines after it), or None when
    the file does not open with a frontmatter mark. Leading blank lines are skipped, and a
    carriage return or a unicode line separator counts as a line break: whether a reader of
    the file does the same is not something this module can know."""
    rows = _H3_BREAKS.sub("\n", text).split("\n")
    for index, row in enumerate(rows):
        if row.strip() == "":
            continue
        if _H3_OPEN.match(row) or _H3_OPEN_INLINE.match(row):
            return index + 2, rows[index:]
        return None
    return None


def _h3_tool_value(key: str, value: str) -> bool:
    """True when a tool key's value (one line of it) grants an unscoped tool, or holds a
    token this check cannot read as a tool name."""
    value = value.split(" #", 1)[0].strip()
    if value.startswith("#") or _H3_BLOCK_SCALAR.match(value):
        return False
    if _H3_UNSCOPED.search(value):
        return True
    for token in _H3_SPLIT.split(_H3_SCOPED.sub(" ", value)):
        token = token.lstrip("-")
        if token == "":
            continue
        if token == "*" or not _H3_TOOL_NAME.match(token):
            return True
        if key in _H3_GRANT_KEYS and token == "Bash":
            return True
    return False


def _h3(text: str) -> List[int]:
    """Lines of the frontmatter that grant unscoped tools, or that are written in a form this
    check cannot read with certainty.

    The check reads a plain subset of YAML: top-level `key: value` lines that start in the
    first column with an unquoted key, indented continuation lines, list items and comments.
    Anything else (a quoted or indented top-level key, a flow mapping, a complex or merge
    key, an anchor, alias, tag or escape in a tool key's value, a second document) could
    spell the same grant in a way a line reader does not see, so it is a hit, not a pass.

    A markdown file whose first line is three dashes is read as frontmatter, to the next
    such line or the end of the file: a reader that takes an unclosed block to the end
    exists, so "no closing mark" cannot mean "no frontmatter". A form this check cannot
    read is reported ONCE per file, at its first line; a grant is reported on its own line.
    """
    found = _h3_frontmatter(text)
    if found is None:
        return []
    first_number, rows = found
    grants: List[int] = []
    unreadable = 0                            # the first line in a form this check cannot read
    if _H3_OPEN_INLINE.match(rows[0]):
        unreadable = first_number - 1         # content on the mark's own line
    key = ""
    for number, line in enumerate(rows[1:], first_number):
        if line.rstrip() == "---":
            break
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            if not key:
                unreadable = unreadable or number     # an indented line with no key above it
                continue
            value = line
        elif line.startswith("-") and line[1:2] in ("", " ", "\t") and key:
            value = line
        else:
            m = _H3_KEY.match(line)
            if m is None:
                key = ""
                unreadable = unreadable or number     # a first-column line that is no plain key
                continue
            key = m.group(1).lower()
            value = m.group(2)
        if key in _H3_TOOL_KEYS and _h3_tool_value(key, value):
            grants.append(number)
    return sorted(set(grants + ([unreadable] if unreadable else [])))


def _h6(name: str, text: Optional[str], lines: Optional[_Lines]) -> List[int]:
    lower = name.lower()
    if lower.endswith(".pth") or lower in _H6_SITE_NAMES:
        return [0]
    if text is None or lines is None:
        return []
    if lower == "package.json":
        try:
            doc = json.loads(text)
        except ValueError:
            return []
        scripts = doc.get("scripts") if isinstance(doc, dict) else None
        if not isinstance(scripts, dict):
            return []
        out = []
        for hook in _H6_LIFECYCLE:
            command = scripts.get(hook)
            if isinstance(command, str) and _H6_NET.search(command):
                at = text.find('"%s"' % hook)
                out.append(lines.of(at) if at >= 0 else 0)
        return out
    if lower == "setup.py":
        return _match_lines(_H6_SETUP_NET, text, lines)
    return []


def _h7_path(raw: str) -> bool:
    path = raw.replace("\\", "/")
    if path.startswith("/") or _DRIVE.match(path):
        return True
    if any(ord(c) < 32 for c in path):
        return True
    return ".." in path.split("/")


def _is_archive(name: str, data: bytes) -> bool:
    lower = name.lower()
    if lower.endswith(_ARCHIVE_EXT):
        return True
    if data.startswith(_ARCHIVE_MAGIC):
        return True
    return data[257:262] == b"ustar"


def _is_opaque(name: str, data: bytes, text: Optional[str]) -> bool:
    ext = _ext(name.lower())
    if ext in _COMPILED_EXT or data.startswith(_BINARY_MAGIC):
        return True
    if text is not None:
        return False
    magic = _IMAGE_MAGIC.get(ext)
    return not (magic and data.startswith(magic))


# --------------------------------------------------------------------------------------
# The scan
# --------------------------------------------------------------------------------------

def _scan_record(record: FileRecord, kind: str, want_block: bool, want_caution: bool,
                 in_layout: bool = False) -> List[Tuple[str, int]]:
    """(rule id, line) pairs for one record, block rules first, in rule order. `in_layout`
    says the record sits under a directory with the shape of a repository."""
    hits: List[Tuple[str, int]] = []
    parts = _parts(record.path)
    name = parts[-1] if parts else ""
    data = record.data

    if record.entry != ENTRY_FILE:
        # Never inspected further: there is no content to read, by construction.
        return [("H7", 0)] if want_block else []

    size = record.size if record.size is not None else len(data)
    oversize = size > MAX_FILE_BYTES
    archive = (not oversize) and _is_archive(name, data)
    text = None if (oversize or archive) else _decode(data)
    lines = _Lines(text) if text is not None else None
    ext = _ext(name.lower())

    lower = text.lower() if text is not None else ""
    # The line patterns read `capped`: the text without its over-long lines.
    capped, long_line = _cap_lines(text) if text is not None else ("", 0)
    capped_lines = _Lines(capped) if long_line else lines
    capped_lower = capped.lower() if long_line else lower
    markdown = ext in _MARKDOWN_EXT
    runnable = text is not None and is_executable(record)

    if want_block:
        if text is not None and lines is not None and not data.isascii():
            hits.extend(("H1", n) for n in _match_lines(_H1, text, lines))
        if parts:
            hits.extend(("H2", n) for n in _h2(parts, text, lines, kind))
        if text is not None and capped_lines is not None and markdown:
            hits.extend(("H3", n) for n in _h3(capped))
            if "!\x60" in capped or "\x60!" in capped:
                hits.extend(("H4", n) for n in _h4(capped, capped_lines))
        if capped_lines is not None and runnable:
            found: set = set()
            for gates, checks in _H5:
                if _gated(capped_lower, gates):
                    for check in checks:
                        found.update(_check_lines(check, capped, capped_lines))
            hits.extend(("H5", n) for n in sorted(found))
        hits.extend(("H6", n) for n in _h6(name, text, lines))
        if (oversize or archive or _h7_path(record.path) or name == ".gitmodules" or in_layout
                or vcs_control_path(record.path) or data.startswith(_LFS_PREFIX)):
            hits.append(("H7", 0))
        if not oversize and not archive and _is_opaque(name, data, text):
            hits.append(("H8", 0))
        if text is not None and lines is not None and _gated(lower, _H9_GATES):
            hits.extend(("H9", n) for n in _match_lines(_H9, text, lines))
        if long_line and (markdown or runnable):
            hits.append(("H11", long_line))

    if want_caution and _auto_loaded(parts):
        hits.append((_AUTO_LOADED_CAUTION[0], 0))
    if want_caution and text is not None and capped_lines is not None:
        for rid, gates, check in _CAUTION_COMPILED:
            if _gated(capped_lower, gates):
                hits.extend((rid, n) for n in _check_lines(check, capped, capped_lines))
        if long_line and not (markdown or runnable):
            hits.append((_UNCHECKED_LINE_CAUTION[0], long_line))
    return hits


def scan(records: Iterable[FileRecord], kind: str = KIND_SKILL,
         classes: Sequence[str] = (BLOCK, CAUTION), context_paths: Iterable[str] = ()) -> List[Finding]:
    """Run the rules over a file set. Findings come back in input order, then rule order.

    `kind` is the target kind and changes only H2 (by presence for a skill, by content
    for a repo). `classes` selects block rules, caution rules or both; the hook and the
    install check pass `(BLOCK,)`. `context_paths` are paths of the same tree that are not
    being scanned: they count toward the repository-layout check and get no finding.
    """
    if kind not in KINDS:
        raise ValueError("kind must be one of %s" % (KINDS,))
    for c in classes:
        if c not in (BLOCK, CAUTION):
            raise ValueError("unknown rule class %r" % (c,))
    want_block = BLOCK in classes
    want_caution = CAUTION in classes

    records = list(records)
    layout: "frozenset[str]" = frozenset()
    if want_block:
        layout = repo_layout_dirs([r.path for r in records] + list(context_paths))

    findings: List[Finding] = []
    count = 0
    total = 0
    for record in records:
        if record.entry not in ENTRIES:
            raise ValueError("unknown entry kind %r" % (record.entry,))
        count += 1
        total += record.size if record.size is not None else len(record.data)
        hits = _scan_record(record, kind, want_block, want_caution,
                            bool(layout) and in_repo_layout(record.path, layout))
        if not hits:
            continue
        digest = sha256_hex(record.data) if (record.entry == ENTRY_FILE and record.size is None) else ""
        seen = set()
        for rid, line in hits:
            if (rid, line) in seen:
                continue
            seen.add((rid, line))
            findings.append(Finding(rid, RULES[rid].rule_class, record.file_id, line, digest))
    if want_block and (count > MAX_FILES or total > MAX_TOTAL_BYTES):
        findings.append(Finding("H7", BLOCK, SET_FILE_ID, 0, ""))
    return findings


def scan_blocks(records: Iterable[FileRecord], kind: str = KIND_SKILL,
                context_paths: Iterable[str] = ()) -> List[Finding]:
    """Block rules only: what the pre-commit arm and the install check run."""
    return scan(records, kind, (BLOCK,), context_paths)
