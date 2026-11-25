#!/usr/bin/env python3
"""intake-scan -- test_intake_fetch.py (#350 WP-1).

Safe acquisition: a git URL, a folder or a zip becomes one quarantined tar plus an
inventory, and nothing from the target is checked out, built or executed.

Every hostile target (a repository with export attributes, a submodule, an LFS pointer and
a link out of the tree; archives with traversal, links, devices, colliding names, nested
archives and a bomb) is BUILT AT TEST TIME in a temp directory. Nothing hostile is tracked.

No test touches the network: repositories are local and are cloned over file://, which the
module accepts only through its explicit test-only parameter. The https-only rule is tested
by argument construction and by refusals that never start git. No test writes under the
real home: every fetch is given a quarantine root inside the test's temp directory.

Stdlib unittest; pytest only runs it.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import harness_rules as hr  # noqa: E402
import intake_fetch as fetch_mod  # noqa: E402

HAVE_GIT = shutil.which("git") is not None
POSIX = os.name == "posix"
FILE_ONLY = ("file",)

# A pointer file in the large-file-storage format, assembled so that no tracked file
# starts with it.
LFS_POINTER = ("version https://git-lfs.github.com/spec/v1\n"
               "oid sha256:" + "ab" * 32 + "\nsize 123456\n").encode("ascii")
SUBST_TEXT = b"$Format:%H$\n"
OUTSIDE_MARKER = b"OUTSIDE-THE-TREE-MARKER-7f3a"

GIT_BUILD_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


def git(repo, *args, data=None):
    """Run git while BUILDING a fixture repository (never the module under test)."""
    done = subprocess.run(["git", *args], cwd=str(repo), env=GIT_BUILD_ENV, input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return done.stdout.decode("utf-8", "replace").strip()


def tar_members(tar_path):
    with tarfile.open(tar_path, "r:") as tar:
        return {m.name: (m, tar.extractfile(m).read() if m.isreg() else None) for m in tar}


def rows_by_path(inventory):
    return {row["path"]: row for row in inventory["files"]}


def subcommand(argv):
    """The git subcommand of an argv built by the module (after -c pairs and --git-dir)."""
    i = 1
    while i < len(argv):
        if argv[i] in ("-c", "--git-dir"):
            i += 2
            continue
        return argv[i]
    return ""


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="intake-fetch-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.root = self.tmp / "quarantine"

    def fetch(self, target, **kwargs):
        kwargs.setdefault("quarantine_root", str(self.root))
        return fetch_mod.fetch(str(target), **kwargs)

    def assert_nothing_left(self):
        """A failed fetch leaves no bundle and no staging directory."""
        left = sorted(os.listdir(self.root)) if self.root.exists() else []
        self.assertEqual(left, [])

    def assert_gap(self, result, name):
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.gap)
        self.assertEqual(result.gap["gap"], name, result.gap)
        self.assertIsNone(result.bundle_dir)
        self.assertIsNone(result.inventory)
        self.assert_nothing_left()

    def assert_bundle(self, result):
        self.assertTrue(result.ok, result.gap)
        self.assertIsNone(result.gap)
        self.assertEqual(sorted(os.listdir(result.bundle_dir)), ["inventory.json", "source.tar"])
        self.assertEqual(os.listdir(self.root), [result.bundle_id])
        if POSIX:
            self.assertEqual(stat.S_IMODE(os.stat(result.tar_path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(result.inventory_path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(result.bundle_dir).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(self.root).st_mode), 0o700)
        self.assertEqual(fetch_mod.load_inventory(result.bundle_dir), result.inventory)
        for member, _data in tar_members(result.tar_path).values():
            self.assertTrue(member.isreg(), member.name)


# --------------------------------------------------------------------------------------
# Git
# --------------------------------------------------------------------------------------

@unittest.skipUnless(HAVE_GIT, "git is not installed")
class GitBase(Base):

    def make_repo(self, name="src"):
        repo = self.tmp / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        return repo

    def write(self, repo, rel, data, executable=False):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if executable:
            path.chmod(0o755)

    def commit(self, repo, message="commit"):
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", message)
        return git(repo, "rev-parse", "HEAD")

    def add_blob_as(self, repo, mode, data, path):
        oid = git(repo, "hash-object", "-w", "--stdin", data=data)
        git(repo, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, oid, path))

    def git_fetch(self, repo, **kwargs):
        kwargs.setdefault("test_only_protocols", FILE_ONLY)
        return self.fetch(Path(repo).resolve().as_uri(), **kwargs)


class GitExportTests(GitBase):

    def test_export_attributes_have_no_effect_on_the_exported_bytes(self):
        """TS-FETCH-01."""
        repo = self.make_repo()
        attributes = b"secret.txt export-ignore\nversion.txt export-subst\ndocs export-ignore\n"
        self.write(repo, ".gitattributes", attributes)
        self.write(repo, "secret.txt", b"kept\n")
        self.write(repo, "version.txt", SUBST_TEXT)
        self.write(repo, "docs/guide.md", b"# guide\n")
        self.write(repo, "scripts/run.sh", b"#!/bin/sh\necho hi\n", executable=True)
        commit = self.commit(repo)

        # The fixture is effective: an archive export WOULD drop and rewrite these files.
        archived = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=str(repo),
                                  env=GIT_BUILD_ENV, stdout=subprocess.PIPE, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archived)) as tar:
            names = set(tar.getnames())
            substituted = tar.extractfile("version.txt").read()
        self.assertNotIn("secret.txt", names)
        self.assertNotIn("docs/guide.md", names)
        self.assertNotEqual(substituted, SUBST_TEXT)

        result = self.git_fetch(repo)
        self.assert_bundle(result)
        members = tar_members(result.tar_path)
        expected = {
            ".gitattributes": attributes,
            "docs/guide.md": b"# guide\n",
            "scripts/run.sh": b"#!/bin/sh\necho hi\n",
            "secret.txt": b"kept\n",
            "version.txt": SUBST_TEXT,
        }
        self.assertEqual({name: data for name, (_m, data) in members.items()}, expected)
        self.assertEqual(members["scripts/run.sh"][0].mode, 0o755)
        self.assertEqual(members["secret.txt"][0].mode, 0o644)

        inventory = result.inventory
        self.assertEqual(inventory["schema"], "intake-inventory.v1")
        self.assertEqual(inventory["source"]["type"], "git")
        self.assertEqual(inventory["source"]["commit"], commit)
        self.assertEqual(inventory["source"]["git_tree"], git(repo, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(inventory["omissions"], [])
        self.assertEqual(inventory["counts"], {"entries": 5, "stored": 5, "omitted": 0,
                                               "stored_bytes": sum(len(v) for v in expected.values())})
        rows = rows_by_path(inventory)
        for path, data in expected.items():
            self.assertEqual(rows[path]["sha256"], hr.sha256_hex(data))
            self.assertEqual(rows[path]["size"], len(data))
            self.assertTrue(rows[path]["stored"])
            self.assertEqual(rows[path]["entry"], "file")
        self.assertEqual(rows["scripts/run.sh"]["mode"], "0755")
        self.assertEqual(rows["version.txt"]["mode"], "0644")
        self.assertEqual([row["id"] for row in inventory["files"]],
                         [hr.make_file_id(i) for i in range(1, 6)])

    def test_no_checkout_hook_filter_or_smudge_runs(self):
        marker = self.tmp / "ran.marker"
        trap = self.tmp / "trap-home"
        hooks = trap / "hooks"
        hooks.mkdir(parents=True)
        touch = 'sh -c "echo ran >> %s"' % marker
        for hook in ("post-checkout", "post-merge", "reference-transaction", "pre-auto-gc", "post-index-change"):
            (hooks / hook).write_text("#!/bin/sh\necho ran >> %s\n" % marker, encoding="utf-8")
            (hooks / hook).chmod(0o755)
        config = trap / ".gitconfig"
        config.write_text(
            "[core]\n\thooksPath = %s\n\tfsmonitor = %s\n"
            "[filter \"lfs\"]\n\tsmudge = %s\n\tclean = %s\n\tprocess = %s\n\trequired = true\n"
            "[filter \"trap\"]\n\tsmudge = %s\n\tclean = %s\n"
            "[init]\n\ttemplateDir = %s\n"
            "[submodule]\n\trecurse = true\n"
            % (hooks, touch, touch, touch, touch, touch, touch, trap), encoding="utf-8")

        repo = self.make_repo()
        self.write(repo, ".gitattributes", b"*.bin filter=lfs diff=lfs merge=lfs -text\n*.txt filter=trap\n")
        self.write(repo, "big.bin", LFS_POINTER)
        self.write(repo, "note.txt", b"plain\n")
        self.commit(repo)
        (repo / ".git" / "hooks" / "post-checkout").write_text(
            "#!/bin/sh\necho ran >> %s\n" % marker, encoding="utf-8")
        (repo / ".git" / "hooks" / "post-checkout").chmod(0o755)

        # The traps are live: an ordinary clone under this configuration DOES run them.
        naive_env = dict(GIT_BUILD_ENV, HOME=str(trap), GIT_CONFIG_GLOBAL=str(config), GIT_ALLOW_PROTOCOL="file")
        subprocess.run(["git", "clone", "-q", repo.resolve().as_uri(), str(self.tmp / "naive")],
                       env=naive_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        self.assertTrue(marker.exists(), "the trap configuration did not fire on an ordinary clone")
        marker.unlink()

        calls = []
        real_spawn = fetch_mod._spawn

        def spy(argv, **kwargs):
            calls.append((list(argv), dict(kwargs.get("env") or {}), kwargs.get("cwd")))
            return real_spawn(argv, **kwargs)

        hostile_env = {
            "HOME": str(trap), "XDG_CONFIG_HOME": str(trap), "GIT_CONFIG_GLOBAL": str(config),
            "GIT_DIR": str(self.tmp / "bogus.git"), "GIT_WORK_TREE": str(self.tmp / "bogus-tree"),
            "GIT_INDEX_FILE": str(self.tmp / "bogus-index"), "GIT_TEMPLATE_DIR": str(trap),
            "GIT_ALLOW_PROTOCOL": "file:ext:ssh", "GIT_SSH_COMMAND": touch, "GIT_ASKPASS": str(hooks / "post-checkout"),
            "GIT_EXTERNAL_DIFF": touch, "GIT_PAGER": touch,
        }
        with mock.patch.dict(os.environ, hostile_env), mock.patch.object(fetch_mod, "_spawn", spy):
            result = self.git_fetch(repo)

        self.assert_bundle(result)
        self.assertFalse(marker.exists(), "something from the target or the caller's git config ran")
        self.assertFalse((self.tmp / "bogus.git").exists())
        self.assertFalse((self.tmp / "bogus-tree").exists())

        # Only raw object commands ran, and exactly one command touched the remote.
        used = [subcommand(argv) for argv, _env, _cwd in calls]
        self.assertEqual(used[0], "clone")
        self.assertEqual(used.count("clone"), 1)
        self.assertLessEqual(set(used), {"clone", "rev-parse", "ls-tree", "cat-file"})
        clone_argv = calls[0][0]
        self.assertIn("--bare", clone_argv)
        for argv, env, cwd in calls:
            words = argv[argv.index(subcommand(argv)):]
            banned = {"checkout", "archive", "submodule", "worktree", "lfs", "--filters", "--textconv",
                      "--recurse-submodules", "reset", "switch", "restore", "--local", "--shared"}
            self.assertEqual(banned & set(words), set())
            self.assertEqual(env.get("GIT_CONFIG_GLOBAL"), os.devnull)
            self.assertEqual(env.get("GIT_CONFIG_NOSYSTEM"), "1")
            self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
            self.assertEqual(env.get("GIT_LFS_SKIP_SMUDGE"), "1")
            for inherited in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_TEMPLATE_DIR",
                              "GIT_ALLOW_PROTOCOL", "GIT_SSH_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_PAGER"):
                self.assertNotIn(inherited, env)
            self.assertNotEqual(env.get("HOME"), str(trap))
            self.assertEqual(env.get("GIT_ASKPASS"), "")
            self.assertTrue(str(cwd).startswith(str(self.root)))
            self.assertIn("core.hooksPath=" + os.devnull, argv)

        # The pointer came out as the pointer: no smudge, no clean, no fetch of the object.
        members = tar_members(result.tar_path)
        self.assertEqual(members["big.bin"][1], LFS_POINTER)
        self.assertEqual(members["note.txt"][1], b"plain\n")
        self.assertTrue(rows_by_path(result.inventory)["big.bin"]["lfs_pointer"])
        # No clone, work tree or scratch file survives the fetch.
        self.assertEqual(sorted(os.listdir(result.bundle_dir)), ["inventory.json", "source.tar"])

    def test_submodule_lfs_pointer_and_symlink_are_recorded_and_never_followed(self):
        outside = self.tmp / "outside.txt"
        outside.write_bytes(OUTSIDE_MARKER)
        sub = self.make_repo("sub-origin")
        self.write(sub, "inner.txt", b"inner " + OUTSIDE_MARKER)
        sub_commit = self.commit(sub)

        repo = self.make_repo()
        self.write(repo, "README.md", b"# readme\n")
        self.write(repo, ".gitmodules",
                   ('[submodule "dep"]\n\tpath = dep\n\turl = %s\n' % sub.resolve().as_uri()).encode("utf-8"))
        self.write(repo, "model.bin", LFS_POINTER)
        git(repo, "add", "-A")
        git(repo, "update-index", "--add", "--cacheinfo", "160000,%s,dep" % sub_commit)
        self.add_blob_as(repo, "120000", b"../outside.txt", "escape")
        self.add_blob_as(repo, "120000", b"README.md", "docs/inside")
        git(repo, "commit", "-q", "-m", "hostile")

        calls = []
        real_spawn = fetch_mod._spawn

        def spy(argv, **kwargs):
            calls.append(list(argv))
            return real_spawn(argv, **kwargs)

        with mock.patch.object(fetch_mod, "_spawn", spy):
            result = self.git_fetch(repo)
        self.assert_bundle(result)
        self.assertEqual([subcommand(a) for a in calls].count("clone"), 1)
        self.assertNotIn(sub.resolve().as_uri(), " ".join(" ".join(a) for a in calls))

        rows = rows_by_path(result.inventory)
        self.assertEqual(rows["dep"]["entry"], "gitlink")
        self.assertEqual(rows["dep"]["gitlink_commit"], sub_commit)
        self.assertFalse(rows["dep"]["stored"])
        self.assertEqual(rows["dep"]["omitted"], "submodule-not-fetched")
        self.assertEqual(rows["escape"]["entry"], "symlink")
        self.assertFalse(rows["escape"]["stored"])
        self.assertEqual(rows["escape"]["omitted"], "symlink-not-followed")
        self.assertEqual(rows["escape"]["link_target"], "../outside.txt")
        self.assertTrue(rows["escape"]["link_escapes"])
        self.assertFalse(rows["docs/inside"]["link_escapes"])
        self.assertTrue(rows["model.bin"]["stored"])
        self.assertTrue(rows["model.bin"]["lfs_pointer"])
        self.assertEqual(
            sorted((o["path"], o["reason"]) for o in result.inventory["omissions"]),
            [("dep", "submodule-not-fetched"), ("docs/inside", "symlink-not-followed"),
             ("escape", "symlink-not-followed")])

        members = tar_members(result.tar_path)
        self.assertEqual(sorted(members), [".gitmodules", "README.md", "model.bin"])
        self.assertEqual(members["model.bin"][1], LFS_POINTER)
        self.assertNotIn(OUTSIDE_MARKER, Path(result.tar_path).read_bytes())

        # The rule set sees every one of them through the bundle entries.
        entries = list(fetch_mod.iter_bundle_entries(result.bundle_dir))
        records = [hr.FileRecord(*entry) for entry in entries]
        by_id = {r.file_id: r.path for r in records}
        hits = {by_id[f.file_id] for f in hr.scan_blocks(records, hr.KIND_REPO) if f.rule_id == "H7"}
        self.assertEqual(hits, {".gitmodules", "dep", "docs/inside", "escape", "model.bin"})

    def test_a_tree_with_a_traversal_name_is_refused(self):
        repo = self.make_repo()
        blob = git(repo, "hash-object", "-w", "--stdin", data=b"x\n")
        raw_tree = b"100644 ..\x00" + bytes.fromhex(blob)
        tree = git(repo, "hash-object", "-t", "tree", "-w", "--stdin", "--literally", data=raw_tree)
        commit = git(repo, "commit-tree", tree, "-m", "crafted")
        git(repo, "update-ref", "refs/heads/main", commit)
        result = self.git_fetch(repo)
        self.assert_gap(result, "git-clone-failed")

    def test_case_colliding_and_oversize_blobs_are_recorded_not_stored(self):
        repo = self.make_repo()
        self.write(repo, "keep.txt", b"keep\n")
        self.write(repo, "big.dat", b"0123456789" * 30)
        git(repo, "add", "-A")
        self.add_blob_as(repo, "100644", b"upper\n", "Docs/Note.txt")
        self.add_blob_as(repo, "100644", b"lower\n", "docs/other.txt")
        if POSIX:
            oid = git(repo, "hash-object", "-w", "--stdin", data=b"odd name\n")
            subprocess.run([b"git", b"update-index", b"--add", b"--cacheinfo",
                            b"100644," + oid.encode("ascii") + b",odd-\xff.txt"],
                           cwd=str(repo), env=GIT_BUILD_ENV, check=True)
        git(repo, "commit", "-q", "-m", "collide")
        limits = fetch_mod.DEFAULT_LIMITS._replace(max_file_bytes=100)
        result = self.git_fetch(repo, limits=limits)
        self.assert_bundle(result)
        rows = rows_by_path(result.inventory)
        self.assertTrue(rows["Docs/Note.txt"]["stored"])
        self.assertFalse(rows["docs/other.txt"]["stored"])
        self.assertEqual(rows["docs/other.txt"]["omitted"], "case-colliding-name")
        self.assertEqual(rows["docs/other.txt"]["sha256"], hr.sha256_hex(b"lower\n"))
        self.assertEqual(rows["big.dat"]["omitted"], "file-over-size-cap")
        self.assertEqual(rows["big.dat"]["size"], 300)
        self.assertEqual(rows["big.dat"]["sha256"], hr.sha256_hex(b"0123456789" * 30))
        self.assertEqual(sorted(tar_members(result.tar_path)), ["Docs/Note.txt", "keep.txt"])
        if POSIX:
            odd = [row for row in result.inventory["files"] if row.get("omitted") == "path-not-utf8"]
            self.assertEqual(len(odd), 1)
            self.assertTrue(odd[0]["path"].isascii())
            self.assertIn("xff", odd[0]["path"])
            self.assertEqual(odd[0]["sha256"], hr.sha256_hex(b"odd name\n"))

        entries = {e.path: e for e in fetch_mod.iter_bundle_entries(result.bundle_dir)}
        self.assertEqual((entries["big.dat"].entry, entries["big.dat"].size, entries["big.dat"].data),
                         ("file", 300, b""))
        self.assertEqual(entries["docs/other.txt"].entry, "other")
        self.assertIsNone(entries["keep.txt"].size)
        self.assertEqual(entries["keep.txt"].data, b"keep\n")

    def test_caps_on_entry_count_and_total_size_are_named_gaps(self):
        repo = self.make_repo()
        for index in range(6):
            self.write(repo, "f%d.txt" % index, b"x" * 50)
        self.commit(repo)
        result = self.git_fetch(repo, limits=fetch_mod.DEFAULT_LIMITS._replace(max_files=5))
        self.assert_gap(result, "over-cap")
        self.assertEqual(result.gap["reasons"], ["too-many-entries"])
        result = self.git_fetch(repo, limits=fetch_mod.DEFAULT_LIMITS._replace(max_total_bytes=299))
        self.assert_gap(result, "over-cap")
        self.assertEqual(result.gap["reasons"], ["total-over-size-cap"])

    def test_ref_selects_a_branch_a_tag_or_a_commit(self):
        repo = self.make_repo()
        self.write(repo, "a.txt", b"one\n")
        first = self.commit(repo, "one")
        git(repo, "tag", "v1")
        self.write(repo, "a.txt", b"two\n")
        second = self.commit(repo, "two")
        git(repo, "branch", "side", first)

        def content(**kwargs):
            result = self.git_fetch(repo, **kwargs)
            self.assertTrue(result.ok, result.gap)
            data = tar_members(result.tar_path)["a.txt"][1]
            commit = result.inventory["source"]["commit"]
            fetch_mod.remove_bundle(result.bundle_dir)
            return data, commit

        self.assertEqual(content(), (b"two\n", second))
        self.assertEqual(content(ref="v1"), (b"one\n", first))
        self.assertEqual(content(ref="side"), (b"one\n", first))
        self.assertEqual(content(ref=first), (b"one\n", first))
        self.assertEqual(content(ref=first[:10]), (b"one\n", first))
        self.assert_nothing_left()
        self.assert_gap(self.git_fetch(repo, ref="no-such-branch"), "git-clone-failed")
        self.assert_gap(self.git_fetch(repo, ref="abcdef0123"), "git-ref-not-found")
        for bad in ("--upload-pack=x", "a..b", "a b", "-x", "x/", ""):
            self.assert_gap(self.git_fetch(repo, ref=bad), "ref-not-accepted")

    def test_an_empty_repository_is_a_named_gap(self):
        repo = self.make_repo()
        self.assert_gap(self.git_fetch(repo), "git-ref-not-found")


class GitRefusalTests(Base):

    def test_clone_command_is_bare_https_only_and_isolated(self):
        argv = fetch_mod.git_clone_argv("https://example.invalid/o/r.git", "/dest")
        self.assertEqual(argv[-3:], ["--", "https://example.invalid/o/r.git", "/dest"])
        self.assertEqual(subcommand(argv), "clone")
        for flag in ("--bare", "--no-recurse-submodules", "--template=", "--no-tags", "--single-branch"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--depth") + 1], "1")
        settings = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
        for setting in ("protocol.allow=never", "protocol.https.allow=always",
                        "core.hooksPath=" + os.devnull, "submodule.recurse=false",
                        "fetch.recurseSubmodules=false", "filter.lfs.smudge=", "filter.lfs.process=",
                        "filter.lfs.clean=", "filter.lfs.required=false", "credential.helper=",
                        "core.fsmonitor=false", "transfer.fsckObjects=true"):
            self.assertIn(setting, settings)
        allowed = [s for s in settings if s.startswith("protocol.") and s.endswith(".allow=always")]
        self.assertEqual(allowed, ["protocol.https.allow=always"])
        self.assertEqual(fetch_mod.ALLOWED_PROTOCOLS, ("https",))
        # A commit id is resolved after the clone; a name is asked for by name.
        self.assertNotIn("--branch", fetch_mod.git_clone_argv("https://example.invalid/r", "/d", "abcdef0"))
        named = fetch_mod.git_clone_argv("https://example.invalid/r", "/d", "v1.0")
        self.assertEqual(named[named.index("--branch") + 1], "v1.0")

    def test_git_environment_is_built_from_nothing(self):
        with mock.patch.dict(os.environ, {"GIT_DIR": "/x", "GIT_CONFIG_GLOBAL": "/y", "GIT_SSH_COMMAND": "z"}):
            env = fetch_mod.git_env("/empty-home")
        self.assertEqual(env["HOME"], "/empty-home")
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["GIT_CONFIG_SYSTEM"], os.devnull)
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_SSH_COMMAND", env)

    def test_any_protocol_but_https_is_refused_before_git_starts(self):
        started = []

        def spy(argv, **kwargs):
            started.append(argv)
            raise AssertionError("git must not start for a refused target")

        targets = [
            "http://example.invalid/o/r.git",
            "git://example.invalid/o/r.git",
            "ssh://git@example.invalid/o/r.git",
            "git@example.invalid:o/r.git",
            "example.invalid:o/r.git",
            "file:///srv/repos/r.git",
            "ftp://example.invalid/r.git",
            "ext::sh -c true",
            "https::example.invalid/r",
        ]
        with mock.patch.object(fetch_mod, "_spawn", spy):
            for target in targets:
                with self.subTest(target=target):
                    self.assertEqual(fetch_mod.classify_target(target), "git")
                    self.assert_gap(self.fetch(target), "protocol-not-allowed")
            for target in ("https://user:pw@example.invalid/r.git", "https://exa mple.invalid/r",
                           "https:///r.git", "https://example.invalid:port/r", "https://example.invalid/r\x7f"):
                with self.subTest(target=target):
                    self.assert_gap(self.fetch(target), "url-not-accepted")
        self.assertEqual(started, [])

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_an_unreachable_repository_is_a_named_gap_not_an_exception(self):
        missing = (self.tmp / "no-such-repo.git").as_uri()
        result = self.fetch(missing, test_only_protocols=FILE_ONLY)
        self.assert_gap(result, "git-clone-failed")
        self.assertFalse(result.gap["internal"])
        self.assertIn("diagnostic", result.gap)
        self.assertTrue(result.gap["diagnostic"].isascii())

    def test_a_missing_git_executable_is_a_named_gap(self):
        with mock.patch.object(fetch_mod, "GIT", str(self.tmp / "no-git-here")):
            result = self.fetch("https://example.invalid/o/r.git")
        self.assert_gap(result, "git-unavailable")

    def _stand_in(self, body):
        script = self.tmp / "stand-in-git"
        script.write_text("#!%s\nimport os, sys, time\n%s\n" % (sys.executable, body), encoding="utf-8")
        script.chmod(0o755)
        return str(script)

    @unittest.skipUnless(POSIX, "needs an executable script")
    def test_a_clone_that_does_not_finish_is_stopped_and_named(self):
        slow = self._stand_in("time.sleep(60)")
        limits = fetch_mod.DEFAULT_LIMITS._replace(clone_timeout_s=0.5)
        with mock.patch.object(fetch_mod, "GIT", slow):
            result = self.fetch("https://example.invalid/o/r.git", limits=limits)
        self.assert_gap(result, "git-clone-timeout")

    @unittest.skipUnless(POSIX, "needs an executable script")
    def test_a_clone_that_grows_past_the_size_cap_is_stopped_and_named(self):
        greedy = self._stand_in(
            "dest = sys.argv[-1]\nos.makedirs(dest, exist_ok=True)\n"
            "open(os.path.join(dest, 'pack'), 'wb').write(b'0' * 200000)\ntime.sleep(60)")
        limits = fetch_mod.DEFAULT_LIMITS._replace(max_clone_bytes=100000, clone_timeout_s=30)
        with mock.patch.object(fetch_mod, "GIT", greedy):
            result = self.fetch("https://example.invalid/o/r.git", limits=limits)
        self.assert_gap(result, "git-clone-over-size-cap")

    def test_the_target_ref_fixture_classifies_as_documented(self):
        sample = json.loads((FIXTURES / "target-ref-sample.json").read_text(encoding="utf-8"))
        for item in sample["accepted"]:
            if item["source_type"] == "git":
                self.assertEqual(fetch_mod.classify_target(item["target"]), "git")
                self.assertEqual(fetch_mod.target_scheme(item["target"]), "https")
                fetch_mod._check_url(item["target"], fetch_mod.ALLOWED_PROTOCOLS)
        with mock.patch.object(fetch_mod, "_spawn", side_effect=AssertionError("git must not start")):
            for item in sample["refused"]:
                with self.subTest(target=item["target"]):
                    self.assert_gap(self.fetch(str(self.tmp / item["target"])
                                               if "://" not in item["target"] else item["target"]),
                                    item["gap"])


# --------------------------------------------------------------------------------------
# Folder
# --------------------------------------------------------------------------------------

class FolderTests(Base):

    def make_folder(self):
        folder = self.tmp / "skill"
        (folder / "scripts").mkdir(parents=True)
        (folder / "SKILL.md").write_bytes(b"# skill\n")
        (folder / "scripts" / "tool.py").write_bytes(b"print('hi')\n")
        (folder / "scripts" / "tool.py").chmod(0o755)
        (folder / "SKILL.md").chmod(0o644)
        return folder

    def test_a_folder_becomes_a_bundle(self):
        folder = self.make_folder()
        (folder / ".git").mkdir()
        (folder / ".git" / "config").write_bytes(b"[core]\n")
        (folder / "sub" / ".git").mkdir(parents=True)
        (folder / "sub" / ".git" / "HEAD").write_bytes(b"ref: x\n")
        result = self.fetch(folder)
        self.assert_bundle(result)
        members = tar_members(result.tar_path)
        # Fix round 1, F1: the nested version-control directory is recorded and not stored.
        self.assertEqual(sorted(members), ["SKILL.md", "scripts/tool.py"])
        self.assertEqual(members["scripts/tool.py"][1], b"print('hi')\n")
        inventory = result.inventory
        self.assertEqual(inventory["source"], {"type": "folder", "target": str(folder), "ref": None,
                                               "commit": None, "git_tree": None})
        self.assertEqual(inventory["omissions"],
                         [{"path": "sub/.git", "entry": "other", "reason": "vcs-control-path"},
                          {"path": ".git", "entry": "directory", "reason": "vcs-directory-skipped"}])
        if POSIX:
            self.assertEqual(members["scripts/tool.py"][0].mode, 0o755)
            self.assertEqual(rows_by_path(inventory)["scripts/tool.py"]["mode"], "0755")
        self.assertEqual(self.fetch(folder, ref="main").gap["gap"], "ref-not-accepted")

    def test_version_control_directories_and_pointer_files_are_never_stored(self):
        """Fix round 1, F1. Git honours the config of a directory named .git as soon as it is
        started inside it, so none is stored, at any depth, under any casing."""
        folder = self.make_folder()
        hostile = b"[core]\n\tfsmonitor = \"touch MARKER; false\"\n"
        for rel in ("sub/.git/config", "sub/.git/HEAD", "deep/er/.GIT/config", "hg/.hg/hgrc", "svn/.svn/entries"):
            path = folder / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(hostile)
        (folder / "worktree").mkdir()
        (folder / "worktree" / ".git").write_bytes(b"gitdir: ../sub/.git\n")
        (folder / ".gitignore").write_bytes(b"*.pyc\n")
        result = self.fetch(folder)
        self.assert_bundle(result)
        self.assertEqual(sorted(tar_members(result.tar_path)), [".gitignore", "SKILL.md", "scripts/tool.py"])
        rows = rows_by_path(result.inventory)
        for path in ("sub/.git", "deep/er/.GIT", "hg/.hg", "svn/.svn", "worktree/.git"):
            self.assertEqual((rows[path]["stored"], rows[path]["omitted"]), (False, "vcs-control-path"), path)
        self.assertNotIn("sub/.git/config", rows)              # the directory is not walked
        # Every one comes back as a non-file entry, so the rule set blocks without reading it.
        entries = {e.path: e for e in fetch_mod.iter_bundle_entries(result.bundle_dir)}
        records = [hr.FileRecord(*e) for e in entries.values()]
        hits = {entries_path for entries_path, e in entries.items()
                for f in hr.scan_blocks([hr.FileRecord(*e)]) if f.rule_id == "H7"}
        self.assertEqual(sorted(hits), ["deep/er/.GIT", "hg/.hg", "sub/.git", "svn/.svn", "worktree/.git"])
        self.assertEqual(len(records), len(rows))

    @unittest.skipUnless(hasattr(os, "symlink") and POSIX, "needs symlinks")
    def test_a_symlink_out_of_the_tree_is_recorded_and_never_read(self):
        folder = self.make_folder()
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(OUTSIDE_MARKER)
        os.symlink(str(outside / "secret.txt"), str(folder / "abs-link"))
        os.symlink("../outside/secret.txt", str(folder / "rel-link"))
        os.symlink(str(outside), str(folder / "dir-link"))
        os.symlink("SKILL.md", str(folder / "scripts" / "dangling-or-inside"))
        result = self.fetch(folder)
        self.assert_bundle(result)
        self.assertNotIn(OUTSIDE_MARKER, Path(result.tar_path).read_bytes())
        self.assertEqual(sorted(tar_members(result.tar_path)), ["SKILL.md", "scripts/tool.py"])
        rows = rows_by_path(result.inventory)
        for name in ("abs-link", "rel-link", "dir-link"):
            self.assertEqual(rows[name]["entry"], "symlink")
            self.assertEqual(rows[name]["omitted"], "symlink-not-followed")
            self.assertFalse(rows[name]["stored"])
            self.assertTrue(rows[name]["link_escapes"], name)
        self.assertFalse(rows["scripts/dangling-or-inside"]["link_escapes"])
        self.assertNotIn("dir-link/secret.txt", rows)
        self.assertEqual(rows["rel-link"]["link_target"], "../outside/secret.txt")
        entries = {e.path: e for e in fetch_mod.iter_bundle_entries(result.bundle_dir)}
        self.assertEqual(entries["abs-link"].entry, hr.ENTRY_SYMLINK)
        self.assertEqual(entries["abs-link"].data, b"")

    @unittest.skipUnless(POSIX, "needs a file system that stores raw byte names")
    def test_a_name_that_is_not_utf8_is_recorded_and_not_stored(self):
        folder = self.make_folder()
        try:
            with open(os.fsencode(str(folder)) + b"/odd-\xff.txt", "wb") as fh:
                fh.write(b"odd name\n")
            os.mkdir(os.fsencode(str(folder)) + b"/dir-\xfe")
        except OSError:
            self.skipTest("this file system refuses names that are not UTF-8")
        result = self.fetch(folder)
        self.assert_bundle(result)
        odd = sorted((row["entry"], row["stored"]) for row in result.inventory["files"]
                     if row.get("omitted") == "path-not-utf8")
        self.assertEqual(odd, [("file", False), ("other", False)])
        self.assertTrue(all(row["path"].isascii() for row in result.inventory["files"]))
        self.assertEqual(sorted(tar_members(result.tar_path)), ["SKILL.md", "scripts/tool.py"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs named pipes")
    def test_a_named_pipe_is_recorded_and_never_opened(self):
        folder = self.make_folder()
        os.mkfifo(str(folder / "pipe"))
        result = self.fetch(folder)
        self.assert_bundle(result)
        row = rows_by_path(result.inventory)["pipe"]
        self.assertEqual((row["entry"], row["omitted"], row["stored"]), ("other", "special-file", False))

    def test_folder_caps(self):
        folder = self.make_folder()
        (folder / "big.dat").write_bytes(b"z" * 500)
        limits = fetch_mod.DEFAULT_LIMITS
        result = self.fetch(folder, limits=limits._replace(max_file_bytes=100))
        self.assert_bundle(result)
        row = rows_by_path(result.inventory)["big.dat"]
        self.assertEqual((row["omitted"], row["size"], row["sha256"]),
                         ("file-over-size-cap", 500, hr.sha256_hex(b"z" * 500)))
        self.assertNotIn("big.dat", tar_members(result.tar_path))
        fetch_mod.remove_bundle(result.bundle_dir)

        result = self.fetch(folder, limits=limits._replace(max_files=2))
        self.assert_gap(result, "over-cap")
        self.assertEqual(result.gap["reasons"], ["too-many-entries"])
        result = self.fetch(folder, limits=limits._replace(max_total_bytes=400))
        self.assert_gap(result, "over-cap")
        self.assertEqual(result.gap["reasons"], ["total-over-size-cap"])

        deep = folder / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "leaf.txt").write_bytes(b"leaf\n")
        result = self.fetch(folder, limits=limits._replace(max_depth=2))
        self.assert_bundle(result)
        rows = rows_by_path(result.inventory)
        self.assertEqual((rows["a/b/c"]["entry"], rows["a/b/c"]["omitted"]), ("other", "directory-too-deep"))
        self.assertNotIn("a/b/c/leaf.txt", rows)

    def test_missing_and_unknown_targets_are_named_gaps(self):
        self.assert_gap(self.fetch(self.tmp / "nowhere"), "target-not-found")
        self.assertEqual(fetch_mod.fetch(None, quarantine_root=str(self.root)).gap["gap"], "target-not-found")
        folder = self.make_folder()
        self.assertTrue(fetch_mod.fetch(folder, quarantine_root=str(self.tmp / "as-path")).ok)
        self.assert_gap(self.fetch(""), "target-not-found")
        plain = self.tmp / "notes.txt"
        plain.write_bytes(b"not an archive\n")
        self.assert_gap(self.fetch(plain), "target-type-unknown")
        cut = self.tmp / "cut.zip"
        cut.write_bytes(b"PK\x03\x04 truncated")
        self.assert_gap(self.fetch(cut), "target-type-unknown")


# --------------------------------------------------------------------------------------
# Zip
# --------------------------------------------------------------------------------------

def unix_info(name, mode):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    return info


class ZipTests(Base):

    def make_zip(self, build, name="target.zip", compression=zipfile.ZIP_DEFLATED):
        path = self.tmp / name
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w", compression) as zf:
                build(zf)
        return path

    def rejected(self, build, limits=None, **kwargs):
        path = self.make_zip(build, **kwargs)
        result = self.fetch(path, limits=limits or fetch_mod.DEFAULT_LIMITS)
        self.assert_gap(result, "archive-rejected")
        self.assertFalse(result.gap["internal"])
        return result.gap

    def test_a_plain_zip_becomes_a_bundle(self):
        def build(zf):
            zf.writestr("pkg/", b"")
            zf.writestr(unix_info("pkg/SKILL.md", stat.S_IFREG | 0o644), b"# skill\n")
            zf.writestr(unix_info("pkg/run.sh", stat.S_IFREG | 0o755), b"#!/bin/sh\necho hi\n")
            zf.writestr("pkg/data/notes.txt", b"notes\n")
        result = self.fetch(self.make_zip(build))
        self.assert_bundle(result)
        members = tar_members(result.tar_path)
        self.assertEqual(sorted(members), ["pkg/SKILL.md", "pkg/data/notes.txt", "pkg/run.sh"])
        self.assertEqual(members["pkg/run.sh"][0].mode, 0o755)
        self.assertEqual(members["pkg/SKILL.md"][0].mode, 0o644)
        self.assertEqual(result.inventory["source"]["type"], "zip")
        self.assertEqual(result.inventory["omissions"], [])
        self.assertEqual(rows_by_path(result.inventory)["pkg/run.sh"]["mode"], "0755")

    def test_a_version_control_directory_in_a_zip_is_never_stored(self):
        """Fix round 1, F1: the zip the review adopted. All text, so no other rule fires."""
        def build(zf):
            zf.writestr("SKILL.md", b"# skill\n")
            zf.writestr(".git/", b"")
            zf.writestr(".git/HEAD", b"ref: refs/heads/main\n")
            zf.writestr(".git/config", b"[core]\n\tfsmonitor = \"touch MARKER; false\"\n")
            zf.writestr(".git/objects/info/packs", b"\n")
            zf.writestr("nested/.Git/config", b"[core]\n")
            zf.writestr("gitfile/.git", b"gitdir: ../.git\n")
        result = self.fetch(self.make_zip(build))
        self.assert_bundle(result)
        self.assertEqual(sorted(tar_members(result.tar_path)), ["SKILL.md"])
        rows = rows_by_path(result.inventory)
        refused = sorted(path for path, row in rows.items() if row.get("omitted") == "vcs-control-path")
        self.assertEqual(refused, [".git/HEAD", ".git/config", ".git/objects/info/packs", "gitfile/.git",
                                   "nested/.Git/config"])
        self.assertEqual(sorted(item["path"] for item in result.inventory["omissions"]), refused)
        with fetch_mod.extracted(result.bundle_dir) as path:
            self.assertEqual(sorted(os.listdir(path)), ["SKILL.md"])
        blocked = [e.path for e in fetch_mod.iter_bundle_entries(result.bundle_dir)
                   if [f.rule_id for f in hr.scan_blocks([hr.FileRecord(*e)])] == ["H7"]]
        self.assertEqual(sorted(blocked), refused)

    def test_traversal_is_rejected_with_its_reason(self):
        """TS-FETCH-02 (traversal)."""
        def build(zf):
            zf.writestr("ok.txt", b"fine\n")
            zf.writestr("../evil.txt", b"x")
            zf.writestr("a/../../evil2.txt", b"x")
            zf.writestr("b\\..\\..\\evil3.txt", b"x")
        gap = self.rejected(build)
        self.assertEqual(gap["reasons"], ["path-traversal"])
        self.assertEqual([r["path"] for r in gap["rejections"]],
                         ["../evil.txt", "a/../../evil2.txt", "b\\\\..\\\\..\\\\evil3.txt"])
        self.assertFalse((self.tmp / "evil.txt").exists())
        self.assertFalse((self.tmp.parent / "evil.txt").exists())

    def test_a_zip_bomb_is_rejected_with_its_reason(self):
        """TS-FETCH-02 (bomb)."""
        def build(zf):
            zf.writestr("ok.txt", b"fine\n")
            zf.writestr("bomb.txt", b"\x00" * (8 * 1024 * 1024))
        path = self.make_zip(build)
        self.assertLess(path.stat().st_size, 64 * 1024)
        opened = []
        real_open = zipfile.ZipFile.open

        def spy(zf, *args, **kwargs):
            opened.append(args)
            return real_open(zf, *args, **kwargs)

        with mock.patch.object(zipfile.ZipFile, "open", spy):
            result = self.fetch(path)
        self.assert_gap(result, "archive-rejected")
        self.assertEqual(result.gap["reasons"], ["compression-ratio-over-cap", "file-over-size-cap"])
        self.assertEqual(opened, [], "a refused archive is never decompressed")

        # Under the per-file cap, the ratio alone refuses it; many small members too.
        def many(zf):
            for index in range(40):
                zf.writestr("part%02d.txt" % index, b"\x00" * (512 * 1024))
        gap = self.rejected(lambda zf: zf.writestr("b.txt", b"\x00" * (2 * 1024 * 1024)))
        self.assertEqual(gap["reasons"], ["compression-ratio-over-cap"])
        gap = self.rejected(many)
        self.assertEqual(gap["reasons"], ["compression-ratio-over-cap"])
        self.assertEqual(gap["rejections"], [{"path": "(archive)", "reason": "compression-ratio-over-cap"}])

    def test_absolute_paths_are_rejected(self):
        def build(zf):
            zf.writestr("/abs.txt", b"x")
            zf.writestr("C:/win.txt", b"x")
            zf.writestr("\\\\server\\share.txt", b"x")
        gap = self.rejected(build)
        self.assertEqual(gap["reasons"], ["absolute-path"])
        self.assertEqual(len(gap["rejections"]), 3)

    def test_links_devices_and_special_entries_are_rejected(self):
        def build(zf):
            zf.writestr(unix_info("link", stat.S_IFLNK | 0o777), b"../outside.txt")
            zf.writestr(unix_info("dev", stat.S_IFCHR | 0o666), b"")
            zf.writestr(unix_info("blk", stat.S_IFBLK | 0o660), b"")
            zf.writestr(unix_info("pipe", stat.S_IFIFO | 0o644), b"")
        gap = self.rejected(build)
        self.assertEqual({(r["path"], r["reason"]) for r in gap["rejections"]},
                         {("link", "symlink-not-followed"), ("dev", "device-entry"),
                          ("blk", "device-entry"), ("pipe", "special-file")})

    def test_duplicate_and_case_colliding_names_are_rejected(self):
        def duplicate(zf):
            zf.writestr("a.txt", b"one")
            zf.writestr("a.txt", b"two")
        self.assertEqual(self.rejected(duplicate)["reasons"], ["duplicate-name"])

        def case_file(zf):
            zf.writestr("Readme.md", b"one")
            zf.writestr("README.MD", b"two")
        self.assertEqual(self.rejected(case_file)["reasons"], ["case-colliding-name"])

        def case_dir(zf):
            zf.writestr("Docs/a.txt", b"one")
            zf.writestr("docs/b.txt", b"two")
        self.assertEqual(self.rejected(case_dir)["reasons"], ["case-colliding-name"])

        def composed(zf):
            zf.writestr("caf\u00e9.txt", b"one")
            zf.writestr("cafe\u0301.txt", b"two")
        self.assertEqual(self.rejected(composed)["reasons"], ["case-colliding-name"])

        def clash(zf):
            zf.writestr("thing", b"file")
            zf.writestr("thing/inner.txt", b"under a file")
        self.assertEqual(self.rejected(clash)["reasons"], ["file-directory-conflict"])

    def test_nested_archives_are_rejected_by_name_and_by_content(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as zf:
            zf.writestr("x.txt", b"x")
        tar_bytes = io.BytesIO()
        with tarfile.open(fileobj=tar_bytes, mode="w") as tar:
            info = tarfile.TarInfo("y.txt")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"y"))

        def by_name(zf):
            zf.writestr("payload.tar.gz", b"not really")
            zf.writestr("lib.whl", b"not really")
        gap = self.rejected(by_name, compression=zipfile.ZIP_STORED)
        self.assertEqual(gap["reasons"], ["nested-archive"])
        self.assertEqual(len(gap["rejections"]), 2)

        def by_content(zf):
            zf.writestr("innocent.dat", inner.getvalue())
            zf.writestr("picture.png", tar_bytes.getvalue())
            zf.writestr("fine.txt", b"fine\n")
        gap = self.rejected(by_content, compression=zipfile.ZIP_STORED)
        self.assertEqual({(r["path"], r["reason"]) for r in gap["rejections"]},
                         {("innocent.dat", "nested-archive"), ("picture.png", "nested-archive")})

    def test_archives_over_a_cap_are_rejected(self):
        limits = fetch_mod.DEFAULT_LIMITS

        def five(zf):
            for index in range(5):
                zf.writestr("f%d.txt" % index, b"y" * 100)
        stored = {"compression": zipfile.ZIP_STORED}
        self.assertEqual(self.rejected(five, limits._replace(max_files=4), **stored)["reasons"],
                         ["too-many-entries"])
        self.assertEqual(self.rejected(five, limits._replace(max_file_bytes=99), **stored)["reasons"],
                         ["file-over-size-cap"])
        self.assertEqual(self.rejected(five, limits._replace(max_total_bytes=499), **stored)["reasons"],
                         ["total-over-size-cap"])
        self.assertEqual(self.rejected(five, limits._replace(max_archive_bytes=200), **stored)["reasons"],
                         ["total-over-size-cap"])
        long_name = "d/" * 40 + "f.txt"
        self.assertEqual(self.rejected(lambda zf: zf.writestr(long_name, b"x"),
                                       limits._replace(max_path_chars=50))["reasons"], ["path-too-long"])

    def test_encrypted_and_damaged_entries_are_rejected(self):
        path = self.make_zip(lambda zf: zf.writestr("a.txt", b"hello world, hello world\n"),
                             compression=zipfile.ZIP_STORED)
        raw = bytearray(path.read_bytes())
        at = raw.index(b"hello world")
        raw[at:at + 5] = b"HELLO"
        damaged = self.tmp / "damaged.zip"
        damaged.write_bytes(bytes(raw))
        result = self.fetch(damaged)
        self.assert_gap(result, "archive-rejected")
        self.assertEqual(result.gap["reasons"], ["unreadable-entry"])

        raw = bytearray(path.read_bytes())
        central = raw.index(b"PK\x01\x02")
        raw[central + 8] |= 0x1
        flagged = self.tmp / "flagged.zip"
        flagged.write_bytes(bytes(raw))
        result = self.fetch(flagged)
        self.assert_gap(result, "archive-rejected")
        self.assertIn("encrypted-entry", result.gap["reasons"])

    def test_every_problem_in_one_archive_is_recorded(self):
        def build(zf):
            zf.writestr("../up.txt", b"x")
            zf.writestr("/abs.txt", b"x")
            zf.writestr(unix_info("link", stat.S_IFLNK | 0o777), b"target")
            zf.writestr("inner.zip", b"x")
            zf.writestr("ctl\x01.txt", b"x")
            zf.writestr("a//b.txt", b"x")
        gap = self.rejected(build)
        self.assertEqual(gap["reasons"], ["absolute-path", "control-character", "malformed-path",
                                          "nested-archive", "path-traversal", "symlink-not-followed"])
        for rejection in gap["rejections"]:
            self.assertTrue(rejection["path"].isascii())
            self.assertTrue(rejection["path"].isprintable())
        limited = self.rejected(lambda zf: [zf.writestr("../%d" % i, b"x") for i in range(9)],
                                fetch_mod.DEFAULT_LIMITS._replace(max_rejections=4))
        self.assertEqual(len(limited["rejections"]), 4)


# --------------------------------------------------------------------------------------
# The bundle: failure, reading back, extraction
# --------------------------------------------------------------------------------------

class BundleTests(Base):

    def make_bundle(self):
        folder = self.tmp / "skill"
        (folder / "scripts").mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_bytes(b"# skill\n")
        (folder / "scripts" / "tool.py").write_bytes(b"print('hi')\n")
        (folder / "scripts" / "tool.py").chmod(0o755)
        result = self.fetch(folder)
        self.assertTrue(result.ok, result.gap)
        return result

    def test_a_failure_while_writing_leaves_no_partial_bundle(self):
        folder = self.tmp / "skill"
        folder.mkdir()
        (folder / "a.txt").write_bytes(b"a\n")
        with mock.patch.object(fetch_mod, "_build_inventory", side_effect=OSError("disk full")):
            result = self.fetch(folder)
        self.assert_gap(result, "quarantine-unwritable")
        self.assertTrue(result.gap["internal"])
        with mock.patch.object(fetch_mod, "_build_inventory", side_effect=RuntimeError("bug")):
            result = self.fetch(folder)
        self.assert_gap(result, "internal-error")
        self.assertTrue(result.gap["internal"])
        with mock.patch.object(fetch_mod._TarSink, "__call__", side_effect=OSError("disk full")):
            result = self.fetch(folder)
        self.assert_gap(result, "quarantine-unwritable")
        with mock.patch.object(fetch_mod.os, "rename", side_effect=OSError("cross-device")):
            result = self.fetch(folder)
        self.assert_gap(result, "quarantine-unwritable")

    def test_an_unwritable_quarantine_is_an_internal_gap(self):
        blocker = self.tmp / "blocker"
        blocker.write_bytes(b"a file where the quarantine should be")
        result = fetch_mod.fetch(str(self.tmp), quarantine_root=str(blocker / "quarantine"))
        self.assertFalse(result.ok)
        self.assertEqual(result.gap["gap"], "quarantine-unwritable")
        self.assertTrue(result.gap["internal"])
        self.assertEqual(blocker.read_bytes(), b"a file where the quarantine should be")

    def test_the_quarantine_root_is_injectable_and_defaults_under_home(self):
        with mock.patch.dict(os.environ, {fetch_mod.QUARANTINE_ENV: str(self.tmp / "from-env")}):
            self.assertEqual(fetch_mod.resolve_quarantine_root(), str(self.tmp / "from-env"))
            self.assertEqual(fetch_mod.resolve_quarantine_root(str(self.tmp / "arg")), str(self.tmp / "arg"))
            folder = self.tmp / "skill"
            folder.mkdir()
            (folder / "a.txt").write_bytes(b"a\n")
            result = fetch_mod.fetch(str(folder))
            self.assertTrue(result.ok, result.gap)
            self.assertEqual(Path(result.bundle_dir).parent, self.tmp / "from-env")
        env = {k: v for k, v in os.environ.items() if k != fetch_mod.QUARANTINE_ENV}
        env["HOME"] = str(self.tmp / "home")
        env["USERPROFILE"] = str(self.tmp / "home")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(fetch_mod.resolve_quarantine_root(),
                             os.path.join(str(self.tmp / "home"), ".foundry", "quarantine"))
        self.assertFalse((self.tmp / "home").exists())

    def test_extraction_is_private_checked_and_removed_afterwards(self):
        result = self.make_bundle()
        holder = self.tmp / "scan-tmp"
        holder.mkdir()
        with fetch_mod.extracted(result.bundle_dir, tmp_parent=str(holder)) as where:
            self.assertEqual(Path(where).parent, holder)
            self.assertEqual((Path(where) / "SKILL.md").read_bytes(), b"# skill\n")
            self.assertEqual((Path(where) / "scripts" / "tool.py").read_bytes(), b"print('hi')\n")
            found = sorted(str(p.relative_to(where)).replace(os.sep, "/")
                           for p in Path(where).rglob("*") if not p.is_dir())
            self.assertEqual(found, ["SKILL.md", "scripts/tool.py"])
            if POSIX:
                self.assertEqual(stat.S_IMODE(os.stat(where).st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(os.stat(Path(where) / "scripts").st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(os.stat(Path(where) / "SKILL.md").st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(os.stat(Path(where) / "scripts" / "tool.py").st_mode), 0o700)
        self.assertEqual(os.listdir(holder), [])

        with self.assertRaises(ZeroDivisionError):
            with fetch_mod.extracted(result.bundle_dir, tmp_parent=str(holder)):
                raise ZeroDivisionError()
        self.assertEqual(os.listdir(holder), [])

    def _rewrite_tar(self, result, build, fix_inventory=True):
        """Replace the bundle's tar; optionally make the inventory vouch for the new bytes."""
        with open(result.tar_path, "wb") as fh:
            with tarfile.open(fileobj=fh, mode="w", format=tarfile.PAX_FORMAT) as tar:
                build(tar)
        if fix_inventory:
            inventory = json.loads(Path(result.inventory_path).read_text(encoding="utf-8"))
            inventory["tar"]["sha256"] = hr.sha256_hex(Path(result.tar_path).read_bytes())
            inventory["inventory_digest"] = fetch_mod.inventory_digest(inventory)
            Path(result.inventory_path).write_text(json.dumps(inventory), encoding="utf-8")

    def _add(self, tar, name, data=b"", kind=tarfile.REGTYPE, linkname=""):
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = linkname
        info.size = len(data) if kind == tarfile.REGTYPE else 0
        tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)

    def test_a_bundle_that_was_altered_is_refused_and_nothing_is_left(self):
        holder = self.tmp / "scan-tmp"
        holder.mkdir()
        outside = self.tmp / "escaped.txt"

        def refuse(result):
            with self.assertRaises(fetch_mod.BundleError):
                with fetch_mod.extracted(result.bundle_dir, tmp_parent=str(holder)):
                    self.fail("an altered bundle was extracted")
            self.assertEqual(os.listdir(holder), [])
            self.assertFalse(outside.exists())
            with self.assertRaises(fetch_mod.BundleError):
                list(fetch_mod.iter_bundle_entries(result.bundle_dir))

        cases = {
            "tar bytes changed": lambda tar: self._add(tar, "SKILL.md", b"# other\n"),
            "link member": lambda tar: (self._add(tar, "SKILL.md", kind=tarfile.SYMTYPE, linkname="/etc/hostname"),
                                        self._add(tar, "scripts/tool.py", b"print('hi')\n")),
            "hard link member": lambda tar: (self._add(tar, "SKILL.md", b"# skill\n"),
                                             self._add(tar, "scripts/tool.py", kind=tarfile.LNKTYPE,
                                                       linkname="SKILL.md")),
            "device member": lambda tar: (self._add(tar, "SKILL.md", kind=tarfile.CHRTYPE),
                                          self._add(tar, "scripts/tool.py", b"print('hi')\n")),
            "traversal member": lambda tar: (self._add(tar, "SKILL.md", b"# skill\n"),
                                             self._add(tar, "../escaped.txt", b"out"),
                                             self._add(tar, "scripts/tool.py", b"print('hi')\n")),
            "extra member": lambda tar: (self._add(tar, "SKILL.md", b"# skill\n"),
                                         self._add(tar, "scripts/tool.py", b"print('hi')\n"),
                                         self._add(tar, "zzz-extra.txt", b"extra")),
            "missing member": lambda tar: self._add(tar, "SKILL.md", b"# skill\n"),
            "changed content": lambda tar: (self._add(tar, "SKILL.md", b"# SKILL\n"),
                                            self._add(tar, "scripts/tool.py", b"print('hi')\n")),
        }
        for name, build in cases.items():
            with self.subTest(case=name):
                result = self.make_bundle()
                self._rewrite_tar(result, build, fix_inventory=(name != "tar bytes changed"))
                refuse(result)
                fetch_mod.remove_bundle(result.bundle_dir)

        result = self.make_bundle()
        inventory = json.loads(Path(result.inventory_path).read_text(encoding="utf-8"))
        inventory["files"][0]["path"] = "renamed.md"
        Path(result.inventory_path).write_text(json.dumps(inventory), encoding="utf-8")
        refuse(result)
        with self.assertRaises(fetch_mod.BundleError):
            fetch_mod.load_inventory(result.bundle_dir)
        fetch_mod.remove_bundle(result.bundle_dir)
        self.assertFalse(os.path.exists(result.bundle_dir))
        with self.assertRaises(fetch_mod.BundleError):
            fetch_mod.load_inventory(result.bundle_dir)

    def test_bundle_entries_line_up_with_the_rule_set(self):
        self.assertEqual(fetch_mod.BundleEntry._fields, hr.FileRecord._fields)
        self.assertEqual((fetch_mod.ENTRY_FILE, fetch_mod.ENTRY_SYMLINK, fetch_mod.ENTRY_DEVICE,
                          fetch_mod.ENTRY_GITLINK, fetch_mod.ENTRY_OTHER), hr.ENTRIES)
        self.assertEqual(fetch_mod._LFS_PREFIX, hr._LFS_PREFIX)
        self.assertEqual(fetch_mod.DEFAULT_LIMITS.max_files, hr.MAX_FILES)
        self.assertEqual(fetch_mod.DEFAULT_LIMITS.max_file_bytes, hr.MAX_FILE_BYTES)
        self.assertEqual(fetch_mod.DEFAULT_LIMITS.max_total_bytes, hr.MAX_TOTAL_BYTES)
        result = self.make_bundle()
        entries = list(fetch_mod.iter_bundle_entries(result.bundle_dir))
        self.assertEqual([e.file_id for e in entries], [hr.make_file_id(1), hr.make_file_id(2)])
        self.assertEqual([(e.path, e.data, e.entry, e.size) for e in entries],
                         [("SKILL.md", b"# skill\n", "file", None),
                          ("scripts/tool.py", b"print('hi')\n", "file", None)])
        records = [hr.FileRecord(*e) for e in entries]
        self.assertEqual(hr.scan_blocks(records, hr.KIND_REPO), [])
        if POSIX:
            self.assertTrue(hr.is_executable(records[1]))

    def test_tree_digest_follows_content_not_the_way_it_arrived(self):
        folder = self.tmp / "skill"
        (folder / "scripts").mkdir(parents=True)
        (folder / "SKILL.md").write_bytes(b"# skill\n")
        (folder / "SKILL.md").chmod(0o644)
        (folder / "scripts" / "tool.py").write_bytes(b"print('hi')\n")
        (folder / "scripts" / "tool.py").chmod(0o755)
        from_folder = self.fetch(folder)

        archive = self.tmp / "skill.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(unix_info("scripts/tool.py", stat.S_IFREG | 0o755), b"print('hi')\n")
            zf.writestr(unix_info("SKILL.md", stat.S_IFREG | 0o600), b"# skill\n")
        from_zip = self.fetch(archive)
        self.assertTrue(from_folder.ok and from_zip.ok)
        digests = {from_folder.inventory["tree_digest"]}
        if POSIX:
            digests.add(from_zip.inventory["tree_digest"])
        if HAVE_GIT and POSIX:
            repo = self.tmp / "repo"
            shutil.copytree(folder, repo)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "same content")
            from_git = self.fetch(repo.resolve().as_uri(), test_only_protocols=FILE_ONLY)
            self.assertTrue(from_git.ok, from_git.gap)
            digests.add(from_git.inventory["tree_digest"])
        self.assertEqual(len(digests), 1)
        self.assertRegex(digests.pop(), r"^[0-9a-f]{64}$")
        self.assertNotEqual(from_folder.inventory["inventory_digest"], from_zip.inventory["inventory_digest"])

        again = self.fetch(folder)
        self.assertEqual(again.inventory["tree_digest"], from_folder.inventory["tree_digest"])
        self.assertEqual(again.inventory["tar"]["sha256"], from_folder.inventory["tar"]["sha256"])
        self.assertNotEqual(again.bundle_id, from_folder.bundle_id)

        changes = {
            "content": lambda: (folder / "SKILL.md").write_bytes(b"# skilL\n"),
            "exec bit": lambda: (folder / "scripts" / "tool.py").chmod(0o644),
            "new file": lambda: (folder / "extra.txt").write_bytes(b""),
        }
        seen = {from_folder.inventory["tree_digest"]}
        for name, change in changes.items():
            change()
            if name == "exec bit" and not POSIX:
                continue
            changed = self.fetch(folder).inventory["tree_digest"]
            self.assertNotIn(changed, seen, name)
            seen.add(changed)

    def test_command_line_reports_without_echoing_target_text(self):
        folder = self.tmp / "skill"
        folder.mkdir()
        (folder / "a.txt").write_bytes(b"a\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fetch_mod.main([str(folder), "--quarantine-root", str(self.root)])
        self.assertEqual(code, 0)
        summary = json.loads(out.getvalue())
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["counts"]["stored"], 1)
        self.assertTrue(os.path.isdir(summary["bundle_dir"]))
        fetch_mod.remove_bundle(summary["bundle_dir"])

        archive = self.tmp / "bad.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../SHOUT-FROM-THE-TARGET.txt", b"x")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fetch_mod.main([str(archive), "--quarantine-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertNotIn("SHOUT", out.getvalue())
        self.assertEqual(json.loads(out.getvalue()),
                         {"ok": False, "gap": "archive-rejected", "reasons": ["path-traversal"], "rejections": 1})
        self.assert_nothing_left()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fetch_mod.main([str(folder), "--quarantine-root", str(folder / "a.txt" / "q")])
        self.assertEqual(code, 3)


class PathPolicyTests(unittest.TestCase):

    def test_path_problems(self):
        problem = fetch_mod._path_problem
        for good in ("a.txt", "a/b/c.txt", ".hidden", "a b/c d.txt", "..a/b..", "caf\u00e9.md"):
            self.assertIsNone(problem(good), good)
        cases = {
            "": "empty-name", "../a": "path-traversal", "a/../b": "path-traversal", "a/..": "path-traversal",
            "..\\a": "path-traversal", "/a": "absolute-path", "\\a": "absolute-path",
            "c:/a": "absolute-path", "C:\\a": "absolute-path", "a\\b": "backslash-in-path",
            "a//b": "malformed-path", "./a": "malformed-path", "a/": "malformed-path",
            "a\nb": "control-character", "a\x00b": "control-character", "a\x7fb": "control-character",
            "x" * 300: "path-too-long", "d/" * 600 + "f": "path-too-long",
        }
        for path, reason in cases.items():
            self.assertEqual(problem(path), reason, repr(path))

    def test_colliding_paths_keep_the_first_spelling(self):
        entries = [fetch_mod._Entry(p, 0o644, "file") for p in
                   ["A/x.txt", "a/y.txt", "b.txt", "b.txt", "c", "c/d.txt", "E.txt", "e.TXT", "ok/z.txt"]]
        fetch_mod._apply_path_policy(entries, fetch_mod.DEFAULT_LIMITS)
        self.assertEqual([e.omit for e in entries],
                         [None, "case-colliding-name", None, "duplicate-name", None,
                          "file-directory-conflict", None, "case-colliding-name", None])

    def test_version_control_paths_are_not_stored_by_the_shared_policy(self):
        """Fix round 1, F1: the policy the git and folder sources share. (A real clone refuses
        such a tree earlier: transfer.fsckObjects is on.)"""
        paths = [".git/config", ".gitignore", "a/.GIT/x", "a/.git", "b/.hg/hgrc", "c/.svn/entries",
                 "d/.git./x", "e/GIT~1/x", "f/git/config", "g/.github/x.yml"]
        entries = [fetch_mod._Entry(p, 0o644, "file") for p in paths]
        fetch_mod._apply_path_policy(entries, fetch_mod.DEFAULT_LIMITS)
        self.assertEqual({e.path: e.omit for e in entries}, {
            ".git/config": "vcs-control-path", ".gitignore": None, "a/.GIT/x": "vcs-control-path",
            "a/.git": "vcs-control-path", "b/.hg/hgrc": "vcs-control-path",
            "c/.svn/entries": "vcs-control-path", "d/.git./x": "vcs-control-path",
            "e/GIT~1/x": "vcs-control-path", "f/git/config": None, "g/.github/x.yml": None})
        for path in paths:
            self.assertEqual(fetch_mod.is_vcs_path(path), hr.vcs_control_path(path), path)

    def test_link_escape_is_judged_lexically(self):
        escapes = fetch_mod._link_escapes
        self.assertFalse(escapes("a/link", "../b.txt"))
        self.assertFalse(escapes("link", "sub/file"))
        self.assertFalse(escapes("a/b/link", "../../c"))
        self.assertTrue(escapes("link", "../b.txt"))
        self.assertTrue(escapes("a/link", "../../b.txt"))
        self.assertTrue(escapes("a/link", "/etc/hostname"))
        self.assertTrue(escapes("a/link", "x/../../../y"))
        self.assertTrue(escapes("a/link", "C:\\Windows"))


class SelfCleanTests(unittest.TestCase):

    def test_sources_are_pure_ascii(self):
        self.assertTrue((SCRIPTS / "intake_fetch.py").read_bytes().isascii())
        self.assertTrue(Path(__file__).read_bytes().isascii())

    def test_module_imports_only_the_standard_library_and_not_the_rule_set(self):
        tree = ast.parse((SCRIPTS / "intake_fetch.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, set(sys.stdlib_module_names) | {"__future__"})
        self.assertNotIn("harness_rules", imported)
        for platform_only in ("fcntl", "pwd", "grp", "termios", "resource", "msvcrt"):
            self.assertNotIn(platform_only, imported)

    def test_module_and_its_tests_trip_no_block_rule(self):
        skill = HERE.parent
        paths = ["scripts/intake_fetch.py", "tests/test_intake_fetch.py", "tests/fixtures/target-ref-sample.json"]
        records = list(hr.records_from_paths(str(skill), paths))
        by_id = {r.file_id: r.path for r in records}
        hits = [(f.rule_id, by_id[f.file_id], f.line) for f in hr.scan_blocks(records)]
        self.assertEqual(hits, [])


# --------------------------------------------------------------------------------------
# Fix round 2
# --------------------------------------------------------------------------------------

LAYOUT_CONFIG = b"[core]\n\tbare = false\n\tworktree = .\n\tfsmonitor = \"touch PROBE_MARKER_FILE; false\"\n"
LAYOUT = {"HEAD": b"ref: refs/heads/main\n", "config": LAYOUT_CONFIG,
          "objects/info/packs": b"\n", "refs/heads/keep.txt": b"x\n"}


def git_dir_answer(directory):
    """What `git rev-parse --git-dir` says inside `directory`, looking no higher than it."""
    env = dict(GIT_BUILD_ENV, GIT_CEILING_DIRECTORIES=os.path.dirname(os.path.abspath(str(directory))))
    proc = subprocess.run(["git", "-C", str(directory), "rev-parse", "--git-dir"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


class RepositoryLayoutTests(Base):
    """Fix round 2, G1: the bare-repository layout. Both review probes, by every way in."""

    def layout_zip(self, prefix):
        def build(zf):
            zf.writestr("SKILL.md", b"# skill\n")
            for rel, data in LAYOUT.items():
                zf.writestr(prefix + rel, data)
        path = self.tmp / ("layout-%s.zip" % (prefix.strip("/") or "root"))
        with zipfile.ZipFile(path, "w") as zf:
            build(zf)
        return path

    def assert_layout_omitted(self, result, prefix, kept):
        self.assert_bundle(result)
        self.assertEqual(sorted(tar_members(result.tar_path)), kept)
        rows = rows_by_path(result.inventory)
        under = sorted(prefix + rel for rel in LAYOUT) + ([] if prefix else ["SKILL.md"])
        for path in under:
            self.assertEqual((rows[path]["stored"], rows[path]["omitted"]),
                             (False, "vcs-repository-layout"), path)
        self.assertEqual(sorted(item["path"] for item in result.inventory["omissions"]), sorted(under))
        entries = list(fetch_mod.iter_bundle_entries(result.bundle_dir))
        hits = sorted({e.path for e in entries for f in hr.scan_blocks([hr.FileRecord(*x) for x in entries])
                       if f.rule_id == "H7" and f.file_id == e.file_id})
        self.assertEqual(hits, sorted(under))
        with fetch_mod.extracted(result.bundle_dir) as path:
            found = sorted(str(p.relative_to(path)).replace(os.sep, "/") for p in Path(path).rglob("*") if p.is_file())
            self.assertEqual(found, kept)
            if HAVE_GIT:
                for sub in ("", prefix):
                    if os.path.isdir(os.path.join(path, sub)):
                        code, answer = git_dir_answer(os.path.join(path, sub))
                        self.assertNotEqual((code, answer), (0, "."), sub)

    def test_a_zip_with_the_layout_at_its_root_stores_nothing_of_it(self):
        self.assert_layout_omitted(self.fetch(self.layout_zip("")), "", [])

    def test_a_zip_with_the_layout_one_level_down_stores_the_rest(self):
        self.assert_layout_omitted(self.fetch(self.layout_zip("data/")), "data/", ["SKILL.md"])

    def layout_folder(self, prefix):
        folder = self.tmp / "folder"
        folder.mkdir()
        (folder / "SKILL.md").write_bytes(b"# skill\n")
        for rel, data in LAYOUT.items():
            target = folder / (prefix + rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if HAVE_GIT:                                  # the probe itself: git does take it for one
            self.assertEqual(git_dir_answer(folder / prefix), (0, "."))
        return folder

    def test_a_folder_with_the_layout_at_its_root(self):
        self.assert_layout_omitted(self.fetch(self.layout_folder("")), "", [])

    def test_a_folder_with_the_layout_two_levels_down(self):
        self.assert_layout_omitted(self.fetch(self.layout_folder("assets/r/")), "assets/r/", ["SKILL.md"])

    def test_empty_directories_in_a_zip_count_by_name(self):
        def build(zf):
            zf.writestr("SKILL.md", b"# skill\n")
            zf.writestr("r/HEAD", b"ref: refs/heads/main\n")
            zf.writestr("r/objects/", b"")
            zf.writestr("r/refs/", b"")
        path = self.tmp / "dirs.zip"
        with zipfile.ZipFile(path, "w") as zf:
            build(zf)
        result = self.fetch(path)
        self.assert_bundle(result)
        self.assertEqual(sorted(tar_members(result.tar_path)), ["SKILL.md"])
        self.assertEqual(rows_by_path(result.inventory)["r/HEAD"]["omitted"], "vcs-repository-layout")

    def test_the_layout_test_is_the_rule_sets(self):
        self.assertEqual(fetch_mod._VCS_NAMES, hr._VCS_NAMES)
        cases = (["HEAD", "objects/a", "refs/b"], ["a/HEAD", "a/config"], ["a/B/head", "a/b/COMMONDIR"],
                 ["x/objects/a", "x/refs/b", "x/config"], ["HEAD", "notes.md"], ["a/HEAD", "b/config"],
                 ["p/HEAD.", "p/config ", "q/r/s.md"], [])
        for paths in cases:
            self.assertEqual(fetch_mod.repo_layout_dirs(paths), hr.repo_layout_dirs(paths), paths)
            dirs = hr.repo_layout_dirs(paths)
            for path in paths + ["a/b/c/d.md", "SKILL.md"]:
                self.assertEqual(fetch_mod.in_repo_layout(path, dirs), hr.in_repo_layout(path, dirs), path)
        for name in (".bzr", ".jj", ".sl", "_darcs"):
            self.assertTrue(fetch_mod.is_vcs_path("a/%s/x" % name), name)


class RepositoryLayoutInAGitTreeTests(GitBase):

    def test_a_git_tree_with_the_layout(self):
        repo = self.make_repo("layout-src")
        self.write(repo, "SKILL.md", b"# skill\n")
        for rel, data in LAYOUT.items():
            self.write(repo, "data/" + rel, data)
        self.commit(repo)
        RepositoryLayoutTests.assert_layout_omitted(self, self.git_fetch(repo), "data/", ["SKILL.md"])


class RootCheckoutMarkerTests(Base):
    """Fix round 2, g6. A folder's own root .git is checkout metadata whether it is a
    directory or the file a work tree or a submodule checkout has: skipped, with the gap."""

    def test_a_root_git_file_is_skipped_like_a_root_git_directory(self):
        folder = self.tmp / "worktree"
        (folder / "sub").mkdir(parents=True)
        (folder / "SKILL.md").write_bytes(b"# skill\n")
        (folder / ".git").write_bytes(b"gitdir: /somewhere/else/.git/worktrees/x\n")
        (folder / "sub" / ".git").write_bytes(b"gitdir: ../.git\n")
        result = self.fetch(folder)
        self.assert_bundle(result)
        self.assertEqual(sorted(tar_members(result.tar_path)), ["SKILL.md"])
        self.assertEqual(result.inventory["omissions"],
                         [{"path": "sub/.git", "entry": "file", "reason": "vcs-control-path"},
                          {"path": ".git", "entry": "file", "reason": "vcs-directory-skipped"}])
        self.assertNotIn(".git", rows_by_path(result.inventory))

    @unittest.skipUnless(POSIX, "a symlink needs a privilege on Windows")
    def test_a_root_git_symlink_is_not_skipped(self):
        folder = self.tmp / "linked"
        folder.mkdir()
        (folder / "SKILL.md").write_bytes(b"# skill\n")
        os.symlink("elsewhere", str(folder / ".git"))
        result = self.fetch(folder)
        self.assert_bundle(result)
        self.assertEqual(rows_by_path(result.inventory)[".git"]["entry"], "symlink")


if __name__ == "__main__":
    unittest.main()
