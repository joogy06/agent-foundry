#!/usr/bin/env python3
"""
trusted_runner.py — Bob's trusted test execution runner.

Implements run_trusted_test_suite per spec section 11.2. The CB3 fix lives here:
skills GENERATE test files, bob's trusted runner EXECUTES them in an isolated
subprocess with sanitized environment, parses the structured JSON report, and
produces a sanitized audit bundle tagged `produced_by: bob-trusted-runner`.

The metacognitive audit (audit_spawn.py) consumes ONLY bob-produced bundles —
never raw skill output. This closes the prompt-injection-via-stdout hole.

Public API:
    run_trusted_test_suite(component_id, test_paths, runner='pytest') -> dict
    canonical_bundle_bytes(bundle) -> bytes        (Phase 1, tester-split design §5.7)
    bundle_hash_hex(bundle) -> str                 (Phase 1, tester-split design §5.7)
    atomic_write_bundle(bundle, dest_dir) -> Path  (Phase 1, tester-split design §5.7)
    atomic_write_bytes(path, data) -> None         (Phase 1, tester-split design §5.7)

CLI:
    python -m trusted_runner <component_id> <test_path> [<test_path> ...] [--runner pytest|jest]
    Output: bundle JSON to stdout. Exit 0 if all tests pass, 2 otherwise.

Provenance: spec section 11.2. Critical invariants enforced: CB3.
Phase 1 additions: tester-split design §5.7 (atomic write semantics +
content-addressed bundle persistence). These are PURE additions; no existing
function signature changes (rollback per design §8 = remove the new helpers).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS = 300
SANITIZED_ENV_KEYS = (
    "PATH", "HOME", "LANG", "LC_ALL", "USER", "SHELL", "TMPDIR", "TERM",
    "PYTHONPATH", "VIRTUAL_ENV", "NODE_PATH", "PYTEST_CURRENT_TEST",
)

# S048 / #116 R-B1 — the env-adoption inventory the tier decision is stamped
# from. The bundle records the inventory_tier + inventory_hash so a sub-tier
# host's sanctioned tier-skip is reproducible from the hash (and R6 reads the
# stamp from the bundle, staying bundle-only at transition time).
DEFAULT_INVENTORY_PATH = Path.home() / ".claude" / "state" / "inventory.json"


# ---------------------------------------------------------------------------
# Fail-open claude_observe loader (for bundle_write rollback emission)
# ---------------------------------------------------------------------------
#
# S028 Phase-5b spawn 7 fix: bundle_write must emit a `gate_false_block`
# observation BEFORE raising BundleWriteError, so alf has a side-channel
# signal in addition to the exception fields. Mirrors the three-tier
# fallback in claims.py / gates.py so trusted_runner.py runs correctly
# in minimal environments.
#
# IMPORTANT: this must NEVER let an observation backend failure block the
# rollback path; the BundleWriteError raise is authoritative.

def _load_claude_observe_for_runner():  # pragma: no cover - tested via spy
    """Fail-open loader that returns a no-op stub if process-observation
    is unavailable. The wrapping `_safe_observe_rollback` adds defense in
    depth so observation failure cannot block the BundleWriteError raise.
    """
    try:
        from process_observation.scripts.write import claude_observe as _co  # type: ignore
        return _co
    except ImportError:
        pass
    try:
        _scripts_dir = (
            Path(__file__).resolve().parent.parent
            / "process-observation" / "scripts"
        )
        if _scripts_dir.is_dir():
            _scripts_str = str(_scripts_dir)
            if _scripts_str not in sys.path:
                sys.path.insert(0, _scripts_str)
            from write import claude_observe as _co  # type: ignore
            return _co
    except Exception:
        pass
    return lambda *args, **kwargs: None


claude_observe = _load_claude_observe_for_runner()


def _safe_observe_rollback(
    *,
    fingerprint: str,
    target_path: str,
    txn_id: str,
    failed_path: Optional[str],
    cause: Optional[BaseException],
) -> None:
    """Emit a `gate_false_block` observation for a bundle_write rollback.

    Per S028 Phase-5b spawn 7 (Codex disagreement SC[2] gate_false_block
    emission gap): rollback is a structural failure (the atomic-commit
    contract just refused to make a multi-file change), so alf needs a
    side-channel signal in addition to the BundleWriteError fields.

    Best-effort: every failure mode (import miss, write miss, observation
    backend down) is swallowed. The BundleWriteError raise that follows
    this call is authoritative — observation is diagnostic only.
    """
    errno = None
    if cause is not None and hasattr(cause, "errno"):
        try:
            errno = int(getattr(cause, "errno"))
        except (TypeError, ValueError):
            errno = None
    detail = (
        f"bundle_write txn {txn_id} rolled back at {target_path}"
        + (f" (errno={errno})" if errno is not None else "")
    )
    try:
        claude_observe(
            "gate_false_block",
            "trusted-runner-keystone",
            detail,
            fingerprint=fingerprint,
            subject_type="gate",
            severity="blocking",
            observed_by="trusted_runner.py:bundle_write",
            related=[f"file://{failed_path}"] if failed_path else [],
        )
    except BaseException as e:  # noqa: BLE001 — defense-in-depth
        sys.stderr.write(
            f"TRUSTED_RUNNER_OBSERVE_FAIL: {type(e).__name__}: {e}\n"
        )
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitized_env() -> Dict[str, str]:
    """Return a minimal env preserving only the keys needed for test runners."""
    return {k: os.environ[k] for k in SANITIZED_ENV_KEYS if k in os.environ}


def runner_info(runner: str) -> Dict[str, str]:
    """Capture the runner version for audit bundle provenance."""
    info = {"runner": runner}
    try:
        if runner == "pytest":
            result = subprocess.run(
                ["pytest", "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            info["version"] = (result.stdout or result.stderr).strip().split("\n")[0]
        elif runner == "jest":
            result = subprocess.run(
                ["jest", "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            info["version"] = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info["version"] = "unknown"
    return info


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# S048 / #116 R-B1 — tier-decision stamping (the bundle carries the signal;
# R6 stays bundle-only)
# ---------------------------------------------------------------------------
#
# A tier-gated component legitimately produces an all-skipped/empty suite below
# its required_tier ("without penalty") and VERIFIES today. The naive
# GREEN-needs->=1-passed rule would false-block it on sub-tier hosts with a
# non-converging rerun loop. Fix: the trusted runner STAMPS the tier decision
# into the bundle so the deterministic arm (deterministic_arm.classify_bundle_
# evidence) can grant GREEN-by-sanctioned-skip — reading ONLY the hash-addressed
# bundle (no new test-plan dependency at transition time; the sanction is
# hash-bound into the evidence).
#
# Stamp shape:
#   bundle["tier_decision"] = {"inventory_tier": <int>, "inventory_hash": <hex>}
#   per-test: result["tests"][i]["required_tier"]       (echoed from bob's map)
#             result["tests"][i]["sanctioned_tier_skip"] = True
#                 iff the test was skipped AND required_tier > inventory_tier
#
# `required_tiers` is a {nodeid: required_tier} map bob derives from the FROZEN
# test plan (test_plan_schema.requirements[].required_tier) and passes in. The
# runner does not parse the plan itself — it only applies the map to the test
# outcomes it actually observed. Reproducible from inventory_hash + the map.


def inventory_tier_and_hash(
    inventory_path: Optional[Path] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """Return (tier, sha256-hex) of the env-adoption inventory.

    Reads the inventory.json bytes, hashes them (so the tier decision is
    reproducible), and extracts the integer `tier`. Returns (None, None) on a
    missing/unreadable/malformed inventory — the caller stamps a None tier and
    NO sanction is granted (fail-safe: an unknowable tier never sanctions a
    skip, so it falls through to INDETERMINATE, never a false GREEN).
    """
    path = Path(inventory_path) if inventory_path is not None else DEFAULT_INVENTORY_PATH
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None
    inv_hash = hashlib.sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, inv_hash
    tier = doc.get("tier") if isinstance(doc, dict) else None
    if not isinstance(tier, int):
        return None, inv_hash
    return tier, inv_hash


def stamp_tier_decision(
    bundle: Dict[str, Any],
    required_tiers: Optional[Dict[str, int]] = None,
    *,
    inventory_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Stamp the bundle-level `tier_decision` + per-test `sanctioned_tier_skip`.

    MUST be called BEFORE bundle_hash is computed so the sanction is hash-bound
    into the evidence. Mutates and returns `bundle`.

    A per-test record gets `sanctioned_tier_skip: True` iff:
      - its outcome is "skipped" (it did not run), AND
      - its required_tier (from `required_tiers[nodeid]`) > inventory_tier.
    "Should-have-run-but-didn't" (a test whose tier IS met but is skipped, or a
    skip with no required_tier mapping) gets NO sanction stamp -> the
    deterministic arm classifies it INDETERMINATE/veto (R-B1).
    """
    inv_tier, inv_hash = inventory_tier_and_hash(inventory_path)
    bundle["tier_decision"] = {
        "inventory_tier": inv_tier,
        "inventory_hash": inv_hash,
    }
    req = required_tiers or {}
    for res in bundle.get("results", []):
        if not isinstance(res, dict):
            continue
        for t in res.get("tests", []) or []:
            if not isinstance(t, dict):
                continue
            nodeid = t.get("nodeid")
            rt = req.get(nodeid) if isinstance(nodeid, str) else None
            if rt is not None:
                t["required_tier"] = rt
            # Sanction ONLY a genuine skip whose required tier exceeds the host.
            if (
                t.get("outcome") == "skipped"
                and isinstance(rt, int)
                and isinstance(inv_tier, int)
                and rt > inv_tier
            ):
                t["sanctioned_tier_skip"] = True
    return bundle


# ---------------------------------------------------------------------------
# Phase 1 additions — content-addressed bundles + atomic write (§5.7)
# ---------------------------------------------------------------------------
#
# Why these helpers exist (tester-split design §5.7):
#
#   The verification arbiter (Phase 2) is invoked against an evidence bundle
#   identified by its SHA-256 content hash. For the verdict tuple match
#   (design §5.3) to be meaningful, two properties must hold:
#
#     1. Hash stability — recomputing bundle_hash from the on-disk bytes
#        MUST yield the same value bob computed before persisting. This
#        requires the field that holds the hash to be EXCLUDED from the
#        canonical bytes, and the canonicalization to be deterministic
#        (sorted keys, no insignificant whitespace, UTF-8, NFC-stable).
#
#     2. No torn writes — a reader (arbiter or recovering bob) must never
#        observe a partially-written bundle. We use temp file in the same
#        directory + fsync(fd) + fsync(parent dir) + atomic rename. The
#        rename is atomic on POSIX when source and destination are on the
#        same filesystem; placing the temp file in the destination
#        directory guarantees that.
#
# Backward-compat note: run_trusted_test_suite() still computes
# bundle["bundle_hash"] using canonical_json (over the bundle including the
# old top-level fields). The new bundle_hash_hex() is the canonical Phase 1
# definition and excludes the "bundle_hash" key from the digest input. Both
# coexist during Phase 1; Phase 2 will migrate consumers to the new digest.


# Keys excluded from the canonical-bytes input when hashing a bundle.
# Excluding "bundle_hash" prevents the recursion paradox: you cannot include
# the hash of X inside X. Excluding other ephemeral runtime metadata is
# deliberate — see canonical_bundle_bytes docstring for the rationale.
_BUNDLE_HASH_EXCLUDED_KEYS = frozenset({"bundle_hash"})


def canonical_bundle_bytes(bundle: Dict[str, Any]) -> bytes:
    """Return the deterministic byte serialization used for hashing a bundle.

    The output:
        - Excludes any key in _BUNDLE_HASH_EXCLUDED_KEYS (currently only
          "bundle_hash") from the top-level object.
        - Uses json.dumps with sort_keys=True and the most compact separators
          so re-serialization on any platform is byte-identical.
        - Uses ensure_ascii=False then encodes UTF-8 — the JSON is platform-
          independent and the byte string round-trips losslessly.

    Two different in-memory bundles that differ only in their "bundle_hash"
    field MUST produce the same canonical bytes. Two bundles that differ in
    ANY other field MUST produce different canonical bytes.
    """
    if not isinstance(bundle, dict):
        raise TypeError(
            f"bundle must be a dict; got {type(bundle).__name__}"
        )
    filtered = {k: v for k, v in bundle.items() if k not in _BUNDLE_HASH_EXCLUDED_KEYS}
    return json.dumps(
        filtered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def bundle_hash_hex(bundle: Dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of canonical_bundle_bytes(bundle).

    Phase 1 definition of bundle_hash. This is what the verification arbiter
    will recompute from the on-disk bytes to verify content integrity
    (verdict tuple field, design §5.3).
    """
    return hashlib.sha256(canonical_bundle_bytes(bundle)).hexdigest()


def _fsync_dir(directory: Path) -> None:
    """fsync the directory so the rename is durable on disk.

    On POSIX, atomic rename's metadata change isn't durable until the parent
    directory is fsynced. Failing this is a silent durability hole (the file
    survives a kernel crash but the rename does not, which means a reader
    sees the OLD file or no file at all — but never a torn one). We tolerate
    OSError because some filesystems (e.g., certain network mounts) reject
    fsync on directories; in that case the OS-level guarantees are weaker
    but the rename is still atomic.
    """
    try:
        fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically with full fsync semantics (§5.7).

    Steps:
        1. Create the temp file in the SAME directory as the destination
           (so the rename stays on the same filesystem and is atomic).
        2. Write all bytes to the temp file's fd.
        3. fsync the fd — guarantees the bytes are on the disk.
        4. Close the fd, then os.replace (atomic on POSIX, atomic on
           Windows for files that fit on the same volume per Python docs).
        5. fsync the parent directory — guarantees the rename is durable.

    No reader is ever able to observe a torn or partial write. A crash at
    any point either leaves the destination unchanged (steps 1–3) or
    fully replaces it (step 4 onward).
    """
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile with delete=False so we control the close + rename.
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(path))
        _fsync_dir(parent)
    except BaseException:
        # On any error (including KeyboardInterrupt), do not leave a stray
        # tmp file in the destination directory.
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_bundle(
    bundle: Dict[str, Any],
    dest_dir: Path,
) -> Tuple[Path, str]:
    """Persist `bundle` to dest_dir under its content-addressed filename.

    The filename is `<bundle_hash>.bundle.json` per design §5.2 / §5.7. The
    bundle is serialized via canonical_bundle_bytes (so the on-disk bytes
    match what bundle_hash_hex hashed). If the bundle dict does not already
    contain a `bundle_hash` field, one is added before serialization for
    consumer convenience — but it is EXCLUDED from the canonical bytes used
    for hashing (see canonical_bundle_bytes).

    Returns (path_written, bundle_hash_hex). Idempotent: writing the same
    bundle twice yields the same destination path and same hash; the
    second write overwrites the first atomically with identical bytes.
    """
    dest_dir = Path(dest_dir)
    h = bundle_hash_hex(bundle)
    # Augment the bundle in-memory with the hash for consumer convenience,
    # WITHOUT changing the bytes used to compute that hash.
    augmented = dict(bundle)
    augmented["bundle_hash"] = h
    # Re-derive canonical bytes from the augmented form: this still excludes
    # bundle_hash, so the bytes equal canonical_bundle_bytes(bundle). We then
    # serialize the AUGMENTED form (with bundle_hash present) for human/tooling
    # readability of the on-disk file. The hashed bytes and the persisted
    # bytes intentionally differ in exactly one key.
    persisted = json.dumps(
        augmented,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    out_path = dest_dir / f"{h}.bundle.json"
    atomic_write_bytes(out_path, persisted)
    return out_path, h


# ---------------------------------------------------------------------------
# Phase 2 additions — multi-file atomic transaction (ecosystem-keystone §5.5, §7.5 R9)
# ---------------------------------------------------------------------------
#
# Why bundle_write exists (ecosystem-keystone design §5.5 last paragraph + §5.10):
#
#   `claims.resolve_challenge` (approved amendment) and
#   `claims.file_lifecycle_event` (entity split/merge/retire) must write TWO
#   or more ledger files in a single logical commit. Example — approving a
#   challenge that amends `binds_to` must update BOTH:
#
#     1. .design-ledger/skeletons/<screen>.yaml   (new skeleton version)
#     2. progress/contract-map.yaml                (matching contract-map delta)
#
#   If the first rename succeeds and the second fails (or the process is
#   pkill'd between the two), the on-disk state is inconsistent: skeleton
#   references a binds_to target that the contract-map doesn't declare yet,
#   or vice versa. Downstream gates (G_V, G_XR) will either falsely block
#   or falsely pass depending on which file won.
#
#   `bundle_write` commits a list of (path, bytes) atomically with pre-image
#   rollback — we save each destination's pre-image bytes under
#   `rollback_dir/<txn_id>/` BEFORE any rename, then replay per-file writes
#   via `atomic_write_bytes`. On any failure mid-transaction, we restore
#   already-renamed files from their pre-images (reverse order) and raise.
#
#   Power-loss or SIGKILL between renames is handled by
#   `recover_orphan_rollback(project_root)` — a session-start sweeper that
#   walks `<project_root>/.tmp/rollback/` for orphan manifests and restores
#   pre-images back to their source paths. Orphan = rollback dir present on
#   disk (meaning the previous transaction did NOT clean up, which only
#   happens if the process died between "rollback dir created" and "all
#   renames committed successfully").
#
# Invariant proof (design §7.6 row 5):
#   - If bundle_write returns normally -> all writes committed; rollback
#     dir deleted. No orphan left for recovery to process.
#   - If bundle_write raises -> every write that renamed successfully has
#     been reverted; rollback dir may remain only if cleanup itself failed
#     (tolerated; next recovery sweep is idempotent).
#   - If bundle_write is killed mid-execution -> rollback dir is still on
#     disk with manifest.json intact; next session's
#     `recover_orphan_rollback` restores any committed pre-images.
#
# Backward compatibility: these are PURE additions. Existing callers of
# `atomic_write_bytes` / `atomic_write_bundle` are unaffected.


# Default subdirectory within `project_root` that holds transaction scratch.
# Matches the on-disk convention referenced in contract-map.yaml and §5.10.
_ROLLBACK_SUBDIR = Path(".tmp") / "rollback"

# Manifest filename written inside each <txn_id> rollback dir. The manifest
# records the pre-image-to-target mapping + whether the target existed
# pre-transaction so recovery can distinguish "restore pre-image" from
# "unlink target that was never supposed to exist".
_ROLLBACK_MANIFEST_NAME = "manifest.json"


def _generate_txn_id() -> str:
    """Return a transaction id: compact timestamp + short uuid hex.

    Shape mirrors `claims.py` id conventions (uuid4-based, kept short enough
    to fit in filesystem path segments without filesystem-case-fold issues).
    """
    import uuid
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:12]
    return f"{stamp}-{suffix}"


def _default_rollback_dir() -> Path:
    """Return the default rollback_dir when the caller passed None.

    Convention: `<cwd>/.tmp/rollback/`. Callers (claims.resolve_challenge,
    claims.file_lifecycle_event) will almost always pass an explicit
    rollback_dir derived from `project_root`; the cwd default is a sane
    fallback for ad-hoc use.
    """
    return Path.cwd() / _ROLLBACK_SUBDIR


def _save_pre_image(
    target: Path,
    txn_dir: Path,
    index: int,
) -> Dict[str, Any]:
    """Capture the pre-image of `target` under `txn_dir`.

    Returns a manifest entry of the shape:
        {
            "target": "<absolute path of target>",
            "pre_image": "<relative filename inside txn_dir, or null>",
            "existed": <bool>,
        }

    If `target` does NOT exist, `existed` is False and `pre_image` is None.
    Recovery uses `existed` to decide: False + target-now-exists -> unlink
    the target (it was created by a partial commit); True -> restore bytes.

    Pre-image bytes are written via atomic_write_bytes for durability.
    """
    target = Path(target)
    entry: Dict[str, Any] = {
        "target": str(target),
        "pre_image": None,
        "existed": False,
    }
    if target.is_file():
        pre_image_name = f"preimage.{index:04d}.bin"
        pre_image_path = txn_dir / pre_image_name
        # Read-then-atomic-write. We cannot just copy because fsync semantics
        # differ; keeping the same durability contract as the commit path
        # ensures recovery bytes are on disk before we attempt any rename.
        data = target.read_bytes()
        atomic_write_bytes(pre_image_path, data)
        entry["pre_image"] = pre_image_name
        entry["existed"] = True
    elif target.exists():
        # Target exists but isn't a regular file (directory, symlink-to-dir,
        # device). We refuse — bundle_write commits bytes to file paths only.
        raise ValueError(
            f"bundle_write target is not a regular file: {target}"
        )
    return entry


def _restore_pre_image(entry: Dict[str, Any], txn_dir: Path) -> None:
    """Reverse a single commit: restore target from its manifest entry.

    Semantics:
        - existed=True  -> re-materialize target from pre_image bytes.
        - existed=False -> unlink target if it now exists (was created by
          the partial commit we are rolling back).

    This function MUST be idempotent: if the target is already in the
    desired state (pre-image content, or absent), calling us again is a
    no-op.  Recovery calls us repeatedly if prior recovery was interrupted.
    """
    target = Path(entry["target"])
    if entry.get("existed"):
        pre_image_name = entry.get("pre_image")
        if not pre_image_name:
            # Manifest corruption: existed=True but no pre_image recorded.
            # Best effort — leave target as-is, surface via observation.
            return
        pre_image_path = txn_dir / pre_image_name
        if pre_image_path.is_file():
            atomic_write_bytes(target, pre_image_path.read_bytes())
    else:
        # Pre-image did not exist. If the target was created by a partial
        # commit, remove it. If it was never created, this is a no-op.
        try:
            target.unlink()
        except FileNotFoundError:
            pass


def _delete_txn_dir(txn_dir: Path) -> None:
    """Remove the transaction scratch dir after successful commit.

    Best-effort: if cleanup fails, the next `recover_orphan_rollback` will
    see the dir, notice all targets already match their committed state,
    and clean up harmlessly. We never raise from cleanup.
    """
    if not txn_dir.is_dir():
        return
    try:
        import shutil
        shutil.rmtree(txn_dir, ignore_errors=True)
    except Exception:
        pass


class BundleWriteError(Exception):
    """Raised when bundle_write fails and has performed a rollback.

    Attributes:
        txn_id (str)                  - id of the failed transaction
        rolled_back_paths (list[str]) - targets whose renames were reverted
        failed_path (str | None)      - the path whose write triggered the
                                        rollback (commit failure point)
        cause (BaseException | None)  - the underlying exception
    """

    def __init__(
        self,
        message: str,
        *,
        txn_id: str,
        rolled_back_paths: List[str],
        failed_path: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message)
        self.txn_id = txn_id
        self.rolled_back_paths = list(rolled_back_paths)
        self.failed_path = failed_path
        self.cause = cause


def bundle_write(
    writes: List[Tuple[Path, bytes]],
    *,
    rollback_dir: Optional[Path] = None,
    txn_id: Optional[str] = None,
) -> str:
    """Commit all `writes` atomically with pre-image rollback (§5.5 last para).

    Each entry in `writes` is (destination_path, new_bytes). All writes
    happen in a single logical transaction:

        Phase 1 (pre-image snapshot):
            For each write: capture current on-disk bytes (or "absent")
            under `rollback_dir/<txn_id>/` with a manifest.json describing
            the target-to-preimage mapping.

        Phase 2 (commit):
            For each write, in the order given: `atomic_write_bytes(path, bytes)`.

        Phase 3 (cleanup):
            If every commit succeeded: delete the rollback dir.
            If ANY commit failed: restore already-committed targets from
            their pre-images in reverse order, then raise BundleWriteError
            with `rolled_back_paths`. The rollback dir is KEPT so the next
            `recover_orphan_rollback` can verify state and clean up.

    Args:
        writes: list of (Path, bytes) pairs. Order determines commit order
            AND the inverse rollback order on failure.
        rollback_dir: directory that holds pre-image scratch. If None,
            defaults to `<cwd>/.tmp/rollback/`. Callers invoking from a
            known project root should pass `project_root / ".tmp/rollback"`.
        txn_id: transaction identifier. If None, a time-ordered id is
            generated automatically.

    Returns:
        The final `txn_id` (generated if caller passed None).

    Raises:
        ValueError: if `writes` is empty, or any target is not a regular file.
        BundleWriteError: if a commit failed and rollback was performed.
            The exception carries `txn_id`, `rolled_back_paths`, `failed_path`,
            and `cause` attributes.

    Durability:
        Each pre-image and each commit uses the same fsync+rename semantics
        as `atomic_write_bytes`. Power-loss between renames leaves the
        rollback dir intact for `recover_orphan_rollback` to process.
    """
    if not writes:
        raise ValueError("bundle_write requires at least one (path, bytes) pair")

    if rollback_dir is None:
        rollback_dir = _default_rollback_dir()
    rollback_dir = Path(rollback_dir)

    if txn_id is None:
        txn_id = _generate_txn_id()

    txn_dir = rollback_dir / txn_id
    txn_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: snapshot pre-images + write manifest BEFORE any commit.
    # The manifest is what recovery reads; it MUST hit disk durably before
    # we attempt any rename of a target, otherwise a crash between
    # "target committed" and "manifest written" would leave recovery
    # unable to undo.
    manifest_entries: List[Dict[str, Any]] = []
    for idx, (target, _data) in enumerate(writes):
        entry = _save_pre_image(Path(target), txn_dir, idx)
        manifest_entries.append(entry)

    manifest = {
        "txn_id": txn_id,
        "created_at": now_iso(),
        "entries": manifest_entries,
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    atomic_write_bytes(txn_dir / _ROLLBACK_MANIFEST_NAME, manifest_bytes)

    # Phase 2: commit each write via atomic_write_bytes. Track which ones
    # committed so we can reverse them on failure.
    committed: List[Path] = []
    for idx, (target, data) in enumerate(writes):
        target_path = Path(target)
        try:
            atomic_write_bytes(target_path, data)
            committed.append(target_path)
        except BaseException as exc:
            # Rollback: reverse every committed write (reverse order).
            # Recovery sweeper completes any residuals on next session start.
            rolled_back: List[str] = []
            for prev_target in reversed(committed):
                prev_entry = next(
                    (e for e in manifest_entries if Path(e["target"]) == prev_target),
                    None,
                )
                if prev_entry is None:
                    continue
                try:
                    _restore_pre_image(prev_entry, txn_dir)
                    rolled_back.append(str(prev_target))
                except Exception:
                    # Best effort — continue with remaining rollbacks.
                    pass
            # Do NOT delete the rollback dir here: if our own restore
            # failed for any reason, the next recovery sweep needs the
            # manifest to finish the job.
            #
            # S028 Phase-5b spawn 7 fix: emit gate_false_block observation
            # BEFORE the raise so alf has a side-channel signal alongside
            # the BundleWriteError fields. Best-effort; never blocks raise.
            _safe_observe_rollback(
                fingerprint="trusted-runner-keystone-bundle-write-rollback",
                target_path=str(target_path),
                txn_id=txn_id,
                failed_path=str(target_path),
                cause=exc,
            )
            raise BundleWriteError(
                f"bundle_write txn {txn_id} failed on target {target_path}: {exc!r}",
                txn_id=txn_id,
                rolled_back_paths=rolled_back,
                failed_path=str(target_path),
                cause=exc,
            ) from exc

    # Phase 3: everything committed — delete rollback scratch.
    _delete_txn_dir(txn_dir)
    return txn_id


def recover_orphan_rollback(project_root: Path) -> List[str]:
    """Restore pre-images from any orphan transaction directory (§5.10).

    Called at session start by bob (see design §5.10 "Cross-ledger atomic
    write fails mid-transaction"). An orphan rollback dir indicates the
    previous session died between the first rename and the final cleanup
    step — we must restore every target from its pre-image so the
    on-disk state rewinds to "before the transaction started".

    Scan scope: `<project_root>/.tmp/rollback/*/manifest.json`. Directories
    without a readable manifest are left alone (they may be in-progress
    transactions from a concurrent process). Directories with a manifest
    are fully processed: each entry restored, the dir deleted on success.

    Args:
        project_root: root directory whose `.tmp/rollback/` subtree holds
            orphan transactions.

    Returns:
        Sorted list of transaction ids whose pre-images were restored (the
        directory names that had valid manifests and completed restoration).

    Idempotency:
        Safe to call repeatedly. A no-op if `.tmp/rollback/` is absent or
        contains no manifests.
    """
    project_root = Path(project_root)
    rollback_root = project_root / _ROLLBACK_SUBDIR
    restored: List[str] = []
    if not rollback_root.is_dir():
        return restored
    for txn_dir in sorted(rollback_root.iterdir()):
        if not txn_dir.is_dir():
            continue
        manifest_path = txn_dir / _ROLLBACK_MANIFEST_NAME
        if not manifest_path.is_file():
            # In-progress transaction (manifest not yet written) or
            # garbage dir. Leave it alone.
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Corrupt manifest — skip, do not crash the session.
            continue
        entries = manifest.get("entries") or []
        if not isinstance(entries, list):
            continue
        # Restore in reverse order — mirrors the rollback order inside
        # `bundle_write` and makes the semantics identical whether the
        # rollback ran in-process or post-crash.
        for entry in reversed(entries):
            if not isinstance(entry, dict) or "target" not in entry:
                continue
            try:
                _restore_pre_image(entry, txn_dir)
            except Exception:
                # Best-effort — continue with remaining entries.
                continue
        restored.append(manifest.get("txn_id") or txn_dir.name)
        _delete_txn_dir(txn_dir)
    return sorted(restored)


# ---------------------------------------------------------------------------
# pytest runner
# ---------------------------------------------------------------------------


def _run_pytest(
    test_path: Path, timeout: int
) -> Dict[str, Any]:
    """Run a single pytest target and return a sanitized result.

    The CB3 fix: we discard raw stdout/stderr after parsing the JSON report.
    The auditor never sees free-form text that could carry prompt injection.
    """
    cmd = [
        "pytest",
        "--tb=short",
        "-q",
        "--disable-warnings",
        # JSON report goes to stdout via --json-report-file=- if pytest-json-report
        # is installed; otherwise we fall back to parsing the exit code.
        str(test_path),
    ]
    # Try with the JSON reporter first; fall back if not installed
    json_cmd = cmd[:1] + ["--json-report", "--json-report-file=/dev/stdout"] + cmd[1:]
    try:
        result = subprocess.run(
            json_cmd,
            env=sanitized_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        # Try to parse JSON report from stdout.
        # pytest-json-report writes its JSON to /dev/stdout, which lands on the
        # same line as pytest's progress bar (e.g. "..... [100%]{...json...}").
        # Strategy: scan the full stdout for the first "{", then find a balanced
        # top-level object via brace counting (skipping braces inside strings).
        report: Dict[str, Any] = {}
        stdout_text = result.stdout or ""
        first_brace = stdout_text.find("{")
        if first_brace >= 0:
            depth = 0
            in_str = False
            esc = False
            end_idx = -1
            for i in range(first_brace, len(stdout_text)):
                ch = stdout_text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
            if end_idx > first_brace:
                candidate = stdout_text[first_brace : end_idx + 1]
                try:
                    report = json.loads(candidate)
                except json.JSONDecodeError:
                    report = {}
        if not report:
            # pytest-json-report is an OPTIONAL plugin and is often absent (an
            # unrecognized --json-report aborts the run, which is why we re-run
            # here). Before degrading to a bare exit code, try pytest's BUILT-IN
            # JUnit XML, which needs no plugin and still carries per-test rows.
            with tempfile.TemporaryDirectory() as _xml_dir:
                xml_path = Path(_xml_dir) / "report.xml"
                junit_cmd = cmd[:1] + [f"--junit-xml={xml_path}"] + cmd[1:]
                try:
                    junit_run = subprocess.run(
                        junit_cmd, env=sanitized_env(), capture_output=True,
                        text=True, timeout=timeout, check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    junit_run = None
                if junit_run is not None and xml_path.is_file():
                    parsed = _parse_junit_xml(xml_path, test_path, junit_run.returncode)
                    if parsed is not None:
                        return parsed
            # Last resort: run plain pytest and report ONLY the exit code,
            # explicitly flagged as degraded (never a fabricated count).
            plain = subprocess.run(
                cmd, env=sanitized_env(), capture_output=True, text=True,
                timeout=timeout, check=False,
            )
            return _result_from_returncode(test_path, plain.returncode)
        summary = report.get("summary") or {}
        tests = report.get("tests") or []
        # RT1 fix: emit per-test granularity from pytest-json-report's tests[]
        # instead of discarding it. Auditors need nodeid/outcome/duration to
        # tie specific passing tests to specific success_criteria. CB3 compliance
        # preserved — no raw stdout/stderr/tracebacks, only structured fields.
        per_test: List[Dict[str, Any]] = []
        for t in tests:
            # Best-effort duration: pytest-json-report records per-phase
            # durations under t["call"]["duration"] (+ setup/teardown). Sum
            # the three phases if present; fall back to top-level "duration".
            duration_s = 0.0
            for phase in ("setup", "call", "teardown"):
                phase_obj = t.get(phase)
                if isinstance(phase_obj, dict):
                    try:
                        duration_s += float(phase_obj.get("duration", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        pass
            if duration_s == 0.0:
                try:
                    duration_s = float(t.get("duration", 0.0) or 0.0)
                except (TypeError, ValueError):
                    duration_s = 0.0
            keywords = t.get("keywords") or []
            # keywords may be a dict (older plugin versions) — coerce to list of keys
            if isinstance(keywords, dict):
                keywords = sorted(keywords.keys())
            per_test.append({
                "nodeid": t.get("nodeid", "?"),
                "outcome": t.get("outcome", "?"),
                "duration_s": round(duration_s, 6),
                "keywords": list(keywords),
            })
        # Backward-compat: keep failed_tests[] exactly as before.
        failed_tests = [
            {"nodeid": t.get("nodeid", "?"), "outcome": t.get("outcome", "?")}
            for t in tests
            if t.get("outcome") in ("failed", "error")
        ]
        return {
            "path": str(test_path),
            "returncode": result.returncode,
            "summary": {
                "total": int(summary.get("total", 0)),
                "passed": int(summary.get("passed", 0)),
                "failed": int(summary.get("failed", 0)),
                "skipped": int(summary.get("skipped", 0)),
                "error": int(summary.get("error", 0)),
                "duration_s": float(report.get("duration", 0.0)),
            },
            "tests": per_test,
            "failed_tests": failed_tests,
        }
    except subprocess.TimeoutExpired:
        return {
            "path": str(test_path),
            "returncode": -1,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": float(timeout)},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "timeout"}],
        }
    except FileNotFoundError:
        return {
            "path": str(test_path),
            "returncode": -2,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": 0.0},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "runner_not_found"}],
        }


def _result_from_returncode(test_path: Path, rc: int) -> Dict[str, Any]:
    """Last-resort fallback: only the exit code is known.

    This MUST NOT fabricate a test count. The previous implementation reported
    ``total: 1, passed: 1`` for a file containing any number of tests, so a
    3-test file that passed was recorded as a single passing test — and nothing
    marked the record as degraded. An auditor scoring coverage against a test
    plan read that invented granularity as real evidence.

    Counts are therefore reported as 0 with ``granularity: "none"`` and an
    explicit ``degraded`` flag. Consumers must treat a ``none`` granularity as
    "pass/fail is known, per-test detail is NOT available", never as a count.
    """
    return {
        "path": str(test_path),
        "returncode": rc,
        "granularity": "none",
        "degraded": True,
        "degraded_reason": (
            "neither pytest-json-report nor JUnit XML was available; only the "
            "process exit code is known"
        ),
        "summary": {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "duration_s": 0.0,
            "counts_available": False,
            "outcome": "passed" if rc == 0 else "failed",
        },
        "failed_tests": [] if rc == 0 else [{"nodeid": str(test_path), "outcome": "failed"}],
    }


def _parse_junit_xml(xml_path: Path, test_path: Path, rc: int) -> Optional[Dict[str, Any]]:
    """Per-test granularity from pytest's BUILT-IN ``--junit-xml``.

    pytest-json-report is an optional third-party plugin and is frequently
    absent; JUnit XML ships with pytest itself, so this path works on any
    stock install. Returns None if the file is missing or unparseable.

    XML safety: the document is produced by pytest into a private temp file we
    created, so it is not attacker-controlled. defusedxml is used when present;
    stdlib ElementTree is the fallback and does not resolve external entities.
    """
    try:
        from defusedxml import ElementTree as _ET  # type: ignore
    except ImportError:
        import xml.etree.ElementTree as _ET  # type: ignore

    try:
        root = _ET.parse(str(xml_path)).getroot()
    except Exception:
        return None

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return None

    per_test: List[Dict[str, Any]] = []
    total_duration = 0.0
    for suite in suites:
        for case in suite.iter("testcase"):
            outcome = "passed"
            for child in case:
                tag = child.tag.lower()
                if tag == "failure":
                    outcome = "failed"
                elif tag == "error":
                    outcome = "error"
                elif tag == "skipped":
                    outcome = "skipped"
            try:
                duration_s = float(case.get("time") or 0.0)
            except (TypeError, ValueError):
                duration_s = 0.0
            total_duration += duration_s
            name = case.get("name") or "?"
            # Reconstruct a pytest-style nodeid. JUnit gives a dotted classname,
            # not a path, so prefer the concrete file we were asked to run.
            file_attr = case.get("file") or test_path.name
            per_test.append({
                "nodeid": f"{file_attr}::{name}",
                "outcome": outcome,
                "duration_s": round(duration_s, 6),
                # JUnit XML carries no marker/keyword data — say so rather than
                # emitting [] which would read as "this test has no markers".
                "keywords": [],
            })

    if not per_test:
        return None

    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for t in per_test:
        counts[t["outcome"]] = counts.get(t["outcome"], 0) + 1

    return {
        "path": str(test_path),
        "returncode": rc,
        "granularity": "junit",
        "keywords_available": False,
        "summary": {
            "total": len(per_test),
            "passed": counts["passed"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "error": counts["error"],
            "duration_s": round(total_duration, 6),
            "counts_available": True,
        },
        "tests": per_test,
        "failed_tests": [
            {"nodeid": t["nodeid"], "outcome": t["outcome"]}
            for t in per_test if t["outcome"] in ("failed", "error")
        ],
    }


# ---------------------------------------------------------------------------
# jest runner
# ---------------------------------------------------------------------------


def _run_jest(test_path: Path, timeout: int) -> Dict[str, Any]:
    cmd = ["jest", "--json", "--silent", str(test_path)]
    try:
        result = subprocess.run(
            cmd,
            env=sanitized_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            report = {}
        num_total = report.get("numTotalTests", 0)
        num_passed = report.get("numPassedTests", 0)
        num_failed = report.get("numFailedTests", 0)
        num_skipped = report.get("numPendingTests", 0)
        failed_tests: List[Dict[str, str]] = []
        for tr in report.get("testResults") or []:
            for assertion in tr.get("assertionResults") or []:
                if assertion.get("status") == "failed":
                    failed_tests.append({
                        "nodeid": assertion.get("fullName", "?"),
                        "outcome": "failed",
                    })
        return {
            "path": str(test_path),
            "returncode": result.returncode,
            "summary": {
                "total": int(num_total),
                "passed": int(num_passed),
                "failed": int(num_failed),
                "skipped": int(num_skipped),
                "error": 0,
                "duration_s": 0.0,
            },
            "failed_tests": failed_tests,
        }
    except subprocess.TimeoutExpired:
        return {
            "path": str(test_path),
            "returncode": -1,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": float(timeout)},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "timeout"}],
        }
    except FileNotFoundError:
        return {
            "path": str(test_path),
            "returncode": -2,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": 0.0},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "runner_not_found"}],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_trusted_test_suite(
    component_id: str,
    test_paths: List[Path],
    runner: str = "pytest",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    *,
    required_tiers: Optional[Dict[str, int]] = None,
    inventory_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Bob runs the test runner directly. Skills NEVER call this.

    Returns a sanitized audit bundle tagged `produced_by: bob-trusted-runner`.
    The bundle is what audit_spawn.py consumes — never raw skill stdout.

    S048 / #116 R-B1: when `required_tiers` (a {nodeid: required_tier} map bob
    derives from the frozen test plan) is supplied, the bundle is stamped with a
    `tier_decision` block + per-test `sanctioned_tier_skip` BEFORE bundle_hash is
    computed, so the deterministic verification arm can grant GREEN-by-sanctioned-
    skip on sub-tier hosts without false-blocking. The stamp is hash-bound into
    the evidence (reproducible from inventory_hash). Default (no map) preserves
    the exact prior bundle shape — additive and back-compatible.
    """
    bundle: Dict[str, Any] = {
        "component_id": component_id,
        "produced_by": "bob-trusted-runner",
        "runner_info": runner_info(runner),
        "run_at": now_iso(),
        "test_paths": [str(p) for p in test_paths],
        "results": [],
    }
    for test_path in test_paths:
        if runner == "pytest":
            res = _run_pytest(Path(test_path), timeout=timeout)
        elif runner == "jest":
            res = _run_jest(Path(test_path), timeout=timeout)
        else:
            res = {
                "path": str(test_path),
                "returncode": -3,
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": 0.0},
                "failed_tests": [{"nodeid": "?", "outcome": f"unknown_runner:{runner}"}],
            }
        bundle["results"].append(res)
    # R-B1: stamp the tier decision BEFORE hashing so the sanction is hash-bound.
    # Only stamp when bob actually supplies a tier map (keeps the default bundle
    # shape byte-identical for callers that don't pass one — the hash is computed
    # over whatever the bundle then contains, exactly as before).
    if required_tiers is not None:
        stamp_tier_decision(bundle, required_tiers, inventory_path=inventory_path)
    bundle["bundle_hash"] = sha256_hex(canonical_json(bundle))
    return bundle


def all_passed(bundle: Dict[str, Any]) -> bool:
    """Convenience: True iff every result has 0 failed and 0 error and returncode 0."""
    for r in bundle.get("results", []):
        if r.get("returncode", -1) != 0:
            return False
        s = r.get("summary") or {}
        if s.get("failed", 0) != 0 or s.get("error", 0) != 0:
            return False
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 3:
        sys.stderr.write("usage: trusted_runner.py <component_id> <test_path> [<test_path> ...] [--runner pytest|jest]\n")
        sys.exit(3)
    component_id = argv[1]
    runner = "pytest"
    test_paths: List[str] = []
    i = 2
    while i < len(argv):
        if argv[i] == "--runner":
            runner = argv[i + 1]
            i += 2
        else:
            test_paths.append(argv[i])
            i += 1
    bundle = run_trusted_test_suite(component_id, [Path(p) for p in test_paths], runner=runner)
    sys.stdout.write(json.dumps(bundle, indent=2) + "\n")
    sys.exit(0 if all_passed(bundle) else 2)


if __name__ == "__main__":
    main()
