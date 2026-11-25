"""cve_proof.py — Emit CVE proof-of-fix tests (mode-c only).

For each CVE finding marked direct-fix-available or workaround-required,
generate one test that:
  1. Documents the vulnerability (CVE id, fix_path, fix_category)
  2. Stubs out the vulnerable-input scenario the CVE describes
  3. Asserts that the fix prevents the vulnerability (post-bump)

A CVE is only marked "fixed" when (a) the test passes AND (b) the
vulnerable version is gone from the lockfile (the lockfile check happens
in evo proper, not in this skill).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import test_header  # noqa: E402


def emit_pytest(
    component_id: str,
    findings: List[Dict[str, Any]],
    *,
    mode: str = "cve-fix",
    wiring_snapshot_hash: str = "unknown",
) -> List[Dict[str, Any]]:
    """Emit one proof-of-fix test per CVE finding for this component."""
    out: List[Dict[str, Any]] = []
    for f in findings:
        if f.get("kind") != "cve":
            continue
        # Only generate when the fix is actionable
        fix_cat = f.get("fix_category", "")
        if fix_cat not in ("direct-fix-available", "workaround-required"):
            continue

        cve_id = f.get("cve_id", "CVE-unknown")
        package = f.get("package", "package")
        fix_path = f.get("fix_path", "")
        cve_slug = cve_id.lower().replace("-", "_")
        filename = f"test_evo_{mode}_{component_id}__{cve_slug}__proof.py"

        header = test_header.build_header(
            language="python",
            confidence_level="cve-proof-of-fix",
            mode=mode,
            source_basis=f"drift-report.findings[cve_id={cve_id}]",
            source_seed=cve_id,
            wiring_evidence=f"{wiring_snapshot_hash} @ {component_id} @ {cve_id}",
        )

        body = f'''
"""
CVE: {cve_id}
Package: {package}
Fix category: {fix_cat}
Fix path: {fix_path}
"""


def test_{cve_slug}_proof_of_fix():
    """Asserts that the {cve_id} vulnerability is not reachable post-fix.

    Pre-conditions (handled by evo):
      - {package} bumped per fix_path: {fix_path}
      - Resolved lockfile no longer contains vulnerable version

    This test exercises a vulnerability-trigger pattern and asserts that
    the fixed code returns a safe value / raises a sanctioned error
    instead of exposing the CVE-described behaviour.
    """
    # TODO-IMPLEMENT-FUZZ: shape an input that would trigger {cve_id} pre-fix
    # TODO-IMPLEMENT-CALL: exercise the patched code on that input
    # TODO-IMPLEMENT-ASSERT: assert the safe-path response, not the vuln response
    pytest.skip(
        "evo-generated CVE proof-of-fix stub — replace TODOs with a "
        "concrete trigger sourced from {cve_id} advisory before relying on it"
    )
'''
        out.append({
            "filename": filename,
            "content": header + body,
            "seed_id": cve_id,
            "test_type": "cve_proof",
        })
    return out


def emit_jest(
    component_id: str,
    findings: List[Dict[str, Any]],
    *,
    mode: str = "cve-fix",
    wiring_snapshot_hash: str = "unknown",
) -> List[Dict[str, Any]]:
    """Emit one proof-of-fix jest test per CVE finding for this component."""
    out: List[Dict[str, Any]] = []
    for f in findings:
        if f.get("kind") != "cve":
            continue
        fix_cat = f.get("fix_category", "")
        if fix_cat not in ("direct-fix-available", "workaround-required"):
            continue
        cve_id = f.get("cve_id", "CVE-unknown")
        package = f.get("package", "package")
        fix_path = f.get("fix_path", "")
        cve_slug = cve_id.lower().replace("-", "_")
        filename = f"test_evo_{mode}_{component_id}__{cve_slug}__proof.test.js"

        header = test_header.build_header(
            language="javascript",
            confidence_level="cve-proof-of-fix",
            mode=mode,
            source_basis=f"drift-report.findings[cve_id={cve_id}]",
            source_seed=cve_id,
            wiring_evidence=f"{wiring_snapshot_hash} @ {component_id} @ {cve_id}",
        )

        body = f'''
describe("CVE proof of fix :: {component_id} :: {cve_id}", () => {{
  // Package: {package}; fix_category: {fix_cat}; fix_path: {fix_path}
  test.skip("vuln pattern is not reachable post-fix", () => {{
    // TODO-IMPLEMENT-FUZZ / CALL / ASSERT
  }});
}});
'''
        out.append({
            "filename": filename,
            "content": header + body,
            "seed_id": cve_id,
            "test_type": "cve_proof",
        })
    return out
