#!/usr/bin/env python3
"""mail-scan -- test_mail_wiring.py (#351 WP-5, component mail-scan-wiring).

What makes the skill usable and safe to install: the permission rules of the settings
template, the reference a consumer builds its mail gate from, the rules reference, the entry
file, and the install into a throwaway home.

    TS-WIRE-01  the permission rules exist; the ask rule matches an override command line
                and no other command
    TS-WIRE-02  the gate reference states each required rule and carries the table
    TS-WIRE-03  an install into a throwaway home places the skill, the rules and the Codex
                symlink, and `doctor` passes from the installed copy
    TS-WIRE-04  the lists printed in rules-and-gaps.md equal the lists of the scripts

NOTHING HERE WRITES OUTSIDE A TEMP DIRECTORY. The home directory and `$FOUNDRY_MAILSCAN_ROOT`
point at an empty temporary directory for the whole module, and the module ends by asserting
it is still empty. The installer runs get a throwaway HOME and --claude-home and pass
--no-git-hooks, --no-extras and --no-log; the real ~/.claude, ~/.codex and ~/.foundry are
compared by one directory entry each before and after, never listed and never read. The
installer tests skip, with the reason, when this file is read from an installed copy (no
install.py beside skills/).

Every sample comes from `samples.py`, which builds it at call time.

Stdlib unittest; pytest only runs it. The scripts may not start a process; these tests may.
"""
from __future__ import annotations

import ast
import contextlib
import fnmatch
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
REFERENCES = SKILL / "references"
SKILLS = SKILL.parent
REPO = SKILLS.parent
INSTALLER = REPO / "install.py"
BOOTSTRAP = REPO / "bootstrap-environment.py"
TEMPLATE = REPO / "templates" / "settings.global.json"
sys.path.insert(0, str(SCRIPTS))

import mail_lists  # noqa: E402
import mail_reuse  # noqa: E402
import mail_scan  # noqa: E402
import mail_sender  # noqa: E402
import mail_state  # noqa: E402
import mailscan  # noqa: E402


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


samples = _load("mail_scan_samples", HERE / "samples.py")
rules_reference = _load("mail_scan_rules_reference", HERE / "rules_reference.py")

# The real home, as it was before this module pointed the home directory elsewhere. Only
# these directory entries are looked at; none is listed and nothing under them is read.
REAL_HOME = os.path.expanduser("~")
REAL_ENTRIES = [os.path.join(REAL_HOME, *parts) for parts in (
    (".claude", "skills", "mail-scan"), (".codex", "skills", "mail-scan"), (".foundry", "mail-scan"))]

RULES = samples.wiring_permission_rules()
ASK_GLOB = RULES["ask"][0][len("Bash("):-1]
WIDER_RULE = RULES["ask"][1]
WIDER_GLOB = WIDER_RULE[len("Bash("):-1]
OVERRIDE_TEXT = "%s %s" % (mailscan.PROGRAM, mailscan.COMMAND_OVERRIDE)
DEFAULT_ROOT = "~/" + "/".join(mail_state.DEFAULT_ROOT_PARTS)

_STATE = {}


def _entry_state(path: str):
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return (info.st_mode, info.st_mtime_ns, info.st_ino)


def setUpModule() -> None:
    _STATE["tmp"] = tempfile.mkdtemp(prefix="mail-wiring-home-")
    _STATE["real"] = [_entry_state(path) for path in REAL_ENTRIES]
    patcher = mock.patch.dict(os.environ, {"HOME": _STATE["tmp"], "USERPROFILE": _STATE["tmp"],
                                           "FOUNDRY_MAILSCAN_ROOT": os.path.join(_STATE["tmp"], "root")})
    patcher.start()
    _STATE["patcher"] = patcher


def tearDownModule() -> None:
    _STATE["patcher"].stop()
    left = sorted(os.listdir(_STATE["tmp"]))
    shutil.rmtree(_STATE["tmp"], ignore_errors=True)
    assert left == [], "the module wrote under the home directory: %s" % left
    assert [_entry_state(path) for path in REAL_ENTRIES] == _STATE["real"], "the real home changed"


def read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def squeezed(text: str) -> str:
    """Lower case, markup marks dropped, every run of white space one space."""
    return re.sub(r"\s+", " ", re.sub(r"[`*]", "", text)).lower()


def run_py(script: Path, *argv, cwd: Path = None, env: dict = None, isolated: bool = False) -> tuple:
    """Run a Python script as its own process. Returns (exit code, stdout + stderr)."""
    command = [sys.executable] + (["-I"] if isolated else []) + [str(script)] + [str(a) for a in argv]
    done = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return done.returncode, done.stdout + done.stderr


def load_installer():
    return _load("mail_wiring_install", INSTALLER)


needs_installer = unittest.skipUnless(INSTALLER.is_file() and TEMPLATE.is_file(),
                                      "no install.py beside this tree (an installed copy)")


# ---------------------------------------------------------------------------------------------
# TS-WIRE-01: the permission rules
# ---------------------------------------------------------------------------------------------

class TheRulesAsWritten(unittest.TestCase):
    """What the five rules say, whatever file holds them."""

    def test_the_rules_are_three_asks_and_two_denies_on_the_default_state_root(self):
        self.assertEqual(RULES["ask"], ["Bash(*%s*)" % OVERRIDE_TEXT, WIDER_RULE, "Edit(%s/**)" % DEFAULT_ROOT])
        self.assertEqual(WIDER_RULE, "Bash(*%s*%s*)" % (mailscan.PROGRAM.rsplit(".", 1)[0], mailscan.COMMAND_OVERRIDE))

    def test_the_wider_rule_covers_the_module_form_and_every_usual_line(self):
        # review C F8: `python3 -m mailscan override` has no file name for the first rule to match
        lines = samples.wiring_command_lines()
        for line in lines["asked"] + lines["asked_by_the_wider_rule"]:
            with self.subTest(line=line):
                self.assertTrue(fnmatch.fnmatchcase(line, WIDER_GLOB))
        for line in lines["asked_by_the_wider_rule"][:2]:
            self.assertFalse(fnmatch.fnmatchcase(line, ASK_GLOB), line)
        for line in lines["not_asked"]:
            with self.subTest(line=line):
                self.assertFalse(fnmatch.fnmatchcase(line, WIDER_GLOB))
        # what stays outside both: a copy under another name, a variable, the library
        for line in lines["around"][2:]:
            if "mailscan" not in line:
                self.assertFalse(fnmatch.fnmatchcase(line, WIDER_GLOB), line)

    def test_the_references_say_the_rules_bind_claude_code_only(self):
        for name in ("SKILL.md", "references/building-a-mail-gate.md"):
            text = squeezed(read(SKILL / name))
            with self.subTest(file=name):
                self.assertIn("bind claude code", text)
                self.assertIn("codex and agy", text)
                self.assertIn("without them", text)
        self.assertEqual(RULES["deny"], ["Read(%s/%s/**)" % (DEFAULT_ROOT, mail_state.DIR_VIEWS),
                                         "Read(%s/%s)" % (DEFAULT_ROOT, mail_state.FILE_KEY)])
        self.assertEqual(samples.WIRING_STATE_ROOT, DEFAULT_ROOT)

    def test_ts_wire_01_the_ask_rule_matches_every_usual_override_line(self):
        lines = samples.wiring_command_lines()["asked"]
        self.assertGreaterEqual(len(lines), 6)
        for line in lines:
            with self.subTest(line=line):
                self.assertTrue(fnmatch.fnmatchcase(line, ASK_GLOB))
                self.assertIn(OVERRIDE_TEXT, line)

    def test_ts_wire_01_the_ask_rule_matches_no_other_command(self):
        lines = samples.wiring_command_lines()["not_asked"]
        named = {word for line in lines for word in line.split() if word in mailscan.COMMANDS}
        self.assertEqual(named, set(mailscan.COMMANDS) - {mailscan.COMMAND_OVERRIDE})
        for line in lines:
            with self.subTest(line=line):
                self.assertFalse(fnmatch.fnmatchcase(line, ASK_GLOB))

    def test_the_rule_is_the_text_the_command_tests_hold_every_override_line_to(self):
        source = read(HERE / "test_mailscan_cli.py")
        found = re.search(r'(?m)^ASK_RULE_PATTERN = "([^"]+)"', source)
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), ASK_GLOB)

    def test_the_stated_limit_other_spellings_are_not_matched_and_the_skill_says_so(self):
        for line in samples.wiring_command_lines()["around"]:
            with self.subTest(line=line):
                self.assertFalse(fnmatch.fnmatchcase(line, ASK_GLOB))
        for name in ("SKILL.md", "references/building-a-mail-gate.md"):
            text = squeezed(read(SKILL / name))
            with self.subTest(file=name):
                self.assertIn("as it is normally typed", text)
                self.assertIn("another way", text)
                self.assertIn("audit trail", text)

    def test_a_moved_root_is_outside_the_rules_and_doctor_says_so(self):
        for bucket in RULES.values():
            for rule in bucket[2:] if bucket is RULES["ask"] else bucket:
                self.assertIn(DEFAULT_ROOT + "/", rule)
        self.assertIn("cover the default state root only", read(SCRIPTS / "mailscan.py"))
        gate = squeezed(read(REFERENCES / "building-a-mail-gate.md"))
        self.assertIn("is not covered by the rules", gate)
        self.assertIn("$foundry_mailscan_root", gate)


@needs_installer
class TheTemplateAndTheMerge(unittest.TestCase):
    """The template holds the rules, and an existing home gets them merged, not replaced."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.I = load_installer()
        cls.template = json.loads(read(TEMPLATE))

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mail-wiring-settings-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def by_bucket(self, pairs) -> dict:
        out = {}
        for bucket, rule in pairs:
            out.setdefault(bucket, []).append(rule)
        return out

    def test_ts_wire_01_the_template_holds_the_five_rules_after_the_intake_rules(self):
        intake = self.by_bucket(self.I.INTAKE_PERMISSION_RULES)
        permissions = self.template["permissions"]
        self.assertEqual(permissions["ask"], intake["ask"] + RULES["ask"])
        self.assertEqual(permissions["deny"], intake["deny"] + RULES["deny"])

    def test_the_template_is_changed_in_nothing_else(self):
        self.assertEqual(sorted(self.template["permissions"]), ["ask", "defaultMode", "deny"])
        self.assertEqual(self.template["permissions"]["defaultMode"], "auto")
        self.assertNotIn("allow", self.template["permissions"])
        self.assertEqual(sorted(self.template), ["effortLevel", "enabledPlugins", "hooks", "permissions",
                                                 "skillListingBudgetFraction", "skipWorkflowUsageWarning", "tui"])

    def test_the_installer_merges_the_same_five_rules(self):
        self.assertEqual(self.by_bucket(self.I.MAILSCAN_PERMISSION_RULES), RULES)
        self.assertEqual(self.I.PERMISSION_RULES, self.I.INTAKE_PERMISSION_RULES + self.I.MAILSCAN_PERMISSION_RULES)
        self.assertEqual(self.I.merge_missing_permission_rules(json.loads(json.dumps(self.template))), [])

    def test_a_home_that_has_the_intake_rules_gets_only_ours(self):
        doc = {"permissions": self.by_bucket(self.I.INTAKE_PERMISSION_RULES)}
        added = self.I.merge_missing_permission_rules(doc)
        self.assertEqual(self.by_bucket(added), RULES)
        self.assertEqual(self.I.merge_missing_permission_rules(doc), [])

    def test_an_existing_settings_file_is_merged_and_nothing_of_the_owner_is_lost(self):
        home = samples.wiring_home(self.tmp)
        own = home["own"]
        before = read(Path(home["settings"]))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            ok = self.I.install_settings(Path(home["claude_home"]), dry_run=True)
        self.assertTrue(ok, buffer.getvalue())
        for bucket, rules in RULES.items():
            for rule in rules:
                self.assertIn("would add permission rule to permissions.%s: %s" % (bucket, rule), buffer.getvalue())
        self.assertEqual(read(Path(home["settings"])), before)
        self.assertEqual(os.listdir(home["claude_home"]), ["settings.json"])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            ok = self.I.install_settings(Path(home["claude_home"]))
        self.assertTrue(ok, buffer.getvalue())
        after = json.loads(read(Path(home["settings"])))
        intake = self.by_bucket(self.I.INTAKE_PERMISSION_RULES)
        self.assertEqual(after["permissions"]["ask"], own["permissions"]["ask"] + intake["ask"] + RULES["ask"])
        self.assertEqual(after["permissions"]["deny"], own["permissions"]["deny"] + intake["deny"] + RULES["deny"])
        self.assertEqual(after["permissions"]["allow"], own["permissions"]["allow"])
        self.assertEqual(after["permissions"]["defaultMode"], "plan")
        self.assertEqual(after["model"], own["model"])
        self.assertEqual(after["env"], own["env"])
        backups = [name for name in os.listdir(home["claude_home"]) if name != "settings.json"]
        self.assertEqual(len(backups), 1)
        self.assertEqual(read(Path(home["claude_home"]) / backups[0]), before)
        # a second run adds nothing
        text = read(Path(home["settings"]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.I.install_settings(Path(home["claude_home"]))
        self.assertEqual(read(Path(home["settings"])), text)


# ---------------------------------------------------------------------------------------------
# TS-WIRE-02: the reference a consumer builds its gate from
# ---------------------------------------------------------------------------------------------

#: Every rule of the design section "Reference for the consumer", with the phrases that state it.
GATE_RULES = {
    "one process holds the credential": ["one process holds the credential"],
    "size first": ["read the size first", "before fetching its body"],
    "re-fetch and re-scan": ["re-fetch by uid and re-scan", "uidvalidity changed", "raw digest differs"],
    "the gate builds every header": ["the gate builds every header", "to is the reply target", "no cc or bcc",
                                     "text/plain"],
    "a fixed first line": ["a fixed first line", "ai draft"],
    "tls": ["verified tls on port 993 only"],
    "no other mailbox path": ["no store, copy, move, expunge, delete or send path", "never imports smtplib"],
    "crash-safe append": ["crash-safe append", "attempt id", "before append", "gate-generated message-id",
                          "appenduid", "no blind retry"],
    "one draft and a budget": ["one draft per record digest and a daily budget"],
    "the drafting model": ["no tools", "one framed view", "knowledge pack",
                           "only what a stranger may be told"],
    "purge": ["schedule purge"],
    "calibrate": ["run calibrate before trusting a provider profile", "one self-sent message",
                  "externally sent message carrying a forged authentication header"],
    "personal data": ["the view is personal data sent to a model provider", "pseudonymous"],
    "exit codes": ["any exit other than 0 or 1 means no draft",
                   "the reply decision, not the exit code, decides whether to draft"],
    "digests": ["place only a body and subject whose digests check-draft returned"],
}

#: The enforced-versus-convention table of the design, row for row.
GATE_TABLE = [
    ["Protection", "Same user as the agent", "Separate OS user (one-time root step)"],
    ["The scanner has no network, send or delete path", "enforced (import test)", "enforced"],
    ["A draft that fails the check is refused by `check-draft`", "enforced when the gate calls it", "same"],
    ["The agent cannot override a block by itself", "permission prompt plus the override log", "enforced"],
    ["The agent cannot read the mailbox credential", "convention", "enforced"],
    ["No process reaches mail-submission ports", "convention",
     "enforced by a firewall rule (not an HTTPS API send)"],
    ["The drafting model has no tools", "the consumer's convention", "same"],
]

#: What the reference says the skill does not catch, by a phrase each.
GATE_LIMITS = [
    "a polite, plain message passes", "the person who reads and sends the draft is the control",
    "spelled in words", "separated by a slash, a tilde, a comma, a colon, an underscore or letters",
    "outside the listed look-alikes", "that the inbound message itself holds",
    "newer than the built-in snapshot", "glued to a following letter", "mailto: links",
    "the shape of a sentence boundary", "inside the path of an allowed host",
    "first scanned in the same second", "carriage return alone",
    "waits for a person who is not there", "call the library from the service", "has not been run",
    # fix round 1: what the three reviews showed and the round does not close
    "is a brake on loops, not an abuse control", "still counts when the sender is unverified",
    "plus-addressing or any change of the from address", "more than two weeks after its last record",
    "a process of the same os user", "opens the records of the last fourteen days",
    "a parent, a subdomain or a sibling of the from domain",
    # fix round 2: the strict style reader and what it costs; what the draft check cannot close
    "it does not imitate a browser", "a marketing or notification template usually loses text",
    "no declaration rescues another", "nothing of it is shown", "text covered by another element",
    "a reader in dark mode", "the choice of words, of punctuation and of capital letters",
    "look-alike letters of scripts other than latin, cyrillic and greek", "a scheme nobody listed",
    "only the general combining marks are capped", "without a provider profile no dmarc failure is ever read",
    "every earlier message that got a draft counts", "an exact dkim or spf match verifies",
    "a file name given twice",
    # fix round 3: the claim is narrowed, the layout residue stated, white space narrowed to one bit,
    # the costs of a profile and of the draft check named
    "catches the common hiding tricks", "a reader that judges one element at a time cannot prove a layout harmless",
    "pushed far to the right or down, where it can be scrolled to", "paddings, word spacing and letter spacing summed",
    "one unbreakable run of characters", "the reversed order of <bdo dir=\"rtl\">",
    "outlook's word engine, the sanitiser of a web mailer and ios mail", "depends on the load of the host",
    "white space is narrowed to that one bit, not closed", "one bit a text", "uncertain-share",
    "what a profile costs", "an alias forward when the sender does not sign", "a mailing list that does not rewrite from",
    "never to a reply-to header", "gives no dmarc hold", "on a copy of the config that carries the candidate",
    "caution dmarc-fail: messages n", "caution auth-header-unreadable: messages n", "the signature line -- ",
    "the ideographic space of japanese and chinese", "draft-white-space", "draft-mixed-script",
]


def tables(text: str) -> list:
    """Every markdown table of a text, as lists of rows of stripped cells (the rule line dropped)."""
    out, current = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            if not re.fullmatch(r"\|(?:-+\|)+", line.replace(" ", "")):
                current.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif current:
            out.append(current)
            current = []
    return out


def code_blocks(text: str, language: str) -> list:
    return re.findall(r"(?ms)^```%s\n(.*?)^```$" % re.escape(language), text)


class TheGateReference(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = read(REFERENCES / "building-a-mail-gate.md")
        cls.flat = squeezed(cls.text)

    def test_ts_wire_02_every_rule_of_the_design_is_stated(self):
        self.assertEqual(len(GATE_RULES), 15)
        for rule, phrases in GATE_RULES.items():
            for phrase in phrases:
                with self.subTest(rule=rule, phrase=phrase):
                    self.assertIn(phrase, self.flat)

    def test_ts_wire_02_the_table_has_its_six_rows_and_three_columns(self):
        found = [table for table in tables(self.text) if table[0][0] == "Protection"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0], GATE_TABLE)
        self.assertEqual(len(found[0]) - 1, 6)
        self.assertTrue(all(len(row) == 3 for row in found[0]))

    def test_the_stated_limits_are_stated(self):
        for phrase in GATE_LIMITS:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)

    def test_the_override_convention_is_said_in_its_three_parts(self):
        for phrase in ("the ask rule covers the command as it is normally typed",
                       "can write an override without the prompt",
                       "the override log is the audit trail",
                       "a line with no good seal lifts nothing",
                       "a person, never an agent, lifts a hold"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)
        for rule in RULES["ask"][2:] + RULES["deny"]:
            tool = rule.split("(", 1)[0]
            self.assertIn(tool.lower(), self.flat)

    def test_it_holds_no_mailbox_code(self):
        self.assertIsNone(re.search(r"(?m)^\s*(?:import|from)\s+(?:imaplib|smtplib|poplib|socket|ssl|email)\b",
                                    self.text))
        for call in ("IMAP4", "SMTP(", "SMTP_SSL", ".login(", ".append(", ".sendmail(", "starttls"):
            self.assertNotIn(call, self.text)
        blocks = code_blocks(self.text, "python")
        self.assertEqual(len(blocks), 1)
        imported = set()
        for node in ast.walk(ast.parse(blocks[0])):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"sys", "mail_scan"})

    def test_every_library_name_it_gives_exists(self):
        named = set(re.findall(r"mail_scan\.([a-z_]+)\(", self.text))
        named |= {"scan_file", "effective", "effective_record", "read_config", "import_guard", "doctor", "calibrate"}
        self.assertGreaterEqual(named, {"scan_bytes", "check_draft", "load_config"})
        for name in sorted(named):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(mail_scan, name)))
        for name in ("ConfigError", "InputError"):
            self.assertIn(name, self.text)
            self.assertTrue(issubclass(getattr(mail_scan, name), Exception))
        result = mail_scan.ScanResult._fields
        self.assertIn("ScanResult(%s)" % ", ".join(result), self.text)
        self.assertIn("DraftResult(result, rule_hits, body_sha256, subject_sha256)", self.text)
        for word in mail_scan.SCAN_FAILURES:
            self.assertIn("`%s`" % word, self.text)
        self.assertIn("mail_state.add_override", self.text)
        self.assertTrue(callable(mail_state.add_override))

    def test_the_command_table_names_the_seven_commands_and_their_real_arguments(self):
        found = [table for table in tables(self.text) if table[0][0] == "Command"]
        self.assertEqual(len(found), 1)
        first_words = [row[0].strip("`").split()[0] for row in found[0][1:]]
        self.assertEqual(first_words, list(mailscan.COMMANDS))
        source = read(SCRIPTS / "mailscan.py")
        for flag in sorted(set(re.findall(r"--[a-z][a-z-]+", " ".join(row[0] for row in found[0][1:])))):
            with self.subTest(flag=flag):
                self.assertIn('"%s"' % flag, source)

    def test_the_config_table_is_the_keys_of_the_loader_and_its_example_loads(self):
        found = [table for table in tables(self.text) if table[0][0] == "Key"]
        self.assertEqual(len(found), 1)
        keys = [row[0].strip("`") for row in found[0][1:]]
        self.assertEqual(sorted(keys + ["schema"]), sorted(mail_scan.CONFIG_KEYS))
        self.assertIn("{:,}".format(mail_scan.MAX_BYTES_LIMIT), self.text)
        blocks = code_blocks(self.text, "json")
        self.assertEqual(len(blocks), 1)
        example = json.loads(blocks[0])
        self.assertEqual(mail_scan.read_config(example)["own_addresses"], example["own_addresses"])
        self.assertTrue(os.path.isabs(example["knowledge_pack"]))

    def test_what_it_says_calibrate_and_doctor_print_is_what_they_print(self):
        source = read(SCRIPTS / "mailscan.py") + read(SCRIPTS / "mail_scan.py") + read(SCRIPTS / "mail_state.py")
        for phrase in ("first header under the profile id", "retention: not running", "body sha256",
                       "subject sha256", "reply if released", "refused: "):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertIn(phrase, source)
        self.assertIn("%d parser behaviours" % len(mail_scan.PINNED_FACTS), self.text)
        self.assertIn("Python %d.%d" % mail_scan.PINNED_PYTHON, self.text)
        self.assertIn("at most {:,}".format(mail_scan.CALIBRATE_MAX_FILES), self.text)
        self.assertIn("{:,} bytes".format(mailscan.DRAFT_FILE_MAX_BYTES), self.text)

    def test_the_ages_and_the_budget_it_gives_are_those_of_the_lists(self):
        self.assertEqual((mail_lists.PURGE_VIEW_DAYS, mail_lists.PURGE_RECORD_DAYS, mail_lists.RETENTION_STALE_DAYS,
                          mail_lists.BUDGET_WINDOW_DAYS, mail_lists.BUDGET_EARLIER_DRAFTS), (7, 90, 2, 7, 3))
        for phrase in ("kept seven days", "kept 90 days", "older than two days",
                       "the fourth draft-eligible message of one sender in seven days is held"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)

    def test_it_has_a_contents_list_that_names_its_sections(self):
        headings = re.findall(r"(?m)^## (\d+)\. (.+)$", self.text)
        self.assertEqual([number for number, _title in headings], [str(n) for n in range(1, len(headings) + 1)])
        contents = self.text.split("## Contents", 1)[1].split("\n## ", 1)[0]
        for number, title in headings:
            self.assertIn("%s. %s" % (number, title), contents)


# ---------------------------------------------------------------------------------------------
# TS-WIRE-04: the rules reference equals the scripts
# ---------------------------------------------------------------------------------------------

def round_trip(value):
    return json.loads(json.dumps(rules_reference.plain(value)))


class TheRulesReference(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = read(REFERENCES / "rules-and-gaps.md")
        cls.entries = rules_reference.parse_entries(cls.text)

    def test_ts_wire_04_the_file_is_what_the_generator_writes_today(self):
        self.assertEqual(self.text, rules_reference.render())
        self.assertEqual(rules_reference.main(["--check"]), 0)

    def test_ts_wire_04_every_public_constant_of_the_lists_is_printed_with_its_value(self):
        titles = [title for title, _entries in rules_reference.sections()]
        printed = {}
        for title in titles:
            for name, value in self.entries.get(title, {}).items():
                self.assertNotIn(name, printed, name)
                printed[name] = value
        public = {name for name in vars(mail_lists) if not name.startswith("_") and name == name.upper()
                  and any(char.isalpha() for char in name)}
        self.assertGreater(len(public), 200)
        self.assertEqual(set(printed), public - set(rules_reference.TABLE_NAMES))
        for name in sorted(printed):
            with self.subTest(name=name):
                self.assertEqual(printed[name], round_trip(getattr(mail_lists, name)))

    def test_ts_wire_04_the_minimum_lists_of_the_design_read_back_as_lists(self):
        printed = {name: value for group in self.entries.values() for name, value in group.items()}
        self.assertEqual(printed["CONTROL_TOKENS"], list(mail_lists.CONTROL_TOKENS))
        self.assertEqual(printed["DANGEROUS_EXTENSIONS"], list(mail_lists.DANGEROUS_EXTENSIONS))
        self.assertNotIn("MULTI_LABEL_SUFFIXES", printed)      # removed in fix round 1: no suffix list
        self.assertEqual(printed["SCANNER_LINES"], list(mail_lists.SCANNER_LINES))
        self.assertEqual(printed["CSS_SAFE_PROPERTIES"], list(mail_lists.CSS_SAFE_PROPERTIES))
        self.assertEqual(printed["DEFAULT_IGNORABLE_RANGES"], [list(pair) for pair in mail_lists.DEFAULT_IGNORABLE_RANGES])
        self.assertEqual(printed["HIDDEN_PHRASE_PATTERNS"] + printed["HIDDEN_PHRASE_WEAK_PATTERNS"],
                         list(mail_lists.HIDDEN_PHRASE_PATTERNS + mail_lists.HIDDEN_PHRASE_WEAK_PATTERNS))
        self.assertEqual(printed["ELEMENT_ALLOWLIST"], list(mail_lists.ELEMENT_ALLOWLIST))
        self.assertEqual(printed["CHARSET_ALLOWLIST"], list(mail_lists.CHARSET_ALLOWLIST))
        self.assertEqual(printed["NO_REPLY_LOCAL_PART_PATTERN"], mail_lists.NO_REPLY_LOCAL_PART_PATTERN)
        self.assertEqual(printed["PHONE_PATTERN"], mail_lists.PHONE_PATTERN)
        self.assertEqual(printed["QUOTE_ATTRIBUTION_PATTERNS"], list(mail_lists.QUOTE_ATTRIBUTION_PATTERNS))
        self.assertEqual(printed["FRAME_LINE_PREFIX"], mail_lists.FRAME_LINE_PREFIX)
        self.assertEqual(printed["LISTS_VERSION"], mail_lists.LISTS_VERSION)
        self.assertEqual([bytes.fromhex(item["bytes"]) for row in printed["SIGNATURES"] for item in row["leading"]],
                         [lead for row in mail_lists.SIGNATURES for lead in row.leading])
        self.assertEqual(printed["DRAFT_TLDS"]["set"], sorted(mail_lists.DRAFT_TLDS))
        self.assertEqual(printed["ROLE_LABEL_LINE"]["flags"], ["IGNORECASE", "MULTILINE"])

    def test_ts_wire_04_the_words_of_the_other_scripts_are_printed_with_their_values(self):
        count = 0
        for module, title, names in rules_reference.OTHER_MODULES:
            self.assertEqual(sorted(self.entries[title]), sorted(names))
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertEqual(self.entries[title][name], round_trip(getattr(module, name)))
                    count += 1
        self.assertGreater(count, 55)
        printed = {name: value for group in self.entries.values() for name, value in group.items()}
        for name, module in (("SENDER_STATUSES", mail_sender), ("SENDER_REASONS", mail_sender),
                             ("ERRORS", mail_state), ("MODE_LABELS", mail_state), ("CONFIG_CODES", mail_scan),
                             ("CONFIG_KEY_WORDS", mail_scan), ("INPUT_CODES", mail_scan),
                             ("SCAN_FAILURES", mail_scan), ("GUARD_KINDS", mail_scan),
                             ("FORBIDDEN_MODULES", mail_scan), ("FORBIDDEN_MODULES_MORE", mail_scan),
                             ("FORBIDDEN_OS_NAMES", mail_scan), ("FORBIDDEN_OS_PREFIXES", mail_scan),
                             ("DOCTOR_LEVELS", mail_scan), ("COMMANDS", mailscan), ("LABELS", mailscan),
                             ("TAG_RANGES", mail_reuse), ("BIDI_RANGES", mail_reuse)):
            self.assertEqual(printed[name], round_trip(getattr(module, name)), name)
        for word in (mailscan.ERROR_INTERNAL, mailscan.ERROR_INTERRUPTED, mailscan.ERROR_NOT_LOADED):
            self.assertIn('"%s"' % word, self.text)

    def test_ts_wire_04_every_rule_id_is_in_a_table_with_its_class_hold_and_reply(self):
        rows = []
        for _rule_class, title, _note in rules_reference.RULE_CLASS_NOTES:
            heading = [line for line in self.text.splitlines() if line.startswith("### %s (" % title)]
            self.assertEqual(len(heading), 1, title)
            rows += rules_reference.parse_table(self.text, heading[0])
        self.assertEqual([tuple(row) for row in rows], [tuple(rule) for rule in mail_lists.RULES.values()])
        self.assertEqual(len(rows), len(mail_lists.BLOCK_RULE_IDS) + len(mail_lists.CAUTION_RULE_IDS)
                         + len(mail_lists.REPLY_RULE_IDS) + len(mail_lists.REFUSE_RULE_IDS))
        self.assertEqual({row[1] for row in rows}, set(mail_lists.RULE_CLASSES))

    def test_ts_wire_04_every_gap_is_in_the_table_with_its_class_and_reply_effect(self):
        rows = rules_reference.parse_table(self.text, "## 3. Gap table")
        self.assertEqual([tuple(row) for row in rows], [tuple(gap) for gap in mail_lists.GAPS.values()])
        self.assertEqual([row[0] for row in rows], list(mail_lists.GAP_NAMES))
        for row in rows:
            self.assertIn(row[1], mail_lists.GAP_CLASSES)
            self.assertIn(row[2], mail_lists.REPLY_EFFECTS)

    def test_the_override_table_has_one_row_for_each_kind(self):
        rows = rules_reference.parse_table(self.text, "## 4. Override table")
        self.assertEqual([row[0] for row in rows], list(mail_lists.OVERRIDE_KINDS))
        by_kind = {row[0]: row for row in rows}
        self.assertIn("caution", by_kind[mail_lists.HOLD_BLOCK][1])
        self.assertIn(mail_lists.REPLY_NONE_LIST, by_kind[mail_lists.OVERRIDE_LIST][1])
        self.assertIn(mail_lists.REPLY_DRAFT, by_kind[mail_lists.OVERRIDE_LIST][2])
        for kind in mail_lists.HOLD_KINDS:
            self.assertIn("reply_if_released", by_kind[kind][2])

    def test_a_changed_entry_makes_the_reference_stale(self):
        with mock.patch.object(mail_lists, "MAX_PARTS", mail_lists.MAX_PARTS + 1):
            self.assertNotEqual(rules_reference.render(), self.text)
        with mock.patch.object(mail_lists, "DANGEROUS_EXTENSIONS", mail_lists.DANGEROUS_EXTENSIONS + ("xyz",)):
            self.assertNotEqual(rules_reference.render(), self.text)
        changed = dict(mail_lists.RULES)
        first = next(iter(changed.values()))
        changed[first.rule_id] = first._replace(rule_class=mail_lists.CLASS_CAUTION)
        with mock.patch.object(mail_lists, "RULES", changed):
            self.assertNotEqual(rules_reference.render(), self.text)
        self.assertEqual(rules_reference.render(), self.text)

    def test_hostile_strings_are_printed_as_escapes_never_as_themselves(self):
        self.assertTrue(self.text.isascii())
        inside = False
        for line in self.text.splitlines():
            if line.startswith(rules_reference.FENCE):
                inside = not inside
            elif inside and not line.startswith("#"):
                # a printed value; a comment of the module may name an element in angle brackets
                self.assertNotIn("<", line)
                self.assertNotIn(">", line)
        for token in mail_lists.CONTROL_TOKENS:
            self.assertNotIn(token, self.text)
        self.assertIsNone(mail_lists.FRAME_FORGERY.search(self.text))
        self.assertIsNone(mail_reuse.HIDDEN_UNICODE.search(self.text))
        self.assertIsNone(mail_reuse.TOKEN_PATTERN.search(self.text))
        self.assertTrue(all(len(line) <= 1000 for line in self.text.split("\n")))
        self.assertIsNone(re.search(r"(?m)^(?:permissions|hooks)\s*:", self.text))

    def test_what_was_decided_after_the_first_design_is_in_the_text(self):
        flat = squeezed(self.text)
        for phrase in ("from-name-irregular", "bare-cr", "comment-conditional", "attachment-active-content",
                       "hidden-phrase-weak", "proven-hidden removed text only", "a message is placed by its first record",
                       "only the first authentication-results header is read", "none-automated wins over everything",
                       "one whole run of the inbound view", "is not a run", "are two numbers",
                       "the three subdivision flags",
                       # fix round 1
                       "equal to the from domain", "no list of public suffixes",
                       "behind the note prefix", "seconds for the parse, the view and the rules", "decoded as windows-1252",
                       "never the body", "a reader that ignores the parameter", "unseen-characters",
                       # fix round 2
                       "the view does not imitate a browser", "never decides that one declaration beats another",
                       "a later, a more specific, an !important or an inline value rescues nothing",
                       "applies its rule to every element", "nothing of the part is shown", "uncertain in full",
                       "a marketing or notification template", "font is not accepted",
                       "gives any parameter more than once in any form"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat)
        self.assertIn("Lists version: `%s`" % mail_lists.LISTS_VERSION, self.text)

    def test_the_generator_refuses_a_command_line_it_does_not_know(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rules_reference.main([]), 3)
            self.assertEqual(rules_reference.main(["--write", "x"]), 3)


# ---------------------------------------------------------------------------------------------
# The entry file, and the skill as a whole
# ---------------------------------------------------------------------------------------------

def skill_files() -> list:
    out = []
    for dirpath, dirnames, filenames in os.walk(str(SKILL)):
        dirnames[:] = sorted(d for d in dirnames if d not in ("__pycache__", ".pytest_cache"))
        out.extend(Path(dirpath) / name for name in sorted(filenames))
    return out


class TheEntryFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = read(SKILL / "SKILL.md")
        cls.flat = squeezed(cls.text)
        found = re.search(r'(?m)^description: "(.+)"$', cls.text)
        cls.description = found.group(1) if found else ""

    def test_the_description_front_loads_the_subject_inside_the_limit(self):
        self.assertTrue(self.description.startswith("Email protection"))
        self.assertFalse(self.description.lower().startswith("use when"))
        self.assertLessEqual(len(self.description), 250)
        self.assertIn("Use when", self.description)
        self.assertNotIn("UNDER CONSTRUCTION", self.text)

    def test_it_names_the_three_related_skills_and_they_exist(self):
        for name in ("llm-security", "intake-scan", "secret-scanning"):
            self.assertIn("`%s`" % name, self.text)
            self.assertTrue((SKILLS / name / "SKILL.md").is_file(), name)

    def test_it_says_an_agent_never_opens_a_view_and_never_overrides_by_itself(self):
        for phrase in ("never open a file under views/", "never run the override command without the user",
                       "it is the user's decision", "do not spell it another way",
                       "it is addressed to nobody"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)
        self.assertIn(OVERRIDE_TEXT, self.text)

    def test_it_says_which_result_decides_and_that_calibration_was_not_run(self):
        for phrase in ("the reply decision decides, not the verdict and not the exit code",
                       "any exit other than 0 or 1 means no draft",
                       "calibrate on real mail is the service owner's step and has not been run"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)
        for word in mail_lists.VERDICTS + mail_lists.REPLIES + mail_lists.HOLD_KINDS:
            self.assertIn("`%s`" % word, self.text)

    def test_it_says_what_the_skill_is_not(self):
        for phrase in ("it reads no mailbox and sends nothing", "no model, no phrase matching",
                       "never opened", "no url is fetched", "email only"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.flat)

    def test_the_commands_and_the_ages_it_gives_are_real(self):
        for command in mailscan.COMMANDS:
            self.assertIn(command, self.text)
        self.assertIn("kept %d days" % mail_lists.PURGE_RECORD_DAYS, self.text)
        self.assertIn("kept %d days" % mail_lists.PURGE_VIEW_DAYS, self.text)
        self.assertIn("$" + mail_state.ENV_ROOT, self.text)
        self.assertIn(DEFAULT_ROOT, self.text)
        self.assertIn("Python standard library only", self.text)
        self.assertIn("%d.%d" % mail_scan.PINNED_PYTHON, self.text)

    def test_every_file_it_points_at_exists(self):
        for rel in sorted(set(re.findall(r"`((?:references|scripts)/[A-Za-z0-9_./-]+)`", self.text))):
            with self.subTest(file=rel):
                self.assertTrue((SKILL / rel).is_file())
        self.assertIn("references/building-a-mail-gate.md", self.text)
        self.assertIn("references/rules-and-gaps.md", self.text)
        self.assertTrue((HERE / "rules_reference.py").is_file())

    def test_the_skill_audit_and_the_frontmatter_lint_report_nothing(self):
        audit = SKILLS / "_meta" / "skill_audit.py"
        lint = SKILLS / "_meta" / "frontmatter_lint.py"
        if not (audit.is_file() and lint.is_file()):
            self.skipTest("the lints are not beside this tree")
        code, out = run_py(audit, "audit", "--root", SKILLS, "--only", "mail-scan", "--strict", cwd=SKILLS.parent)
        self.assertEqual(code, 0, out)
        self.assertIn("0 fail(s)", out)
        code, out = run_py(lint, "check", SKILL / "SKILL.md", cwd=SKILLS.parent)
        self.assertEqual(code, 0, out)
        self.assertIn("0 failing", out)
        self.assertIn("0 with warnings", out)


class TheSkillAsAWhole(unittest.TestCase):

    def test_no_consumer_project_and_no_host_path_is_named_anywhere(self):
        words = ["the" + "cpu" + "hub", "cpu" + "hub", "hosting" + "er", "/mnt/" + "data", "/home/" + "adm"]
        for path in skill_files():
            text = read(path).lower()
            for word in words:
                with self.subTest(file=str(path.relative_to(SKILL)), word=word):
                    self.assertNotIn(word, text)

    def test_every_example_address_and_host_is_a_reserved_name(self):
        reserved = re.compile(r"(?:^|\.)(?:example\.(?:org|com|net)|invalid|test|example|localhost)$")
        for name in ("SKILL.md", "references/building-a-mail-gate.md"):
            for host in re.findall(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", read(SKILL / name)):
                with self.subTest(file=name, host=host):
                    self.assertRegex(host.lower(), reserved)

    def test_the_skill_is_standard_library_only_scripts_and_tests_alike(self):
        local = {path.stem for path in skill_files() if path.suffix == ".py"}
        local |= {"mail_scan_samples", "mail_scan_rules_reference"}
        foreign = set()
        for path in skill_files():
            if path.suffix != ".py":
                continue
            for node in ast.walk(ast.parse(read(path))):
                if isinstance(node, ast.Import):
                    foreign.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    foreign.add(node.module.split(".")[0])
        self.assertEqual(sorted(foreign - set(sys.stdlib_module_names) - local), [])

    def test_the_references_store_no_hostile_text_as_itself(self):
        for path in sorted(REFERENCES.glob("*.md")) + [SKILL / "SKILL.md"]:
            text = read(path)
            with self.subTest(file=path.name):
                self.assertTrue(text.isascii())
                self.assertIsNone(mail_reuse.HIDDEN_UNICODE.search(text))
                self.assertEqual(mail_reuse.STRIPPED.find(text), [])
                self.assertIsNone(mail_reuse.TOKEN_PATTERN.search(text))
                for token in mail_lists.CONTROL_TOKENS:
                    self.assertNotIn(token, text)
                self.assertIsNone(mail_lists.FRAME_FORGERY.search(text))
        self.assertEqual(sorted(path.name for path in REFERENCES.iterdir()),
                         ["building-a-mail-gate.md", "rules-and-gaps.md"])

    def test_the_new_files_are_ascii(self):
        for name in ("tests/test_mail_wiring.py", "tests/rules_reference.py", "SKILL.md",
                     "references/building-a-mail-gate.md", "references/rules-and-gaps.md"):
            self.assertTrue((SKILL / name).read_bytes().isascii(), name)

    def test_the_wiring_builders_are_listed_for_this_component(self):
        self.assertEqual(samples.BUILDERS["mail-scan-wiring"],
                         ("wiring_permission_rules", "wiring_command_lines", "wiring_home", "wiring_codex_stub"))
        self.assertEqual(json.loads(read(HERE / "manifest.json")), samples.manifest())


# ---------------------------------------------------------------------------------------------
# TS-WIRE-03: the install proof
# ---------------------------------------------------------------------------------------------

def install(home: Path, mode: str, *extra: str) -> tuple:
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    for key in ("CLAUDE_CONFIG_DIR", "FOUNDRY_MAILSCAN_ROOT", "PYTHONPATH"):
        env.pop(key, None)
    return run_py(INSTALLER, "--target", "c", "--mode", mode, "--noninteractive", "--no-git-hooks", "--no-extras",
                  "--no-log", "--claude-home", home / ".claude", *extra, cwd=REPO, env=env)


@needs_installer
class TheInstallProof(unittest.TestCase):
    """One copy-mode install into a throwaway home that already has settings of its owner."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="mail-wiring-install-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        made = samples.wiring_home(str(cls.tmp))
        cls.own = made["own"]
        cls.home = Path(made["home"])
        cls.claude = Path(made["claude_home"])
        cls.settings = Path(made["settings"])
        cls.settings_before = read(cls.settings)
        cls.dry_code, cls.dry_out = install(cls.home, "move", "--dry-run")
        # (the installer's scan of the host runs other tools, which may write under that HOME)
        cls.dry_left = sorted(str(p.relative_to(cls.home)) for p in cls.claude.rglob("*"))
        cls.dry_settings = read(cls.settings)
        cls.code, cls.out = install(cls.home, "move")
        cls.tree = cls.claude / "skills"
        cls.placed = cls.tree / "mail-scan"

    def child_env(self, **more) -> dict:
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        env.update(more)
        return env

    def test_ts_wire_03_the_dry_run_names_the_rules_and_places_nothing(self):
        self.assertEqual(self.dry_code, 0, self.dry_out)
        self.assertIn("dry run complete", self.dry_out)
        self.assertEqual(self.dry_left, [".claude/settings.json"])
        self.assertEqual(self.dry_settings, self.settings_before)
        for bucket, rules in RULES.items():
            for rule in rules:
                self.assertIn("would add permission rule to permissions.%s: %s" % (bucket, rule), self.dry_out)

    def test_ts_wire_03_the_install_exits_zero_into_the_throwaway_home_only(self):
        self.assertEqual(self.code, 0, self.out)
        self.assertNotIn("Traceback", self.out)
        self.assertTrue(self.placed.is_dir())
        self.assertFalse(self.placed.is_symlink())

    def test_ts_wire_03_the_skill_is_placed_whole_and_byte_equal(self):
        count = 0
        for source in skill_files():
            rel = source.relative_to(SKILL)
            with self.subTest(file=str(rel)):
                self.assertTrue((self.placed / rel).is_file())
                self.assertEqual((self.placed / rel).read_bytes(), source.read_bytes())
            count += 1
        self.assertGreater(count, 25)
        for rel in ("SKILL.md", "scripts/mailscan.py", "scripts/mail_scan.py", "scripts/mail_lists.py",
                    "schemas/mail-verdict.v1.json", "schemas/mail-scan-config.v1.json",
                    "references/building-a-mail-gate.md", "references/rules-and-gaps.md"):
            self.assertTrue((self.placed / rel).is_file(), rel)
        for beside in ("intake-scan/scripts/intake_policy.py", "intake-scan/scripts/harness_rules.py",
                       "secret-scanning/scripts/secrets-scan.py"):
            self.assertTrue((self.tree / beside).is_file(), beside)

    def test_ts_wire_03_the_settings_of_that_home_hold_the_rules_merged_in(self):
        after = json.loads(read(self.settings))
        ask, deny = after["permissions"]["ask"], after["permissions"]["deny"]
        self.assertEqual(ask[:1], self.own["permissions"]["ask"])
        self.assertEqual(deny[:1], self.own["permissions"]["deny"])
        self.assertEqual(ask[-len(RULES["ask"]):], RULES["ask"])
        self.assertEqual(deny[-len(RULES["deny"]):], RULES["deny"])
        self.assertEqual(len(ask), len(set(ask)))
        self.assertEqual(after["permissions"]["allow"], self.own["permissions"]["allow"])
        self.assertEqual(after["permissions"]["defaultMode"], "plan")
        self.assertEqual(after["model"], self.own["model"])
        self.assertEqual(after["env"], self.own["env"])
        backups = [p for p in self.claude.iterdir() if p.name.startswith("settings.json") and p.name != "settings.json"]
        self.assertEqual(len(backups), 1)
        self.assertEqual(read(backups[0]), self.settings_before)
        self.assertTrue(fnmatch.fnmatchcase("python3 %s %s 20261013T080000Z-0a1b2c3d --kind block --reason seen"
                                            % (self.placed / "scripts" / mailscan.PROGRAM, mailscan.COMMAND_OVERRIDE),
                                            ASK_GLOB))

    def test_ts_wire_03_doctor_passes_from_the_installed_copy(self):
        runner = self.placed / "scripts" / mailscan.PROGRAM
        code, out = run_py(runner, "doctor", cwd=self.tmp, env=self.child_env(), isolated=True)
        self.assertEqual(code, 0, out)
        self.assertIn("doctor: ok", out)
        self.assertIn("import guard: %d files read, 0 findings" % 15, out)
        self.assertNotIn(str(self.home), out)
        self.assertNotIn("Traceback", out)
        # a state root of its own is outside the permission rules: a warning, exit 1
        code, out = run_py(runner, "doctor", "--root", self.tmp / "other-root", cwd=self.tmp, env=self.child_env(),
                           isolated=True)
        self.assertEqual(code, 1, out)
        self.assertIn("doctor: warn", out)
        self.assertIn("custom", out)

    def test_ts_wire_03_the_installed_copy_scans_and_checks_a_draft(self):
        runner = self.placed / "scripts" / mailscan.PROGRAM
        work = self.tmp / "work"
        work.mkdir()
        config = work / "config.json"
        config.write_text(json.dumps(samples.scan_config()), encoding="utf-8")
        message = Path(samples.scan_message_file(str(work), samples.scan_plain_message(), "one.eml"))
        root = self.tmp / "state"
        code, out = run_py(runner, "scan", "--config", config, "--root", root, message, cwd=self.tmp,
                           env=self.child_env(), isolated=True)
        self.assertIn(code, (0, 1), out)
        record = re.search(r"(?m)^record: (\S+)$", out).group(1)
        self.assertIn("reply: draft", out)
        self.assertTrue((root / "records" / (record + ".json")).is_file())
        self.assertTrue((root / "views" / (record + ".txt")).is_file())
        code, out = run_py(runner, "status", "--root", root, record, cwd=self.tmp, env=self.child_env(), isolated=True)
        self.assertEqual(code, 0, out)

    def test_ts_wire_03_the_codex_symlink_is_placed_under_the_throwaway_home(self):
        if os.name == "nt":
            self.skipTest("the Codex mirror is a symlink step; not run on Windows")
        if not BOOTSTRAP.is_file():
            self.skipTest("no bootstrap-environment.py beside this tree")
        self.assertFalse((SKILL / ".no-codex-symlink").exists())
        bootstrap = _load("mail_wiring_bootstrap", BOOTSTRAP)
        stub = samples.wiring_codex_stub(str(self.tmp))
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home),
               "PATH": stub + os.pathsep + os.environ.get("PATH", "")}
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            self.assertEqual(Path.home(), self.home)
            boot = bootstrap.Bootstrap(claude_home=self.claude, dry_run=False, force=False, install_args=[])
            boot.step_8_codex_symlinks()
        link = self.home / ".codex" / "skills" / "mail-scan"
        self.assertTrue(link.is_symlink(), buffer.getvalue())
        self.assertEqual(link.resolve(), self.placed.resolve())
        self.assertEqual(read(link / "SKILL.md"), read(SKILL / "SKILL.md"))
        self.assertTrue((self.home / ".codex" / "skills" / "intake-scan").is_symlink())
        self.assertEqual(boot.out.steps_failed, 0)


if __name__ == "__main__":
    unittest.main()
