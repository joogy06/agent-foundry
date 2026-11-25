#!/usr/bin/env python3
"""Tests for skill_frontmatter.py (#344 WP-2): one reader for custom frontmatter keys.

    python -m pytest skills/_meta/tests/test_skill_frontmatter.py -v

A custom key may sit at the top level (the layout this library grew up with) or under
`metadata:` (the skill standard). Every case below runs on BOTH parsers -- PyYAML and
the line reader -- because the line reader is what serves a host without PyYAML and a
frontmatter that is not valid YAML, and the two must never disagree.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

META = Path(__file__).resolve().parent.parent
SKILLS = META.parent
sys.path.insert(0, str(META))

import skill_frontmatter as sf  # noqa: E402
import skill_overlap  # noqa: E402
import skill_resolve  # noqa: E402

ENGINES = ("yaml", "lines") if sf.have_yaml() else ("lines",)
CUSTOM_KEYS = ("disambiguation", "family", "applies_when", "version")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


assess = _load("intake_assess", SKILLS / "skill-intake" / "scripts" / "assess.py")
claims_lint = _load("claims_lint_under_test", SKILLS / "business-edge" / "scripts" / "claims_lint.py")


class BothEngines(unittest.TestCase):
    """Each assertion is made once per parser."""

    def each(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                yield engine

    def test_top_level_layout(self):
        fm = "name: x\ndescription: A skill.\nfamily: rhel\ndisambiguation: Does X. Y is other-skill.\n"
        for e in self.each():
            self.assertTrue(sf.has(fm, "family", engine=e))
            self.assertEqual(sf.value(fm, "family", engine=e), "rhel")
            self.assertEqual(sf.value(fm, "disambiguation", engine=e), "Does X. Y is other-skill.")
            self.assertEqual(sf.read(fm, "family", engine=e).source, "top")

    def test_metadata_layout(self):
        fm = ('name: x\ndescription: A skill.\nmetadata:\n  family: "rhel"\n'
              "  disambiguation: 'Does X. Y is other-skill.'\n  version: \"1.1.0\"\n")
        for e in self.each():
            self.assertTrue(sf.has(fm, "family", engine=e))
            self.assertEqual(sf.value(fm, "family", engine=e), "rhel")
            self.assertEqual(sf.value(fm, "disambiguation", engine=e), "Does X. Y is other-skill.")
            self.assertEqual(sf.value(fm, "version", engine=e), "1.1.0")
            self.assertEqual(sf.read(fm, "family", engine=e).source, "metadata")

    def test_absent_key(self):
        fm = 'name: x\ndescription: A skill.\nmetadata:\n  other: "y"\n'
        for e in self.each():
            self.assertFalse(sf.has(fm, "family", engine=e))
            self.assertIsNone(sf.value(fm, "family", engine=e))
            self.assertEqual(sf.read(fm, "family", engine=e).status, sf.OK)

    def test_both_present_and_equal(self):
        fm = 'name: x\nfamily: rhel\nmetadata:\n  family: "rhel"\n'
        for e in self.each():
            self.assertTrue(sf.has(fm, "family", engine=e))
            self.assertEqual(sf.value(fm, "family", engine=e), "rhel")
            self.assertEqual(sf.read(fm, "family", engine=e).source, "both")

    def test_both_present_and_different_names_the_file_and_the_key(self):
        fm = 'name: x\nfamily: rhel\nmetadata:\n  family: "ubuntu"\n'
        for e in self.each():
            for call in (sf.has, sf.value, sf.read):
                with self.assertRaises(sf.FrontmatterConflict) as ctx:
                    call(fm, "family", path="skills/x/SKILL.md", engine=e)
                self.assertEqual(ctx.exception.key, "family")
                self.assertEqual(ctx.exception.path, "skills/x/SKILL.md")
                self.assertIn("skills/x/SKILL.md", str(ctx.exception))
                self.assertIn("`family`", str(ctx.exception))
                self.assertIn("rhel", str(ctx.exception))
                self.assertIn("ubuntu", str(ctx.exception))

    def test_precedence_is_metadata_first(self):
        # Equal values: the answer is attributed to both. One side absent: that side wins.
        only_meta = 'name: x\nmetadata:\n  family: "m"\n'
        only_top = "name: x\nfamily: t\nmetadata:\n  other: \"o\"\n"
        for e in self.each():
            self.assertEqual(sf.value(only_meta, "family", engine=e), "m")
            self.assertEqual(sf.value(only_top, "family", engine=e), "t")

    def test_empty_value_is_present_and_empty(self):
        for fm in ("name: x\ndisambiguation:\nfamily: f\n",
                   'name: x\ndisambiguation: ""\n',
                   "name: x\nmetadata:\n  disambiguation: ''\n",
                   'name: x\nmetadata:\n  disambiguation: ""\n  other: "o"\n'):
            for e in self.each():
                self.assertTrue(sf.has(fm, "disambiguation", engine=e), fm)
                self.assertEqual(sf.value(fm, "disambiguation", engine=e), "", fm)

    def test_escaped_quotes(self):
        fm = ('name: x\nmetadata:\n'
              '  disambiguation: "The \\"fast\\" path and a back\\\\slash."\n'
              "  family: 'it''s one'\n")
        for e in self.each():
            self.assertEqual(sf.value(fm, "disambiguation", engine=e), 'The "fast" path and a back\\slash.')
            self.assertEqual(sf.value(fm, "family", engine=e), "it's one")

    def test_hash_inside_a_quoted_value_is_not_a_comment(self):
        fm = ('name: x\nfamily: "seo #1 # not a comment"   # a real comment\n'
              "metadata:\n  disambiguation: 'issue #344 # kept'  # dropped\n")
        for e in self.each():
            self.assertEqual(sf.value(fm, "family", engine=e), "seo #1 # not a comment")
            self.assertEqual(sf.value(fm, "disambiguation", engine=e), "issue #344 # kept")

    def test_plain_value_drops_a_trailing_comment(self):
        fm = "name: x\nfamily: rhel # the red hat family\n"
        for e in self.each():
            self.assertEqual(sf.value(fm, "family", engine=e), "rhel")

    def test_indented_key_inside_a_folded_description_does_not_match(self):
        fm = ("name: x\ndescription: >\n  Use it for things.\n"
              "  disambiguation: this is prose inside the description\n"
              "  family: also prose\n")
        for e in self.each():
            self.assertFalse(sf.has(fm, "disambiguation", engine=e))
            self.assertIsNone(sf.value(fm, "family", engine=e))

    def test_a_key_nested_under_another_parent_does_not_match(self):
        fm = 'name: x\nhooks:\n  family: "not metadata"\n'
        for e in self.each():
            self.assertFalse(sf.has(fm, "family", engine=e))

    def test_malformed_metadata_is_unsupported_never_guessed(self):
        for fm in ("name: x\nmetadata: just a string\nfamily: rhel\n",
                   "name: x\nmetadata:\n  - family\n  - rhel\nfamily: rhel\n"):
            for e in self.each():
                found = sf.read(fm, "family", engine=e)
                self.assertEqual(found.status, sf.UNSUPPORTED, fm)
                self.assertIsNone(found.present, fm)
                with self.assertRaises(sf.FrontmatterUnsupported) as ctx:
                    sf.has(fm, "family", path="p/SKILL.md", engine=e)
                self.assertIn("p/SKILL.md", str(ctx.exception))
                with self.assertRaises(sf.FrontmatterUnsupported):
                    sf.value(fm, "family", engine=e)

    def test_empty_metadata_falls_through_to_the_top_level(self):
        for fm in ("name: x\nmetadata:\nfamily: rhel\n", "name: x\nfamily: rhel\nmetadata:\n"):
            for e in self.each():
                self.assertEqual(sf.value(fm, "family", engine=e), "rhel", fm)

    def test_crlf(self):
        fm = ('name: x\r\ndescription: A skill.\r\nfamily: rhel\r\n'
              'metadata:\r\n  disambiguation: "Does X."\r\n  version: "1.1.0"\r\n')
        for e in self.each():
            self.assertEqual(sf.value(fm, "family", engine=e), "rhel")
            self.assertEqual(sf.value(fm, "disambiguation", engine=e), "Does X.")
            self.assertEqual(sf.value(fm, "version", engine=e), "1.1.0")

    def test_an_unquoted_number_keeps_its_source_text(self):
        # YAML reads `1.10` as the float 1.1; a reader wants what the author wrote.
        fm = "name: x\nversion: 1.10\nfamily: 7\n"
        for e in self.each():
            self.assertEqual(sf.value(fm, "version", engine=e), "1.10")
            self.assertEqual(sf.value(fm, "family", engine=e), "7")

    def test_a_non_scalar_value_is_present_but_its_value_is_unsupported(self):
        fm = "name: x\napplies_when:\n  os_family: rhel\n"
        for e in self.each():
            self.assertTrue(sf.has(fm, "applies_when", engine=e))
            self.assertEqual(sf.read(fm, "applies_when", engine=e).status, sf.UNSUPPORTED)
            with self.assertRaises(sf.FrontmatterUnsupported):
                sf.value(fm, "applies_when", engine=e)


class LineReaderOnly(unittest.TestCase):
    """Forms the line reader must refuse instead of guessing."""

    def unsupported(self, fm: str, key: str = "family") -> sf.Lookup:
        found = sf.read(fm, key, engine="lines")
        self.assertEqual(found.status, sf.UNSUPPORTED, fm)
        return found

    def test_flow_map_metadata(self):
        self.assertIsNone(self.unsupported('name: x\nmetadata: {family: "rhel"}\n').present)

    def test_block_scalar_under_metadata(self):
        self.assertIsNone(self.unsupported("name: x\nmetadata:\n  family: >\n    rhel\n").present)

    def test_tab_indentation_under_metadata(self):
        self.assertIsNone(self.unsupported('name: x\nmetadata:\n\tfamily: "rhel"\n').present)

    def test_four_space_children(self):
        self.assertIsNone(self.unsupported('name: x\nmetadata:\n    family: "rhel"\n').present)

    def test_block_scalar_at_the_top_level(self):
        found = self.unsupported("name: x\nfamily: |\n  rhel\n")
        self.assertTrue(found.present)

    def test_quoted_value_that_runs_onto_the_next_line(self):
        self.assertTrue(self.unsupported('name: x\nfamily: "rhel\n  and more"\n').present)
        self.assertTrue(self.unsupported('name: x\nmetadata:\n  family: "rhel\n').present)

    def test_duplicated_key(self):
        self.assertIsNone(self.unsupported("name: x\nfamily: a\nfamily: b\n").present)
        self.assertIsNone(self.unsupported('name: x\nmetadata:\n  family: "a"\n  family: "b"\n').present)

    def test_unknown_escape(self):
        self.assertTrue(self.unsupported('name: x\nmetadata:\n  family: "a\\qb"\n').present)

    def test_one_unreadable_copy_cannot_be_compared(self):
        found = self.unsupported('name: x\nfamily: |\n  rhel\nmetadata:\n  family: "rhel"\n')
        self.assertEqual(found.source, "both")

    def test_invalid_yaml_falls_back_to_the_line_reader(self):
        # The break frontmatter_lint exists for: an unquoted `: ` in a description.
        fm = ('name: x\ndescription: Use when: things happen\nfamily: rhel\n'
              'metadata:\n  disambiguation: "Does X."\n')
        found = sf.read(fm, "family")
        self.assertEqual((found.status, found.value, found.engine), (sf.OK, "rhel", "lines"))
        self.assertEqual(sf.value(fm, "disambiguation"), "Does X.")
        if sf.have_yaml():
            self.assertEqual(sf.read(fm, "family", engine="yaml").status, sf.UNSUPPORTED)

    def test_unicode_and_hex_escapes(self):
        fm = 'name: x\nmetadata:\n  family: "a\\u2192b\\x41\\tc"\n'
        for engine in ENGINES:
            self.assertEqual(sf.value(fm, "family", engine=engine), "a→bA\tc")


class EnginesAgreeOnConflicts(unittest.TestCase):
    """#344 fix round 1 (F5). The line reader may refuse what PyYAML reads, but it must
    never return a value PyYAML contradicts, and both refuse a duplicated key."""

    QUOTED_PARENT = 'name: x\nfamily: ubuntu\n"metadata":\n  family: "rhel"\n'

    def test_a_quoted_metadata_key_does_not_hide_a_conflict(self):
        """The line reader returned `ubuntu` here while PyYAML raised the conflict."""
        for engine in ENGINES:
            with self.subTest(engine=engine), self.assertRaises(sf.FrontmatterConflict) as ctx:
                sf.read(self.QUOTED_PARENT, "family", path="p/SKILL.md", engine=engine)
            self.assertEqual((ctx.exception.top, ctx.exception.meta), ("ubuntu", "rhel"))

    def test_a_quoted_parent_or_a_quoted_key_reads_like_a_bare_one(self):
        for fm in ('name: x\n"metadata":\n  family: "rhel"\n',
                   "name: x\n'metadata':\n  family: rhel\n",
                   'name: x\n"family": rhel\n', "name: x\n'family': \"rhel\"\n"):
            for engine in ENGINES:
                with self.subTest(fm=fm, engine=engine):
                    self.assertEqual(sf.value(fm, "family", engine=engine), "rhel")

    def test_a_quoted_and_a_bare_copy_of_one_key_are_a_duplicate(self):
        fm = 'name: x\nfamily: a\n"family": b\n'
        for engine in ENGINES:
            with self.subTest(engine=engine):
                found = sf.read(fm, "family", engine=engine)
                self.assertEqual((found.status, found.present), (sf.UNSUPPORTED, None))

    def test_a_duplicated_key_is_unsupported_in_both_engines(self):
        """PyYAML silently kept the last copy; the line reader said unsupported."""
        for fm in ("name: x\nfamily: a\nfamily: b\n",
                   'name: x\nmetadata:\n  family: "a"\n  family: "b"\n',
                   'name: x\nmetadata:\n  family: "a"\nmetadata:\n  family: "a"\n'):
            for engine in ENGINES:
                with self.subTest(fm=fm, engine=engine):
                    found = sf.read(fm, "family", engine=engine)
                    self.assertEqual((found.status, found.present), (sf.UNSUPPORTED, None))
                    with self.assertRaises(sf.FrontmatterUnsupported):
                        sf.value(fm, "family", engine=engine)
            self.assertEqual(sf.read(fm, "family").status, sf.UNSUPPORTED, "auto")

    def test_a_duplicate_of_another_key_does_not_disturb_this_one(self):
        fm = "name: x\nlicense: a\nlicense: b\nfamily: rhel\n"
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.assertEqual(sf.value(fm, "family", engine=engine), "rhel")

    def test_the_line_reader_refuses_mapping_syntax_it_cannot_parse(self):
        """A top-level flow map read as ABSENT: the key was there and the answer was no."""
        for fm in ("{family: rhel, name: x}\n", "name: x\n? family\n: rhel\n",
                   'name: x\n"family" : rhel # spaced\n{other: 1}\n',
                   "name: x\n!!str family: rhel\n", 'name: x\n"fam\\qily": rhel\n'):
            with self.subTest(fm=fm):
                found = sf.read(fm, "family", engine="lines")
                self.assertEqual((found.status, found.present), (sf.UNSUPPORTED, None), fm)
                with self.assertRaises(sf.FrontmatterUnsupported):
                    sf.has(fm, "family", engine="lines")

    def test_the_line_reader_never_contradicts_pyyaml(self):
        """Wherever both give an answer it is the same answer; where the line reader
        gives one and PyYAML raises a conflict, that is the bug F5 reports."""
        if not sf.have_yaml():
            self.skipTest("PyYAML is not importable")
        shapes = [self.QUOTED_PARENT, "{family: rhel}\n",
                  'family: a\n"metadata": {family: b}\n',
                  "family: a\n'metadata':\n  family: b\n",
                  '"family": a\nmetadata:\n  "family": b\n',
                  "family: a\nmetadata:\n  family: a\n", "name: x\n"]
        for fm in shapes:
            with self.subTest(fm=fm):
                def ask(engine):
                    try:
                        return sf.read(fm, "family", engine=engine)
                    except sf.FrontmatterConflict:
                        return "conflict"
                by_yaml, by_lines = ask("yaml"), ask("lines")
                if by_lines == "conflict" or by_yaml == "conflict":
                    self.assertTrue(by_lines == "conflict" or by_lines.status == sf.UNSUPPORTED)
                    self.assertTrue(by_yaml == "conflict" or by_yaml.status == sf.UNSUPPORTED)
                elif by_lines.status == sf.OK and by_yaml.status == sf.OK:
                    self.assertEqual((by_lines.present, by_lines.value),
                                     (by_yaml.present, by_yaml.value))


class FrontmatterOf(unittest.TestCase):
    def test_cuts_the_block_and_accepts_crlf(self):
        self.assertEqual(sf.frontmatter_of("---\nname: x\n---\n# body\n---\n"), "name: x\n")
        self.assertEqual(sf.frontmatter_of("---\r\nname: x\r\n---\r\n# body\r\n"), "name: x\r\n")

    def test_no_frontmatter(self):
        self.assertIsNone(sf.frontmatter_of("# just a body\n"))
        self.assertIsNone(sf.frontmatter_of("---\nname: x\nnever closed\n"))

    def test_a_dashed_line_inside_a_value_is_not_the_end(self):
        self.assertEqual(sf.frontmatter_of("---\nname: x\ndescription: a --- b\n---\nbody\n"),
                         "name: x\ndescription: a --- b\n")


@unittest.skipUnless(sf.have_yaml(), "PyYAML is not importable: there is no second parser to compare")
class Agreement(unittest.TestCase):
    """The YAML path and the line reader give the same answer for every SKILL.md in the tree."""

    def test_every_skill_md_in_the_tree(self):
        files = sorted(SKILLS.glob("**/SKILL.md"))
        self.assertGreater(len(files), 100, "the tree walk found too few skills to mean anything")
        compared = agreed_present = unsupported = 0
        disagreements = []
        for path in files:
            fm = sf.frontmatter_of(path.read_text(encoding="utf-8", errors="ignore"))
            if fm is None:
                continue
            keys = set(CUSTOM_KEYS)
            for line in fm.replace("\r\n", "\n").split("\n"):
                m = sf._TOP_RE.match(line.rstrip())
                if m:
                    keys.add(m.group(1))
                m = sf._CHILD_RE.match(line[2:].rstrip()) if line.startswith("  ") else None
                if m:
                    keys.add(m.group(1))
            keys.discard("metadata")
            for key in sorted(keys):
                by_yaml = sf.read(fm, key, path=path, engine="yaml")
                by_lines = sf.read(fm, key, path=path, engine="lines")
                compared += 1
                if sf.UNSUPPORTED in (by_yaml.status, by_lines.status):
                    unsupported += 1
                    continue
                if (by_yaml.present, by_yaml.value, by_yaml.source) != (
                        by_lines.present, by_lines.value, by_lines.source):
                    disagreements.append((str(path.relative_to(SKILLS)), key, by_yaml, by_lines))
                elif by_yaml.present:
                    agreed_present += 1
        self.assertEqual(disagreements, [])
        # Not vacuous: most comparisons are real ones, and many of them found a value.
        self.assertGreater(agreed_present, len(files))
        self.assertLess(unsupported, compared / 2)

    def test_auto_equals_the_line_reader_wherever_both_can_read(self):
        """What the tools get (auto) is what a host without PyYAML would get."""
        for path in sorted(SKILLS.glob("*/SKILL.md")):
            fm = sf.frontmatter_of(path.read_text(encoding="utf-8", errors="ignore"))
            if fm is None:
                continue
            for key in CUSTOM_KEYS:
                auto, lines = sf.read(fm, key, path=path), sf.read(fm, key, path=path, engine="lines")
                if sf.UNSUPPORTED in (auto.status, lines.status):
                    continue
                self.assertEqual((auto.present, auto.value), (lines.present, lines.value), f"{path}: {key}")


# ------------------------------------------------------------------ the switched readers

OLD = "---\nname: {name}\ndescription: {desc}\n{key}: {val}\n---\n\n# {name}\n"
NEW = '---\nname: {name}\ndescription: {desc}\nmetadata:\n  {key}: "{val}"\n---\n\n# {name}\n'
BOTH = '---\nname: {name}\ndescription: {desc}\n{key}: {val}\nmetadata:\n  {key}: "{val}"\n---\n\n# {name}\n'
DIFFERENT = ('---\nname: {name}\ndescription: {desc}\n{key}: {val}\nmetadata:\n'
             '  {key}: "something else"\n---\n\n# {name}\n')
LAYOUTS = (("old", OLD), ("new", NEW), ("both-equal", BOTH))


def _write(root: Path, name: str, template: str, key: str, val: str,
           desc: str = "A skill about one thing.") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(template.format(name=name, desc=desc, key=key, val=val), encoding="utf-8")
    return p


class Readers(unittest.TestCase):
    """Each reader gives one answer for the old layout, the new layout and both-equal."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_skill_overlap_has_boundary(self):
        for key in ("disambiguation", "applies_when"):
            results = {}
            for label, template in LAYOUTS:
                root = self.root / f"overlap-{key}-{label}"
                _write(root, "alpha", template, key, "Counts stock. Levels are beta.")
                results[label] = skill_overlap._has_boundary(root, "alpha")
            self.assertEqual(results, {"old": True, "new": True, "both-equal": True}, key)
        plain = self.root / "overlap-none"
        (plain / "alpha").mkdir(parents=True)
        (plain / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: A skill.\n---\n")
        self.assertFalse(skill_overlap._has_boundary(plain, "alpha"))

    def test_skill_overlap_conflict(self):
        root = self.root / "overlap-diff"
        path = _write(root, "alpha", DIFFERENT, "disambiguation", "Counts stock.")
        with self.assertRaises(sf.FrontmatterConflict) as ctx:
            skill_overlap._has_boundary(root, "alpha")
        self.assertEqual((ctx.exception.path, ctx.exception.key), (str(path), "disambiguation"))

    def test_skill_overlap_update_baseline_accepts_a_metadata_boundary(self):
        """End to end: the gate that needs a boundary sees one under `metadata:`."""
        results = {}
        for label, template in LAYOUTS:
            root = self.root / f"baseline-{label}"
            desc = "Manage widget inventory levels and widget stock counts"
            _write(root, "alpha-thing", "---\nname: {name}\ndescription: {desc}\n---\n", "", "", desc)
            _write(root, "beta-thing", template, "disambiguation", "Counts stock. Levels are alpha-thing.", desc)
            base = self.root / f"baseline-{label}.json"
            with redirect_stderr(io.StringIO()):
                results[label] = skill_overlap.main(
                    ["--skills-root", str(root), "--baseline", str(base), "--update-baseline"])
        self.assertEqual(results, {"old": 0, "new": 0, "both-equal": 0})

    def test_skill_overlap_main_fails_closed_on_a_conflict(self):
        root = self.root / "baseline-diff"
        desc = "Manage widget inventory levels and widget stock counts"
        _write(root, "alpha-thing", "---\nname: {name}\ndescription: {desc}\n---\n", "", "", desc)
        _write(root, "beta-thing", DIFFERENT, "disambiguation", "Counts stock.", desc)
        base = self.root / "baseline-diff.json"
        err = io.StringIO()
        with redirect_stderr(err):
            rc = skill_overlap.main(["--skills-root", str(root), "--baseline", str(base), "--update-baseline"])
        self.assertEqual(rc, 2)
        self.assertFalse(base.exists(), "a refused run must not write a baseline")
        self.assertIn("disambiguation", err.getvalue())

    def test_skill_resolve_family(self):
        results = {}
        for label, template in LAYOUTS:
            root = self.root / f"resolve-{label}"
            _write(root, "rhel-databases", template, "family", "rhel")
            _write(root, "rhel-monitoring", template, "family", "rhel")
            _write(root, "unrelated", "---\nname: {name}\ndescription: {desc}\n---\n", "", "")
            index = skill_resolve.build_index(root)
            resolved = skill_resolve.resolve(["family:rhel"], index, set())
            results[label] = (index["families"], resolved["resolved"], resolved["unresolved"])
        self.assertEqual(results["old"],
                         ({"rhel": ["rhel-databases", "rhel-monitoring"]},
                          ["rhel-databases", "rhel-monitoring"], []))
        self.assertEqual(results["new"], results["old"])
        self.assertEqual(results["both-equal"], results["old"])

    def test_skill_resolve_conflict(self):
        root = self.root / "resolve-diff"
        path = _write(root, "rhel-databases", DIFFERENT, "family", "rhel")
        with self.assertRaises(sf.FrontmatterConflict) as ctx:
            skill_resolve.build_index(root)
        self.assertEqual((ctx.exception.path, ctx.exception.key), (str(path), "family"))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = skill_resolve.main(["family:rhel", "--skills-root", str(root),
                                     "--claude-home", str(self.root / "no-home")])
        self.assertEqual(rc, 2)
        self.assertIn("family", err.getvalue())

    def test_intake_assess(self):
        results = {}
        for label, template in LAYOUTS:
            root = self.root / f"intake-{label}"
            path = _write(root, "incoming", template, "disambiguation", "Does X. Y is other-skill.")
            results[label] = assess.assess(path, self.root / "no-skills-root")
        self.assertEqual(results["old"]["structural"], [], "a declared disambiguation is not a finding")
        for label in ("new", "both-equal"):
            got = dict(results[label], lines=None)
            self.assertEqual(got, dict(results["old"], lines=None), label)

    def test_intake_assess_missing_and_empty_read_the_same_in_both_layouts(self):
        advisory = [{"issue": "no `disambiguation` — needed once a near neighbour exists",
                     "severity": "advisory"}]
        cases = {
            "absent": "---\nname: incoming\ndescription: A skill.\n---\n",
            "empty-top": "---\nname: incoming\ndescription: A skill.\ndisambiguation:\n---\n",
            "empty-metadata": '---\nname: incoming\ndescription: A skill.\nmetadata:\n  disambiguation: ""\n---\n',
        }
        for label, text in cases.items():
            d = self.root / f"intake-{label}" / "incoming"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(text, encoding="utf-8")
            got = assess.assess(d / "SKILL.md", self.root / "no-skills-root")
            self.assertEqual(got["structural"], advisory, label)

    def test_intake_assess_conflict(self):
        path = _write(self.root / "intake-diff", "incoming", DIFFERENT, "disambiguation", "Does X.")
        with self.assertRaises(sf.FrontmatterConflict) as ctx:
            assess.assess(path, self.root / "no-skills-root")
        self.assertEqual((ctx.exception.path, ctx.exception.key), (str(path), "disambiguation"))

    def test_intake_assess_cli_reports_a_conflict_without_a_traceback(self):
        """#344 fix round 1 (m6): exit 2 and the message, like skill_resolve."""
        path = _write(self.root / "intake-cli", "incoming", DIFFERENT, "disambiguation", "Does X.")
        out, err = io.StringIO(), io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out), redirect_stderr(err):
            rc = assess.main(["--skill", str(path),
                              "--skills-root", str(self.root / "no-skills-root")])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("disambiguation", err.getvalue())
        self.assertIn(str(path), err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_claims_lint_family_members(self):
        results = {}
        for label, template in LAYOUTS:
            root = self.root / f"claims-{label}"
            _write(root, "seo-a", template, "family", "seo")
            _write(root, "seo-b", template, "family", "seo")
            _write(root, "other", template, "family", "rhel")
            results[label] = claims_lint.family_members(root, "seo")
        self.assertEqual(results, {label: {"seo-a", "seo-b"} for label, _ in LAYOUTS})

    def test_claims_lint_conflict(self):
        root = self.root / "claims-diff"
        _write(root, "seo-a", DIFFERENT, "family", "seo")
        with self.assertRaises(sf.FrontmatterConflict) as ctx:
            claims_lint.family_members(root, "seo")
        self.assertEqual(ctx.exception.key, "family")


class Hygiene(unittest.TestCase):
    def test_only_the_stdlib_and_optional_yaml(self):
        import ast
        tree = ast.parse((META / "skill_frontmatter.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "no relative imports")
                imported.add((node.module or "").split(".")[0])
        imported.discard("__future__")
        self.assertEqual(imported - set(sys.stdlib_module_names), {"yaml"})


if __name__ == "__main__":
    unittest.main()
