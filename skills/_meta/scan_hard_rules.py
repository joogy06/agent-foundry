#!/usr/bin/env python3
"""
scan_hard_rules.py — SessionStart hook + forge helper.

Scans CLAUDE.md (global + project-local) for hard-rule-style directives and
surfaces any that are NOT reflected in ~/.claude/skills/_meta/hard-rules-checklist.md.

Usage:
    scan_hard_rules.py            # plain markdown output (for forge, CLI)
    scan_hard_rules.py --hook     # emit SessionStart hook JSON on stdout
    scan_hard_rules.py --plain    # explicit plain (same as default)

Design notes:
- Fuzzy token-overlap comparison against the checklist (not exact match).
- Non-fatal: any failure returns a benign "continue" JSON so sessions never break.
- Fast: sub-100ms on a laptop; reads 2-3 small files.
- Classifies each missing directive as global-source or project-source and
  routes project-source ones through a y/n/edit AskUserQuestion proposal.
- Filters out directives that the project already has under
  '## Project HARD-RULEs' (locally-handled), and directives the user
  previously chose to suppress for this project.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

# Shared canonicalization helpers (single source of truth — Codex #9).
_META = Path(__file__).resolve().parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

from hard_rules_common import (  # noqa: E402
    canonical_directive_text,
    canonical_project_id,
    directive_hash,
    display_directive_text,
)

HOME = Path.home()
GLOBAL_CLAUDE_MD = HOME / ".claude" / "CLAUDE.md"
CHECKLIST = HOME / ".claude" / "skills" / "_meta" / "hard-rules-checklist.md"
STATE_FILE = HOME / ".claude" / "state" / "hard-rules-suppressed.json"
APPLY_HELPER = (
    HOME / ".claude" / "skills" / "_meta" / "apply_project_hard_rules.py"
)

PROJECT_CLAUDE_MD_CANDIDATES = [
    Path("CLAUDE.md"),
    Path(".claude/CLAUDE.md"),
]

PROJECT_HARD_RULES_SECTION_HEADER = "## Project HARD-RULEs"
PROJECT_HARD_RULES_MARKER = (
    "<!-- managed-by: scan_hard_rules.py — "
    "edit freely; new directives can be added below -->"
)

# Generic bold-led bullet patterns are WEAK signals: any doc bullet that
# happens to lead with bold (e.g. a wrapped agy reference line like
# "- **Other modes:** `-i` ...") would otherwise be captured as a directive.
# These two patterns get a second-stage mandate-language filter in
# extract_rules(); the explicit HARD-RULE / header patterns do NOT.
_BOLD_BULLET_PATTERNS = (
    re.compile(r"^- \*\*[^*]+\*\*"),
    re.compile(r"^\s*\d+\.\s+\*\*[^*]+\*\*"),
)

# Second-stage filter: a bold-led bullet is only a hard-rule candidate if
# the line also contains mandate language.
MANDATE_LANGUAGE_RE = re.compile(
    # `require` is matched in all its inflections: the original pattern had only
    # the bare word "required", so a real directive phrased "X requires explicit
    # user approval" was silently dropped as a non-mandate bullet.
    r"\b(MUST(?: NOT)?|NEVER|ALWAYS|HARD-RULE|require(?:s|d|ment|ments)?|"
    r"do not|don't|shall|forbidden|prohibited|mandatory|may not|"
    r"only ever|under no circumstances)\b",
    re.IGNORECASE,
)

# Patterns that identify a "hard rule" line in a CLAUDE.md file.
HARD_RULE_PATTERNS = [
    re.compile(r"<HARD-RULE>|<HARD-GATE>|HARD RULE|Hard Rules|Hard-Rules"),
    re.compile(
        r"^##+ .*([Ss]ession [Ss]tart|[Hh]ard [Rr]ule|[Mm]andatory|"
        r"[Cc]heckpoint|[Rr]outing|[Aa]utonomy|[Ww]iki [Bb]inding)"
    ),
    *_BOLD_BULLET_PATTERNS,
]

STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "each",
    "have", "been", "read", "check", "will", "should", "must", "when",
    "what", "your", "global", "project", "local", "also", "then", "before",
    "after", "file", "files", "would", "could", "their", "them", "they",
    "which", "while", "about", "where", "there", "these", "those", "make",
    "made", "over", "under", "above", "below", "other", "same", "such",
}

# Section bounds detection for locally-handled extraction.
_SECTION_HEADER_RE = re.compile(
    r"^##[ \t]+Project HARD-RULEs[ \t]*\r?$",
    re.MULTILINE,
)
_NEXT_H1_OR_H2_RE = re.compile(r"^#{1,2}[ \t]", re.MULTILINE)
_TOP_BULLET_RE = re.compile(r"^- ")
_FENCE_RE = re.compile(r"^(```|~~~)")


def extract_rules(path: Path | None, label: str) -> list[str]:
    """Extract hard-rule-looking lines from a markdown file."""
    if not path or not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rules: list[str] = []
    for line in text.splitlines():
        for pat in HARD_RULE_PATTERNS:
            if pat.search(line):
                # Second-stage mandate-language filter — applies ONLY to the
                # generic bold-bullet patterns, never to explicit HARD-RULE
                # tags or section headers. Drops wrapped doc bullets that
                # merely lead with bold text (false-positive fix 2026-06-10).
                if pat in _BOLD_BULLET_PATTERNS and not MANDATE_LANGUAGE_RE.search(line):
                    continue
                rules.append(f"[{label}] {line.rstrip()}")
                break
    return rules


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def significant_tokens(s: str) -> list[str]:
    return [t for t in normalize(s).split() if len(t) > 3 and t not in STOPWORDS]


def checklist_tokens() -> set[str]:
    if not CHECKLIST.exists():
        return set()
    try:
        text = CHECKLIST.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    tokens: set[str] = set()
    for line in text.splitlines():
        tokens.update(normalize(line).split())
    return tokens


def rule_reflected(rule: str, tokens: set[str]) -> bool:
    """Fuzzy: does the rule share >=50% of its significant tokens with checklist?"""
    sig = significant_tokens(rule)
    if len(sig) < 3:
        return True  # too little signal, assume covered
    hits = sum(1 for t in sig if t in tokens)
    return hits / len(sig) >= 0.5


def find_project_claude_md() -> Path | None:
    for cand in PROJECT_CLAUDE_MD_CANDIDATES:
        try:
            if cand.exists() and cand.is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# Locally-handled filter (Codex #1 critical fix)
# ---------------------------------------------------------------------------

def _build_fence_mask(lines: list[str]) -> list[bool]:
    """One bool per line: True if inside a fenced code block (incl. fence
    delimiters themselves). ``` pairs with ```; ~~~ pairs with ~~~."""
    mask = [False] * len(lines)
    open_fence: str | None = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        m = _FENCE_RE.match(stripped)
        if open_fence is None:
            if m:
                open_fence = m.group(1)
                mask[i] = True
        else:
            mask[i] = True
            if m and m.group(1) == open_fence:
                open_fence = None
    return mask


def extract_locally_handled(project_claude_md: Path | None) -> set[str]:
    """Return the canonical-text set of every top-level bullet under the
    project's '## Project HARD-RULEs' section, outside any code fence.

    Returns empty set if the file or section is missing.

    This is the load-bearing filter (Codex #1): after the user runs `apply`,
    the bullets land in this section and subsequent scans will see them
    here and treat the directives as handled — even though the GLOBAL
    checklist still doesn't reflect them.
    """
    if project_claude_md is None or not project_claude_md.is_file():
        return set()
    try:
        text = project_claude_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines(keepends=False)
    fence_mask = _build_fence_mask(lines)
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if fence_mask[i]:
            continue
        if _SECTION_HEADER_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        return set()
    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        if fence_mask[j]:
            continue
        if _NEXT_H1_OR_H2_RE.match(lines[j]):
            end_idx = j
            break
    handled: set[str] = set()
    for k in range(header_idx + 1, end_idx):
        if fence_mask[k]:
            continue
        line = lines[k]
        if _TOP_BULLET_RE.match(line):
            handled.add(canonical_directive_text(line))
    return handled


def filter_locally_handled(
    rules: list[str], handled: set[str]
) -> list[str]:
    """Remove rules whose canonical form appears in `handled`."""
    if not handled:
        return list(rules)
    return [r for r in rules if canonical_directive_text(r) not in handled]


# ---------------------------------------------------------------------------
# Suppression filter
# ---------------------------------------------------------------------------

def load_suppressed(project_id: str) -> set[str]:
    """Return the set of suppressed directive hashes for `project_id`.
    Empty set on missing/corrupt state file (never raises)."""
    if not STATE_FILE.exists():
        return set()
    try:
        raw = STATE_FILE.read_text(encoding="utf-8")
    except OSError:
        return set()
    if not raw.strip():
        return set()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, dict):
        return set()
    proj = data.get(project_id)
    if not isinstance(proj, dict):
        return set()
    entries = proj.get("suppressed", [])
    if not isinstance(entries, list):
        return set()
    return {
        e.get("hash")
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("hash"), str)
    }


def filter_suppressed(
    rules: list[str], suppressed_hashes: set[str]
) -> list[str]:
    if not suppressed_hashes:
        return list(rules)
    return [r for r in rules if directive_hash(r) not in suppressed_hashes]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_missing(
    missing: list[str],
) -> tuple[list[str], list[str]]:
    """Split missing rules into (global_missing, project_missing) by source
    label."""
    global_missing = [r for r in missing if r.startswith("[global]")]
    project_missing = [r for r in missing if r.startswith("[project:")]
    return global_missing, project_missing


def _strip_source_label(rule: str) -> str:
    """Drop the leading '[global] ' / '[project:...] ' prefix for display.

    Note: this only strips the source label. For directive text that is
    being emitted as a `--rule` argument or as a preview bullet, callers
    should use `display_directive_text()` from hard_rules_common, which
    additionally strips bullet markers, markdown emphasis, and HTML
    comments while preserving casing.
    """
    m = re.match(r"^\s*\[(?:global|project:[^\]]*)\]\s*", rule)
    return rule[m.end():] if m else rule


# ---------------------------------------------------------------------------
# build_context — single output renderer for hook & plain modes (Codex #6)
# ---------------------------------------------------------------------------

def _format_apply_command(
    project_id: str,
    project_claude_md: Path,
    directives: list[str],
) -> str:
    """Render the fully-quoted apply command (Codex #3: shlex.quote every
    interpolated value, including --project-id, --project-claude-md, and
    every --rule). `--rule` values use display_directive_text() so the
    user copy-runs a clean directive (no bullet, no emphasis, no source
    label)."""
    parts = [
        "python3",
        shlex.quote(str(APPLY_HELPER)),
        "apply",
        "--project-id", shlex.quote(project_id),
        "--project-claude-md", shlex.quote(str(project_claude_md)),
    ]
    rule_lines = []
    for d in directives:
        bare = display_directive_text(d)
        rule_lines.append(f"  --rule {shlex.quote(bare)}")
    head = " ".join(parts) + " \\\n"
    return head + " \\\n".join(rule_lines)


def _format_suppress_command(
    project_id: str,
    directives: list[str],
) -> str:
    parts = [
        "python3",
        shlex.quote(str(APPLY_HELPER)),
        "suppress",
        "--project-id", shlex.quote(project_id),
    ]
    rule_lines = []
    for d in directives:
        bare = display_directive_text(d)
        rule_lines.append(f"  --rule {shlex.quote(bare)}")
    head = " ".join(parts) + " \\\n"
    return head + " \\\n".join(rule_lines)


def _project_section_block(
    project_id: str,
    project_claude_md: Path,
    project_missing: list[str],
) -> str:
    """Emit the y/n/edit AskUserQuestion proposal for project-scoped rules.

    Uses display_directive_text() for the user-facing bullet list, the
    preview, and the embedded --rule values so the user sees clean
    directives without source labels, bullet markers, or markdown
    emphasis."""
    bare_rules = [display_directive_text(r) for r in project_missing]
    bullet_list = "\n".join(
        f"{i+1}. `{b}`" for i, b in enumerate(bare_rules)
    )
    preview = (
        f"{PROJECT_HARD_RULES_SECTION_HEADER}\n\n"
        f"{PROJECT_HARD_RULES_MARKER}\n\n"
        + "\n".join(f"- {b}" for b in bare_rules)
        + "\n"
    )
    apply_cmd = _format_apply_command(
        project_id, project_claude_md, project_missing
    )
    suppress_cmd = _format_suppress_command(project_id, project_missing)
    n = len(project_missing)
    return (
        "## Project-Scoped Directives Need Action\n\n"
        f"**Project CLAUDE.md:** `{project_claude_md}`\n"
        "**Directives not in checklist (and not previously declined):**\n\n"
        f"{bullet_list}\n\n"
        "These appear to be **project-scoped** (not in the global cross-project "
        "checklist). Recommended target: project `CLAUDE.md` under a "
        f"`{PROJECT_HARD_RULES_SECTION_HEADER}` section.\n\n"
        "**Action — surface this to the user via AskUserQuestion:**\n\n"
        "- header: \"HARD-RULE add\"\n"
        f"- question: \"Add these {n} project HARD-RULE(s) to "
        f"{project_claude_md}?\"\n"
        "- options:\n"
        "  - **y** — Apply now. Run:\n\n"
        f"    ```bash\n    {apply_cmd}\n    ```\n\n"
        "  - **n** — Skip permanently for this project. Run:\n\n"
        f"    ```bash\n    {suppress_cmd}\n    ```\n\n"
        "  - **edit** — Draft revised wording inline with the user, then "
        "re-run the apply command above with revised `--rule` strings "
        "(use Bash arg arrays correctly).\n\n"
        "**Proposed addition (preview):**\n\n"
        f"```markdown\n{preview}```\n"
    )


def _global_section_block(global_missing: list[str]) -> str:
    """Existing advisory for global-source missing rules (unchanged behavior)."""
    return (
        "## Global-Scoped Directives\n\n"
        f"Found **{len(global_missing)}** global-source directive(s) that "
        "may be missing from the checklist.\n\n"
        "**Action** — at the first natural opportunity this session (or "
        "forge Step 1), surface these to the user and ask whether to: "
        "(a) add to `hard-rules-checklist.md`, "
        "(b) wire into a skill, or "
        "(c) apply ad-hoc this session.\n\n"
        "### Potentially missing directives\n\n"
        "```\n" + "\n".join(global_missing) + "\n```\n\n"
        f"### Checklist path\n`{CHECKLIST}`\n"
    )


def build_context(
    all_rules: list[str],
    missing: list[str],
    project_id: str,
    project_claude_md: Path | None,
    suppressed_count: int = 0,
) -> str:
    """Single output renderer — used by both hook and plain modes.

    - all_rules: every extracted directive (global + project), source-labeled.
    - missing: subset of all_rules that survived fuzzy checklist match,
      locally-handled filter, AND suppression filter — these need surfacing.
    - project_id: canonical project root (from canonical_project_id()).
    - project_claude_md: resolved path to the project CLAUDE.md (or None).
    - suppressed_count: how many missing-after-checklist rules were filtered
      out by the suppression state (informational footer).
    """
    header = (
        "## Hard Rule Scan (CLAUDE.md → hard-rules-checklist)\n\n"
        "Scanned CLAUDE.md (global + project-local) for hard-rule directives "
        "and compared against `~/.claude/skills/_meta/hard-rules-checklist.md`.\n\n"
    )

    if not all_rules:
        return header + "No hard-rule directives found. No action needed.\n"

    if not missing:
        body = (
            f"All {len(all_rules)} extracted directive(s) appear to be "
            "reflected in the checklist or are locally handled in the "
            "project CLAUDE.md. No action needed.\n"
        )
        if suppressed_count:
            body += (
                f"\n(Suppressed {suppressed_count} directive(s) per "
                f"`{STATE_FILE}`.)\n"
            )
        return header + body

    global_missing, project_missing = classify_missing(missing)

    parts = [
        header,
        (
            f"Found **{len(all_rules)}** directive(s); "
            f"**{len(missing)}** need attention "
            f"({len(project_missing)} project-scoped, "
            f"{len(global_missing)} global-scoped).\n\n"
        ),
    ]

    # Project-scoped section — y/n/edit proposal (Codex #5: NEVER hide the
    # global section when both are present).
    if project_missing and project_claude_md is not None:
        parts.append(_project_section_block(
            project_id, project_claude_md, project_missing
        ))
        parts.append("\n")

    # Global-scoped advisory (existing behavior).
    if global_missing:
        parts.append(_global_section_block(global_missing))
        parts.append("\n")

    # Edge case: project_missing present but project_claude_md is None.
    # Treat them as global advisory (very unlikely — only happens if the
    # source label says "project:..." but the path no longer resolves).
    if project_missing and project_claude_md is None:
        parts.append(_global_section_block(project_missing))
        parts.append("\n")

    if suppressed_count:
        parts.append(
            f"_Suppressed {suppressed_count} previously-declined "
            f"directive(s) per `{STATE_FILE}`._\n"
        )

    return "".join(parts)


# ---------------------------------------------------------------------------
# Hook emission
# ---------------------------------------------------------------------------

def emit_hook_json(context: str) -> None:
    out = {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        },
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")


def emit_benign_hook_json() -> None:
    sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # Drain stdin if piped (hook protocol) so we don't block.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    hook_mode = "--hook" in sys.argv

    try:
        global_rules = extract_rules(GLOBAL_CLAUDE_MD, "global")
        project_path = find_project_claude_md()
        project_label = (
            f"project:{project_path}" if project_path else "project"
        )
        project_rules = extract_rules(project_path, project_label) if project_path else []
        all_rules = global_rules + project_rules

        tokens = checklist_tokens()
        missing_after_checklist = [
            r for r in all_rules if not rule_reflected(r, tokens)
        ]

        # Split by source.
        global_missing, project_missing = classify_missing(missing_after_checklist)

        # Locally-handled filter (Codex #1) — only meaningful for the
        # project-source subset. Run this BEFORE the suppression filter so
        # the user sees no stale nudge after they choose 'y' and the apply
        # helper writes the bullets.
        project_id = canonical_project_id(
            project_path.parent if project_path is not None else None
        )
        handled = extract_locally_handled(project_path)
        project_missing = filter_locally_handled(project_missing, handled)

        # Suppression filter — also only for project-source (suppression
        # state is keyed on project id).
        suppressed_hashes = load_suppressed(project_id)
        before_suppress = len(project_missing)
        project_missing = filter_suppressed(project_missing, suppressed_hashes)
        suppressed_count = before_suppress - len(project_missing)

        # Final missing set for the renderer.
        missing = global_missing + project_missing

        context = build_context(
            all_rules,
            missing,
            project_id=project_id,
            project_claude_md=project_path,
            suppressed_count=suppressed_count,
        )

        if hook_mode:
            # Only inject context if there's something actionable.
            if missing:
                emit_hook_json(context)
            else:
                emit_benign_hook_json()
        else:
            sys.stdout.write(context)
            if not context.endswith("\n"):
                sys.stdout.write("\n")
        return 0
    except Exception as exc:  # never break a session
        if hook_mode:
            emit_benign_hook_json()
        else:
            sys.stderr.write(f"scan_hard_rules: {exc}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
