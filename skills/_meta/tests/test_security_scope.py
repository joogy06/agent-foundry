#!/usr/bin/env python3
"""test_security_scope.py — S045 / #120 §9 verification suite.

Covers the advisory-default-on universal security checkpoint (G_SECURITY) +
the git-diff-derived security_scope() helper + the D3 false-clean hardening of
G_SECURE / G_SECRETS_SCAN.

Run:
    pytest skills/_meta/tests/test_security_scope.py -v

§9 cases exercised (verbatim from the design's BINDING scope-B):
  * security_scope: code-bearing -> sast+secrets; prose-only `_meta`.py -> STILL
    sast (NOT exempt — the key correction); binary -> neither; markdown ->
    secrets-only.
  * false-clean: malformed SARIF / non-zero exit / timeout -> SECURITY_INDETERMINATE
    (NOT clean, never zero findings).
  * N/A-cycle coverage: the checkpoint runs on an N/A->DONE-shaped diff.
  * advisory posture: a finding surfaces in the report + nudge, never blocks.
  * telemetry byte-invariance under forced ImportError.
  * NO_COMPATIBLE_TOOL grace vs scanner-error distinction.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

# --- make _meta importable -------------------------------------------------
_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import gates  # noqa: E402

_GATES_PY = _META / "gates.py"


# ===========================================================================
# Helpers
# ===========================================================================

def _git(args, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    )


def make_repo(tmp_path: Path) -> Path:
    """Create an initialized git repo with one committed baseline file so that
    subsequent writes show up as a real `git diff` / untracked set."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "t"], root)
    # baseline committed file (NOT in any later diff)
    (root / "README_BASE.md").write_text("base\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-q", "-m", "base"], root)
    return root


def write(root: Path, rel: str, content: str = "x\n", *, executable: bool = False) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    if executable:
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def write_bytes(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def run_g_security(cwd: Path, force_importerror: bool = False):
    """Invoke gates.py G_SECURITY as a subprocess. Returns (rc, stdout, stderr)."""
    cmd = [sys.executable, str(_GATES_PY), "G_SECURITY", str(cwd)]
    env = dict(os.environ)
    if force_importerror:
        env["GATES_TELEMETRY_FORCE_IMPORTERROR"] = "1"
    else:
        env.pop("GATES_TELEMETRY_FORCE_IMPORTERROR", None)
    proc = subprocess.run(cmd, cwd=str(cwd), env=env,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


# ===========================================================================
# security_scope() — git-diff-derived scope (§9 D1)
# ===========================================================================

def test_scope_code_bearing_in_both_sast_and_secrets(tmp_path):
    """A code-bearing changed file (.py) lands in BOTH sast and secrets scope."""
    root = make_repo(tmp_path)
    write(root, "src/app.py", "print('hi')\n")
    r = gates.security_scope(root)
    assert r["indeterminate"] is False
    assert "src/app.py" in r["sast"]
    assert "src/app.py" in r["secrets"]


def test_scope_prose_only_meta_py_still_gets_sast(tmp_path):
    """THE KEY CORRECTION: a prose-only `_meta`.py change is STILL in SAST scope.
    G_CLASSIFY exempts `_meta/*.py`, but security_scope MUST NOT — it derives
    from the git diff, and a .py is code regardless of what G_CLASSIFY thinks.
    """
    root = make_repo(tmp_path)
    write(root, "skills/_meta/some_helper.py", "# pure stdlib helper\nx = 1\n")
    r = gates.security_scope(root)
    assert "skills/_meta/some_helper.py" in r["sast"], (
        "prose-only _meta.py MUST be in SAST scope (NOT exempt) — the §9 "
        "critical correction over the G_CLASSIFY-scoping approach"
    )
    assert "skills/_meta/some_helper.py" in r["secrets"]


def test_scope_binary_in_neither(tmp_path):
    """A binary changed file is in NEITHER scope (text=no -> not secrets;
    no code signal -> not sast)."""
    root = make_repo(tmp_path)
    write_bytes(root, "assets/logo.png", b"\x89PNG\r\n\x00\x00binary\x00data")
    r = gates.security_scope(root)
    assert "assets/logo.png" not in r["secrets"]
    assert "assets/logo.png" not in r["sast"]


def test_scope_markdown_secrets_only(tmp_path):
    """A markdown (text, non-code) change is in secrets scope ONLY, not sast."""
    root = make_repo(tmp_path)
    write(root, "docs/notes.md", "# notes\nsome prose\n")
    r = gates.security_scope(root)
    assert "docs/notes.md" in r["secrets"]
    assert "docs/notes.md" not in r["sast"]


def test_scope_known_filename_dockerfile_is_code(tmp_path):
    root = make_repo(tmp_path)
    write(root, "Dockerfile", "FROM scratch\n")
    r = gates.security_scope(root)
    assert "Dockerfile" in r["sast"]


def test_scope_ci_yaml_is_code(tmp_path):
    root = make_repo(tmp_path)
    write(root, ".github/workflows/ci.yml", "name: ci\non: [push]\n")
    r = gates.security_scope(root)
    assert ".github/workflows/ci.yml" in r["sast"]


def test_scope_shebang_no_extension_is_code(tmp_path):
    root = make_repo(tmp_path)
    write(root, "bin/tool", "#!/usr/bin/env bash\necho hi\n")
    r = gates.security_scope(root)
    assert "bin/tool" in r["sast"]


def test_scope_executable_bit_is_code(tmp_path):
    root = make_repo(tmp_path)
    write(root, "bin/run", "echo no shebang but +x\n", executable=True)
    r = gates.security_scope(root)
    assert "bin/run" in r["sast"]


def test_scope_plain_yaml_not_code(tmp_path):
    """A non-CI yaml (config) is text (secrets) but NOT code (sast)."""
    root = make_repo(tmp_path)
    write(root, "config/settings.yaml", "key: value\n")
    r = gates.security_scope(root)
    assert "config/settings.yaml" in r["secrets"]
    assert "config/settings.yaml" not in r["sast"]


def test_scope_untracked_and_staged_both_collected(tmp_path):
    """The diff union must include untracked (new) AND staged files."""
    root = make_repo(tmp_path)
    write(root, "new_untracked.py", "x=1\n")          # untracked
    write(root, "staged.py", "y=2\n")
    _git(["add", "staged.py"], root)                   # staged
    r = gates.security_scope(root)
    assert "new_untracked.py" in r["sast"]
    assert "staged.py" in r["sast"]


def test_scope_failed_diff_collection_is_indeterminate(tmp_path):
    """A non-git directory (no repo) => diff collection fails => indeterminate
    scope (escalate, NOT a silent empty 'clean')."""
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    r = gates.security_scope(nogit)
    assert r["indeterminate"] is True
    assert r["reason"]
    assert r["sast"] == []
    assert r["secrets"] == []


def test_scope_is_pure_no_classify_dependency(tmp_path):
    """security_scope must NOT consult G_CLASSIFY. Proven indirectly: a repo
    with ONLY a prose markdown design doc (which G_CLASSIFY would call 'no')
    still yields a non-empty secrets scope from the diff."""
    root = make_repo(tmp_path)
    write(root, "docs/plans/x-design.md", "# prose design\nNo new components.\n")
    r = gates.security_scope(root)
    assert "docs/plans/x-design.md" in r["secrets"]
    assert r["indeterminate"] is False


# ===========================================================================
# D3 false-clean hardening — _g_secure_parse_sarif (pure)
# ===========================================================================

WELL_FORMED_SARIF_ZERO = (
    '{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"semgrep",'
    '"rules":[]}},"results":[]}]}'
)
WELL_FORMED_SARIF_ONE_HIGH = (
    '{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"semgrep",'
    '"rules":[{"id":"r1","defaultConfiguration":{"level":"error"}}]}},'
    '"results":[{"ruleId":"r1","level":"error"}]}]}'
)


def test_parse_sarif_wellformed_zero_is_ok_clean():
    status, count = gates._g_secure_parse_sarif(WELL_FORMED_SARIF_ZERO, "high")
    assert status == "ok"
    assert count == 0


def test_parse_sarif_wellformed_finding_counts():
    status, count = gates._g_secure_parse_sarif(WELL_FORMED_SARIF_ONE_HIGH, "high")
    assert status == "ok"
    assert count == 1


def test_parse_sarif_malformed_json_is_malformed_not_zero():
    """Malformed SARIF must NOT be silently treated as 0 findings/clean."""
    status, count = gates._g_secure_parse_sarif("{not valid json", "high")
    assert status == "malformed"
    assert count == 0  # the count is 0 but the STATUS flags it as not-clean


def test_parse_sarif_wrong_shape_is_malformed():
    """Valid JSON but not a SARIF object (no `runs` list) => malformed."""
    status, _ = gates._g_secure_parse_sarif('{"hello":"world"}', "high")
    assert status == "malformed"
    status2, _ = gates._g_secure_parse_sarif('[1,2,3]', "high")
    assert status2 == "malformed"


def test_parse_sarif_empty_is_empty_not_ok():
    """Empty output when output was expected => empty (a crashed scanner),
    NOT clean."""
    status, count = gates._g_secure_parse_sarif("", "high")
    assert status == "empty"
    status2, _ = gates._g_secure_parse_sarif("   \n  ", "high")
    assert status2 == "empty"


def test_legacy_count_helper_still_returns_zero_on_malformed():
    """Back-compat: the ORIGINAL helper is untouched (still returns 0 on
    malformed). The hardening is ADDITIVE via the new _g_secure_parse_sarif."""
    assert gates._g_secure_count_sarif_findings("{bad", "high") == 0
    assert gates._g_secure_count_sarif_findings(WELL_FORMED_SARIF_ONE_HIGH, "high") == 1


# ===========================================================================
# D3 false-clean hardening — check_G_SECURE / check_G_SECRETS_SCAN exit paths
# (monkeypatch subprocess + runner pick so no real scanner is needed)
# ===========================================================================

class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_g_secure_malformed_sarif_is_indeterminate(tmp_path, monkeypatch, capsys):
    """A semgrep run that exits 0 but emits malformed SARIF must surface
    SECURITY_INDETERMINATE (exit 0 advisory v1) — NOT a _PASS/clean line."""
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secure_pick_runner", lambda r, p: "semgrep")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeProc(0, "{garbage not sarif"))
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURE(root, mode="advisory", runner="semgrep", severity="high")
    assert ei.value.code == 0  # advisory v1 never blocks
    out = capsys.readouterr().out
    assert "SECURITY_INDETERMINATE" in out
    assert "_PASS" not in out


def test_g_secure_nonzero_exit_is_indeterminate(tmp_path, monkeypatch, capsys):
    """semgrep exiting >=2 (config/internal error) => SECURITY_INDETERMINATE,
    not clean, even if stdout happened to be empty."""
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secure_pick_runner", lambda r, p: "semgrep")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeProc(2, "", "boom"))
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURE(root, mode="advisory", runner="semgrep", severity="high")
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "SECURITY_INDETERMINATE" in out
    assert "_PASS" not in out


def test_g_secure_timeout_is_indeterminate(tmp_path, monkeypatch, capsys):
    """A scanner timeout => indeterminate (the scan never completed), NOT clean
    and NOT a missing-tool env error."""
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secure_pick_runner", lambda r, p: "bandit")

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="bandit", timeout=300)

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURE(root, mode="advisory", runner="bandit", severity="high")
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "SECURITY_INDETERMINATE" in out


def test_g_secure_empty_sarif_is_indeterminate(tmp_path, monkeypatch, capsys):
    """rc 0 but empty SARIF output (a killed/crashed scanner) => indeterminate."""
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secure_pick_runner", lambda r, p: "semgrep")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeProc(0, ""))
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURE(root, mode="advisory", runner="semgrep", severity="high")
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "SECURITY_INDETERMINATE" in out
    assert "_PASS" not in out


def test_g_secure_wellformed_zero_is_clean(tmp_path, monkeypatch, capsys):
    """rc 0 + well-formed SARIF with no findings => genuine clean _PASS."""
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secure_pick_runner", lambda r, p: "semgrep")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeProc(0, WELL_FORMED_SARIF_ZERO))
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURE(root, mode="advisory", runner="semgrep", severity="high")
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "G_SECURE_PASS" in out
    assert "SECURITY_INDETERMINATE" not in out


def test_g_secrets_scan_unexpected_rc_is_indeterminate(tmp_path, monkeypatch, capsys):
    """gitleaks exiting with an unexpected rc (>1) => SECURITY_INDETERMINATE,
    NOT the old env_error (which conflated it with no-tool)."""
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secrets_scan_pick_scanner",
                        lambda s, p: ("gitleaks", None))
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeProc(2, "", "internal error"))
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECRETS_SCAN(root, mode="advisory", scanner="gitleaks")
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "SECURITY_INDETERMINATE" in out
    assert "_PASS" not in out


def test_g_secrets_scan_timeout_is_indeterminate(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secrets_scan_pick_scanner",
                        lambda s, p: ("gitleaks", None))

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="gitleaks", timeout=120)

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECRETS_SCAN(root, mode="advisory", scanner="gitleaks")
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "SECURITY_INDETERMINATE" in out


def test_g_secrets_scan_clean_rc0_is_clean(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    monkeypatch.setattr(gates, "_g_secrets_scan_pick_scanner",
                        lambda s, p: ("gitleaks", None))
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeProc(0, ""))
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECRETS_SCAN(root, mode="advisory", scanner="gitleaks")
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "G_SECRETS_SCAN_PASS" in out


def test_no_compatible_tool_is_env_error_not_indeterminate(tmp_path, monkeypatch):
    """NO_COMPATIBLE_TOOL (no scanner installed) is the ONLY grace case: it
    exits 3 (env_error) so the orchestrator treats it as advisory-skip+nudge,
    distinct from a broken-run indeterminate."""
    root = make_repo(tmp_path)
    # force the picker to env_error (no scanner). G_SECURE picker calls
    # env_error -> exit 3.
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    # ensure no pyproject/py so bandit branch isn't taken before env_error
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURE(root, mode="advisory", runner="auto", severity="high")
    assert ei.value.code == 3  # env_error == NO_COMPATIBLE_TOOL grace


# ===========================================================================
# G_SECURITY orchestration — advisory posture + N/A-cycle coverage
# ===========================================================================

def test_g_security_runs_on_na_cycle_diff(tmp_path):
    """N/A-CYCLE COVERAGE: the checkpoint RUNS on an N/A->DONE-shaped diff
    (prose markdown + a _meta.py edit) and reports — never bypassed. Exit 0
    advisory regardless of which scanners exist."""
    root = make_repo(tmp_path)
    write(root, "docs/plans/x-design.md", "# prose\nNo new components.\n")
    write(root, "skills/_meta/helper.py", "x = 1\n")
    rc, out, err = run_g_security(root)
    assert rc == 0, f"advisory checkpoint must exit 0 on N/A cycle; got {rc}\n{err}"
    assert "G_SECURITY_ADVISORY:" in out
    # the _meta.py must have driven a SAST arm (run or no-tool), proving the
    # prose-only-_meta-still-gets-SAST correction end-to-end.
    assert '"sast":1' in out or '"sast": 1' in out


def test_g_security_failed_diff_escalates_not_silent(tmp_path):
    """A non-git dir => indeterminate scope => exit 3 escalate (NOT a silent
    exit-0 'clean')."""
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    rc, out, err = run_g_security(nogit)
    assert rc == 3, "failed-diff-collection must escalate (exit 3), not silent-skip"
    assert "could not derive security scope" in (out + err)


def test_g_security_empty_diff_is_clean_exit0(tmp_path):
    """A clean tree (no diff) => empty SAST scope, exit 0 advisory.

    Note: the S039 telemetry rider (main() bump) writes `.process-observations/`
    into the cwd on every gate run; a real project gitignores that, so we mirror
    that hygiene here. With it gitignored the diff is genuinely empty and the
    aggregate is clean.
    """
    root = make_repo(tmp_path)  # nothing changed since the base commit
    (root / ".gitignore").write_text(".process-observations/\n", encoding="utf-8")
    _git(["add", ".gitignore"], root)
    _git(["commit", "-q", "-m", "gitignore telemetry"], root)
    rc, out, err = run_g_security(root)
    assert rc == 0
    assert "G_SECURITY_ADVISORY:" in out
    assert '"aggregate":"clean"' in out
    # SAST scope is always empty on a no-code clean tree.
    assert '"sast":0' in out or '"sast": 0' in out


def test_g_security_empty_scope_in_process_is_clean(tmp_path):
    """Purest empty-diff check: security_scope() in-process (no subprocess
    telemetry self-write) yields a fully empty scope on a clean repo."""
    root = make_repo(tmp_path)
    r = gates.security_scope(root)
    assert r["indeterminate"] is False
    assert r["secrets"] == []
    assert r["sast"] == []


def test_g_security_advisory_finding_does_not_block(tmp_path, monkeypatch):
    """ADVISORY POSTURE: even when an inner arm reports findings, G_SECURITY
    exits 0 (report + nudge, never block in v1). Simulated by an inner gate
    that exits 0 with a non-PASS, non-INDETERMINATE stdout (advisory-findings
    shape)."""
    root = make_repo(tmp_path)
    write(root, "src/app.py", "x=1\n")

    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        # Intercept the inner G_SECURE / G_SECRETS_SCAN subprocess calls.
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[2] in (
            "G_SECURE", "G_SECRETS_SCAN"
        ):
            return _FakeProc(
                0,
                f"{cmd[2]}: findings detected (mode=advisory — not blocking)\n",
            )
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURITY(root)
    assert ei.value.code == 0  # advisory: a finding NEVER blocks in v1


def test_g_security_no_tool_arm_is_advisory_skip(tmp_path, monkeypatch):
    """An inner arm exiting 3 (NO_COMPATIBLE_TOOL) => normalized
    no_compatible_tool => advisory-skip + nudge, exit 0 (never block)."""
    root = make_repo(tmp_path)
    write(root, "src/app.py", "x=1\n")
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[2] == "G_SECURE":
            return _FakeProc(3, "", "no SAST runner found")
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[2] == "G_SECRETS_SCAN":
            return _FakeProc(0, "G_SECRETS_SCAN_PASS: clean\n")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURITY(root)
    assert ei.value.code == 0


def test_g_security_inner_indeterminate_is_advisory_not_clean(tmp_path, monkeypatch, capsys):
    """An inner arm emitting SECURITY_INDETERMINATE => aggregate
    advisory_indeterminate (NOT clean), still exit 0 advisory v1."""
    root = make_repo(tmp_path)
    write(root, "src/app.py", "x=1\n")
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[2] == "G_SECURE":
            return _FakeProc(0, "G_SECURE_SECURITY_INDETERMINATE: broken\n")
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[2] == "G_SECRETS_SCAN":
            return _FakeProc(0, "G_SECRETS_SCAN_PASS: clean\n")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as ei:
        gates.check_G_SECURITY(root)
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "advisory_indeterminate" in out


def test_g_security_report_has_no_raw_secret_material(tmp_path, monkeypatch, capsys):
    """SANITIZED: the G_SECURITY aggregate must NOT echo raw matched secret
    material even if an inner scanner leaked some into stdout — only the first
    bounded summary line is kept, and finding bodies are not surfaced."""
    root = make_repo(tmp_path)
    write(root, "config.txt", "x\n")
    real_run = subprocess.run
    leaked = "AKIAIOSFODNN7EXAMPLE_super_secret_value_should_not_appear"

    def fake_run(cmd, *a, **k):
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[2] == "G_SECRETS_SCAN":
            # An (improperly) un-redacted scanner dumping a secret on line 2+.
            return _FakeProc(
                0,
                "G_SECRETS_SCAN: findings detected (mode=advisory)\n"
                f"  match: {leaked}\n",
            )
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[2] == "G_SECURE":
            return _FakeProc(0, "G_SECURE_PASS: clean\n")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        gates.check_G_SECURITY(root)
    out = capsys.readouterr().out
    assert leaked not in out, (
        "raw matched secret material must NEVER appear in the G_SECURITY report"
    )


# ===========================================================================
# Telemetry byte-invariance (§9: security_scope is pure; gates ride S039)
# ===========================================================================

def test_g_security_telemetry_byte_invariance(tmp_path):
    """G_SECURITY exit code + stdout must be byte-identical with and without the
    process-observation backend (forced ImportError). Proves the S039
    telemetry rider does not perturb the gate."""
    root = make_repo(tmp_path)
    write(root, "docs/x.md", "# prose\n")
    write(root, "skills/_meta/h.py", "x=1\n")
    rc_a, out_a, _ = run_g_security(root, force_importerror=False)
    rc_b, out_b, _ = run_g_security(root, force_importerror=True)
    assert rc_a == rc_b
    assert out_a == out_b, "telemetry ImportError must not change G_SECURITY stdout"
