#!/usr/bin/env python3
"""intake-scan -- test_intake_ledger.py (#350 WP-5).

The ledger, the committed records and the override log: one entry per unit, per-hit
exceptions keyed to a file digest, overrides keyed to a tree digest, and adopt, triage,
override, except, baseline, verify and status as library functions.

Every repo in these tests is a temp directory, and so are the quarantine, the ledger, the
records and the override log. Nothing is written to the real ledger, to intake/ or under
the real home. Every sample that trips a block rule is BUILT AT TEST TIME from pieces, so
this file holds no hit of its own.

Stdlib unittest; pytest only runs it.
"""
from __future__ import annotations

import ast
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
sys.path.insert(0, str(SCRIPTS))

import harness_rules as hr  # noqa: E402
import intake_fetch  # noqa: E402
import intake_ledger as il  # noqa: E402

GIT = shutil.which("git")

# Built from pieces: a provider-prefixed token shape (H9) and compiled-file bytes (H8).
TOKEN = "gh" + "p_" + "A" * 36
KEY_DOC = ("# Keys\n\nAn example value looks like " + TOKEN + " in the docs.\n").encode("ascii")
COMPILED = b"\x00\x01\x02\x03compiled"
SKILL_MD = b"---\nname: sample\ndescription: Sample skill.\n---\n\n# Sample\n\nPlain prose.\n"
T0 = "2026-10-11T12:00:00Z"
T1 = "2026-10-11T13:00:00Z"


def write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.chmod(path, mode)


def make_record(record_id: str, verdict: str, tree_digest: str, *, kind: str = "skill",
                findings=(), unit=None) -> dict:
    subject = {"kind": kind, "source": "test", "tree_digest": tree_digest}
    if unit is not None:
        subject["unit"] = unit
    return {"schema": "intake-verdict.v1", "id": record_id, "verdict": verdict, "subject": subject,
            "findings": list(findings), "gaps": [], "review": []}


class LedgerCase(unittest.TestCase):
    """A temp repo with an empty ledger, and a temp quarantine."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="intake-ledger-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "repo"
        self.q = self.tmp / "quarantine"
        self.root.mkdir()
        il.save(str(self.root), il.empty())

    # -- helpers ---------------------------------------------------------------------

    def bundle(self, files: dict, verdict: str, findings=()) -> str:
        """Fetch a folder built from `files` into the quarantine and write its record."""
        src = Path(tempfile.mkdtemp(prefix="src-", dir=str(self.tmp)))
        for rel, spec in files.items():
            data, mode = spec if isinstance(spec, tuple) else (spec, 0o644)
            write(src / rel, data, mode)
        result = intake_fetch.fetch(str(src), quarantine_root=str(self.q))
        self.assertTrue(result.ok, result.gap)
        record = make_record(result.bundle_id, verdict, result.inventory["tree_digest"], findings=findings)
        Path(result.bundle_dir, il.RECORD_NAME).write_text(json.dumps(record), encoding="utf-8")
        return result.bundle_id

    def adopt(self, record_id: str, dest: str, now: str = T1) -> dict:
        return il.adopt(str(self.root), record_id, dest, quarantine_root=str(self.q), now=now)

    def log(self) -> list:
        return il.read_overrides(str(self.root))

    def doc(self) -> dict:
        return il.load(str(self.root))

    def refused(self, code: str, func, *args, **kwargs) -> il.LedgerRefused:
        with self.assertRaises(il.LedgerRefused) as caught:
            func(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def local_unit(self, name: str = "sample", extra: dict = None) -> str:
        unit = "skills/" + name
        write(self.root / unit / "SKILL.md", SKILL_MD)
        for rel, data in (extra or {}).items():
            write(self.root / unit / rel, data)
        return unit

    def local_record(self, unit: str, verdict: str, record_id: str = "l-0001") -> dict:
        digest = il.unit_tree_digest(str(self.root), unit)
        return make_record(record_id, verdict, digest, unit=unit)


# --------------------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------------------

class UnitTests(unittest.TestCase):

    def test_unit_for_path_on_every_root(self) -> None:
        self.assertEqual(il.unit_for_path("skills/foo/SKILL.md"), "skills/foo")
        self.assertEqual(il.unit_for_path("skills/foo/scripts/deep/tool.py"), "skills/foo")
        self.assertEqual(il.unit_for_path("agents/bob.md"), "agents/bob.md")
        self.assertEqual(il.unit_for_path("commands/roll.md"), "commands/roll.md")
        self.assertEqual(il.unit_for_path("workflows/flow.js"), "workflows/flow.js")
        self.assertEqual(il.unit_for_path("./skills\\foo\\SKILL.md"), "skills/foo")

    def test_both_exclusions_need_no_entry(self) -> None:
        self.assertIsNone(il.unit_for_path("skills/_meta/gates.py"))
        self.assertIsNone(il.unit_for_path("skills/_meta/tests/test_x.py"))
        for root in ("agents", "commands", "workflows"):
            self.assertIsNone(il.unit_for_path(root + "/README.md"))

    def test_paths_that_are_rule_checked_but_are_no_unit(self) -> None:
        self.assertIsNone(il.unit_for_path("skills/loose-file.md"))
        self.assertIsNone(il.unit_for_path("agents/nested/agent.md"))
        self.assertIsNone(il.unit_for_path("docs/plans/x.md"))
        self.assertIsNone(il.unit_for_path("install.py"))
        self.assertTrue(il.is_enforced("skills/_meta/gates.py"))
        self.assertTrue(il.is_enforced("skills/loose-file.md"))
        self.assertFalse(il.is_enforced("docs/plans/x.md"))

    def test_is_unit(self) -> None:
        for unit in ("skills/foo", "agents/bob.md", "commands/roll.md", "workflows/flow.js"):
            self.assertTrue(il.is_unit(unit), unit)
        for not_unit in ("skills/_meta", "agents/README.md", "skills", "skills/foo/SKILL.md",
                         "docs/x", "../skills/foo", "/skills/foo", "skills/.."):
            self.assertFalse(il.is_unit(not_unit), not_unit)

    def test_units_missing_entry(self) -> None:
        doc = il.empty()
        paths = ["skills/a/SKILL.md", "skills/a/x.py", "skills/_meta/g.py", "agents/b.md", "agents/README.md"]
        self.assertEqual(il.units_missing_entry(doc, paths), ["agents/b.md", "skills/a"])


# --------------------------------------------------------------------------------------
# The ledger file
# --------------------------------------------------------------------------------------

class LedgerFileTests(LedgerCase):

    def test_tracked_ledger_is_empty_but_valid(self) -> None:
        doc = json.loads((REPO / il.LEDGER_REL).read_text(encoding="utf-8"))
        il.validate(doc)
        self.assertEqual(doc["schema"], il.SCHEMA)
        self.assertEqual((REPO / il.OVERRIDES_REL).read_text(encoding="utf-8").strip() == "",
                         il.read_overrides(str(REPO)) == [])

    def test_fixtures_are_valid_and_match_the_manifest(self) -> None:
        import hashlib
        il.validate(json.loads((FIXTURES / "ledger-sample.json").read_text(encoding="utf-8")))
        manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
        component = manifest["components"]["intake-ledger"]
        for group in (component["inputs"]["ledger_request"], component["outputs"]["ledger_state"]):
            for fixture in group["fixtures"]:
                data = (REPO / fixture["path"]).read_bytes()
                self.assertEqual(fixture["hash"], "sha256:" + hashlib.sha256(data).hexdigest())
        requests = json.loads((FIXTURES / "ledger-request-sample.json").read_text(encoding="utf-8"))
        self.assertEqual({r["op"] for r in requests["requests"]},
                         {"adopt", "override", "triage", "except", "lookup"})

    def test_missing_ledger_raises_the_named_error(self) -> None:
        os.unlink(il.ledger_path(str(self.root)))
        with self.assertRaises(il.LedgerMissing):
            il.load(str(self.root))
        self.assertFalse(il.exists(str(self.root)))

    def test_malformed_ledger_raises_the_named_error_never_an_empty_ledger(self) -> None:
        good = json.loads((FIXTURES / "ledger-sample.json").read_text(encoding="utf-8"))
        path = Path(il.ledger_path(str(self.root)))

        def broken(change) -> dict:
            doc = json.loads(json.dumps(good))
            change(doc)
            return doc

        cases = {
            "not json": b"{not json",
            "empty file": b"",
            "a list": b"[]",
            "wrong schema": json.dumps(broken(lambda d: d.update(schema="other"))).encode(),
            "no entries": json.dumps(broken(lambda d: d.pop("entries"))).encode(),
            "no exceptions": json.dumps(broken(lambda d: d.pop("exceptions"))).encode(),
            "bad unit": json.dumps(broken(lambda d: d["entries"][0].update(unit="skills/_meta"))).encode(),
            "repeated unit": json.dumps(broken(lambda d: d["entries"].append(d["entries"][0]))).encode(),
            "bad verdict": json.dumps(broken(lambda d: d["entries"][0].update(verdict="fine"))).encode(),
            "bad digest": json.dumps(broken(lambda d: d["entries"][0].update(digest="abc"))).encode(),
            "flag not bool": json.dumps(broken(lambda d: d["entries"][0].update(unsigned_caution="no"))).encode(),
            "exception without digest":
                json.dumps(broken(lambda d: d["entries"][1]["exceptions"][0].update(sha256=""))).encode(),
            "exception outside its unit":
                json.dumps(broken(lambda d: d["entries"][1]["exceptions"][0].update(path="skills/other/x.md"))).encode(),
            "exception without reason":
                json.dumps(broken(lambda d: d["entries"][1]["exceptions"][0].update(reason=""))).encode(),
        }
        for name, data in cases.items():
            with self.subTest(name):
                path.write_bytes(data)
                with self.assertRaises(il.LedgerMalformed):
                    il.load(str(self.root))
                with self.assertRaises(il.LedgerError):
                    il.verify(str(self.root))

    def test_malformed_override_log_raises(self) -> None:
        log = Path(il.overrides_path(str(self.root)))
        log.parent.mkdir(parents=True, exist_ok=True)
        for data in (b"not json\n", b'{"action": "override"}\n', b'{"action": "other", "record_id": "x"}\n'):
            log.write_bytes(data)
            with self.assertRaises(il.LedgerMalformed):
                il.read_overrides(str(self.root))

    def test_save_is_atomic_sorted_and_leaves_no_temp_file(self) -> None:
        doc = il.empty()
        for unit in ("skills/zeta", "agents/alpha.md", "skills/beta"):
            il.add_entry(str(self.root), unit, kind="skill", record_id="r-1", digest="a" * 64,
                         verdict="pass", unsigned_caution=False, origin="local", now=T0, doc=doc, write=False)
        il.save(str(self.root), doc)
        on_disk = self.doc()
        self.assertEqual([e["unit"] for e in on_disk["entries"]], ["agents/alpha.md", "skills/beta", "skills/zeta"])
        directory = Path(il.ledger_path(str(self.root))).parent
        self.assertEqual(sorted(p.name for p in directory.iterdir()), ["intake-ledger.json"])
        self.assertTrue(Path(il.ledger_path(str(self.root))).read_bytes().endswith(b"\n"))

    def test_save_refuses_an_invalid_document_and_keeps_the_old_file(self) -> None:
        before = Path(il.ledger_path(str(self.root))).read_bytes()
        bad = il.empty()
        bad["entries"].append({"unit": "skills/x"})
        with self.assertRaises(il.LedgerMalformed):
            il.save(str(self.root), bad)
        self.assertEqual(Path(il.ledger_path(str(self.root))).read_bytes(), before)

    def test_add_entry_replaces_and_keeps_exceptions(self) -> None:
        unit = self.local_unit(extra={"references/keys.md": KEY_DOC})
        il.add_exception(str(self.root), "H9", unit + "/references/keys.md", reason="documented example", now=T0)
        self.assertEqual(len(self.doc()["exceptions"]), 1)          # no entry yet: top level
        il.add_local_entry(str(self.root), unit, self.local_record(unit, "pass"), now=T0)
        doc = self.doc()
        self.assertEqual(doc["exceptions"], [])                      # moved into the entry
        self.assertEqual(len(il.get_entry(doc, unit)["exceptions"]), 1)
        il.add_local_entry(str(self.root), unit, self.local_record(unit, "caution", "l-0002"), now=T1)
        entry = il.get_entry(self.doc(), unit)
        self.assertEqual((entry["record_id"], entry["verdict"], len(entry["exceptions"])), ("l-0002", "caution", 1))
        self.assertEqual(len(self.doc()["entries"]), 1)


# --------------------------------------------------------------------------------------
# except
# --------------------------------------------------------------------------------------

class ExceptionTests(LedgerCase):

    def setUp(self) -> None:
        super().setUp()
        self.unit = self.local_unit(extra={"references/keys.md": KEY_DOC})
        self.path = self.unit + "/references/keys.md"

    def test_except_writes_one_per_hit_exception_and_one_log_line(self) -> None:
        self.assertEqual([h.rule_id for h in il.verify(str(self.root)).hits], ["H9"])
        exc = il.add_exception(str(self.root), "H9", self.path, reason="  documented\n example value ", now=T0)
        self.assertEqual(exc["sha256"], hr.sha256_hex(KEY_DOC))
        self.assertEqual(exc["reason"], "documented example value")
        self.assertEqual(len(il.iter_exceptions(self.doc())), 1)
        self.assertEqual(self.log(), [{
            "action": "except", "record_id": "", "tree_digest": "", "rule_ids": ["H9"], "path": self.path,
            "file_sha256": hr.sha256_hex(KEY_DOC), "reason": "documented example value", "time": T0}])
        self.assertEqual(il.verify(str(self.root)).hits, [])

    def test_ts_led_02_exception_no_longer_matches_after_the_file_changes(self) -> None:
        il.add_exception(str(self.root), "H9", self.path, reason="documented example", now=T0)
        doc = self.doc()
        self.assertTrue(il.exception_matches(doc, "H9", self.path, hr.sha256_hex(KEY_DOC)))
        changed = KEY_DOC + b"One more line.\n"
        write(self.root / self.path, changed)
        self.assertFalse(il.exception_matches(doc, "H9", self.path, hr.sha256_hex(changed)))
        result = il.verify(str(self.root))
        self.assertEqual([(h.rule_id, h.path) for h in result.hits], [("H9", self.path)])
        self.assertEqual([e["path"] for e in result.stale_exceptions], [self.path])
        self.assertFalse(result.ok)
        # Renewal: the same call again, for the content as it is now.
        il.add_exception(str(self.root), "H9", self.path, reason="still an example", now=T1)
        self.assertEqual(len(il.iter_exceptions(self.doc())), 1)
        self.assertEqual(il.verify(str(self.root)).hits, [])
        self.assertEqual(len(self.log()), 2)

    def test_exception_is_for_one_rule_on_one_file(self) -> None:
        il.add_exception(str(self.root), "H9", self.path, reason="documented example", now=T0)
        doc = self.doc()
        digest = hr.sha256_hex(KEY_DOC)
        self.assertFalse(il.exception_matches(doc, "H1", self.path, digest))
        self.assertFalse(il.exception_matches(doc, "H9", self.unit + "/references/copy.md", digest))
        self.assertFalse(il.exception_matches(doc, "H9", self.path, ""))
        write(self.root / self.unit / "references/copy.md", KEY_DOC)       # same bytes, other file
        self.assertEqual([h.path for h in il.verify(str(self.root)).hits], [self.unit + "/references/copy.md"])

    def test_except_refuses_h7_and_h8(self) -> None:
        write(self.root / self.unit / "tool.pyc", COMPILED)
        self.assertIn("H8", [h.rule_id for h in il.verify(str(self.root)).hits])
        for rule in ("H7", "H8"):
            self.refused("rule-takes-no-exception", il.add_exception, str(self.root), rule,
                         self.unit + "/tool.pyc", reason="we need it")
        self.assertEqual(il.iter_exceptions(self.doc()), [])
        self.assertEqual(self.log(), [])

    def test_except_refusals_write_nothing(self) -> None:
        root = str(self.root)
        self.refused("bad-reason", il.add_exception, root, "H9", self.path, reason="   ")
        self.refused("unknown-rule", il.add_exception, root, "C1", self.path, reason="r")
        self.refused("unknown-rule", il.add_exception, root, "H10", self.path, reason="r")
        self.refused("no-such-hit", il.add_exception, root, "H1", self.path, reason="r")
        self.refused("no-such-hit", il.add_exception, root, "H9", self.unit + "/SKILL.md", reason="r")
        self.refused("file-not-found", il.add_exception, root, "H9", self.unit + "/absent.md", reason="r")
        self.refused("bad-path", il.add_exception, root, "H9", "docs/keys.md", reason="r")
        self.refused("bad-path", il.add_exception, root, "H9", "../" + self.path, reason="r")
        self.assertEqual(il.iter_exceptions(self.doc()), [])
        self.assertEqual(self.log(), [])

    def test_exception_on_a_path_with_no_unit_is_top_level(self) -> None:
        write(self.root / "skills/_meta/notes.md", KEY_DOC)
        il.add_exception(str(self.root), "H9", "skills/_meta/notes.md", reason="documented example", now=T0)
        il.add_exception(str(self.root), "H9", self.path, reason="documented example", now=T0)
        il.add_local_entry(str(self.root), self.unit, self.local_record(self.unit, "pass"), now=T0)
        doc = self.doc()
        self.assertEqual([e["path"] for e in doc["exceptions"]], ["skills/_meta/notes.md"])
        self.assertTrue(il.verify(str(self.root)).ok)


# --------------------------------------------------------------------------------------
# override and triage
# --------------------------------------------------------------------------------------

class OverrideAndTriageTests(LedgerCase):

    FINDINGS = [{"rule": "H9", "class": "block", "file": "f001", "line": 3, "scanner": "harness-rules"},
                {"rule": "C2", "class": "caution", "file": "f002", "line": 1, "scanner": "harness-rules"}]

    def test_override_appends_record_id_digest_rule_ids_reason_and_time(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "block", self.FINDINGS)
        line = il.override(str(self.root), rid, reason="read by hand: a documented example",
                           quarantine_root=str(self.q), now=T0)
        record, _path = il.find_record(str(self.root), rid, str(self.q))
        self.assertEqual(self.log(), [line])
        self.assertEqual(line, {"action": "override", "record_id": rid,
                                "tree_digest": record["subject"]["tree_digest"], "rule_ids": ["H9"], "gaps": [],
                                "reason": "read by hand: a documented example", "time": T0})
        self.assertEqual(record["review"][-1], {"action": "override", "time": T0,
                                                "reason": "read by hand: a documented example"})
        self.assertEqual(il.record_state(record, self.log()), il.STATE_OVERRIDDEN)

    def test_override_is_void_when_the_tree_digest_changes(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "block", self.FINDINGS)
        il.override(str(self.root), rid, reason="reviewed", quarantine_root=str(self.q), now=T0)
        record, _path = il.find_record(str(self.root), rid, str(self.q))
        self.assertEqual(il.record_state(record, self.log(), record["subject"]["tree_digest"]), il.STATE_OVERRIDDEN)
        self.assertEqual(il.record_state(record, self.log(), "b" * 64), il.STATE_BLOCK)

    def test_override_of_a_swapped_bundle_does_not_adopt(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "block", self.FINDINGS)
        il.override(str(self.root), rid, reason="reviewed", quarantine_root=str(self.q), now=T0)
        # Another tree is put in the bundle's place, with the record left as it was.
        other = intake_fetch.fetch(str(self.root), quarantine_root=str(self.q))
        for name in (il.TAR_NAME, "inventory.json"):
            shutil.copyfile(Path(other.bundle_dir, name), self.q / rid / name)
        self.refused("record-does-not-match", self.adopt, rid, "skills/taken")
        self.assertFalse((self.root / "skills/taken").exists())

    def test_override_refusals(self) -> None:
        root, q = str(self.root), str(self.q)
        caution = self.bundle({"SKILL.md": SKILL_MD}, "caution")
        self.refused("not-a-block", il.override, root, caution, reason="r", quarantine_root=q)
        block = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "block", self.FINDINGS)
        self.refused("bad-reason", il.override, root, block, reason="", quarantine_root=q)
        self.refused("record-not-found", il.override, root, "q-absent", reason="r", quarantine_root=q)
        self.refused("bad-id", il.override, root, "../" + block, reason="r", quarantine_root=q)
        self.assertEqual(self.log(), [])

    def test_triage_accept_signs_a_caution_and_is_logged(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD}, "caution", self.FINDINGS[1:])
        self.refused("caution-not-signed", self.adopt, rid, "skills/taken")
        line = il.triage(str(self.root), rid, accept=True, reason="findings read", quarantine_root=str(self.q), now=T0)
        self.assertEqual((line["action"], line["record_id"], line["rule_ids"], line["reason"], line["time"]),
                         ("triage-accept", rid, ["C2"], "findings read", T0))
        self.assertRegex(line["tree_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.log(), [line])
        entry = self.adopt(rid, "skills/taken")
        self.assertEqual((entry["verdict"], entry["unsigned_caution"], entry["origin"]), ("caution", False, "adopt"))

    def test_triage_accept_is_only_for_a_caution(self) -> None:
        for verdict in ("pass", "block"):
            rid = self.bundle({"SKILL.md": SKILL_MD}, verdict)
            self.refused("not-a-caution", il.triage, str(self.root), rid, accept=True, reason="r",
                         quarantine_root=str(self.q))
        self.assertEqual(self.log(), [])

    def test_triage_reject_marks_the_record_block_and_is_final(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD}, "pass", self.FINDINGS[1:])
        line = il.triage(str(self.root), rid, accept=False, reason="confirmed malicious",
                         quarantine_root=str(self.q), now=T0)
        self.assertEqual((line["action"], line["rule_ids"], line["reason"]),
                         ("triage-reject", ["C2"], "confirmed malicious"))
        record, _path = il.find_record(str(self.root), rid, str(self.q))
        self.assertEqual(record["verdict"], "block")
        self.assertEqual(il.record_state(record, self.log()), il.STATE_REJECTED)
        # Retention: the tar is gone, the bundle is marked, and nothing brings it back.
        self.assertFalse((self.q / rid / il.TAR_NAME).exists())
        self.assertEqual(json.loads((self.q / rid / il.CLOSED_NAME).read_text(encoding="utf-8"))["state"], "rejected")
        self.refused("rejected", il.override, str(self.root), rid, reason="r", quarantine_root=str(self.q))
        self.refused("rejected", il.triage, str(self.root), rid, accept=True, reason="r", quarantine_root=str(self.q))
        self.refused("rejected", self.adopt, rid, "skills/taken")
        self.assertEqual(len(self.log()), 1)

    def test_every_decision_is_one_appended_line(self) -> None:
        a = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "block", self.FINDINGS)
        b = self.bundle({"SKILL.md": SKILL_MD}, "caution", self.FINDINGS[1:])
        il.override(str(self.root), a, reason="one", quarantine_root=str(self.q), now=T0)
        first = Path(il.overrides_path(str(self.root))).read_bytes()
        il.triage(str(self.root), b, accept=True, reason="two", quarantine_root=str(self.q), now=T0)
        il.triage(str(self.root), a, accept=False, reason="three", quarantine_root=str(self.q), now=T1)
        raw = Path(il.overrides_path(str(self.root))).read_bytes()
        self.assertTrue(raw.startswith(first))                       # append-only
        self.assertEqual([(l["action"], l["reason"]) for l in self.log()],
                         [("override", "one"), ("triage-accept", "two"), ("triage-reject", "three")])
        for line in self.log():
            for key in ("record_id", "tree_digest", "rule_ids", "reason", "time", "action"):
                self.assertIn(key, line)


# --------------------------------------------------------------------------------------
# adopt
# --------------------------------------------------------------------------------------

class AdoptTests(LedgerCase):

    FILES = {"SKILL.md": SKILL_MD, "scripts/tool.py": (b"#!/usr/bin/env python3\nprint('hi')\n", 0o755),
             "references/data.bin.txt": bytes(range(32, 127)) * 40}

    def test_ts_led_01_adopt_of_a_block_record_without_an_override_is_refused(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "block",
                          [{"rule": "H9", "class": "block", "file": "f002", "line": 3}])
        before = Path(il.ledger_path(str(self.root))).read_bytes()
        self.refused("block-not-overridden", self.adopt, rid, "skills/taken")
        self.assertFalse((self.root / "skills/taken").exists())
        self.assertFalse((self.root / "intake/records").exists())
        self.assertEqual(Path(il.ledger_path(str(self.root))).read_bytes(), before)
        self.assertTrue((self.q / rid / il.TAR_NAME).is_file())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".intake")], [])

    def test_adopt_accepts_only_pass_signed_caution_or_overridden_block(self) -> None:
        q = str(self.q)
        ok_pass = self.bundle(self.FILES, "pass")
        self.assertEqual(self.adopt(ok_pass, "skills/one")["verdict"], "pass")
        unsigned = self.bundle(self.FILES, "caution")
        self.refused("caution-not-signed", self.adopt, unsigned, "skills/two")
        il.triage(str(self.root), unsigned, accept=True, reason="read", quarantine_root=q, now=T0)
        self.assertEqual(self.adopt(unsigned, "skills/two")["verdict"], "caution")
        gap_block = self.bundle(self.FILES, "block")            # a block from a scanner gap, no hit
        self.refused("block-not-overridden", self.adopt, gap_block, "skills/three")
        il.override(str(self.root), gap_block, reason="scanner unavailable; read by hand", quarantine_root=q, now=T0)
        entry = self.adopt(gap_block, "skills/three")
        self.assertEqual((entry["verdict"], entry["exceptions"]), ("block", []))
        self.assertEqual([e["unit"] for e in self.doc()["entries"]], ["skills/one", "skills/three", "skills/two"])

    def test_adopt_writes_exactly_the_scanned_bytes(self) -> None:
        src_files = dict(self.FILES)
        rid = self.bundle(src_files, "pass")
        inventory = intake_fetch.load_inventory(str(self.q / rid))
        entry = self.adopt(rid, "skills/taken")
        dest = self.root / "skills/taken"
        written = sorted(str(p.relative_to(dest)).replace(os.sep, "/") for p in dest.rglob("*") if p.is_file())
        self.assertEqual(written, sorted(src_files))
        for row in inventory["files"]:
            data = (dest / row["path"]).read_bytes()
            self.assertEqual(hr.sha256_hex(data), row["sha256"])
            self.assertEqual(len(data), row["size"])
        if os.name != "nt":
            self.assertEqual((dest / "scripts/tool.py").stat().st_mode & 0o777, 0o755)
            self.assertEqual((dest / "SKILL.md").stat().st_mode & 0o777, 0o644)
        # The entry digest is the digest of the tree that was scanned.
        self.assertEqual(entry["digest"], inventory["tree_digest"])
        self.assertEqual(entry["digest"], il.unit_tree_digest(str(self.root), "skills/taken"))
        self.assertEqual((entry["record_id"], entry["kind"], entry["time"]), (rid, "skill", T1))

    def test_adopt_copies_the_record_and_closes_the_bundle(self) -> None:
        rid = self.bundle(self.FILES, "pass")
        Path(self.q / rid / il.TRIAGE_NAME).write_text("human report\n", encoding="utf-8")
        self.adopt(rid, "skills/taken")
        record = json.loads(Path(il.record_path(str(self.root), rid)).read_text(encoding="utf-8"))
        self.assertEqual((record["id"], record["verdict"]), (rid, "pass"))
        self.assertEqual(record["review"][-1]["action"], "adopt")
        self.assertFalse((self.q / rid / il.TAR_NAME).exists())
        self.assertTrue((self.q / rid / il.TRIAGE_NAME).is_file())
        self.assertEqual(json.loads((self.q / rid / il.CLOSED_NAME).read_text(encoding="utf-8"))["state"], "adopted")
        self.refused("bundle-invalid", self.adopt, rid, "skills/again")
        self.assertTrue(il.verify(str(self.root)).ok)

    def test_adopt_converts_an_override_into_per_hit_exceptions(self) -> None:
        files = {"SKILL.md": SKILL_MD, "references/keys.md": KEY_DOC, "references/more.md": KEY_DOC + b"x\n"}
        rid = self.bundle(files, "block", [{"rule": "H9", "class": "block", "file": "f002", "line": 3}])
        il.override(str(self.root), rid, reason="documented example values", quarantine_root=str(self.q), now=T0)
        entry = self.adopt(rid, "skills/taken")
        self.assertEqual([(e["rule"], e["path"], e["origin"], e["record_id"], e["reason"]) for e in entry["exceptions"]],
                         [("H9", "skills/taken/references/keys.md", "override", rid, "documented example values"),
                          ("H9", "skills/taken/references/more.md", "override", rid, "documented example values")])
        self.assertEqual(entry["exceptions"][0]["sha256"], hr.sha256_hex(KEY_DOC))
        # The unit is now governed like any other: clean as adopted, a hit once a file changes.
        self.assertTrue(il.verify(str(self.root)).ok)
        write(self.root / "skills/taken/references/keys.md", KEY_DOC + b"edited\n")
        result = il.verify(str(self.root))
        self.assertEqual([(h.rule_id, h.path) for h in result.hits], [("H9", "skills/taken/references/keys.md")])
        self.assertEqual(il.status(str(self.root), quarantine_root=str(self.q))["overrides"], [])

    def test_adopt_refuses_content_with_a_hit_the_record_does_not_account_for(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "pass")     # a record that says pass
        exc = self.refused("block-hit-in-content", self.adopt, rid, "skills/taken")
        self.assertEqual([(h.rule_id, h.path) for h in exc.hits], [("H9", "skills/taken/keys.md")])
        self.assertFalse((self.root / "skills/taken").exists())
        self.assertEqual(self.doc()["entries"], [])

    def test_adopt_never_writes_a_version_control_path_even_under_an_override(self) -> None:
        """Fix round 1, F1. Acquisition does not store such a path; if a bundle holds one
        all the same, no override takes it into the repo."""
        files = {"SKILL.md": SKILL_MD, "sub/.git/config": b"[core]\n\tbare = false\n",
                 "sub/.git/HEAD": b"ref: refs/heads/main\n"}
        finding = [{"rule": "H7", "class": "block", "file": "f002", "line": 0}]
        with mock.patch.object(intake_fetch, "_vcs_name", return_value=False), \
                mock.patch.object(intake_fetch, "is_vcs_path", return_value=False), \
                mock.patch.object(intake_fetch, "repo_layout_dirs", return_value=frozenset()):
            forged = self.bundle(files, "block", finding)
        self.assertEqual(sorted(e.path for e in intake_fetch.iter_bundle_entries(str(self.q / forged))
                                if e.entry == "file" and e.size is None),
                         ["SKILL.md", "sub/.git/HEAD", "sub/.git/config"])
        il.override(str(self.root), forged, reason="looked fine", quarantine_root=str(self.q), now=T0)
        before = Path(il.ledger_path(str(self.root))).read_bytes()
        self.refused("vcs-control-path", self.adopt, forged, "skills/taken")
        self.assertFalse((self.root / "skills/taken").exists())
        self.assertEqual(Path(il.ledger_path(str(self.root))).read_bytes(), before)
        # As fetched for real, the directory is an omission: an override adopts the rest.
        real = self.bundle(files, "block", finding)
        il.override(str(self.root), real, reason="the rest was read", quarantine_root=str(self.q), now=T0)
        entry = self.adopt(real, "skills/rest")
        self.assertEqual(sorted(p.name for p in (self.root / "skills/rest").rglob("*")), ["SKILL.md"])
        self.assertEqual(entry["exceptions"], [])

    def test_adopt_into_a_unit_root_needs_a_record_scanned_as_a_skill(self) -> None:
        """Fix round 1, m2: kind repo makes the skill scanner optional, so it is no way in."""
        for number, dest in enumerate(("skills/taken", "agents/taken.md", "commands/taken.md", "workflows/t.js")):
            files = self.FILES if dest.startswith("skills/") else {"taken.md": SKILL_MD}
            rid = self.bundle(files, "pass")
            path = self.q / rid / il.RECORD_NAME
            record = json.loads(path.read_text(encoding="utf-8"))
            record["subject"]["kind"] = "repo"
            path.write_text(json.dumps(record), encoding="utf-8")
            self.refused("kind-not-skill", self.adopt, rid, dest)
            self.assertFalse((self.root / dest).exists(), dest)
        self.assertEqual(self.doc()["entries"], [])

    def test_adopt_checks_both_digests_against_the_record(self) -> None:
        """Fix round 1, m3."""
        rid = self.bundle(self.FILES, "pass")
        directory = self.q / rid
        record_path = directory / il.RECORD_NAME
        record = json.loads(record_path.read_text(encoding="utf-8"))
        inventory = json.loads((directory / intake_fetch.INVENTORY_NAME).read_text(encoding="utf-8"))
        # The record names another inventory.
        record["inventory_digest"] = "0" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.refused("record-does-not-match", self.adopt, rid, "skills/taken")
        record["inventory_digest"] = inventory["inventory_digest"]
        record_path.write_text(json.dumps(record), encoding="utf-8")
        # An inventory whose tree digest is not the digest of its own rows (self-digest redone).
        forged = dict(inventory, tree_digest="1" * 64)
        forged["inventory_digest"] = intake_fetch.inventory_digest(forged)
        record["subject"]["tree_digest"] = "1" * 64
        record["inventory_digest"] = forged["inventory_digest"]
        record_path.write_text(json.dumps(record), encoding="utf-8")
        (directory / intake_fetch.INVENTORY_NAME).write_text(json.dumps(forged), encoding="utf-8")
        self.refused("bundle-invalid", self.adopt, rid, "skills/taken")
        self.assertFalse((self.root / "skills/taken").exists())
        # Put back as fetched: it adopts.
        (directory / intake_fetch.INVENTORY_NAME).write_text(json.dumps(inventory), encoding="utf-8")
        record["subject"]["tree_digest"] = inventory["tree_digest"]
        record["inventory_digest"] = inventory["inventory_digest"]
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.adopt(rid, "skills/taken")["verdict"], "pass")

    def test_adopt_destination_rules(self) -> None:
        rid = self.bundle(self.FILES, "pass")
        for dest in ("docs/taken", "skills/_meta", "skills/a/b", "agents/README.md", "../skills/x", "skills"):
            self.refused("destination-not-a-unit", self.adopt, rid, dest)
        self.refused("not-a-single-file", self.adopt, rid, "agents/taken.md")
        (self.root / "skills/present").mkdir(parents=True)
        self.refused("destination-exists", self.adopt, rid, "skills/present")
        self.assertEqual(self.doc()["entries"], [])
        self.assertTrue((self.q / rid / il.TAR_NAME).is_file())

    def test_adopt_a_single_file_unit(self) -> None:
        agent = b"---\nname: helper\ndescription: Helper agent.\n---\n\nDo the task.\n"
        rid = self.bundle({"helper.md": agent}, "pass")
        entry = self.adopt(rid, "agents/helper.md")
        self.assertEqual((self.root / "agents/helper.md").read_bytes(), agent)
        self.assertEqual(entry["unit"], "agents/helper.md")
        self.assertEqual(entry["digest"], il.unit_tree_digest(str(self.root), "agents/helper.md"))
        self.assertTrue(il.verify(str(self.root)).ok)

    def test_adopt_does_not_write_what_the_tar_does_not_hold(self) -> None:
        if os.name == "nt":
            self.skipTest("needs a symlink")
        src = Path(tempfile.mkdtemp(prefix="src-", dir=str(self.tmp)))
        write(src / "SKILL.md", SKILL_MD)
        os.symlink("/etc/hostname", src / "link")
        result = intake_fetch.fetch(str(src), quarantine_root=str(self.q))
        record = make_record(result.bundle_id, "block", result.inventory["tree_digest"],
                             findings=[{"rule": "H7", "class": "block", "file": "f002", "line": 0}])
        Path(result.bundle_dir, il.RECORD_NAME).write_text(json.dumps(record), encoding="utf-8")
        il.override(str(self.root), result.bundle_id, reason="link dropped", quarantine_root=str(self.q), now=T0)
        self.adopt(result.bundle_id, "skills/taken")
        self.assertEqual(sorted(p.name for p in (self.root / "skills/taken").iterdir()), ["SKILL.md"])

    def test_adopt_with_a_missing_or_malformed_record(self) -> None:
        rid = self.bundle(self.FILES, "pass")
        record_file = self.q / rid / il.RECORD_NAME
        record_file.write_text("{}", encoding="utf-8")
        self.refused("bad-record", self.adopt, rid, "skills/taken")
        record_file.unlink()
        self.refused("record-not-found", self.adopt, rid, "skills/taken")
        self.refused("bad-id", self.adopt, "a/b", "skills/taken")


# --------------------------------------------------------------------------------------
# scan --local, the baseline, verify, status
# --------------------------------------------------------------------------------------

class LocalEntryTests(LedgerCase):

    def test_local_entry_at_any_verdict_without_a_block_hit(self) -> None:
        for number, verdict in enumerate(("pass", "caution", "block"), 1):
            unit = self.local_unit("unit%d" % number)
            entry = il.add_local_entry(str(self.root), unit, self.local_record(unit, verdict, "l-%d" % number), now=T0)
            self.assertEqual((entry["verdict"], entry["origin"], entry["unsigned_caution"]),
                             (verdict, "local", verdict == "caution"))
            self.assertTrue(Path(il.record_path(str(self.root), "l-%d" % number)).is_file())
        self.assertEqual(il.status(str(self.root), quarantine_root=str(self.q))["unsigned_cautions"], ["skills/unit2"])
        self.assertTrue(il.verify(str(self.root)).ok)

    def test_local_entry_refused_on_an_unexcepted_block_hit(self) -> None:
        unit = self.local_unit(extra={"references/keys.md": KEY_DOC})
        exc = self.refused("unexcepted-block-hit", il.add_local_entry, str(self.root), unit,
                           self.local_record(unit, "block"))
        self.assertEqual([(h.rule_id, h.path) for h in exc.hits], [("H9", unit + "/references/keys.md")])
        self.assertEqual(self.doc()["entries"], [])
        il.add_exception(str(self.root), "H9", unit + "/references/keys.md", reason="documented example", now=T0)
        entry = il.add_local_entry(str(self.root), unit, self.local_record(unit, "block"), now=T0)
        self.assertEqual(len(entry["exceptions"]), 1)

    def test_local_entry_refused_on_a_block_finding_of_any_scanner(self) -> None:
        """Fix round 1, F3: H10 comes from the dependency check, not from H1 to H9, and takes
        no exception. Only an override lets the unit in, and the entry is then listed."""
        unit = self.local_unit(extra={"requirements.txt": b"somepackage==1.0\n"})
        record = self.local_record(unit, "block")
        record["findings"] = [{"rule": "H10", "class": "block", "file": "f002", "line": 0, "scanner": "deps"}]
        exc = self.refused("unexcepted-block-finding", il.add_local_entry, str(self.root), unit, record)
        self.assertEqual(exc.hits, [])
        self.assertEqual(self.doc()["entries"], [])
        self.assertFalse(Path(il.record_path(str(self.root), record["id"])).exists())
        il.write_record(str(self.root), record)
        il.override(str(self.root), record["id"], reason="a false advisory, checked by hand",
                    quarantine_root=str(self.q), now=T0)
        entry = il.add_local_entry(str(self.root), unit, record, now=T0)
        self.assertEqual(entry["verdict"], "block")
        state = il.status(str(self.root), quarantine_root=str(self.q))
        self.assertEqual(state["block_entries"], [unit])
        self.assertEqual(il.verify(str(self.root)).block_entries, [unit])

    def test_an_excepted_block_finding_does_not_refuse_the_entry(self) -> None:
        unit = self.local_unit(extra={"references/keys.md": KEY_DOC})
        il.add_exception(str(self.root), "H9", unit + "/references/keys.md", reason="documented example", now=T0)
        record = self.local_record(unit, "caution")
        record["findings"] = [{"rule": "H9", "class": "block", "file": "f001", "line": 3, "excepted": True},
                              {"rule": "C6", "class": "caution", "file": "f002", "line": 1}]
        self.assertEqual(il.add_local_entry(str(self.root), unit, record, now=T0)["verdict"], "caution")
        self.assertEqual(il.status(str(self.root), quarantine_root=str(self.q))["block_entries"], [])

    def test_a_block_verdict_entry_is_listed_by_status_and_verify(self) -> None:
        """Fix round 1, F3: a block from a gap (no sandbox on this host) is entered by design;
        it must not then be invisible."""
        gap = self.local_unit("gap")
        fine = self.local_unit("fine")
        il.add_local_entry(str(self.root), gap, self.local_record(gap, "block", "l-gap"), now=T0)
        il.add_local_entry(str(self.root), fine, self.local_record(fine, "pass", "l-fine"), now=T0)
        self.assertEqual(il.status(str(self.root), quarantine_root=str(self.q))["block_entries"], [gap])
        result = il.verify(str(self.root))
        self.assertEqual((result.ok, result.block_entries), (True, [gap]))

    def test_a_version_control_path_takes_no_exception_and_no_override(self) -> None:
        """Fix round 1, F1: in the repo's own tree too."""
        unit = self.local_unit(extra={".git/config": b"[core]\n"})
        path = unit + "/.git/config"
        record = self.local_record(unit, "block")
        il.write_record(str(self.root), record)
        il.override(str(self.root), record["id"], reason="override in place", quarantine_root=str(self.q), now=T0)
        exc = self.refused("unexcepted-block-hit", il.add_local_entry, str(self.root), unit, record)
        self.assertEqual([(h.rule_id, h.path) for h in exc.hits], [("H7", path)])
        self.refused("rule-takes-no-exception", il.add_exception, str(self.root), "H7", path, reason="r")
        # Even an exception written into the ledger by hand does not let it through.
        doc = self.doc()
        doc["exceptions"].append({"rule": "H7", "path": path, "sha256": hr.sha256_hex(b"[core]\n"),
                                  "reason": "by hand", "time": T0})
        il.save(str(self.root), doc)
        result = il.verify(str(self.root))
        self.assertEqual([(h.rule_id, h.path) for h in result.hits], [("H7", path)])
        self.assertFalse(result.ok)

    def test_local_entry_needs_a_record_of_the_unit_as_it_is(self) -> None:
        unit = self.local_unit()
        record = self.local_record(unit, "pass")
        write(self.root / unit / "notes.md", b"added after the scan\n")
        self.refused("record-does-not-match", il.add_local_entry, str(self.root), unit, record)
        self.refused("unit-not-found", il.add_local_entry, str(self.root), "skills/absent", record)
        self.refused("bad-record", il.add_local_entry, str(self.root), unit, {"id": "x"})

    def test_triage_accept_clears_the_unsigned_caution(self) -> None:
        unit = self.local_unit()
        il.add_local_entry(str(self.root), unit, self.local_record(unit, "caution"), now=T0)
        self.assertTrue(il.get_entry(self.doc(), unit)["unsigned_caution"])
        il.triage(str(self.root), "l-0001", accept=True, reason="read", quarantine_root=str(self.q), now=T1)
        self.assertFalse(il.get_entry(self.doc(), unit)["unsigned_caution"])
        self.assertEqual(il.status(str(self.root), quarantine_root=str(self.q))["unsigned_cautions"], [])

    def test_override_in_place_holds_until_the_unit_changes(self) -> None:
        unit = self.local_unit(extra={"references/keys.md": KEY_DOC})
        record = self.local_record(unit, "block")
        il.write_record(str(self.root), record)
        il.override(str(self.root), record["id"], reason="example values", quarantine_root=str(self.q), now=T0)
        self.assertEqual(self.log()[0]["unit"], unit)
        entry = il.add_local_entry(str(self.root), unit, record, now=T0)
        self.assertEqual(entry["verdict"], "block")
        self.assertTrue(il.verify(str(self.root)).ok)
        state = il.status(str(self.root), quarantine_root=str(self.q))
        self.assertEqual([o["record_id"] for o in state["overrides"]], [record["id"]])
        write(self.root / unit / "SKILL.md", SKILL_MD + b"More.\n")           # any change to the unit
        result = il.verify(str(self.root))
        self.assertFalse(result.ok)
        self.assertEqual([h.rule_id for h in result.hits], ["H9"])
        self.assertEqual([o["record_id"] for o in result.stale_overrides], [record["id"]])
        self.assertEqual(il.status(str(self.root), quarantine_root=str(self.q))["overrides"], [])


class VerifyAndStatusTests(LedgerCase):

    def test_verify_reports_units_without_an_entry_and_entries_without_a_unit(self) -> None:
        self.local_unit("one")
        write(self.root / "agents/helper.md", b"---\nname: helper\ndescription: Helper.\n---\n")
        write(self.root / "agents/README.md", b"# Agents\n")
        write(self.root / "skills/_meta/gates.py", b"print('gate')\n")
        write(self.root / "skills/loose.md", b"loose\n")
        write(self.root / "docs/keys.md", KEY_DOC)                         # outside the enforced roots
        result = il.verify(str(self.root))
        self.assertEqual((result.ok, result.files, result.hits), (False, 6, []))    # with the ledger file
        self.assertEqual(result.missing_entries, ["agents/helper.md", "skills/one"])
        for unit in result.missing_entries:
            il.add_local_entry(str(self.root), unit, self.local_record(unit, "pass", "l-" + unit[-3:-1]), now=T0)
        self.assertTrue(il.verify(str(self.root)).ok)
        shutil.rmtree(self.root / "skills/one")
        result = il.verify(str(self.root))
        self.assertEqual((result.ok, result.orphan_entries), (True, ["skills/one"]))

    def test_verify_checks_paths_that_are_no_unit(self) -> None:
        write(self.root / "skills/_meta/notes.md", KEY_DOC)
        write(self.root / "skills/_meta/blob.pyc", COMPILED)
        hits = il.verify(str(self.root)).hits
        self.assertEqual(sorted((h.rule_id, h.path) for h in hits),
                         [("H8", "skills/_meta/blob.pyc"), ("H9", "skills/_meta/notes.md")])

    def test_a_link_is_a_hit_and_is_never_followed(self) -> None:
        if os.name == "nt":
            self.skipTest("needs a symlink")
        outside = self.tmp / "outside"
        write(outside / "secret.md", KEY_DOC)
        self.local_unit("one")
        os.symlink(str(outside), self.root / "skills/one/linked")
        os.symlink(str(outside / "secret.md"), self.root / "skills/one/file-link")
        items = il.read_items(str(self.root))
        self.assertEqual([(i.path, i.entry, i.data) for i in items if "link" in i.path],
                         [("skills/one/file-link", "symlink", b""), ("skills/one/linked", "symlink", b"")])
        hits = il.verify(str(self.root)).hits
        self.assertEqual(sorted((h.rule_id, h.path) for h in hits),
                         [("H7", "skills/one/file-link"), ("H7", "skills/one/linked")])
        self.refused("file-not-found", il.add_exception, str(self.root), "H9", "skills/one/file-link", reason="r")

    def test_status_lists_what_is_in_force(self) -> None:
        unit = self.local_unit(extra={"references/keys.md": KEY_DOC})
        il.add_exception(str(self.root), "H9", unit + "/references/keys.md", reason="documented example", now=T0)
        il.add_local_entry(str(self.root), unit, self.local_record(unit, "caution"), now=T0)
        waiting = self.bundle({"SKILL.md": SKILL_MD, "keys.md": KEY_DOC}, "block",
                              [{"rule": "H9", "class": "block", "file": "f002", "line": 3}])
        il.override(str(self.root), waiting, reason="reviewed", quarantine_root=str(self.q), now=T0)
        state = il.status(str(self.root), quarantine_root=str(self.q), now=T1)
        self.assertEqual((state["entries"], state["unsigned_cautions"]), (1, [unit]))
        self.assertEqual([(e["rule"], e["path"]) for e in state["exceptions"]], [("H9", unit + "/references/keys.md")])
        self.assertEqual(state["stale_exceptions"], [])
        self.assertEqual([o["record_id"] for o in state["overrides"]], [waiting])
        self.assertEqual([(row["id"], row["state"], row["has_tar"]) for row in state["quarantine"]],
                         [(waiting, "open", True)])
        write(self.root / unit / "references/keys.md", KEY_DOC + b"edited\n")
        state = il.status(str(self.root), quarantine_root=str(self.q), now=T1)
        self.assertEqual((state["exceptions"], len(state["stale_exceptions"])), ([], 1))

    def test_quarantine_retention(self) -> None:
        kept = self.bundle({"SKILL.md": SKILL_MD}, "pass")
        gone = self.bundle({"SKILL.md": SKILL_MD + b"other\n"}, "pass")
        Path(self.q / gone / il.TRIAGE_NAME).write_text("report\n", encoding="utf-8")
        il.triage(str(self.root), gone, accept=False, reason="not wanted", quarantine_root=str(self.q),
                  now="2026-01-01T00:00:00Z")
        rows = {row["id"]: row for row in il.list_quarantine(str(self.q), "2026-03-31T23:59:59Z")}
        self.assertEqual((rows[gone]["state"], rows[gone]["has_tar"], rows[gone]["has_triage"], rows[gone]["expired"]),
                         ("rejected", False, True, False))             # day 89: the report is kept
        self.assertEqual(il.purge_quarantine(str(self.q), "2026-03-31T23:59:59Z"), [])
        self.assertEqual(il.purge_quarantine(str(self.q), "2026-04-01T00:00:00Z"), [gone])     # day 90
        self.assertFalse((self.q / gone).exists())
        self.assertTrue((self.q / kept / il.TAR_NAME).is_file())       # an open bundle never expires
        self.assertEqual([row["id"] for row in il.list_quarantine(str(self.q), "2030-01-01T00:00:00Z")], [kept])

    def test_quarantine_root_resolution(self) -> None:
        from unittest import mock
        with mock.patch.dict(os.environ, {il.QUARANTINE_ENV: str(self.tmp / "from-env")}):
            self.assertEqual(il.resolve_quarantine_root(), str(self.tmp / "from-env"))
            self.assertEqual(il.resolve_quarantine_root(str(self.q)), str(self.q))
            self.assertEqual(il.resolve_quarantine_root(), intake_fetch.resolve_quarantine_root())
        self.assertEqual(il.list_quarantine(str(self.tmp / "absent")), [])


@unittest.skipUnless(GIT, "git is not installed")
class GitSourceTests(LedgerCase):
    """The index source and the baseline, in a temp git repository."""

    def git(self, *args: str) -> None:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        subprocess.run([GIT, "-C", str(self.root)] + list(args), check=True, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q")
        self.local_unit("one", {"scripts/tool.py": b"print('one')\n"})
        self.local_unit("two", {"references/keys.md": KEY_DOC})
        write(self.root / "agents/helper.md", b"---\nname: helper\ndescription: Helper.\n---\n")
        write(self.root / "workflows/README.md", b"# Workflows\n")
        write(self.root / "skills/_meta/gates.py", b"print('gate')\n")
        os.chmod(self.root / "skills/one/scripts/tool.py", 0o755)
        write(self.root / ".gitignore", b"__pycache__/\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "tree")

    def scan_unit(self, unit, records, digest) -> dict:
        self.seen[unit] = [r.path for r in records]
        findings = [f.to_dict() for f in hr.scan(records, "skill")]
        verdict = "block" if any(f["class"] == "block" for f in findings) else ("caution" if findings else "pass")
        return make_record("b-" + unit.replace("/", "-").replace(".", "-"), verdict, digest, findings=findings, unit=unit)

    def test_sources(self) -> None:
        write(self.root / "skills/one/scripts/__pycache__/tool.cpython-313.pyc", COMPILED)   # ignored
        write(self.root / "skills/one/new.md", b"untracked\n")                               # untracked
        root = str(self.root)
        index = [i.path for i in il.read_items(root, il.SOURCE_INDEX)]
        worktree = [i.path for i in il.read_items(root, il.SOURCE_WORKTREE)]
        walk = [i.path for i in il.read_items(root, il.SOURCE_WALK)]
        self.assertNotIn("skills/one/new.md", index)
        self.assertEqual(sorted(set(worktree) - set(index)), ["skills/one/new.md"])
        self.assertEqual(sorted(set(walk) - set(worktree)), ["skills/one/scripts/__pycache__/tool.cpython-313.pyc"])
        self.assertEqual([i.path for i in il.read_items(root)], worktree)                   # auto in a checkout
        self.assertEqual(il.list_units(il.read_items(root, il.SOURCE_INDEX)),
                         ["agents/helper.md", "skills/one", "skills/two"])

    def test_index_source_reads_staged_content_not_the_disk(self) -> None:
        root = str(self.root)
        before = il.unit_tree_digest(root, "skills/one", il.SOURCE_INDEX)
        self.assertEqual(before, il.unit_tree_digest(root, "skills/one", il.SOURCE_WORKTREE))
        write(self.root / "skills/one/SKILL.md", SKILL_MD + KEY_DOC)
        self.assertEqual(il.unit_tree_digest(root, "skills/one", il.SOURCE_INDEX), before)
        self.assertEqual(il.block_hits(il.unit_items(root, "skills/one", il.SOURCE_INDEX)), [])
        self.git("add", "skills/one/SKILL.md")
        staged = il.unit_items(root, "skills/one", il.SOURCE_INDEX)
        self.assertEqual([h.rule_id for h in il.block_hits(staged)], ["H9"])
        tool = [i for i in staged if i.path.endswith("tool.py")][0]
        self.assertEqual((tool.mode, tool.data), (0o755, b"print('one')\n"))

    def test_baseline_enters_every_unit_from_tracked_blobs(self) -> None:
        write(self.root / "skills/one/scripts/__pycache__/tool.cpython-313.pyc", COMPILED)
        self.seen = {}
        report = il.baseline(str(self.root), self.scan_unit, now=T0)
        self.assertEqual(report["units"], ["agents/helper.md", "skills/one", "skills/two"])
        self.assertEqual(report["verdicts"], {"pass": 2, "caution": 0, "block": 1})
        self.assertEqual(report["block_hits"], {"H9": 1})                # the ignored file never appears
        self.assertEqual([(h.rule_id, h.path) for h in report["unexcepted"]],
                         [("H9", "skills/two/references/keys.md")])
        self.assertEqual(self.seen["skills/one"], ["SKILL.md", "scripts/tool.py"])     # unit-relative paths
        self.assertEqual(self.seen["agents/helper.md"], ["helper.md"])
        doc = self.doc()
        self.assertEqual([(e["unit"], e["origin"], e["verdict"]) for e in doc["entries"]],
                         [("agents/helper.md", "baseline", "pass"), ("skills/one", "baseline", "pass"),
                          ("skills/two", "baseline", "block")])
        for entry in doc["entries"]:
            self.assertTrue(Path(il.record_path(str(self.root), entry["record_id"])).is_file())
        # Report-only: the hit is then excepted one by one, and the tree verifies.
        self.assertFalse(il.verify(str(self.root), source=il.SOURCE_INDEX).ok)
        il.add_exception(str(self.root), "H9", "skills/two/references/keys.md", reason="documented example", now=T0)
        self.assertTrue(il.verify(str(self.root), source=il.SOURCE_INDEX).ok)
        self.assertEqual(len(il.get_entry(self.doc(), "skills/two")["exceptions"]), 1)


# --------------------------------------------------------------------------------------
# Digest, records, module hygiene
# --------------------------------------------------------------------------------------

class DigestTests(LedgerCase):

    def test_unit_digest_equals_the_fetch_digest_of_the_same_folder(self) -> None:
        unit = self.local_unit(extra={"scripts/tool.py": b"print(1)\n", "a/b/c.txt": b"", "z.md": b"z\n"})
        os.chmod(self.root / unit / "scripts/tool.py", 0o755)
        result = intake_fetch.fetch(str(self.root / unit), quarantine_root=str(self.q))
        self.assertTrue(result.ok)
        self.assertEqual(il.unit_tree_digest(str(self.root), unit), result.inventory["tree_digest"])

    def test_digest_changes_with_content_mode_and_name(self) -> None:
        unit = self.local_unit(extra={"scripts/tool.py": b"print(1)\n"})
        seen = {il.unit_tree_digest(str(self.root), unit)}
        write(self.root / unit / "scripts/tool.py", b"print(2)\n")
        seen.add(il.unit_tree_digest(str(self.root), unit))
        if os.name != "nt":
            os.chmod(self.root / unit / "scripts/tool.py", 0o755)
            seen.add(il.unit_tree_digest(str(self.root), unit))
        os.rename(self.root / unit / "scripts/tool.py", self.root / unit / "scripts/other.py")
        seen.add(il.unit_tree_digest(str(self.root), unit))
        self.assertEqual(len(seen), 3 if os.name == "nt" else 4)

    def test_oversize_file_is_listed_without_content(self) -> None:
        unit = self.local_unit()
        with open(self.root / unit / "big.txt", "wb") as fh:
            fh.truncate(hr.MAX_FILE_BYTES + 1)
        item = [i for i in il.unit_items(str(self.root), unit) if i.path.endswith("big.txt")][0]
        self.assertEqual((item.data, item.size), (b"", hr.MAX_FILE_BYTES + 1))
        self.assertEqual([(h.rule_id, h.path) for h in il.verify(str(self.root)).hits], [("H7", unit + "/big.txt")])


class ModuleTests(unittest.TestCase):

    SOURCE = SCRIPTS / "intake_ledger.py"

    def test_stdlib_only_and_no_import_of_the_siblings_at_load(self) -> None:
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported - set(sys.stdlib_module_names), set())
        self.assertFalse(imported & {"harness_rules", "intake_fetch"})

    def test_import_has_no_side_effects(self) -> None:
        code = ("import os, sys; sys.path.insert(0, %r); before = set(os.listdir('.')); import intake_ledger; "
                "assert 'harness_rules' not in sys.modules and 'intake_fetch' not in sys.modules; "
                "assert set(os.listdir('.')) == before; print('ok')") % str(SCRIPTS)
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=cwd, capture_output=True, text=True)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, "ok"), proc.stderr)

    def test_loads_by_path_from_another_directory(self) -> None:
        # The hook and the installer load the file by path; the rule set comes from beside it.
        code = ("import importlib.util, sys; spec = importlib.util.spec_from_file_location('il_by_path', %r); "
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
                "print(m.unit_for_path('skills/a/b'), m.validate(m.empty())['schema'])") % str(self.SOURCE)
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=cwd, capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), "skills/a intake-ledger.v1", proc.stderr)

    def test_own_files_are_ascii_and_scan_clean(self) -> None:
        for path in (self.SOURCE, Path(__file__).resolve()):
            data = path.read_bytes()
            self.assertTrue(data.isascii(), path.name)
            record = hr.FileRecord("f001", path.name, 0o644, data)
            self.assertEqual(hr.scan_blocks([record]), [], path.name)

    def test_refusal_text_is_fixed(self) -> None:
        exc = il.LedgerRefused("block-not-overridden")
        self.assertEqual(str(exc), "the record is a block with no override for this tree")
        with self.assertRaises(KeyError):
            il.LedgerRefused("made-up-code")


# --------------------------------------------------------------------------------------
# Fix round 2
# --------------------------------------------------------------------------------------

LAYOUT = {"HEAD": b"ref: refs/heads/main\n",
          "config": b"[core]\n\tbare = false\n\tworktree = .\n\tfsmonitor = \"touch PROBE_MARKER_FILE; false\"\n",
          "objects/info/packs": b"\n", "refs/heads/keep.txt": b"x\n"}
H7_FINDING = [{"rule": "H7", "class": "block", "file": "f002", "line": 0}]


def layout_files(prefix: str) -> dict:
    files = {"SKILL.md": SKILL_MD}
    files.update({prefix + rel: data for rel, data in LAYOUT.items()})
    return files


def git_dir_answer(directory) -> tuple:
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=os.path.dirname(os.path.abspath(str(directory))),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    proc = subprocess.run(["git", "-C", str(directory), "rev-parse", "--git-dir"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def files_under(directory: Path) -> list:
    return sorted(str(p.relative_to(directory)).replace(os.sep, "/") for p in directory.rglob("*") if p.is_file())


class RepositoryLayoutTests(LedgerCase):
    """Fix round 2, G1: a directory git takes for a repository by what it holds."""

    def test_adopt_under_an_override_writes_none_of_a_layout_one_level_down(self) -> None:
        rid = self.bundle(layout_files("data/"), "block", H7_FINDING)
        self.refused("block-not-overridden", self.adopt, rid, "skills/taken")
        il.override(str(self.root), rid, reason="the skill file was read", quarantine_root=str(self.q), now=T0)
        self.adopt(rid, "skills/taken")
        dest = self.root / "skills/taken"
        self.assertEqual(files_under(dest), ["SKILL.md"])
        if GIT:
            self.assertNotEqual(git_dir_answer(dest), (0, "."))
        self.assertTrue(il.verify(str(self.root)).ok)

    def test_adopt_of_a_layout_at_the_root_has_nothing_to_write(self) -> None:
        rid = self.bundle(layout_files(""), "block", H7_FINDING)
        il.override(str(self.root), rid, reason="looked fine", quarantine_root=str(self.q), now=T0)
        self.refused("nothing-to-adopt", self.adopt, rid, "skills/taken")
        self.assertFalse((self.root / "skills/taken").exists())
        self.assertEqual(self.doc()["entries"], [])

    def test_adopt_refuses_a_bundle_that_stores_a_layout_even_under_an_override(self) -> None:
        """Acquisition does not store one; if a bundle holds one all the same, nothing takes it in."""
        with mock.patch.object(intake_fetch, "repo_layout_dirs", return_value=frozenset()):
            forged = self.bundle(layout_files("data/"), "block", H7_FINDING)
        stored = sorted(e.path for e in intake_fetch.iter_bundle_entries(str(self.q / forged))
                        if e.entry == "file" and e.size is None)
        self.assertEqual(stored, ["SKILL.md"] + sorted("data/" + rel for rel in LAYOUT))
        il.override(str(self.root), forged, reason="looked fine", quarantine_root=str(self.q), now=T0)
        before = Path(il.ledger_path(str(self.root))).read_bytes()
        self.refused("vcs-control-path", self.adopt, forged, "skills/taken")
        self.assertFalse((self.root / "skills/taken").exists())
        self.assertEqual(Path(il.ledger_path(str(self.root))).read_bytes(), before)

    def test_a_layout_in_the_tree_takes_no_exception_and_no_override(self) -> None:
        unit = self.local_unit(extra={"data/" + rel: data for rel, data in LAYOUT.items()})
        under = sorted(unit + "/data/" + rel for rel in LAYOUT)
        record = self.local_record(unit, "block")
        il.write_record(str(self.root), record)
        il.override(str(self.root), record["id"], reason="override in place", quarantine_root=str(self.q), now=T0)
        exc = self.refused("unexcepted-block-hit", il.add_local_entry, str(self.root), unit, record)
        self.assertEqual(sorted((h.rule_id, h.path) for h in exc.hits), [("H7", path) for path in under])
        self.refused("rule-takes-no-exception", il.add_exception, str(self.root), "H7", under[0], reason="r")
        doc = self.doc()
        for path in under:
            data = (self.root / path).read_bytes()
            doc["exceptions"].append({"rule": "H7", "path": path, "sha256": hr.sha256_hex(data),
                                      "reason": "by hand", "time": T0})
        il.save(str(self.root), doc)
        result = il.verify(str(self.root))
        self.assertEqual(sorted((h.rule_id, h.path) for h in result.hits), [("H7", path) for path in under])
        self.assertFalse(result.ok)

    def test_verify_sees_a_layout_among_files_that_belong_to_no_unit(self) -> None:
        write(self.root / "skills/_meta/vendored/HEAD", LAYOUT["HEAD"])
        self.assertTrue(il.verify(str(self.root)).ok)                  # a file called HEAD is a file
        write(self.root / "skills/_meta/vendored/config", LAYOUT["config"])
        result = il.verify(str(self.root))
        self.assertEqual(sorted((h.rule_id, h.path) for h in result.hits),
                         [("H7", "skills/_meta/vendored/HEAD"), ("H7", "skills/_meta/vendored/config")])

    def test_the_hit_on_one_file_counts_the_paths_beside_it(self) -> None:
        """What the commit hook passes: the staged file, and every tracked path as context."""
        write(self.root / "skills/_meta/vendored/HEAD", LAYOUT["HEAD"])
        items = il.read_items(str(self.root), il.SOURCE_WALK, ["skills/_meta/vendored/HEAD"])
        doc = self.doc()
        self.assertEqual(il.unexcepted_hits(doc, items), [])
        hits = il.unexcepted_hits(doc, items, context_paths=["skills/_meta/vendored/objects/x",
                                                             "skills/_meta/vendored/refs/y"])
        self.assertEqual([(h.rule_id, h.path) for h in hits], [("H7", "skills/_meta/vendored/HEAD")])


class AdoptedFlagTests(LedgerCase):
    """Fix round 2, g3: a later local scan must not make an adopted unit's file names print."""

    NAME = "notes/ignore-all-previous-instructions.md"

    def test_a_later_local_scan_keeps_the_names_withheld(self) -> None:
        rid = self.bundle({"SKILL.md": SKILL_MD, self.NAME: b"plain\n"}, "pass")
        entry = self.adopt(rid, "skills/taken")
        self.assertEqual((entry["origin"], entry.get("adopted")), ("adopt", True))
        record = self.local_record("skills/taken", "pass", "l-0002")
        il.add_local_entry(str(self.root), "skills/taken", record, now=T1)
        doc = self.doc()
        entry = il.get_entry(doc, "skills/taken")
        self.assertEqual((entry["origin"], entry.get("adopted")), ("local", True))
        self.assertTrue(il.is_adopted(entry))
        shown = il.show_path(doc, "skills/taken/" + self.NAME, "ab" * 32)
        self.assertEqual(shown, "skills/taken/(name withheld) sha256 abababababab")

    def test_an_entry_made_before_the_flag_existed_gets_it_on_the_next_scan(self) -> None:
        unit = self.local_unit("older", {self.NAME: b"plain\n"})
        il.add_entry(str(self.root), unit, kind="skill", record_id="q-older", digest="0" * 64,
                     verdict="pass", unsigned_caution=False, origin="adopt", now=T0)
        doc = self.doc()
        entry = il.get_entry(doc, unit)
        entry.pop("adopted", None)
        il.save(str(self.root), doc)
        self.assertTrue(il.is_adopted(il.get_entry(self.doc(), unit)))
        il.add_local_entry(str(self.root), unit, self.local_record(unit, "pass"), now=T1)
        doc = self.doc()
        self.assertEqual((il.get_entry(doc, unit)["origin"], il.get_entry(doc, unit).get("adopted")), ("local", True))
        self.assertIn("(name withheld)", il.show_path(doc, unit + "/" + self.NAME))

    def test_a_unit_written_here_is_not_marked(self) -> None:
        unit = self.local_unit("mine", {self.NAME: b"plain\n"})
        il.add_local_entry(str(self.root), unit, self.local_record(unit, "pass"), now=T0)
        doc = self.doc()
        self.assertNotIn("adopted", il.get_entry(doc, unit))
        self.assertFalse(il.is_adopted(il.get_entry(doc, unit)))
        self.assertEqual(il.show_path(doc, unit + "/" + self.NAME), unit + "/" + self.NAME)

    def test_the_flag_must_be_a_boolean(self) -> None:
        unit = self.local_unit("mine")
        il.add_local_entry(str(self.root), unit, self.local_record(unit, "pass"), now=T0)
        doc = self.doc()
        il.get_entry(doc, unit)["adopted"] = "yes"
        with self.assertRaises(il.LedgerMalformed):
            il.validate(doc)


class LongLineExceptionTests(LedgerCase):
    """Fix round 2, g4: an over-long line in a markdown file can be wrapped, and the line the
    patterns never read may be the grant itself. A script that cannot be re-wrapped may be excepted."""

    def test_except_refuses_h11_on_markdown_and_takes_it_on_a_script(self) -> None:
        long_line = b"x" * (hr.MAX_LINE_CHARS + 1) + b"\n"
        unit = self.local_unit(extra={"notes.md": b"# Notes\n" + long_line, "Deep/Guide.MDX": long_line,
                                      "vendor.min.js": b"/* vendored */\n" + long_line})
        hits = sorted((h.rule_id, h.path) for h in il.verify(str(self.root)).hits)
        self.assertEqual(hits, [("H11", unit + "/Deep/Guide.MDX"), ("H11", unit + "/notes.md"),
                                ("H11", unit + "/vendor.min.js")])
        for name in ("notes.md", "Deep/Guide.MDX"):
            self.refused("rule-takes-no-exception", il.add_exception, str(self.root), "H11",
                         unit + "/" + name, reason="it is long")
        self.assertEqual(self.log(), [])
        il.add_exception(str(self.root), "H11", unit + "/vendor.min.js", reason="vendored, minified", now=T0)
        self.assertEqual(sorted((h.rule_id, h.path) for h in il.verify(str(self.root)).hits),
                         [("H11", unit + "/Deep/Guide.MDX"), ("H11", unit + "/notes.md")])


if __name__ == "__main__":
    unittest.main()
