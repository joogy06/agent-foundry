#!/usr/bin/env python3
"""mailscan.py -- the one command of mail-scan (#351).

    mailscan.py scan <file> --config <config.json> [--root <dir>]
    mailscan.py check-draft <record-id> --config <config.json> --body-file <file>
                            --subject-file <file> --reply-target-file <file> [--root <dir>]
    mailscan.py override <record-id> --kind block|list|budget|held --reason "<text>" [--root <dir>]
    mailscan.py status [<record-id>] [--root <dir>]
    mailscan.py purge [--root <dir>]
    mailscan.py calibrate <dir> --config <config.json> [--forged <file>]
    mailscan.py doctor [--root <dir>]

THE COMMAND WORD COMES FIRST. The first argument is one of the seven words above, written
in full; nothing may stand in front of it and no shorter spelling is accepted. That is what
lets a permission rule on the text `mailscan.py override` see every override: there is no
other command, flag or spelling that writes one. A flag is never accepted in a shortened
form either.

EXIT CODES. 0 pass, accept, done. 1 caution. 2 block, refuse, or a request the state
refuses. 3 a usage or environment error. For `scan` the code follows the verdict, and the
REPLY DECISION it prints, not the code, says whether a draft may be written. Any code
other than 0 or 1 means: no draft.

WHAT THIS COMMAND PRINTS. Words of a fixed vocabulary of ours (verdicts, reply decisions,
hold kinds, rule ids, gap names, classes, labels, fixed error words), numbers, record ids,
times of ours, and the two SHA-256 digests `check-draft` returns on accept. It never
prints a path, a file name, the value of an argument, the text of an error or a traceback,
and nothing taken from a message, a draft or a config: a reader of this output may be an
agent, and all of those are text somebody else chose. Every value that goes into a line
passes `_shown`, which lets through a number, an id of ours or a word of the vocabulary and
replaces anything else with a fixed word. `scan` prints no path: the view of a record is
`views/<record-id>.txt` under the state root the caller named.

A draft is never taken from the command line: the body, the subject and the reply target
are read from files (one of them may be `-` for standard input), so they are in no
process list and no shell history. From the subject and the reply target exactly one
trailing line break is dropped; the body is checked as it is.

Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import warnings
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import draft_check  # noqa: E402
import mail_lists  # noqa: E402
import mail_scan  # noqa: E402
import mail_sender  # noqa: E402
import mail_state  # noqa: E402

PROGRAM = "mailscan.py"
COMMAND_SCAN = "scan"
COMMAND_CHECK_DRAFT = "check-draft"
COMMAND_OVERRIDE = "override"
COMMAND_STATUS = "status"
COMMAND_PURGE = "purge"
COMMAND_CALIBRATE = "calibrate"
COMMAND_DOCTOR = "doctor"
COMMANDS = (COMMAND_SCAN, COMMAND_CHECK_DRAFT, COMMAND_OVERRIDE, COMMAND_STATUS, COMMAND_PURGE,
            COMMAND_CALIBRATE, COMMAND_DOCTOR)
HELP_FLAGS = ("-h", "--help")
STANDARD_INPUT = "-"

EXIT_PASS = mail_lists.EXIT_PASS
EXIT_CAUTION = mail_lists.EXIT_CAUTION
EXIT_BLOCK = mail_lists.EXIT_BLOCK
EXIT_USAGE = mail_lists.EXIT_USAGE

# What a draft file may weigh before it is read at all. The length caps of the draft are the
# check's; these only keep a wrong path from being loaded whole.
DRAFT_FILE_MAX_BYTES = 1_000_000
TARGET_FILE_MAX_BYTES = 4_096

WITHHELD = "(withheld)"
NONE = "none"
LABEL_MESSAGE = "message"
LABEL_CONFIG = "config"
LABEL_BODY = "body"
LABEL_SUBJECT = "subject"
LABEL_TARGET = "reply-target"
LABEL_DIRECTORY = "directory"
LABEL_FORGED = "forged"
LABELS = (LABEL_MESSAGE, LABEL_CONFIG, LABEL_BODY, LABEL_SUBJECT, LABEL_TARGET, LABEL_DIRECTORY, LABEL_FORGED)
ERROR_INTERNAL = "internal-error"
ERROR_INTERRUPTED = "interrupted"
ERROR_NOT_LOADED = "not-loaded"

# `os.open` under another name: it opens a descriptor, not a text file.
_open_fd = os.open

_RECORD_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_HEX = re.compile(r"[0-9a-f]{64}|[0-9a-f]{%d}" % mail_scan.CALIBRATE_HASH_CHARS)
_LINE = re.compile(r"[ -~]{0,400}")


def _vocabulary() -> frozenset:
    """Every word a value of an output line may be. All of them are ours."""
    words = set()
    for group in (
            mail_lists.VERDICTS, mail_lists.REPLIES, mail_lists.HOLD_KINDS, mail_lists.OVERRIDE_KINDS,
            mail_lists.DRAFT_RESULTS, mail_lists.RULE_CLASSES, tuple(mail_lists.RULES), mail_lists.GAP_NAMES,
            mail_lists.GAP_DETAILS, mail_lists.AMBIGUOUS_HEADER_NAMES, mail_lists.HEADER_REASONS,
            mail_lists.PARSE_BOUND_NAMES, mail_state.ERRORS, mail_state.MODE_LABELS,
            mail_sender.SENDER_STATUSES, mail_sender.SENDER_REASONS,
            mail_scan.CONFIG_CODES, mail_scan.CONFIG_KEY_WORDS, mail_scan.INPUT_CODES, mail_scan.SCAN_FAILURES,
            mail_scan.GUARD_KINDS, mail_scan.FORBIDDEN_MODULES, mail_scan.FORBIDDEN_MODULES_MORE,
            (mail_scan.URLLIB, mail_scan.OTHER_FILE_LABEL), mail_scan.DOCTOR_LEVELS, mail_scan.guard_labels(),
            COMMANDS, LABELS, (NONE, WITHHELD, ERROR_INTERNAL, ERROR_INTERRUPTED, ERROR_NOT_LOADED)):
        words.update(word for word in group if isinstance(word, str) and word)
    return frozenset(words)


VOCABULARY = _vocabulary()


def _shown(value: Any) -> Any:
    """`value` as it may stand in a line: a number, yes or no, an id or time of ours, a word of ours.

    Anything else becomes WITHHELD. This is the one gate between a value and the output.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return value
    if isinstance(value, str) and (value in VOCABULARY or _RECORD_ID.fullmatch(value)
                                   or _TIME.fullmatch(value) or _HEX.fullmatch(value)):
        return value
    return WITHHELD


def _listed(values: Sequence[Any]) -> str:
    return ", ".join(str(_shown(value)) for value in values) or NONE


class _Output:
    """The lines of one run. Nothing is written until the run is over, then all at once."""

    def __init__(self) -> None:
        self.lines: List[str] = []
        self.errors: List[str] = []

    @staticmethod
    def _line(template: str, values: Sequence[Any]) -> str:
        line = template % tuple(_shown(value) for value in values)
        return line if _LINE.fullmatch(line) else WITHHELD

    def say(self, template: str, *values: Any) -> None:
        self.lines.append(self._line(template, values))

    def error(self, template: str, *values: Any) -> None:
        self.errors.append(self._line("%s: " % PROGRAM + template, values))

    def text(self, text: str) -> None:
        """Help text of ours, line by line."""
        for line in text.splitlines():
            self.lines.append(line if _LINE.fullmatch(line) else WITHHELD)

    def reset(self) -> None:
        del self.lines[:]
        del self.errors[:]


def _silence(stream: Any) -> None:
    """Point a stream nobody reads any more at the null device, so nothing complains at exit."""
    try:
        descriptor = stream.fileno()
        null = _open_fd(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, descriptor)
        finally:
            os.close(null)
    except Exception:  # noqa: BLE001 - there is nobody left to tell
        pass


def _write(stream: Any, lines: Sequence[str]) -> None:
    if not lines:
        return
    try:
        stream.write("".join(line + "\n" for line in lines))
        stream.flush()
    except Exception:  # noqa: BLE001 - a closed pipe, a full disk: the exit code still stands
        _silence(stream)


# --------------------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------------------

class _Usage(Exception):
    """A command line this program does not accept. It carries no text."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        # argparse's own message repeats what was typed; this program repeats nothing.
        raise _Usage()

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:  # type: ignore[override]
        raise _Usage()


def build_parser(command: str) -> argparse.ArgumentParser:
    """The parser of the arguments that follow one command word. No flag may be shortened."""
    parser = _Parser(prog="%s %s" % (PROGRAM, command), add_help=False, allow_abbrev=False)
    root_help = "the state root (default: $%s, else ~/.foundry/mail-scan)" % mail_state.ENV_ROOT
    config_help = "the config file, mail-scan-config.v1"
    if command == COMMAND_SCAN:
        parser.description = "Scan one raw message: one verdict, one reply decision, one record."
        parser.add_argument("file", help="the raw message")
        parser.add_argument("--config", required=True, help=config_help)
        parser.add_argument("--root", default=None, help=root_help)
    elif command == COMMAND_CHECK_DRAFT:
        parser.description = ("Accept or refuse the draft written for a scanned message. The draft is read "
                              "from files, never from the command line; one of the three may be - for "
                              "standard input.")
        parser.add_argument("record", help="the record id scan printed")
        parser.add_argument("--config", required=True, help=config_help)
        parser.add_argument("--body-file", required=True, help="the body of the draft")
        parser.add_argument("--subject-file", required=True, help="its subject (one trailing line break is dropped)")
        parser.add_argument("--reply-target-file", required=True,
                            help="the address the reply would go to (one trailing line break is dropped)")
        parser.add_argument("--root", default=None, help=root_help)
    elif command == COMMAND_OVERRIDE:
        parser.description = ("A person lifts one hold of one scanned message. The line it writes is bound "
                              "to the digest of that message. The reason is kept as its length and digest.")
        parser.add_argument("record", help="the record id")
        parser.add_argument("--kind", required=True, choices=mail_lists.OVERRIDE_KINDS)
        parser.add_argument("--reason", required=True, help="why; the text itself is not stored")
        parser.add_argument("--root", default=None, help=root_help)
    elif command == COMMAND_STATUS:
        parser.description = ("With a record id: its verdict and reply decision after overrides. With none: "
                              "what the state root holds and whether purge is being run.")
        parser.add_argument("record", nargs="?", default=None, help="a record id")
        parser.add_argument("--root", default=None, help=root_help)
    elif command == COMMAND_PURGE:
        parser.description = ("Delete views and sheets older than %d days and records older than %d days."
                              % (mail_lists.PURGE_VIEW_DAYS, mail_lists.PURGE_RECORD_DAYS))
        parser.add_argument("--root", default=None, help=root_help)
    elif command == COMMAND_CALIBRATE:
        parser.description = ("Scan every .eml file directly inside a directory into a temporary state root "
                              "that is deleted afterwards, and print counts only.")
        parser.add_argument("directory", help="a directory of .eml files")
        parser.add_argument("--config", required=True, help=config_help)
        parser.add_argument("--forged", default=None,
                            help="a message you sent yourself from outside with a forged Authentication-Results header")
    elif command == COMMAND_DOCTOR:
        parser.description = ("Check this host: the parser behaviours, the reused pieces, the import guard, "
                              "the state root.")
        parser.add_argument("--root", default=None, help=root_help)
    else:
        raise _Usage()
    return parser


def _help_text() -> str:
    lines = ["usage: %s <command> ..." % PROGRAM, "", "commands (the command word comes first, written in full):"]
    lines.extend("  %s" % command for command in COMMANDS)
    lines.extend(["", "%s <command> --help shows the arguments of one command." % PROGRAM,
                  "exit codes: 0 pass or accept, 1 caution, 2 block or refuse, 3 usage or environment error"])
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Reading what a caller named
# --------------------------------------------------------------------------------------

class _Failed(Exception):
    """A command ends with a usage or environment error: one fixed word and one label of ours."""

    def __init__(self, code: str, label: str = "") -> None:
        Exception.__init__(self, code)
        self.code = code
        self.label = label


def _config(path: str) -> Dict[str, Any]:
    try:
        return mail_scan.load_config(path)
    except mail_scan.ConfigError as error:
        raise _Failed(error.code, error.key) from None


def _draft_text(name: str, label: str, limit: int, stdin: Any) -> str:
    """The text of one draft file (or of standard input), strict UTF-8."""
    try:
        if name == STANDARD_INPUT:
            data = stdin.read(limit + 1)
            if not isinstance(data, bytes):
                raise mail_scan.InputError(mail_scan.INPUT_UNREADABLE)
            if len(data) > limit:
                raise mail_scan.InputError(mail_scan.INPUT_TOO_LARGE)
        else:
            data = mail_scan.read_bounded(name, limit)
    except mail_scan.InputError as error:
        raise _Failed(error.code, label) from None
    except Exception:  # noqa: BLE001 - standard input that cannot be read
        raise _Failed(mail_scan.INPUT_UNREADABLE, label) from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _Failed(mail_scan.INPUT_NOT_UTF8, label) from None


def _one_line(text: str) -> str:
    """`text` without exactly one trailing line break (LF or CRLF)."""
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n"):
        return text[:-1]
    return text


# --------------------------------------------------------------------------------------
# The commands
# --------------------------------------------------------------------------------------

def _record_lines(out: _Output, record: Dict[str, Any]) -> None:
    out.say("rules: %d", len(record["rules"]))
    for row in record["rules"]:
        out.say("  %s %s x%d", row["class"], row["rule"], row["count"])
    out.say("gaps: %d", len(record["gaps"]))
    for row in record["gaps"]:
        if row["detail"]:
            out.say("  %s %s (%s) x%d", row["class"], row["gap"], row["detail"], row["count"])
        else:
            out.say("  %s %s x%d", row["class"], row["gap"], row["count"])


def cmd_scan(args: argparse.Namespace, out: _Output, stdin: Any) -> int:
    config = _config(args.config)
    try:
        result = mail_scan.scan_file(args.file, config, args.root)
    except mail_scan.InputError as error:
        raise _Failed(error.code, LABEL_MESSAGE) from None
    record = result.record
    if record is None:
        out.say("record: %s", NONE)
        out.say("verdict: %s", result.verdict)
        out.say("reply: %s", result.reply)
        out.say("failure: %s", result.failure)
        return mail_scan.exit_code(result)
    out.say("record: %s", record["id"])
    out.say("verdict: %s", record["verdict"])
    out.say("reply: %s", record["reply"])
    out.say("reply if released: %s", record["reply_if_released"])
    out.say("holds: %s", _listed(record["holds"]))
    out.say("effective verdict: %s", result.effective_verdict)
    out.say("effective reply: %s", result.effective_reply)
    _record_lines(out, record)
    if result.failure is not None:
        out.say("failure: %s", result.failure)
    return mail_scan.exit_code(result)


def cmd_check_draft(args: argparse.Namespace, out: _Output, stdin: Any) -> int:
    names = (args.body_file, args.subject_file, args.reply_target_file)
    if sum(1 for name in names if name == STANDARD_INPUT) > 1:
        raise _Usage()
    config = _config(args.config)
    body = _draft_text(args.body_file, LABEL_BODY, DRAFT_FILE_MAX_BYTES, stdin)
    subject = _one_line(_draft_text(args.subject_file, LABEL_SUBJECT, DRAFT_FILE_MAX_BYTES, stdin))
    target = _one_line(_draft_text(args.reply_target_file, LABEL_TARGET, TARGET_FILE_MAX_BYTES, stdin))
    result = mail_scan.check_draft(args.record, body, subject, target, config, args.root)
    shown = draft_check.recordable(result)
    out.say("result: %s", shown["result"])
    if result.result == mail_lists.DRAFT_ACCEPT:
        out.say("body sha256: %s", shown["body_sha256"])
        out.say("subject sha256: %s", shown["subject_sha256"])
    else:
        out.say("rules: %d", len(shown["rules"]))
        for row in shown["rules"]:
            out.say("  %s %s x%d", row["rule_class"], row["rule_id"], row["count"])
    return mail_scan.draft_exit_code(result)


def _effective_lines(out: _Output, effective: mail_state.Effective) -> None:
    out.say("verdict: %s", effective.verdict)
    out.say("reply: %s", effective.reply)
    out.say("holds: %s", _listed(effective.holds))
    out.say("lifted: %s", _listed(effective.lifted))


def cmd_override(args: argparse.Namespace, out: _Output, stdin: Any) -> int:
    try:
        entry = mail_state.add_override(args.record, args.kind, args.reason, args.root)
    except mail_state.StateError as error:
        if error.code in mail_state.OVERRIDE_REFUSALS:
            out.say("refused: %s", error.code)
            return EXIT_BLOCK
        raise _Failed(error.code) from None
    out.say("override: recorded")
    out.say("record: %s", entry.record)
    out.say("kind: %s", entry.kind)
    try:
        _effective_lines(out, mail_state.effective_record(entry.record, args.root))
    except mail_state.StateError as error:
        out.say("status: %s", error.code)
    return EXIT_PASS


_STATUS_REFUSALS = (mail_state.ERROR_ID, mail_state.ERROR_RECORD_UNKNOWN, mail_state.ERROR_RECORD_UNREADABLE)


def cmd_status(args: argparse.Namespace, out: _Output, stdin: Any) -> int:
    root = args.root
    if args.record is not None:
        try:
            record = mail_state.load_record(args.record, root)
            effective = mail_state.effective_of(record, mail_state.read_overrides(root).entries)
        except mail_state.StateError as error:
            if error.code in _STATUS_REFUSALS:
                out.say("refused: %s", error.code)
                return EXIT_BLOCK
            raise _Failed(error.code) from None
        out.say("record: %s", record["id"])
        _effective_lines(out, effective)
        out.say("recorded verdict: %s", effective.record_verdict)
        out.say("recorded reply: %s", effective.record_reply)
        out.say("reply if released: %s", record["reply_if_released"])
        _record_lines(out, record)
        return EXIT_PASS
    try:
        report = mail_state.retention_report(root)
        unreadable = 0
        for record_id in mail_state.record_ids(root):
            try:
                mail_state.load_record(record_id, root)
            except mail_state.StateError:
                unreadable += 1
        log = mail_state.read_overrides(root)
    except mail_state.StateError as error:
        raise _Failed(error.code) from None
    out.say("records: %d", report.records)
    out.say("records unreadable: %d", unreadable)
    out.say("views: %d", report.views)
    out.say("sheets: %d", report.sheets)
    if report.oldest_view_age is None:
        out.say("oldest view: %s", NONE)
    else:
        out.say("oldest view: %d days", report.oldest_view_age // mail_state.DAY_SECONDS)
    out.say("last purge: %s", report.last_purge or NONE)
    out.say("overrides: %d", len(log.entries))
    out.say("override lines ignored: %d", log.ignored)
    out.say(mail_state.RETENTION_RUNNING if report.running else mail_state.RETENTION_NOT_RUNNING)
    return EXIT_PASS if report.running and not unreadable and not log.ignored else EXIT_CAUTION


def cmd_purge(args: argparse.Namespace, out: _Output, stdin: Any) -> int:
    try:
        result = mail_state.purge(args.root)
    except mail_state.StateError as error:
        raise _Failed(error.code) from None
    except OSError:
        raise _Failed(mail_state.ERROR_ROOT) from None
    out.say("purged: views %d, sheets %d, records %d, temporary files %d",
            result.views, result.sheets, result.records, result.temporary)
    out.say("last purge: %s", result.time)
    return EXIT_PASS


def _pairs(out: _Output, title: str, table: Dict[str, Tuple[int, int]], order: Sequence[str],
           classes: Optional[Callable[[str], str]], unit: str) -> None:
    out.say(title + ": %d", len(table))
    for name in order:
        if name not in table:
            continue
        messages, total = table[name]
        if classes is None:
            out.say("  %s: messages %d, " + unit + " %d", name, messages, total)
        else:
            out.say("  %s %s: messages %d, " + unit + " %d", classes(name), name, messages, total)


def cmd_calibrate(args: argparse.Namespace, out: _Output, stdin: Any) -> int:
    config = _config(args.config)
    try:
        report = mail_scan.calibrate(args.directory, config, args.forged)
    except mail_scan.InputError as error:
        # which of the two could not be read is not said: the directory is read first
        raise _Failed(error.code, LABEL_DIRECTORY if args.forged is None else "") from None
    out.say("calibrate: scanned %d, unreadable %d, not read %d, over the limit %d, scanner errors %d",
            report.scanned, report.unreadable, report.not_read, report.over_limit, report.failures)
    out.say("verdicts: " + ", ".join("%s %%d" % word for word in mail_lists.VERDICTS),
            *[report.verdicts.get(word, 0) for word in mail_lists.VERDICTS])
    out.say("replies: " + ", ".join("%s %%d" % word for word in mail_lists.REPLIES),
            *[report.replies.get(word, 0) for word in mail_lists.REPLIES])
    _pairs(out, "rules", report.rules, tuple(mail_lists.RULES), lambda name: mail_lists.RULES[name].rule_class, "hits")
    _pairs(out, "gaps", report.gaps, mail_lists.GAP_NAMES, lambda name: mail_lists.GAPS[name].gap_class, "count")
    _pairs(out, "header-ambiguous", report.header_ambiguous, mail_lists.AMBIGUOUS_HEADER_NAMES, None, "count")
    out.say("sender: %d", len(report.senders))
    for status in mail_sender.SENDER_STATUSES:
        for reason in mail_sender.SENDER_REASONS:
            if (status, reason) in report.senders:
                out.say("  %s %s: messages %d", status, reason, report.senders[(status, reason)])
    out.say("authentication headers: none in %d messages, unreadable %d", report.no_header,
            report.unreadable_headers)
    out.say("profile: present" if report.profile else "profile: absent")
    for title, table in (("authserv-id of the first header", report.first_ids),
                         ("authserv-id of later headers", report.later_ids)):
        out.say(title + ", by keyed hash: %d", len(table))
        for value in sorted(table, key=lambda item: (-table[item], item)):
            if value == report.profile_hash:
                out.say("  %s: messages %d (the profile)", value, table[value])
            else:
                out.say("  %s: messages %d", value, table[value])
    forged = report.forged
    if forged is not None:
        out.say("forged message: authentication headers %d, under the profile id %d", forged.headers,
                forged.profile_headers)
        out.say("forged message: first header under the profile id: %s", forged.first_is_profile)
        out.say("forged message: sender %s %s", forged.sender_status, forged.sender_reason)
    out.say("note: each message was judged alone; the reply budget was not counted")
    out.say("note: the hashes are keyed with a key that is already deleted; they compare within this run only")
    return EXIT_PASS


def cmd_doctor(args: argparse.Namespace, out: _Output, stdin: Any) -> int:
    report = mail_scan.doctor(args.root)
    out.say("python: %d.%d.%d (the parser behaviours were recorded on %d.%d)",
            *(report.python + mail_scan.PINNED_PYTHON))
    out.say("parser behaviours: %d of %d hold", report.pins_held, report.pins)
    out.say("reused pieces of intake-scan: ok" if report.reuse else "reused pieces of intake-scan: missing")
    if report.catalog_checks:
        out.say("secrets catalog: ok, %d checks", report.catalog_checks)
    else:
        out.say("secrets catalog: missing (every scan is a block and every draft is refused)")
    out.say("schemas: ok" if report.schemas else "schemas: unreadable")
    out.say("import guard: %d files read, %d findings", report.guard_files, len(report.guard))
    for finding in report.guard:
        label = finding.file if finding.file in VOCABULARY else mail_scan.OTHER_FILE_LABEL
        out.say("  %s: %s %s", label, finding.kind, finding.name or NONE)
    out.say("import guard: outside it by design: the secrets catalog file of the skill secret-scanning")
    if report.custom_root:
        out.say("state root: custom")
        out.say("warning: the permission rules of the settings template cover the default state root only; "
                "an override and a view under a custom root are not gated by them")
    else:
        out.say("state root: default")
    out.say("state root modes: %d not as they should be", len(report.modes))
    for label, mode in report.modes:
        out.say("  %s: %04o", label, mode)
    out.say("override lines ignored: %d", report.overrides_ignored)
    out.say("top-level domains: snapshot of %d days ago", max(0, report.tlds_age_days))
    if report.tlds_stale:
        out.say("warning: the snapshot of top-level domains the draft check reads is over a year old; "
                "a host under a newer name is not found")
    out.say("doctor: %s", report.level)
    return mail_scan.doctor_exit_code(report)


_COMMANDS: Dict[str, Callable[[argparse.Namespace, _Output, Any], int]] = {
    COMMAND_SCAN: cmd_scan, COMMAND_CHECK_DRAFT: cmd_check_draft, COMMAND_OVERRIDE: cmd_override,
    COMMAND_STATUS: cmd_status, COMMAND_PURGE: cmd_purge, COMMAND_CALIBRATE: cmd_calibrate,
    COMMAND_DOCTOR: cmd_doctor,
}
# A failure nobody foresaw, after a message or a draft may have been read: no draft.
_INTERNAL_EXITS = {COMMAND_SCAN: EXIT_BLOCK, COMMAND_CHECK_DRAFT: EXIT_BLOCK}


def _run(argv: List[str], out: _Output, stdin: Any) -> int:
    if not argv:
        raise _Usage()
    if argv[0] in HELP_FLAGS and len(argv) == 1:
        out.text(_help_text())
        return EXIT_PASS
    command = argv[0]
    if command not in COMMANDS:         # the command word comes first, in full, or nothing runs
        raise _Usage()
    rest = argv[1:]
    parser = build_parser(command)
    if any(item in HELP_FLAGS for item in rest):
        out.text(parser.format_help())
        return EXIT_PASS
    args = parser.parse_args(rest)
    try:
        return _COMMANDS[command](args, out, stdin)
    except (_Usage, _Failed, KeyboardInterrupt):
        raise
    except Exception:  # noqa: BLE001 - never a traceback: it may hold text somebody else chose
        out.reset()
        out.error("error: %s", ERROR_INTERNAL)
        return _INTERNAL_EXITS.get(command, EXIT_USAGE)


def main(argv: Optional[Sequence[str]] = None, stdin: Any = None) -> int:
    """Run one command. Returns the exit code; writes to sys.stdout and sys.stderr, once, at the end."""
    out = _Output()
    code = EXIT_USAGE
    words: List[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            words = [word for word in (sys.argv[1:] if argv is None else argv)]
            if stdin is None:
                stdin = getattr(sys.stdin, "buffer", sys.stdin)
            code = _run(words, out, stdin)
    except _Usage:
        out.reset()
        out.error("usage error: the command line was not understood")
        out.error("run %s --help for the commands", PROGRAM)
        code = EXIT_USAGE
    except _Failed as failed:
        out.reset()
        if failed.label:
            out.error("error: %s (%s)", failed.code, failed.label)
        else:
            out.error("error: %s", failed.code)
        code = EXIT_USAGE
    except KeyboardInterrupt:
        out.reset()
        out.error("error: %s", ERROR_INTERRUPTED)
        code = EXIT_USAGE
    except BaseException:  # noqa: BLE001 - SystemExit from a library, or anything else: fixed words only
        out.reset()
        out.error("error: %s", ERROR_INTERNAL)
        code = _INTERNAL_EXITS.get(words[0] if words and isinstance(words[0], str) else "", EXIT_USAGE)
    _write(sys.stdout, out.lines)
    _write(sys.stderr, out.errors)
    return code


def _entry() -> int:
    """`main` for a process: whatever happens, fixed words or nothing, and a code."""
    sys.unraisablehook = lambda _unraisable: None
    try:
        code = main()
    except BaseException:  # noqa: BLE001 - an interrupt while the lines were being written
        code = EXIT_USAGE
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 - see _silence
            _silence(stream)
    return code


if __name__ == "__main__":
    sys.exit(_entry())
