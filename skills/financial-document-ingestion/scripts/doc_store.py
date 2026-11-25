#!/usr/bin/env python3
"""doc_store.py — S075. The document store §6 specifies, as commands (#227).

    add          hash a document, store it period-first, index it
    verify       re-hash every indexed document — OK / CHANGED / MISSING
    link         record the journal entry a document became (posted_ref)
    supersede    a correction REPLACES, never overwrites
    open-items   indexed documents with no posted_ref

WHAT THIS EXISTS TO PREVENT

A folder of PDFs and a set of books with no demonstrable relationship between them. That is
precisely what an enquiry probes, and it is what you have the moment indexing becomes a
thing done later. Filing later never happens.

THE FIELD THAT EARNS ITS KEEP IS posted_ref

It closes document -> validated rows -> posted entry. Everything else here is bookkeeping
about bookkeeping; `posted_ref` is the only field that makes a figure defensible years
after the person who posted it has forgotten it. An indexed document without one is an OPEN
ITEM, and `open-items` derives that list rather than reading a flag — so nobody can mark a
document closed without naming what it became.

IDENTITY IS THE HASH, NOT THE FILENAME

`sha256` is COMPUTED here and never accepted from input, for the same reason `overdue` is
absent from the accounting tracker: a caller must not be able to assert something the tool
can determine. It makes re-ingestion idempotent — the same statement handed over twice is
detected, not double-posted — and it is what proves, later, that this file is the one the
figure came from.

NEVER OVERWRITE

A corrected invoice is a NEW entry with `superseded_by` set on the old one. The original was
the basis of a filed return and remains part of the record. A byte-different file landing on
an occupied path is REFUSED, not silently replaced.

WHAT IT WILL NOT DO

It does not extract, validate or post. It does not prune for retention — six-year retention
means the answer to "is this old enough to delete?" is almost always no, and a tool that can
delete evidence to save disk is a tool that will one day delete evidence to save disk.

Stdlib only. Exit: 0 ok · 2 refused / verification failed · 3 bad input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "document-index.v1"
INDEX_NAME = "index.json"

# §6. Each type dictates where the document lives and what it must be told to get there.
DOC_TYPES = {
    "statement":       {"dir": "bank",        "needs": ("account",),  "period": "month"},
    "purchase_invoice": {"dir": "purchases",  "needs": ("supplier", "reference"), "period": "month"},
    "sales_invoice":   {"dir": "sales",       "needs": ("reference",), "period": "month"},
    "settlement":      {"dir": "settlements", "needs": ("provider",),  "period": "month"},
    "payroll":         {"dir": "payroll",     "needs": (),             "period": "month"},
    "filing":          {"dir": "filings",     "needs": ("reference",), "period": "year"},
}

SOURCES = ("email", "download", "woocommerce", "bank_export", "scan", "portal", "post")

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_YEAR_RE = re.compile(r"^\d{4}$")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def die(msg: str, code: int = 3) -> int:
    sys.stderr.write(f"{msg}\n")
    return code


def slug(text: str) -> str:
    """A path-safe token. Collapses everything that would make two suppliers
    resolve to the same directory on a case-insensitive filesystem."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return s or "unnamed"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_index(store: Path) -> dict:
    idx_path = store / INDEX_NAME
    if not idx_path.exists():
        return {"schema_version": SCHEMA_VERSION, "documents": []}
    try:
        data = json.loads(idx_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(die(f"INDEX_UNREADABLE: {idx_path}: {exc}"))
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        raise SystemExit(die(f"INDEX_MALFORMED: {idx_path} has no documents[] array"))
    data.setdefault("schema_version", SCHEMA_VERSION)
    return data


def save_index(store: Path, index: dict) -> None:
    """Atomic. A half-written index is worse than a missing one: it looks readable."""
    index["schema_version"] = SCHEMA_VERSION
    index["generated_at"] = utc_today()
    index["documents"].sort(key=lambda e: (e.get("period", ""), e.get("stored_path", "")))
    idx_path = store / INDEX_NAME
    tmp = idx_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, idx_path)


def find_by_hash(index: dict, digest: str):
    for entry in index["documents"]:
        if entry.get("sha256") == digest:
            return entry
    return None


def resolve_ref(index: dict, ref: str):
    """Accept a full sha256 or any unambiguous prefix. Ambiguity is an error,
    never a first match — picking one would silently link the wrong document."""
    ref = (ref or "").strip().lower()
    if not ref:
        return None, "empty reference"
    hits = [e for e in index["documents"] if e.get("sha256", "").startswith(ref)]
    if not hits:
        return None, f"no indexed document matches {ref}"
    if len(hits) > 1:
        return None, f"{ref} is ambiguous — matches {len(hits)} documents"
    return hits[0], None


def stored_path_for(doc_type: str, period: str, ext: str, opts: dict) -> str:
    """COMPUTED from the document's own facts. Period-first, so a VAT quarter or a
    year end is one directory listing — which is how the work is actually organised."""
    spec = DOC_TYPES[doc_type]
    year = period[:4]
    root = spec["dir"]
    if doc_type == "statement":
        return f"{root}/{slug(opts['account'])}/{year}/{period}-statement{ext}"
    if doc_type == "purchase_invoice":
        return f"{root}/{year}/{period}/{slug(opts['supplier'])}-{slug(opts['reference'])}{ext}"
    if doc_type == "sales_invoice":
        return f"{root}/{year}/{period}/{slug(opts['reference'])}{ext}"
    if doc_type == "settlement":
        return f"{root}/{slug(opts['provider'])}/{year}/{period}-settlement{ext}"
    if doc_type == "payroll":
        return f"{root}/{year}/{period}-payroll-run{ext}"
    return f"{root}/{year}/{slug(opts['reference'])}{ext}"


def validate_period(doc_type: str, period: str) -> str | None:
    want = DOC_TYPES[doc_type]["period"]
    if want == "month" and not _MONTH_RE.match(period or ""):
        return (f"PERIOD_INVALID: {doc_type} needs --period YYYY-MM (the period the document "
                f"BELONGS to, not the date it arrived); got {period!r}")
    if want == "year" and not _YEAR_RE.match(period or ""):
        return f"PERIOD_INVALID: {doc_type} needs --period YYYY; got {period!r}"
    return None


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

def cmd_add(args) -> int:
    store = Path(args.store).expanduser().resolve()
    src = Path(args.file).expanduser()
    if not src.is_file():
        return die(f"NO_SUCH_FILE: {src}")
    if args.doc_type not in DOC_TYPES:
        return die(f"UNKNOWN_DOC_TYPE: {args.doc_type} (one of: {', '.join(sorted(DOC_TYPES))})")

    err = validate_period(args.doc_type, args.period)
    if err:
        return die(err)

    opts = {"account": args.account, "supplier": args.supplier,
            "provider": args.provider, "reference": args.reference}
    missing = [n for n in DOC_TYPES[args.doc_type]["needs"] if not opts.get(n)]
    if missing:
        return die(f"MISSING_FOR_{args.doc_type.upper()}: --{' --'.join(missing)} "
                   f"required to place the file — it will not be guessed")

    store.mkdir(parents=True, exist_ok=True)
    index = load_index(store)

    # Hash BEFORE storing. This is what makes re-ingestion idempotent.
    digest = sha256_of(src)
    dup = find_by_hash(index, digest)
    if dup:
        print(f"ALREADY INDEXED — identical content, nothing stored.")
        print(f"  sha256      {digest[:12]}…")
        print(f"  stored_path {dup['stored_path']}")
        print(f"  indexed as  {dup.get('original_filename')}  ({dup.get('received_at')})")
        if dup.get("posted_ref"):
            print(f"  posted_ref  {dup['posted_ref']}")
        else:
            print(f"  posted_ref  — OPEN ITEM")
        return 0

    rel = stored_path_for(args.doc_type, args.period, src.suffix.lower(), opts)
    dest = store / rel

    # Never overwrite. Same path + different bytes is a correction or a mistake, and
    # this tool refuses to decide which.
    if dest.exists():
        return die(
            f"REFUSING TO OVERWRITE: {rel}\n"
            f"  A different file already occupies that path (sha256 {sha256_of(dest)[:12]}…).\n"
            f"  If this is a CORRECTION, store it under a distinct --reference and then:\n"
            f"    doc_store.py supersede --old <old-sha> --new <new-sha>\n"
            f"  The original was the basis of a filed return and stays part of the record.", 2)

    if args.dry_run:
        print(f"would store {src.name} -> {rel}  (sha256 {digest[:12]}…)")
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

    entry = {
        "sha256": digest,
        "original_filename": src.name,
        "stored_path": rel,
        "doc_type": args.doc_type,
        "period": args.period,
        "source": args.source,
        "received_at": args.received_at or utc_today(),
        "tax_point": args.tax_point,
        "extracted": args.extracted,
        "posted_ref": None,
        "superseded_by": None,
    }
    index["documents"].append(entry)
    save_index(store, index)

    print(f"stored  {rel}")
    print(f"sha256  {digest}")
    if not args.tax_point:
        print("note    no --tax-point recorded. For VAT the tax point is the SUPPLY, "
              "not the date the document arrived or was paid.")
    print("note    OPEN ITEM until `link --posted-ref` names the entry it became.")
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def cmd_verify(args) -> int:
    store = Path(args.store).expanduser().resolve()
    index = load_index(store)
    docs = index["documents"]
    if not docs:
        print(f"index is empty: {store / INDEX_NAME}")
        print("nothing to verify — an empty index is not a clean bill of health")
        return 0

    ok, changed, missing = [], [], []
    for entry in docs:
        path = store / entry.get("stored_path", "")
        if not path.is_file():
            missing.append(entry)
            continue
        if sha256_of(path) != entry.get("sha256"):
            changed.append(entry)
        else:
            ok.append(entry)

    print(f"[document store] {store}")
    print(f"  indexed   {len(docs)}")
    print(f"  verified  {len(ok)}")
    if changed:
        print(f"  CHANGED   {len(changed)}  — content no longer matches the recorded hash")
        for e in changed:
            print(f"    {e['stored_path']}  (indexed {e['sha256'][:12]}…)")
    if missing:
        print(f"  MISSING   {len(missing)}  — indexed but not on disk")
        for e in missing:
            print(f"    {e['stored_path']}")

    if changed or missing:
        print("\nA document behind a filed figure is not where the index says it is.")
        print("Restore from backup — and note that a backup without index.json is a")
        print("folder of unlabelled PDFs. See references/retention-and-backup.md.")
        return 2

    periods = sorted(e.get("period", "") for e in docs if e.get("period"))
    if periods:
        print(f"  earliest  {periods[0]}   (retain at least six years; this tool never prunes)")
    return 0


# ---------------------------------------------------------------------------
# link / supersede / open-items
# ---------------------------------------------------------------------------

def cmd_link(args) -> int:
    store = Path(args.store).expanduser().resolve()
    index = load_index(store)
    entry, err = resolve_ref(index, args.id)
    if err:
        return die(f"NOT_RESOLVED: {err}")

    if entry.get("posted_ref") and entry["posted_ref"] != args.posted_ref and not args.force:
        return die(
            f"ALREADY LINKED: {entry['stored_path']} -> {entry['posted_ref']}\n"
            f"  Re-linking a document to a different entry usually means it was posted twice.\n"
            f"  Check the ledger first; pass --force if the original link was wrong.", 2)

    entry["posted_ref"] = args.posted_ref
    if args.extracted:
        entry["extracted"] = args.extracted
    save_index(store, index)
    print(f"linked  {entry['stored_path']}")
    print(f"        -> {args.posted_ref}")
    return 0


def cmd_supersede(args) -> int:
    store = Path(args.store).expanduser().resolve()
    index = load_index(store)
    old, err = resolve_ref(index, args.old)
    if err:
        return die(f"NOT_RESOLVED (--old): {err}")
    new, err = resolve_ref(index, args.new)
    if err:
        return die(f"NOT_RESOLVED (--new): {err}")
    if old["sha256"] == new["sha256"]:
        return die("REFUSING: a document cannot supersede itself")
    if old.get("superseded_by"):
        return die(f"ALREADY SUPERSEDED: by {old['superseded_by'][:12]}…", 2)

    old["superseded_by"] = new["sha256"]
    save_index(store, index)
    print(f"superseded  {old['stored_path']}")
    print(f"        by  {new['stored_path']}")
    print("Both remain in the store and in the index. The original was the basis of a")
    print("filed return; it is replaced in the books, not removed from the record.")
    return 0


def cmd_open_items(args) -> int:
    store = Path(args.store).expanduser().resolve()
    index = load_index(store)
    # DERIVED, never read from a flag. There is no way to mark a document closed
    # other than naming the entry it became.
    items = [e for e in index["documents"]
             if not e.get("posted_ref") and not e.get("superseded_by")]
    if args.period:
        items = [e for e in items if str(e.get("period", "")).startswith(args.period)]

    scope = f" in {args.period}" if args.period else ""
    if not items:
        print(f"no open items{scope} — every indexed document names the entry it became")
        return 0

    print(f"{len(items)} OPEN ITEM(S){scope} — indexed, but nothing says what they became:\n")
    for e in sorted(items, key=lambda x: (x.get("period", ""), x.get("stored_path", ""))):
        tp = e.get("tax_point") or "tax point not recorded"
        print(f"  {e.get('period','?'):<8} {e.get('doc_type',''):<17} {e.get('stored_path','')}")
        print(f"           {tp}   sha {e.get('sha256','')[:12]}…")
    print("\nThese belong in the period-end review alongside unreconciled differences.")
    return 0 if args.quiet else 2


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc_store.py",
        description="The document store from financial-document-ingestion §6.")
    p.add_argument("--store", default=".",
                   help="document-store root holding index.json (default: cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="hash, store period-first, index")
    a.add_argument("--file", required=True)
    a.add_argument("--doc-type", required=True, choices=sorted(DOC_TYPES))
    a.add_argument("--period", required=True,
                   help="the period the document BELONGS to (YYYY-MM, or YYYY for a filing)")
    a.add_argument("--source", default=None, choices=SOURCES)
    a.add_argument("--account", help="bank statements")
    a.add_argument("--supplier", help="purchase invoices")
    a.add_argument("--provider", help="settlements")
    a.add_argument("--reference", help="invoice / filing reference")
    a.add_argument("--tax-point", default=None,
                   help="the date driving VAT — the SUPPLY, not arrival or payment")
    a.add_argument("--received-at", default=None)
    a.add_argument("--extracted", default="none",
                   choices=("none", "pending", "validated", "failed"))
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_add)

    v = sub.add_parser("verify", help="re-hash everything indexed")
    v.set_defaults(func=cmd_verify)

    ln = sub.add_parser("link", help="record the entry a document became")
    ln.add_argument("--id", required=True, help="sha256 or an unambiguous prefix")
    ln.add_argument("--posted-ref", required=True)
    ln.add_argument("--extracted", default=None,
                    choices=("none", "pending", "validated", "failed"))
    ln.add_argument("--force", action="store_true")
    ln.set_defaults(func=cmd_link)

    s = sub.add_parser("supersede", help="a correction replaces, never overwrites")
    s.add_argument("--old", required=True)
    s.add_argument("--new", required=True)
    s.set_defaults(func=cmd_supersede)

    o = sub.add_parser("open-items", help="indexed with no posted_ref")
    o.add_argument("--period", default=None, help="YYYY or YYYY-MM prefix")
    o.add_argument("--quiet", action="store_true",
                   help="exit 0 even when open items exist (for interactive use)")
    o.set_defaults(func=cmd_open_items)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
