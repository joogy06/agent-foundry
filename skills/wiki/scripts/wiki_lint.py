#!/usr/bin/env python3
"""wiki_lint.py — S074 (#35). The deterministic half of the wiki protocol, as a command.

`schema.md`, `lint.md` and `ingest.md` describe a protocol precisely enough that parts of it
are pure mechanism — required fields, enum membership, slug/filename agreement, source-entry
shape, wikilink resolution. Those were being re-derived by a model on every run: slow,
expensive, and inconsistent across runs in a way that makes a lint result unciteable.

    create   bootstrap a new wiki — directory skeleton + WIKI.md with its 11 sections
    lint     validate every page against the frontmatter contract and resolve wikilinks

WHAT IS DELIBERATELY NOT SCRIPTED

`ingest.py` is not here, and should not be. Reading a PDF and deciding what a page ought to
SAY is comprehension, not mechanism — a script that pretended otherwise would produce
confident, shallow pages. The mechanical parts of ingestion (discovery, hashing, dedup) are
worth extracting later; the judgement is not.

THE LINT CONTRACT

Structural failures are ERRORS: the page cannot be trusted to participate in the wiki.
Content concerns are WARNINGS: staleness, thin sources, orphan pages. Conflating them
trains people to ignore the output — the same reason `business-profile` reports drift as a
question rather than a verdict.

A broken wikilink is an ERROR, because a wiki whose links do not resolve is a worse
reference than no wiki: it asserts connections that are not there.

Stdlib only; yaml optional and its absence is REPORTED, never silently passed.
Exit: 0 clean · 2 findings · 3 bad input.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
    HAVE_YAML = True
except ImportError:                                   # pragma: no cover - env dependent
    HAVE_YAML = False

REQUIRED = ["type", "title", "slug", "created", "updated", "sources", "tags",
            "status", "confidence"]
STATUS = {"draft", "active", "review", "archived"}
CONFIDENCE = {"high", "medium", "low", "uncertain"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

SECTIONS = [
    "Identity & Purpose", "Directory Structure", "Page Types",
    "Frontmatter Conventions", "Cross-Referencing Rules", "Naming Conventions",
    "Output Formats", "Maintenance Workflows", "Obsidian Compatibility",
    "Domain-Specific Behavior", "Evolution Log",
]
STALE_DAYS = 180


# ---------------------------------------------------------------- helpers


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    return text[3:end], text[end + 4:]


def parse_date(v) -> date | None:
    s = str(v).strip()
    if not DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- lint


def lint_page(path: Path, slugs: set[str], today: date,
              page_types: set[str] | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = split_frontmatter(text)
    if fm is None:
        return [("E", "no YAML frontmatter")]
    if not HAVE_YAML:
        return [("W", "pyyaml absent — frontmatter NOT validated for this page")]
    try:
        meta = yaml.safe_load(fm)
    except Exception as e:
        return [("E", f"frontmatter does not parse: {str(e).splitlines()[0]}")]
    if not isinstance(meta, dict):
        return [("E", "frontmatter is not a mapping")]

    for k in REQUIRED:
        if k not in meta:
            out.append(("E", f"missing required field `{k}`"))

    slug = meta.get("slug")
    if slug:
        if not SLUG_RE.match(str(slug)):
            out.append(("E", f"slug `{slug}` is not kebab-case"))
        if str(slug) != path.stem:
            out.append(("E", f"slug `{slug}` != filename `{path.stem}`"))

    if (st := meta.get("status")) is not None and st not in STATUS:
        out.append(("E", f"status `{st}` not in {sorted(STATUS)}"))
    if (cf := meta.get("confidence")) is not None and cf not in CONFIDENCE:
        out.append(("E", f"confidence `{cf}` not in {sorted(CONFIDENCE)}"))
    if page_types and (ty := meta.get("type")) is not None and ty not in page_types:
        out.append(("E", f"type `{ty}` not in the WIKI.md Page Types table"))

    created = updated = None
    for k in ("created", "updated"):
        if k in meta:
            d = parse_date(meta[k])
            if d is None:
                out.append(("E", f"`{k}` is not YYYY-MM-DD: {meta[k]!r}"))
            elif k == "created":
                created = d
            else:
                updated = d
    if created and updated and updated < created:
        out.append(("E", f"updated {updated} precedes created {created}"))
    if updated and (age := (today - updated).days) > STALE_DAYS:
        out.append(("W", f"not updated for {age} days"))

    # Sources — an 'overview' page may legitimately have none; nothing else may.
    srcs = meta.get("sources")
    if srcs is None or srcs == []:
        if meta.get("type") != "overview":
            out.append(("E", "no sources (only an 'overview' page may have none)"))
    elif not isinstance(srcs, list):
        out.append(("E", "`sources` is not a list"))
    else:
        for i, s in enumerate(srcs, 1):
            if not isinstance(s, dict):
                out.append(("E", f"source {i} is not a mapping"))
                continue
            if not s.get("path"):
                out.append(("E", f"source {i} has no `path`"))
            if not any(k in s for k in ("pages", "lines", "anchor")):
                out.append(("E", f"source {i} needs one of pages/lines/anchor "
                                 f"to be citable"))

    if meta.get("deprecated") and not meta.get("superseded_by"):
        out.append(("W", "deprecated with no `superseded_by` — the reader has nowhere to go"))

    for target in WIKILINK_RE.findall(body):
        t = target.strip()
        if t and t not in slugs:
            out.append(("E", f"wikilink [[{t}]] resolves to nothing"))

    if not isinstance(meta.get("tags", []), list):
        out.append(("E", "`tags` is not a list"))
    return out


def collect(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md")
                  if p.name != "WIKI.md" and "raw" not in p.relative_to(root).parts
                  and not p.name.startswith("."))


def cmd_lint(args) -> int:
    root: Path = args.wiki
    if not root.is_dir():
        sys.exit(f"[input] not a directory: {root}")
    wiki_md = root / "WIKI.md"
    page_types = None
    struct: list[tuple[str, str]] = []
    if not wiki_md.is_file():
        struct.append(("E", "no WIKI.md — this directory is not a wiki"))
    else:
        wt = wiki_md.read_text(encoding="utf-8", errors="replace")
        missing = [s for s in SECTIONS if s.lower() not in wt.lower()]
        if missing:
            struct.append(("E", f"WIKI.md missing {len(missing)} of 11 required sections: "
                                f"{', '.join(missing)}"))
        types = set(re.findall(r"^\|\s*`?([a-z][a-z0-9-]*)`?\s*\|", wt, re.M))
        page_types = types or None

    pages = collect(root)
    today = date.fromisoformat(args.today) if args.today else date.today()
    slugs = {p.stem for p in pages}

    results = {p: lint_page(p, slugs, today, page_types) for p in pages}
    errs = sum(1 for f in results.values() for c, _ in f if c == "E") + \
        sum(1 for c, _ in struct if c == "E")
    warns = sum(1 for f in results.values() for c, _ in f if c == "W")

    for code, msg in struct:
        print(f"{'FAIL' if code == 'E' else 'warn'} WIKI.md\n  {code} {msg}")
    for p, fs in results.items():
        if not fs:
            continue
        rel = p.relative_to(root)
        print(f"{'FAIL' if any(c == 'E' for c, _ in fs) else 'warn'} {rel}")
        for code, msg in fs:
            print(f"  {code} {msg}")

    print(f"\nwiki_lint: {len(pages)} page(s) · {errs} error(s) · {warns} warning(s)")
    if not HAVE_YAML:
        print("  NOTE: pyyaml absent — frontmatter was NOT validated. Degraded, not a pass.")
    return 2 if (errs or warns) else 0


# ---------------------------------------------------------------- create


WIKI_TEMPLATE = """# {name}

<!-- schema_version: 1.0.0 -->

## 1. Identity & Purpose

- **Name:** {name}
- **Domain:** {domain}
- **Visibility:** {visibility}
- **Purpose:** _One paragraph: what this wiki is for, and for whom._

## 2. Directory Structure

```
{slug}/
  raw/     immutable source material — never edited after ingestion
  wiki/    generated and curated pages — LLM-owned
  WIKI.md  this file: the wiki's own schema
```

## 3. Page Types

| type | purpose | required frontmatter | template |
|---|---|---|---|
| `overview` | Entry point; may have no sources | standard | general |
| `topic` | A subject with cited sources | standard | general |
| `source` | A single ingested artefact | standard | research |

## 4. Frontmatter Conventions

Required on every page: `type`, `title`, `slug`, `created`, `updated`, `sources`, `tags`,
`status`, `confidence`. Dates are `YYYY-MM-DD`. `status` is draft|active|review|archived.
`confidence` is high|medium|low|uncertain. Slugs are kebab-case and match the filename.

## 5. Cross-Referencing Rules

Wikilinks are `[[slug]]`. **A link that does not resolve is a lint error** — a wiki that
asserts connections it does not have is worse than no wiki.

## 6. Naming Conventions

Kebab-case slugs; filename equals slug plus `.md`.

## 7. Output Formats

Every non-obvious claim carries a source entry with `path` plus one of `pages`/`lines`/`anchor`.

## 8. Maintenance Workflows

Lint before publishing. A page not updated for {stale} days is flagged stale — suspect, not
wrong, and re-verified rather than deleted.

## 9. Obsidian Compatibility

`[[wikilink]]` syntax and YAML frontmatter are Obsidian-native. Keep it that way: the wiki
must stay usable without any tooling from this library.

## 10. Domain-Specific Behavior

_What makes this wiki different from a generic one. Fill this in — it is the section that
makes the wiki yours._

## 11. Evolution Log

| version | date | change |
|---|---|---|
| 1.0.0 | {today} | Created |
"""

OVERVIEW = """---
type: overview
title: "{name}"
slug: {slug}-overview
created: {today}
updated: {today}
sources: []
tags: []
status: draft
confidence: medium
---

# {name}

_Entry point. An overview page may carry no sources; every other page must._
"""


def cmd_create(args) -> int:
    root: Path = args.path
    if root.exists() and any(root.iterdir()):
        sys.exit(f"[input] {root} exists and is not empty — refusing to overwrite a wiki")
    today = args.today or date.today().isoformat()
    slug = args.name.lower().replace(" ", "-")
    if not SLUG_RE.match(slug):
        sys.exit(f"[input] name must reduce to a kebab-case slug; got {slug!r}")
    if args.dry_run:
        print(f"[dry-run] would create {root}/ with WIKI.md, raw/, wiki/{slug}-overview.md")
        return 0
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "wiki").mkdir(parents=True, exist_ok=True)
    (root / "WIKI.md").write_text(WIKI_TEMPLATE.format(
        name=args.name, domain=args.domain, visibility=args.visibility,
        slug=slug, today=today, stale=STALE_DAYS))
    (root / "wiki" / f"{slug}-overview.md").write_text(
        OVERVIEW.format(name=args.name, slug=slug, today=today))
    print(f"created {root}")
    print(f"  WIKI.md                       11 sections, schema 1.0.0")
    print(f"  raw/                          immutable sources")
    print(f"  wiki/{slug}-overview.md")
    print(f"\nSections 1 and 10 are placeholders ON PURPOSE — a wiki whose purpose and")
    print(f"domain behaviour are unstated will drift into a folder of notes. Fill them in,")
    print(f"then: wiki_lint.py lint --wiki {root}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Wiki bootstrap and lint (#35).")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("lint"); p.add_argument("--wiki", type=Path, required=True)
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("create")
    p.add_argument("--path", type=Path, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--domain", default="_unstated_")
    p.add_argument("--visibility", default="private")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_create)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
