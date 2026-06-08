#!/usr/bin/env python3
"""freshness.py — FRESHNESS:v1 lint / restamp / reindex / deadline engine.

Part of Ecosystem Evergreening v1 (S041). The companion to rot_scan.py: rot_scan
SCANS (regex-primary, FRESHNESS-as-sugar) and reports; freshness.py is the WRITER
side — it parses/validates FRESHNESS:v1 blocks, re-stamps anchors (bob's refresh
engine), rebuilds the by_tool/by_deadline index, and turns dated deadlines into
idempotent tasks.md rows.

Design refs:
  §6.5  FRESHNESS:v1 convention (HTML-comment, universal — works in SKILL.md AND
        frontmatter-less references; NEVER frontmatter, per Adjudication 1)
  §6.6  subcommands lint / restamp / reindex / check-deadlines
        upsert key for a deadline row = `target` ALONE (the date is a MUTABLE field;
        spec-review Issue 4 — keying on (target,date) would orphan a row when a
        deadline shifts). #132/#133 row format.

CLI:
  freshness.py lint <path>                          # advisory block schema check
  freshness.py restamp <file> --tool codex --to 0.137.0 [--on 2026-06-05] [--review-by 2027-01]
  freshness.py reindex [--root <skills-root>]       # rebuild state/freshness/index.json
  freshness.py check-deadlines [--root ...] [--tasks <tasks.md>] [--horizon 30] [--today YYYY-MM-DD]
  freshness.py parse <path>                          # debug: dump parsed anchors as JSON

stdlib-only, deterministic (modulo today's date in check-deadlines). NEVER writes
under ~/.claude/skills/ except a restamp of the SPECIFIC user-named file (bob's
sanctioned refresh write); reindex/deadlines write only under ~/.claude/state/ and
the named tasks.md. (D1: detection has no skill-write path; restamp is the REFRESH
side, invoked by bob from an approved recipe, never by the detection bus.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = "FRESHNESS:v1"
INDEX_SCHEMA = "freshness-index.v1"

HOME = Path(os.environ.get("HOME", str(Path.home())))
SKILLS_ROOT = HOME / ".claude" / "skills"
AGENTS_ROOT = HOME / ".claude" / "agents"
STATE_FRESH = HOME / ".claude" / "state" / "freshness"
INDEX_FILE = STATE_FRESH / "index.json"

# A FRESHNESS:v1 block is an HTML comment whose body starts with the marker.
_BLOCK_RE = re.compile(
    r"<!--\s*FRESHNESS:v1\s*\n(?P<body>.*?)\n?-->",
    re.DOTALL,
)

VALID_KINDS = {"tool_version", "date_review", "retirement", "model_id", "status_snapshot"}
VALID_VOLATILITY = {"high", "medium", "low"}

# YELLOW lead time (days) by volatility (§6.5 / §6.2: high 60, else 30).
VOLATILITY_HORIZON = {"high": 60, "medium": 30, "low": 30}


# ── tiny YAML subset parser (stdlib-only; FRESHNESS bodies are simple) ───────
#
# We deliberately avoid a yaml dependency (cross-model portability + no import of a
# third-party lib in a _meta engine). FRESHNESS:v1 bodies are a constrained subset:
#   - a top-level `anchors:` list of `- key: value` mappings
#   - optional top-level scalars (`volatility: high`)
# This parser handles exactly that shape and is covered by golden-fixture tests.

def _strip_inline_comment(s: str) -> str:
    # Remove a trailing " # comment" but respect quoted strings.
    out = []
    in_s = None
    i = 0
    while i < len(s):
        c = s[i]
        if in_s:
            out.append(c)
            if c == in_s:
                in_s = None
        elif c in ("'", '"'):
            in_s = c
            out.append(c)
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _scalar(v: str):
    v = v.strip()
    if not v:
        return None
    if (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'"):
        return v[1:-1]
    return v


def parse_freshness_yaml(body: str) -> dict:
    """Parse the constrained YAML subset inside a FRESHNESS:v1 block.

    Returns {"anchors": [ {k:v,...}, ... ], "<top-scalar>": value, ...}.
    Raises ValueError on a structural problem the lint should surface.
    """
    result: dict = {"anchors": []}
    lines = body.splitlines()
    i = 0
    n = len(lines)
    cur_anchor = None
    in_anchors = False
    while i < n:
        raw = lines[i]
        line = _strip_inline_comment(raw)
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            in_anchors = False
            cur_anchor = None
            if stripped == "anchors:":
                in_anchors = True
                i += 1
                continue
            # top-level scalar  key: value
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                result[k.strip()] = _scalar(v)
                i += 1
                continue
            raise ValueError(f"unexpected top-level line: {stripped!r}")

        # indented — must be inside anchors
        if not in_anchors:
            raise ValueError(f"indented line outside anchors: {stripped!r}")

        if stripped.startswith("- "):
            cur_anchor = {}
            result["anchors"].append(cur_anchor)
            stripped = stripped[2:].strip()
            if stripped and ":" in stripped:
                k, _, v = stripped.partition(":")
                cur_anchor[k.strip()] = _scalar(v)
            i += 1
            continue

        if cur_anchor is None:
            raise ValueError(f"anchor field before any '- ': {stripped!r}")
        if ":" in stripped:
            k, _, v = stripped.partition(":")
            cur_anchor[k.strip()] = _scalar(v)
            i += 1
            continue
        raise ValueError(f"unparseable anchor line: {stripped!r}")

    return result


# ── extraction ───────────────────────────────────────────────────────────────

def extract_blocks(text: str) -> list[str]:
    """Return the raw bodies of all FRESHNESS:v1 blocks in `text`."""
    return [m.group("body") for m in _BLOCK_RE.finditer(text)]


def parse_file(path: Path) -> list[dict]:
    """Parse every FRESHNESS:v1 block in a file → list of parsed dicts."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for body in extract_blocks(text):
        out.append(parse_freshness_yaml(body))
    return out


# ── lint ─────────────────────────────────────────────────────────────────────

def lint_block(parsed: dict) -> list[str]:
    """Return a list of advisory warnings for one parsed FRESHNESS block."""
    warns: list[str] = []
    anchors = parsed.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        warns.append("block has no anchors[]")
        anchors = anchors if isinstance(anchors, list) else []
    vol = parsed.get("volatility")
    if vol is not None and vol not in VALID_VOLATILITY:
        warns.append(f"volatility {vol!r} not in {sorted(VALID_VOLATILITY)}")
    for idx, a in enumerate(anchors):
        kind = a.get("kind")
        if kind not in VALID_KINDS:
            warns.append(f"anchor[{idx}] kind {kind!r} not in {sorted(VALID_KINDS)}")
            continue
        if kind == "tool_version":
            if not a.get("subject"):
                warns.append(f"anchor[{idx}] tool_version missing 'subject'")
            if not a.get("verified_against"):
                warns.append(f"anchor[{idx}] tool_version missing 'verified_against'")
        elif kind == "date_review":
            if not a.get("review_by"):
                warns.append(f"anchor[{idx}] date_review missing 'review_by'")
        elif kind == "retirement":
            if not (a.get("retire_on") or a.get("review_by")):
                warns.append(f"anchor[{idx}] retirement missing 'retire_on'")
        elif kind == "model_id":
            if not a.get("subject"):
                warns.append(f"anchor[{idx}] model_id missing 'subject'")
    return warns


def cmd_lint(args) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"freshness lint: {path} does not exist", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    bodies = extract_blocks(text)
    if not bodies:
        print(f"freshness lint: {path}: no FRESHNESS:v1 block (advisory — not required for legacy files)")
        return 0
    total = 0
    for i, body in enumerate(bodies):
        try:
            parsed = parse_freshness_yaml(body)
        except ValueError as e:
            print(f"freshness lint: {path}: block {i}: PARSE ERROR: {e}")
            total += 1
            continue
        for w in lint_block(parsed):
            print(f"freshness lint: {path}: block {i}: WARN: {w}")
            total += 1
    if total == 0:
        print(f"freshness lint: {path}: OK ({len(bodies)} block(s))")
    # Advisory: warnings do NOT make this a gate. Exit 0 even with warnings so it
    # never blocks publish; the count is informational.
    return 0


# ── restamp (the refresh write) ──────────────────────────────────────────────

def restamp_text(text: str, tool: str, to_version: str, on: str | None,
                 review_by: str | None) -> tuple[str, bool]:
    """Update (or insert) a tool_version anchor for `tool` to `to_version`/`on`.

    Returns (new_text, changed). If a FRESHNESS:v1 block exists, the matching
    tool_version anchor's verified_against/verified_on are updated in place; if no
    block exists, a new minimal block is appended at end of file.
    """
    on = on or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    m = _BLOCK_RE.search(text)
    if m:
        body = m.group("body")
        try:
            parsed = parse_freshness_yaml(body)
        except ValueError:
            parsed = {"anchors": []}
        anchors = parsed.get("anchors", [])
        found = False
        for a in anchors:
            if a.get("kind") == "tool_version" and a.get("subject") == tool:
                a["verified_against"] = to_version
                a["verified_on"] = on
                found = True
        if not found:
            anchors.append({"kind": "tool_version", "subject": tool,
                            "verified_against": to_version, "verified_on": on})
        if review_by:
            rev = next((a for a in anchors if a.get("kind") == "date_review"), None)
            if rev:
                rev["review_by"] = review_by
            else:
                anchors.append({"kind": "date_review", "review_by": review_by})
        parsed["anchors"] = anchors
        new_block = render_block(parsed)
        new_text = text[:m.start()] + new_block + text[m.end():]
        return new_text, new_text != text

    # No block — append a fresh one.
    anchors = [{"kind": "tool_version", "subject": tool,
                "verified_against": to_version, "verified_on": on}]
    if review_by:
        anchors.append({"kind": "date_review", "review_by": review_by})
    block = render_block({"anchors": anchors})
    sep = "" if text.endswith("\n") else "\n"
    new_text = text + sep + "\n" + block + "\n"
    return new_text, True


def render_block(parsed: dict) -> str:
    """Render a parsed FRESHNESS block back to canonical HTML-comment form."""
    lines = ["<!-- FRESHNESS:v1", "anchors:"]
    for a in parsed.get("anchors", []):
        kind = a.get("kind")
        first = True
        # deterministic key order
        order = ["kind", "subject", "verified_against", "verified_on",
                 "review_by", "retire_on", "snapshot_of"]
        keys = [k for k in order if k in a] + [k for k in a if k not in order]
        for k in keys:
            v = a[k]
            vs = _emit_scalar(v)
            if first:
                lines.append(f"  - {k}: {vs}")
                first = False
            else:
                lines.append(f"    {k}: {vs}")
    for k, v in parsed.items():
        if k == "anchors":
            continue
        lines.append(f"{k}: {_emit_scalar(v)}")
    lines.append("-->")
    return "\n".join(lines)


def _emit_scalar(v) -> str:
    if v is None:
        return '""'
    s = str(v)
    # Quote anything that could be ambiguous to a strict YAML reader: values with
    # a colon/hash, leading/trailing whitespace, OR a version/date-like shape
    # (digits with a '.' or '-' or ':' separator). Bare enum words (kinds,
    # volatility) stay unquoted for readability.
    if re.search(r"[:#]", s) or s != s.strip():
        return f'"{s}"'
    if re.search(r"\d", s) and re.search(r"[.\-]", s):
        return f'"{s}"'
    return s


def cmd_restamp(args) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"freshness restamp: {path} does not exist", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    new_text, changed = restamp_text(text, args.tool, args.to, args.on, args.review_by)
    if not changed:
        print(f"freshness restamp: {path}: already current ({args.tool} == {args.to})")
        return 0
    # Atomic write (temp + replace).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(str(tmp), str(path))
    print(f"freshness restamp: {path}: {args.tool} -> {args.to} (verified_on {args.on or 'today'})")
    return 0


# ── reindex ──────────────────────────────────────────────────────────────────

def _iter_md_files(root: Path):
    if root.is_dir():
        yield from root.rglob("*.md")


def build_index(skills_root: Path = SKILLS_ROOT, agents_root: Path = AGENTS_ROOT) -> dict:
    """Build the by_tool / by_deadline reverse maps from FRESHNESS blocks."""
    by_tool: dict[str, list[str]] = {}
    by_deadline: list[dict] = []
    for root in (skills_root, agents_root):
        for f in _iter_md_files(root):
            try:
                blocks = parse_file(f)
            except ValueError:
                continue
            rel = str(f)
            for parsed in blocks:
                vol = parsed.get("volatility")
                for a in parsed.get("anchors", []):
                    kind = a.get("kind")
                    if kind in ("tool_version", "model_id"):
                        subj = a.get("subject")
                        if subj:
                            by_tool.setdefault(subj, [])
                            if rel not in by_tool[subj]:
                                by_tool[subj].append(rel)
                    if kind in ("date_review", "retirement"):
                        deadline = a.get("review_by") or a.get("retire_on")
                        if deadline:
                            by_deadline.append({
                                "target": rel,
                                "date": str(deadline),
                                "kind": kind,
                                "volatility": vol or "medium",
                            })
    for k in by_tool:
        by_tool[k].sort()
    by_deadline.sort(key=lambda d: (d["date"], d["target"]))
    return {
        "schema_version": INDEX_SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by_tool": by_tool,
        "by_deadline": by_deadline,
    }


def cmd_reindex(args) -> int:
    skills_root = Path(args.root) if args.root else SKILLS_ROOT
    idx = build_index(skills_root)
    STATE_FRESH.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(INDEX_FILE))
    print(f"freshness reindex: {len(idx['by_tool'])} tool(s), "
          f"{len(idx['by_deadline'])} deadline(s) -> {INDEX_FILE}")
    return 0


# ── check-deadlines → idempotent tasks.md rows ───────────────────────────────
#
# Upsert key = `target` ALONE (spec-review Issue 4). The date is a MUTABLE field of
# the row. Re-running with a changed date updates the existing row IN PLACE — never
# orphans it. We mark each managed row with a stable HTML-comment sentinel keyed on
# the target so we can find-and-replace it idempotently.

_ROW_SENTINEL = "<!-- freshness-deadline:{key} -->"


def _deadline_key(target: str) -> str:
    # Stable, filesystem-name-free key from the target path's basename + parent.
    p = Path(target)
    return f"{p.parent.name}/{p.name}"


def _horizon_days(d: dict, default_horizon: int) -> int:
    vol = d.get("volatility", "medium")
    return VOLATILITY_HORIZON.get(vol, default_horizon)


def deadlines_within_horizon(index: dict, today: date, default_horizon: int) -> list[dict]:
    out = []
    for d in index.get("by_deadline", []):
        ds = d.get("date", "")
        due = _parse_deadline_date(ds)
        if due is None:
            continue
        horizon = _horizon_days(d, default_horizon)
        delta = (due - today).days
        if delta <= horizon:  # within horizon OR already past
            out.append({**d, "due_date": due.isoformat(), "days_remaining": delta})
    return out


def _parse_deadline_date(ds: str) -> date | None:
    ds = ds.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(ds, fmt)
            # Year-only / year-month -> treat as end-of-period for horizon purposes:
            if fmt == "%Y":
                return date(dt.year, 12, 31)
            if fmt == "%Y-%m":
                # last day handling is overkill; use the 1st (conservative — fires earlier)
                return date(dt.year, dt.month, 1)
            return dt.date()
        except ValueError:
            continue
    return None


def upsert_tasks_md(tasks_path: Path, deadlines: list[dict]) -> tuple[int, int]:
    """Upsert one row per target into tasks.md. Returns (updated, inserted)."""
    if tasks_path.exists():
        text = tasks_path.read_text(encoding="utf-8")
    else:
        text = "# Tasks\n\n## Freshness deadlines (managed by freshness.py)\n"
    updated = inserted = 0
    for d in deadlines:
        key = _deadline_key(d["target"])
        sentinel = _ROW_SENTINEL.format(key=key)
        row = _format_deadline_row(d, sentinel)
        # Find an existing managed row by its sentinel and replace the WHOLE line.
        pat = re.compile(r"^.*" + re.escape(sentinel) + r".*$", re.MULTILINE)
        if pat.search(text):
            text = pat.sub(row, text)
            updated += 1
        else:
            if not text.endswith("\n"):
                text += "\n"
            text += row + "\n"
            inserted += 1
    tmp = tasks_path.with_suffix(tasks_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(tasks_path))
    return updated, inserted


def _format_deadline_row(d: dict, sentinel: str) -> str:
    # Mirrors the #132/#133 dated-reminder row shape: a checkbox + ⏰ ON/AFTER <date>.
    kind = "retirement" if d.get("kind") == "retirement" else "review"
    target = d["target"]
    due = d.get("due_date", d.get("date"))
    rem = d.get("days_remaining")
    when = f"T{rem:+d}d" if isinstance(rem, int) else ""
    return (f"- [ ] ⏰ ON/AFTER {due} — freshness {kind}: `{target}` ({when}) {sentinel}")


def cmd_check_deadlines(args) -> int:
    # Build a fresh index (do not depend on a stale one) unless told to use a file.
    if args.index and Path(args.index).exists():
        index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    else:
        skills_root = Path(args.root) if args.root else SKILLS_ROOT
        index = build_index(skills_root)
    today = date.fromisoformat(args.today) if args.today else date.today()
    due = deadlines_within_horizon(index, today, args.horizon)
    if not due:
        print(f"freshness check-deadlines: no deadlines within {args.horizon}d of {today}")
        return 0
    if args.dry_run or not args.tasks:
        for d in due:
            print(f"  DUE {d['due_date']} ({d['days_remaining']:+d}d) {d['target']} [{d['kind']}]")
        if not args.tasks:
            print("freshness check-deadlines: --tasks not given; dry listing only")
        return 0
    updated, inserted = upsert_tasks_md(Path(args.tasks), due)
    print(f"freshness check-deadlines: {updated} row(s) updated, {inserted} inserted "
          f"in {args.tasks} ({len(due)} within horizon)")
    return 0


def cmd_parse(args) -> int:
    path = Path(args.path)
    out = parse_file(path)
    print(json.dumps(out, indent=2))
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="freshness.py", description="FRESHNESS:v1 engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("lint")
    pl.add_argument("path")
    pl.set_defaults(func=cmd_lint)

    pr = sub.add_parser("restamp")
    pr.add_argument("file")
    pr.add_argument("--tool", required=True)
    pr.add_argument("--to", required=True)
    pr.add_argument("--on", default=None, help="verified_on date (default: today)")
    pr.add_argument("--review-by", default=None)
    pr.set_defaults(func=cmd_restamp)

    pi = sub.add_parser("reindex")
    pi.add_argument("--root", default=None)
    pi.set_defaults(func=cmd_reindex)

    pd = sub.add_parser("check-deadlines")
    pd.add_argument("--root", default=None)
    pd.add_argument("--index", default=None)
    pd.add_argument("--tasks", default=None)
    pd.add_argument("--horizon", type=int, default=30)
    pd.add_argument("--today", default=None)
    pd.add_argument("--dry-run", action="store_true")
    pd.set_defaults(func=cmd_check_deadlines)

    pp = sub.add_parser("parse")
    pp.add_argument("path")
    pp.set_defaults(func=cmd_parse)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:  # noqa: BLE001 — surface but never crash the caller hard
        print(f"freshness.py: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
