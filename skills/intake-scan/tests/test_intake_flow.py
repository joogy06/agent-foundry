#!/usr/bin/env python3
"""intake-scan -- test_intake_flow.py (#350 WP-8).

The three flows the contract map declares, each run end to end through the real
components, from the declared entry input to the declared terminal output. Only these
three: nothing here is derived from a call graph.

    flow-intake-scan          intake-cli -> intake-fetch -> harness-rules ->
                              scanner-adapters -> scan-sandbox -> intake-policy
                              entry: a scan request; terminal: the verdict record
    flow-commit-enforcement   precommit-intake-arm -> harness-rules
                              entry: a staged change; terminal: the hook exit code
    flow-install-enforcement  install-intake-check -> harness-rules
                              entry: an install source; terminal: the install exit code

What each flow must show (the map's expected_outcome):

    scan      a benign skill yields pass or caution with a complete record; a block-rule
              fixture yields block; nothing from the target is executed
    commit    an unexcepted hit or an unledgered new unit exits non-zero; a clean change
              exits 0
    install   an unexcepted hit stops the install in every placement mode

The scan flow runs twice. Once on every host, with no sandbox and no toolchain, where the
same path must fail closed (a skill is never a pass when its required scanner did not
run). Once with the installed toolchain inside bwrap, skipped with the reason stated where
either is absent. The commit flow is a real `git commit` in a throwaway repo whose own
.git/hooks/pre-commit runs the hook from its source file; the unit tests call the hook
directly, this one checks that the commit itself lands or does not. The install flow is
install.py's main() against a temp source tree and a throwaway --claude-home.

Every repo, source tree, quarantine, tool root and home here is a temp directory. Nothing
under the real home, no .git/hooks of this checkout and no file of this repo is written,
and no test reaches the network. A sample that trips a rule is BUILT AT TEST TIME from
pieces, so this file holds no hit of its own.

Stdlib unittest; pytest only runs it.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURES = HERE / "fixtures"
REPO = HERE.parents[2]
HOOK = REPO / "skills" / "secret-scanning" / "hooks" / "pre_commit.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import adapters  # noqa: E402
import intake  # noqa: E402
import intake_ledger as il  # noqa: E402
import intake_policy as ip  # noqa: E402
from adapters import deps as deps_adapter  # noqa: E402

# The scaffolding of the two enforcement suites: a temp source tree for install.py and the
# list of files a throwaway repo needs for the hook. Neither class has a test of its own.
from test_install_check import I, SourceCase  # noqa: E402
from test_precommit_arm import VENDORED  # noqa: E402

GIT = shutil.which("git")
POSIX = os.name == "posix"

LEDGER_REL = "skills/_meta/intake-ledger.json"
OVERRIDES_REL = "intake/overrides.jsonl"
ZERO_WIDTH = chr(0x200B)
HIDDEN = "# Notes\n\nPlain" + ZERO_WIDTH + " prose.\n"
PLAIN = "# Notes\n\nPlain prose.\n"
T0 = "2026-10-11T12:00:00Z"
SCANNERS = ("harness-rules", "secrets-catalog", "skillspector", "bandit", "deps")

SKILL_MD = (b"---\nname: sample\ndescription: Sample skill that formats tables.\n---\n\n"
            b"# Sample\n\nPlain prose.\n")


def _sample(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _live_reason():
    toolchain = adapters.sibling("toolchain")
    sandbox = adapters.sibling("sandbox")
    try:
        if not toolchain.all_ok(toolchain.check()):
            return "the pinned toolchain is not installed at %s" % toolchain.default_root()
    except toolchain.ToolchainError as exc:
        return "the toolchain pins are unreadable (%s)" % exc
    if sandbox.isolation()[1] is None:
        return "bwrap is absent or cannot build a sandbox on this host"
    return None


LIVE_SKIP = _live_reason()


# --------------------------------------------------------------------------------------
# flow-intake-scan
# --------------------------------------------------------------------------------------

class ScanFlowCase(unittest.TestCase):
    """A temp repo root with an empty ledger, a temp quarantine and an EMPTY temp tool root.

    The entry input is the fixture's scan request with its placeholder target replaced by
    a folder built here. Every Python file of the target writes a marker file when it is
    run or imported, so a scan that executed any of them leaves the marker behind."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="scan-flow-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "repo"
        self.q = self.tmp / "quarantine"
        self.tools = self.tmp / "tools"
        self.marker = self.tmp / "target-code-ran"
        self.root.mkdir()
        self.tools.mkdir()
        il.save(str(self.root), il.empty())
        # A tripwire in place of the advisory lookup: no test may reach the network.
        self.lookups = []
        patcher = mock.patch.object(deps_adapter, "osv_lookup", self._no_network)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: self.assertEqual(self.lookups, [], "a test tried the advisory service"))

    def _no_network(self, *_args, **_kwargs):
        def lookup(deps):
            self.lookups.append(len(deps))
            raise OSError("no network in tests")
        return lookup

    # -- the target ------------------------------------------------------------------

    def target(self, extra=None) -> Path:
        """A small skill folder. Its Python files are harmless, and each one would write
        the marker file if anything ran or imported it."""
        code = ("from pathlib import Path\n"
                "Path(%r).write_text('ran')\n" % str(self.marker)).encode("ascii")
        files = {"SKILL.md": (SKILL_MD, 0o644),
                 "scripts/tool.py": (b"#!/usr/bin/env python3\n" + code, 0o755),
                 "conftest.py": (code, 0o644),
                 "setup.py": (code, 0o644)}
        for rel, data in (extra or {}).items():
            files[rel] = (data, 0o644)
        src = self.tmp / "sample-skill"
        for rel, (data, mode) in files.items():
            path = src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            os.chmod(path, mode)
        return src

    def snapshot(self, src: Path) -> dict:
        return {str(p.relative_to(src)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(src.rglob("*")) if p.is_file()}

    # -- the request -----------------------------------------------------------------

    def request(self, does: str, src: Path) -> list:
        """The fixture's argv for `does`, with the placeholder target replaced."""
        wanted = [r for r in _sample("scan-request-sample.json")["requests"] if r["does"] == does]
        self.assertEqual(len(wanted), 1, does)
        argv = list(wanted[0]["argv"])
        self.assertEqual(argv[:2], ["scan", "downloads/sample-skill"])
        argv[1] = str(src)
        return argv

    def scan(self, argv: list, tool_root: bool = True) -> tuple:
        args = list(argv) + ["--root", str(self.root), "--quarantine-root", str(self.q)]
        if tool_root:
            args += ["--tool-root", str(self.tools)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = intake.main(args)
        return code, out.getvalue()

    # -- the terminal output ---------------------------------------------------------

    def only_bundle(self) -> Path:
        held = sorted(p for p in self.q.iterdir() if p.is_dir()) if self.q.exists() else []
        self.assertEqual(len(held), 1, [p.name for p in held])
        return held[0]

    def complete_record(self, src: Path) -> dict:
        """The one record of the one scan, checked against what each step of the flow left:
        the fetch's bundle and inventory, every scanner's row, the policy's verdict."""
        bundle = self.only_bundle()
        self.assertEqual(sorted(os.listdir(bundle)),
                         ["inventory.json", "record.json", "source.tar", "triage.md"])
        record = json.loads((bundle / "record.json").read_text(encoding="utf-8"))
        inventory = json.loads((bundle / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(ip.validate_record(record), [])
        self.assertEqual(record["id"], bundle.name)
        self.assertIn(record["verdict"], ip.VERDICTS)
        self.assertTrue(record["reasons"] or record["verdict"] == "pass")
        self.assertEqual(record["subject"]["kind"], "skill")
        self.assertEqual(record["subject"]["source"]["type"], "folder")
        # intake-fetch -> the record: the same tree and the same inventory.
        self.assertEqual(record["subject"]["tree_digest"], inventory["tree_digest"])
        self.assertEqual(record["inventory_digest"], inventory["inventory_digest"])
        count = len(self.snapshot(src))
        self.assertEqual(record["coverage"]["files"], {"entries": count, "stored": count, "omitted": 0})
        # every scanner has a row, whether it ran or not.
        self.assertEqual(sorted(row["scanner"] for row in record["coverage"]["scanners"]), sorted(SCANNERS))
        gaps = {g["gap"] for g in record["gaps"]}
        self.assertFalse(gaps & {"scan-incomplete", "evidence-malformed", "internal-error"}, gaps)
        return record

    def states(self, record: dict) -> dict:
        return {row["scanner"]: row["state"] for row in record["coverage"]["scanners"]}


class ScanFlowWithoutSandboxTests(ScanFlowCase):
    """flow-intake-scan on a host with no sandbox and no toolchain: the path completes,
    writes a complete record, and fails closed."""

    DOES = "act as a host with no sandbox: third-party scanners are not run"

    def test_flow_intake_scan_a_benign_skill_is_never_a_pass_when_its_scanner_did_not_run(self) -> None:
        src = self.target()
        before = self.snapshot(src)
        code, out = self.scan(self.request(self.DOES, src))
        record = self.complete_record(src)
        self.assertEqual((code, record["verdict"]), (2, "block"))
        self.assertIn("required-scanner-gap", record["reasons"])
        self.assertNotIn("block-rule-hit", record["reasons"])
        self.assertEqual(record["counts"]["findings"]["block"], 0)
        states = self.states(record)
        self.assertEqual((states["harness-rules"], states["secrets-catalog"]), ("ran", "ran"))
        self.assertEqual(states["skillspector"], "not-run")
        self.assertIn("verdict: block", out.splitlines())
        self.assertFalse(self.marker.exists(), "the scan ran code of the target")
        self.assertEqual(self.snapshot(src), before)

    def test_flow_intake_scan_a_block_rule_fixture_is_a_block_by_the_rule(self) -> None:
        src = self.target({"references/notes.md": HIDDEN.encode("utf-8")})
        code, out = self.scan(self.request(self.DOES, src))
        record = self.complete_record(src)
        self.assertEqual((code, record["verdict"]), (2, "block"))
        self.assertIn("block-rule-hit", record["reasons"])
        hits = [f for f in record["findings"] if f["class"] == "block"]
        self.assertEqual([(f["rule"], f["scanner"], f["line"]) for f in hits], [("H1", "harness-rules", 3)])
        self.assertNotIn(ZERO_WIDTH, out)
        self.assertNotIn("notes.md", out)
        self.assertFalse(self.marker.exists(), "the scan ran code of the target")


@unittest.skipIf(LIVE_SKIP is not None, "flow-intake-scan with the real scanners skipped: %s" % LIVE_SKIP)
class ScanFlowTests(ScanFlowCase):
    """flow-intake-scan with the installed scanners inside bwrap. Offline; the quarantine
    and the repo root are still temp directories."""

    DOES = "scan with no network: the advisory lookup is a named gap"

    def test_flow_intake_scan_a_benign_skill_is_a_pass_or_a_caution_with_a_complete_record(self) -> None:
        src = self.target()
        before = self.snapshot(src)
        code, out = self.scan(self.request(self.DOES, src), tool_root=False)
        record = self.complete_record(src)
        self.assertIn(record["verdict"], ("pass", "caution"), (record["reasons"], record["gaps"]))
        self.assertEqual(code, ip.exit_code(record["verdict"]))
        self.assertIn("verdict: %s" % record["verdict"], out.splitlines())
        self.assertEqual(record["counts"]["findings"]["block"], 0)
        self.assertEqual([g["gap"] for g in record["gaps"] if g["effect"] == "block"], [])
        # scanner-adapters -> scan-sandbox: both third-party scanners ran, inside bwrap.
        rows = {row["scanner"]: (row["state"], row["isolation"]) for row in record["coverage"]["scanners"]}
        self.assertEqual(rows["skillspector"], ("ran", "bwrap"), record["gaps"])
        self.assertEqual(rows["bandit"], ("ran", "bwrap"), record["gaps"])
        self.assertEqual(rows["harness-rules"][0], "ran")
        self.assertEqual(rows["secrets-catalog"][0], "ran")
        self.assertEqual(record["isolation"], "bwrap")
        self.assertEqual(record["coverage"]["uncovered"], [])
        self.assertFalse(self.marker.exists(), "the scan ran code of the target")
        self.assertEqual(self.snapshot(src), before)

    def test_flow_intake_scan_a_block_rule_fixture_is_a_block(self) -> None:
        src = self.target({"references/notes.md": HIDDEN.encode("utf-8")})
        code, out = self.scan(self.request(self.DOES, src), tool_root=False)
        record = self.complete_record(src)
        self.assertEqual((code, record["verdict"]), (2, "block"))
        self.assertIn("block-rule-hit", record["reasons"])
        self.assertNotIn("required-scanner-gap", record["reasons"])
        hits = [f for f in record["findings"] if f["class"] == "block"]
        self.assertEqual([(f["rule"], f["scanner"], f["line"]) for f in hits], [("H1", "harness-rules", 3)])
        # the scanners still ran: a block hit does not cut the flow short.
        states = self.states(record)
        self.assertEqual((states["skillspector"], states["bandit"]), ("ran", "ran"), record["gaps"])
        self.assertEqual(record["isolation"], "bwrap")
        self.assertNotIn(ZERO_WIDTH, out)
        self.assertFalse(self.marker.exists(), "the scan ran code of the target")


# --------------------------------------------------------------------------------------
# flow-commit-enforcement
# --------------------------------------------------------------------------------------

@unittest.skipUnless(GIT and POSIX, "needs git and a POSIX hook file")
class CommitFlowTests(unittest.TestCase):
    """A throwaway repo that tracks an intake ledger and has the hook installed in ITS OWN
    .git/hooks. The terminal output is the hook's exit code as git acts on it: the commit
    lands or it does not."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="commit-flow-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.home = self.tmp / "empty-home"
        self.repo.mkdir()
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=str(self.home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        for rel in VENDORED:
            dst = self.repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dst)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "commit flow")
        self.git("config", "commit.gpgsign", "false")
        self.write("README.md", "baseline\n")
        il.save(str(self.repo), il.empty())
        self.git("add", "--", "README.md", LEDGER_REL)
        self.git("commit", "-qm", "baseline")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text('#!/bin/sh\nexec "%s" "%s"\n' % (sys.executable, HOOK), encoding="utf-8")
        os.chmod(hook, 0o755)

    # -- helpers ---------------------------------------------------------------------

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(self.repo), env=self.env,
                              capture_output=True, text=True, check=check)

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def add(self, rel: str, text: str) -> None:
        self.write(rel, text)
        self.git("add", "--", rel)

    def enter(self, unit: str) -> None:
        il.add_entry(str(self.repo), unit, kind="skill", record_id="u-test-" + "0" * 12,
                     digest="0" * 64, verdict="pass", unsigned_caution=False, origin="local", now=T0)
        self.git("add", "--", LEDGER_REL)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def commit(self) -> tuple:
        """Try the commit. Returns (hook exit code as git reports it, output, landed)."""
        before = self.head()
        done = self.git("commit", "-qm", "change", check=False)
        return done.returncode, (done.stdout or "") + (done.stderr or ""), self.head() != before

    def stage_sample(self) -> dict:
        sample = _sample("staged-change-sample.json")
        for change in sample["changes"]:
            self.add(change["path"], change["text"])
        return sample

    # -- the flow --------------------------------------------------------------------

    def test_flow_commit_enforcement_a_new_unit_without_an_entry_does_not_land(self) -> None:
        sample = self.stage_sample()
        code, out, landed = self.commit()
        self.assertEqual(code, sample["expect"]["exit"], out)
        self.assertFalse(landed, out)
        self.assertIn("BLOCKED", out)
        self.assertIn("no intake ledger entry", out)
        for unit in sample["expect"]["units_without_entry"]:
            self.assertIn(unit, out)

    def test_flow_commit_enforcement_the_same_change_with_its_entry_lands(self) -> None:
        sample = self.stage_sample()
        for unit in sample["expect"]["units_without_entry"]:
            self.enter(unit)
        code, out, landed = self.commit()
        self.assertEqual(code, 0, out)
        self.assertTrue(landed, out)
        self.assertNotIn("BLOCKED", out)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=no").stdout, "")

    def test_flow_commit_enforcement_an_unexcepted_hit_does_not_land(self) -> None:
        sample = self.stage_sample()
        for unit in sample["expect"]["units_without_entry"]:
            self.enter(unit)
        rel = "skills/sample-skill/references/notes.md"
        self.add(rel, HIDDEN)
        code, out, landed = self.commit()
        self.assertNotEqual(code, 0, out)
        self.assertFalse(landed, out)
        self.assertIn("BLOCKED", out)
        self.assertIn("block-rule hit", out)
        self.assertIn("H1", out)
        self.assertIn(rel + ":3", out)
        self.assertNotIn(ZERO_WIDTH, out)
        self.assertNotIn("no intake ledger entry", out)

    def test_flow_commit_enforcement_the_hit_lands_once_fixed_or_excepted(self) -> None:
        sample = self.stage_sample()
        for unit in sample["expect"]["units_without_entry"]:
            self.enter(unit)
        rel = "skills/sample-skill/references/notes.md"
        self.add(rel, HIDDEN)
        self.assertFalse(self.commit()[2])
        il.add_exception(str(self.repo), "H1", rel, reason="a documented example character", now=T0)
        self.git("add", "--", LEDGER_REL, OVERRIDES_REL)
        code, out, landed = self.commit()
        self.assertEqual((code, landed), (0, True), out)
        # the exception is bound to the file's content: one more line and it is refused again.
        self.add(rel, HIDDEN + "\nOne more line.\n")
        code, out, landed = self.commit()
        self.assertNotEqual(code, 0, out)
        self.assertFalse(landed, out)
        self.add(rel, PLAIN)
        code, out, landed = self.commit()
        self.assertEqual((code, landed), (0, True), out)


# --------------------------------------------------------------------------------------
# flow-install-enforcement
# --------------------------------------------------------------------------------------

class InstallFlowTests(SourceCase):
    """install.py's main() on a temp source tree built from the install-source fixture.
    The terminal output is the install exit code, and whether anything was placed."""

    MODES = ("link", "move", "mc")
    REL = "skills/sample-skill/references/notes.md"

    def test_flow_install_enforcement_the_clean_source_installs(self) -> None:
        sample = _sample("install-source-sample.json")
        code, out = self.install("--mode", "link")
        self.assertEqual(code, sample["expect"]["exit"], out)
        self.assertNotIn("REFUSING", out)
        self.assertTrue((self.home / "skills" / "sample-skill").exists())

    def test_flow_install_enforcement_an_unexcepted_hit_stops_every_placement_mode(self) -> None:
        self.write(self.REL, HIDDEN)
        for mode in self.MODES:
            for extra in ((), ("--dry-run",)):
                with self.subTest(mode=mode, dry_run=bool(extra)):
                    code, out = self.install("--mode", mode, *extra)
                    self.assertEqual(code, I.EXIT_INTAKE_REFUSED, out)
                    self.assertIn("would be REFUSED" if extra else "REFUSING to install", out)
                    self.assertIn("H1  " + self.REL + ":3", out)
                    self.assertNotIn(ZERO_WIDTH, out)
                    self.assertEqual(self.placed(), [])

    def test_flow_install_enforcement_the_refusal_is_the_rule_not_the_mode(self) -> None:
        # the same tree, refused then let through, with nothing changed but the hit.
        self.write(self.REL, HIDDEN)
        code, out = self.install("--mode", "link")
        self.assertEqual(code, I.EXIT_INTAKE_REFUSED, out)
        self.assertEqual(self.placed(), [])
        il.add_exception(str(self.repo), "H1", self.REL, reason="a documented example character", now=T0)
        code, out = self.install("--mode", "link")
        self.assertEqual(code, 0, out)
        self.assertIn("exceptions in force: 1", out)
        self.assertTrue((self.home / "skills" / "sample-skill").exists())

    def test_flow_install_enforcement_a_unit_without_an_entry_stops_every_placement_mode(self) -> None:
        self.write("skills/new-skill/SKILL.md", "---\nname: new-skill\ndescription: New.\n---\n\n# New\n")
        for mode in self.MODES:
            with self.subTest(mode=mode):
                code, out = self.install("--mode", mode)
                self.assertEqual(code, I.EXIT_INTAKE_REFUSED, out)
                self.assertIn("units with no ledger entry: 1", out)
                self.assertEqual(self.placed(), [])


if __name__ == "__main__":
    unittest.main()
