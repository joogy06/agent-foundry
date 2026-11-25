#!/usr/bin/env python3
"""contract_lint.py -- #313. The describe -> question -> done-when contract, checked in the text.

Design docs/plans/2026-09-25-apply-the-contract-design.md sections 3, 4 and 7. Agents looped
through never-ending improvement because the definition of done lived only in the orchestrator's
head. The contract now lives in the spawn templates and loop texts themselves; this lint is the
mechanical half (user decision U2) that stops a later edit quietly dropping it.

WHAT IT IS, AND WHAT IT IS NOT
------------------------------
Template REGRESSION protection, not universal runtime enforcement. It proves the pinned templates
and loops still carry their fields and bounds. It cannot prove that a spawn the main loop composes
by hand carries them; skills/_meta/spawn-brief.md says the same. It runs in pytest only, never in
the commit hook.

MARKERS -- only an exact marker line counts
-------------------------------------------
A marker is a line that is NOTHING BUT the marker, optionally behind a `#` or `//` comment lead
(so it can sit inside a fenced bash block or a JS file). Prose that quotes a marker inline, as this
docstring does, is never a marker. The two shapes:

    spawn template : an HTML comment `spawn-brief.v1 id=<id>` on the line before the template
    bounded loop   : an HTML comment `contract:loop id=<id> bound=<N> on_exhaust=user|stop|escalate`

A template's extent is the fenced block that opens right after its marker, or else every line up
to the next marker, an end marker (`/spawn-brief.v1`), a fence line, or MAX_EXTENT lines.

RULES
-----
  C001 E  a marked template is missing, or has empty, Goal / Non-goals / Done when / Stop when /
          Open questions, or a field EXTRA_FIELDS adds for its id (and any malformed spawn-brief marker)
  C002 E  a marked loop has no integer bound in 1..5, or no valid on_exhaust
  C003 E  the pinned inventory (SPAWN_BRIEFS, LOOPS) differs from the markers found: a deleted,
          moved, unpinned or duplicated marker, or a stale exclusion
  C004 W  an unmarked `Agent(` / `subagent_type` template candidate (advisory, never blocking)
  C005 E  check-plan: a plan's `covers` union differs from the design's non-integration DW set

    contract_lint.py lint [ROOT] [--warnings] [--json]
    contract_lint.py check-plan PLAN [--design DOC] [--json]
    contract_lint.py check-verdict VERDICT.json --design DOC [--json]

Exit: 0 clean, 2 errors, 3 bad input. Stdlib (+ PyYAML for a YAML plan, when present).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

try:  # a YAML plan needs PyYAML; a JSON plan does not
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

#: The tree this file ships in: the repo (skills/_meta/..) or an installed home (~/.claude).
TREE = Path(__file__).resolve().parents[2]

EXIT_OK, EXIT_ERRORS, EXIT_BAD_INPUT = 0, 2, 3

# --------------------------------------------------------------------------- #
# The pinned inventory. Adding, moving or deleting a marker is a deliberate edit HERE too.
# --------------------------------------------------------------------------- #
#: id -> path of every spawn template (Markdown templates AND runtime prompt producers).
SPAWN_BRIEFS: Mapping[str, str] = {
    "spawn-brief.canonical": "skills/_meta/spawn-brief.md",
    # forge is an entry file plus step references (#344 WP-4): each template is pinned to the
    # reference that holds it, so a template moved back or into another file is a C003.
    "forge.approach": "skills/forge/references/02-design-team.md",
    "forge.ux": "skills/forge/references/02-design-team.md",
    "forge.challenger-claude": "skills/forge/references/02-design-team.md",
    "forge.challenger-codex": "skills/forge/references/03-codex-seats.md",
    "forge.explorer-codex": "skills/forge/references/03-codex-seats.md",
    "forge.bob": "skills/forge/references/09-bob-handoff.md",
    "forge.d21-reviewer": "skills/forge/references/10-close-out.md",
    "forge.spec-reviewer": "skills/forge/references/08-spec-review.md",
    "alf.bob": "agents/alf.md",
    "agent-teams.lead": "skills/agent-teams/SKILL.md",
    "team-manager.specialist": "skills/team-manager/SKILL.md",
    "adversarial-team-brainstorm.team": "skills/adversarial-team-brainstorm/SKILL.md",
    "adversarial-team-brainstorm.codex-team": "skills/adversarial-team-brainstorm/SKILL.md",
    "codex-orchestration.delta-challenger": "skills/codex-orchestration/SKILL.md",
    "cross-cli-deliberation.ballot": "skills/cross-cli-deliberation/references/ballot-template.md",
    "bob-stage.stage": "workflows/bob-stage.js",
}

#: id -> (path, bound, on_exhaust) of every bounded loop named in design section 4.
LOOPS: Mapping[str, Tuple[str, int, str]] = {
    "forge.d21-fix-loop": ("skills/forge/references/10-close-out.md", 2, "user"),
    "development-lifecycle.review": ("skills/development-lifecycle/SKILL.md", 2, "user"),
    "qa-reviewer.re-review": ("skills/qa-reviewer/SKILL.md", 1, "user"),
    "challenger.re-challenge": ("skills/challenger/SKILL.md", 2, "user"),
    "alf.carry-over": ("agents/alf.md", 2, "user"),
    "bob-stage.fix-round": ("workflows/bob-stage.js", 2, "user"),
}

#: Deliberately unmarked template candidates (C004), each with its reason.
EXCLUSIONS: Mapping[str, str] = {
    "agents/pa.md": "routing rows: pa names which agent to spawn, the spawn brief is composed elsewhere",
    "agents/wiki.md": "routing rows: the Tier 3 row names the spawn shape, not a brief",
}

FIELDS: Tuple[Tuple[str, str], ...] = (
    ("Goal", r"(?<![\w-])goal:[ \t]*\S"),
    ("Non-goals", r"non-goals:[ \t]*\S"),
    ("Open questions", r"open questions:[ \t]*\S"),
    ("Done when", r"done[ -]when:[ \t]*\S"),
    ("Stop when", r"stop[ -]when:[ \t]*\S"),
)
#: Fields only some templates carry: id -> (name, pattern). #345: a reviewer who is not told what the
#: cycle is for judges against the rule it was handed. Line-anchored and case-sensitive, so that prose
#: mentioning the Purpose cannot stand in for the field.
_PURPOSE: Tuple[str, str] = ("Purpose", r"^[ \t]*Purpose:[ \t]*\S")
EXTRA_FIELDS: Mapping[str, Tuple[Tuple[str, str], ...]] = {
    "forge.spec-reviewer": (_PURPOSE,),
    "forge.d21-reviewer": (_PURPOSE,),
}
ON_EXHAUST = ("user", "stop", "escalate")
BOUND_RANGE = range(1, 6)
MAX_EXTENT = 80

_LEAD = r"^(?:(?://|#)[ \t]*)?"
_SPAWN = re.compile(_LEAD + r"<!-- spawn-brief\.v1 id=([a-z0-9][a-z0-9._-]*) -->$")
_SPAWN_LOOSE = re.compile(_LEAD + r"<!--\s*spawn-brief\.v1\b.*-->$")
_END = re.compile(_LEAD + r"<!-- /spawn-brief\.v1 -->$")
_LOOP_LOOSE = re.compile(_LEAD + r"<!--\s*contract:loop\b(.*?)-->$")
_ATTR = re.compile(r"([a-z_]+)=(\S+)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CANDIDATE = re.compile(r"\bAgent\(|\bsubagent_type\b")
#: In a workflow script the spawn is the lowercase runtime call (fix round 1 m5).
_CANDIDATE_JS = re.compile(r"\bAgent\(|\bsubagent_type\b|\bagent\(")

SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", "fixtures", ".pytest_cache"})


class Finding:
    __slots__ = ("path", "line", "code", "severity", "message")

    def __init__(self, path: str, line: int, code: str, severity: str, message: str):
        self.path, self.line, self.code = path, line, code
        self.severity, self.message = severity, message

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "line": self.line, "code": self.code,
                "severity": self.severity, "message": self.message}

    def __str__(self) -> str:
        return f"{self.code} {self.severity} {self.path}:{self.line}  {self.message}"


# --------------------------------------------------------------------------- #
# One file
# --------------------------------------------------------------------------- #
def _extent(lines: Sequence[str], start: int) -> Tuple[int, int]:
    """[begin, end) of the template whose marker is at index `start`."""
    i = start + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and _FENCE.match(lines[i]):          # a fenced block opens right here
        j = i + 1
        while j < len(lines) and not _FENCE.match(lines[j]):
            j += 1
        return i, min(j + 1, len(lines))
    end = start + 1
    while end < len(lines) and end - start <= MAX_EXTENT:
        s = lines[end].strip()
        if _SPAWN_LOOSE.match(s) or _END.match(s) or _FENCE.match(lines[end]):
            break
        end += 1
    return start + 1, end


def missing_fields(text: str) -> List[str]:
    """The contract fields a template text lacks, or carries empty."""
    return [name for name, pat in FIELDS if re.search(pat, text, re.IGNORECASE) is None]


def scan_text(rel: str, text: str) -> Tuple[List[Finding], Dict[str, int], Dict[str, Tuple[int, int, str]],
                                            List[Tuple[int, int]]]:
    """(findings, spawn ids -> line, loop ids -> (line, bound, on_exhaust), extents) for one file."""
    findings: List[Finding] = []
    spawns: Dict[str, int] = {}
    loops: Dict[str, Tuple[int, int, str]] = {}
    extents: List[Tuple[int, int]] = []
    lines = text.splitlines()
    for idx, raw in enumerate(lines):
        s = raw.strip()
        lineno = idx + 1
        m = _SPAWN.match(s)
        if m:
            sid = m.group(1)
            if sid in spawns:
                findings.append(Finding(rel, lineno, "C003", "E", f"duplicate spawn-brief id {sid!r}"))
            spawns[sid] = lineno
            b, e = _extent(lines, idx)
            extents.append((idx, e))
            body = "\n".join(lines[b:e])
            gaps = missing_fields(body)
            gaps += [name for name, pat in EXTRA_FIELDS.get(sid, ()) if re.search(pat, body, re.MULTILINE) is None]
            if gaps:
                findings.append(Finding(rel, lineno, "C001", "E",
                                        f"template {sid!r} is missing or has empty: {', '.join(gaps)}"))
            continue
        if _SPAWN_LOOSE.match(s):
            findings.append(Finding(rel, lineno, "C001", "E", "malformed spawn-brief marker (needs `id=<id>`)"))
            continue
        m = _LOOP_LOOSE.match(s)
        if m:
            attrs = dict(_ATTR.findall(m.group(1)))
            lid = attrs.get("id")
            bound_txt = attrs.get("bound", "")
            on_exhaust = attrs.get("on_exhaust")
            problems = []
            if not lid:
                problems.append("no id")
            bound = int(bound_txt) if re.fullmatch(r"[0-9]+", bound_txt) else None
            if bound is None or bound not in BOUND_RANGE:
                problems.append(f"bound {bound_txt or '(none)'!s} is not an integer in 1..5")
            if on_exhaust not in ON_EXHAUST:
                problems.append(f"on_exhaust {on_exhaust or '(none)'!s} is not one of {'|'.join(ON_EXHAUST)}")
            if problems:
                findings.append(Finding(rel, lineno, "C002", "E",
                                        f"loop {lid or '?'}: " + "; ".join(problems)))
            if lid:
                if lid in loops:
                    findings.append(Finding(rel, lineno, "C003", "E", f"duplicate loop id {lid!r}"))
                loops[lid] = (lineno, bound if bound is not None else -1, on_exhaust or "")
    return findings, spawns, loops, extents


def _candidates(rel: str, text: str, extents: List[Tuple[int, int]]) -> List[Finding]:
    out = []
    pat = _CANDIDATE_JS if rel.endswith(".js") else _CANDIDATE
    for idx, raw in enumerate(text.splitlines()):
        if not pat.search(raw):
            continue
        if any(start <= idx < end for start, end in extents):
            continue
        out.append(Finding(rel, idx + 1, "C004", "W", "unmarked Agent/subagent_type template candidate"))
    return out


# --------------------------------------------------------------------------- #
# A tree
# --------------------------------------------------------------------------- #
def iter_targets(root: Path) -> Iterable[Path]:
    """agents/*.md, skills/**/*.md and workflows/*.js under `root`."""
    agents = root / "agents"
    if agents.is_dir():
        yield from sorted(agents.glob("*.md"))
    skills = root / "skills"
    if skills.is_dir():
        for p in sorted(skills.rglob("*.md")):
            if not SKIP_DIRS.intersection(p.relative_to(skills).parts):
                yield p
    workflows = root / "workflows"
    if workflows.is_dir():
        yield from sorted(workflows.glob("*.js"))


def lint_tree(root: Path, *, inventory: bool = True) -> List[Finding]:
    findings: List[Finding] = []
    found_spawns: Dict[str, Tuple[str, int]] = {}
    found_loops: Dict[str, Tuple[str, int, int, str]] = {}
    for path in iter_targets(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(Finding(rel, 0, "C003", "E", f"unreadable ({type(exc).__name__})"))
            continue
        f, spawns, loops, extents = scan_text(rel, text)
        findings.extend(f)
        for sid, line in spawns.items():
            if sid in found_spawns:
                findings.append(Finding(rel, line, "C003", "E",
                                        f"duplicate spawn-brief id {sid!r} (also {found_spawns[sid][0]})"))
            found_spawns[sid] = (rel, line)
        for lid, (line, bound, oe) in loops.items():
            if lid in found_loops:
                findings.append(Finding(rel, line, "C003", "E",
                                        f"duplicate loop id {lid!r} (also {found_loops[lid][0]})"))
            found_loops[lid] = (rel, line, bound, oe)
        if rel not in EXCLUSIONS:
            findings.extend(_candidates(rel, text, extents))
    if inventory:
        findings.extend(check_inventory(root, found_spawns, found_loops))
    return findings


def check_inventory(root: Path, spawns: Mapping[str, Tuple[str, int]],
                    loops: Mapping[str, Tuple[str, int, int, str]]) -> List[Finding]:
    out: List[Finding] = []
    for sid, path in SPAWN_BRIEFS.items():
        got = spawns.get(sid)
        if got is None:
            out.append(Finding(path, 0, "C003", "E", f"pinned template {sid!r} has no marker (deleted?)"))
        elif got[0] != path:
            out.append(Finding(got[0], got[1], "C003", "E", f"template {sid!r} is pinned to {path}"))
    for sid, (rel, line) in spawns.items():
        if sid not in SPAWN_BRIEFS:
            out.append(Finding(rel, line, "C003", "E", f"template {sid!r} is not in the pinned inventory"))
    for lid, (path, bound, oe) in LOOPS.items():
        got = loops.get(lid)
        if got is None:
            out.append(Finding(path, 0, "C003", "E", f"pinned loop {lid!r} has no marker (deleted?)"))
        elif (got[0], got[2], got[3]) != (path, bound, oe):
            out.append(Finding(got[0], got[1], "C003", "E",
                               f"loop {lid!r} is pinned as {path} bound={bound} on_exhaust={oe}"))
    for lid, (rel, line, _b, _o) in loops.items():
        if lid not in LOOPS:
            out.append(Finding(rel, line, "C003", "E", f"loop {lid!r} is not in the pinned inventory"))
    for rel in EXCLUSIONS:
        if not (root / rel).is_file():
            out.append(Finding(rel, 0, "C003", "E", "stale exclusion: the file does not exist"))
    return out


# --------------------------------------------------------------------------- #
# The done-when chain: design DWs, plan covers, review verdicts
# --------------------------------------------------------------------------- #
#: #313 round 3: the Done-when parser fails CLOSED on anything it cannot classify. It targets
#: honest mistakes, not a determined agent (the store and the docs are agent-writable anyway).
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE_OPEN = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_DONE_WHEN = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)*\.?\s+)?Done when\b", re.IGNORECASE)
#: A line that LOOKS like a heading mentioning Done when; one the parser cannot classify is an error.
_DW_HEADINGISH = re.compile(r"^\s*(?:#|\*\*|__|<h[1-6])", re.IGNORECASE)
#: A canonical DW DEFINITION: a bullet or numbered item (optionally a checkbox), a table row's first
#: cell, or a sub-heading, then the id (optionally bold), then optionally `(integration)` right after.
_DW_DEF = re.compile(
    r"^ {0,3}(?:[-*]\s+|[0-9]+\.\s+|\|\s*|#{2,6}\s+)?(?:\[[ xX]\]\s+)?(?:\*\*)?DW-0*([0-9]+)(?![0-9])"
    r"(?:\*\*)?:?(?:\*\*)?\s*(\(integration\))?(?=\s|$|[:|—–-]|\*\*)", re.IGNORECASE)
#: ANY DW-like reference: `DW` then an optional dash-like/space/underscore then a digit.
_DW_ANY = re.compile(r"DW[\s_‐-―−-]?[0-9]", re.IGNORECASE)
_DW_CANON_REF = re.compile(r"\bDW-0*([0-9]+)\b")
#: Line leads that make a DW reference ambiguous: a quote, a non-ASCII bullet, a link, strikethrough.
_DW_AMBIGUOUS = re.compile(r"^\s*(?:>|•)|\[\s*DW|~~\s*DW", re.IGNORECASE)
#: What may precede a DW id at the start of a line without it being prose.
_LEAD = re.compile(r"^\s*(?:[-*+]\s+|[0-9]+[.)]\s+|\|\s*|#{1,6}\s+)?(?:\[[ xX]\]\s*)?[*_`~\s]*")
DW_ID = re.compile(r"^DW-[0-9]+$")


class ContractError(ValueError):
    """Bad input: an unreadable plan, design or verdict."""


def _split_lines(text: str) -> List[str]:
    """`\n` only, after `\r\n` / `\r` normalisation, and without a leading BOM -- never
    str.splitlines, which also splits on \x0c, \x85 and U+2028 (#313 round 3 item 1)."""
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _fence_mask(lines: Sequence[str]) -> Tuple[List[bool], Optional[int]]:
    """(inside-or-on-a-fence per line, index of an unterminated opener). CommonMark rules: an opener
    is indented at most 3 spaces; a backtick opener's info string has no backtick (so ```x``` is
    inline code); it closes only on the same character, at least as long, with nothing after."""
    mask = [False] * len(lines)
    open_char = open_len = open_at = None
    for i, line in enumerate(lines):
        if open_char is None:
            m = _FENCE_OPEN.match(line)
            if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
                open_char, open_len, open_at = m.group(2)[0], len(m.group(2)), i
                mask[i] = True
        else:
            mask[i] = True
            s = line
            stripped = s.lstrip(" ")
            if (len(s) - len(stripped) <= 3 and stripped.rstrip() and set(stripped.rstrip()) == {open_char}
                    and len(stripped.rstrip()) >= open_len):
                open_char = open_len = open_at = None
    return mask, open_at


def _headings(lines: Sequence[str], mask: Sequence[bool]) -> Tuple[List[Tuple[int, int, str]], List[int]]:
    """(headings, ambiguous underlines). Headings are (index, level, text) for every ATX and setext
    heading outside fences. A setext underline counts ONLY under a paragraph that starts at column 0
    and is not a list item, quote or table row (#313 R3-N1). Under a list item it is a thematic break
    or lazy text, never a heading. Under an indented, quoted or table paragraph it is AMBIGUOUS and
    returned separately, so the caller can fail closed near the Done-when section."""
    out: List[Tuple[int, int, str]] = []
    ambiguous: List[int] = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        m = _ATX.match(line)
        if m:
            out.append((i, len(m.group(1)), (m.group(2) or "").strip()))
            continue
        s = _SETEXT.match(line)
        if not (s and i > 0 and not mask[i - 1] and lines[i - 1].strip() and not _ATX.match(lines[i - 1])):
            continue
        j = i - 1                                            # the paragraph's first line
        while j > 0 and lines[j - 1].strip() and not mask[j - 1] and not _ATX.match(lines[j - 1]) \
                and not _SETEXT.match(lines[j - 1]):
            j -= 1
        first = lines[j]
        if re.match(r"^(?:[-*+]\s|[0-9]+[.)]\s)", first.lstrip()):
            continue                                         # a list: thematic break / lazy text, not a heading
        if first[:1].isspace() or re.match(r"^\s*(?:>|\|)", first):
            ambiguous.append(i)
            continue
        out.append((j, 1 if s.group(1)[0] == "=" else 2, " ".join(l.strip() for l in lines[j:i])))
    return out, ambiguous


def _unbold(text: str) -> str:
    t = text.strip()
    for w in ("**", "__"):
        if t.startswith(w) and t.endswith(w) and len(t) > 2 * len(w):
            t = t[len(w):-len(w)].strip()
    return t


def design_dws(text: str) -> Optional[Dict[str, bool]]:
    """DW id -> is-integration, from the design's Done when section; None when it has none.

    THE one parser: check-plan and check-verdict both call it. It FAILS CLOSED (#313 fix rounds 1 E,
    2 items 1-2, round 3 items 1-2): fences follow CommonMark (and an unterminated fence before or
    in the section is an error); there is exactly one Done when heading (ATX or setext, 0-3 space
    indent, bold text allowed); a heading-like line mentioning Done when that is not one is an
    error; inside the section every line carrying a DW-like reference must be a canonical definition
    or plain prose citing an already-defined id; ids normalise (DW-01 is DW-1); duplicates, and a
    section with no DW, are errors. HONEST LIMITS: unicode confusables beyond these forms and
    HTML-comment tricks beyond the duplicate-heading refusal are not handled."""
    lines = _split_lines(text)
    mask, unterminated = _fence_mask(lines)
    heads, ambiguous = _headings(lines, mask)
    dw_heads = [(i, lvl) for i, lvl, txt in heads if _DONE_WHEN.match(_unbold(txt))]
    head_idx = {i for i, _, _ in heads}
    for i, line in enumerate(lines):
        if not mask[i] and i not in head_idx and "done when" in line.lower() and _DW_HEADINGISH.match(line) \
                and not re.match(r"^\s*(?:\*\*|__)[^*_]*(?:\*\*|__)\s*\S", line):
            raise ContractError(f"line {i + 1} looks like a Done when heading but is not one: {line.strip()[:80]!r}")
    if len(dw_heads) > 1:
        raise ContractError(f"{len(dw_heads)} Done when headings (lines {', '.join(str(i + 1) for i, _ in dw_heads)}); "
                            "a design has exactly one")
    if not dw_heads:
        if unterminated is not None:
            raise ContractError(f"line {unterminated + 1}: an unterminated code fence may hide the Done when section")
        return None
    start, level = dw_heads[0]
    end = next((i for i, lvl, _ in heads if i > start and lvl <= level), len(lines))
    near = [k for k in ambiguous if start < k <= end]
    if near:
        raise ContractError(f"line {near[0] + 1}: a `---`/`===` line under an indented, quoted or table paragraph "
                            "in or right after the Done when section is ambiguous (heading or not); add a blank line")
    if unterminated is not None and unterminated < end:
        raise ContractError(f"line {unterminated + 1}: an unterminated code fence before or in the Done when section")
    setext_underline = {k for k, line in enumerate(lines) if _SETEXT.match(line) and not mask[k]}
    dws: Dict[str, bool] = {}
    for i in range(start + 1, end):
        line = lines[i]
        if mask[i] or i in setext_underline or not _DW_ANY.search(line):
            continue
        m = _DW_DEF.match(line)
        if m and not _DW_AMBIGUOUS.search(line):
            dw = f"DW-{int(m.group(1))}"
            if dw in dws:
                raise ContractError(f"line {i + 1}: {dw} is defined twice in the Done when section")
            dws[dw] = m.group(2) is not None
            continue
        rest = line[_LEAD.match(line).end():]
        refs = _DW_ANY.findall(line)
        canon = [f"DW-{int(n)}" for n in _DW_CANON_REF.findall(line)]
        prose = (not _DW_AMBIGUOUS.search(line) and not _DW_ANY.match(rest)
                 and len(canon) == len(refs) and all(c in dws for c in canon))
        if not prose:
            raise ContractError(f"line {i + 1} carries a DW reference that is neither a definition nor prose citing a "
                                f"defined DW: {line.strip()[:80]!r} (use `- DW-n:`, `| DW-n |` or `### DW-n`)")
    if not dws:
        raise ContractError("the design has a Done when heading but no DW-<n> parses under it "
                            "(use bullets, table rows or sub-headings starting with the id)")
    return dws


def load_plan(path: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read plan {path}: {exc}") from exc
    if path.suffix.lower() == ".json":
        doc = json.loads(text)
    elif yaml is not None:
        doc = yaml.safe_load(text)
    else:  # pragma: no cover
        raise ContractError("PyYAML is not installed; pass a JSON plan")
    if not isinstance(doc, dict) or not isinstance(doc.get("work_packages"), list):
        raise ContractError(f"{path} is not a work-packages.v1 plan")
    return doc


def resolve_design(plan: Mapping[str, Any], plan_path: Path, design: Optional[Path]) -> Optional[Path]:
    if design is not None:
        return design
    name = plan.get("design_doc")
    if not isinstance(name, str) or not name:
        return None
    p = Path(name)
    if p.is_absolute():
        return p
    root = plan.get("project_root")
    for base in ([Path(root)] if isinstance(root, str) and root else []) + [plan_path.parent]:
        if (base / p).is_file():
            return base / p
    return None


def check_plan(plan: Mapping[str, Any], dws: Optional[Mapping[str, bool]], rel: str = "plan") -> List[Finding]:
    """C005: every WP carries acceptance criteria; when the design has DWs, every WP carries
    `covers`, cites only known non-integration DWs, and the union equals that set."""
    out: List[Finding] = []
    union: Set[str] = set()
    known = set(dws or {})
    integration = {d for d, is_int in (dws or {}).items() if is_int}
    for wp in plan.get("work_packages") or []:
        wid = wp.get("id", "?") if isinstance(wp, dict) else "?"
        if not isinstance(wp, dict):
            out.append(Finding(rel, 0, "C005", "E", "a work package is not a mapping"))
            continue
        crit = wp.get("acceptance_criteria")
        if not isinstance(crit, list) or not [c for c in crit if isinstance(c, str) and c.strip()]:
            out.append(Finding(rel, 0, "C005", "E", f"{wid}: acceptance_criteria is empty (it is the WP's done-when)"))
        covers = wp.get("covers")
        if covers is None:
            if dws:
                out.append(Finding(rel, 0, "C005", "E", f"{wid}: no `covers` although the design has a Done when section"))
            continue
        if not isinstance(covers, list) or not all(isinstance(c, str) and DW_ID.match(c) for c in covers):
            out.append(Finding(rel, 0, "C005", "E", f"{wid}: `covers` must be a list of DW-<n> ids"))
            continue
        for c in covers:
            if c not in known:
                out.append(Finding(rel, 0, "C005", "E", f"{wid}: covers unknown {c}"))
            elif c in integration:
                out.append(Finding(rel, 0, "C005", "E",
                                   f"{wid}: covers {c}, an (integration) DW verified at finalize, never by one WP"))
        union.update(covers)
    if dws:
        uncovered = sorted(known - integration - union, key=lambda d: int(d[3:]))
        if uncovered:
            out.append(Finding(rel, 0, "C005", "E", f"uncovered DWs: {', '.join(uncovered)}"))
    return out


RULINGS = ("met", "unmet", "unverified")


def verdict_problems(verdict: Mapping[str, Any], dws: Mapping[str, bool]) -> Tuple[List[str], bool]:
    """(problems, done) for a reviewer's DW verdict {DW-n: {ruling, evidence}}. Every design DW,
    integration included, is ruled met | unmet | unverified WITH evidence; `unverified` counts as
    not met, so done = every DW met and no problem. The existing gates still apply on top."""
    problems: List[str] = []
    for dw in dws:
        v = verdict.get(dw)
        if not isinstance(v, Mapping):
            problems.append(f"{dw}: not ruled")
            continue
        if v.get("ruling") not in RULINGS:
            problems.append(f"{dw}: ruling {v.get('ruling')!r} is not one of {'|'.join(RULINGS)}")
        ev = v.get("evidence")
        good = (isinstance(ev, str) and ev.strip()) or (
            isinstance(ev, list) and ev and all(isinstance(e, str) and e.strip() for e in ev))
        if not good:
            problems.append(f"{dw}: evidence must be a non-empty string or a list of non-empty strings")
    for dw in verdict:
        if dw not in dws:
            problems.append(f"{dw}: not a DW of the design (a reviewer rules the design's DWs, not its own)")
    done = not problems and all(verdict[d].get("ruling") == "met" for d in dws)
    return problems, done


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _emit(findings: List[Finding], as_json: bool, warnings: bool, extra: Optional[Dict[str, Any]] = None) -> int:
    errors = [f for f in findings if f.severity == "E"]
    warns = [f for f in findings if f.severity == "W"]
    if as_json:
        doc = {"errors": [f.to_dict() for f in errors], "warnings": len(warns)}
        if warnings:
            doc["warning_findings"] = [f.to_dict() for f in warns]
        doc.update(extra or {})
        print(json.dumps(doc, sort_keys=True))
    else:
        for f in errors + (warns if warnings else []):
            print(f)
        print(f"contract_lint: {len(errors)} error(s), {len(warns)} warning(s)")
    return EXIT_ERRORS if errors else EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="contract_lint.py", description="The #313 contract, checked in the text.")
    sub = ap.add_subparsers(dest="command")
    p_lint = sub.add_parser("lint", help="lint a tree against the pinned inventory")
    p_lint.add_argument("root", nargs="?", type=Path, default=TREE)
    p_lint.add_argument("--warnings", action="store_true", help="print C004 advisories too")
    p_lint.add_argument("--json", action="store_true")
    p_plan = sub.add_parser("check-plan", help="C005: a plan's covers against its design's DWs")
    p_plan.add_argument("plan", type=Path)
    p_plan.add_argument("--design", type=Path)
    p_plan.add_argument("--json", action="store_true")
    p_ver = sub.add_parser("check-verdict", help="a reviewer's DW verdict against the design")
    p_ver.add_argument("verdict", type=Path)
    p_ver.add_argument("--design", type=Path, required=True)
    p_ver.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.command is None:
        ap.print_usage(sys.stderr)
        return EXIT_BAD_INPUT
    try:
        if args.command == "lint":
            if not args.root.is_dir():
                raise ContractError(f"not a directory: {args.root}")
            return _emit(lint_tree(args.root), args.json, args.warnings)
        if args.command == "check-plan":
            plan = load_plan(args.plan)
            rel = args.plan.as_posix()
            design = resolve_design(plan, args.plan, args.design)
            if design is None and plan.get("design_doc"):
                return _emit([Finding(rel, 0, "C005", "E", f"design_doc {plan.get('design_doc')!r} cannot be resolved; "
                                                            "a plan that names a design is checked against it")],
                             args.json, False, {"design": None, "dws": []})
            try:
                dws = design_dws(design.read_text(encoding="utf-8-sig")) if design is not None else None
            except (ContractError, OSError) as exc:
                return _emit([Finding(rel, 0, "C005", "E", f"design {design}: {exc}")], args.json, False,
                             {"design": str(design), "dws": []})
            return _emit(check_plan(plan, dws, rel), args.json, False,
                         {"design": str(design) if design else None, "dws": sorted(dws or {})})
        try:
            verdict = json.loads(args.verdict.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ContractError(f"{args.verdict} is not JSON: {exc}") from exc
        if not isinstance(verdict, dict):
            raise ContractError(f"{args.verdict}: a verdict is an object {{DW-n: {{ruling, evidence}}}}")
        dws = design_dws(args.design.read_text(encoding="utf-8-sig"))
        if not dws:
            raise ContractError(f"{args.design} has no Done when section")
        problems, done = verdict_problems(verdict, dws)
        findings = [Finding(args.verdict.as_posix(), 0, "C005", "E", p) for p in problems]
        return _emit(findings, args.json, False, {"done": done})
    except (ContractError, OSError, ValueError) as exc:
        print(f"contract_lint.py: bad input: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
