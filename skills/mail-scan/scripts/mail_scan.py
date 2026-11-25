#!/usr/bin/env python3
"""mail_scan.py -- the library entry point of mail-scan: scan, check a draft, calibrate, doctor (#351).

THE THREE CALLS A MAIL SERVICE MAKES.

    scan_bytes(raw, config, state_root=None)    one raw message -> one verdict and one reply
                                                decision, stored as a `mail-verdict.v1` record
    check_draft(record_id, body, subject, reply_target, config, state_root=None)
                                                accept or refuse the draft written for it
    effective(digest, state_root=None)          the verdict and reply after a person's overrides

`scan_bytes` returns a `ScanResult`: the record, the path of the framed view (the only form
of the message a model may be given), the path of the sheet a person reads, and the reply
target. The reply target is an address: it is returned IN MEMORY, only when a draft may be
written, and is never stored or printed. The result also carries the EFFECTIVE verdict and
reply: the recorded decision after the overrides a person gave for this raw digest. The
effective reply, never an exit code or a verdict, says whether a draft may be written. A
record keeps the decision as it was made; nothing about an override is stored in it.

ONE HANDLER FOR EVERY FAILURE. A scan runs parse -> view -> sender hash and budget query
-> rules -> store. An exception in any of them does not leave this module: the message
gets a block record with the gap `scanner-error`, whose reply stays held even after an
override, because nobody read the message. When not even that record can be written (the
state root cannot be written, or intake-scan and with it the schema interpreter is not
there, or the root holds records and its key is gone: `key-missing`, never a new key made
in silence) the result carries no record and says so with a fixed word; it is still a block.
No text of an exception is kept, returned or printed anywhere: it may hold text of the
message.

THE CONFIG is `mail-scan-config.v1`: `read_config` takes a dict and `load_config` a JSON
file. Both check the whole form in code (the bounds the schema subset cannot state as
well), then against the schema where the interpreter is available, and last through the
two readers that will read it (the rules and the draft check), so a config they accept
cannot fail later. A refusal is a `ConfigError` whose text is a fixed word and whose `key`
names a key of ours; no value of the config is ever in it.

THE BUDGET (JC-9). `mail_state` counts the earlier messages of the sender that REALLY were
open to a draft in the seven days before this one (not blocked, reply `draft` as recorded
or after an override, whatever the sender result), other than this very message; `mail_rules`
holds the reply at three. This module only carries the number from one to the other.

CALIBRATE scans every regular `.eml` file directly inside one directory (no folder below
it, no symbolic link) into a TEMPORARY state root that is deleted before it returns, and
gives back counts: nothing of a message. The authserv-id values it saw are counted under a
keyed hash whose key is thrown away with that root.

DOCTOR looks at this host: the parser behaviours the rules were written against (a small
set of messages built in memory, with the parse each must give), the reused symbols, the
secrets catalog, the two schemas, the import guard, and the modes of the state root.

THE IMPORT GUARD (`import_guard`) reads, as syntax trees, every script of this skill and
every intake-scan module `mail_reuse` loads, and reports an import of a network, mail
transport or process module, of `urllib` other than `urllib.parse`, and any use of
`os.system`, `os.popen`, `os.exec*`, `os.spawn*` or `os.fork`. It is static: a name put
together at run time is not seen. ONE FILE IS OUTSIDE IT BY DESIGN: the secrets catalog
of the skill `secret-scanning` (GUARD_OUT_OF_SCOPE). It is another skill's file, which
`load_checks` of intake-scan runs to read its table, and it imports `subprocess` inside a
function that mail-scan never calls.

Stdlib only. Importing this module has no side effects beyond loading its siblings.
"""
from __future__ import annotations

import ast
import datetime
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import draft_check  # noqa: E402
import mail_lists  # noqa: E402
import mail_parse  # noqa: E402
import mail_reuse  # noqa: E402
import mail_rules  # noqa: E402
import mail_sender  # noqa: E402
import mail_state  # noqa: E402
import mail_view  # noqa: E402

# `os.open` under another name: it opens a descriptor, not a text file.
_open_fd = os.open

EXIT_PASS = mail_lists.EXIT_PASS
EXIT_CAUTION = mail_lists.EXIT_CAUTION
EXIT_BLOCK = mail_lists.EXIT_BLOCK
EXIT_USAGE = mail_lists.EXIT_USAGE

# --------------------------------------------------------------------------------------
# The config
# --------------------------------------------------------------------------------------

CONFIG_SCHEMA_ID = "mail-scan-config.v1"
CONFIG_SCHEMA_PATH = os.path.join(os.path.dirname(SCRIPTS_DIR), "schemas", "mail-scan-config.v1.json")
CONFIG_KEYS = ("schema", "own_addresses", "provider_profile", "allowed_hosts", "approved_phones",
               "reply_to_map", "knowledge_pack", "canary", "max_bytes")
PROFILE_KEYS = ("authserv_id", "validated_on")

# Bounds the schema subset cannot state. They are checked here.
MAX_BYTES_LIMIT = 25_000_000            # the largest `max_bytes` a config may ask for
CONFIG_MAX_FILE_BYTES = 1_000_000
CONFIG_MAX_ENTRIES = 1_000              # entries of one list or of the reply map
ADDRESS_MAX_CHARS = 320
HOST_MAX_CHARS = 253
PHONE_MAX_CHARS = 40
AUTHSERV_ID_MAX_CHARS = 255
PACK_PATH_MAX_CHARS = 4_096
CANARY_MAX_CHARS = 200

# The fixed words of a refused config. `ConfigError.key` is a key of ours or one of these.
CONFIG_UNREADABLE = "config-unreadable"     # no such file, not a regular file, too large
CONFIG_NOT_JSON = "config-not-json"         # not UTF-8, not one JSON document, a repeated key
CONFIG_INVALID = "config-invalid"           # JSON of another form than mail-scan-config.v1
CONFIG_CODES = (CONFIG_UNREADABLE, CONFIG_NOT_JSON, CONFIG_INVALID)
KEY_FORM = "form"                           # the config as a whole
KEY_UNKNOWN = "unknown-key"                 # a key the schema does not list
CONFIG_KEY_WORDS = CONFIG_KEYS + (KEY_FORM, KEY_UNKNOWN)

_ADDRESS = re.compile(r"[^\s<>()\[\]\\,;:\"@\x00-\x1f\x7f]+@[^\s<>()\[\]\\,;:\"@\x00-\x1f\x7f]+")
_HOST = re.compile(r"[^\s/?#@:\\<>\"'|\x00-\x1f\x7f]+")
_PHONE = re.compile(r"[0-9+ .\-()]+")
_AUTHSERV_ID = re.compile(r"[A-Za-z0-9._\-]+")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class ConfigError(ValueError):
    """A config mail-scan does not read. `code` is a word of CONFIG_CODES, `key` of CONFIG_KEY_WORDS."""

    def __init__(self, code: str, key: str = "") -> None:
        ValueError.__init__(self, code)
        self.code = code
        self.key = key


_CONFIG_SCHEMA_CACHE: List[Dict[str, Any]] = []


def config_schema() -> Optional[Dict[str, Any]]:
    """mail-scan-config.v1 as a dict; None when the file cannot be read (doctor reports that)."""
    if not _CONFIG_SCHEMA_CACHE:
        try:
            with open(CONFIG_SCHEMA_PATH, "r", encoding="utf-8") as handle:
                schema = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(schema, dict) or schema.get("$id") != CONFIG_SCHEMA_ID:
            return None
        _CONFIG_SCHEMA_CACHE.append(schema)
    return _CONFIG_SCHEMA_CACHE[0]


def _text(value: Any, pattern: "re.Pattern[str]", limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit and pattern.fullmatch(value) is not None


def _entries(config: Mapping[str, Any], key: str) -> List[Any]:
    value = config.get(key, [])
    if not isinstance(value, (list, tuple)) or len(value) > CONFIG_MAX_ENTRIES:
        raise ConfigError(CONFIG_INVALID, key)
    return list(value)


def _is_host(value: Any) -> bool:
    if not _text(value, _HOST, HOST_MAX_CHARS):
        return False
    labels = value.rstrip(".").split(".")
    return len(labels) >= 2 and all(labels)


def _is_date(value: Any) -> bool:
    if not _text(value, _DATE, 10):
        return False
    try:
        datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return False
    return True


def read_config(config: Any) -> Dict[str, Any]:
    """`config` checked, as a new plain dict with `max_bytes` filled in. Raises ConfigError.

    The dict is what `mail_rules.decide` and `draft_check.check` read; neither can refuse a
    config this function returned.
    """
    if not isinstance(config, Mapping):
        raise ConfigError(CONFIG_INVALID, KEY_FORM)
    if any(not isinstance(key, str) or key not in CONFIG_KEYS for key in config):
        raise ConfigError(CONFIG_INVALID, KEY_UNKNOWN)
    if "schema" in config and config["schema"] != CONFIG_SCHEMA_ID:
        raise ConfigError(CONFIG_INVALID, "schema")
    if "own_addresses" not in config:
        raise ConfigError(CONFIG_INVALID, "own_addresses")
    out: Dict[str, Any] = {}
    for key, check in (("own_addresses", lambda item: _text(item, _ADDRESS, ADDRESS_MAX_CHARS)),
                       ("allowed_hosts", _is_host),
                       ("approved_phones", lambda item: _text(item, _PHONE, PHONE_MAX_CHARS)
                        and any("0" <= char <= "9" for char in item))):
        entries = _entries(config, key)
        if not all(check(item) for item in entries):
            raise ConfigError(CONFIG_INVALID, key)
        out[key] = entries
    mapping = config.get("reply_to_map", {})
    if not isinstance(mapping, Mapping) or len(mapping) > CONFIG_MAX_ENTRIES or not all(
            _text(key, _ADDRESS, ADDRESS_MAX_CHARS) and _text(value, _ADDRESS, ADDRESS_MAX_CHARS)
            for key, value in mapping.items()):
        raise ConfigError(CONFIG_INVALID, "reply_to_map")
    out["reply_to_map"] = dict(mapping)
    if "provider_profile" in config:
        profile = config["provider_profile"]
        if (not isinstance(profile, Mapping) or any(key not in PROFILE_KEYS for key in profile)
                or not _text(profile.get("authserv_id"), _AUTHSERV_ID, AUTHSERV_ID_MAX_CHARS)
                or ("validated_on" in profile and not _is_date(profile["validated_on"]))):
            raise ConfigError(CONFIG_INVALID, "provider_profile")
        out["provider_profile"] = dict(profile)
    if "knowledge_pack" in config:
        pack = config["knowledge_pack"]
        if not isinstance(pack, str) or not 0 < len(pack) <= PACK_PATH_MAX_CHARS or "\x00" in pack:
            raise ConfigError(CONFIG_INVALID, "knowledge_pack")
        out["knowledge_pack"] = pack
    if "canary" in config:
        canary = config["canary"]
        if not isinstance(canary, str) or not canary.strip() or len(canary) > CANARY_MAX_CHARS:
            raise ConfigError(CONFIG_INVALID, "canary")
        out["canary"] = canary
    limit = config.get("max_bytes", mail_lists.MAX_BYTES_DEFAULT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BYTES_LIMIT:
        raise ConfigError(CONFIG_INVALID, "max_bytes")
    out["max_bytes"] = limit
    # The schema, where the interpreter is there to read it: it and the code must agree.
    schema = config_schema()
    if mail_reuse.validate_record is not None and schema is not None:
        try:
            errors = mail_reuse.validate_record(out, schema)
        except Exception:  # noqa: BLE001 - an interpreter that fails on it has not accepted it
            errors = [KEY_FORM]
        if errors:
            raise ConfigError(CONFIG_INVALID, KEY_FORM)
    # Last, the two readers that will read it. What they accept here they accept in a scan.
    for reader in (getattr(mail_rules, "_read_config", None), getattr(draft_check, "_settings", None)):
        if reader is None:
            continue
        try:
            reader(out)
        except Exception:  # noqa: BLE001 - whatever a reader says, the text stays there
            raise ConfigError(CONFIG_INVALID, KEY_FORM) from None
    return out


def _no_repeated_key(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("repeated key")
        out[key] = value
    return out


def _no_constant(_name: str) -> Any:
    raise ValueError("not a number of JSON")


def load_config(path: Any) -> Dict[str, Any]:
    """The config file at `path`, read and checked. Raises ConfigError; never echoes the file."""
    try:
        data = read_bounded(path, CONFIG_MAX_FILE_BYTES)
    except InputError:
        raise ConfigError(CONFIG_UNREADABLE, KEY_FORM) from None
    try:
        config = json.loads(data.decode("utf-8"), object_pairs_hook=_no_repeated_key,
                            parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise ConfigError(CONFIG_NOT_JSON, KEY_FORM) from None
    return read_config(config)


# --------------------------------------------------------------------------------------
# Reading a file a caller named
# --------------------------------------------------------------------------------------

INPUT_UNREADABLE = "input-unreadable"       # no such file, not a regular file, cannot be read
INPUT_TOO_LARGE = "input-too-large"
INPUT_NOT_UTF8 = "input-not-utf-8"
INPUT_NOT_BYTES = "input-not-bytes"         # scan_bytes was given something that is not bytes
INPUT_CODES = (INPUT_UNREADABLE, INPUT_TOO_LARGE, INPUT_NOT_UTF8, INPUT_NOT_BYTES)
_CHUNK = 1 << 20


class InputError(Exception):
    """What a caller named cannot be read. `code` is a word of INPUT_CODES; there is no other text."""

    def __init__(self, code: str) -> None:
        Exception.__init__(self, code)
        self.code = code


def _open_regular(path: Any) -> int:
    """A descriptor on the regular file at `path`. A folder, a pipe or a device is refused unread."""
    try:
        name = os.fspath(path)
        if not isinstance(name, (str, bytes)) or not name:
            raise InputError(INPUT_UNREADABLE)
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
        fd = _open_fd(name, flags)
    except (OSError, ValueError, TypeError):
        raise InputError(INPUT_UNREADABLE) from None
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:
        os.close(fd)
        raise InputError(INPUT_UNREADABLE)
    return fd


def read_bounded(path: Any, limit: int) -> bytes:
    """The bytes of the regular file at `path`; InputError when it is not one or is over `limit`."""
    fd = _open_regular(path)
    try:
        chunks = []
        size = 0
        while True:
            chunk = os.read(fd, min(_CHUNK, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise InputError(INPUT_TOO_LARGE)
        return b"".join(chunks)
    except OSError:
        raise InputError(INPUT_UNREADABLE) from None
    finally:
        os.close(fd)


def read_message(path: Any, max_bytes: int) -> Tuple[bytes, str]:
    """(the first `max_bytes` + 1 bytes of the message file, the SHA-256 of ALL of it).

    A message over the bound is not kept in memory, but its digest is that of the whole
    file: the record of an oversize message names the same bytes a later scan would.
    """
    fd = _open_regular(path)
    try:
        digest = hashlib.sha256()
        kept: List[bytes] = []
        size = 0
        while True:
            chunk = os.read(fd, _CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            if size <= max_bytes:
                kept.append(chunk[:max_bytes + 1 - size])
            size += len(chunk)
        return b"".join(kept), digest.hexdigest()
    except OSError:
        raise InputError(INPUT_UNREADABLE) from None
    finally:
        os.close(fd)


# --------------------------------------------------------------------------------------
# Scan
# --------------------------------------------------------------------------------------

FAILURE_SCANNER_ERROR = "scanner-error"         # a stage failed; the message has a block record
FAILURE_NO_RECORD = "record-not-written"        # and not even that record could be written
FAILURE_KEY_MISSING = "key-missing"             # the same, because the root holds records and its key is gone
SCAN_FAILURES = (FAILURE_SCANNER_ERROR, FAILURE_NO_RECORD, FAILURE_KEY_MISSING)


class ScanResult(NamedTuple):
    record: Optional[Dict[str, Any]]    # the stored record; None only for FAILURE_NO_RECORD
    view_path: Optional[str]            # the framed view; None when none was stored
    sheet_path: Optional[str]
    reply_target: Optional[str]         # MEMORY ONLY: where a reply would go, and only when the effective
                                        # reply is `draft` (None otherwise); never store or print it
    failure: Optional[str]              # None, or a word of SCAN_FAILURES
    effective_verdict: Optional[str] = None     # the verdict after the overrides given for this raw digest
    effective_reply: Optional[str] = None       # the reply likewise: DRAFT ONLY WHEN THIS IS `draft`

    @property
    def verdict(self) -> str:
        return mail_lists.VERDICT_BLOCK if self.record is None else self.record["verdict"]

    @property
    def reply(self) -> str:
        """The reply decision AS RECORDED, before overrides. `effective_reply` is the one to act on."""
        return mail_lists.REPLY_HELD if self.record is None else self.record["reply"]

    @property
    def record_id(self) -> Optional[str]:
        return None if self.record is None else self.record["id"]


_VERDICT_EXITS = {mail_lists.VERDICT_PASS: EXIT_PASS, mail_lists.VERDICT_CAUTION: EXIT_CAUTION,
                  mail_lists.VERDICT_BLOCK: EXIT_BLOCK}


def exit_code(result: ScanResult) -> int:
    """0 pass, 1 caution, 2 block, by the EFFECTIVE verdict. A result with no record is a block."""
    if result.record is None:
        return EXIT_BLOCK
    return _VERDICT_EXITS.get(result.effective_verdict or result.verdict, EXIT_BLOCK)


def _effective_pair(record: Mapping[str, Any], root: Any) -> Tuple[str, str]:
    """(verdict, reply) of a stored record after the overrides given for its raw digest.

    Nothing of it is stored: the record keeps the decision as it was made. When the override
    log cannot be read the recorded pair stands, which is never the more permissive one.
    """
    try:
        found = mail_state.effective_of(record, mail_state.read_overrides(root).entries)
        return found.verdict, found.reply
    except Exception:  # noqa: BLE001 - an unreadable log lifts nothing
        return record["verdict"], record["reply"]


class _Detail(NamedTuple):
    result: ScanResult
    parsed: Any         # None when the parse stage was not reached or failed
    decision: Any       # None likewise


def _drop_orphans(record: Mapping[str, Any], root: Any) -> None:
    """Remove the view and the sheet of a record that was never written: a view with no verdict."""
    try:
        record_id = record["id"]
        if os.path.lexists(mail_state.record_path(record_id, root)):
            return
        for path in (mail_state.view_path(record_id, root), mail_state.sheet_path(record_id, root)):
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception:  # noqa: BLE001 - tidying up must not turn one failure into another
        pass


def _scan(raw: bytes, digest: str, settings: Mapping[str, Any], root: Any, now: Any,
          catalog: Optional[mail_reuse.Catalog] = None, budget: bool = True) -> _Detail:
    """The one handler. Every stage runs inside it and nothing a stage raises leaves it."""
    parsed = decision = record = None
    try:
        if catalog is None:
            catalog = mail_reuse.catalog_checks()
        extra = (mail_reuse.GAP_CATALOG_MISSING,) if catalog.gap is not None else ()
        bounds = mail_parse.DEFAULT_BOUNDS._replace(max_bytes=settings["max_bytes"])
        # one wall-clock budget for the parse, the view and the rules of this message
        clock = mail_reuse.Budget(bounds.max_seconds)
        parsed = mail_parse.parse(raw, bounds, clock)
        view = mail_view.build(parsed, catalog.checks, clock)
        sender = mail_state.sender_hash(parsed.headers.from_address, root)
        earlier = mail_state.earlier_drafts(sender, digest, root, now) if budget else 0
        decision = mail_rules.decide(parsed, view, settings, earlier, extra, clock)
        record = mail_state.build_record(digest, parsed, view, decision, sender, root, now)
        stored = mail_state.store(record, view.framed, root)
        verdict, reply = _effective_pair(record, root)
        target = decision.reply_target if reply == mail_lists.REPLY_DRAFT else None
        return _Detail(ScanResult(record, stored.view_path, stored.sheet_path, target, None, verdict, reply),
                       parsed, decision)
    except Exception:  # noqa: BLE001 - the text of the exception may be text of the message
        pass
    if record is not None:
        _drop_orphans(record, root)
    try:
        record = mail_state.build_record(digest, None, None, mail_rules.error_decision(), None, root, now)
        stored = mail_state.store(record, None, root)
        verdict, reply = _effective_pair(record, root)
        return _Detail(ScanResult(record, None, stored.sheet_path, None, FAILURE_SCANNER_ERROR, verdict, reply),
                       parsed, None)
    except Exception:  # noqa: BLE001 - no record can be written: still a block, with no record
        failure = FAILURE_KEY_MISSING if mail_state.key_missing(root) else FAILURE_NO_RECORD
        return _Detail(ScanResult(None, None, None, None, failure, mail_lists.VERDICT_BLOCK,
                                  mail_lists.REPLY_HELD), parsed, None)


def scan_bytes(raw: Any, config: Any, state_root: Any = None, now: Any = None) -> ScanResult:
    """Scan one raw message and store its record, its view and its sheet.

        raw          the message as bytes
        config       a dict in the form of mail-scan-config.v1
        state_root   the state root; None: $FOUNDRY_MAILSCAN_ROOT, else ~/.foundry/mail-scan
        now          seconds since the epoch; None: the clock

    Raises ConfigError for a config of the wrong form and InputError when `raw` is not
    bytes, both BEFORE anything is read or written. After that it never raises: every
    failure is a block (see ONE HANDLER in the module text).
    """
    settings = read_config(config)
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise InputError(INPUT_NOT_BYTES)
    raw = bytes(raw)
    return _scan(raw, mail_state.raw_digest(raw), settings, state_root, now).result


def scan_file(path: Any, config: Any, state_root: Any = None, now: Any = None) -> ScanResult:
    """`scan_bytes` for a message in a file. InputError when the file cannot be read.

    A file over `max_bytes` is not loaded whole; its record is the block `structure-over-bound`
    under the digest of the whole file.
    """
    settings = read_config(config)
    raw, digest = read_message(path, settings["max_bytes"])
    return _scan(raw, digest, settings, state_root, now).result


# --------------------------------------------------------------------------------------
# Draft check and the effective verdict
# --------------------------------------------------------------------------------------

def check_draft(record_id: Any, body: Any, subject: Any, reply_target: Any, config: Any,
                state_root: Any = None) -> draft_check.DraftResult:
    """Accept or refuse the draft written for the message stored under `record_id`.

    On accept the result carries the SHA-256 of the body and of the subject as given: place
    exactly those. Raises ConfigError for a config of the wrong form and ValueError (a fixed
    text) for a body or subject that is not text. Any other failure is a refusal with no
    rule: a draft that could not be checked is not accepted. Nothing is written.
    """
    settings = read_config(config)
    if not isinstance(body, str) or not isinstance(subject, str):
        raise ValueError(draft_check.INPUT_ERROR)
    try:
        return draft_check.check(record_id, body, subject, reply_target, settings, state_root,
                                 mail_reuse.catalog_checks())
    except Exception:  # noqa: BLE001 - the text of the exception may be text of the draft
        return draft_check.DraftResult(mail_lists.DRAFT_REFUSE, (), None, None)


def draft_exit_code(result: draft_check.DraftResult) -> int:
    return EXIT_PASS if result.result == mail_lists.DRAFT_ACCEPT else EXIT_BLOCK


def effective(digest: Any, state_root: Any = None) -> Optional[mail_state.Effective]:
    """The verdict and reply, after overrides, of the newest record of the message with this raw digest.

    None for a digest no record carries. An override counts only for the digest it names.
    """
    return mail_state.effective(digest, state_root)


def effective_record(record_id: Any, state_root: Any = None) -> mail_state.Effective:
    """The same for one record id. Raises `mail_state.StateError` as `load_record` does."""
    return mail_state.effective_record(record_id, state_root)


# --------------------------------------------------------------------------------------
# Calibrate
# --------------------------------------------------------------------------------------

CALIBRATE_SUFFIX = ".eml"
CALIBRATE_MAX_FILES = 5_000
CALIBRATE_HASH_CHARS = 16
CALIBRATE_TEMP_PREFIX = "mailscan-calibrate-"


class Forged(NamedTuple):
    """What the message the caller sent itself, with a forged header, looked like on arrival."""
    headers: int            # Authentication-Results headers it carried
    profile_headers: int    # of those, the ones under the authserv-id of the profile
    first_is_profile: bool  # the first one is under that id
    sender_status: str      # a word of mail_sender.SENDER_STATUSES
    sender_reason: str      # a word of mail_sender.SENDER_REASONS


class Calibration(NamedTuple):
    scanned: int                                # regular .eml files scanned
    unreadable: int                             # regular .eml files that could not be read
    not_read: int                               # other entries of the directory: never opened
    over_limit: int                             # .eml files beyond CALIBRATE_MAX_FILES: not scanned
    failures: int                               # scans that ended as a scanner error
    verdicts: Dict[str, int]
    replies: Dict[str, int]
    rules: Dict[str, Tuple[int, int]]           # rule id -> (messages, hits)
    gaps: Dict[str, Tuple[int, int]]            # gap name -> (messages, count)
    header_ambiguous: Dict[str, Tuple[int, int]]    # header name -> (messages, count)
    senders: Dict[Tuple[str, str], int]         # (status, reason) -> messages
    profile: bool                               # the config carries a provider profile
    profile_hash: Optional[str]                 # the keyed hash of its authserv-id
    first_ids: Dict[str, int]                   # keyed hash of the id of the FIRST header -> messages
    later_ids: Dict[str, int]                   # the same for every header below the first
    no_header: int                              # messages with no Authentication-Results header
    unreadable_headers: int                     # such headers that cannot be read
    forged: Optional[Forged]


def _id_hash(key: bytes, authserv_id: str) -> str:
    folded = authserv_id.strip().lower().encode("utf-8", "surrogatepass")
    return hmac.new(key, folded, hashlib.sha256).hexdigest()[:CALIBRATE_HASH_CHARS]


def _authserv_ids(parsed: Any) -> List[Optional[str]]:
    """The authserv-id of every Authentication-Results header in order; None for one that cannot be read."""
    out: List[Optional[str]] = []
    for value in parsed.headers.authentication_results:
        try:
            read = mail_sender.parse_authentication_results(value)
        except Exception:  # noqa: BLE001 - a header that breaks the reader is an unread header
            read = None
        out.append(None if read is None else read.authserv_id)
    return out


def _count(table: Dict[Any, int], key: Any, amount: int = 1) -> None:
    table[key] = table.get(key, 0) + amount


def _count_pair(table: Dict[str, Tuple[int, int]], key: str, amount: int) -> None:
    messages, total = table.get(key, (0, 0))
    table[key] = (messages + 1, total + amount)


def _eml_files(directory: Any) -> Tuple[List[str], int, int]:
    """(regular .eml files directly inside `directory`, entries left alone, .eml files over the limit)."""
    try:
        with os.scandir(directory) as listing:
            entries = sorted(listing, key=lambda entry: entry.name)
    except (OSError, ValueError, TypeError):
        raise InputError(INPUT_UNREADABLE) from None
    paths: List[str] = []
    other = 0
    for entry in entries:
        try:
            wanted = (entry.name.lower().endswith(CALIBRATE_SUFFIX)
                      and entry.is_file(follow_symlinks=False) and not entry.is_symlink())
        except OSError:
            wanted = False
        if wanted:
            paths.append(entry.path)
        else:
            other += 1
    return paths[:CALIBRATE_MAX_FILES], other, max(0, len(paths) - CALIBRATE_MAX_FILES)


def calibrate(directory: Any, config: Any, forged: Any = None, now: Any = None) -> Calibration:
    """Scan the .eml files of `directory` into a temporary root and count what the rules said.

    `forged` names a message the caller sent itself from outside with a forged
    Authentication-Results header. Raises ConfigError, and InputError when the directory or
    the forged file cannot be read. Each message is judged alone: the reply budget is not
    counted. Nothing of a message is returned and no state root of the caller is touched.
    """
    settings = read_config(config)
    paths, other, over = _eml_files(directory)
    forged_raw = None
    if forged is not None:
        forged_raw = read_message(forged, settings["max_bytes"])
    profile = settings.get("provider_profile")
    verdicts: Dict[str, int] = {}
    replies: Dict[str, int] = {}
    rules: Dict[str, Tuple[int, int]] = {}
    gaps: Dict[str, Tuple[int, int]] = {}
    ambiguous: Dict[str, Tuple[int, int]] = {}
    senders: Dict[Tuple[str, str], int] = {}
    first_ids: Dict[str, int] = {}
    later_ids: Dict[str, int] = {}
    scanned = unreadable = failures = no_header = unreadable_headers = 0
    forged_facts = None
    root = tempfile.mkdtemp(prefix=CALIBRATE_TEMP_PREFIX)
    try:
        key = mail_state.state_key(root)
        catalog = mail_reuse.catalog_checks()
        for path in paths:
            try:
                raw, digest = read_message(path, settings["max_bytes"])
            except InputError:
                unreadable += 1
                continue
            detail = _scan(raw, digest, settings, root, now, catalog, budget=False)
            scanned += 1
            result = detail.result
            _count(verdicts, result.verdict)
            _count(replies, result.reply)
            if result.failure is not None:
                failures += 1
            for row in (result.record or {}).get("rules", ()):
                _count_pair(rules, row["rule"], row["count"])
            for row in (result.record or {}).get("gaps", ()):
                _count_pair(gaps, row["gap"], row["count"])
            for row in (result.record or {}).get("header_ambiguous", ()):
                _count_pair(ambiguous, row["header"], row["count"])
            if detail.decision is not None:
                _count(senders, (detail.decision.sender.status, detail.decision.sender.reason))
            if detail.parsed is not None:
                ids = _authserv_ids(detail.parsed)
                if not ids:
                    no_header += 1
                unreadable_headers += sum(1 for item in ids if item is None)
                if ids and ids[0] is not None:
                    _count(first_ids, _id_hash(key, ids[0]))
                for item in ids[1:]:
                    if item is not None:
                        _count(later_ids, _id_hash(key, item))
        profile_hash = _id_hash(key, profile["authserv_id"]) if profile else None
        if forged_raw is not None:
            detail = _scan(forged_raw[0], forged_raw[1], settings, root, now, catalog, budget=False)
            ids = _authserv_ids(detail.parsed) if detail.parsed is not None else []
            wanted = profile["authserv_id"].strip().lower() if profile else None
            under = [item is not None and wanted is not None and item.strip().lower() == wanted for item in ids]
            sender = detail.decision.sender if detail.decision is not None else mail_rules.error_decision().sender
            forged_facts = Forged(len(ids), sum(under), bool(under and under[0]), sender.status, sender.reason)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return Calibration(scanned, unreadable, other, over, failures, verdicts, replies, rules, gaps, ambiguous,
                       senders, profile is not None, profile_hash, first_ids, later_ids, no_header,
                       unreadable_headers, forged_facts)


# --------------------------------------------------------------------------------------
# The import guard
# --------------------------------------------------------------------------------------

# The design's list: mail transports, the network, processes.
FORBIDDEN_MODULES = ("smtplib", "imaplib", "poplib", "ftplib", "socket", "ssl", "http", "asyncio",
                     "subprocess", "multiprocessing", "ctypes")
# The same three kinds under other names: added here, beyond the design's list.
FORBIDDEN_MODULES_MORE = ("socketserver", "xmlrpc", "nntplib", "telnetlib", "smtpd", "webbrowser", "pty",
                          "concurrent", "_socket", "_ssl", "_posixsubprocess", "_ctypes")
URLLIB = "urllib"
URLLIB_ALLOWED = "urllib.parse"
FORBIDDEN_OS_NAMES = ("system", "popen", "fork", "forkpty", "startfile")
FORBIDDEN_OS_PREFIXES = ("exec", "spawn", "posix_spawn")

GUARD_IMPORT = "import"
GUARD_OS = "os-call"
GUARD_UNREADABLE = "unreadable"
GUARD_KINDS = (GUARD_IMPORT, GUARD_OS, GUARD_UNREADABLE)
# Outside the guard, by design and by name: (skill, directory, file) and why.
GUARD_OUT_OF_SCOPE = ("secret-scanning", "scripts", "secrets-scan.py")
GUARD_OUT_OF_SCOPE_REASON = (
    "the secrets catalog is a file of the skill secret-scanning, not of mail-scan: load_checks of "
    "intake-scan runs it to read its table of patterns, and it imports subprocess inside a function "
    "that mail-scan never calls")
INTAKE_LABEL = "intake-scan"
OTHER_FILE_LABEL = "another-file"


class GuardFinding(NamedTuple):
    file: str       # a label of ours: a script of this skill, or `intake-scan/<file>`
    kind: str       # a word of GUARD_KINDS
    name: str       # a forbidden module or `os.<function>`; "" for an unreadable file


def _forbidden_module(name: str) -> Optional[str]:
    """The forbidden module `name` stands for, or None. `name` is dotted, as written."""
    top = name.split(".", 1)[0]
    if top in FORBIDDEN_MODULES or top in FORBIDDEN_MODULES_MORE:
        return top
    if top == URLLIB and name != URLLIB_ALLOWED and not name.startswith(URLLIB_ALLOWED + "."):
        return URLLIB
    return None


def _forbidden_os(name: str) -> bool:
    return name in FORBIDDEN_OS_NAMES or name.startswith(FORBIDDEN_OS_PREFIXES)


def _literal(node: Any) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def guard_source(source: str, label: str) -> List[GuardFinding]:
    """The findings of the guard in one module, given as text."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return [GuardFinding(label, GUARD_UNREADABLE, "")]
    found: List[GuardFinding] = []

    def add(kind: str, name: str) -> None:
        finding = GuardFinding(label, kind, name)
        if finding not in found:
            found.append(finding)

    os_names = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_names.add(alias.asname or "os")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bad = _forbidden_module(alias.name)
                if bad is not None:
                    add(GUARD_IMPORT, bad)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == URLLIB:
                if any(alias.name != "parse" for alias in node.names):
                    add(GUARD_IMPORT, URLLIB)
            else:
                bad = _forbidden_module(node.module)
                if bad is not None:
                    add(GUARD_IMPORT, bad)
            if node.module == "os":
                for alias in node.names:
                    if alias.name == "*" or _forbidden_os(alias.name):
                        add(GUARD_OS, "os." + alias.name)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in os_names and _forbidden_os(node.attr):
                add(GUARD_OS, "os." + node.attr)
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            first = _literal(node.args[0]) if node.args else None
            if called in ("__import__", "import_module") and first is not None:
                bad = _forbidden_module(first)
                if bad is not None:
                    add(GUARD_IMPORT, bad)
            if (called == "getattr" and len(node.args) >= 2 and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in os_names):
                second = _literal(node.args[1])
                if second is not None and _forbidden_os(second):
                    add(GUARD_OS, "os." + second)
    return found


def guard_files(scripts_dir: Optional[str] = None, reused: Optional[Sequence[str]] = None) -> List[Tuple[str, str]]:
    """(label, path) of every file the guard reads.

    The Python files directly inside `scripts_dir` (this skill's scripts by default), then
    the intake-scan modules `mail_reuse` loaded (`reused` replaces that list).
    """
    directory = SCRIPTS_DIR if scripts_dir is None else scripts_dir
    out: List[Tuple[str, str]] = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(directory, name)
        if name.endswith(".py") and os.path.isfile(path):
            out.append((name, path))
    files = mail_reuse.reused_module_files() if reused is None else list(reused)
    base = os.path.realpath(mail_reuse.INTAKE_SCRIPTS_DIR)
    for path in files:
        real = os.path.realpath(path)
        inside = real.startswith(base + os.sep)
        relative = os.path.relpath(real, base).replace(os.sep, "/") if inside else os.path.basename(real)
        out.append(("%s/%s" % (INTAKE_LABEL, relative), path))
    return out


def import_guard(scripts_dir: Optional[str] = None, reused: Optional[Sequence[str]] = None) -> List[GuardFinding]:
    """Every finding of the guard over the files of `guard_files`. Empty when the guard holds.

    The catalog file named by GUARD_OUT_OF_SCOPE is never among those files.
    """
    found: List[GuardFinding] = []
    for label, path in guard_files(scripts_dir, reused):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except (OSError, ValueError):
            found.append(GuardFinding(label, GUARD_UNREADABLE, ""))
            continue
        found.extend(guard_source(source, label))
    return found


def guard_labels() -> Tuple[str, ...]:
    """The labels a finding may carry for the tree as it is installed (for a printer's fixed list)."""
    return tuple(label for label, _path in guard_files())


# --------------------------------------------------------------------------------------
# Doctor: the parser behaviours the rules were written against
# --------------------------------------------------------------------------------------

PINNED_PYTHON = (3, 13)     # the version the pinned behaviours were recorded on

_CRLF = "\r\n"


def _pin_message(headers: Sequence[Tuple[str, str]], body: str) -> bytes:
    return (_CRLF.join("%s: %s" % pair for pair in headers) + _CRLF + _CRLF + body).encode("latin-1")


def _pin_multipart(subtype: str, boundary: str, parts: Sequence[str]) -> Tuple[Tuple[str, str], str]:
    body = "".join("--%s%s%s%s" % (boundary, _CRLF, part, _CRLF) for part in parts) + "--%s--%s" % (boundary, _CRLF)
    return ("Content-Type", 'multipart/%s; boundary="%s"' % (subtype, boundary)), body


def _pin_part(media_type: str, body: str, extra: Sequence[Tuple[str, str]] = ()) -> str:
    headers = [("Content-Type", media_type)] + list(extra)
    return _CRLF.join("%s: %s" % pair for pair in headers) + _CRLF + _CRLF + body


def pinned_samples() -> List[Tuple[str, bytes]]:
    """The built-in messages of doctor, put together here in memory. Each is plain sample data."""
    top = [("From", "Ann Example <ann@example.org>"), ("To", "desk@example.com"), ("Subject", "Hello"),
           ("MIME-Version", "1.0")]
    plain = ("Content-Type", "text/plain; charset=utf-8")
    alternative, alternative_body = _pin_multipart("alternative", "pin-a", [
        _pin_part("text/plain; charset=utf-8", "Plain words"),
        _pin_part("text/html; charset=utf-8",
                  '<p>Seen words <a href="https://www.example.com/a">a link</a></p>'
                  '<div style="display:none">unseen words</div>')])
    mixed, mixed_body = _pin_multipart("mixed", "pin-m", [
        _pin_part("text/plain; charset=utf-8", "See the file"),
        _pin_part("application/pdf; name*=utf-8''r%C3%A9sum%C3%A9.pdf", "JVBERi0xLjQK",
                  [("Content-Transfer-Encoding", "base64"),
                   ("Content-Disposition", "attachment; filename*=utf-8''r%C3%A9sum%C3%A9.pdf")]),
        _pin_part("message/rfc822", "From: x@example.net" + _CRLF + _CRLF + "inner")])
    deep_header, deep_body = ("Content-Type", "text/plain; charset=utf-8"), "deep"
    for level in range(mail_lists.MAX_MIME_DEPTH):
        deep_header, deep_body = _pin_multipart("mixed", "pin-d%d" % level, [
            "%s: %s%s%s%s" % (deep_header[0], deep_header[1], _CRLF, _CRLF, deep_body)])
    return [
        ("plain", _pin_message(top + [plain], "Hello there" + _CRLF)),
        ("alternative", _pin_message(top + [alternative], alternative_body)),
        ("two-from", _pin_message([("From", "a@example.org"), ("From", "b@example.net"),
                                   ("Subject", "Hello"), plain], "x")),
        ("group-from", _pin_message([("From", "Team: a@example.org, b@example.net;"), ("Subject", "Hello"),
                                     plain], "x")),
        ("no-from", _pin_message([("Subject", "Hello"), plain], "x")),
        ("encoded-words", _pin_message([("From", "=?utf-8?q?Ann_=C3=89xample?= <ann@example.org>"),
                                        ("Subject", "=?utf-8?b?SGVsbG8gdGhlcmU=?= =?iso-8859-1?q?caf=E9?="),
                                        plain], "x")),
        ("folded-subject", _pin_message([("From", "ann@example.org"),
                                         ("Subject", "Hello" + _CRLF + " again" + _CRLF + "\tand again"),
                                         plain], "x")),
        ("other-charset", _pin_message(top + [("Content-Type", "text/plain; charset=koi8-r")], "x")),
        ("quoted-printable", _pin_message(top + [("Content-Type", "text/plain; charset=iso-8859-1"),
                                                 ("Content-Transfer-Encoding", "quoted-printable")],
                                          "caf=E9 and a soft=" + _CRLF + " break" + _CRLF)),
        ("attachment-and-nested", _pin_message(top + [mixed], mixed_body)),
        ("too-deep", _pin_message(top + [deep_header], deep_body)),
        ("no-boundary", _pin_message(top + [("Content-Type", "multipart/mixed")], "x")),
        ("automated", _pin_message(top + [plain, ("Auto-Submitted", "auto-replied"), ("Return-Path", "<>"),
                                          ("Precedence", "bulk"), ("List-Id", "<list.example.org>"),
                                          ("Authentication-Results", "mx.example.com;" + _CRLF
                                           + " dmarc=pass header.from=example.org")], "x")),
    ]


def parser_facts(raw: bytes) -> Tuple[Any, ...]:
    """What the parser and the view make of `raw`, as fixed words, numbers and three short texts.

    The texts (the From address, the Subject, the visible letters) are compared against the
    pinned sample they belong to and are never printed.
    """
    parsed = mail_parse.parse(raw)
    view = mail_view.build(parsed, ())
    headers = parsed.headers
    return (
        parsed.over_bound,
        tuple((gap.name, gap.detail) for gap in parsed.gaps),
        tuple((item.header, item.reason) for item in parsed.header_ambiguous),
        tuple((part.media_type, part.role, part.depth) for part in parsed.parts),
        tuple((part.subtype, part.charset) for part in parsed.selected),
        tuple((item.role, item.media_type, item.extension_class, item.signature, item.extension)
              for item in parsed.attachments),
        tuple((link.kind, link.host) for link in parsed.links),
        (headers.from_address, headers.from_name, headers.subject),
        (headers.return_path, headers.auto_submitted, headers.precedence, headers.list_id_present,
         headers.authentication_results_count),
        tuple(headers.authentication_results),
        (view.counts.hidden_chars, view.counts.visible_letters, view.counts.links),
        tuple((gap.name, gap.detail) for gap in view.gaps),
    )


# name -> the facts recorded on PINNED_PYTHON (3.13.5). A test regenerates and compares them.
PINNED_FACTS: Dict[str, Tuple[Any, ...]] = {
    "plain": ("",
         (),
         (),
         (("text/plain", "selected", 1),),
         (("plain", "utf-8"),),
         (),
         (),
         ("ann@example.org", "Ann Example", "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 10, 0),
         ()),
    "alternative": ("",
         (),
         (),
         (("multipart/alternative", "container", 1),
          ("text/plain", "unselected", 2),
          ("text/html", "selected", 2)),
         (("html", "utf-8"),),
         (),
         (("anchor", "www.example.com"),),
         ("ann@example.org", "Ann Example", "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (11, 14, 1),
         ()),
    "two-from": ("",
         (),
         (("from", "repeated"),),
         (("text/plain", "selected", 1),),
         (("plain", "utf-8"),),
         (),
         (),
         (None, None, "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 1, 0),
         ()),
    "group-from": ("",
         (),
         (("from", "group"),),
         (("text/plain", "selected", 1),),
         (("plain", "utf-8"),),
         (),
         (),
         (None, None, "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 1, 0),
         ()),
    "no-from": ("",
         (),
         (("from", "missing"),),
         (("text/plain", "selected", 1),),
         (("plain", "utf-8"),),
         (),
         (),
         (None, None, "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 1, 0),
         ()),
    "encoded-words": ("",
         (),
         (),
         (("text/plain", "selected", 1),),
         (("plain", "utf-8"),),
         (),
         (),
         ("ann@example.org", "Ann \xc9xample", "Hello therecaf\xe9"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 1, 0),
         ()),
    "folded-subject": ("",
         (),
         (),
         (("text/plain", "selected", 1),),
         (("plain", "utf-8"),),
         (),
         (),
         ("ann@example.org", "", "Hello again\tand again"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 1, 0),
         ()),
    "other-charset": ("",
         (("charset-unsupported", "body"),),
         (),
         (("text/plain", "selected", 1),),
         (("plain", ""),),
         (),
         (),
         ("ann@example.org", "Ann Example", "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 0, 0),
         ()),
    "quoted-printable": ("",
         (),
         (),
         (("text/plain", "selected", 1),),
         (("plain", "iso-8859-1"),),
         (),
         (),
         ("ann@example.org", "Ann Example", "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 17, 0),
         ()),
    "attachment-and-nested": ("",
         (("nested-message", ""),),
         (),
         (("multipart/mixed", "container", 1),
          ("text/plain", "selected", 2),
          ("application/pdf", "attachment", 2),
          ("message/rfc822", "nested-message", 2)),
         (("plain", "utf-8"),),
         (("attachment", "application/pdf", "known", "pdf", "pdf"),
          ("nested-message", "message/rfc822", "none", "none", "")),
         (),
         ("ann@example.org", "Ann Example", "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 10, 0),
         ()),
    "too-deep": ("depth",
         (("structure-over-bound", "depth"),),
         (),
         (),
         (),
         (),
         (),
         (None, None, None),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 0, 0),
         ()),
    "no-boundary": ("",
         (("parse-defect", "structure"),),
         (),
         (("multipart/mixed", "attachment", 1),),
         (),
         (("attachment", "multipart/mixed", "none", "none", ""),),
         (),
         ("ann@example.org", "Ann Example", "Hello"),
         ("absent", "absent", "absent", False, 0),
         (),
         (0, 0, 0),
         ()),
    "automated": ("",
         (),
         (),
         (("text/plain", "selected", 1),),
         (("plain", "utf-8"),),
         (),
         (),
         ("ann@example.org", "Ann Example", "Hello"),
         ("null", "auto", "bulk", True, 1),
         ("mx.example.com; dmarc=pass header.from=example.org",),
         (0, 1, 0),
         ()),
}


def parser_pins() -> Tuple[int, int]:
    """(samples whose parse is the pinned one, samples). A sample that raises does not hold."""
    samples = pinned_samples()
    held = 0
    for name, raw in samples:
        try:
            if name in PINNED_FACTS and parser_facts(raw) == PINNED_FACTS[name]:
                held += 1
        except Exception:  # noqa: BLE001 - a parse that fails is a behaviour that changed
            pass
    return held, len(samples)


DOCTOR_OK = "ok"
DOCTOR_WARN = "warn"
DOCTOR_FAIL = "fail"
DOCTOR_LEVELS = (DOCTOR_OK, DOCTOR_WARN, DOCTOR_FAIL)


class Doctor(NamedTuple):
    python: Tuple[int, int, int]
    python_pinned: bool                 # this is the minor version the behaviours were recorded on
    pins_held: int
    pins: int
    reuse: bool                         # every reused symbol of intake-scan resolves
    catalog_checks: int                 # 0: the secrets catalog is missing or cannot be used
    schemas: bool                       # both schemas load, and the record schema reads a record of ours
    guard: Tuple[GuardFinding, ...]
    guard_files: int
    custom_root: bool                   # the root is not the default one
    modes: Tuple[Tuple[str, int], ...]  # (label, mode) of what is wider or narrower than it should be
    overrides_ignored: int              # lines of the override log that are not ours
    level: str                          # a word of DOCTOR_LEVELS
    tlds_age_days: int = 0              # the age of the top-level-domain snapshot of the draft check
    tlds_stale: bool = False            # it is over mail_lists.DRAFT_TLDS_MAX_AGE_DAYS old


def _schemas_ok() -> bool:
    try:
        return config_schema() is not None and isinstance(mail_state.record_schema(), dict)
    except Exception:  # noqa: BLE001 - a schema that cannot be read is a failed check
        return False


def tlds_age_days(today: Optional[datetime.date] = None) -> int:
    """How many days old the snapshot of top-level domains is."""
    taken = datetime.date(*(int(part) for part in mail_lists.DRAFT_TLDS_SNAPSHOT_DATE.split("-")))
    return ((today or datetime.date.today()) - taken).days


def doctor(state_root: Any = None, today: Optional[datetime.date] = None) -> Doctor:
    """Look at this host. Nothing is written; a state root that is not there is not made."""
    version = (sys.version_info[0], sys.version_info[1], sys.version_info[2])
    pinned = version[:2] == PINNED_PYTHON
    held, pins = parser_pins()
    reuse = bool(mail_reuse.REUSE_AVAILABLE) and all(
        getattr(mail_reuse, name, None) is not None for name in mail_reuse.PINNED_SYMBOLS)
    checks = len(mail_reuse.catalog_checks().checks)
    schemas = _schemas_ok()
    files = guard_files()
    findings = tuple(import_guard())
    custom = state_root is not None or bool(os.environ.get(mail_state.ENV_ROOT))
    try:
        modes = tuple(mail_state.mode_report(state_root))
        ignored = mail_state.read_overrides(state_root).ignored
        state_ok = True
    except Exception:  # noqa: BLE001 - a root that cannot even be looked at is a failed check
        modes, ignored, state_ok = (), 0, False
    age = tlds_age_days(today)
    stale = age > mail_lists.DRAFT_TLDS_MAX_AGE_DAYS
    if held != pins or not reuse or not checks or not schemas or findings or modes or not state_ok:
        level = DOCTOR_FAIL
    elif custom or ignored or not pinned or stale:
        level = DOCTOR_WARN
    else:
        level = DOCTOR_OK
    return Doctor(version, pinned, held, pins, reuse, checks, schemas, findings, len(files), custom, modes,
                  ignored, level, age, stale)


_DOCTOR_EXITS = {DOCTOR_OK: EXIT_PASS, DOCTOR_WARN: EXIT_CAUTION, DOCTOR_FAIL: EXIT_BLOCK}


def doctor_exit_code(report: Doctor) -> int:
    return _DOCTOR_EXITS.get(report.level, EXIT_BLOCK)
