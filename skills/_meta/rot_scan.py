#!/usr/bin/env python3
"""rot_scan.py — regex-primary anchor rot scanner for the skill/agent library.

Part of Ecosystem Evergreening v1 (S041). Walks every skill + agent markdown file,
finds version/date/model-ID anchors, and grades each against ground truth
(inventory.json for tool versions; today's date for deadlines). Emits a rot-report.v1.

Adjudication 4 (BINDING): **regex anchor scanning is PRIMARY**; FRESHNESS:v1 metadata
is additive sugar that RAISES CONFIDENCE where present. A file with a FRESHNESS block
is graded from the block; a file without one is graded from the regex catalog. Legacy
forms (`REVIEW-BY:`, `Annual review on:`) are first-class scanner inputs forever.

Verdicts (§6.2 step 4):
  RED        anchor strictly behind installed version by >=1 minor, OR a date is past
  YELLOW     a deadline falls within the horizon (+30d; +60d when volatility: high)
  GREEN      anchor matches ground truth
  VAGUE      band-style anchor ("2.1.x", "8.x", year-only) — acceptable, not graded
  UNANNOTATED a file the walker visited that carries no anchors (advisory count only)

Self-rot defenses (§6.13): schema_version + scanner_version on the report;
last_success / last_error / runtime_ms on every run; the report is replace-on-write
and a one-line summary is appended to rot-history.jsonl.

CLI:
  rot_scan.py [--root <skills-root>] [--agents <agents-root>] [--inventory <inv.json>]
              [--today YYYY-MM-DD] [--json] [--refresh]
  --refresh just re-runs the scan and rewrites the report (alias for the default;
            exists so the nudge/launcher can say `rot_scan.py --refresh`).

stdlib-only, deterministic (modulo today's date + runtime_ms). Writes ONLY under
~/.claude/state/freshness/. (D1: no skill-write path.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

SCANNER_VERSION = "1.0.0"
REPORT_SCHEMA = "rot-report.v1"

HOME = Path(os.environ.get("HOME", str(Path.home())))
SKILLS_ROOT = HOME / ".claude" / "skills"
AGENTS_ROOT = HOME / ".claude" / "agents"
WORKFLOWS_ROOT = HOME / ".claude" / "workflows"  # S055 — scanned for *.md + *.js
INVENTORY_FILE = HOME / ".claude" / "state" / "inventory.json"
STATE_FRESH = HOME / ".claude" / "state" / "freshness"
REPORT_FILE = STATE_FRESH / "rot-report.json"
HISTORY_FILE = STATE_FRESH / "rot-history.jsonl"

DEFAULT_HORIZON = 30
HIGH_VOL_HORIZON = 60

# Reuse the FRESHNESS:v1 parser from the sibling engine (single source of truth).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import freshness as _fresh  # type: ignore
except Exception:  # pragma: no cover - freshness.py is a hard sibling dep
    _fresh = None


# ── regex catalog (PRIMARY mechanism) ────────────────────────────────────────
#
# Each pattern captures the anchored value where useful. Proximity gating (±2 lines
# to a version/verify/cover/review token) suppresses prose-date false positives for
# the date-style anchors.

_PROXIMITY_TOKENS = re.compile(
    r"\b(version|verified|verify|covers?|review|retire|retirement|as of|installed|cli)\b",
    re.IGNORECASE,
)

# tool-version style: "Covers Codex CLI 0.118.0", "verified ... 0.118.0 via codex --version"
RE_VERIFIED_DATE = re.compile(r"verified(?:\s+\w+){0,3}\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
RE_COVERS_VERSION = re.compile(r"[Cc]overs?\b.*?\bv?(\d+\.\d+(?:\.\d+)?)")
RE_VERSION_INLINE = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")
# A *status snapshot* claim — the structural "Status as of <date>" / "Status snapshot:
# <date>" form (the wiring-reconcile WP-status case). Requires the literal word
# "status" immediately before "as of" so generic prose ("OWASP Top 10 as of 2026-05",
# "current as of mid-2026") is NOT graded as a stale snapshot (prose-date FP class).
RE_AS_OF = re.compile(
    r"status\s+(?:snapshot\s*:?\s*)?as of\s+(?:early|mid|late)?[- ]?"
    r"((?:\d{4}-\d{2}(?:-\d{2})?)|(?:20\d{2}))",
    re.IGNORECASE,
)
# table-row / inline tool-version claim: "Codex CLI version | 0.118.0", "gh CLI 2.87.0",
# "<tool> ... version ... N.N.N". Captures (tool, version).
RE_TOOL_VERSION_CLAIM = re.compile(
    r"\b(codex|claude|agy|copilot|gemini|gh|docker|git|jq|yq|openssl)\b"
    r"(?:[ \t]+cli)?(?:[ \t]+version)?[ \t|`:]*\bv?(\d+\.\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
RE_REVIEW_BY = re.compile(r"REVIEW-BY:\s*(\d{4}(?:-\d{2}(?:-\d{2})?)?)", re.IGNORECASE)
RE_ANNUAL = re.compile(r"Annual review on:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
RE_RETIRE = re.compile(r"retire[ds]?\b.*?(\d{4}-\d{2}-\d{2})", re.IGNORECASE)

# model-ID anchors (§6.2 step 2)
RE_MODEL_CLAUDE = re.compile(r"\bclaude-(?:opus|sonnet|haiku)-[0-9][\w.\-]*")
RE_MODEL_GPT = re.compile(r"\bgpt-\d[\w.\-]*")
RE_MODEL_GEMINI = re.compile(r"\bgemini-[\w.\-]+")

# VAGUE band-style anchors — acceptable, never RED. Matches "2.1.x", "8.x", "2.x".
RE_VAGUE_BAND = re.compile(r"\b\d+(?:\.\d+)*\.x\b|\b\d+\.x\b")
# "Covers ... 2.1.x" band form, captured WITH its trailing .x so we can tag it VAGUE.
RE_COVERS_BAND = re.compile(r"[Cc]overs?\b.*?\bv?(\d+(?:\.\d+)*\.x)\b")


def _tool_join_key(text: str, version: str) -> str | None:
    """Best-effort: map a covered-version anchor to an inventory tool name by
    looking for a known tool token near the version. Uses WORD-BOUNDARY matching so
    "gh" does not match inside "GitHub" (a real false-RED class — WCAG 2.1 under a
    "GitHub Actions" sentence was being attributed to the gh CLI)."""
    lowered = text.lower()
    for tool in ("codex", "claude", "agy", "copilot", "gemini", "docker",
                 "git", "jq", "yq", "openssl", "gh"):
        if re.search(rf"\b{re.escape(tool)}\b", lowered):
            return tool
    return None


# ── inventory ground truth ───────────────────────────────────────────────────

def load_inventory(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _installed_version(inv: dict, tool: str) -> str | None:
    t = (inv.get("tools") or {}).get(tool) or {}
    v = t.get("version")
    return v if isinstance(v, str) else None


def _semver(v):
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", v.strip()) if isinstance(v, str) else None
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _behind_by_minor(anchor_v: str, installed_v: str) -> bool:
    """True if anchor is strictly behind installed by >=1 minor (the RED threshold)."""
    a = _semver(anchor_v)
    i = _semver(installed_v)
    if a is None or i is None:
        return False
    if a[0] != i[0]:
        return a[0] < i[0]
    if a[1] != i[1]:
        return a[1] < i[1]
    return False  # only patch differs -> not RED (patch-counted-not-RED)


# ── per-file scan ────────────────────────────────────────────────────────────

def scan_file(path: Path, inv: dict, today: date) -> list[dict]:
    """Return a list of finding dicts for one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rel = str(path)
    findings: list[dict] = []

    # 1) FRESHNESS:v1 sugar (high confidence) — if present, grade from it.
    fresh_blocks = []
    if _fresh is not None:
        try:
            fresh_blocks = _fresh.parse_file(path)
        except Exception:  # noqa: BLE001
            fresh_blocks = []
    if fresh_blocks:
        for parsed in fresh_blocks:
            findings.extend(_grade_freshness(rel, parsed, inv, today))
        # FRESHNESS present means the file is annotated — still run regex for any
        # stray legacy anchors the block might not cover, but it is not UNANNOTATED.
        findings.extend(_grade_regex(rel, text, inv, today, annotated=True))
        return findings

    # 2) regex catalog (PRIMARY) for un-FRESHNESS'd files.
    regex_findings = _grade_regex(rel, text, inv, today, annotated=False)
    if regex_findings:
        return regex_findings

    # 3) nothing found anywhere -> UNANNOTATED (advisory only, never RED).
    return [{"file": rel, "verdict": "UNANNOTATED", "anchor": None,
             "kind": None, "detail": "no version/date/model anchors found",
             "confidence": "low"}]


def _grade_freshness(rel: str, parsed: dict, inv: dict, today: date) -> list[dict]:
    out = []
    vol = parsed.get("volatility", "medium")
    for a in parsed.get("anchors", []):
        kind = a.get("kind")
        if kind == "tool_version":
            subj = a.get("subject")
            anchored = a.get("verified_against")
            installed = _installed_version(inv, subj) if subj else None
            if anchored and installed:
                if _behind_by_minor(anchored, installed):
                    out.append(_f(rel, "RED", anchored, "tool_version", "high",
                                  f"{subj} anchor {anchored} behind installed {installed}"))
                elif _semver(anchored) == _semver(installed):
                    out.append(_f(rel, "GREEN", anchored, "tool_version", "high",
                                  f"{subj} {anchored} matches installed"))
                else:
                    # ahead, or only patch-behind -> GREEN (acceptable)
                    out.append(_f(rel, "GREEN", anchored, "tool_version", "high",
                                  f"{subj} {anchored} vs installed {installed} (within patch)"))
            else:
                out.append(_f(rel, "VAGUE", anchored, "tool_version", "medium",
                              f"{subj} not in inventory; cannot grade"))
        elif kind in ("date_review", "retirement"):
            deadline = a.get("review_by") or a.get("retire_on")
            out.append(_grade_deadline(rel, deadline, kind, vol, today, "high"))
        elif kind == "model_id":
            out.append(_f(rel, "VAGUE", a.get("subject"), "model_id", "medium",
                          "model-ID anchor (no model registry in v1)"))
        elif kind == "status_snapshot":
            deadline = a.get("review_by")
            if deadline:
                out.append(_grade_deadline(rel, deadline, "status_snapshot", vol, today, "high"))
    return [o for o in out if o is not None]


def _grade_regex(rel: str, text: str, inv: dict, today: date, annotated: bool) -> list[dict]:
    out = []
    lines = text.splitlines()

    def _near_proximity(match_start: int) -> bool:
        # ±2 lines proximity to a version/verify/cover/review token.
        upto = text[:match_start]
        line_no = upto.count("\n")
        lo = max(0, line_no - 2)
        hi = min(len(lines), line_no + 3)
        window = "\n".join(lines[lo:hi])
        return bool(_PROXIMITY_TOKENS.search(window))

    seen = set()

    # band-style "Covers ... 2.1.x" -> VAGUE (acceptable, never RED). Check FIRST so
    # the exact-version regex below doesn't try to grade the "2.1" prefix of a band.
    for m in RE_COVERS_BAND.finditer(text):
        band = m.group(1)
        if ("band", band) in seen:
            continue
        seen.add(("band", band))
        out.append(_f(rel, "VAGUE", band, "tool_version", "low", "band-style version"))

    # tool-version "Covers ... 0.118.0"
    for m in RE_COVERS_VERSION.finditer(text):
        if RE_VAGUE_BAND.search(m.group(0)):
            continue  # already handled as a band above
        ver = m.group(1)
        ctx = text[max(0, m.start() - 80):m.end() + 80]
        tool = _tool_join_key(ctx, ver)
        key = ("ver", tool, ver)
        if key in seen:
            continue
        seen.add(key)
        installed = _installed_version(inv, tool) if tool else None
        if tool and installed and _behind_by_minor(ver, installed):
            out.append(_f(rel, "RED", ver, "tool_version", "medium",
                          f"covers {tool} {ver} but installed {installed}"))
        elif tool and installed and _semver(ver) == _semver(installed):
            out.append(_f(rel, "GREEN", ver, "tool_version", "medium",
                          f"covers {tool} {ver} matches installed"))
        elif RE_VAGUE_BAND.search(ver):
            out.append(_f(rel, "VAGUE", ver, "tool_version", "low", "band-style version"))
        # else: no inventory match -> not graded (avoid false RED)

    # table-row / inline tool-version claims: "Codex CLI version | 0.118.0 (verified ...)".
    # Proximity-gated to a version/verify token so we don't grade arbitrary "<tool> 2.1"
    # prose; only graded against inventory (no false RED when the tool isn't tracked).
    for m in RE_TOOL_VERSION_CLAIM.finditer(text):
        if not _near_proximity(m.start()):
            continue
        tool = m.group(1).lower()
        ver = m.group(2)
        key = ("tvc", tool, ver)
        if key in seen:
            continue
        seen.add(key)
        if RE_VAGUE_BAND.search(m.group(0)):
            continue
        installed = _installed_version(inv, tool)
        if installed and _behind_by_minor(ver, installed):
            out.append(_f(rel, "RED", ver, "tool_version", "medium",
                          f"{tool} version {ver} but installed {installed}"))
        elif installed and _semver(ver) == _semver(installed):
            out.append(_f(rel, "GREEN", ver, "tool_version", "medium",
                          f"{tool} {ver} matches installed"))

    # "verified 2026-04-08" dates
    for m in RE_VERIFIED_DATE.finditer(text):
        ds = m.group(1)
        if ("vdate", ds, m.start()) in seen:
            continue
        # A verified-on date in the past is NOT itself RED (verification ages
        # gracefully); it is informational. Only flag if extremely stale (>1yr) as YELLOW.
        d = _safe_date(ds)
        if d and (today - d).days > 365:
            out.append(_f(rel, "YELLOW", ds, "date_review", "medium",
                          f"verified {ds} is >1yr old"))

    # "Status as of <date>" / "as of <date>" — a status-snapshot claim. A PAST date
    # means the snapshot is stale -> RED (the wiring-reconcile case). Future/recent
    # -> GREEN. Proximity-gated so prose "as of 2024" without a status token is softer.
    for m in RE_AS_OF.finditer(text):
        ds = m.group(1)
        d = _safe_date(ds)
        if d is None:
            continue
        key = ("asof", ds, m.start() // 200)
        if key in seen:
            continue
        seen.add(key)
        delta = (d - today).days
        # Only treat clearly-stale (>=21 days past) status snapshots as RED to avoid
        # flapping on a snapshot written days ago.
        if delta <= -21:
            out.append(_f(rel, "RED", ds, "status_snapshot", "medium",
                          f"status 'as of {ds}' is stale ({delta}d)"))

    # explicit deadlines: REVIEW-BY / Annual review on / retirement
    for rx, kind in ((RE_REVIEW_BY, "date_review"), (RE_ANNUAL, "date_review"),
                     (RE_RETIRE, "retirement")):
        for m in rx.finditer(text):
            ds = m.group(1)
            g = _grade_deadline(rel, ds, kind, "medium", today, "medium")
            if g:
                out.append(g)

    # model-ID anchors (proximity-gated to suppress prose)
    for rx, fam in ((RE_MODEL_CLAUDE, "claude"), (RE_MODEL_GPT, "gpt"),
                    (RE_MODEL_GEMINI, "gemini")):
        for m in rx.finditer(text):
            if not _near_proximity(m.start()):
                continue
            sub = m.group(0)
            if ("model", sub) in seen:
                continue
            seen.add(("model", sub))
            out.append(_f(rel, "VAGUE", sub, "model_id", "low",
                          "model-ID anchor (advisory; no model registry in v1)"))

    return out


def _grade_deadline(rel, ds, kind, vol, today, confidence):
    d = _safe_date(ds)
    if d is None:
        return None
    horizon = HIGH_VOL_HORIZON if vol == "high" else DEFAULT_HORIZON
    delta = (d - today).days
    if delta < 0:
        return _f(rel, "RED", ds, kind, confidence, f"deadline {ds} is past ({delta}d)")
    if delta <= horizon:
        return _f(rel, "YELLOW", ds, kind, confidence,
                  f"deadline {ds} within {horizon}d horizon ({delta}d)")
    return _f(rel, "GREEN", ds, kind, confidence, f"deadline {ds} beyond horizon ({delta}d)")


def _safe_date(ds: str):
    ds = (ds or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(ds, fmt)
            if fmt == "%Y":
                return date(dt.year, 12, 31)
            if fmt == "%Y-%m":
                return date(dt.year, dt.month, 1)
            return dt.date()
        except ValueError:
            continue
    return None


def _f(rel, verdict, anchor, kind, confidence, detail) -> dict:
    return {"file": rel, "verdict": verdict, "anchor": anchor, "kind": kind,
            "confidence": confidence, "detail": detail}


# ── library walk + report ────────────────────────────────────────────────────

def iter_targets(skills_root: Path, agents_root: Path, exclude_fixtures: bool = True):
    if skills_root.is_dir():
        for f in sorted(skills_root.rglob("*.md")):
            parts = set(f.parts)
            # Always skip vendored / archive / cache noise.
            if parts & {"archive", "__pycache__", ".pytest_cache", "node_modules"}:
                continue
            # Skip fixture/test trees only on a default library scan (a custom --root
            # pointed AT a fixture tree must scan it — golden tests rely on this).
            if exclude_fixtures and (parts & {"fixtures"} or "tests" in f.parts):
                continue
            yield f
    if agents_root.is_dir():
        for f in sorted(agents_root.glob("*.md")):
            yield f
    # S055: the workflows root carries FRESHNESS:v1 anchors in JS block comments;
    # scan *.md (README) + *.js so a stale tool_version anchor in a workflow is
    # graded just like a stale anchor in a skill. ONLY on a real LIBRARY scan
    # (skills_root == the live SKILLS_ROOT) — a fixture-scoped scan (golden tests
    # pass a fixture skills_root) must NOT pull in the live workflows tree.
    if skills_root == SKILLS_ROOT and WORKFLOWS_ROOT.is_dir():
        for f in sorted(WORKFLOWS_ROOT.glob("*.md")) + sorted(WORKFLOWS_ROOT.glob("*.js")):
            yield f


def run_scan(skills_root: Path, agents_root: Path, inv: dict, today: date,
             exclude_fixtures: bool = True) -> dict:
    t0 = time.time()
    findings: list[dict] = []
    last_error = None
    n_files = 0
    try:
        for f in iter_targets(skills_root, agents_root, exclude_fixtures):
            n_files += 1
            findings.extend(scan_file(f, inv, today))
    except Exception as e:  # noqa: BLE001 — never crash; record the error
        last_error = str(e)

    # Dedup identical findings (a file can match both its FRESHNESS block and a
    # legacy regex for the SAME anchor; collapse to one row). Key on the salient
    # fields; preserve first-seen order for determinism.
    deduped: list[dict] = []
    seen_keys = set()
    for fnd in findings:
        key = (fnd["file"], fnd["verdict"], str(fnd.get("anchor")), fnd.get("kind"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(fnd)
    findings = deduped
    runtime_ms = int((time.time() - t0) * 1000)

    counts = {"RED": 0, "YELLOW": 0, "GREEN": 0, "VAGUE": 0, "UNANNOTATED": 0}
    for fnd in findings:
        counts[fnd["verdict"]] = counts.get(fnd["verdict"], 0) + 1

    report = {
        "schema_version": REPORT_SCHEMA,
        "scanner_version": SCANNER_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "today": today.isoformat(),
        "files_scanned": n_files,
        "counts": counts,
        "last_success": last_error is None,
        "last_error": last_error,
        "runtime_ms": runtime_ms,
        "findings": findings,
    }
    return report


def write_report(report: dict) -> None:
    STATE_FRESH.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(REPORT_FILE))
    # append a one-line summary to rot-history.jsonl (best-effort).
    try:
        summary = {k: report[k] for k in
                   ("schema_version", "scanner_version", "generated_at",
                    "files_scanned", "counts", "runtime_ms", "last_success")}
        fd = os.open(str(HISTORY_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (json.dumps(summary, separators=(",", ":"), sort_keys=True) + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rot_scan.py", description="regex-primary rot scanner")
    p.add_argument("--root", default=None, help="skills root (default ~/.claude/skills)")
    p.add_argument("--agents", default=None, help="agents root (default ~/.claude/agents)")
    p.add_argument("--inventory", default=None, help="inventory.json path")
    p.add_argument("--today", default=None, help="override today (YYYY-MM-DD)")
    p.add_argument("--json", action="store_true", help="print full report JSON to stdout")
    p.add_argument("--refresh", action="store_true", help="re-run + rewrite report (default behaviour)")
    p.add_argument("--no-write", action="store_true", help="do not write report (dry)")
    args = p.parse_args(argv)

    skills_root = Path(args.root) if args.root else SKILLS_ROOT
    agents_root = Path(args.agents) if args.agents else AGENTS_ROOT
    inv = load_inventory(Path(args.inventory) if args.inventory else INVENTORY_FILE)
    today = date.fromisoformat(args.today) if args.today else date.today()

    # A custom --root (e.g. a golden fixture tree) is scanned in full; the default
    # library scan excludes fixture/test trees.
    exclude_fixtures = args.root is None
    report = run_scan(skills_root, agents_root, inv, today, exclude_fixtures)
    if not args.no_write:
        write_report(report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        c = report["counts"]
        print(f"rot_scan v{SCANNER_VERSION}: {report['files_scanned']} files in "
              f"{report['runtime_ms']}ms — RED {c['RED']} / YELLOW {c['YELLOW']} / "
              f"GREEN {c['GREEN']} / VAGUE {c['VAGUE']} / UNANNOTATED {c['UNANNOTATED']}")
        reds = [f for f in report["findings"] if f["verdict"] == "RED"]
        for r in reds:
            print(f"  RED  {r['file']}: {r['detail']}")
        yellows = [f for f in report["findings"] if f["verdict"] == "YELLOW"]
        for y in yellows[:20]:
            print(f"  YEL  {y['file']}: {y['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
