#!/usr/bin/env python3
"""Tests for skill_audit.py (#344 WP-1, DW-1).

Every rule ships a sample that fires it and a sample that does not, in the precedent of
tests/secrets-scan/test_every_rule_fires.py: a rule with no positive sample is a rule
nobody has seen work. `test_every_rule_has_a_positive_and_a_negative_sample` fails when a
rule is added to RULES without both.

  rules       A1-A11 positive and negative, N1 and N2, notes never change the exit code
  exemption   an own-directory home path on a listed line is a note; any other line fails
  tag lines   A11 and inventory see `<HARD-RULE>` at the start of a line, never the words
  conserve    passes on a pure move; FAILS on a reworded line, a dropped line and a
              reordered span; a manifest-recorded reorder is the one legal exception
  hook        the pre-commit arm BLOCKS a failing listed skill and only WARNS on an
              unlisted one

Writes only under a TemporaryDirectory; reads the repo tree for the two whole-tree tests.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
REPO = _META.parents[1]
SCRIPT = _META / "skill_audit.py"
HOOK = REPO / "skills" / "secret-scanning" / "hooks" / "pre_commit.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sa = _load("skill_audit_under_test", SCRIPT)

GOOD_DESCRIPTION = ("Widget calibration for bench rigs. Computes offsets from a reference "
                    "run and writes a report. Use it when a rig drifts.")


def skill_md(name: str = "demo", description: str = GOOD_DESCRIPTION, extra_fm: str = "",
             body: str = "# Demo\n\nSee references/guide.md for the detail.\n") -> str:
    return f"---\nname: {name}\ndescription: {description}\n{extra_fm}---\n\n{body}"


def write_skill(root: Path, name: str = "demo", files: dict | None = None, **kw) -> Path:
    """A clean skill: one named reference, nothing any rule objects to."""
    base = root / name
    tree = {"SKILL.md": skill_md(name=name, **kw), "references/guide.md": "# Guide\n\nShort.\n"}
    tree.update(files or {})
    for rel, text in tree.items():
        if text is None:
            continue
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
    return base


def audit(name: str = "demo", exemptions: dict | None = None, **kw) -> dict:
    with tempfile.TemporaryDirectory() as td:
        write_skill(Path(td), name, **kw)
        return sa.audit_skill(sa.SkillFiles.from_tree(Path(td), name), exemptions)


def codes(record: dict, key: str = "findings") -> list[str]:
    return [f["code"] for f in record[key]]


def run_cli(*args: str, cwd: Path | None = None, stdin: bytes | None = None
            ) -> tuple[int, str, str]:
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          cwd=cwd, input=stdin)
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


LONG_REFERENCE = "# Long\n\n" + "".join(f"line {i}\n" for i in range(120))
LONG_WITH_CONTENTS = "# Long\n\n## Contents\n\n- part one\n\n" + "".join(
    f"line {i}\n" for i in range(120))
PADDING = "".join(f"padding line {i:04d} that only makes the file longer\n" for i in range(600))

#: rule -> (kwargs that FIRE it, kwargs that do NOT). The negative is the nearest clean
#: neighbour of the positive, so each pair pins the boundary and not just the rule.
SAMPLES: dict[str, tuple[dict, dict]] = {
    "A1": (dict(extra_fm="disambiguation: not a standard key\n"),
           dict(extra_fm="when_to_use: a Claude Code key\nlicense: MIT\n")),
    "A2": (dict(extra_fm="metadata:\n  version: 1.2\n"),
           dict(extra_fm="metadata:\n  version: \"1.2\"\n  owner: platform team\n")),
    "A3": (dict(name="Claude_Helper"),
           dict(name="demo-2")),
    "A4": (dict(description="Fixtures for bench rigs, written to tests/<component>/ on demand."),
           dict(description="Fixtures for bench rigs, written under tests/ on demand. "
                            "A value of x < 3 or y > 4 is not a tag.")),
    "A5": (dict(description="Use when a bench rig drifts and its offsets need recomputing "
                            "from a run."),
           dict(description="Bench rig calibration. Use when a rig drifts.")),
    "A6": (dict(body="# Demo\n\nreferences/guide.md\n" + "x\n" * 500),
           dict(body="# Demo\n\nreferences/guide.md\n" + "x\n" * 480)),
    "A7": (dict(files={"references/orphan.md": "# Orphan\n"}),
           dict(files={"tests/notes.md": "# a test note\n", "evals/case.md": "# an eval\n",
                       "tests/fixtures/sample.md": "# fixture\n"})),
    "A8": (dict(files={"references/guide.md": LONG_REFERENCE}),
           dict(files={"references/guide.md": LONG_WITH_CONTENTS})),
    "A9": (dict(body="# Demo\n\nreferences/guide.md\n\nRun ~/.claude/skills/demo/scripts/x.sh\n"),
           dict(body="# Demo\n\nreferences/guide.md\n\nRun scripts/x.sh from this directory; "
                     "~/.claude/skills/demo-other/x.sh is another skill.\n")),
    "A10": (dict(files={"references/guide.md": "# Guide\n\nThen read deep.md.\n",
                        "references/deep.md": "# Deep\n"}),
            dict(files={"references/guide.md": "# Guide\n\nThen read deep.md.\n",
                        "references/deep.md": "# Deep\n"},
                 body="# Demo\n\nreferences/guide.md and references/deep.md\n")),
    "A11": (dict(body="# Demo\n\nreferences/guide.md\n" + PADDING
                      + "<HARD-RULE>\nNever skip the gate.\n</HARD-RULE>\n"),
            dict(body="# Demo\n\nreferences/guide.md\n<HARD-RULE>\nNever skip the gate.\n"
                      "</HARD-RULE>\n" + PADDING)),
}


class EveryRule(unittest.TestCase):
    def test_the_clean_fixture_is_clean(self):
        record = audit()
        self.assertEqual(record["findings"], [])
        self.assertEqual(record["notes"], [])

    def test_every_rule_has_a_positive_and_a_negative_sample(self):
        fail_rules = sorted(c for c in sa.RULES if c.startswith("A"))
        self.assertEqual(fail_rules, sorted(SAMPLES),
                         "a rule in RULES has no sample here (or a sample has no rule)")
        self.assertEqual(len(fail_rules), 11)
        for code, (positive, negative) in SAMPLES.items():
            with self.subTest(rule=code, sample="positive"):
                self.assertIn(code, codes(audit(**positive)))
            with self.subTest(rule=code, sample="negative"):
                self.assertNotIn(code, codes(audit(**negative)))

    def test_every_finding_is_a_fail_and_every_note_a_note(self):
        for code, (positive, _) in SAMPLES.items():
            record = audit(**positive)
            self.assertTrue(all(f["level"] == "fail" for f in record["findings"]), code)
            self.assertTrue(all(n["level"] == "note" for n in record["notes"]), code)

    def test_a1_key_lists_are_data_and_cover_the_spec_and_claude_code(self):
        self.assertEqual(set(sa.SPEC_KEYS), {"name", "description", "license",
                                             "compatibility", "metadata", "allowed-tools"})
        for key in ("when_to_use", "argument-hint", "arguments", "disable-model-invocation",
                    "user-invocable", "disallowed-tools", "model", "effort", "context",
                    "agent", "background", "hooks", "paths", "shell"):
            self.assertIn(key, sa.CLAUDE_CODE_KEYS)
        everything = "".join(f"{k}: v\n" for k in sa.ALLOWED_KEYS - {"name", "description",
                                                                     "metadata"})
        self.assertNotIn("A1", codes(audit(extra_fm=everything)))

    def test_a2_names_each_non_string_shape(self):
        for value in ("1", "true", "2026-10-09", "[a, b]", "{a: b}", "", "\n    nested: x"):
            with self.subTest(value=value):
                self.assertIn("A2", codes(audit(extra_fm=f"metadata:\n  key: {value}\n")))
        for value in ('"1"', "'true'", "plain words", "v1.2-beta", ">\n    folded text"):
            with self.subTest(value=value):
                self.assertNotIn("A2", codes(audit(extra_fm=f"metadata:\n  key: {value}\n")))
        self.assertIn("A2", codes(audit(extra_fm="metadata: just a string\n")))

    def test_a3_each_arm(self):
        self.assertIn("A3", codes(audit(name="a" * 65)))
        self.assertNotIn("A3", codes(audit(name="a" * 64)))
        for bad in ("Upper", "under_score", "-lead", "trail-", "dou--ble", "my-claude-tool",
                    "anthropic-helper"):
            with self.subTest(name=bad):
                self.assertIn("A3", codes(audit(name=bad)))

    def test_a4_over_1024_chars(self):
        self.assertIn("A4", codes(audit(description="Rig data. " + "word " * 210)))

    def test_a5_limit_is_250_and_the_override_table_raises_it(self):
        text = "Rig calibration. " + "x" * 300
        self.assertIn("A5", codes(audit(description=text)))
        self.assertEqual(sa.DESCRIPTION_LIMIT, 250)
        self.assertEqual(sa.DESCRIPTION_LIMIT_OVERRIDES,
                         {"avengers": 400, "codex-orchestration": 400})
        self.assertNotIn("A5", codes(audit(name="avengers", description=text)))
        self.assertIn("A5", codes(audit(name="avengers",
                                        description="Panel. " + "x" * 400)))

    def test_description_length_is_counted_on_the_decoded_folded_text(self):
        folded = ">\n  Bench rig calibration.\n  Computes offsets\n  from a reference run."
        record = audit(description=folded)
        self.assertEqual(record["description_chars"],
                         len("Bench rig calibration. Computes offsets from a reference run."))
        quoted = audit(description='"Rig: calibration with a colon, and \\"quotes\\"."')
        self.assertEqual(quoted["description_chars"],
                         len('Rig: calibration with a colon, and "quotes".'))
        self.assertEqual(quoted["findings"], [])

    def test_a7_a_nested_skill_is_not_a_reference_of_its_parent(self):
        record = audit(files={"child/SKILL.md": skill_md(name="child"),
                              "child/notes.md": "# child notes\n"})
        self.assertNotIn("A7", codes(record))
        self.assertEqual(record["nested_skills"], ["child"])

    def test_a8_only_counts_a_contents_list_in_the_first_thirty_lines(self):
        late = "# Long\n\n" + "".join(f"line {i}\n" for i in range(60)) + "## Contents\n" \
               + "".join(f"more {i}\n" for i in range(60))
        self.assertIn("A8", codes(audit(files={"references/guide.md": late})))
        for form in ("**Contents**", "Contents:", "### Table of contents"):
            with self.subTest(form=form):
                text = f"# Long\n\n{form}\n\n" + "".join(f"line {i}\n" for i in range(120))
                self.assertNotIn("A8", codes(audit(files={"references/guide.md": text})))

    def test_a9_and_n2_match_all_three_spellings(self):
        for prefix in ("~", "$HOME", "${HOME}"):
            with self.subTest(prefix=prefix):
                own = audit(body=f"references/guide.md\n\n{prefix}/.claude/skills/demo/x.sh\n")
                self.assertIn("A9", codes(own))
                shared = audit(body="references/guide.md\n\n"
                                    f"{prefix}/.claude/skills/_meta/gates.py and "
                                    f"{prefix}/.claude/skills/other-skill/SKILL.md\n")
                self.assertNotIn("A9", codes(shared))
                self.assertEqual(codes(shared, "notes"), ["N2"])
                self.assertIn("_meta", shared["notes"][0]["message"])
                self.assertIn("other-skill", shared["notes"][0]["message"])

    def test_a9_is_found_in_a_reference_too(self):
        record = audit(files={"references/guide.md": "# G\n\n$HOME/.claude/skills/demo/a.md\n"})
        self.assertEqual([(f["code"], f["file"], f["line"]) for f in record["findings"]],
                         [("A9", "references/guide.md", 3)])

    def test_a9_exemption_listed_line_is_a_note_and_any_other_line_fails(self):
        exempt_line = "bash ~/.claude/skills/demo/scripts/verify.sh \\"
        other_line = "cat ~/.claude/skills/demo/scripts/verify.sh"
        body = f"references/guide.md\n\n{exempt_line}\n{other_line}\n"
        exemptions = {("SKILL.md", exempt_line): "command run from a project directory"}
        record = audit(body=body, exemptions=exemptions)
        self.assertEqual([(f["code"], f["line"]) for f in record["findings"]], [("A9", 9)])
        self.assertEqual([(n["code"], n["line"]) for n in record["notes"]], [("N2", 8)])
        self.assertIn("command run from a project directory", record["notes"][0]["message"])
        # the same text in ANOTHER file is not exempt: an exemption names its file
        moved = audit(body="references/guide.md\n",
                      files={"references/guide.md": f"# G\n\n{exempt_line}\n"},
                      exemptions=exemptions)
        self.assertIn("A9", codes(moved))

    def test_exemption_file_refuses_an_entry_without_a_reason(self):
        with tempfile.TemporaryDirectory() as td:
            meta = Path(td)
            (meta / sa.EXEMPTIONS_FILE).write_text(json.dumps({"exemptions": {"demo": [
                {"file": "SKILL.md", "line": "x", "reason": " "}]}}), encoding="utf-8")
            with self.assertRaises(sa.AuditError):
                sa.load_exemptions(meta)

    def test_the_shipped_exemptions_match_real_lines_and_carry_reasons(self):
        exemptions = sa.load_exemptions(_META)
        self.assertIn("research-for-skills", exemptions)
        self.assertIn("avengers", exemptions)
        for skill, entries in exemptions.items():
            for (rel, line), reason in entries.items():
                self.assertTrue(reason.strip())
                self.assertIn("/.claude/skills/" + skill, line,
                              f"{skill}:{rel}: an exemption for a line with no own-dir path")

    def test_a11_boundary_is_byte_20000(self):
        head = "---\nname: demo\ndescription: " + GOOD_DESCRIPTION + "\n---\n"
        block = "<HARD-GATE>\nStop.\n</HARD-GATE>\n"
        for offset, expect in ((19_999, False), (20_000, True)):
            pad = "p" * (offset - len(head.encode()) - 1) + "\n"
            with tempfile.TemporaryDirectory() as td:
                write_skill(Path(td), files={"SKILL.md": head + pad + block,
                                             "references/guide.md": None})
                record = sa.audit_skill(sa.SkillFiles.from_tree(Path(td), "demo"))
            self.assertEqual("A11" in codes(record), expect, offset)

    def test_a11_ignores_a_prose_mention_of_hard_rule(self):
        prose = ("The words HARD-RULE and <HARD-RULE> inside a sentence are not a block, "
                 "nor is `<HARD-GATE>` in code.\n"
                 "`<HARD-RULE>` in inline code at the start of a line is not one either.\n")
        record = audit(body="# Demo\n\nreferences/guide.md\n" + PADDING + prose)
        self.assertNotIn("A11", codes(record))
        self.assertEqual(record["hard_blocks"], 0)


    # -- fix round 1 (F2b, F2c): tag lines --------------------------------------------

    def test_an_indented_tag_line_is_a_block(self):
        """F2b: `  <HARD-RULE>` (inside a list item) was invisible to A11 and inventory."""
        block = "  <HARD-RULE>\n  Never skip the gate.\n  </HARD-RULE>\n"
        late = audit(body="# Demo\n\nreferences/guide.md\n" + PADDING + block)
        self.assertEqual(late["hard_blocks"], 1)
        self.assertIn("A11", codes(late))
        tabbed = audit(body="# Demo\n\nreferences/guide.md\n\t<HARD-GATE>\n\tStop.\n"
                            "\t</HARD-GATE>\n" + PADDING)
        self.assertEqual(tabbed["hard_blocks"], 1)
        self.assertNotIn("A11", codes(tabbed))

    def test_an_unterminated_block_is_an_a11_fail_and_hides_no_later_block(self):
        """F2c: a block with no closing tag used to swallow the rest of the file."""
        body = ("# Demo\n\nreferences/guide.md\n<HARD-RULE>\nNever skip the gate.\n\n"
                "Prose that follows.\n\n<HARD-GATE>\nStop.\n</HARD-GATE>\n")
        record = audit(body=body)
        self.assertEqual(record["hard_blocks"], 2, "the later block is still seen")
        a11 = [f for f in record["findings"] if f["code"] == "A11"]
        self.assertEqual(len(a11), 1)
        self.assertIn("no closing", a11[0]["message"])
        blocks = sa.hard_blocks(body)
        self.assertEqual([(b["kind"], b["terminated"]) for b in blocks],
                         [("HARD-RULE", False), ("HARD-GATE", True)])
        self.assertLess(blocks[0]["end_line"], blocks[1]["line"])
        closed = audit(body=body.replace("Never skip the gate.\n",
                                         "Never skip the gate.\n</HARD-RULE>\n"))
        self.assertNotIn("A11", codes(closed))

    # -- fix round 1 (F4): the frontmatter reading fails closed -------------------------

    def test_a1_an_unrecognised_column_zero_line_fails(self):
        """F4: `"custom": "x"` was glued onto the previous key and never seen."""
        for line in ('"custom": "x"', "'custom': x", "{custom: x}", "? custom", "- item",
                     "just some words"):
            with self.subTest(line=line):
                record = audit(extra_fm=line + "\n")
                self.assertIn("A1", codes(record), record["findings"])
        for ok in ("license: MIT\n", "# a comment\n", "compatibility: >\n  folded\n  text\n",
                   'license: "a quoted value\n  that continues"\n',
                   "compatibility: a plain value\n  that continues\n"):
            with self.subTest(ok=ok):
                self.assertEqual(audit(extra_fm=ok)["findings"], [])

    def test_a1_a_quoted_key_before_name_is_not_dropped(self):
        text = ('---\n"custom": "x"\nname: demo\ndescription: ' + GOOD_DESCRIPTION
                + "\n---\n\n# Demo\n\nreferences/guide.md\n")
        with tempfile.TemporaryDirectory() as td:
            write_skill(Path(td), files={"SKILL.md": text})
            record = sa.audit_skill(sa.SkillFiles.from_tree(Path(td), "demo"))
        self.assertEqual([(f["code"], f["line"]) for f in record["findings"]], [("A1", 2)])

    def test_a2_typed_tagged_and_unreadable_metadata_values_fail(self):
        """F4: `version: 12:30` (sexagesimal) and `version: !!int 7` gave no finding."""
        for value in ("12:30", "1:02:03", "-1:30", "20:30.15", "!!int 7", "!!str 7",
                      "&a text", "*a", "0b101", "0x1F", "1_000", ".5", "1e3", "~", "Null",
                      "TRUE", "2026-10-09 12:00:00"):
            with self.subTest(value=value):
                record = audit(extra_fm=f"metadata:\n  version: {value}\n")
                self.assertIn("A2", codes(record))
        for value in ('"12:30"', "'!!int 7'", "12:30 UTC", "v12:30", "1.2.3", "a:b"):
            with self.subTest(ok=value):
                self.assertNotIn("A2", codes(audit(extra_fm=f"metadata:\n  version: {value}\n")))

    def test_a2_an_unrecognised_line_under_metadata_fails(self):
        for child in ('"version": 7', "? version", "- item"):
            with self.subTest(child=child):
                record = audit(extra_fm=f'metadata:\n  owner: "team"\n  {child}\n')
                self.assertIn("A2", codes(record), record["findings"])

    def test_a4_checks_the_decoded_description(self):
        """F4: `"\\x3ccomponent\\x3e"` decodes to an XML tag and used to pass."""
        for raw in ('"Rigs under tests/\\x3ccomponent\\x3e/ on demand."',
                    '"Rigs under tests/\\u003ccomponent\\u003e/ on demand."',
                    '"Rigs under tests/\\U0000003ccomponent\\U0000003e/ on demand."'):
            with self.subTest(raw=raw):
                record = audit(description=raw)
                self.assertIn("A4", codes(record))
                self.assertTrue(any("<component>" in f["message"] for f in record["findings"]))
        self.assertEqual(audit(description='"Rigs \\x41 and a tab\\t, no tag."')["findings"], [])

    def test_a4_an_escape_that_cannot_be_decoded_fails_closed(self):
        for raw in ('"Rigs \\q on demand."', '"Rigs \\x4 on demand."', '"Rigs \\uZZZZ."'):
            with self.subTest(raw=raw):
                self.assertIn("A4", codes(audit(description=raw)))

    def test_a3_and_a4_a_tagged_value_is_not_a_string(self):
        self.assertIn("A4", codes(audit(description="!!binary Zm9v")))
        self.assertIn("A3", codes(audit(name="!!str demo")))

    def test_the_stdlib_reading_alone_still_fails_closed(self):
        """Every F4 fixture again with PyYAML switched off: the stdlib path decides."""
        saved, sa._yaml = sa._yaml, None
        try:
            self.assertIn("A1", codes(audit(extra_fm='"custom": "x"\n')))
            self.assertIn("A2", codes(audit(extra_fm="metadata:\n  version: 12:30\n")))
            self.assertIn("A2", codes(audit(extra_fm="metadata:\n  version: !!int 7\n")))
            self.assertIn("A4", codes(audit(
                description='"Rigs under tests/\\x3ccomponent\\x3e/ on demand."')))
            self.assertEqual(audit()["findings"], [])
        finally:
            sa._yaml = saved

    @unittest.skipUnless(sa._yaml is not None, "PyYAML is not importable")
    def test_pyyaml_is_a_second_reading_when_importable(self):
        """What only a real YAML parser types: a value the stdlib table does not list."""
        saved = sa._YAML_NON_STRING_RE
        sa._YAML_NON_STRING_RE = __import__("re").compile(r"(?!)")     # the table sees nothing
        try:
            self.assertIn("A2", codes(audit(extra_fm="metadata:\n  version: 12\n")))
            self.assertNotIn("A2", codes(audit(extra_fm='metadata:\n  version: "12"\n')))
        finally:
            sa._YAML_NON_STRING_RE = saved

    # -- fix round 2 (R4): the frontmatter reader, fail-closed gaps ----------------------

    @staticmethod
    @contextlib.contextmanager
    def reading(stdlib_alone: bool):
        """The audit with PyYAML as its second reading, or with the stdlib reader alone."""
        saved = sa._yaml
        if stdlib_alone:
            sa._yaml = None
        try:
            yield
        finally:
            sa._yaml = saved

    def test_r4a_text_after_a_closing_quote_is_not_ignored(self):
        for alone in (False, True):
            with self.subTest(stdlib_alone=alone), self.reading(alone):
                self.assertIn("A4", codes(audit(description='"Fine text here" <b>x</b>')))
                self.assertIn("A4", codes(audit(description="'Fine text here' trailing")))
                self.assertIn("A2", codes(audit(extra_fm='metadata:\n  version: "1" !!int\n')))
                self.assertIn("A3", codes(audit(name='"demo" junk')))
                # a trailing comment is YAML, and so is trailing white space
                self.assertEqual(audit(description='"Fine text here"   # why')["findings"], [])
                self.assertEqual(audit(extra_fm="metadata:\n  version: '1' # pinned\n")["findings"],
                                 [])

    def test_r4b_an_indented_dashed_line_does_not_end_the_header(self):
        """`  ---` inside a block scalar closed the header and hid the key after it."""
        text = ("---\nname: demo\ndescription: >\n  " + GOOD_DESCRIPTION
                + "\n  ---\n  more of it\ncustom: x\n---\n\n# Demo\n\nreferences/guide.md\n")
        for alone in (False, True):
            with self.subTest(stdlib_alone=alone), self.reading(alone):
                with tempfile.TemporaryDirectory() as td:
                    write_skill(Path(td), files={"SKILL.md": text})
                    record = sa.audit_skill(sa.SkillFiles.from_tree(Path(td), "demo"))
                self.assertEqual(codes(record), ["A1"], record["findings"])
                self.assertIn("custom", record["frontmatter_keys"])
            fm, body = sa.split_frontmatter("---\nname: a\n --- \nb: c\n---  \nbody\n")
            self.assertEqual((fm, body), ("name: a\n --- \nb: c\n", "body\n"))

    def test_r4c_a_duplicated_top_level_key_fails(self):
        for alone in (False, True):
            with self.subTest(stdlib_alone=alone), self.reading(alone):
                record = audit(extra_fm="description: Fixtures written to tests/<component>/.\n")
                self.assertIn("A1", codes(record), record["findings"])
                self.assertTrue(any("more than once" in f["message"] for f in record["findings"]))
                twice = audit(extra_fm='metadata:\n  version: "1"\nmetadata:\n  owner: "t"\n')
                self.assertEqual(codes(twice), ["A1"], twice["findings"])
                self.assertEqual(audit(extra_fm='metadata:\n  version: "1"\n')["findings"], [])

    def test_r4d_the_stdlib_reader_fails_closed_on_what_it_cannot_fold(self):
        """An escaped line break inside a double-quoted scalar joins `<` to `b>`, and a
        comment line under a plain number does not make it a string."""
        for alone in (False, True):
            with self.subTest(stdlib_alone=alone), self.reading(alone):
                self.assertIn("A4", codes(audit(description='"A <\\\n  b> tag in the text"')))
                for cont in ("      # c\n", "    # c\n      # d\n"):
                    record = audit(extra_fm="metadata:\n  version: 12\n" + cont)
                    self.assertIn("A2", codes(record), (cont, record["findings"]))
                # a double-quoted value folded WITHOUT an escaped break still reads
                self.assertEqual(audit(description='"Rig calibration,\n  folded over two lines."')
                                 ["findings"], [])

    def test_r4e_a_comment_under_metadata_is_not_a_finding(self):
        for alone in (False, True):
            with self.subTest(stdlib_alone=alone), self.reading(alone):
                for fm in ('metadata:\n  # note\n  version: "1"\n',
                           'metadata: # note\n  version: "1"\n',
                           'metadata:\n      # deep note\n  version: "1"\n  # between\n  owner: "t"\n',
                           'license: # none yet\n'):
                    with self.subTest(fm=fm):
                        self.assertEqual(audit(extra_fm=fm)["findings"], [])
                # and a comment does not hide a real one
                self.assertIn("A2", codes(audit(extra_fm="metadata: # note\n  version: 1\n")))
                self.assertIn("A2", codes(audit(extra_fm="metadata:\n  # note\n  version: 1\n")))

    # -- fix round 1 (m1): name and directory -------------------------------------------

    def test_a3_name_must_equal_the_directory_name(self):
        with tempfile.TemporaryDirectory() as td:
            write_skill(Path(td), "rig-tools", files={"SKILL.md": skill_md(name="rig-tool")})
            record = sa.audit_skill(sa.SkillFiles.from_tree(Path(td), "rig-tools"))
        a3 = [f for f in record["findings"] if f["code"] == "A3"]
        self.assertEqual(len(a3), 1, record["findings"])
        self.assertIn("rig-tools", a3[0]["message"])
        self.assertNotIn("A3", codes(audit(name="rig-tools")))


class Notes(unittest.TestCase):
    def test_n1_fires_over_5000_tokens_and_not_under(self):
        big = audit(body="references/guide.md\n" + "word " * 4100)
        self.assertEqual(codes(big, "notes"), ["N1"])
        self.assertNotIn("A6", codes(big))
        self.assertEqual(codes(audit(body="references/guide.md\n" + "word " * 3000), "notes"),
                         [])

    def test_notes_never_change_the_exit_code_even_on_a_listed_skill(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, body="references/guide.md\n\n~/.claude/skills/_meta/gates.py\n"
                                   + "word " * 4100)
            rc, out, _ = run_cli("audit", "--root", str(root), "--strict", "--json")
            report = json.loads(out)
            self.assertEqual(rc, 0, out)
            self.assertEqual(report["summary"]["notes_by_code"], {"N1": 1, "N2": 1})
            self.assertEqual(report["summary"]["fails_listed"], 0)
            rc, text, _ = run_cli("audit", "--root", str(root), "--strict")
            self.assertEqual(rc, 0)
            self.assertIn("NOTES -- never affect the exit code", text)
            self.assertIn("N1: 1   N2: 1", text)


class AuditCli(unittest.TestCase):
    def test_exit_code_follows_the_conformant_list_not_the_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "demo", description="Use when nothing else fits this at all.")
            rc, out, _ = run_cli("audit", "--root", str(root), "--json")
            report = json.loads(out)
            self.assertEqual(rc, 0, "an unlisted skill is reported, never blocking")
            self.assertEqual(report["summary"]["fails_unlisted"], 1)
            self.assertFalse(report["skills"]["demo"]["listed"])
            rc, out, _ = run_cli("audit", "--root", str(root), "--strict", "--json")
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(out)["summary"]["fails_listed"], 1)

    def test_only_selects_and_an_unknown_name_is_bad_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "demo")
            write_skill(root, "other")
            rc, out, _ = run_cli("audit", "--root", str(root), "--only", "other", "--json")
            self.assertEqual((rc, list(json.loads(out)["skills"])), (0, ["other"]))
            rc, _, err = run_cli("audit", "--root", str(root), "--only", "nope")
            self.assertEqual(rc, 2)
            self.assertIn("nope", err)

    def test_the_repo_tree_audits_without_a_traceback_and_covers_every_skill(self):
        rc, out, err = run_cli("audit", "--json")
        self.assertIn(rc, (0, 1), err)
        self.assertNotIn("Traceback", err)
        report = json.loads(out)
        expected = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md")
                          if not p.parent.name.startswith(("_", ".")))
        self.assertEqual(sorted(report["skills"]), expected)
        self.assertEqual(report["root"], "skills")
        self.assertGreater(len(expected), 200)

    def test_the_conformant_list_is_the_core_nine(self):
        self.assertEqual(sa.load_conformant(_META), frozenset({
            "forge", "codex-orchestration", "avengers", "agent-teams", "research-for-skills",
            "component-contract-mapping", "sample-data-scaffolding",
            "integration-flow-testing", "verification-arbiter"}))


class Hygiene(unittest.TestCase):
    def test_imports_nothing_outside_the_stdlib(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "no relative imports")
                imported.add((node.module or "").split(".")[0])
        imported.discard("__future__")
        self.assertTrue(imported)
        # PyYAML is OPTIONAL (a guarded import): it only adds a second reading of the
        # frontmatter, and the stdlib reader fails closed without it.
        self.assertEqual(imported - set(sys.stdlib_module_names) - {"yaml"}, set())

    def test_default_root_is_the_repo_skills_tree_never_the_home_tree(self):
        self.assertEqual(sa.DEFAULT_ROOT, REPO / "skills")
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("Path.home()", source)
        self.assertNotIn("expanduser", source)

    def test_listing_budget_is_labelled_an_estimate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "demo")
            write_skill(root, "other", description="Short one.")
            rc, text, _ = run_cli("listing-budget", "--root", str(root))
            self.assertEqual(rc, 0)
            self.assertIn("ESTIMATE", text)
            rc, out, _ = run_cli("listing-budget", "--root", str(root), "--fraction", "0.03",
                                 "--json")
            data = json.loads(out)
            self.assertIs(data["estimate"], True)
            self.assertEqual(data["budget_chars"], int(200_000 * 0.03 * 4))
            self.assertEqual(data["fits_with_description"]["shortest_first"], 2)
            tiny = sa.run_listing_budget(root, 0.0001, 200_000)      # 80 chars
            self.assertEqual(tiny["fits_with_description"]["shortest_first"], 1)
            self.assertEqual(tiny["fits_with_description"]["longest_first"], 0)


# --------------------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------------------

INVENTORY_BODY = """# Demo

<HARD-RULE>
Never skip the gate.
</HARD-RULE>

<HARD-GATE>
Stop before the merge.
</HARD-GATE>

A sentence that mentions HARD-RULE and <HARD-RULE> in prose is not a block.

## Step 1: Understand

```bash
# Step 9: a comment inside a fence is not a heading
# <!-- spawn-brief.v1 id=demo.approach -->
```

### Step 8a.2: Sign

<!-- contract:loop id=demo.fix-loop bound=2 on_exhaust=user -->

## Step 2: Build

See references/guide.md.
"""


class Inventory(unittest.TestCase):
    def _inventory(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            write_skill(Path(td), files=files)
            return sa.run_inventory(sa.SkillFiles.from_tree(Path(td), "demo"))

    def test_blocks_steps_and_anchors_in_file_order(self):
        inv = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY)})
        first = inv["files"][0]
        self.assertEqual([f["file"] for f in inv["files"]], ["SKILL.md", "references/guide.md"])
        self.assertEqual([(b["kind"], b["line"], b["end_line"]) for b in first["hard_blocks"]],
                         [("HARD-RULE", 8, 10), ("HARD-GATE", 12, 14)])
        self.assertTrue(all(len(b["sha256"]) == 64 and b["terminated"]
                            for b in first["hard_blocks"]))
        self.assertEqual([s["id"] for s in first["steps"]], ["1", "8a.2", "2"])
        self.assertEqual([(a["kind"], a["id"]) for a in first["anchors"]],
                         [("spawn-brief", "demo.approach"),
                          ("contract-loop", "id=demo.fix-loop bound=2 on_exhaust=user")])

    def test_a_block_hash_changes_with_one_character_and_not_with_its_position(self):
        base = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY)})
        moved = self._inventory({"SKILL.md": skill_md(body="intro\n\n" + INVENTORY_BODY)})
        edited = self._inventory({"SKILL.md": skill_md(
            body=INVENTORY_BODY.replace("Never skip the gate.", "Never skip the gate"))})
        digest = lambda inv: [b["sha256"] for b in inv["files"][0]["hard_blocks"]]  # noqa: E731
        self.assertEqual(digest(base), digest(moved))
        self.assertNotEqual(digest(base)[0], digest(edited)[0])
        self.assertEqual(digest(base)[1], digest(edited)[1])

    def test_compare_same_after_a_split_and_different_after_an_edit(self):
        base = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY)})
        head, tail = INVENTORY_BODY.split("### Step 8a.2: Sign")
        split = self._inventory({
            "SKILL.md": skill_md(body=head + "\nreferences/sign.md\n"),
            "references/sign.md": "### Step 8a.2: Sign" + tail})
        self.assertEqual(sa.compare_inventories(base, split), [])

        weakened = self._inventory({"SKILL.md": skill_md(
            body=INVENTORY_BODY.replace("Stop before the merge.", "Consider stopping."))})
        problems = sa.compare_inventories(base, weakened)
        self.assertTrue(any("HARD-GATE" in p and "missing or changed" in p for p in problems))

        dropped = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY.replace(
            "<!-- contract:loop id=demo.fix-loop bound=2 on_exhaust=user -->", "").replace(
            "## Step 2: Build", "## Build"))})
        problems = sa.compare_inventories(base, dropped)
        self.assertTrue(any("anchor contract-loop" in p for p in problems), problems)
        self.assertTrue(any("step ids differ" in p for p in problems), problems)

        swapped = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY.replace(
            "## Step 2: Build", "## Step X").replace("## Step 1: Understand", "## Step 2: Build")
            .replace("## Step X", "## Step 1: Understand"))})
        self.assertTrue(any("step order changed" in p
                            for p in sa.compare_inventories(base, swapped)))


    # -- fix round 1 (F2a, F2c) -------------------------------------------------------

    def _moved_out(self) -> tuple[dict, dict]:
        base = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY)})
        gate = "<HARD-GATE>\nStop before the merge.\n</HARD-GATE>\n"
        moved = self._inventory({
            "SKILL.md": skill_md(body=INVENTORY_BODY.replace(gate, "")
                                 + "\nreferences/gate.md\n"),
            "references/gate.md": "# Gate\n\n" + gate})
        return base, moved

    def test_a_block_moved_out_of_skill_md_is_a_difference(self):
        """F2a: counted corpus-wide, a must-hold block could leave SKILL.md unseen."""
        base, moved = self._moved_out()
        problems = sa.compare_inventories(base, moved)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("HARD-GATE", problems[0])
        self.assertIn("left SKILL.md", problems[0])
        self.assertIn("references/gate.md", problems[0])

    def test_a_reviewed_block_move_is_the_one_legal_exception(self):
        base, moved = self._moved_out()
        digest = base["files"][0]["hard_blocks"][1]["sha256"]
        ok = [{"sha256": digest, "file": "references/gate.md"}]
        self.assertEqual(sa.compare_inventories(base, moved, block_moves=ok), [])
        self.assertEqual(sa.compare_inventories(
            base, moved, block_moves=[{"sha256": digest[:12], "file": "references/gate.md"}]), [])
        elsewhere = [{"sha256": digest, "file": "references/other.md"}]
        self.assertTrue(sa.compare_inventories(base, moved, block_moves=elsewhere))
        other = [{"sha256": "0" * 64, "file": "references/gate.md"}]
        self.assertTrue(sa.compare_inventories(base, moved, block_moves=other))

    def test_a_block_that_moves_between_references_or_into_skill_md_is_not_flagged(self):
        gate = "<HARD-GATE>\nStop before the merge.\n</HARD-GATE>\n"
        old = self._inventory({"SKILL.md": skill_md(body="# Demo\n\nreferences/guide.md\n"),
                               "references/guide.md": "# Guide\n\n" + gate})
        hoisted = self._inventory({
            "SKILL.md": skill_md(body="# Demo\n\n" + gate + "\nreferences/guide.md\n"),
            "references/guide.md": "# Guide\n"})
        self.assertEqual(sa.compare_inventories(old, hoisted), [])

    def test_a_step_inside_a_reviewed_reorder_may_change_place(self):
        """A reorder the manifest records (and `conserve` holds whole and in order) is not
        reported a second time as a step-order change; an unrecorded one still is."""
        base = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY)})
        tail = "## Step 2: Build\n\nSee references/guide.md.\n"
        hoisted = self._inventory({"SKILL.md": skill_md(
            body=INVENTORY_BODY.replace(tail, "").replace(
                "## Step 1: Understand", tail + "\n## Step 1: Understand"))})
        self.assertTrue(any("step order changed" in p
                            for p in sa.compare_inventories(base, hoisted)))
        line = next(s["line"] for s in base["files"][0]["steps"] if s["id"] == "2")
        reviewed = [{"old_lines": (line, line + 2), "file": "SKILL.md"}]
        self.assertEqual(sa.compare_inventories(base, hoisted, reorders=reviewed), [])
        elsewhere = [{"old_lines": (1, 3), "file": "SKILL.md"}]
        self.assertTrue(sa.compare_inventories(base, hoisted, reorders=elsewhere))

    def test_a_reorder_exempts_the_heading_in_its_range_not_every_step_with_that_id(self):
        """Fix round 2 (R7): the exemption was keyed on the step id, so a reviewed reorder
        of one `Step 2` heading let every other heading numbered 2 change place too."""
        body = INVENTORY_BODY.replace(
            "## Step 1: Understand",
            "### Step 2: Check the inputs\n\nInputs.\n\n## Step 1: Understand")
        base = self._inventory({"SKILL.md": skill_md(body=body)})
        tail = "## Step 2: Build\n\nSee references/guide.md.\n"
        line = next(s["line"] for s in base["files"][0]["steps"]
                    if s["heading"] == "Step 2: Build")
        reviewed = [{"old_lines": (line, line + 2), "file": "SKILL.md"}]
        hoisted = body.replace(tail, "").replace("# Demo\n", "# Demo\n\n" + tail)
        self.assertEqual(sa.compare_inventories(
            base, self._inventory({"SKILL.md": skill_md(body=hoisted)}), reorders=reviewed), [])
        # the OTHER step 2 heading, outside the range, moves to the end of the file
        other = "### Step 2: Check the inputs\n\nInputs.\n\n"
        moved = body.replace(other, "") + "\n" + other
        problems = sa.compare_inventories(
            base, self._inventory({"SKILL.md": skill_md(body=moved)}), reorders=reviewed)
        self.assertTrue(any("step order changed" in p for p in problems), problems)

    def test_an_unterminated_block_is_an_inventory_problem(self):
        base = self._inventory({"SKILL.md": skill_md(body=INVENTORY_BODY)})
        broken = self._inventory({"SKILL.md": skill_md(
            body=INVENTORY_BODY.replace("Never skip the gate.\n</HARD-RULE>\n",
                                        "Never skip the gate.\n"))})
        self.assertTrue(sa.inventory_problems(broken))
        self.assertEqual(sa.inventory_problems(base), [])
        self.assertTrue(any("no closing" in p for p in sa.compare_inventories(base, broken)))

    def test_the_cli_exits_1_on_an_unterminated_block(self):
        with tempfile.TemporaryDirectory() as td:
            write_skill(Path(td), files={"SKILL.md": skill_md(
                body="# Demo\n\nreferences/guide.md\n<HARD-RULE>\nNever.\n")})
            rc, out, _ = run_cli("inventory", "demo", "--root", td)
            self.assertEqual(rc, 1)
            self.assertIn("UNTERMINATED", out)
            rc, out, _ = run_cli("inventory", "demo", "--root", td, "--json")
            self.assertEqual(rc, 1)
            self.assertTrue(json.loads(out)["problems"])


# --------------------------------------------------------------------------------------
# conserve
# --------------------------------------------------------------------------------------

OLD_SKILL = """---
name: demo
description: Demo skill.
---

# Demo

<HARD-RULE>
Never skip the gate.
</HARD-RULE>

## Step 1: Understand

Read the request.

```bash
echo one
```

## Step 2: Build

Build it carefully.

```bash
echo two
```

Then check the result.

## Step 3: Report

Say what happened.

<HARD-RULE>
Late rule that must be hoisted.
</HARD-RULE>

The end.
"""

#: Step 2 moved to a reference, byte for byte; nothing else touched.
NEW_SKILL = OLD_SKILL.replace("""## Step 2: Build

Build it carefully.

```bash
echo two
```

Then check the result.

""", "")
NEW_REFERENCE = """## Step 2: Build

Build it carefully.

```bash
echo two
```

Then check the result.
"""
def manifest(**kw) -> dict:
    out = {"extra_files": [], "deletes": Counter(), "adds": Counter(), "reorders": []}
    for key, value in kw.items():
        out[key] = Counter(value) if key in ("deletes", "adds") else value
    return out


class Conserve(unittest.TestCase):
    OLD = {"SKILL.md": OLD_SKILL}

    def check(self, new: dict, **kw) -> dict:
        return sa.conserve(self.OLD, new, manifest(**kw))

    def test_a_pure_move_passes(self):
        result = self.check({"SKILL.md": NEW_SKILL, "references/build.md": NEW_REFERENCE})
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["old_nonblank_lines"], result["new_nonblank_lines"])

    def test_an_untouched_skill_passes(self):
        self.assertTrue(self.check({"SKILL.md": OLD_SKILL})["ok"])

    def test_a_reworded_line_fails(self):
        reworded = NEW_REFERENCE.replace("Build it carefully.", "Build it with care.")
        result = self.check({"SKILL.md": NEW_SKILL, "references/build.md": reworded})
        self.assertFalse(result["ok"])
        self.assertEqual(result["count_problems"], 2)          # one lost, one appeared
        self.assertTrue(any("Build it carefully." in p and "lost" in p
                            for p in result["problems"]))
        self.assertTrue(any("Build it with care." in p and "added" in p
                            for p in result["problems"]))

    def test_a_whitespace_only_rewording_fails_too(self):
        shifted = NEW_REFERENCE.replace("echo two", "  echo two")
        self.assertFalse(self.check({"SKILL.md": NEW_SKILL,
                                     "references/build.md": shifted})["ok"])

    def test_a_dropped_line_fails(self):
        dropped = NEW_REFERENCE.replace("Then check the result.\n", "")
        result = self.check({"SKILL.md": NEW_SKILL, "references/build.md": dropped})
        self.assertFalse(result["ok"])
        self.assertTrue(any("Then check the result." in p and "lost" in p
                            for p in result["problems"]))

    def test_a_dropped_duplicate_line_fails_on_the_count(self):
        """A line that also occurs elsewhere (a fence) is still counted."""
        dropped = NEW_REFERENCE.replace("```bash\necho two\n```", "```bash\necho two")
        result = self.check({"SKILL.md": NEW_SKILL, "references/build.md": dropped})
        self.assertFalse(result["ok"])
        self.assertTrue(any("'```'" in p for p in result["problems"]), result["problems"])

    def test_a_reordered_span_fails(self):
        reordered = NEW_REFERENCE.replace(
            "Build it carefully.\n\n```bash\necho two\n```\n\nThen check the result.\n",
            "Then check the result.\n\n```bash\necho two\n```\n\nBuild it carefully.\n")
        result = self.check({"SKILL.md": NEW_SKILL, "references/build.md": reordered})
        self.assertEqual(result["count_problems"], 0, "every line is still there")
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(result["order_problems"], 1)
        self.assertTrue(any("order changed in references/build.md" in p
                            for p in result["problems"]))

    def test_reordered_duplicate_lines_between_two_anchors_fail(self):
        """The fence lines are not unique, so only the between-neighbours check sees it."""
        swapped = NEW_REFERENCE.replace("```bash\necho two\n```", "```\necho two\n```bash")
        result = self.check({"SKILL.md": NEW_SKILL, "references/build.md": swapped})
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"], "the opening and closing fence changed places")

    # -- fix round 1 (F6): duplicate lines at span boundaries -------------------------

    TWO_BLOCKS_OLD = OLD_SKILL.replace(
        "Then check the result.\n",
        "Then check the result.\n\n```bash\necho three\n```\n\nAnd once more.\n")
    TWO_BLOCKS_MOVED = ("## Step 2: Build\n\nBuild it carefully.\n\n```bash\necho two\n```\n\n"
                        "Then check the result.\n\n```bash\necho three\n```\n\n"
                        "And once more.\n")

    def two_blocks(self, reference: str) -> dict:
        new_skill = self.TWO_BLOCKS_OLD.replace(self.TWO_BLOCKS_MOVED + "\n", "")
        self.assertNotEqual(new_skill, self.TWO_BLOCKS_OLD)
        return sa.conserve({"SKILL.md": self.TWO_BLOCKS_OLD},
                           {"SKILL.md": new_skill, "references/build.md": reference}, manifest())

    def test_the_two_block_move_itself_passes(self):
        result = self.two_blocks(self.TWO_BLOCKS_MOVED)
        self.assertTrue(result["ok"], result["problems"])

    def test_closing_fences_moved_to_the_start_of_a_file_fail(self):
        """The reviewers' negative control: every line is still there, and no unique
        line changed place -- only the two closing fences, now the file's first lines."""
        moved = "```\n```\n" + self.TWO_BLOCKS_MOVED.replace("echo two\n```\n", "echo two\n") \
                                                      .replace("echo three\n```\n", "echo three\n")
        result = self.two_blocks(moved)
        self.assertEqual(result["count_problems"], 0, "every line is still there")
        self.assertFalse(result["ok"], "the closing fences left their blocks")
        self.assertGreaterEqual(result["order_problems"], 1)
        self.assertTrue(any("order changed in references/build.md" in p
                            for p in result["problems"]), result["problems"])

    def test_closing_fences_moved_to_the_end_of_a_file_fail(self):
        moved = self.TWO_BLOCKS_MOVED.replace("echo two\n```\n", "echo two\n") \
                                     .replace("echo three\n```\n", "echo three\n") + "```\n```\n"
        result = self.two_blocks(moved)
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"])

    def test_one_fence_moved_from_one_block_to_the_next_fails(self):
        """A duplicate line may not be lent by a neighbouring span: each old occurrence
        answers for one new line."""
        moved = self.TWO_BLOCKS_MOVED.replace("echo two\n```\n", "echo two\n") \
                                     .replace("echo three\n```\n", "echo three\n```\n```\n")
        result = self.two_blocks(moved)
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"])

    def test_duplicate_lines_around_a_reviewed_reorder_are_still_checked(self):
        first = OLD_SKILL.splitlines().index("Late rule that must be hoisted.")
        hoisted = OLD_SKILL.replace(
            "<HARD-RULE>\nLate rule that must be hoisted.\n</HARD-RULE>\n\n", "").replace(
            "## Step 1: Understand",
            "<HARD-RULE>\nLate rule that must be hoisted.\n</HARD-RULE>\n\n## Step 1: Understand")
        entry = [{"old_lines": (first, first + 2), "file": "SKILL.md"}]
        self.assertTrue(self.check({"SKILL.md": hoisted}, reorders=entry)["ok"])
        # the closing fence of block one now sits right after the moved span
        fence_moved = hoisted.replace("echo one\n```\n", "echo one\n").replace(
            "## Step 1: Understand", "```\n\n## Step 1: Understand")
        result = self.check({"SKILL.md": fence_moved}, reorders=entry)
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"])

    def test_a_split_into_several_files_at_duplicate_lines_passes(self):
        """No false alarm: two files cut exactly at a fence each keep their own."""
        old = {"SKILL.md": "# T\n\nintro\n\n```\none\n```\n\n```\ntwo\n```\n\nouter\n"}
        new = {"SKILL.md": "# T\n\nintro\n\nouter\n",
               "references/a.md": "```\none\n```\n", "references/b.md": "```\ntwo\n```\n"}
        result = sa.conserve(old, new, manifest())
        self.assertTrue(result["ok"], result["problems"])

    def test_a_file_made_only_of_repeated_lines_is_placed_or_refused(self):
        old = {"SKILL.md": "# T\n\nintro\n\n| a |\n|---|\n\nmid\n\n| a |\n|---|\n\nouter\n"}
        new = {"SKILL.md": "# T\n\nintro\n\n| a |\n|---|\n\nmid\n\nouter\n",
               "references/t.md": "| a |\n|---|\n"}
        self.assertTrue(sa.conserve(old, new, manifest())["ok"])
        new["references/t.md"] = "|---|\n| a |\n"
        result = sa.conserve(old, new, manifest())
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"], "the two table lines changed places")

    # -- fix round 1 (F2a): a must-hold block may not leave SKILL.md unseen -------------

    def test_a_hard_block_moved_out_of_skill_md_fails_without_a_manifest_entry(self):
        block = "<HARD-RULE>\nLate rule that must be hoisted.\n</HARD-RULE>\n"
        new = {"SKILL.md": OLD_SKILL.replace(block + "\n", ""),
               "references/rules.md": block}
        result = self.check(new)
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["block_problems"], 1)
        self.assertTrue(any("left SKILL.md" in p for p in result["problems"]))
        digest = [b for b in sa.hard_blocks(OLD_SKILL)][1]["sha256"]
        reviewed = self.check(new, block_moves=[{"sha256": digest,
                                                 "file": "references/rules.md"}])
        self.assertTrue(reviewed["ok"], reviewed["problems"])

    def test_a_reorder_inside_skill_md_fails_without_a_manifest_entry(self):
        hoisted = OLD_SKILL.replace(
            "<HARD-RULE>\nLate rule that must be hoisted.\n</HARD-RULE>\n\n", "").replace(
            "## Step 1: Understand",
            "<HARD-RULE>\nLate rule that must be hoisted.\n</HARD-RULE>\n\n## Step 1: Understand")
        result = self.check({"SKILL.md": hoisted})
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"])

        first = OLD_SKILL.splitlines().index("Late rule that must be hoisted.")   # 0-based
        reviewed = self.check({"SKILL.md": hoisted}, reorders=[
            {"old_lines": (first, first + 2), "file": "SKILL.md"}])
        self.assertTrue(reviewed["ok"], reviewed["problems"])

    def test_a_reviewed_reorder_may_hold_a_line_the_manifest_also_adds(self):
        """Fix round 1: a moved span that holds `fi` could not be matched once another
        entry ADDED a `fi` elsewhere -- the add was dropped from one side only."""
        old_skill = OLD_SKILL.replace("echo one\n", "if true; then\n  echo one\nfi\n")
        first = old_skill.splitlines().index("## Step 1: Understand") + 1     # 1-based
        last = old_skill.splitlines().index("## Step 2: Build") - 1
        span = "\n".join(old_skill.splitlines()[first - 1:last]) + "\n"
        moved = old_skill.replace(span, "").replace("The end.\n", span + "\nThe end.\n") \
                         .replace("echo two\n", "echo two\nfi\n")
        entry = [{"old_lines": (first, last), "file": "SKILL.md"}]
        result = sa.conserve({"SKILL.md": old_skill}, {"SKILL.md": moved},
                             manifest(reorders=entry, adds={"fi": 1}))
        self.assertTrue(result["ok"], result["problems"])
        broken = moved.replace("if true; then\n  echo one\n", "  echo one\nif true; then\n")
        result = sa.conserve({"SKILL.md": old_skill}, {"SKILL.md": broken},
                             manifest(reorders=entry, adds={"fi": 1}))
        self.assertFalse(result["ok"])

    def test_a_reviewed_reorder_must_arrive_whole(self):
        first = OLD_SKILL.splitlines().index("Late rule that must be hoisted.")
        broken = OLD_SKILL.replace(
            "<HARD-RULE>\nLate rule that must be hoisted.\n</HARD-RULE>\n\n", "").replace(
            "## Step 1: Understand",
            "<HARD-RULE>\n</HARD-RULE>\nLate rule that must be hoisted.\n\n## Step 1: Understand")
        result = self.check({"SKILL.md": broken}, reorders=[
            {"old_lines": (first, first + 2), "file": "SKILL.md"}])
        self.assertFalse(result["ok"])
        self.assertTrue(any("not whole and in order" in p for p in result["problems"]))

    def test_deletes_and_adds_are_legal_only_through_the_manifest(self):
        pointer = "Read references/build.md before this step."
        new_skill = NEW_SKILL.replace("## Step 3: Report", pointer + "\n\n## Step 3: Report") \
                             .replace("The end.\n", "")
        new = {"SKILL.md": new_skill, "references/build.md": NEW_REFERENCE}
        self.assertFalse(self.check(new)["ok"])
        self.assertFalse(self.check(new, adds={pointer: 1})["ok"])
        self.assertTrue(self.check(new, adds={pointer: 1}, deletes={"The end.": 1})["ok"])
        # a manifest that allows MORE than happened is as wrong as one that allows less
        self.assertFalse(self.check(new, adds={pointer: 2}, deletes={"The end.": 1})["ok"])

    def test_an_existing_reference_is_part_of_both_corpora(self):
        old = {"SKILL.md": OLD_SKILL, "references/old.md": "# Old\n\n```bash\necho kept\n```\n"}
        new = {"SKILL.md": NEW_SKILL, "references/build.md": NEW_REFERENCE,
               "references/old.md": "# Old\n\n```bash\necho kept\n```\n"}
        self.assertTrue(sa.conserve(old, new, manifest())["ok"])
        new["references/old.md"] = "# Old\n\n```bash\necho changed\n```\n"
        self.assertFalse(sa.conserve(old, new, manifest())["ok"])

    def test_manifest_loading_normalises_and_refuses_an_unreasoned_entry(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / sa.MANIFEST_FILE
            self.assertEqual(sa.load_manifest(path)["reorders"], [])      # absent = empty
            path.write_text(json.dumps({
                "extra_files": ["_meta/fn.sh"],
                "deletes": [{"lines": ["a", "", "b"], "count": 2, "reason": "duplicate copy"}],
                "adds": [{"text": "pointer", "reason": "pointer line"}],
                "changes": [{"old": "x", "new": "y", "reason": "own path made relative"}],
                "reorders": [{"old_lines": [5, 9], "file": "SKILL.md", "reason": "hoist"}],
            }), encoding="utf-8")
            m = sa.load_manifest(path)
            self.assertEqual(dict(m["deletes"]), {"a": 2, "b": 2, "x": 1})
            self.assertEqual(dict(m["adds"]), {"pointer": 1, "y": 1})
            self.assertEqual(m["reorders"], [{"old_lines": (5, 9), "file": "SKILL.md"}])
            self.assertEqual(m["extra_files"], ["_meta/fn.sh"])
            path.write_text(json.dumps({"block_moves": [
                {"sha256": "ab" * 32, "file": "references/x.md", "reason": "reviewed"}]}),
                encoding="utf-8")
            self.assertEqual(sa.load_manifest(path)["block_moves"],
                             [{"sha256": "ab" * 32, "file": "references/x.md"}])
            for bad in ({"block_moves": [{"sha256": "abc", "file": "x.md", "reason": "r"}]},
                        {"block_moves": [{"sha256": "ab" * 32, "file": "x.md"}]},
                        {"block_moves": [{"sha256": "ab" * 32, "reason": "r"}]}):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(bad=bad), self.assertRaises(sa.AuditError):
                    sa.load_manifest(path)
            for bad in ({"adds": [{"text": "pointer"}]},
                        {"deletes": [{"text": "x", "reason": ""}]},
                        {"reorders": [{"old_lines": [9, 5], "file": "SKILL.md", "reason": "r"}]},
                        {"changes": [{"old": "x", "reason": "r"}]}):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(bad=bad), self.assertRaises(sa.AuditError):
                    sa.load_manifest(path)


# -- fix round 2 (R1, R2): a manifest add or delete excuses a COUNT, never a text ---------

SHELL_OLD = """# Shell

Intro line.

## Step 1: Start

```bash
mkdir -p .work
if have_tool; then
  run_tool
else
  run_fallback
fi
if check_one; then
  keep_one
fi
```

Middle prose.

## Step 2: Record

```bash
mkdir -p .work
write_size
```

Closing prose.
"""
#: The one reviewed change: a guard with its own `fi` is added to the Step 2 block.
SHELL_NEW = SHELL_OLD.replace("write_size\n", "write_size\nif size_empty; then\n  drop_size\nfi\n")
SHELL_ADDS = {"if size_empty; then": 1, "  drop_size": 1, "fi": 1}


class ConserveExemptsByCount(unittest.TestCase):
    """Before: any line whose TEXT the manifest added or deleted somewhere was left out
    of the order check everywhere, so one added `fi` let every `fi` move."""

    def run_it(self, new: str, old: str = SHELL_OLD, **kw) -> dict:
        kw.setdefault("adds", SHELL_ADDS)
        return sa.conserve({"SKILL.md": old}, {"SKILL.md": new}, manifest(**kw))

    def assert_order_fails(self, new: str, **kw) -> None:
        self.assertNotEqual(new, SHELL_NEW)
        result = self.run_it(new, **kw)
        self.assertEqual(result["count_problems"], 0, result["problems"])
        self.assertFalse(result["ok"], "a repeated line moved and nothing noticed")
        self.assertGreaterEqual(result["order_problems"], 1)

    def test_the_reviewed_add_itself_passes(self):
        result = self.run_it(SHELL_NEW)
        self.assertTrue(result["ok"], result["problems"])

    def test_an_add_that_was_not_reviewed_still_fails_on_the_count(self):
        self.assertFalse(self.run_it(SHELL_NEW, adds={})["ok"])

    def test_NEGATIVE_CONTROL_a_fi_moved_above_else_fails(self):
        self.assert_order_fails(SHELL_NEW.replace(
            "else\n  run_fallback\nfi\n", "fi\nelse\n  run_fallback\n"))

    def test_NEGATIVE_CONTROL_a_fi_moved_three_lines_down_fails(self):
        self.assert_order_fails(SHELL_NEW.replace(
            "  run_fallback\nfi\nif check_one; then\n  keep_one\nfi\n",
            "  run_fallback\nif check_one; then\n  keep_one\nfi\nfi\n"))

    def test_NEGATIVE_CONTROL_a_fi_moved_far_above_its_block_fails(self):
        self.assert_order_fails(SHELL_NEW.replace("  run_fallback\nfi\n", "  run_fallback\n")
                                .replace("Intro line.\n", "fi\nIntro line.\n"))

    def test_NEGATIVE_CONTROL_a_fi_moved_to_the_end_of_the_file_fails(self):
        self.assert_order_fails(SHELL_NEW.replace("  run_fallback\nfi\n", "  run_fallback\n")
                                + "fi\n")

    def test_NEGATIVE_CONTROL_the_added_fi_does_not_excuse_a_second_one(self):
        """Both `fi` of the Step 1 block leave their place; the manifest adds ONE."""
        self.assert_order_fails(
            SHELL_NEW.replace("  run_fallback\nfi\n", "  run_fallback\n")
                     .replace("  keep_one\nfi\n", "  keep_one\n")
                     .replace("Closing prose.\n", "fi\nfi\nClosing prose.\n"))

    def test_a_deleted_occurrence_does_not_free_the_ones_that_stay(self):
        """`deletes: fi x1` removes the second `fi`; the first may still not move."""
        deleted = SHELL_OLD.replace("  keep_one\nfi\n", "  keep_one\n")
        self.assertTrue(self.run_it(deleted, adds={}, deletes={"fi": 1})["ok"])
        moved = deleted.replace("else\n  run_fallback\nfi\n", "fi\nelse\n  run_fallback\n")
        result = self.run_it(moved, adds={}, deletes={"fi": 1})
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"])

    def test_a_line_added_and_deleted_once_each_is_a_declared_move(self):
        """`deletes: X x1` with `adds: X x1` is how a manifest declares that one line
        moved: it is excused, and exactly one occurrence of it."""
        moved = SHELL_OLD.replace("Middle prose.\n\n", "").replace(
            "Closing prose.\n", "Closing prose.\n\nMiddle prose.\n")
        self.assertFalse(self.run_it(moved, adds={})["ok"])
        both = {"Middle prose.": 1}
        self.assertTrue(self.run_it(moved, adds=both, deletes=both)["ok"])

    # -- inside and beside a reviewed reorder ------------------------------------------

    def reordered(self):
        """The Step 1 block moves, whole, to the end of the file (a reviewed reorder)."""
        lines = SHELL_NEW.splitlines()
        first = lines.index("## Step 1: Start") + 1                       # 1-based
        last = lines.index("Middle prose.") - 1
        span = "\n".join(lines[first - 1:last]) + "\n"
        self.assertIn(span, SHELL_OLD)
        new = SHELL_NEW.replace(span, "") + "\n" + span
        return new, [{"old_lines": (first, last), "file": "SKILL.md"}]

    def test_the_reviewed_reorder_passes(self):
        new, entry = self.reordered()
        result = self.run_it(new, reorders=entry)
        self.assertTrue(result["ok"], result["problems"])

    def test_NEGATIVE_CONTROL_a_fi_moved_inside_a_reviewed_reorder_fails(self):
        new, entry = self.reordered()
        broken = new.replace("else\n  run_fallback\nfi\n", "fi\nelse\n  run_fallback\n")
        self.assertNotEqual(broken, new)
        result = self.run_it(broken, reorders=entry)
        self.assertEqual(result["count_problems"], 0)
        self.assertFalse(result["ok"], "the span did not arrive in order")

    def test_NEGATIVE_CONTROL_a_repeated_line_moved_to_the_edge_of_a_reorder_fails(self):
        """R2: the moved span was treated as a file edge, so a repeated line from further
        down (Step 2's `mkdir -p .work`) could be parked just before or after it."""
        lines = SHELL_NEW.splitlines()
        first = lines.index("## Step 2: Record") + 1
        last = lines.index("Closing prose.") - 1
        span = "\n".join(lines[first - 1:last]) + "\n"
        hoisted = SHELL_NEW.replace(span, "").replace("Intro line.\n\n",
                                                      "Intro line.\n\n" + span + "\n")
        entry = [{"old_lines": (first, last), "file": "SKILL.md"}]
        # the manifest adds sit inside the span, so the span is matched with them in it
        old = SHELL_NEW
        ok = sa.conserve({"SKILL.md": old}, {"SKILL.md": hoisted}, manifest(reorders=entry))
        self.assertTrue(ok["ok"], ok["problems"])
        for label, broken in (
                ("before", hoisted.replace("```bash\nmkdir -p .work\nif have_tool", "```bash\nif have_tool")
                                  .replace("Intro line.\n\n", "Intro line.\n\nmkdir -p .work\n")),
                ("after", hoisted.replace("```bash\nmkdir -p .work\nif have_tool", "```bash\nif have_tool")
                                 .replace("## Step 1: Start", "mkdir -p .work\n\n## Step 1: Start"))):
            with self.subTest(side=label):
                self.assertNotEqual(broken, hoisted)
                result = sa.conserve({"SKILL.md": old}, {"SKILL.md": broken},
                                     manifest(reorders=entry))
                self.assertEqual(result["count_problems"], 0, result["problems"])
                self.assertFalse(result["ok"], f"a repeated line parked {label} the span")


SPLIT_BASE = "a8f17a2"          # the revision the three core skills were split from


class RealSplitNegativeControls(unittest.TestCase):
    """The reviewers' repro on the real forge split: move one `fi` of the Step 1 block."""

    @classmethod
    def setUpClass(cls):
        root = REPO / "skills"
        probe = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                SPLIT_BASE + "^{commit}"], capture_output=True)
        if probe.returncode != 0:
            raise unittest.SkipTest(f"revision {SPLIT_BASE} is not in this checkout")
        cls.man = sa.load_manifest(root / "forge" / sa.MANIFEST_FILE)
        cls.old = dict(sa.SkillFiles.from_ref(root, "forge", SPLIT_BASE).files)
        cls.new = dict(sa.SkillFiles.from_tree(root, "forge").files)
        top, prefix = sa._git_top(root)
        for extra in cls.man["extra_files"]:
            cls.new["../" + extra] = sa._read(root / extra)
            if sa._git(top, "ls-tree", "--name-only", SPLIT_BASE, "--", prefix + extra).strip():
                cls.old["../" + extra] = sa._git(top, "show", f"{SPLIT_BASE}:{prefix}{extra}")
        lines = cls.new["SKILL.md"].split("\n")
        start = lines.index("### Step 1: Understanding (Lead Only)")
        cls.fi = lines.index("fi", start)
        assert lines[cls.fi - 2] == "else", lines[cls.fi - 2]
        cls.lines = lines

    def moved(self, to: int) -> dict:
        lines = list(self.lines)
        lines.pop(self.fi)
        lines.insert(to if to >= 0 else len(lines), "fi")
        return dict(self.new, **{"SKILL.md": "\n".join(lines)})

    def test_the_tree_as_it_is_passes(self):
        result = sa.conserve(self.old, self.new, self.man)
        self.assertTrue(result["ok"], result["problems"][:10])

    def test_NEGATIVE_CONTROL_each_move_of_the_first_fi_fails(self):
        for label, to in (("above else", self.fi - 2), ("three lines down", self.fi + 3),
                          ("30 lines above the block", self.fi - 34), ("end of file", -1)):
            with self.subTest(move=label):
                result = sa.conserve(self.old, self.moved(to), self.man)
                self.assertEqual(result["count_problems"], 0, result["problems"][:5])
                self.assertFalse(result["ok"], f"`fi` moved {label} and conserve passed")

    def test_NEGATIVE_CONTROL_a_repeated_line_parked_beside_the_moved_span_fails(self):
        """R2 on the real tree: Step 4's `mkdir -p .forge` moved above `### Step 1`."""
        lines = list(self.lines)
        step4 = lines.index("### Step 4: Write Design Doc")
        at = lines.index("mkdir -p .forge", step4)
        lines.pop(at)
        lines.insert(lines.index("### Step 1: Understanding (Lead Only)"), "mkdir -p .forge")
        result = sa.conserve(self.old, dict(self.new, **{"SKILL.md": "\n".join(lines)}),
                             self.man)
        self.assertEqual(result["count_problems"], 0, result["problems"][:5])
        self.assertFalse(result["ok"])


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout


class ConserveAgainstGit(unittest.TestCase):
    """The CLI, against a real revision: `git show REF:` is the old side."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name) / "repo"
        self.root = self.repo / "skills"
        base = self.root / "demo"
        base.mkdir(parents=True)
        (base / "SKILL.md").write_text(OLD_SKILL, encoding="utf-8", newline="")
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        _git(self.repo, "config", "commit.gpgsign", "false")
        _git(self.repo, "add", "-A")
        _git(self.repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "base")
        self.base = _git(self.repo, "rev-parse", "HEAD").strip()

    def split(self, reference: str = NEW_REFERENCE) -> None:
        base = self.root / "demo"
        (base / "SKILL.md").write_text(NEW_SKILL, encoding="utf-8", newline="")
        (base / "references").mkdir(exist_ok=True)
        (base / "references" / "build.md").write_text(reference, encoding="utf-8", newline="")

    def conserve(self, *extra: str) -> tuple[int, str, str]:
        return run_cli("conserve", "--before", self.base, "--skill", "demo",
                       "--root", str(self.root), *extra)

    def test_pure_move_passes_and_a_reworded_line_fails(self):
        self.split()
        rc, out, err = self.conserve()
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS", out)
        self.split(NEW_REFERENCE.replace("Build it carefully.", "Build it carefully!"))
        rc, out, _ = self.conserve("--json")
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(out)["ok"])

    def test_a_function_moved_into_a_script_is_conserved_through_extra_files(self):
        self.split()
        meta = self.root / "_meta"
        meta.mkdir()
        skill = self.root / "demo" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8").replace("echo one\n", ""),
                         encoding="utf-8", newline="")
        (meta / "fn.sh").write_text("echo one\n", encoding="utf-8")
        rc, out, _ = self.conserve()
        self.assertEqual(rc, 1, "without the manifest the line is lost")
        (self.root / "demo" / sa.MANIFEST_FILE).write_text(json.dumps(
            {"schema": "split-manifest.v1", "skill": "demo", "extra_files": ["_meta/fn.sh"]}),
            encoding="utf-8")
        rc, out, err = self.conserve()
        self.assertEqual(rc, 0, out + err)
        self.assertIn("_meta/fn.sh", out)

    def test_inventory_at_a_ref_and_against_it(self):
        self.split()
        rc, out, err = run_cli("inventory", "demo", "--root", str(self.root),
                               "--ref", self.base, "--json")
        self.assertEqual(rc, 0, err)
        old = json.loads(out)
        self.assertEqual([f["file"] for f in old["files"]], ["SKILL.md"])
        self.assertEqual(len(old["files"][0]["hard_blocks"]), 2)
        rc, out, _ = run_cli("inventory", "demo", "--root", str(self.root),
                             "--against", self.base)
        self.assertEqual(rc, 0, out)
        self.assertIn("SAME must-hold blocks", out)
        skill = self.root / "demo" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8").replace(
            "Never skip the gate.", "Skip the gate when in a hurry."),
            encoding="utf-8", newline="")
        rc, out, _ = run_cli("inventory", "demo", "--root", str(self.root),
                             "--against", self.base)
        self.assertEqual(rc, 1)
        self.assertIn("DIFFERENT", out)

    def test_an_unknown_ref_or_skill_is_bad_input_not_a_pass(self):
        rc, _, err = run_cli("conserve", "--before", "no-such-ref", "--skill", "demo",
                             "--root", str(self.root))
        self.assertEqual(rc, 2, err)
        rc, _, err = run_cli("conserve", "--before", self.base, "--skill", "nope",
                             "--root", str(self.root))
        self.assertEqual(rc, 2, err)


# --------------------------------------------------------------------------------------
# check, and the pre-commit arm
# --------------------------------------------------------------------------------------

FAILING = dict(description="Use when a bench rig drifts and its offsets need recomputing.")


class Check(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)
        self.root = self.repo / "skills"
        write_skill(self.root, "listed", **FAILING)
        write_skill(self.root, "unlisted", **FAILING)
        write_skill(self.root, "clean")
        (self.root / "_meta").mkdir()
        (self.root / "_meta" / sa.CONFORMANT_FILE).write_text(
            "# held to the standard\nlisted\nclean\n", encoding="utf-8")

    def check(self, *paths: str, stdin: bytes | None = None) -> tuple[int, str]:
        rc, out, err = run_cli("check", "--repo", str(self.repo), *paths, stdin=stdin)
        self.assertEqual(err, "")
        return rc, out

    def test_a_listed_skill_blocks_with_sa_e(self):
        rc, out = self.check("--", "skills/listed/references/guide.md")
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"(?m)^SA-E A5 skills/listed/SKILL\.md:3: ")
        self.assertNotIn("SA-W", out)

    def test_an_unlisted_skill_only_warns_with_sa_w(self):
        rc, out = self.check("--", "skills/unlisted/SKILL.md")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"(?m)^SA-W A5 skills/unlisted/SKILL\.md:3: ")
        self.assertNotIn("SA-E", out)

    def test_a_clean_skill_and_paths_outside_any_skill_print_nothing(self):
        rc, out = self.check("--", "skills/clean/SKILL.md", "docs/notes.md",
                             "skills/_meta/skill_audit.py", "skills/gone/SKILL.md",
                             "skills/README.md")
        self.assertEqual((rc, out), (0, ""))

    def test_paths_arrive_nul_separated_on_stdin(self):
        rc, out = self.check("--paths-from", "-",
                             stdin=b"skills/unlisted/SKILL.md\0skills/listed/SKILL.md\0")
        self.assertEqual(rc, 1)
        self.assertIn("SA-E A5 skills/listed/", out)
        self.assertIn("SA-W A5 skills/unlisted/", out)
        self.assertIn("2 skill(s), 1 blocking", out)

    def test_a_repo_with_no_conformant_list_never_blocks(self):
        (self.root / "_meta" / sa.CONFORMANT_FILE).unlink()
        rc, out = self.check("--", "skills/listed/SKILL.md")
        self.assertEqual(rc, 0)
        self.assertIn("SA-W A5", out)


class CheckReadsTheIndex(unittest.TestCase):
    """F3: the commit is what is staged. In a git repository `check` reads the skill, the
    conformant list and the exemption list from the INDEX; `--tree` is the explicit
    other choice, and a directory that is no repository has only its tree."""

    GOOD = skill_md(name="rigs")
    BAD = skill_md(name="rigs", **FAILING)
    LIST = "skills/_meta/standard-conformant.txt"

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name) / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        _git(self.repo, "config", "commit.gpgsign", "false")

    def put(self, rel: str, text: str, stage: bool = True) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
        if stage:
            _git(self.repo, "add", rel)

    def check(self, *args: str) -> tuple[int, str]:
        rc, out, err = run_cli("check", "--repo", str(self.repo), *args,
                               "--", "skills/rigs/SKILL.md")
        self.assertEqual(err, "")
        return rc, out

    def base(self, skill: str, listed: bool = True) -> None:
        self.put(self.LIST, "rigs\n" if listed else "# nobody\n")
        self.put("skills/rigs/SKILL.md", skill)
        self.put("skills/rigs/references/guide.md", "# Guide\n")

    def test_a_staged_failure_is_not_hidden_by_a_fixed_working_copy(self):
        self.base(self.BAD)
        self.put("skills/rigs/SKILL.md", self.GOOD, stage=False)
        rc, out = self.check()
        self.assertEqual(rc, 1, "the staged version fails, and that is what is committed")
        self.assertIn("SA-E A5 skills/rigs/SKILL.md", out)
        self.assertEqual(self.check("--tree"), (0, ""))

    def test_a_staged_clean_skill_is_not_blocked_by_a_broken_working_copy(self):
        self.base(self.GOOD)
        self.put("skills/rigs/SKILL.md", self.BAD, stage=False)
        self.assertEqual(self.check(), (0, ""))
        rc, out = self.check("--tree")
        self.assertEqual(rc, 1)
        self.assertIn("SA-E A5", out)

    def test_an_unstaged_reference_is_not_part_of_the_commit(self):
        self.base(self.GOOD)
        self.put("skills/rigs/references/orphan.md", "# Orphan\n", stage=False)
        self.assertEqual(self.check(), (0, ""))
        _git(self.repo, "add", "skills/rigs/references/orphan.md")
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("SA-E A7 skills/rigs/references/orphan.md", out)

    def test_a_reference_deleted_only_in_the_working_tree_is_still_staged(self):
        self.base(self.GOOD)
        (self.repo / "skills/rigs/references/guide.md").unlink()
        self.assertEqual(self.check(), (0, ""))

    def test_an_unstaged_edit_of_the_conformant_list_changes_nothing(self):
        self.base(self.BAD)
        self.put(self.LIST, "# rigs taken off the list, not staged\n", stage=False)
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("SA-E A5", out)
        self.base(self.BAD, listed=False)                 # and the other direction
        self.put(self.LIST, "rigs\n", stage=False)
        rc, out = self.check()
        self.assertEqual(rc, 0)
        self.assertIn("SA-W A5", out)

    def test_an_unstaged_edit_of_the_exemption_list_changes_nothing(self):
        line = "Run ~/.claude/skills/rigs/scripts/x.sh"
        exempt = json.dumps({"exemptions": {"rigs": [
            {"file": "SKILL.md", "line": line, "reason": "run from a project directory"}]}})
        own_path = skill_md(name="rigs", body=f"# Rigs\n\nreferences/guide.md\n\n{line}\n")
        self.base(own_path)
        self.put("skills/_meta/standard-exemptions.json", exempt, stage=False)
        rc, out = self.check()
        self.assertEqual(rc, 1, "the exemption is not staged")
        self.assertIn("SA-E A9", out)
        _git(self.repo, "add", "skills/_meta/standard-exemptions.json")
        self.put("skills/_meta/standard-exemptions.json", '{"exemptions": {}}', stage=False)
        self.assertEqual(self.check(), (0, ""), "the staged exemption list still holds")

    def test_a_skill_whose_skill_md_is_staged_for_deletion_is_not_audited(self):
        self.base(self.BAD)
        _git(self.repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "base")
        _git(self.repo, "rm", "-q", "--cached", "skills/rigs/SKILL.md")
        self.assertEqual(self.check(), (0, ""))

    def test_index_is_refused_outside_a_repository_and_auto_falls_back_to_the_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            write_skill(root, "rigs", **FAILING)
            rc, out, err = run_cli("check", "--repo", td, "--", "skills/rigs/SKILL.md")
            self.assertEqual((rc, err), (0, ""))
            self.assertIn("SA-W A5", out)
            rc, out, err = run_cli("check", "--repo", td, "--index", "--",
                                   "skills/rigs/SKILL.md")
            self.assertEqual(rc, 2)
            self.assertIn("--index", err)

    # -- fix round 2 (R5) ---------------------------------------------------------------

    def test_a_repo_directory_inside_a_checkout_is_refused_not_read_from_its_tree(self):
        """`--repo` below the top of a checkout has no index of its own. Reading its
        working tree without a word would judge text that is not the commit."""
        inner = self.repo / "vendor" / "lib"
        write_skill(inner / "skills", "rigs", **FAILING)
        rc, out, err = run_cli("check", "--repo", str(inner), "--", "skills/rigs/SKILL.md")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("top level", err)
        self.assertIn("--tree", err)
        rc, out, err = run_cli("check", "--repo", str(inner), "--tree", "--",
                               "skills/rigs/SKILL.md")
        self.assertEqual((rc, err), (0, ""), "the working tree, when it is asked for")
        self.assertIn("SA-W A5", out)

    def test_a_skill_md_staged_as_a_symlink_is_a_finding_not_a_skipped_skill(self):
        for listed, tag, expected in ((True, "SA-E", 1), (False, "SA-W", 0)):
            with self.subTest(listed=listed):
                self.base(self.GOOD, listed=listed)
                self.put("skills/shared.md", self.GOOD)
                target = self.repo / "skills/rigs/SKILL.md"
                target.unlink()
                try:
                    target.symlink_to("../shared.md")
                except (OSError, NotImplementedError):
                    self.skipTest("this file system has no symbolic links")
                _git(self.repo, "add", "skills/rigs/SKILL.md")
                mode = _git(self.repo, "ls-files", "-s", "skills/rigs/SKILL.md").split()[0]
                self.assertEqual(mode, "120000")
                rc, out = self.check()
                self.assertEqual(rc, expected, out)
                self.assertRegex(out, rf"(?m)^{tag} A3 skills/rigs/SKILL\.md: .*symbolic link")
                _git(self.repo, "rm", "-q", "-f", "--cached", "skills/rigs/SKILL.md")
                target.unlink()


@unittest.skipUnless(HOOK.exists(), f"python pre-commit not present: {HOOK}")
class PreCommitArm(unittest.TestCase):
    """The arm as git runs it: a throwaway repo, HOME pointed at an empty directory so
    only the vendored helpers can run (tests/hooks/hook_contract.py harness)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO / "tests" / "hooks"))
        import hook_contract                              # noqa: PLC0415
        cls.hc = hook_contract

    def run_hook(self, files: dict, drop_helper: bool = False, helper: str | None = None
                 ) -> tuple[int, str]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        repo = self.hc.build_repo(Path(td.name), self.hc.Scenario(
            name="skill_audit_arm", files=files, expect_exit=0))
        target = repo / "skills" / "_meta" / "skill_audit.py"
        self.assertTrue(target.is_file(), "hook_contract.VENDORED must carry skill_audit.py")
        if drop_helper:
            target.unlink()
        if helper is not None:
            target.write_text(helper, encoding="utf-8")
        return self.hc.run_hook(repo, HOOK, "pre-commit")

    BAD = skill_md(name="rigs", **FAILING)
    LIST = "skills/_meta/standard-conformant.txt"

    def test_a_failing_change_to_a_listed_skill_is_blocked(self):
        code, out = self.run_hook({self.LIST: "rigs\n", "skills/rigs/SKILL.md": self.BAD,
                                   "skills/rigs/references/guide.md": "# Guide\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED", out)
        self.assertIn("SA-E A5 skills/rigs/SKILL.md", out)
        self.assertIn("--no-verify", out, "the blocked message names the deliberate bypass")

    def test_the_same_change_to_an_unlisted_skill_only_warns(self):
        code, out = self.run_hook({self.LIST: "another-skill\n",
                                   "skills/rigs/SKILL.md": self.BAD,
                                   "skills/rigs/references/guide.md": "# Guide\n"})
        self.assertEqual(code, 0, out)
        self.assertNotIn("BLOCKED", out)
        self.assertIn("SA-W A5 skills/rigs/SKILL.md", out)

    def test_a_listed_skill_is_blocked_when_only_a_reference_is_staged(self):
        """The skill is judged, not the staged file: a new unnamed reference fails A7."""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        good = skill_md(name="rigs")
        repo = self.hc.build_repo(Path(td.name), self.hc.Scenario(
            name="skill_audit_arm", expect_exit=0,
            files={self.LIST: "rigs\n", "skills/rigs/SKILL.md": good,
                   "skills/rigs/references/guide.md": "# Guide\n"}))
        code, out = self.hc.run_hook(repo, HOOK, "pre-commit")
        self.assertEqual(code, 0, out)
        self.hc.git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "clean skill")
        (repo / "skills/rigs/references/orphan.md").write_text("# Orphan\n", encoding="utf-8")
        self.hc.git(repo, "add", "skills/rigs/references/orphan.md")
        code, out = self.hc.run_hook(repo, HOOK, "pre-commit")
        self.assertEqual(code, 1, out)
        self.assertIn("SA-E A7 skills/rigs/references/orphan.md", out)

    def staged_then_edited(self, staged: str, working: str, listed: str = "rigs\n",
                           working_list: str | None = None) -> tuple[int, str]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        repo = self.hc.build_repo(Path(td.name), self.hc.Scenario(
            name="skill_audit_arm", expect_exit=0,
            files={self.LIST: listed, "skills/rigs/SKILL.md": staged,
                   "skills/rigs/references/guide.md": "# Guide\n"}))
        (repo / "skills/rigs/SKILL.md").write_text(working, encoding="utf-8")
        if working_list is not None:
            (repo / self.LIST).write_text(working_list, encoding="utf-8")
        return self.hc.run_hook(repo, HOOK, "pre-commit")

    def test_the_hook_judges_what_is_staged_not_the_working_copy(self):
        """F3: stage a failing SKILL.md, fix the working copy without staging it."""
        code, out = self.staged_then_edited(self.BAD, skill_md(name="rigs"))
        self.assertEqual(code, 1, out)
        self.assertIn("SA-E A5 skills/rigs/SKILL.md", out)

    def test_the_hook_does_not_block_on_an_unstaged_breakage(self):
        code, out = self.staged_then_edited(skill_md(name="rigs"), self.BAD)
        self.assertEqual(code, 0, out)
        self.assertNotIn("SA-", out)

    def test_the_hook_reads_the_staged_conformant_list(self):
        code, out = self.staged_then_edited(self.BAD, self.BAD, working_list="# emptied\n")
        self.assertEqual(code, 1, out)
        self.assertIn("SA-E A5", out)

    def test_a_file_renamed_out_of_a_listed_skill_still_has_the_skill_audited(self):
        """Fix round 2 (R6): with rename detection the staged listing named only the
        destination, so a rename out of a listed skill left that skill unaudited."""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        repo = self.hc.build_repo(Path(td.name), self.hc.Scenario(
            name="skill_audit_arm", expect_exit=0, files={},
            committed={self.LIST: "rigs\n", "skills/rigs/SKILL.md": self.BAD,
                       "skills/rigs/references/guide.md": "# Guide\n\nA page of text.\n"},
            moves=(("skills/rigs/references/guide.md", "docs/guide.md"),)))
        listing = self.hc.git(repo, "diff", "--cached", "--name-status").stdout
        self.assertRegex(listing, r"^R\d+\s", "git must see this as a rename")
        code, out = self.hc.run_hook(repo, HOOK, "pre-commit")
        self.assertEqual(code, 1, out)
        self.assertIn("SA-E A5 skills/rigs/SKILL.md", out)

    def test_a_clean_listed_skill_passes_silently(self):
        code, out = self.run_hook({self.LIST: "rigs\n",
                                   "skills/rigs/SKILL.md": skill_md(name="rigs"),
                                   "skills/rigs/references/guide.md": "# Guide\n"})
        self.assertEqual(code, 0, out)
        self.assertNotIn("SA-", out)

    def test_a_missing_auditor_does_not_block(self):
        """Same as the other lint arms: a repo that does not vendor it is not wedged."""
        code, out = self.run_hook({self.LIST: "rigs\n", "skills/rigs/SKILL.md": self.BAD},
                                  drop_helper=True)
        self.assertEqual(code, 0, out)
        self.assertNotIn("BLOCKED", out)

    def test_a_crashing_auditor_fails_closed(self):
        code, out = self.run_hook(
            {self.LIST: "rigs\n", "skills/rigs/SKILL.md": skill_md(name="rigs"),
             "skills/rigs/references/guide.md": "# Guide\n"},
            helper="import sys\nraise RuntimeError('audit exploded')\n")
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED", out)
        self.assertIn("without a finding", out)

    def test_a_commit_that_stages_nothing_under_skills_never_runs_the_arm(self):
        code, out = self.run_hook({"docs/notes.md": "plain notes\n"},
                                  helper="import sys\nraise RuntimeError('must not run')\n")
        self.assertEqual(code, 0, out)
        self.assertNotIn("BLOCKED", out)


if __name__ == "__main__":
    unittest.main()
