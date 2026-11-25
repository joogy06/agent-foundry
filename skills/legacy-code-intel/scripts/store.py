#!/usr/bin/env python3
"""store.py — content-addressed library store + SINGLE-WRITER flock'd promote.

The persistence layer for legacy-code-intel. Content-addressed git-object model
(design §4). store.py is the SOLE writer of catalog/latest.json: producers
(parallel agent-teams workers) write only their own disjoint objects/<sha>/ dirs;
the catalog projection is rebuilt and promoted under an exclusive flock with an
atomic os.replace. This is the anti-requirement-#2 fix: the discarded agy build did
naive read-modify-write on the catalog and raced under the agent-teams batch
trigger. The flock+atomic pattern is ported from wiring-reconcile/promote.py and
project-state/reconcile.py.

Store layout (design §4):
    <store>/                                  (0700, NEVER /tmp; default ~/.codelib)
    ├── objects/<sha[:2]>/<sha>/
    │   └── derivations/<pipeline_fingerprint>/index.json   immutable; a prompt/model
    │                                                        change = NEW derivation
    ├── refs/by-path/<urlenc_path>.json       mutable pointer + version history
    ├── catalog/latest.json                   PROMOTED projection (query reads ONLY this)
    ├── catalog/runs/<run_id>/...             pre-promote scratch (reserved)
    └── .promote.lock                         flock target

Dedup ("process once"): a probe for (content_sha256, pipeline_fingerprint) that
hits an existing derivation means the LLM pass can be skipped entirely — store-hit,
zero LLM calls. A prompt/model bump changes the pipeline_fingerprint, so the same
bytes correctly MISS (re-extract) rather than serve a stale cache hit.

Atomic writes via .tmp.<pid> + os.replace + fsync everywhere (HARD-RULE 3).
Pure stdlib + jsonschema (catalog validation). No LLM calls.

CLI usage:
    store.py probe --content-sha256 H --pipeline-fingerprint H [--store PATH]
        exit 0 = HIT (already stored), exit 3 = MISS (needs extraction)
    store.py persist <index_json> [--store PATH]
        write the object derivation + ref, then promote the catalog
    store.py promote [--store PATH]
        rebuild + atomically promote catalog/latest.json from all objects
    store.py path [--store PATH]
        print the resolved store root
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Cross-platform advisory locking (#249). `import fcntl` at module level made
# this module unimportable on Windows -- it died at IMPORT, not at use.
_META_DIR = Path(__file__).resolve().parents[2] / "_meta"
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))
from portable_lock import lock_exclusive, unlock  # noqa: E402


try:
    from jsonschema import Draft7Validator
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False

CATALOG_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "library-catalog.v1.json"

DEFAULT_PRECISION_THRESHOLD = 0.85


# ---------------- Store-root resolution ---------------- #

def resolve_store_root(store: Optional[str] = None) -> Path:
    """Resolve the store root. Precedence: explicit --store > $LCI_STORE > ~/.codelib.

    A relative --store (e.g. '.codelib') is resolved against CWD for project-local
    stores. The root is created mode 0700 (HARD-RULE 8: 0700, never /tmp)."""
    if store:
        root = Path(store)
        if not root.is_absolute():
            root = Path.cwd() / root
    elif os.environ.get("LCI_STORE"):
        root = Path(os.environ["LCI_STORE"])
    else:
        root = Path.home() / ".codelib"
    root = root.resolve()
    _refuse_tmp(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def _refuse_tmp(root: Path) -> None:
    """HARD-RULE 8: the store must never live under /tmp."""
    parts = root.parts
    if "/tmp" in str(root) or (len(parts) > 1 and parts[1] == "tmp"):
        raise ValueError(f"refusing to use a /tmp store root ({root}); HARD-RULE 8 (0700, never /tmp)")


# ---------------- Atomic write helpers ---------------- #

def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


# ---------------- Object addressing ---------------- #

def derivation_dir(root: Path, content_sha256: str, pipeline_fingerprint: str) -> Path:
    return root / "objects" / content_sha256[:2] / content_sha256 / "derivations" / pipeline_fingerprint


def index_path(root: Path, content_sha256: str, pipeline_fingerprint: str) -> Path:
    return derivation_dir(root, content_sha256, pipeline_fingerprint) / "index.json"


def probe(root: Path, content_sha256: str, pipeline_fingerprint: str) -> bool:
    """Return True iff this (content_sha256, pipeline_fingerprint) derivation is
    already stored (dedup HIT). The store-hit means zero LLM calls on re-ingest."""
    return index_path(root, content_sha256, pipeline_fingerprint).is_file()


# ---------------- Promote lock ---------------- #

class _PromoteLock:
    """Exclusive non-blocking flock on <store>/.promote.lock. Raises
    BlockingIOError if held (mirrors wiring-reconcile/promote.py)."""

    def __init__(self, lock_path: Path, blocking: bool = False) -> None:
        self.lock_path = lock_path
        self.blocking = blocking
        self._fh = None

    def __enter__(self) -> "_PromoteLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.lock_path, "a+")
        try:
            lock_exclusive(self._fh, blocking=self.blocking)
        except BlockingIOError:
            self._fh.close()
            self._fh = None
            raise BlockingIOError("promote lock held")
        except OSError:
            self._fh.close()
            self._fh = None
            raise
        return self

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            try:
                unlock(self._fh)
            finally:
                self._fh.close()


# ---------------- Persist (object + ref) ---------------- #

def persist(root: Path, index: dict, promote_after: bool = True, blocking_promote: bool = True) -> dict:
    """Write the immutable object derivation + update the path ref, then (by
    default) promote the catalog under the flock.

    The object write targets a content-addressed dir UNIQUE to this
    (content_sha256, pipeline_fingerprint), so parallel workers writing different
    artifacts never collide (anti-requirement #2). Only the catalog promote
    serializes.

    Returns a summary dict. Idempotent: re-persisting the same derivation
    overwrites it byte-identically (deterministic input => deterministic bytes).
    """
    artifact = index.get("artifact") or {}
    content_sha256 = artifact.get("content_sha256")
    pipeline_fingerprint = artifact.get("pipeline_fingerprint")
    source_path = artifact.get("source_path", "")
    if not content_sha256 or not pipeline_fingerprint:
        raise ValueError("index.artifact must carry content_sha256 + pipeline_fingerprint (anti-requirement #4)")

    # 1. Immutable object derivation (disjoint per artifact+pipeline).
    idx_path = index_path(root, content_sha256, pipeline_fingerprint)
    _atomic_write_json(idx_path, index)
    _fsync_dir(idx_path.parent)

    # 2. Mutable path ref + append version history.
    _update_ref(root, source_path, content_sha256, pipeline_fingerprint)

    promoted = None
    if promote_after:
        promoted = promote(root, blocking=blocking_promote)

    return {
        "content_sha256": content_sha256,
        "pipeline_fingerprint": pipeline_fingerprint,
        "object_path": str(idx_path),
        "promoted_generation": (promoted or {}).get("generation"),
    }


def _ref_path(root: Path, source_path: str) -> Path:
    enc = urllib.parse.quote(source_path, safe="")
    return root / "refs" / "by-path" / f"{enc}.json"


def _update_ref(root: Path, source_path: str, content_sha256: str, pipeline_fingerprint: str) -> None:
    """Update the mutable path pointer and append to its version history. The ref
    points at the CURRENT (latest) derivation; history records prior ones."""
    rp = _ref_path(root, source_path)
    history = []
    if rp.is_file():
        try:
            prev = json.loads(rp.read_text(encoding="utf-8"))
            history = prev.get("history", [])
            cur = prev.get("current")
            # Append the previous current to history if it differs from the new one.
            if cur and (cur.get("content_sha256") != content_sha256 or cur.get("pipeline_fingerprint") != pipeline_fingerprint):
                if cur not in history:
                    history = history + [cur]
        except (json.JSONDecodeError, OSError):
            history = []
    ref = {
        "schema_version": "1.0.0",
        "source_path": source_path,
        "current": {"content_sha256": content_sha256, "pipeline_fingerprint": pipeline_fingerprint},
        "history": history,
    }
    _atomic_write_json(rp, ref)


# ---------------- Promote (rebuild catalog projection) ---------------- #

def _iter_all_indexes(root: Path):
    """Yield every stored index.json. For each artifact, prefer the derivation
    that the path ref currently points at; if no ref, yield all derivations.

    Determinism: we walk refs first (the authoritative 'current' selection), then
    fall back to a sorted directory walk for any orphan objects."""
    objects_dir = root / "objects"
    refs_dir = root / "refs" / "by-path"

    selected: dict = {}  # (sha, fp) -> Path
    # 1. Ref-selected currents.
    if refs_dir.is_dir():
        for rf in sorted(refs_dir.glob("*.json")):
            try:
                ref = json.loads(rf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            cur = ref.get("current") or {}
            sha, fp = cur.get("content_sha256"), cur.get("pipeline_fingerprint")
            if sha and fp:
                p = index_path(root, sha, fp)
                if p.is_file():
                    selected[(sha, fp)] = p
    # 2. Fall back: include any object derivation not already selected.
    if objects_dir.is_dir():
        for idx in sorted(objects_dir.rglob("index.json")):
            try:
                doc = json.loads(idx.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            art = doc.get("artifact") or {}
            key = (art.get("content_sha256"), art.get("pipeline_fingerprint"))
            selected.setdefault(key, idx)

    for key in sorted(selected.keys()):
        try:
            yield json.loads(selected[key].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


def build_catalog(root: Path, generation: int, accuracy: dict, deterministic: bool = True) -> dict:
    """Rebuild the promoted catalog projection from all stored objects.

    Flattens every artifact's symbols/occurrences/relationships into a single
    deduped view (symbols deduped by symbol_id across artifacts — content-addressed
    IDs from the same copybook in two repos merge). Deterministic ordering."""
    artifacts = []
    symbols_by_id: dict = {}
    occ_set: dict = {}
    rel_set: dict = {}
    refs_by_path: dict = {}

    for index in _iter_all_indexes(root):
        art = index.get("artifact") or {}
        fmt = art.get("format", "etl")
        src = art.get("source_path", "")
        artifacts.append({
            "content_sha256": art.get("content_sha256", "0" * 64),
            "pipeline_fingerprint": art.get("pipeline_fingerprint", "0" * 64),
            "format": fmt,
            "source_path": src or "unknown",
            "line_count": int(art.get("line_count", 0)),
        })

        for sym in index.get("symbols", []):
            sid = sym.get("symbol_id")
            if not sid:
                continue
            entry = dict(sym)
            entry["format"] = fmt
            # Keep the first; symbols are content-addressed so this is stable.
            symbols_by_id.setdefault(sid, entry)

        for occ in index.get("occurrences", []):
            r = occ.get("range", {})
            key = (occ.get("symbol_id"), occ.get("role"), r.get("start_line"), r.get("end_line"), src)
            if key in occ_set:
                continue
            occ_set[key] = {
                "symbol_id": occ.get("symbol_id"),
                "role": occ.get("role"),
                "range": {"start_line": r.get("start_line", 1), "end_line": r.get("end_line", 1)},
                "evidence_snippet": occ.get("evidence_snippet", ""),
                "confidence": occ.get("confidence", "speculative"),
                "confidence_reason": occ.get("confidence_reason", ""),
                "source_path": src,
            }

        for rel in index.get("relationships", []):
            key = (rel.get("rel"), rel.get("from_id"), rel.get("to_id"))
            if key in rel_set:
                # Keep the more conservative confidence on a cross-artifact collision.
                rank = {"grounded": 3, "inferred": 2, "speculative": 1}
                if rank.get(rel.get("confidence"), 0) < rank.get(rel_set[key].get("confidence"), 0):
                    rel_set[key]["confidence"] = rel.get("confidence")
                continue
            rel_set[key] = {
                "rel": rel.get("rel"), "from_id": rel.get("from_id"), "to_id": rel.get("to_id"),
                "evidence_line": int(rel.get("evidence_line", 0)), "confidence": rel.get("confidence", "speculative"),
            }

        for path, sids in (index.get("refs", {}).get("by_path", {}) or {}).items():
            bucket = refs_by_path.setdefault(path, set())
            for s in sids:
                bucket.add(s)

    catalog = {
        "schema_version": "1.0.0",
        "generation": generation,
        "promoted_at": "SOURCE_DATE_EPOCH" if deterministic else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts": sorted(artifacts, key=lambda a: (a["content_sha256"], a["pipeline_fingerprint"])),
        "symbols": sorted(symbols_by_id.values(), key=lambda s: (s.get("symbol_id", ""), s.get("kind", ""))),
        "occurrences": sorted(occ_set.values(), key=lambda o: (
            o["range"]["start_line"], o["range"]["end_line"], o["symbol_id"] or "", o["role"] or "", o["source_path"] or "")),
        "relationships": sorted(rel_set.values(), key=lambda r: (r["rel"] or "", r["from_id"] or "", r["to_id"] or "")),
        "refs": {"by_path": {p: sorted(s) for p, s in sorted(refs_by_path.items())}},
        "accuracy": accuracy,
    }
    return catalog


def _read_generation(root: Path) -> int:
    gp = root / "catalog" / "generation"
    if not gp.is_file():
        # derive from existing catalog if present
        cat = root / "catalog" / "latest.json"
        if cat.is_file():
            try:
                return int(json.loads(cat.read_text(encoding="utf-8")).get("generation", 0))
            except (json.JSONDecodeError, OSError, ValueError):
                return 0
        return 0
    try:
        return int(gp.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0


def _write_generation(root: Path, n: int) -> None:
    gp = root / "catalog" / "generation"
    gp.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="generation.tmp.", suffix=f".{os.getpid()}", dir=str(gp.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(int(n)) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, gp)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _load_accuracy(root: Path) -> dict:
    """Preserve the accuracy block across promotes (goldcheck.py writes it via
    set_accuracy). Defaults to all-advisory if absent."""
    cat = root / "catalog" / "latest.json"
    if cat.is_file():
        try:
            prev = json.loads(cat.read_text(encoding="utf-8"))
            acc = prev.get("accuracy")
            if acc and "by_format" in acc and "precision_threshold" in acc:
                return acc
        except (json.JSONDecodeError, OSError):
            pass
    return {"precision_threshold": DEFAULT_PRECISION_THRESHOLD, "by_format": {}}


def promote(root: Path, blocking: bool = True, deterministic: bool = True) -> dict:
    """Rebuild + atomically promote catalog/latest.json under the flock.

    SINGLE WRITER: this is the only function that writes catalog/latest.json
    (CB4: producers never do). The exclusive flock serializes concurrent promotes
    from parallel agent-teams workers; the catalog write is atomic os.replace so a
    reader never sees a partial file.
    """
    lock_path = root / ".promote.lock"
    if not lock_path.exists():
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.touch()

    with _PromoteLock(lock_path, blocking=blocking):
        gen = _read_generation(root) + 1
        accuracy = _load_accuracy(root)
        catalog = build_catalog(root, gen, accuracy, deterministic=deterministic)
        _validate_catalog(catalog)
        cat_path = root / "catalog" / "latest.json"
        _atomic_write_json(cat_path, catalog)
        _write_generation(root, gen)
        _fsync_dir(cat_path.parent)
        return {"generation": gen, "catalog_path": str(cat_path),
                "symbols": len(catalog["symbols"]), "relationships": len(catalog["relationships"])}


def set_accuracy(root: Path, fmt: str, precision, recall, gold_program: str = "",
                 precision_threshold: float = DEFAULT_PRECISION_THRESHOLD, blocking: bool = True) -> dict:
    """Record a format's gold-file accuracy and re-promote so the catalog header
    reflects it. advisory=True when precision is None or < threshold (impact()
    stays speculative). Called by goldcheck.py."""
    lock_path = root / ".promote.lock"
    if not lock_path.exists():
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.touch()
    with _PromoteLock(lock_path, blocking=blocking):
        accuracy = _load_accuracy(root)
        accuracy["precision_threshold"] = precision_threshold
        advisory = precision is None or precision < precision_threshold
        accuracy["by_format"][fmt] = {
            "precision": precision, "recall": recall,
            "gold_program": gold_program, "advisory": advisory,
        }
        gen = _read_generation(root) + 1
        catalog = build_catalog(root, gen, accuracy, deterministic=True)
        _validate_catalog(catalog)
        cat_path = root / "catalog" / "latest.json"
        _atomic_write_json(cat_path, catalog)
        _write_generation(root, gen)
        return {"generation": gen, "format": fmt, "advisory": advisory}


def _validate_catalog(catalog: dict) -> None:
    if not HAVE_JSONSCHEMA:
        return
    with CATALOG_SCHEMA_PATH.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    errors = sorted(Draft7Validator(schema).iter_errors(catalog), key=lambda e: list(e.path))
    if errors:
        msgs = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
        raise ValueError(f"library-catalog.v1 validation failed: {msgs}")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("--content-sha256", required=True)
    p_probe.add_argument("--pipeline-fingerprint", required=True)
    p_probe.add_argument("--store")

    p_persist = sub.add_parser("persist")
    p_persist.add_argument("index_json", type=Path)
    p_persist.add_argument("--store")
    p_persist.add_argument("--no-promote", action="store_true")

    p_promote = sub.add_parser("promote")
    p_promote.add_argument("--store")

    p_path = sub.add_parser("path")
    p_path.add_argument("--store")

    args = parser.parse_args(argv)

    try:
        root = resolve_store_root(args.store)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.cmd == "path":
        print(str(root))
        return 0

    if args.cmd == "probe":
        hit = probe(root, args.content_sha256, args.pipeline_fingerprint)
        print(json.dumps({"hit": hit, "content_sha256": args.content_sha256,
                          "pipeline_fingerprint": args.pipeline_fingerprint}))
        return 0 if hit else 3

    if args.cmd == "persist":
        if not args.index_json.exists():
            print(f"ERROR: index not found: {args.index_json}", file=sys.stderr)
            return 1
        index = json.loads(args.index_json.read_text(encoding="utf-8"))
        try:
            res = persist(root, index, promote_after=not args.no_promote)
        except (ValueError, BlockingIOError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(json.dumps(res))
        return 0

    if args.cmd == "promote":
        try:
            res = promote(root)
        except (ValueError, BlockingIOError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(json.dumps(res))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
