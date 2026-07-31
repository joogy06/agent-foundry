#!/usr/bin/env python3
"""sync_metadata.py — keep the three repo-metadata surfaces in sync from ONE source.

The catalog README counts/version header, and the GitHub "About" (description +
topics) drift apart because no single tool owns all of them (see the
`repo-metadata-maintenance` memory). This engine derives all of them from the LIVE
source tree (the same `source.root` + `subdirs` + `exclusions` the publisher uses)
so a publish can reconcile every surface in one step.

Operations:
  counts                 print the live {skills,agents,workflows,commands} counts
  readme  --readme P     rewrite the count tokens + `Last published:` date (and,
                         with --bump, the Version) in catalog README P
  about   --repo R       apply (or, without --apply, print) the GitHub About from
                         the publish-config `about` block, with {skills}/{agents}/…
                         placeholders substituted from the live counts
  sync    --readme P --repo R [--apply]   do both

Design: deterministic + idempotent. README edits are local (always safe). The
`about` op runs `gh repo edit` ONLY with --apply (mirrors the skill's "print, don't
auto-mutate" discipline); without --apply it prints the exact command.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# config + counting
# --------------------------------------------------------------------------- #
def load_config(path: str | None) -> dict:
    for cand in (path, os.environ.get("PUBLISH_CONFIG"),
                 str(Path.home() / ".claude" / "publish-config.json"),
                 "./publish-config.json"):
        if cand and Path(cand).expanduser().is_file():
            return json.loads(Path(cand).expanduser().read_text())
    raise SystemExit("ERROR: no publish-config.json found (pass --config).")


# Always-skip these name patterns on any path part (mirrors publish_prep
# ALWAYS_EXCLUDE_PATTERNS) so the count matches what is actually published.
_ALWAYS_EXCLUDE = ("__pycache__", ".pytest_cache", "*.pyc", ".DS_Store", "*.swp", "*.swo")


def _excluded(rel: str, exclusions: list[str]) -> bool:
    # Config exclusions are LITERAL exact-or-prefix matches — faithful to
    # publish_prep.should_exclude (NOT fnmatch globs), so counts cannot diverge.
    for excl in exclusions:
        e = excl.rstrip("/")
        if rel == excl or rel == e or rel.startswith(e + "/"):
            return True
    # Plus the always-exclude name patterns on any path component.
    for part in rel.split("/"):
        if part.startswith(".") or part.startswith("__"):
            return True
        for pat in _ALWAYS_EXCLUDE:
            if fnmatch.fnmatch(part, pat):
                return True
    return False


def live_counts(cfg: dict) -> dict:
    src = cfg.get("source", {})
    root = Path(src.get("root", "~/.claude")).expanduser()
    subdirs = src.get("subdirs", ["skills", "agents", "commands", "workflows"])
    excl = cfg.get("exclusions", [])
    out = {"skills": 0, "agents": 0, "workflows": 0, "commands": 0}
    for sub in subdirs:
        d = root / sub
        if not d.is_dir():
            continue
        if sub == "skills":
            items = [c for c in d.iterdir() if c.is_dir()]
        else:  # agents/commands = *.md files; workflows = *.* files
            items = [c for c in d.iterdir() if c.is_file()
                     and not c.name.startswith(".") and c.suffix]
        n = sum(1 for c in items if not _excluded(f"{sub}/{c.name}", excl))
        if sub in out:
            out[sub] = n
    return out


# --------------------------------------------------------------------------- #
# README rewriting
# --------------------------------------------------------------------------- #
def _bump(version: str, kind: str) -> str:
    a, b, c = (int(x) for x in version.split("."))
    if kind == "major":
        return f"{a + 1}.0.0"
    if kind == "minor":
        return f"{a}.{b + 1}.0"
    return f"{a}.{b}.{c + 1}"


def sync_readme(path: Path, counts: dict, today: str, bump: str | None) -> list[str]:
    """Rewrite count tokens + Last-published (+ optional version bump). Returns the
    list of human-readable changes (empty = already in sync)."""
    text = path.read_text()
    orig = text
    changes: list[str] = []

    # Count bullets — ANCHORED to a markdown list item that STARTS with the bold
    # count (`- **N skills**`), so changelog/body prose like `159 -> **182 skills**`
    # is NEVER rewritten (that would corrupt historical entries on re-run).
    text = re.sub(r"(?m)^(\s*[-*]\s+)\*\*\d+ skills\b",
                  rf"\g<1>**{counts['skills']} skills", text)
    text = re.sub(r"(?m)^(\s*[-*]\s+)\*\*\d+ agents\b",
                  rf"\g<1>**{counts['agents']} agents", text)
    text = re.sub(r"(?m)^(\s*[-*]\s+)\*\*\d+ (saved )?workflows\b",
                  lambda m: f"{m.group(1)}**{counts['workflows']} {m.group(2) or ''}workflows", text)

    # Header tuple: `**182 skills · 5 agents · 9 workflows · 2 commands**`
    header = (f"**{counts['skills']} skills · {counts['agents']} agents · "
              f"{counts['workflows']} workflows · {counts['commands']} commands**")
    text = re.sub(r"\*\*\d+ skills · \d+ agents · \d+ workflows · \d+ commands\*\*",
                  header, text)

    # Last published date
    text = re.sub(r"(\*\*Last published:\*\* )\d{4}-\d{2}-\d{2}", rf"\g<1>{today}", text)

    # Optional version bump
    if bump:
        m = re.search(r"\*\*Version:\*\* (\d+\.\d+\.\d+)", text)
        if m:
            newv = _bump(m.group(1), bump)
            text = text.replace(f"**Version:** {m.group(1)}", f"**Version:** {newv}", 1)
            changes.append(f"version {m.group(1)} -> {newv}")

    if text != orig:
        path.write_text(text)
        changes.insert(0, f"counts -> {counts}; last_published={today}")
    return changes


# --------------------------------------------------------------------------- #
# GitHub About
# --------------------------------------------------------------------------- #
def about_for(cfg: dict, repo: str, counts: dict) -> dict | None:
    block = (cfg.get("about") or {}).get(repo)
    if not block:
        return None
    desc = (block.get("description") or "").format(**counts)
    return {"description": desc,
            "topics": block.get("topics", []),
            "homepage": block.get("homepage", "")}


def _current_topics(repo: str) -> list[str]:
    try:
        r = subprocess.run(["gh", "repo", "view", repo, "--json", "repositoryTopics"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return [t["name"] for t in (json.loads(r.stdout).get("repositoryTopics") or [])]
    except Exception:
        pass
    return []


def apply_about(repo: str, about: dict, do_apply: bool) -> int:
    desired = about.get("topics", [])
    cmd = ["gh", "repo", "edit", repo, "--description", about["description"]]
    if about.get("homepage"):
        cmd += ["--homepage", about["homepage"]]
    # FULL topic reconciliation: add desired, and remove stale topics no longer
    # in the config set (read-only gh repo view; safe in dry-run too).
    current = _current_topics(repo)
    for t in desired:
        cmd += ["--add-topic", t]
    for t in current:
        if t not in desired:
            cmd += ["--remove-topic", t]
    if not do_apply:
        print("  (dry-run — re-run with --apply to set) About command:")
        print("   ", " ".join(f'"{c}"' if " " in c else c for c in cmd))
        return 0
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"  ERROR: gh repo edit failed: {r.stderr.strip()[:200]}", file=sys.stderr)
        return 1
    print(f"  About applied to {repo}: {about['description'][:70]}…")
    return 0


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Sync README counts/version + GitHub About from the live tree.")
    p.add_argument("op", choices=["counts", "readme", "about", "sync"])
    p.add_argument("--config", default=None)
    p.add_argument("--readme", default=None, help="catalog README path (readme/sync).")
    p.add_argument("--repo", default=None, help="owner/repo for the About (about/sync).")
    p.add_argument("--bump", choices=["major", "minor", "patch"], default=None)
    p.add_argument("--date", default=None, help="override Last-published date (default: today UTC).")
    p.add_argument("--apply", action="store_true", help="actually run gh repo edit (else dry-run).")
    a = p.parse_args(argv)

    cfg = load_config(a.config)
    counts = live_counts(cfg)
    today = a.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    if a.op == "counts":
        print(json.dumps(counts, sort_keys=True))
        return 0

    rc = 0
    if a.op in ("readme", "sync"):
        if not a.readme:
            print("ERROR: --readme required", file=sys.stderr); return 2
        changes = sync_readme(Path(a.readme).expanduser(), counts, today, a.bump)
        print(f"README {a.readme}: " + ("; ".join(changes) if changes else "already in sync"))

    if a.op in ("about", "sync"):
        if not a.repo:
            print("ERROR: --repo required", file=sys.stderr); return 2
        about = about_for(cfg, a.repo, counts)
        if not about:
            print(f"  no `about.{a.repo}` block in publish-config — skipping About.")
        else:
            rc |= apply_about(a.repo, about, a.apply)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
