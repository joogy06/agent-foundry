#!/usr/bin/env python3
"""reconcile.py — S074. Two skill trees that share an ancestor and have drifted apart.

The situation this exists for: two repos were forked from one, both were worked on, and
now one has many more skills and scripts than the other. Somebody has to decide which is
the target, what to bring across, and what has silently diverged in BOTH.

    diff     classify every skill in both trees
    plan     the migration worklist, in dependency-aware order
    gaps     capability present in source and absent in target — the "what am I missing"

WHAT IT DOES NOT DO, DELIBERATELY

**It never copies anything.** Enumeration is mechanical and safe; migration is a decision
per item, and `skill-intake` is where that decision is made. A tool that both classified
and moved would make the easy half feel like the whole job.

WHY `divergent` IS THE CATEGORY THAT MATTERS

`source_only` is a shopping list and everyone finds it. `divergent` — same name, different
content, both edited since the fork — is where work gets destroyed, because whoever copies
last wins and the loss is silent. Those are reported first and never summarised away.

ON "WHICH SIDE IS NEWER"

Modification times are reported and must not be trusted: copying a tree rewrites them, so
a freshly-cloned stale repo looks newer than the original it came from. Size and line count
are reported for the same reason and carry the same warning — **more lines is not better,
and this tool cannot tell you which version is right.** It tells you they differ.

Stdlib only. Exit: 0 trees agree · 2 differences found · 3 bad input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", "archive", "evals"}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def skill_files(root: Path) -> list[Path]:
    """Every tracked file under a skill dir, relative, stable order."""
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in {".pyc", ".tmp"}:
            continue
        out.append(p)
    return out


def scan(root: Path) -> dict[str, dict]:
    """One entry per skill directory (a dir containing SKILL.md)."""
    if not root.is_dir():
        sys.exit(f"[input] not a directory: {root}")
    skills = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name in SKIP_DIRS or d.name.startswith("."):
            continue
        sk = d / "SKILL.md"
        if not sk.is_file():
            continue
        files = skill_files(d)
        digests = {str(f.relative_to(d)): sha(f) for f in files}
        skills[d.name] = {
            "files": len(files),
            "bytes": sum(f.stat().st_size for f in files),
            "lines": sum(f.read_text(errors="replace").count("\n")
                         for f in files if f.suffix in {".md", ".py", ".sh", ".yaml", ".json"}),
            "mtime": max((f.stat().st_mtime for f in files), default=0),
            "digests": digests,
            "tree_hash": hashlib.sha256(
                json.dumps(digests, sort_keys=True).encode()).hexdigest(),
        }
    return skills


def classify(src: dict, tgt: dict) -> dict:
    both = sorted(set(src) & set(tgt))
    out = {
        "source_only": sorted(set(src) - set(tgt)),
        "target_only": sorted(set(tgt) - set(src)),
        "identical": [n for n in both if src[n]["tree_hash"] == tgt[n]["tree_hash"]],
        "divergent": [],
    }
    for n in both:
        if src[n]["tree_hash"] == tgt[n]["tree_hash"]:
            continue
        s, t = src[n], tgt[n]
        sk, tk = set(s["digests"]), set(t["digests"])
        out["divergent"].append({
            "name": n,
            "files_only_in_source": sorted(sk - tk),
            "files_only_in_target": sorted(tk - sk),
            "files_changed": sorted(f for f in (sk & tk)
                                    if s["digests"][f] != t["digests"][f]),
            "source": {"files": s["files"], "lines": s["lines"],
                       "mtime": datetime.fromtimestamp(s["mtime"]).date().isoformat()},
            "target": {"files": t["files"], "lines": t["lines"],
                       "mtime": datetime.fromtimestamp(t["mtime"]).date().isoformat()},
        })
    out["divergent"].sort(key=lambda r: -(len(r["files_changed"])
                                          + len(r["files_only_in_source"])
                                          + len(r["files_only_in_target"])))
    return out


MTIME_WARNING = (
    "mtimes are shown but must NOT be read as 'newer is better' — copying a tree rewrites\n"
    "  them, so a freshly-cloned stale repo looks newer than what it came from. Line counts\n"
    "  are shown for scale, not quality."
)


def cmd_diff(args) -> int:
    src, tgt = scan(args.source), scan(args.target)
    c = classify(src, tgt)
    if args.json:
        print(json.dumps({"source": str(args.source), "target": str(args.target),
                          "counts": {k: len(v) for k, v in c.items()}, **c}, indent=2))
        return 2 if (c["source_only"] or c["divergent"] or c["target_only"]) else 0

    print(f"SOURCE {args.source}  ({len(src)} skills)")
    print(f"TARGET {args.target}  ({len(tgt)} skills)\n")
    print(f"  identical    {len(c['identical']):>4}")
    print(f"  source only  {len(c['source_only']):>4}   candidates to migrate")
    print(f"  target only  {len(c['target_only']):>4}   already ahead in target")
    print(f"  DIVERGENT    {len(c['divergent']):>4}   same name, different content\n")

    if c["divergent"]:
        print("DIVERGENT — decide these FIRST. Copying either way loses the other side.\n")
        for r in c["divergent"][: args.limit]:
            print(f"  {r['name']}")
            print(f"    source: {r['source']['files']} files, {r['source']['lines']} lines, "
                  f"touched {r['source']['mtime']}")
            print(f"    target: {r['target']['files']} files, {r['target']['lines']} lines, "
                  f"touched {r['target']['mtime']}")
            if r["files_changed"]:
                print(f"    changed: {', '.join(r['files_changed'][:6])}"
                      + (" ..." if len(r["files_changed"]) > 6 else ""))
            if r["files_only_in_source"]:
                print(f"    only in source: {', '.join(r['files_only_in_source'][:6])}")
            if r["files_only_in_target"]:
                print(f"    only in target: {', '.join(r['files_only_in_target'][:6])}")
            print()
        if len(c["divergent"]) > args.limit:
            print(f"  ... and {len(c['divergent']) - args.limit} more "
                  f"(raise --limit; none were dropped from the counts above)\n")
        print("  " + MTIME_WARNING + "\n")

    if c["source_only"]:
        print(f"SOURCE ONLY ({len(c['source_only'])}) — each needs a skill-intake verdict, "
              f"not a copy:\n  " + ", ".join(c["source_only"]) + "\n")
    if c["target_only"]:
        print(f"TARGET ONLY ({len(c['target_only'])}):\n  " + ", ".join(c["target_only"]) + "\n")
    return 2 if (c["source_only"] or c["divergent"] or c["target_only"]) else 0


def cmd_plan(args) -> int:
    src, tgt = scan(args.source), scan(args.target)
    c = classify(src, tgt)
    lines = [
        f"# Reconciliation plan — {date.today().isoformat()}",
        "",
        f"- **Source:** `{args.source}` ({len(src)} skills)",
        f"- **Target:** `{args.target}` ({len(tgt)} skills) — **the target is where work lands**",
        "",
        "Nothing here has been copied. Each row is a decision.",
        "",
        "## 1. Divergent — resolve before anything else",
        "",
    ]
    if c["divergent"]:
        lines += ["Same name, different content on both sides. **Copying either direction destroys "
                  "the other's work silently.** Merge per `skill-intake` §5.", "",
                  "| Skill | Changed | Only in source | Only in target | Decision |",
                  "|---|---|---|---|---|"]
        for r in c["divergent"]:
            lines.append(f"| `{r['name']}` | {len(r['files_changed'])} | "
                         f"{len(r['files_only_in_source'])} | "
                         f"{len(r['files_only_in_target'])} | _merge / keep-target / keep-source_ |")
    else:
        lines.append("_None — every shared skill is byte-identical._")

    lines += ["", "## 2. Source-only — one verdict each", "",
              "Run `assess.py` per skill. **REJECT is the default**: a skill that adds nothing "
              "dilutes selection for the whole target library.", ""]
    if c["source_only"]:
        lines += ["| Skill | Verdict | Note |", "|---|---|---|"]
        lines += [f"| `{n}` | _adopt / adapt / merge / reject_ | |" for n in c["source_only"]]
    else:
        lines.append("_None._")

    lines += ["", "## 3. After any migration — the integration steps", "",
              "1. `python3 _meta/skill_overlap.py` — a migrated skill that collides with an "
              "existing one degrades selection; add `disambiguation:` before re-pinning the baseline.",
              "2. Check every cross-reference the migrated skill makes — a `See also` pointing at a "
              "skill that exists only in the source is a phantom reference.",
              "3. Re-point absolute paths and any harness-specific assumptions (`skill-intake` §4).",
              "4. Create the symlinks / mirrors the target expects.",
              "5. Run the target's test suite. Migrated scripts are the ones that break.",
              "6. Record provenance — where it came from, what changed (`skill-intake` §6).", ""]
    if c["target_only"]:
        lines += [f"## 4. Target-only ({len(c['target_only'])}) — no action, listed for completeness",
                  "", ", ".join(f"`{n}`" for n in c["target_only"]), ""]

    text = "\n".join(lines)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 2 if (c["source_only"] or c["divergent"]) else 0


def cmd_gaps(args) -> int:
    """Capability in source that target lacks — described, not just named."""
    src, tgt = scan(args.source), scan(args.target)
    c = classify(src, tgt)
    if not c["source_only"]:
        print("No skills exist in source that are absent from target.")
        return 0
    print(f"{len(c['source_only'])} skill(s) in source and not in target.\n")
    for n in c["source_only"]:
        d = args.source / n / "SKILL.md"
        desc = ""
        for line in d.read_text(errors="replace").splitlines()[:12]:
            if line.startswith("description:"):
                desc = line[len("description:"):].strip().strip('"\'>')
                break
        print(f"  {n}  ({src[n]['files']} files, {src[n]['lines']} lines)")
        print(f"    {desc[:180]}{'...' if len(desc) > 180 else ''}\n")
    print("Each is a CANDIDATE, not a requirement. The question skill-intake §2 asks is:")
    print("  what can the target do with this that it could not before?")
    print("  If you cannot name a task the target currently handles badly, the answer is REJECT.")
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Classify two skill trees that share an ancestor and have drifted.")
    ap.add_argument("--source", type=Path, required=True, help="tree to migrate FROM")
    ap.add_argument("--target", type=Path, required=True, help="tree work lands IN")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("diff")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int, default=15, help="divergent entries printed in full")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("plan"); p.add_argument("--out", type=Path); p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("gaps"); p.set_defaults(fn=cmd_gaps)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
