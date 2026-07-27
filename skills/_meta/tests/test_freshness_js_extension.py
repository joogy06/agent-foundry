#!/usr/bin/env python3
"""test_freshness_js_extension.py — WP-18 (S055 §10 / M4 / Codex #14).

Regression: a `.js`-anchored FRESHNESS block under the workflows root lands in
the freshness index AND rot_scan sees the file. Without the per-root extension
generalization, adding the workflows root alone would leave every `.js` anchor
decorative.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import freshness as fr  # noqa: E402
import rot_scan as rs  # noqa: E402

JS_FIXTURE = """// WORKFLOW: fixture v1.0.0
export const meta = { name: "fixture" };
/* <!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: fixture-tool-surface
    verified_against: "1.2.3"
    verified_on: "2026-06-11"
    volatility: high
--> */
"""


def test_js_anchor_lands_in_freshness_index():
    with tempfile.TemporaryDirectory() as d:
        wf = Path(d) / "workflows"
        wf.mkdir()
        (wf / "fixture.js").write_text(JS_FIXTURE)
        # build_index with empty skills/agents roots + our workflows root.
        empty = Path(d) / "empty"
        empty.mkdir()
        idx = fr.build_index(skills_root=empty, agents_root=empty, workflows_root=wf)
        assert "fixture-tool-surface" in idx["by_tool"], "JS FRESHNESS anchor not indexed"
        targets = idx["by_tool"]["fixture-tool-surface"]
        assert any(t.endswith("fixture.js") for t in targets)


def test_per_root_extension_set():
    # The workflows root yields *.md AND *.js; other roots yield *.md only.
    assert "*.js" in fr.ROOT_EXTENSIONS[str(fr.WORKFLOWS_ROOT)]
    assert "*.js" not in fr.ROOT_EXTENSIONS[str(fr.SKILLS_ROOT)]


def test_rot_scan_iterates_workflow_js():
    # Against the live prod workflows root (where the 8 .js are synced), rot's
    # iter_targets must surface at least one .js.
    targets = list(rs.iter_targets(Path.home() / ".claude" / "skills", Path.home() / ".claude" / "agents"))
    js = [str(t) for t in targets if str(t).endswith(".js") and "workflows" in str(t)]
    # Tolerate a fresh checkout with no synced workflows by asserting the code path
    # exists; when workflows are present, at least one .js is yielded.
    if (Path.home() / ".claude" / "workflows").is_dir() and any(
        p.suffix == ".js" for p in (Path.home() / ".claude" / "workflows").glob("*.js")
    ):
        assert js, "rot_scan did not yield any workflow .js targets"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
