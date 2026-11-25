#!/usr/bin/env python3
"""intake-scan -- test_sandbox.py (#350 WP-3).

The bwrap sandbox third-party scanners run in. Two things are proved:

    TS-SBX-01  under the built argv a stand-in process cannot reach the network and cannot
               read the real home directory (nor the repo, nor the host /tmp)
    TS-SBX-02  with bwrap forced absent NOTHING is run: isolation none and a named gap

The stand-in is the system interpreter running a few lines written here. No third-party
scanner and no network are needed: "the network" is a listener this test opens on the
loopback interface of the host, which a process outside the sandbox can reach and a
process inside it cannot.

The tests that start bwrap are skipped, with the reason, on a host where it is absent or
cannot build a namespace. The argv tests and TS-SBX-02 run everywhere. Nothing is written
under the real home.

Stdlib unittest; pytest only runs it.
"""
from __future__ import annotations

import ast
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURES = HERE / "fixtures"
REPO = HERE.parents[2]
sys.path.insert(0, str(SCRIPTS))

import sandbox  # noqa: E402

ISOLATION, BWRAP, WHY_NOT = sandbox.isolation()
NEEDS_BWRAP = unittest.skipUnless(
    BWRAP is not None, "bwrap is absent or cannot build a sandbox on this host (%s)" % WHY_NOT)
PYTHON = "/usr/bin/python3"

# What the stand-in does inside the sandbox. It writes what it saw to /out/seen.json.
STAND_IN = r'''
import json, os, socket, sys
host, port, home, marker, repo = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
seen = {}
try:
    socket.create_connection((host, port), timeout=3).close()
    seen["network"] = "connected"
except OSError as exc:
    seen["network"] = "refused:" + type(exc).__name__
try:
    seen["home"] = "listed:%d" % len(os.listdir(home))
except OSError as exc:
    seen["home"] = "absent:" + type(exc).__name__
seen["home_dirs"] = sorted(os.listdir("/home"))
seen["marker"] = os.path.exists(marker)
seen["repo"] = os.path.exists(repo)
seen["target"] = open("/target/note.txt", encoding="utf-8").read()
try:
    open("/target/new.txt", "w").close()
    seen["target_write"] = "written"
except OSError as exc:
    seen["target_write"] = "refused:" + type(exc).__name__
seen["env"] = dict(os.environ)
seen["processes"] = len([p for p in os.listdir("/proc") if p.isdigit()])
with open("/out/seen.json", "w", encoding="utf-8") as fh:
    json.dump(seen, fh)
'''


class SandboxCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="intake-sbx-test-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.target = self.tmp / "target"
        self.work = self.tmp / "work"
        self.target.mkdir()
        self.work.mkdir()
        (self.target / "note.txt").write_text("target note\n", encoding="utf-8")

    def request(self, *argv, **changes):
        base = sandbox.SandboxRequest(tuple(argv), str(self.target), str(self.work), None, None, 60)
        return base._replace(**changes)


class ArgvTests(SandboxCase):
    """The command line itself, without starting anything."""

    def build(self, **changes):
        request = self.request(PYTHON, "-c", "pass", **changes)
        return sandbox.build_argv("/usr/bin/bwrap", request, str(self.work / "out")), request

    def test_namespaces_session_and_environment_are_cut(self):
        argv, _ = self.build()
        for flag in ("--unshare-all", "--die-with-parent", "--new-session", "--clearenv"):
            self.assertIn(flag, argv)
        self.assertNotIn("--share-net", argv)

    def test_only_usr_toolchain_target_and_out_are_bound(self):
        tools = self.tmp / "venv"
        conf = self.tmp / "conf"
        tools.mkdir()
        conf.mkdir()
        argv, _ = self.build(toolchain_dir=str(tools), conf_dir=str(conf))
        read_only = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == "--ro-bind"]
        writable = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == "--bind"]
        self.assertEqual(writable, [(str(self.work / "out"), "/out")])
        self.assertIn(("/usr", "/usr"), read_only)
        self.assertIn((str(tools), "/tools/venv"), read_only)
        self.assertIn((str(conf), "/conf"), read_only)
        self.assertIn((str(self.target), "/target"), read_only)
        allowed_hosts = {"/usr", str(tools), str(conf), str(self.target)} | {
            "/" + name for name in sandbox._USR_ALIASES}
        self.assertLessEqual({host for host, _ in read_only}, allowed_hosts)
        self.assertNotIn("--dev-bind", argv)

    def test_real_home_and_repo_are_never_bound(self):
        argv, _ = self.build()
        home = os.path.expanduser("~")
        bound = [argv[i + 1] for i, a in enumerate(argv) if a in ("--ro-bind", "--bind")]
        for host in bound:
            inside = host.rstrip("/") + "/"
            self.assertFalse(home == host or home.startswith(inside),
                             "the real home is reachable through %s" % host)
            self.assertFalse(str(REPO) == host or str(REPO).startswith(inside),
                             "the repo is reachable through %s" % host)
        self.assertIn("--tmpfs", argv)
        tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
        self.assertEqual(sorted(tmpfs), ["/home/sandbox", "/tmp"])

    def test_environment_is_ours_and_holds_no_key(self):
        argv, _ = self.build()
        names = [argv[i + 1] for i, a in enumerate(argv) if a == "--setenv"]
        self.assertEqual(names, [name for name, _ in sandbox.SANDBOX_ENV])
        for name in names:
            for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PROXY", "SKILLSPECTOR", "API"):
                self.assertNotIn(word, name.upper())
        values = dict(sandbox.SANDBOX_ENV)
        self.assertEqual(values["HOME"], "/home/sandbox")
        self.assertEqual(values["PATH"], "/usr/bin")

    def test_scanner_command_comes_last_and_unchanged(self):
        argv, request = self.build()
        split = argv.index("--")
        self.assertEqual(tuple(argv[split + 1:]), request.argv)
        self.assertEqual(argv[split - 2:split], ["--chdir", "/out"])


class Ts_Sbx_01_ContainmentTests(SandboxCase):
    """TS-SBX-01: the stand-in cannot reach the network or read the real home."""

    def run_stand_in(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        host, port = listener.getsockname()
        # Control: outside the sandbox the same connection succeeds.
        socket.create_connection((host, port), timeout=3).close()
        marker = self.tmp / "host-marker.txt"
        marker.write_text("visible on the host only\n", encoding="utf-8")
        home = os.path.expanduser("~")
        self.assertTrue(os.path.isdir(home))
        with mock.patch.dict(os.environ, {"SAMPLE_PROVIDER_API_KEY": "placeholder-not-a-key",
                                          "SKILLSPECTOR_PROVIDER": "placeholder"}):
            result = sandbox.run(self.request(PYTHON, "-c", STAND_IN, host, str(port), home,
                                              str(marker), str(REPO)))
        self.assertEqual((result.isolation, result.ran, result.gap), (sandbox.ISOLATION_BWRAP, True, None),
                         Path(result.stderr_path).read_text(encoding="utf-8") if result.stderr_path else "")
        self.assertEqual(result.exit_status, 0, Path(result.stderr_path).read_text(encoding="utf-8"))
        with open(os.path.join(result.out_dir, "seen.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)

    @NEEDS_BWRAP
    def test_cannot_reach_the_network(self):
        seen = self.run_stand_in()
        self.assertTrue(seen["network"].startswith("refused:"), seen["network"])

    @NEEDS_BWRAP
    def test_cannot_read_the_real_home_the_repo_or_the_host_tmp(self):
        seen = self.run_stand_in()
        self.assertTrue(seen["home"].startswith("absent:") or seen["home"] == "listed:0", seen["home"])
        self.assertEqual(seen["home_dirs"], ["sandbox"])
        self.assertFalse(seen["marker"])
        self.assertFalse(seen["repo"])

    @NEEDS_BWRAP
    def test_target_is_readable_and_read_only_and_out_is_writable(self):
        seen = self.run_stand_in()
        self.assertEqual(seen["target"], "target note\n")
        self.assertTrue(seen["target_write"].startswith("refused:"), seen["target_write"])
        self.assertFalse((self.target / "new.txt").exists())

    @NEEDS_BWRAP
    def test_environment_is_cleared(self):
        seen = self.run_stand_in()
        self.assertNotIn("SAMPLE_PROVIDER_API_KEY", seen["env"])
        self.assertNotIn("SKILLSPECTOR_PROVIDER", seen["env"])
        self.assertLessEqual(set(seen["env"]), {name for name, _ in sandbox.SANDBOX_ENV} | {"PWD"})

    @NEEDS_BWRAP
    def test_sees_no_host_process(self):
        seen = self.run_stand_in()
        self.assertLessEqual(seen["processes"], 3)


class RunTests(SandboxCase):

    @NEEDS_BWRAP
    def test_exit_status_is_passed_through_as_evidence(self):
        result = sandbox.run(self.request(PYTHON, "-c", "import sys; print('out'); sys.exit(7)"))
        self.assertEqual((result.ran, result.exit_status, result.timed_out, result.gap), (True, 7, False, None))
        self.assertEqual(Path(result.stdout_path).read_text(encoding="utf-8"), "out\n")

    @NEEDS_BWRAP
    def test_timeout_is_a_named_gap(self):
        result = sandbox.run(self.request("/usr/bin/sleep", "30", timeout_s=1))
        self.assertEqual((result.ran, result.timed_out, result.exit_status, result.gap),
                         (True, True, None, sandbox.GAP_TIMEOUT))
        self.assertLess(result.duration_s, 15)

    @NEEDS_BWRAP
    def test_a_missing_path_in_the_request_runs_nothing(self):
        for request in (self.request(PYTHON, "-c", "pass", target_dir=str(self.tmp / "absent")),
                        self.request(PYTHON, "-c", "pass", toolchain_dir=str(self.tmp / "absent")),
                        self.request(PYTHON, "-c", "pass", target_dir="relative/path"),
                        self.request()):
            result = sandbox.run(request)
            self.assertEqual((result.ran, result.gap), (False, sandbox.GAP_BAD_REQUEST))


class Ts_Sbx_02_NoBwrapTests(SandboxCase):
    """TS-SBX-02: bwrap forced absent yields isolation none and a gap, and runs nothing."""

    def marker_request(self):
        self.marker = self.tmp / "ran.txt"
        code = "open(%r, 'w').close()" % str(self.marker)
        return self.request(sys.executable, "-c", code)

    def assert_nothing_ran(self, result, gap):
        self.assertEqual(result.isolation, sandbox.ISOLATION_NONE)
        self.assertFalse(result.ran)
        self.assertEqual(result.gap, gap)
        self.assertIsNone(result.exit_status)
        self.assertIsNone(result.out_dir)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.work / "out").exists())

    def test_forced_by_argument(self):
        self.assert_nothing_ran(sandbox.run(self.marker_request(), force_none=True), sandbox.GAP_UNAVAILABLE)

    def test_forced_by_argument_even_when_a_bwrap_path_is_given(self):
        result = sandbox.run(self.marker_request(), force_none=True, bwrap="/usr/bin/bwrap")
        self.assert_nothing_ran(result, sandbox.GAP_UNAVAILABLE)

    def test_forced_by_environment(self):
        with mock.patch.dict(os.environ, {sandbox.FORCE_ENV: "none"}):
            self.assertIsNone(sandbox.find_bwrap())
            self.assert_nothing_ran(sandbox.run(self.marker_request()), sandbox.GAP_UNAVAILABLE)

    def test_absent_on_a_non_posix_host(self):
        with mock.patch.object(sandbox.os, "name", "nt"):
            self.assertIsNone(sandbox.find_bwrap())
            self.assertEqual(sandbox.isolation(), (sandbox.ISOLATION_NONE, None, sandbox.GAP_UNAVAILABLE))

    def test_absent_when_no_binary_is_found(self):
        with mock.patch.object(sandbox, "find_bwrap", return_value=None):
            self.assert_nothing_ran(sandbox.run(self.marker_request()), sandbox.GAP_UNAVAILABLE)

    @unittest.skipUnless(os.path.exists("/usr/bin/false"), "needs /usr/bin/false as a bwrap that cannot start")
    def test_a_bwrap_that_cannot_build_a_sandbox_is_unusable(self):
        with mock.patch.object(sandbox, "find_bwrap", return_value="/usr/bin/false"), \
                mock.patch.dict(sandbox._PROBE_CACHE, {}, clear=True):
            self.assertEqual(sandbox.isolation(), (sandbox.ISOLATION_NONE, None, sandbox.GAP_UNUSABLE))
            self.assert_nothing_ran(sandbox.run(self.marker_request()), sandbox.GAP_UNUSABLE)

    def test_there_is_no_unsandboxed_fallback_in_the_source(self):
        tree = ast.parse((SCRIPTS / "sandbox.py").read_text(encoding="utf-8"))
        starts = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr in ("Popen", "run", "call",
                                                                                  "check_output", "check_call")
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"]
        # One start for the probe and one for the scanner; both are given the bwrap argv.
        self.assertEqual(len(starts), 2)
        for node in starts:
            self.assertEqual(ast.unparse(node.args[0]), "argv")


class ShapeTests(unittest.TestCase):

    def test_result_sample_matches_the_result_type(self):
        with open(FIXTURES / "sandbox-result-sample.json", "r", encoding="utf-8") as fh:
            sample = json.load(fh)
        for row in sample["results"]:
            self.assertEqual(sorted(row), sorted(sandbox.SandboxResult._fields))
            self.assertIn(row["isolation"], (sandbox.ISOLATION_BWRAP, sandbox.ISOLATION_NONE))
            if row["gap"] is not None:
                self.assertIn(row["gap"], sandbox.GAPS)
            self.assertEqual(sandbox.SandboxResult(**row).to_dict(), row)

    def test_request_sample_matches_the_request_type(self):
        with open(FIXTURES / "sandbox-request-sample.json", "r", encoding="utf-8") as fh:
            sample = json.load(fh)
        fields = {name: sample[name] for name in sandbox.SandboxRequest._fields}
        request = sandbox.SandboxRequest(**fields)._replace(argv=tuple(sample["argv"]))
        argv = sandbox.build_argv("/usr/bin/bwrap", request, "/placeholder/work/out")
        self.assertEqual(argv[argv.index("--") + 1:], sample["argv"])
        self.assertEqual(sample["in_sandbox"], {"target": sandbox.TARGET, "toolchain": sandbox.TOOLS,
                                                "out": sandbox.OUT, "conf": sandbox.CONF,
                                                "home": sandbox.HOME})

    def test_gap_descriptions_are_fixed_ascii_text(self):
        for name, text in sandbox.GAPS.items():
            self.assertRegex(name, r"^[a-z][a-z-]+$")
            self.assertTrue(text.isascii() and text)

    def test_module_is_ascii_and_imports_only_the_standard_library(self):
        source = (SCRIPTS / "sandbox.py").read_bytes()
        self.assertTrue(source.isascii())
        imported = set()
        for node in ast.walk(ast.parse(source.decode("ascii"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, set(sys.stdlib_module_names) | {"__future__"})


if __name__ == "__main__":
    unittest.main()
