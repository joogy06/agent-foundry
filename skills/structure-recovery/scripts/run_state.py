#!/usr/bin/env python3
"""run_state.py — resumable run-state + job fingerprint for structure-recovery.

The "process once / resume cleanly" layer (design §6). Two responsibilities:

  1. JOB FINGERPRINT — a single sha256 that changes iff *anything* that could
     change the output changes: the project root, the exact selected-file set
     (sorted relpath:content-sha), the run options (incl. the
     --infer-relationships flag), the prompt-template hash, and the
     extractor/schema/normalizer versions + model_id. This OUTER hash is
     LAYERED OVER legacy-code-intel's `pipeline_fingerprint` — it embeds the
     5-field pipeline fingerprint as one of its inputs and adds the run-scoped
     inputs around it. It NEVER widens the legacy-code-intel signature (§9
     note 2): pipeline_fingerprint keeps its fixed 5 fields (schema_version,
     prompt_hash, extractor_version, model_id, normalizer_version) so the
     legacy-code-intel store still dedups per-file derivations the same way;
     the job fingerprint is the run-level key, the pipeline fingerprint is the
     per-file derivation key, and the two compose cleanly.

  2. RUN-STATE CHECKPOINT — `run-state.json`: an aggregate index plus per-file
     state (pending|chunked|analyzing|accumulated|persisted|skipped) and the
     list of completed chunk indices per file (chunks_done[]). The checkpoint
     is a FAST-PATH HINT, not the source of truth: on-disk artifacts are TRUTH.
     `reconcile()` rebuilds chunks_done from the filesystem so a torn / stale /
     partially-written checkpoint self-heals.

Skip ladder (cheapest first; design §6):
    store.probe(content_sha256, pipeline_fingerprint) HIT   -> 0 LLM calls
    summary.json present + complete                          -> file already done
    partial chunks_done                                      -> resume at first
                                                               missing chunk
    nothing                                                  -> from scratch

PARTIAL is a first-class non-failure outcome. A wall-clock cap
(STRUCT_MAX_DURATION_S, default 3600s) is checked BETWEEN files and BETWEEN
chunks; when it trips the run finalizes status:partial and lists
files_pending / files_partial / files_skipped so a later invocation of the SAME
job (identical fingerprint) resumes exactly where it stopped.

Concurrency: run-state writes go under an exclusive non-blocking flock on
<run_dir>/.run-state.lock (the legacy-code-intel _PromoteLock pattern) with an
atomic .tmp.<pid> + os.replace + fsync. Each writer carries a unique attempt-id;
a CAS guard (compare-and-set on a monotonic `revision`) rejects a stale writer
that read an older checkpoint, so two concurrent attempts can't clobber each
other's progress.

Security / hygiene: run dirs are created mode 0700 and NEVER under /tmp
(HARD-RULE: 0700, never /tmp — mirrors legacy-code-intel store.resolve_store_root
and lineage ensure_cache_dir). Pure stdlib. No LLM calls. Deterministic
fingerprints (no timestamps fold into the fingerprint; timestamps live only in
the human-facing checkpoint metadata, never in the hash).

CLI usage (mainly debugging / smoke tests):
    run_state.py fingerprint --project-root P --file F [F ...]
                 --prompt-hash H --model-id M
                 [--infer-relationships] [--option K=V ...]
        -> prints the job fingerprint (sha256 hex)

    run_state.py init --run-dir D --project-root P --file F [F ...]
                 --prompt-hash H --model-id M [--infer-relationships]
        -> create/refresh run-state.json for this job, print the resume plan

    run_state.py reconcile --run-dir D
        -> rebuild chunks_done from on-disk artifacts (filesystem = truth)

    run_state.py status --run-dir D
        -> print the current aggregate status (pending/partial/complete counts)
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------------- #
# Tunables (env-overridable, sibling-parity with chunk_file.py STRUCT_* knobs)
# ------------------------------------------------------------------------- #

STRUCT_MAX_DURATION_S = int(os.environ.get("STRUCT_MAX_DURATION_S", "3600"))

RUN_STATE_FILENAME = "run-state.json"
RUN_STATE_LOCK = ".run-state.lock"

RUN_STATE_SCHEMA = "structure-run-state.v1"

# Per-file lifecycle states. Order matters only for documentation; the set is
# what the validator checks.
FILE_STATES = ("pending", "chunked", "analyzing", "accumulated", "persisted", "skipped")

_FIELD_SEP = b"\x00"

# A NUL cannot appear in any fingerprint component (paths/hex/identifiers), so
# NUL-joining the parts keeps the concatenation injective (same idiom as
# legacy-code-intel pipeline_fingerprint).


# ------------------------------------------------------------------------- #
# Locate + import legacy-code-intel fingerprint.pipeline_fingerprint.
# We WRAP it (never widen it). Resolve from the sibling skill tree relative to
# THIS file so it works in both the repo tree and the ~/.claude shadow tree;
# fall back to the ~/.claude shadow path; finally degrade to a local inline
# re-implementation of the SAME 5-field hash if neither is importable (so the
# job fingerprint is still computable in a bare test sandbox — the bytes are
# identical because the 5-field formula is fixed and pinned).
# ------------------------------------------------------------------------- #

# Pinned versions for the structure-recovery extractor identity. Bumping any of
# these is a deliberate cache-invalidation event for the JOB fingerprint.
EXTRACTOR_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
NORMALIZER_VERSION = "1.0.0"


def _import_pipeline_fingerprint():
    """Return legacy-code-intel's pipeline_fingerprint callable, or None.

    Tried in order:
      1. <this_file>/../../../legacy-code-intel/scripts/fingerprint.py  (repo tree)
      2. ~/.claude/skills/legacy-code-intel/scripts/fingerprint.py      (shadow)
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "legacy-code-intel" / "scripts" / "fingerprint.py",
        Path.home() / ".claude" / "skills" / "legacy-code-intel" / "scripts" / "fingerprint.py",
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                spec = importlib.util.spec_from_file_location(
                    "lci_fingerprint_for_structrecovery", cand
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    fn = getattr(mod, "pipeline_fingerprint", None)
                    if callable(fn):
                        return fn
        except Exception:
            # Never let an import failure of the sibling break fingerprinting;
            # we fall through to the inline equivalent below.
            continue
    return None


_PIPELINE_FP = _import_pipeline_fingerprint()


def _pipeline_fingerprint_inline(
    prompt_hash: str,
    model_id: str,
    schema_version: str = SCHEMA_VERSION,
    extractor_version: str = EXTRACTOR_VERSION,
    normalizer_version: str = NORMALIZER_VERSION,
) -> str:
    """Byte-identical fallback for legacy-code-intel.pipeline_fingerprint.

    SAME fixed 5-field NUL-joined formula. This is NOT a widening — it is the
    identical signature, used only when the sibling module cannot be imported
    (e.g. an isolated test sandbox). The order MUST match legacy-code-intel
    exactly: schema_version, prompt_hash, extractor_version, model_id,
    normalizer_version.
    """
    parts = [
        schema_version.encode("utf-8"),
        prompt_hash.encode("utf-8"),
        extractor_version.encode("utf-8"),
        model_id.encode("utf-8"),
        normalizer_version.encode("utf-8"),
    ]
    return hashlib.sha256(_FIELD_SEP.join(parts)).hexdigest()


def pipeline_fingerprint(
    prompt_hash: str,
    model_id: str,
    schema_version: str = SCHEMA_VERSION,
    extractor_version: str = EXTRACTOR_VERSION,
    normalizer_version: str = NORMALIZER_VERSION,
) -> str:
    """The per-file derivation key — DELEGATES to legacy-code-intel verbatim.

    This is the value the legacy-code-intel store probes against (the per-file
    dedup key). The job fingerprint below WRAPS this value; it does not replace
    or widen it.
    """
    if _PIPELINE_FP is not None:
        return _PIPELINE_FP(
            prompt_hash,
            model_id,
            schema_version=schema_version,
            extractor_version=extractor_version,
            normalizer_version=normalizer_version,
        )
    return _pipeline_fingerprint_inline(
        prompt_hash,
        model_id,
        schema_version=schema_version,
        extractor_version=extractor_version,
        normalizer_version=normalizer_version,
    )


# ------------------------------------------------------------------------- #
# Hashing helpers
# ------------------------------------------------------------------------- #

def content_sha256_of_file(path: Path) -> str:
    """Stream-hash a file's bytes (sha256 hex)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for buf in iter(lambda: f.read(64 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def file_set_snapshot(project_root: Path, files: Iterable[Path]) -> List[Tuple[str, str]]:
    """Return a SORTED list of (relpath, content_sha256) for the selected files.

    relpath is POSIX-normalized relative to project_root when the file is under
    it, else the absolute POSIX path (so out-of-tree includes still pin). The
    sort makes the snapshot order-independent: the SAME set of files in any
    selection order yields the SAME snapshot and therefore the SAME fingerprint.
    """
    pr = Path(project_root).resolve()
    out: List[Tuple[str, str]] = []
    for f in files:
        fp = Path(f).resolve()
        try:
            rel = fp.relative_to(pr).as_posix()
        except ValueError:
            rel = fp.as_posix()
        out.append((rel, content_sha256_of_file(fp)))
    out.sort(key=lambda t: t[0])
    return out


def _normalize_options(options: Optional[Dict[str, object]]) -> str:
    """Canonical, deterministic JSON of the run options (sorted keys).

    Booleans, numbers, strings, and nested dict/list are all supported; the
    canonical form is compact-separators + sort_keys so logically-identical
    option sets hash identically regardless of insertion order.
    """
    if not options:
        return "{}"
    return json.dumps(options, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def job_fingerprint(
    *,
    project_root: Path,
    files: Iterable[Path],
    prompt_hash: str,
    model_id: str,
    infer_relationships: bool = False,
    options: Optional[Dict[str, object]] = None,
    extractor_version: str = EXTRACTOR_VERSION,
    schema_version: str = SCHEMA_VERSION,
    normalizer_version: str = NORMALIZER_VERSION,
) -> str:
    """Compute the run-level JOB fingerprint (sha256 hex).

    The OUTER hash folds, in a FIXED NUL-separated order:

        "structure-recovery-job:v1"           (domain tag — prevents cross-tool collisions)
        project_root (resolved, POSIX)
        file_set_snapshot                      (sorted "relpath\\x1fsha" rows, row-joined by \\x1e)
        infer_relationships flag               ("infer:0" | "infer:1")
        options                                (canonical JSON, sorted keys)
        prompt_hash
        extractor_version
        schema_version
        normalizer_version
        model_id
        pipeline_fingerprint(...)              (the EMBEDDED legacy-code-intel 5-field key)

    Embedding the unmodified pipeline_fingerprint is the WRAP (§9 note 2): the
    legacy-code-intel signature is untouched; the job key simply includes it.

    Determinism: nothing time-varying is folded in. The same inputs -> the same
    fingerprint -> the run resumes. Any input delta (a changed file's bytes, the
    file set, the options, the --infer-relationships flag, a prompt edit, a model
    swap, a version bump) -> a new fingerprint -> no stale cache is served.
    """
    pr = Path(project_root).resolve().as_posix()
    snapshot = file_set_snapshot(Path(project_root), files)
    # Row-encode the snapshot injectively: relpath and sha cannot contain \x1f
    # (unit separator) or \x1e (record separator), so this is unambiguous.
    snap_blob = "\x1e".join(f"{rel}\x1f{sha}" for rel, sha in snapshot)
    infer = "infer:1" if infer_relationships else "infer:0"
    opts = _normalize_options(options)
    embedded_pipe = pipeline_fingerprint(
        prompt_hash,
        model_id,
        schema_version=schema_version,
        extractor_version=extractor_version,
        normalizer_version=normalizer_version,
    )

    parts = [
        b"structure-recovery-job:v1",
        pr.encode("utf-8"),
        snap_blob.encode("utf-8"),
        infer.encode("utf-8"),
        opts.encode("utf-8"),
        prompt_hash.encode("utf-8"),
        extractor_version.encode("utf-8"),
        schema_version.encode("utf-8"),
        normalizer_version.encode("utf-8"),
        model_id.encode("utf-8"),
        embedded_pipe.encode("utf-8"),
    ]
    return hashlib.sha256(_FIELD_SEP.join(parts)).hexdigest()


# ------------------------------------------------------------------------- #
# Filesystem hygiene: 0700 dirs, never /tmp, atomic writes
# ------------------------------------------------------------------------- #

def _refuse_tmp(root: Path) -> None:
    """HARD-RULE: run dirs must never live under /tmp (mirrors store.py)."""
    parts = root.parts
    if "/tmp" in str(root) or (len(parts) > 1 and parts[1] == "tmp"):
        raise ValueError(
            f"refusing to use a /tmp run-dir ({root}); HARD-RULE (0700, never /tmp)"
        )


def ensure_run_dir(run_dir: Path) -> Path:
    """Create the run dir mode 0700 (refusing /tmp). Returns the resolved path."""
    rd = Path(run_dir).resolve()
    _refuse_tmp(rd)
    rd.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(rd, 0o700)
    return rd


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Atomic JSON write: .tmp.<pid> + fsync + os.replace + dir fsync.

    Mirrors lineage chunk_file.atomic_write_json / store._atomic_write_json.
    Keys sorted for byte-stable output (idempotent re-write).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(path.parent)
    )
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
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


# ------------------------------------------------------------------------- #
# Exclusive non-blocking flock (legacy-code-intel _PromoteLock pattern)
# ------------------------------------------------------------------------- #

class _RunStateLock:
    """Exclusive non-blocking flock on <run_dir>/.run-state.lock.

    Raises BlockingIOError if the lock is already held (so a concurrent writer
    backs off rather than racing). Mirrors legacy-code-intel store._PromoteLock.
    """

    def __init__(self, lock_path: Path, blocking: bool = False) -> None:
        self.lock_path = Path(lock_path)
        self.blocking = blocking
        self._fh = None

    def __enter__(self) -> "_RunStateLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.lock_path, "a+")
        flags = fcntl.LOCK_EX if self.blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(self._fh.fileno(), flags)
        except OSError as e:
            self._fh.close()
            self._fh = None
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise BlockingIOError("run-state lock held") from e
            raise
        return self

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


# ------------------------------------------------------------------------- #
# Time helpers
# ------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _monotonic() -> float:
    return time.monotonic()


# ------------------------------------------------------------------------- #
# Run-state model
# ------------------------------------------------------------------------- #

def _empty_file_record(relpath: str, content_sha256: str) -> dict:
    return {
        "relpath": relpath,
        "content_sha256": content_sha256,
        "state": "pending",
        "chunks_total": None,      # filled once chunked
        "chunks_done": [],         # sorted unique chunk indices completed
        "store_hit": False,        # store.probe HIT -> 0 LLM calls
        "summary_complete": False, # summary.json present + complete
        "updated_at": None,
    }


def new_run_state(
    *,
    job_fingerprint_hex: str,
    project_root: Path,
    snapshot: Sequence[Tuple[str, str]],
    prompt_hash: str,
    model_id: str,
    infer_relationships: bool,
    options: Optional[Dict[str, object]] = None,
) -> dict:
    """Construct a fresh run-state document (pre-write).

    `revision` is the CAS counter; `attempt_id` rotates each writer. The
    `resume_token` is a stable per-run handle a caller can echo back to prove it
    is continuing the SAME run.
    """
    files = [_empty_file_record(rel, sha) for rel, sha in snapshot]
    return {
        "schema": RUN_STATE_SCHEMA,
        "job_fingerprint": job_fingerprint_hex,
        "project_root": Path(project_root).resolve().as_posix(),
        "prompt_hash": prompt_hash,
        "model_id": model_id,
        "infer_relationships": bool(infer_relationships),
        "options": options or {},
        "resume_token": uuid.uuid4().hex,
        "attempt_id": uuid.uuid4().hex,
        "revision": 0,
        "status": "pending",         # pending | partial | complete
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "max_duration_s": STRUCT_MAX_DURATION_S,
        "files": files,
        # Aggregate buckets (recomputed by _recompute_aggregate):
        "files_pending": [f["relpath"] for f in files],
        "files_partial": [],
        "files_persisted": [],
        "files_skipped": [],
    }


def read_run_state(run_dir: Path) -> Optional[dict]:
    """Read run-state.json if present and parseable; else None (torn/absent).

    A torn / unparseable checkpoint returns None so callers fall back to
    reconcile-from-filesystem rather than trusting a corrupt hint.
    """
    p = Path(run_dir) / RUN_STATE_FILENAME
    if not p.is_file():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("schema") != RUN_STATE_SCHEMA:
            return None
        return data
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _recompute_aggregate(state: dict) -> None:
    """Recompute the aggregate buckets + top-level status from per-file states.

    pending : never started (state == pending, no chunks done, not skipped)
    partial : some chunks done but not persisted/skipped
    persisted: state == persisted (or store_hit / summary_complete short-circuit)
    skipped : state == skipped
    Top-level status: complete iff every file is persisted or skipped; else
    partial iff any progress exists; else pending.
    """
    pending, partial, persisted, skipped = [], [], [], []
    for f in state.get("files", []):
        st = f.get("state")
        if st == "persisted":
            persisted.append(f["relpath"])
        elif st == "skipped":
            skipped.append(f["relpath"])
        elif f.get("chunks_done"):
            partial.append(f["relpath"])
        else:
            pending.append(f["relpath"])
    state["files_pending"] = pending
    state["files_partial"] = partial
    state["files_persisted"] = persisted
    state["files_skipped"] = skipped

    total = len(state.get("files", []))
    done = len(persisted) + len(skipped)
    if total > 0 and done == total:
        state["status"] = "complete"
    elif partial or persisted or skipped:
        state["status"] = "partial"
    else:
        state["status"] = "pending"


def write_run_state(run_dir: Path, state: dict, *, expected_revision: Optional[int] = None) -> dict:
    """Atomically persist run-state under the flock with a CAS guard.

    If `expected_revision` is given, the on-disk revision MUST equal it (compare-
    and-set); otherwise a StaleRevisionError is raised so a writer that read an
    older checkpoint cannot clobber a newer one. On success the in-memory
    `revision` is bumped, `attempt_id` rotated, aggregates recomputed, and the
    document written atomically. Returns the persisted document.
    """
    rd = ensure_run_dir(run_dir)
    lock_path = rd / RUN_STATE_LOCK
    with _RunStateLock(lock_path, blocking=False):
        if expected_revision is not None:
            on_disk = read_run_state(rd)
            current_rev = on_disk.get("revision") if on_disk else None
            # If there is no parseable on-disk state, treat as revision 0 baseline
            # (first write / self-heal after a torn checkpoint).
            current_rev = current_rev if current_rev is not None else 0
            if current_rev != expected_revision:
                raise StaleRevisionError(
                    f"CAS failed: on-disk revision {current_rev} != expected {expected_revision}"
                )
        state["revision"] = int(state.get("revision", 0)) + 1
        state["attempt_id"] = uuid.uuid4().hex
        state["updated_at"] = _now_iso()
        _recompute_aggregate(state)
        _atomic_write_json(rd / RUN_STATE_FILENAME, state)
    return state


class StaleRevisionError(RuntimeError):
    """Raised when a CAS write loses to a concurrent writer (stale revision)."""


# ------------------------------------------------------------------------- #
# Self-healing reconcile: on-disk artifacts are TRUTH
# ------------------------------------------------------------------------- #

# Per-file chunk artifacts are named chunk_NNNN.jsonl (4+ digit zero-padded
# index), mirroring the lineage chunk naming. A per-file summary.json marks the
# file accumulated/persisted. These live under <run_dir>/files/<safe_relpath>/.
_CHUNK_RE = re.compile(r"^chunk_(\d+)\.jsonl$")
_SUMMARY_NAME = "summary.json"


def _safe_relpath_dir(relpath: str) -> str:
    """Map a relpath to a filesystem-safe single directory component.

    URL-quote-ish: replace path separators and unsafe chars so each input file
    gets its own artifact subdir without collisions. Deterministic.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", relpath)


def file_artifact_dir(run_dir: Path, relpath: str) -> Path:
    return Path(run_dir) / "files" / _safe_relpath_dir(relpath)


def _scan_chunks_done(artifact_dir: Path) -> List[int]:
    """Return the SORTED unique chunk indices present on disk for a file."""
    if not artifact_dir.is_dir():
        return []
    found: List[int] = []
    for entry in artifact_dir.iterdir():
        if not entry.is_file():
            continue
        m = _CHUNK_RE.match(entry.name)
        if m:
            found.append(int(m.group(1)))
    return sorted(set(found))


def _summary_complete(artifact_dir: Path) -> bool:
    """A summary.json is 'complete' iff it parses and is flagged complete.

    The summary writer (WP-6 accumulate_structure) sets {"complete": true} when
    the file's findings are fully accumulated. A torn/partial summary -> False.
    """
    sp = artifact_dir / _SUMMARY_NAME
    if not sp.is_file():
        return False
    try:
        with sp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(isinstance(data, dict) and data.get("complete") is True)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False


def reconcile(run_dir: Path, state: Optional[dict] = None) -> dict:
    """Rebuild chunks_done + summary/persisted flags from on-disk artifacts.

    THE SELF-HEALING CORE: the filesystem is truth; run-state.json is only a
    hint. This walks each tracked file's artifact dir, rebuilds chunks_done from
    the chunk_NNNN.jsonl files actually present, and derives the per-file state:

        summary.json complete           -> state = persisted, summary_complete
        some chunks present, no summary  -> state = analyzing (resume), partial
        no chunks, not previously skipped-> state = pending

    A previously-recorded store_hit (0-LLM dedup) or an explicit `skipped` state
    is preserved (those are NOT contradicted by the absence of chunk files). The
    rebuilt state is persisted atomically under the flock (revision bumped). If
    `state` is None it is read from disk; if THAT is torn/absent, the function
    still reconciles from the artifact tree against the file roster it can
    recover, returning a healed document.

    Survives a deliberately-torn run-state.json: read_run_state returns None for
    a corrupt file, and we rebuild from the artifact directories that exist.
    """
    rd = ensure_run_dir(run_dir)
    if state is None:
        state = read_run_state(rd)

    if state is None:
        # Torn / absent checkpoint AND no in-memory state: reconstruct a minimal
        # roster from whatever artifact dirs exist. We cannot recover the job
        # fingerprint from artifacts alone, so we leave it unknown but rebuild
        # the per-file progress so a caller that re-derives the fingerprint can
        # re-attach. This is the last-resort heal.
        state = {
            "schema": RUN_STATE_SCHEMA,
            "job_fingerprint": None,
            "project_root": None,
            "prompt_hash": None,
            "model_id": None,
            "infer_relationships": False,
            "options": {},
            "resume_token": uuid.uuid4().hex,
            "attempt_id": uuid.uuid4().hex,
            "revision": 0,
            "status": "pending",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "max_duration_s": STRUCT_MAX_DURATION_S,
            "files": [],
            "files_pending": [],
            "files_partial": [],
            "files_persisted": [],
            "files_skipped": [],
        }
        files_root = rd / "files"
        if files_root.is_dir():
            for d in sorted(files_root.iterdir()):
                if d.is_dir():
                    rec = _empty_file_record(d.name, "")
                    state["files"].append(rec)

    # Rebuild each tracked file from disk.
    for rec in state.get("files", []):
        relpath = rec.get("relpath", "")
        adir = file_artifact_dir(rd, relpath)
        on_disk_chunks = _scan_chunks_done(adir)
        rec["chunks_done"] = on_disk_chunks
        summary_done = _summary_complete(adir)
        rec["summary_complete"] = summary_done

        if summary_done:
            rec["state"] = "persisted"
        elif rec.get("state") == "skipped":
            # Preserve an explicit skip (e.g. excluded / unreadable file).
            pass
        elif rec.get("store_hit"):
            # Store-hit dedup: the file is already in the content-addressed store;
            # 0 LLM calls needed. Treat as persisted for resume purposes.
            rec["state"] = "persisted"
        elif on_disk_chunks:
            rec["state"] = "analyzing"
        else:
            rec["state"] = "pending"
        rec["updated_at"] = _now_iso()

    # Persist the healed state atomically (no CAS guard here: reconcile is the
    # authority that REPLACES a torn hint; it takes the lock and overwrites).
    rd_lock = rd / RUN_STATE_LOCK
    with _RunStateLock(rd_lock, blocking=False):
        state["revision"] = int(state.get("revision", 0)) + 1
        state["attempt_id"] = uuid.uuid4().hex
        state["updated_at"] = _now_iso()
        _recompute_aggregate(state)
        _atomic_write_json(rd / RUN_STATE_FILENAME, state)
    return state


def first_missing_chunk(rec: dict) -> int:
    """Return the first chunk index NOT yet done (the resume point).

    chunks_done is a sorted unique list; the resume point is the smallest index
    in [0, chunks_total) not present. If chunks_total is unknown, it is the
    smallest gap or len(chunks_done). This is what a resuming run analyzes next.
    """
    done = set(rec.get("chunks_done", []))
    total = rec.get("chunks_total")
    upper = total if isinstance(total, int) and total >= 0 else (max(done) + 2 if done else 0)
    i = 0
    while i < upper:
        if i not in done:
            return i
        i += 1
    return upper


# ------------------------------------------------------------------------- #
# Skip ladder + resume planning
# ------------------------------------------------------------------------- #

def plan_file(
    rec: dict,
    *,
    store_root: Optional[Path] = None,
    pipeline_fp: Optional[str] = None,
    probe_fn=None,
) -> dict:
    """Decide the cheapest action for one file (the skip ladder).

    Ladder (cheapest first):
      1. store.probe HIT (content_sha256, pipeline_fingerprint) -> 'store_hit'
         (0 LLM calls).
      2. summary.json complete                                  -> 'already_done'.
      3. partial chunks_done                                    -> 'resume' at
         first_missing_chunk.
      4. nothing                                                -> 'from_scratch'.

    `probe_fn(store_root, content_sha256, pipeline_fp) -> bool` is injectable
    (defaults to legacy-code-intel store.probe when store_root + pipeline_fp are
    given and the module is importable). Returns an action dict; does not mutate
    `rec` (the caller records the decision via update helpers).
    """
    csha = rec.get("content_sha256", "")
    # 1. store-hit dedup
    if store_root is not None and pipeline_fp:
        fn = probe_fn or _default_probe_fn()
        try:
            if fn is not None and fn(Path(store_root), csha, pipeline_fp):
                return {"action": "store_hit", "resume_chunk": None}
        except Exception:
            # Probe must never be fatal; fall through to the disk ladder.
            pass
    # 2. summary complete
    if rec.get("summary_complete") or rec.get("state") == "persisted":
        return {"action": "already_done", "resume_chunk": None}
    # 3. partial -> resume
    if rec.get("chunks_done"):
        return {"action": "resume", "resume_chunk": first_missing_chunk(rec)}
    # 4. from scratch
    return {"action": "from_scratch", "resume_chunk": 0}


def _default_probe_fn():
    """Import legacy-code-intel store.probe lazily; None if unavailable."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "legacy-code-intel" / "scripts" / "store.py",
        Path.home() / ".claude" / "skills" / "legacy-code-intel" / "scripts" / "store.py",
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                spec = importlib.util.spec_from_file_location(
                    "lci_store_for_structrecovery", cand
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    fn = getattr(mod, "probe", None)
                    if callable(fn):
                        return fn
        except Exception:
            continue
    return None


# ------------------------------------------------------------------------- #
# Wall-clock cap (PARTIAL is not failure)
# ------------------------------------------------------------------------- #

class WallClock:
    """A monotonic budget checked BETWEEN files and BETWEEN chunks.

    expired() returns True once `max_duration_s` of monotonic time has elapsed
    since start(). The caller checks expired() at file/chunk boundaries and, when
    it trips, calls finalize_partial() so the run ends status:partial with the
    pending/partial/skipped buckets populated (resumable on the next same-job
    invocation). Using monotonic time avoids wall-clock jumps affecting the cap.
    """

    def __init__(self, max_duration_s: int = STRUCT_MAX_DURATION_S, *, clock=None) -> None:
        self.max_duration_s = max_duration_s
        self._clock = clock or _monotonic
        self._start: Optional[float] = None

    def start(self) -> "WallClock":
        self._start = self._clock()
        return self

    def elapsed(self) -> float:
        if self._start is None:
            return 0.0
        return self._clock() - self._start

    def expired(self) -> bool:
        if self.max_duration_s <= 0:
            return False
        return self.elapsed() >= self.max_duration_s


def finalize_partial(run_dir: Path, state: dict, *, reason: str = "wall_clock_cap") -> dict:
    """Finalize the run as PARTIAL (a first-class non-failure outcome).

    Recomputes aggregates, stamps status='partial' (unless already complete),
    records the partial reason, and persists atomically under the flock. The
    populated files_pending / files_partial / files_skipped buckets are the
    resume manifest for the next same-job invocation.
    """
    rd = ensure_run_dir(run_dir)
    with _RunStateLock(rd / RUN_STATE_LOCK, blocking=False):
        _recompute_aggregate(state)
        if state.get("status") != "complete":
            state["status"] = "partial"
        state["partial_reason"] = reason
        state["finalized_at"] = _now_iso()
        state["revision"] = int(state.get("revision", 0)) + 1
        state["attempt_id"] = uuid.uuid4().hex
        state["updated_at"] = _now_iso()
        _atomic_write_json(rd / RUN_STATE_FILENAME, state)
    return state


# ------------------------------------------------------------------------- #
# Per-file mutation helpers (record progress; callers persist via write_run_state)
# ------------------------------------------------------------------------- #

def get_file_record(state: dict, relpath: str) -> Optional[dict]:
    for rec in state.get("files", []):
        if rec.get("relpath") == relpath:
            return rec
    return None


def mark_chunked(rec: dict, chunks_total: int) -> None:
    rec["chunks_total"] = int(chunks_total)
    if rec.get("state") in (None, "pending"):
        rec["state"] = "chunked"
    rec["updated_at"] = _now_iso()


def mark_chunk_done(rec: dict, chunk_index: int) -> None:
    done = set(rec.get("chunks_done", []))
    done.add(int(chunk_index))
    rec["chunks_done"] = sorted(done)
    rec["state"] = "analyzing"
    rec["updated_at"] = _now_iso()


def mark_store_hit(rec: dict) -> None:
    rec["store_hit"] = True
    rec["state"] = "persisted"
    rec["updated_at"] = _now_iso()


def mark_persisted(rec: dict) -> None:
    rec["summary_complete"] = True
    rec["state"] = "persisted"
    rec["updated_at"] = _now_iso()


def mark_skipped(rec: dict, reason: str = "") -> None:
    rec["state"] = "skipped"
    rec["skip_reason"] = reason
    rec["updated_at"] = _now_iso()


# ------------------------------------------------------------------------- #
# CLI
# ------------------------------------------------------------------------- #

def _parse_options(pairs: Optional[Sequence[str]]) -> Dict[str, object]:
    """Parse --option K=V pairs into a dict. Values are kept as strings (the
    fingerprint canonicalizes them); JSON-looking values are parsed best-effort.
    """
    out: Dict[str, object] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--option must be K=V, got: {pair!r}")
        k, v = pair.split("=", 1)
        try:
            out[k] = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            out[k] = v
    return out


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fp = sub.add_parser("fingerprint", help="compute the job fingerprint")
    p_fp.add_argument("--project-root", type=Path, required=True)
    p_fp.add_argument("--file", type=Path, nargs="+", required=True, dest="files")
    p_fp.add_argument("--prompt-hash", required=True)
    p_fp.add_argument("--model-id", required=True)
    p_fp.add_argument("--infer-relationships", action="store_true")
    p_fp.add_argument("--option", action="append", dest="options", default=[])

    p_init = sub.add_parser("init", help="create/refresh run-state.json")
    p_init.add_argument("--run-dir", type=Path, required=True)
    p_init.add_argument("--project-root", type=Path, required=True)
    p_init.add_argument("--file", type=Path, nargs="+", required=True, dest="files")
    p_init.add_argument("--prompt-hash", required=True)
    p_init.add_argument("--model-id", required=True)
    p_init.add_argument("--infer-relationships", action="store_true")
    p_init.add_argument("--option", action="append", dest="options", default=[])

    p_rec = sub.add_parser("reconcile", help="rebuild chunks_done from disk")
    p_rec.add_argument("--run-dir", type=Path, required=True)

    p_st = sub.add_parser("status", help="print aggregate status")
    p_st.add_argument("--run-dir", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.cmd == "fingerprint":
        for f in args.files:
            if not f.exists():
                print(f"ERROR: file not found: {f}", file=sys.stderr)
                return 1
        opts = _parse_options(args.options)
        fp = job_fingerprint(
            project_root=args.project_root,
            files=args.files,
            prompt_hash=args.prompt_hash,
            model_id=args.model_id,
            infer_relationships=args.infer_relationships,
            options=opts,
        )
        print(fp)
        return 0

    if args.cmd == "init":
        for f in args.files:
            if not f.exists():
                print(f"ERROR: file not found: {f}", file=sys.stderr)
                return 1
        opts = _parse_options(args.options)
        snapshot = file_set_snapshot(args.project_root, args.files)
        fp = job_fingerprint(
            project_root=args.project_root,
            files=args.files,
            prompt_hash=args.prompt_hash,
            model_id=args.model_id,
            infer_relationships=args.infer_relationships,
            options=opts,
        )
        rd = ensure_run_dir(args.run_dir)
        existing = read_run_state(rd)
        if existing is not None and existing.get("job_fingerprint") == fp:
            # Same job -> reconcile from disk and resume.
            state = reconcile(rd, existing)
            print(json.dumps({
                "job_fingerprint": fp,
                "resumed": True,
                "status": state["status"],
                "files_pending": state["files_pending"],
                "files_partial": state["files_partial"],
                "files_persisted": state["files_persisted"],
                "files_skipped": state["files_skipped"],
            }, indent=2))
            return 0
        # Different (or no) prior job -> fresh state (input change invalidated it).
        state = new_run_state(
            job_fingerprint_hex=fp,
            project_root=args.project_root,
            snapshot=snapshot,
            prompt_hash=args.prompt_hash,
            model_id=args.model_id,
            infer_relationships=args.infer_relationships,
            options=opts,
        )
        write_run_state(rd, state)
        print(json.dumps({
            "job_fingerprint": fp,
            "resumed": False,
            "status": state["status"],
            "files_pending": state["files_pending"],
            "resume_token": state["resume_token"],
        }, indent=2))
        return 0

    if args.cmd == "reconcile":
        state = reconcile(args.run_dir)
        print(json.dumps({
            "status": state["status"],
            "files_pending": state["files_pending"],
            "files_partial": state["files_partial"],
            "files_persisted": state["files_persisted"],
            "files_skipped": state["files_skipped"],
        }, indent=2))
        return 0

    if args.cmd == "status":
        state = read_run_state(args.run_dir)
        if state is None:
            print("ERROR: no readable run-state.json (try reconcile)", file=sys.stderr)
            return 1
        print(json.dumps({
            "status": state.get("status"),
            "revision": state.get("revision"),
            "files_pending": state.get("files_pending"),
            "files_partial": state.get("files_partial"),
            "files_persisted": state.get("files_persisted"),
            "files_skipped": state.get("files_skipped"),
        }, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
