#!/usr/bin/env python3
"""mail_state.py -- the state root of mail-scan: records, views, sheets, overrides (#351).

Everything mail-scan keeps between two calls is in one directory, the state root, and this
module is the only one that reads or writes it:

    records/<record-id>.json    one `mail-verdict.v1` record per scan; NO message text
    views/<record-id>.txt       the framed view: the ONE file that holds message text
    sheets/<record-id>.txt      the record as a person reads it; no message text
    overrides.jsonl             one line per override a person gave
    key                         32 random bytes, made on first use; never made again once the
                                root holds a record (a lost key is the error `key-missing`)
    last-purge                  when `purge` last ran
    lock                        an empty file the advisory lock is taken on

The root is the argument, else `$FOUNDRY_MAILSCAN_ROOT`, else `~/.foundry/mail-scan`.
Directories are made 0700 and files 0600. A directory of the root that is a symbolic link is
refused (`root-unusable`): records and views never land outside the root. Every file is written whole to a temporary name
beside it and renamed, so a reader never sees half of one; the override log is the one file
that grows, a line at a time, under the lock.

WHAT A RECORD HOLDS. `build_record` copies named fields, one by one, out of the parsed
message, the view result and the decision it is given (`_*_FIELDS` below are the whole
list), and then checks every copied value against the fixed lists of `mail_lists`: a rule
id, a gap name, a role, a media-type word of ours, an id of ours, a number. A field that is
not on the list is never looked at, so the reply target, the subject, an address, a host, a
URL, a file name and removed text cannot reach a record whatever the caller passes. The
sender is a keyed hash: HMAC-SHA256 of the lower-cased From address under the key of the
root, or null for a message with no single From. The sheet is rendered from the finished
record and from nothing else.

THE SEAL. A record carries an HMAC over the rest of itself under a key derived from the
key of the root, and a line of the override log carries one too. A record that was edited
after it was stored, or copied under another id, and a log line somebody typed, fail the
check and are refused: the record cannot be read (so no draft is checked against it and no
override names it) and the line lifts nothing. This is a guard against a careless or
automated edit, not against a process that can read `key`: under one OS user the override
stays a convention kept by the permission prompt and the log.

OVERRIDES. A person lifts a hold for ONE message: `add_override` names a record, and the
line it appends is bound to the SHA-256 of the raw bytes of that record. It refuses an
unknown or unreadable record, a record whose reply is `none-automated`, a record of a
message that was NOT JUDGED (the gap `scanner-error`, or any record no override can release:
there is nothing a person has seen to approve), and a kind that is not among the holds of
the record (`list`: a record that is not list mail). A `block` override also records WHAT
it was given for: the block rule ids and block-class gap names of that record (`basis`). The reason is
stored as its length and SHA-256; its text is not kept. Reading the log, a line counts only
when it ends in a newline, is exactly the text this module writes for its fields, names a
kind of the list and carries a good seal. Anything else is ignored and counted, and an
ignored line lifts nothing: the hold stays.

THE EFFECTIVE VERDICT of a record applies the lines whose digest equals the digest of the
record, and no other line:

    block    lifts the hold `block`, and the verdict becomes caution, ONLY when every
             block rule and block-class gap of the record is in the basis of the line:
             a later scan of the same bytes that blocks for something the person never
             saw stays blocked
    budget   lifts the hold `budget`
    held     lifts the hold `held`
    list     turns `none-list` into draft once no hold is left

While any hold is left the reply is `held`; when the last is lifted it is
`reply_if_released`. A `none-automated` record is never changed by anything. Because a line
is bound to a digest and not to a record id, scanning the same bytes again does not ask for
the override again, and a record of other bytes from the same sender is not touched by it.

TIME IS AN INPUT. Every function that depends on the clock takes `now` (seconds since the
epoch) and uses the system clock only when it is not given. The age of a record, a view and
a sheet is read from the time stamp in its id, never from the file system.

Stdlib only; callee `mail_reuse` (the schema interpreter) with the data of `mail_lists`. It
imports no other module of mail-scan. Importing this module has no side effects.
"""
from __future__ import annotations

import calendar
import contextlib
import getpass
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import stat
import sys
import time
from typing import Any, Dict, Iterator, List, Mapping, NamedTuple, Optional, Sequence, Tuple

import mail_lists
import mail_reuse

# The lock is the one thing here that differs by platform. Each import sits inside an `if`,
# so this module can be imported everywhere.
if sys.platform == "win32":  # pragma: no cover - selected by platform
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None

SCHEMA_ID = "mail-verdict.v1"
OVERRIDE_SCHEMA_ID = "mail-override.v2"     # v2: a line carries its `basis` (fix round 1)
SCANNER_VERSION = "1"
SUBJECT_KIND = "email"

ENV_ROOT = "FOUNDRY_MAILSCAN_ROOT"
DEFAULT_ROOT_PARTS = (".foundry", "mail-scan")      # under the home directory

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
SCHEMA_PATH = os.path.join(os.path.dirname(SCRIPTS_DIR), "schemas", "mail-verdict.v1.json")

DIR_RECORDS = "records"
DIR_VIEWS = "views"
DIR_SHEETS = "sheets"
STATE_DIRS = (DIR_RECORDS, DIR_VIEWS, DIR_SHEETS)
FILE_OVERRIDES = "overrides.jsonl"
FILE_KEY = "key"
FILE_LAST_PURGE = "last-purge"
FILE_LOCK = "lock"
RECORD_SUFFIX = ".json"
TEXT_SUFFIX = ".txt"
TEMP_PREFIX = ".tmp-"

MODE_DIR = 0o700
MODE_FILE = 0o600
KEY_BYTES = 32

DAY_SECONDS = 86_400
TEMP_MAX_AGE_SECONDS = DAY_SECONDS       # purge removes a temporary file older than this
MAX_TIME = 253_402_300_799               # the last second of the year 9999
MAX_COUNT = 2 ** 53
# What is read back is bounded. A file over its bound is not ours.
MAX_RECORD_BYTES = 2_000_000
MAX_VIEW_BYTES = 1_000_000
MAX_LOG_BYTES = 16_000_000
MAX_STAMP_BYTES = 64
_LOCK_TRIES = 600                        # Windows only: one try each 0.1 s

# The fixed words of a refusal or a failure. A `StateError` carries one and nothing else.
ERROR_ID = "id-invalid"
ERROR_RECORD_UNKNOWN = "record-unknown"
ERROR_RECORD_UNREADABLE = "record-unreadable"
ERROR_RECORD_INVALID = "record-invalid"
ERROR_RECORD_EXISTS = "record-exists"
ERROR_VIEW_INVALID = "view-invalid"
ERROR_VIEW_UNKNOWN = "view-unknown"
ERROR_VIEW_UNREADABLE = "view-unreadable"
ERROR_KEY = "key-unreadable"
ERROR_ROOT = "root-unusable"
ERROR_SCHEMA = "schema-unavailable"
ERROR_DIGEST = "digest-invalid"
ERROR_SENDER = "sender-invalid"
ERROR_TIME = "time-invalid"
ERROR_KIND = "kind-unknown"
ERROR_REASON = "reason-missing"
ERROR_AUTOMATED = "override-automated"
ERROR_NOT_HELD = "kind-not-held"
ERROR_LOCK = "lock-unavailable"
ERROR_KEY_MISSING = "key-missing"        # the root holds records and its key is gone
ERROR_NOT_JUDGED = "override-not-judged"     # the record is of a message nobody read: nothing to release
ERRORS = (ERROR_ID, ERROR_RECORD_UNKNOWN, ERROR_RECORD_UNREADABLE, ERROR_RECORD_INVALID, ERROR_RECORD_EXISTS,
          ERROR_VIEW_INVALID, ERROR_VIEW_UNKNOWN, ERROR_VIEW_UNREADABLE, ERROR_KEY, ERROR_ROOT, ERROR_SCHEMA,
          ERROR_DIGEST, ERROR_SENDER, ERROR_TIME, ERROR_KIND, ERROR_REASON, ERROR_AUTOMATED, ERROR_NOT_HELD,
          ERROR_LOCK, ERROR_KEY_MISSING, ERROR_NOT_JUDGED)
# The refusals of `add_override` that say something about the record or the request.
OVERRIDE_REFUSALS = (ERROR_ID, ERROR_RECORD_UNKNOWN, ERROR_RECORD_UNREADABLE, ERROR_KIND, ERROR_REASON,
                     ERROR_AUTOMATED, ERROR_NOT_HELD, ERROR_NOT_JUDGED)
# The gap of a message that was not judged.
GAP_NOT_JUDGED = "scanner-error"

USER_UNKNOWN = "unknown"
RETENTION_RUNNING = "retention: running"
RETENTION_NOT_RUNNING = "retention: not running"


class StateError(Exception):
    """A refusal or a failure of the state. `code` is a word of ERRORS; there is no other text."""

    def __init__(self, code: str) -> None:
        Exception.__init__(self, code)
        self.code = code


# --------------------------------------------------------------------------------------
# Time and ids
# --------------------------------------------------------------------------------------

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_RECORD_ID = re.compile(r"([0-9]{8}T[0-9]{6}Z)-[0-9a-f]{8}")
_TIME_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_USER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}")
_PART_ID = re.compile(r"p[0-9]{1,6}")
_ATTACHMENT_ID = re.compile(r"a[0-9]{1,6}")
_LINK_ID = re.compile(r"l[0-9]{1,6}")


def _seconds(now: Any) -> int:
    """`now` as whole seconds since the epoch; the system clock when it is None."""
    if now is None:
        return int(time.time())
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not 0 <= now <= MAX_TIME:
        raise StateError(ERROR_TIME)
    return int(now)


def time_text(seconds: int) -> str:
    return time.strftime(_TIME_FORMAT, time.gmtime(seconds))


def _read_time(text: str, form: str) -> Optional[int]:
    try:
        return calendar.timegm(time.strptime(text, form))
    except (ValueError, OverflowError):
        return None


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def id_time(record_id: Any) -> int:
    """The instant in a record id, as seconds. Raises `id-invalid` for anything that is not one.

    A record id is the only text of a caller that becomes part of a path here, and this is
    the check every such use goes through: sixteen characters of time stamp, a hyphen and
    eight lower-case hex characters, and nothing else.
    """
    matched = _RECORD_ID.fullmatch(record_id) if isinstance(record_id, str) else None
    seconds = _read_time(matched.group(1), _STAMP_FORMAT) if matched else None
    if seconds is None:
        raise StateError(ERROR_ID)
    return seconds


def new_record_id(now: Any = None) -> str:
    """A time stamp and eight random hex characters."""
    return "%s-%s" % (time.strftime(_STAMP_FORMAT, time.gmtime(_seconds(now))), secrets.token_hex(4))


# --------------------------------------------------------------------------------------
# The root, its files and the lock
# --------------------------------------------------------------------------------------

def state_root(root: Any = None) -> str:
    """The path of the state root: the argument, else the environment, else the default.

    Nothing is created and nothing is read.
    """
    if root is None:
        root = os.environ.get(ENV_ROOT) or None
    if root is None:
        root = os.path.join(os.path.expanduser("~"), *DEFAULT_ROOT_PARTS)
    try:
        root = os.fspath(root)
    except TypeError:
        raise StateError(ERROR_ROOT) from None
    if not isinstance(root, str) or not root or "\x00" in root:
        raise StateError(ERROR_ROOT)
    return os.path.abspath(root)


def _is_link(path: str) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _make_dir(path: str, own: bool = True) -> None:
    """Make `path` a directory (0700) when it is not there. `own`: it is a directory of the
    state root itself, which must not be a symbolic link."""
    if own and _is_link(path):
        raise StateError(ERROR_ROOT)
    if os.path.isdir(path):
        return
    try:
        os.mkdir(path, MODE_DIR)
        os.chmod(path, MODE_DIR)        # the mode asked for, whatever the umask is
    except FileExistsError:
        if not os.path.isdir(path):
            raise StateError(ERROR_ROOT) from None
    except OSError:
        raise StateError(ERROR_ROOT) from None


def ensure_root(root: Any = None) -> str:
    """The state root, made with its three directories (0700) where they are missing.

    A directory that is already there is left as it is; `mode_report` says when one is
    wider than it should be. One of the three that is a symbolic link is `root-unusable`.
    """
    path = state_root(root)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError:
            raise StateError(ERROR_ROOT) from None
    _make_dir(path, own=False)          # the root itself may be a link to where the state is kept
    for name in STATE_DIRS:
        _make_dir(os.path.join(path, name))
    return path


def _state_dir(root: Any, name: str) -> str:
    """The directory `name` of the state root. A symbolic link in its place is refused: what is
    read from it or written to it would lie outside the root."""
    path = os.path.join(state_root(root), name)
    if _is_link(path):
        raise StateError(ERROR_ROOT)
    return path


def record_path(record_id: str, root: Any = None) -> str:
    id_time(record_id)
    return os.path.join(_state_dir(root, DIR_RECORDS), record_id + RECORD_SUFFIX)


def view_path(record_id: str, root: Any = None) -> str:
    id_time(record_id)
    return os.path.join(_state_dir(root, DIR_VIEWS), record_id + TEXT_SUFFIX)


def sheet_path(record_id: str, root: Any = None) -> str:
    id_time(record_id)
    return os.path.join(_state_dir(root, DIR_SHEETS), record_id + TEXT_SUFFIX)


_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# Files are opened as descriptors, in binary. Under this name the portability lint, which
# takes any call named `open` for a text-mode open, does not misread them.
_open_fd = os.open


def _open_private(path: str, flags: int) -> int:
    """Open `path`, which is made 0600 (whatever the umask is) when it is not there yet."""
    try:
        fd = _open_fd(path, flags | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW, MODE_FILE)
    except FileExistsError:
        return _open_fd(path, flags | _O_BINARY | _O_NOFOLLOW)
    try:
        os.chmod(path, MODE_FILE)
    except OSError:
        os.close(fd)
        raise
    return fd


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def _sync_dir(directory: str) -> None:
    try:
        fd = _open_fd(directory, os.O_RDONLY)
    except OSError:
        return                          # a directory cannot be opened on every platform
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_atomic(path: str, data: bytes) -> None:
    """`data` as the whole content of `path` (0600): a temporary file beside it, then a rename.

    If anything fails the temporary file is removed and `path` is as it was.
    """
    directory = os.path.dirname(path)
    temp = os.path.join(directory, TEMP_PREFIX + secrets.token_hex(8))
    fd = _open_fd(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW, MODE_FILE)
    try:
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(temp, MODE_FILE)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    _sync_dir(directory)


def _read_bounded(path: str, limit: int) -> bytes:
    """The content of `path`. OSError when it cannot be read; ValueError when it is over `limit`."""
    fd = _open_fd(path, os.O_RDONLY | _O_BINARY | _O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a file")
        chunks = []
        size = 0
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError("over the bound")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _lock_fd(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    for _ in range(_LOCK_TRIES):  # pragma: no cover - Windows
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.1)
    raise StateError(ERROR_LOCK)  # pragma: no cover - Windows


def _unlock_fd(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    try:  # pragma: no cover - Windows
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextlib.contextmanager
def _locked(root: str) -> Iterator[None]:
    """The advisory lock of the state root, held for the body. One holder at a time."""
    try:
        fd = _open_private(os.path.join(root, FILE_LOCK), os.O_RDWR)
    except OSError:
        raise StateError(ERROR_LOCK) from None
    try:
        _lock_fd(fd)
        try:
            yield
        finally:
            _unlock_fd(fd)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------------------
# The key, the sender hash and the seals
# --------------------------------------------------------------------------------------

_SEAL_RECORD = b"mail-scan record seal v1"
_SEAL_OVERRIDE = b"mail-scan override seal v1"
_SEAL_FIELD = "seal"


def _read_key(path: str) -> Optional[bytes]:
    try:
        data = _read_bounded(path, KEY_BYTES)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise StateError(ERROR_KEY) from None
    if len(data) != KEY_BYTES:
        raise StateError(ERROR_KEY)
    return data


def state_key(root: Any = None, create: bool = True) -> bytes:
    """The key of the state root: 32 random bytes, made on first use and never replaced.

    A key file of another length is `key-unreadable`: a new key would silently cut every
    record and every sender hash loose from the old one. With `create` False a missing key
    is `key-unreadable` too and nothing is written. A root that already holds a record and
    has no key is `key-missing`: the key is never made a second time, because a new one
    would start the reply budget at nothing and leave every record unreadable without a word.
    """
    if not create:
        key = _read_key(os.path.join(state_root(root), FILE_KEY))
        if key is None:
            raise StateError(ERROR_KEY)
        return key
    path = ensure_root(root)
    key_path = os.path.join(path, FILE_KEY)
    key = _read_key(key_path)
    if key is None:
        with _locked(path):
            key = _read_key(key_path)
            if key is None:
                if _ids_in(os.path.join(path, DIR_RECORDS), RECORD_SUFFIX)[0]:
                    raise StateError(ERROR_KEY_MISSING)
                key = secrets.token_bytes(KEY_BYTES)
                try:
                    _write_atomic(key_path, key)
                except OSError:
                    raise StateError(ERROR_KEY) from None
    return key


def key_missing(root: Any = None) -> bool:
    """Whether the root holds a record and no key. Nothing is written; never raises."""
    try:
        path = state_root(root)
        if os.path.lexists(os.path.join(path, FILE_KEY)):
            return False
        return bool(_ids_in(_state_dir(path, DIR_RECORDS), RECORD_SUFFIX)[0])
    except (StateError, OSError):
        return False


def raw_digest(raw: bytes) -> str:
    """The SHA-256 of the raw bytes of a message: what a record and an override name it by."""
    return hashlib.sha256(raw).hexdigest()


def sender_hash(address: Optional[str], root: Any = None) -> Optional[str]:
    """HMAC-SHA256 of the lower-cased address under the key of the root; None for no address.

    The same address in another letter case hashes the same; under another root it does
    not. The address itself is kept nowhere.
    """
    if address is None:
        return None
    if not isinstance(address, str):
        raise StateError(ERROR_SENDER)
    folded = address.strip().lower()
    if not folded:
        return None
    return hmac.new(state_key(root), folded.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _seal(key: bytes, purpose: bytes, item: Mapping[str, Any]) -> str:
    """The seal of `item` (without its own seal field) under a key derived for `purpose`."""
    derived = hmac.new(key, purpose, hashlib.sha256).digest()
    body = {name: value for name, value in item.items() if name != _SEAL_FIELD}
    return hmac.new(derived, _canonical(body), hashlib.sha256).hexdigest()


def _sealed(key: bytes, purpose: bytes, item: Mapping[str, Any]) -> bool:
    seal = item.get(_SEAL_FIELD)
    return isinstance(seal, str) and hmac.compare_digest(seal, _seal(key, purpose, item))


def _reject_constant(_name: str) -> Any:
    raise ValueError("not a value of ours")


def _no_repeats(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, value in pairs:
        if name in out:
            raise ValueError("a key twice")
        out[name] = value
    return out


def _read_object(data: bytes) -> Optional[Dict[str, Any]]:
    """`data` as one JSON object; None for anything else, a repeated key or a number that is not whole."""
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_no_repeats,
                           parse_constant=_reject_constant, parse_float=_reject_constant)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


# --------------------------------------------------------------------------------------
# Building a record: the allowlist
# --------------------------------------------------------------------------------------

_SCHEMA_CACHE: List[Dict[str, Any]] = []


def record_schema() -> Dict[str, Any]:
    """mail-verdict.v1 as a dict. Read with `json`: `load_schema` of intake-scan reads its own only."""
    if not _SCHEMA_CACHE:
        try:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
                schema = json.load(handle)
        except (OSError, ValueError):
            raise StateError(ERROR_SCHEMA) from None
        if not isinstance(schema, dict) or schema.get("$id") != SCHEMA_ID:
            raise StateError(ERROR_SCHEMA)
        _SCHEMA_CACHE.append(schema)
    return _SCHEMA_CACHE[0]


def schema_errors(record: Any) -> List[str]:
    """The ways `record` breaks mail-verdict.v1, as the interpreter of intake-scan reports them."""
    if mail_reuse.validate_record is None:
        raise StateError(ERROR_SCHEMA)
    return list(mail_reuse.validate_record(record, record_schema()))


# THE ALLOWLIST. (field of the input, key in the record). `build_record` reads these fields
# and no other; each holds an id of ours, a number, a boolean or a word of `mail_lists`.
_DECISION_WORDS = ("verdict", "reply", "reply_if_released")
_RULE_FIELDS = (("rule_id", "rule"), ("rule_class", "class"), ("count", "count"))
_GAP_FIELDS = (("name", "gap"), ("gap_class", "class"), ("reply_effect", "effect"), ("detail", "detail"),
               ("count", "count"))
_AMBIGUITY_FIELDS = (("header", "header"), ("reason", "reason"), ("count", "count"))
_PART_FIELDS = (("part_id", "id"), ("media_type", "type"), ("role", "role"), ("depth", "depth"))
_ATTACHMENT_FIELDS = (("attachment_id", "id"), ("part_id", "part"), ("role", "role"), ("media_type", "type"),
                      ("extension_class", "extension_class"), ("signature", "signature"), ("size", "size"))
_LINK_FIELDS = (("link_id", "id"), ("part_id", "part"), ("kind", "kind"), ("number", "number"),
                ("flags", "flags"))
VIEW_FLAG_FIELDS = ("warning", "truncated")
# The counts of a view result, by the names `mail_view.ViewCounts` gives them.
VIEW_COUNT_FIELDS = (
    "hidden_chars", "uncertain_chars", "dropped_chars", "dropped_elements", "dropped_attributes",
    "tag_chars", "bidi_chars", "format_chars", "links", "links_unlisted", "secrets_masked",
    "quoted_lines", "visible_chars", "visible_letters", "images", "style_blocks",
    "conditional_comments", "view_chars", "view_lines")

# The media-type words the parser writes: a listed type, `<main type>/other`, or `other`.
MEDIA_WORDS = frozenset(mail_lists.COMMON_MEDIA_TYPES) | frozenset(mail_lists.DANGEROUS_MEDIA_TYPES) | frozenset(
    mail_lists.GENERIC_MEDIA_TYPES) | frozenset(mail_lists.ACTIVE_CONTENT_MEDIA_TYPES) | frozenset(
        media for row in mail_lists.SIGNATURES for media in row.media_types) | frozenset(
            main + "/" + mail_lists.MEDIA_TYPE_OTHER for main in mail_lists.MEDIA_MAIN_TYPES) | frozenset(
                {mail_lists.MEDIA_TYPE_OTHER})
_SIGNATURE_WORDS = frozenset(mail_lists.SIGNATURE_NAMES) | {mail_lists.SIGNATURE_NONE}
_RECORD_RULE_CLASSES = (mail_lists.CLASS_BLOCK, mail_lists.CLASS_CAUTION, mail_lists.CLASS_REPLY)
_RELEASED_WORDS = (mail_lists.REPLY_DRAFT, mail_lists.REPLY_NONE_LIST, mail_lists.REPLY_HELD)


def _field(source: Any, name: str) -> Any:
    """One named field of an input: a key of a mapping or an attribute of a tuple type."""
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _sequence(source: Any, name: str) -> List[Any]:
    value = None if source is None else _field(source, name)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise StateError(ERROR_RECORD_INVALID)
    return list(value)


def _rows(items: Sequence[Any], fields: Sequence[Tuple[str, str]]) -> List[Dict[str, Any]]:
    rows = []
    for item in items:
        row = {}
        for name, key in fields:
            value = _field(item, name)
            row[key] = list(value) if isinstance(value, tuple) else value
        rows.append(row)
    return rows


def _need(condition: Any) -> None:
    if not condition:
        raise StateError(ERROR_RECORD_INVALID)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_COUNT


def _is_word(value: Any, words: Any) -> bool:
    return isinstance(value, str) and value in words


def _is_id(value: Any, pattern: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _check_decision(record: Mapping[str, Any]) -> None:
    """A verdict, a reply and holds that go together. A decision that does not is not stored."""
    verdict, reply, released, holds = (record["verdict"], record["reply"], record["reply_if_released"],
                                       record["holds"])
    _need(_is_word(verdict, mail_lists.VERDICTS) and _is_word(reply, mail_lists.REPLIES))
    _need(isinstance(holds, list) and all(_is_word(kind, mail_lists.HOLD_KINDS) for kind in holds))
    _need(len(set(holds)) == len(holds))
    if reply == mail_lists.REPLY_NONE_AUTOMATED:
        _need(not holds and released == mail_lists.REPLY_NONE_AUTOMATED)
        return
    _need(_is_word(released, _RELEASED_WORDS))
    _need((reply == mail_lists.REPLY_HELD) == bool(holds))
    if not holds:
        _need(reply == released and verdict != mail_lists.VERDICT_BLOCK)
    if verdict == mail_lists.VERDICT_BLOCK:
        _need(mail_lists.HOLD_BLOCK in holds)


def _check_values(record: Mapping[str, Any]) -> None:
    """Every copied value is an id of ours, a number, a boolean or a word of a fixed list."""
    _check_decision(record)
    for row in record["rules"]:
        rule = mail_lists.RULES.get(row["rule"]) if isinstance(row["rule"], str) else None
        _need(rule is not None and row["class"] == rule.rule_class)
        _need(row["class"] in _RECORD_RULE_CLASSES and _is_count(row["count"]))
    for row in record["gaps"]:
        gap = mail_lists.GAPS.get(row["gap"]) if isinstance(row["gap"], str) else None
        _need(gap is not None and row["class"] == gap.gap_class and row["effect"] == gap.reply_effect)
        _need(_is_word(row["detail"], mail_lists.GAP_DETAILS) and _is_count(row["count"]))
    for row in record["header_ambiguous"]:
        _need(_is_word(row["header"], mail_lists.AMBIGUOUS_HEADER_NAMES))
        _need(_is_word(row["reason"], mail_lists.HEADER_REASONS) and _is_count(row["count"]))
    _need(record["over_bound"] == "" or _is_word(record["over_bound"], mail_lists.PARSE_BOUND_NAMES))
    _need(isinstance(record["attachment_only"], bool))
    inventory = record["inventory"]
    for row in inventory["parts"]:
        _need(_is_id(row["id"], _PART_ID) and _is_word(row["type"], MEDIA_WORDS))
        _need(_is_word(row["role"], mail_lists.PART_ROLES) and _is_count(row["depth"]))
    for row in inventory["attachments"]:
        _need(_is_id(row["id"], _ATTACHMENT_ID) and _is_id(row["part"], _PART_ID))
        _need(_is_word(row["role"], mail_lists.ATTACHMENT_ROLES) and _is_word(row["type"], MEDIA_WORDS))
        _need(_is_word(row["extension_class"], mail_lists.EXTENSION_CLASSES))
        _need(_is_word(row["signature"], _SIGNATURE_WORDS) and _is_count(row["size"]))
    for row in inventory["links"]:
        _need(_is_id(row["id"], _LINK_ID) and _is_id(row["part"], _PART_ID))
        _need(_is_word(row["kind"], mail_lists.LINK_KINDS) and _is_count(row["number"]))
        _need(isinstance(row["flags"], list) and all(_is_word(f, mail_lists.LINK_FLAGS) for f in row["flags"]))
    view = record["view"]
    if view is not None:
        _need(all(isinstance(view[name], bool) for name in VIEW_FLAG_FIELDS))
        _need(all(_is_count(view["counts"][name]) for name in VIEW_COUNT_FIELDS))


def build_record(raw_sha256: str, parsed: Any, view: Any, decision: Any, sender: Optional[str] = None,
                 root: Any = None, now: Any = None) -> Dict[str, Any]:
    """A finished, sealed `mail-verdict.v1` record for one scan. Nothing is written.

        raw_sha256   `raw_digest(raw)`
        parsed       the parsed message, as `mail_parse.parse` returns it or in its
                     recordable form; None for a message that was not parsed
        view         the view result, likewise; None when no view was built
        decision     the decision of `mail_rules`, likewise
        sender       `sender_hash(the From address)`, or None for no single From

    Only the fields of the allowlist are read from the three inputs. Raises `StateError`
    (`record-invalid`) when a copied value is not what its place allows, or the decision
    does not hold together: such a scan is the caller's to store as an error decision.
    """
    if not is_digest(raw_sha256):
        raise StateError(ERROR_DIGEST)
    if sender is not None and not is_digest(sender):
        raise StateError(ERROR_SENDER)
    _need(decision is not None)
    seconds = _seconds(now)
    record: Dict[str, Any] = {
        "schema": SCHEMA_ID,
        "id": new_record_id(seconds),
        "time": time_text(seconds),
        "sha256": raw_sha256,
        "subject": {"kind": SUBJECT_KIND},
        "sender": sender,
    }
    for name in _DECISION_WORDS:
        record[name] = _field(decision, name)
    record["holds"] = _sequence(decision, "holds")
    record["rules"] = _rows(_sequence(decision, "rule_hits"), _RULE_FIELDS)
    record["gaps"] = _rows(_sequence(decision, "gaps"), _GAP_FIELDS)
    record["header_ambiguous"] = _rows(_sequence(parsed, "header_ambiguous"), _AMBIGUITY_FIELDS)
    over_bound = None if parsed is None else _field(parsed, "over_bound")
    record["over_bound"] = "" if over_bound is None else over_bound
    record["attachment_only"] = False if parsed is None else _field(parsed, "attachment_only")
    record["inventory"] = {
        "parts": _rows(_sequence(parsed, "parts"), _PART_FIELDS),
        "attachments": _rows(_sequence(parsed, "attachments"), _ATTACHMENT_FIELDS),
        "links": _rows(_sequence(parsed, "links"), _LINK_FIELDS),
    }
    if view is None:
        record["view"] = None
    else:
        counts = _field(view, "counts")
        _need(counts is not None)
        record["view"] = {
            "warning": _field(view, "warning"), "truncated": _field(view, "truncated"),
            "counts": {name: _field(counts, name) for name in VIEW_COUNT_FIELDS}}
    record["versions"] = {"scanner": SCANNER_VERSION, "lists": mail_lists.LISTS_VERSION,
                          "python": platform.python_version()}
    try:
        _check_values(record)
    except (KeyError, TypeError):
        raise StateError(ERROR_RECORD_INVALID) from None
    record[_SEAL_FIELD] = _seal(state_key(root), _SEAL_RECORD, record)
    if schema_errors(record):
        raise StateError(ERROR_RECORD_INVALID)
    return record


# --------------------------------------------------------------------------------------
# The sheet
# --------------------------------------------------------------------------------------

SHEET_TITLE = "mail-scan verdict sheet"
SHEET_FOOTER = ("This sheet shows the scan as it was stored. It holds no text of the message. "
                "Overrides given later are not shown here.")


def _described(name: str, table: Mapping[str, Any]) -> str:
    entry = table.get(name)
    return " - %s" % entry.description if entry is not None else ""


def render_sheet(record: Mapping[str, Any]) -> str:
    """The record as a person reads it: fixed words, ids of ours and numbers. No message text."""
    lines = [
        SHEET_TITLE,
        "record: %s" % record["id"],
        "scanned: %s" % record["time"],
        "verdict: %s" % record["verdict"],
        "reply: %s" % record["reply"],
        "reply if released: %s" % record["reply_if_released"],
        "holds: %s" % (", ".join(record["holds"]) or "none"),
        "sender: %s" % ("one From address (kept as a keyed hash)" if record["sender"] else "no single From address"),
        "rules: %d" % len(record["rules"]),
    ]
    for row in record["rules"]:
        lines.append("  %-7s %s x%d%s" % (row["class"], row["rule"], row["count"],
                                         _described(row["rule"], mail_lists.RULES)))
    lines.append("gaps: %d" % len(record["gaps"]))
    for row in record["gaps"]:
        where = " (%s)" % row["detail"] if row["detail"] else ""
        lines.append("  %-7s %s%s x%d%s" % (row["class"], row["gap"], where, row["count"],
                                            _described(row["gap"], mail_lists.GAPS)))
    for row in record["header_ambiguous"]:
        lines.append("header %s: %s x%d" % (row["header"], row["reason"], row["count"]))
    if record["over_bound"]:
        lines.append("over the bound: %s" % record["over_bound"])
    view = record["view"]
    if view is None:
        lines.append("view: none was built")
    else:
        counts = view["counts"]
        lines.extend([
            "removed text, in characters: proven hidden %d, visibility uncertain %d, outside the allowlist %d"
            % (counts["hidden_chars"], counts["uncertain_chars"], counts["dropped_chars"]),
            "removed elements: %d; removed alt and title attributes: %d"
            % (counts["dropped_elements"], counts["dropped_attributes"]),
            "stripped characters: tag %d, bidi %d, format %d"
            % (counts["tag_chars"], counts["bidi_chars"], counts["format_chars"]),
            "view: %d characters in %d lines; links %d; secrets masked %d; quoted lines %d; images %d"
            % (counts["view_chars"], counts["view_lines"], counts["links"], counts["secrets_masked"],
               counts["quoted_lines"], counts["images"]),
            "view: completeness warning %s; cut at the cap %s"
            % ("yes" if view["warning"] else "no", "yes" if view["truncated"] else "no"),
        ])
    inventory = record["inventory"]
    lines.append("inventory: parts %d, attachments %d, links %d%s" % (
        len(inventory["parts"]), len(inventory["attachments"]), len(inventory["links"]),
        "; the message is one part that is not text" if record["attachment_only"] else ""))
    versions = record["versions"]
    lines.append("versions: scanner %s, lists %s, python %s" % (versions["scanner"], versions["lists"],
                                                                versions["python"]))
    lines.append(SHEET_FOOTER)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Storing and reading
# --------------------------------------------------------------------------------------

class Stored(NamedTuple):
    record_id: str
    record_path: str
    view_path: Optional[str]    # None when no view was stored
    sheet_path: str


_FRAME_OPEN = re.compile(re.escape(mail_lists.FRAME_OPEN_FORMAT).replace(
    "%s", "([0-9a-f]{%d})" % mail_lists.FRAME_MARKER_HEX_CHARS))
# What a line reader splits on, LF aside: a framed line holds none of these.
_LINE_BREAKING = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f\\u2028\\u2029]")


def is_frame(text: Any) -> bool:
    """Whether `text` has the shape of a framed view: two marker lines of one drawing, every
    line between them behind the line prefix (or, for a fixed line of the scanner, behind
    the note prefix), nothing after, no character a reader splits on.

    The state stores a view only in this shape, so text that was never framed is not kept
    as one by mistake. It says nothing about what the content is.
    """
    if not isinstance(text, str) or not text.endswith("\n") or _LINE_BREAKING.search(text):
        return False
    lines = text[:-1].split("\n")
    opened = _FRAME_OPEN.fullmatch(lines[0])
    if opened is None or len(lines) < 2 or lines[-1] != mail_lists.FRAME_CLOSE_FORMAT % opened.group(1):
        return False
    note = mail_lists.FRAME_NOTE_PREFIX
    return all(line.startswith(mail_lists.FRAME_LINE_PREFIX)
               or (line.startswith(note) and line[len(note):] in mail_lists.SCANNER_LINES)
               for line in lines[1:-1])


def _verified(record: Any, record_id: str, key: bytes) -> bool:
    """Whether `record` is a record this root sealed under this id."""
    if not isinstance(record, dict) or schema_errors(record):
        return False
    return record["id"] == record_id and _sealed(key, _SEAL_RECORD, record)


def store(record: Mapping[str, Any], framed: Optional[str] = None, root: Any = None) -> Stored:
    """Write the view (when there is one), the sheet and then the record of one scan.

    `record` must be what `build_record` returned under this root; `framed` the framed view
    of the message, or None. The record is written last: a record on disk has its sheet and
    its view beside it. Raises `StateError`: `record-invalid`, `record-exists`,
    `view-invalid`. A failure of the file system is passed on as the OSError it is, with
    no partial file left behind.
    """
    path = ensure_root(root)
    record = dict(record)
    record_id = record.get("id")
    id_time(record_id)
    if not _verified(record, record_id, state_key(path)):
        raise StateError(ERROR_RECORD_INVALID)
    target = record_path(record_id, path)
    if os.path.lexists(target):
        raise StateError(ERROR_RECORD_EXISTS)
    view_file = None
    if framed is not None:
        if not is_frame(framed):
            raise StateError(ERROR_VIEW_INVALID)
        try:
            view_bytes = framed.encode("utf-8")
        except UnicodeEncodeError:
            raise StateError(ERROR_VIEW_INVALID) from None
        if len(view_bytes) > MAX_VIEW_BYTES:
            raise StateError(ERROR_VIEW_INVALID)
        view_file = view_path(record_id, path)
        _write_atomic(view_file, view_bytes)
    sheet_file = sheet_path(record_id, path)
    _write_atomic(sheet_file, render_sheet(record).encode("ascii"))
    body = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    _write_atomic(target, body.encode("ascii"))
    return Stored(record_id, target, view_file, sheet_file)


def load_record(record_id: str, root: Any = None) -> Dict[str, Any]:
    """The record stored under `record_id`, checked against the schema, its id and its seal.

    Raises `StateError`: `id-invalid`; `record-unknown` when there is no such record;
    `record-unreadable` when the file is not a record this root sealed under that id (it
    was edited, cut, copied from another id or another root, or the key is gone).
    """
    path = record_path(record_id, root)
    try:
        data = _read_bounded(path, MAX_RECORD_BYTES)
    except FileNotFoundError:
        raise StateError(ERROR_RECORD_UNKNOWN) from None
    except (OSError, ValueError):
        raise StateError(ERROR_RECORD_UNREADABLE) from None
    record = _read_object(data)
    try:
        key = state_key(root, create=False)
    except StateError:
        raise StateError(ERROR_RECORD_UNREADABLE) from None
    if record is None or not _verified(record, record_id, key):
        raise StateError(ERROR_RECORD_UNREADABLE)
    return record


def read_view(record_id: str, root: Any = None) -> str:
    """The framed view stored for `record_id`: MESSAGE TEXT, for a model inside its frame only.

    Raises `StateError`: `id-invalid`, `view-unknown` (none stored, or purged),
    `view-unreadable` (the file is not a framed view).
    """
    path = view_path(record_id, root)
    try:
        data = _read_bounded(path, MAX_VIEW_BYTES)
    except FileNotFoundError:
        raise StateError(ERROR_VIEW_UNKNOWN) from None
    except (OSError, ValueError):
        raise StateError(ERROR_VIEW_UNREADABLE) from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise StateError(ERROR_VIEW_UNREADABLE) from None
    if not is_frame(text):
        raise StateError(ERROR_VIEW_UNREADABLE)
    return text


def _ids_in(directory: str, suffix: str) -> Tuple[List[str], int]:
    """(the record ids that name a file of `directory`, sorted; the files with any other name)."""
    try:
        names = os.listdir(directory)
    except OSError:
        return [], 0
    ids = []
    other = 0
    for name in names:
        stem = name[:-len(suffix)] if name.endswith(suffix) else ""
        try:
            id_time(stem)
        except StateError:
            other += 1
            continue
        ids.append(stem)
    return sorted(ids), other


def record_ids(root: Any = None) -> List[str]:
    """The ids of the stored records, oldest first. Nothing is opened."""
    return _ids_in(_state_dir(root, DIR_RECORDS), RECORD_SUFFIX)[0]


# --------------------------------------------------------------------------------------
# The budget query
# --------------------------------------------------------------------------------------

def _was_open_to_a_draft(record: Mapping[str, Any], entries: Sequence["Override"]) -> bool:
    """Whether a draft could really be written for the message of `record`.

    Its recorded verdict was not a block and its reply is `draft`: as recorded, or after the
    overrides a person gave for it. Whatever the sender check said of it: a message that got
    a draft counts (fix round 2: mail with a DMARC failure was drafted to without limit).
    """
    if record["verdict"] == mail_lists.VERDICT_BLOCK:
        return False
    if record["reply"] == mail_lists.REPLY_DRAFT:
        return True
    return effective_of(record, entries).reply == mail_lists.REPLY_DRAFT


def earlier_drafts(sender: Optional[str], digest: str, root: Any = None, now: Any = None) -> int:
    """How many other messages of this sender were really open to a draft in the seven days BEFORE this one.

    WHAT COUNTS. A message of the same sender hash, of other raw bytes, with a record that
    `_was_open_to_a_draft`: not blocked, and a reply of `draft` as recorded or after an
    override, whatever its sender result. Mail that was blocked or held never counts, so a
    stranger cannot spend a real sender's budget with mail the scanner stopped. (Under a
    provider profile mail with a DMARC failure is held, so it does not count there; without
    a profile no failure is ever read, such mail is drafted to, and it counts.)

    WHEN. The message asked about is placed at its FIRST record (the smallest record id
    among the records of its raw digest; ids sort by their time stamp, then by their random
    part), or at `now` when it has none yet. Another message counts when its first counting
    record comes before that moment and no more than `mail_lists.BUDGET_WINDOW_DAYS` days
    before it. Mail that arrived AFTER a message never counts against it, so scanning a
    message again within the window gives the count its first scan gave.

    WHICH FILES ARE OPENED. A record file is chosen by the time stamp in its id BEFORE it is
    opened: the `mail_lists.BUDGET_LOOKBACK_DAYS` days before `now`, and then as many days
    before the first record of this message, as long as an earlier one keeps turning up. So
    the work is bounded by two weeks of mail, not by everything the root keeps. The price:
    a first record that lies further back than that is not seen, so a message whose records
    all lie more than two weeks back is placed at `now`, and another message is placed by
    its first record within those two weeks.

    0 for a null sender. A record that cannot be read is not counted. Nothing is written.
    """
    if not is_digest(digest):
        raise StateError(ERROR_DIGEST)
    if sender is None:
        return 0
    if not is_digest(sender):
        raise StateError(ERROR_SENDER)
    seconds = _seconds(now)
    window = mail_lists.BUDGET_WINDOW_DAYS * DAY_SECONDS
    ids = [(id_time(record_id), record_id) for record_id in record_ids(root)]     # sorted: ids sort by time
    entries = read_overrides(root).entries
    lookback = mail_lists.BUDGET_LOOKBACK_DAYS * DAY_SECONDS
    opened: Dict[str, Optional[Dict[str, Any]]] = {}
    low = seconds - lookback
    while True:
        for stamp, record_id in ids:
            if stamp > seconds:
                break
            if stamp < low or record_id in opened:
                continue
            try:
                opened[record_id] = load_record(record_id, root)
            except StateError:
                opened[record_id] = None
        mine = sorted(record_id for record_id, record in opened.items()
                      if record is not None and record["sha256"] == digest)
        own = mine[0] if mine else None
        moment = seconds if own is None else id_time(own)
        if moment - lookback >= low:
            break
        low = moment - lookback
    first: Dict[str, str] = {}  # raw digest -> the first counting record id of another message
    for record_id in sorted(opened):
        record = opened[record_id]
        if record is None or record["sha256"] == digest or record["sender"] is None:
            continue
        if not hmac.compare_digest(record["sender"], sender) or not _was_open_to_a_draft(record, entries):
            continue
        first.setdefault(record["sha256"], record_id)
    oldest = moment - window
    count = 0
    for record_id in first.values():
        stamp = id_time(record_id)
        before = stamp <= moment if own is None else record_id < own
        if before and stamp >= oldest:
            count += 1
    return count


# --------------------------------------------------------------------------------------
# The override log
# --------------------------------------------------------------------------------------

class Override(NamedTuple):
    time: str               # when it was given
    record: str             # the record it named
    sha256: str             # the raw digest of that record: what the override is bound to
    kind: str               # a word of mail_lists.OVERRIDE_KINDS
    reason_length: int      # characters of the reason; its text is not kept
    reason_sha256: str
    user: str               # the OS user, or USER_UNKNOWN
    # What a `block` override was given for: the block rule ids and block-class gap names of
    # the record it named, sorted. Empty for the other kinds.
    basis: Tuple[str, ...] = ()


class OverrideLog(NamedTuple):
    entries: Tuple[Override, ...]   # the lines that count, in the order of the file
    ignored: int                    # lines that are not an override of ours; they lift nothing


_OVERRIDE_KEYS = frozenset(Override._fields) | {"schema", _SEAL_FIELD}
_NO_OVERRIDES = OverrideLog((), 0)


def _os_user() -> str:
    """The name of the OS user running this, from the user database where there is one."""
    name = ""
    try:
        import pwd                      # absent on Windows; imported here so the module loads there
        name = pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, AttributeError, KeyError, OSError):
        try:
            name = getpass.getuser()
        except Exception:               # getpass raises whatever its lookups raise
            name = ""
    return name if isinstance(name, str) and _USER.fullmatch(name) else USER_UNKNOWN


def block_basis(record: Mapping[str, Any]) -> Tuple[str, ...]:
    """The block rule ids and block-class gap names of a record, sorted: what its block rests on."""
    names = {row["rule"] for row in record["rules"] if row["class"] == mail_lists.CLASS_BLOCK}
    names |= {row["gap"] for row in record["gaps"] if row["class"] == mail_lists.CLASS_BLOCK}
    return tuple(sorted(names))


_BASIS_NAMES = frozenset(mail_lists.BLOCK_RULE_IDS) | frozenset(
    name for name, gap in mail_lists.GAPS.items() if gap.gap_class == mail_lists.CLASS_BLOCK)


def _override_line(key: bytes, entry: Override) -> bytes:
    item: Dict[str, Any] = dict(entry._asdict())
    item["basis"] = list(entry.basis)
    item["schema"] = OVERRIDE_SCHEMA_ID
    item[_SEAL_FIELD] = _seal(key, _SEAL_OVERRIDE, item)
    return _canonical(item)


def _read_override(line: bytes, key: bytes) -> Optional[Override]:
    """`line` as an override, or None when it is not one this root wrote."""
    item = _read_object(line)
    if item is None or frozenset(item) != _OVERRIDE_KEYS or item["schema"] != OVERRIDE_SCHEMA_ID:
        return None
    length = item["reason_length"]
    if not (isinstance(item["time"], str) and _TIME_TEXT.fullmatch(item["time"])
            and _read_time(item["time"], _TIME_FORMAT) is not None
            and isinstance(item["kind"], str) and item["kind"] in mail_lists.OVERRIDE_KINDS
            and is_digest(item["sha256"]) and is_digest(item["reason_sha256"])
            and isinstance(length, int) and not isinstance(length, bool) and 1 <= length <= MAX_COUNT
            and isinstance(item["user"], str) and _USER.fullmatch(item["user"])):
        return None
    basis = item["basis"]
    if not (isinstance(basis, list) and all(isinstance(name, str) and name in _BASIS_NAMES for name in basis)
            and basis == sorted(set(basis)) and (item["kind"] == mail_lists.HOLD_BLOCK or not basis)):
        return None
    try:
        id_time(item["record"])
    except StateError:
        return None
    if not _sealed(key, _SEAL_OVERRIDE, item) or _canonical(item) != line:
        return None
    fields = {name: item[name] for name in Override._fields}
    fields["basis"] = tuple(basis)
    return Override(**fields)


def _ends_with_newline(path: str) -> bool:
    with open(path, "rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) == b"\n"


def _append_line(root: str, line: bytes) -> None:
    """One whole line at the end of the log, under the lock, in one write."""
    path = os.path.join(root, FILE_OVERRIDES)
    with _locked(root):
        fd = _open_private(path, os.O_WRONLY | os.O_APPEND)
        try:
            # A log that does not end in a newline ends in a line somebody cut short. It
            # is closed first, so the new line cannot become the tail of the cut one.
            start = b"" if os.fstat(fd).st_size == 0 or _ends_with_newline(path) else b"\n"
            _write_all(fd, start + line + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)


def add_override(record_id: str, kind: str, reason: str, root: Any = None, now: Any = None,
                 user: Optional[str] = None) -> Override:
    """Record that a person lifts the hold `kind` for the message of `record_id`.

    Appends one line to the log and returns it. Raises `StateError` and writes nothing for:
    `kind-unknown`; `reason-missing` (no reason, or only white space); `id-invalid`,
    `record-unknown`, `record-unreadable`; `override-automated` (the reply of the record is
    none-automated: nothing releases such a message); `override-not-judged` (the record
    carries the gap `scanner-error`, or its reply would still be held with every hold
    lifted: nobody read that message, so there is nothing a person can have approved);
    `kind-not-held` (the kind is not among the holds of the record; for `list`, the record
    is not list mail). A `block` override is bound to what the record was blocked for.
    """
    if not isinstance(kind, str) or kind not in mail_lists.OVERRIDE_KINDS:
        raise StateError(ERROR_KIND)
    if not isinstance(reason, str) or not reason.strip():
        raise StateError(ERROR_REASON)
    record = load_record(record_id, root)
    if record["reply"] == mail_lists.REPLY_NONE_AUTOMATED:
        raise StateError(ERROR_AUTOMATED)
    if (record["reply_if_released"] == mail_lists.REPLY_HELD
            or any(row["gap"] == GAP_NOT_JUDGED for row in record["gaps"])):
        raise StateError(ERROR_NOT_JUDGED)
    if kind == mail_lists.OVERRIDE_LIST:
        held = record["reply_if_released"] == mail_lists.REPLY_NONE_LIST
    else:
        held = kind in record["holds"]
    if not held:
        raise StateError(ERROR_NOT_HELD)
    path = state_root(root)
    name = _os_user() if user is None else user
    entry = Override(
        time=time_text(_seconds(now)), record=record_id, sha256=record["sha256"], kind=kind,
        reason_length=len(reason),
        reason_sha256=hashlib.sha256(reason.encode("utf-8", "surrogatepass")).hexdigest(),
        user=name if isinstance(name, str) and _USER.fullmatch(name) else USER_UNKNOWN,
        basis=block_basis(record) if kind == mail_lists.HOLD_BLOCK else ())
    _append_line(path, _override_line(state_key(path, create=False), entry))
    return entry


def read_overrides(root: Any = None) -> OverrideLog:
    """The overrides of the log that count, and how many lines were ignored.

    A line counts when it ends in a newline, is exactly the text this module writes for its
    fields, names a kind of the list and carries the seal of this root. A log that cannot
    be read, or is over its bound, counts as one ignored line and no override. Nothing is
    written.
    """
    path = state_root(root)
    log = os.path.join(path, FILE_OVERRIDES)
    if not os.path.lexists(log):
        return _NO_OVERRIDES
    try:
        with _locked(path):
            data = _read_bounded(log, MAX_LOG_BYTES)
        key = state_key(path, create=False)
    except (OSError, ValueError, StateError):
        return OverrideLog((), 1)
    lines = data.split(b"\n")
    cut_short = lines.pop()             # what follows the last newline: b"" for a whole log
    entries = []
    ignored = 1 if cut_short else 0
    for line in lines:
        if not line:
            continue                    # the newline that closed a cut line
        entry = _read_override(line, key)
        if entry is None:
            ignored += 1
        else:
            entries.append(entry)
    return OverrideLog(tuple(entries), ignored)


# --------------------------------------------------------------------------------------
# The effective verdict
# --------------------------------------------------------------------------------------

class Effective(NamedTuple):
    record_id: str
    sha256: str
    verdict: str            # after overrides
    reply: str              # after overrides
    holds: Tuple[str, ...]  # the holds still in force
    lifted: Tuple[str, ...]     # the override kinds that changed something, in the order of the list
    record_verdict: str     # as the record has them
    record_reply: str


def effective_of(record: Mapping[str, Any], entries: Sequence[Override]) -> Effective:
    """The verdict and the reply of `record` after the overrides bound to its raw digest.

    See THE EFFECTIVE VERDICT in the module text. An entry for another digest is not read,
    and a `block` entry counts only when its basis covers every block rule and block-class
    gap of this record.
    """
    digest = record["sha256"]
    mine = [entry for entry in entries if hmac.compare_digest(entry.sha256, digest)]
    kinds = {entry.kind for entry in mine if entry.kind != mail_lists.HOLD_BLOCK}
    verdict, reply, held = record["verdict"], record["reply"], list(record["holds"])
    if reply == mail_lists.REPLY_NONE_AUTOMATED:
        return Effective(record["id"], digest, verdict, reply, tuple(held), (), verdict, reply)
    # A block is lifted only by a line given for everything this record is blocked for. A
    # record that does not say what it is blocked for is lifted by nothing.
    if "rules" in record and "gaps" in record:
        blocked_for = set(block_basis(record))
        if any(entry.kind == mail_lists.HOLD_BLOCK and blocked_for <= set(entry.basis) for entry in mine):
            kinds.add(mail_lists.HOLD_BLOCK)
    left = [kind for kind in held if kind not in kinds]
    lifted = [kind for kind in mail_lists.HOLD_KINDS if kind in held and kind in kinds]
    now_verdict = verdict
    if verdict == mail_lists.VERDICT_BLOCK and mail_lists.HOLD_BLOCK in lifted:
        now_verdict = mail_lists.VERDICT_CAUTION
    if left:
        now_reply = mail_lists.REPLY_HELD
    else:
        now_reply = record["reply_if_released"] if held else reply
        if (now_reply == mail_lists.REPLY_NONE_LIST and mail_lists.OVERRIDE_LIST in kinds
                and record["reply_if_released"] == mail_lists.REPLY_NONE_LIST):
            now_reply = mail_lists.REPLY_DRAFT
            lifted.append(mail_lists.OVERRIDE_LIST)
    order = {kind: index for index, kind in enumerate(mail_lists.OVERRIDE_KINDS)}
    return Effective(record["id"], digest, now_verdict, now_reply, tuple(left),
                     tuple(sorted(lifted, key=order.__getitem__)), verdict, reply)


def effective_record(record_id: str, root: Any = None) -> Effective:
    """The effective verdict of one stored record. Raises as `load_record` does."""
    record = load_record(record_id, root)
    return effective_of(record, read_overrides(root).entries)


def effective(digest: str, root: Any = None) -> Optional[Effective]:
    """The effective verdict of the NEWEST record whose raw digest is `digest`; None for no such record.

    A record that cannot be read is passed over.
    """
    if not is_digest(digest):
        raise StateError(ERROR_DIGEST)
    for record_id in reversed(record_ids(root)):
        try:
            record = load_record(record_id, root)
        except StateError:
            continue
        if record["sha256"] == digest:
            return effective_of(record, read_overrides(root).entries)
    return None


# --------------------------------------------------------------------------------------
# Purge and the retention report
# --------------------------------------------------------------------------------------

class PurgeResult(NamedTuple):
    views: int              # files removed
    sheets: int
    records: int
    temporary: int          # temporary files a failed write left behind
    time: str               # what was written to last-purge


class Retention(NamedTuple):
    records: int
    views: int
    sheets: int
    oldest_view_age: Optional[int]  # seconds; None when there is no view
    last_purge: Optional[str]       # as written; None when absent or not a time
    running: bool                   # last-purge is there and no older than RETENTION_STALE_DAYS


def _remove_older(directory: str, suffix: str, oldest: int) -> int:
    removed = 0
    for record_id in _ids_in(directory, suffix)[0]:
        if id_time(record_id) < oldest:
            try:
                os.unlink(os.path.join(directory, record_id + suffix))
                removed += 1
            except OSError:
                pass
    return removed


def _remove_temporary(directory: str, seconds: int) -> int:
    removed = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(TEMP_PREFIX):
            continue
        path = os.path.join(directory, name)
        try:
            if seconds - os.lstat(path).st_mtime > TEMP_MAX_AGE_SECONDS:
                os.unlink(path)
                removed += 1
        except OSError:
            pass
    return removed


def purge(root: Any = None, now: Any = None) -> PurgeResult:
    """Delete views and sheets older than seven days and records older than 90, then write last-purge.

    The age of a file is `now` less the time stamp in its record id; a file is deleted when
    it is OLDER than the limit, so one of exactly that age stays. A file whose name is not
    a record id is not ours to delete and is left. The override log is kept.
    """
    path = ensure_root(root)
    seconds = _seconds(now)
    text_oldest = seconds - mail_lists.PURGE_VIEW_DAYS * DAY_SECONDS
    record_oldest = seconds - mail_lists.PURGE_RECORD_DAYS * DAY_SECONDS
    with _locked(path):
        views = _remove_older(os.path.join(path, DIR_VIEWS), TEXT_SUFFIX, text_oldest)
        sheets = _remove_older(os.path.join(path, DIR_SHEETS), TEXT_SUFFIX, text_oldest)
        records = _remove_older(os.path.join(path, DIR_RECORDS), RECORD_SUFFIX, record_oldest)
        temporary = sum(_remove_temporary(directory, seconds)
                        for directory in [path] + [os.path.join(path, name) for name in STATE_DIRS])
        stamp = time_text(seconds)
        _write_atomic(os.path.join(path, FILE_LAST_PURGE), (stamp + "\n").encode("ascii"))
    return PurgeResult(views, sheets, records, temporary, stamp)


def retention_report(root: Any = None, now: Any = None) -> Retention:
    """Counts of what is kept, the age of the oldest view, and whether purge is being run.

    `running` is False when last-purge is absent, is not a time this module wrote, is older
    than `mail_lists.RETENTION_STALE_DAYS` days, or is later than `now`. Nothing is written.
    """
    path = state_root(root)
    seconds = _seconds(now)
    views = _ids_in(_state_dir(path, DIR_VIEWS), TEXT_SUFFIX)[0]
    last = None
    try:
        text = _read_bounded(os.path.join(path, FILE_LAST_PURGE), MAX_STAMP_BYTES).decode("ascii")
        if text.endswith("\n") and _TIME_TEXT.fullmatch(text[:-1]):
            last = _read_time(text[:-1], _TIME_FORMAT)
    except (OSError, ValueError):
        last = None
    running = last is not None and 0 <= seconds - last <= mail_lists.RETENTION_STALE_DAYS * DAY_SECONDS
    return Retention(
        records=len(record_ids(path)), views=len(views),
        sheets=len(_ids_in(_state_dir(path, DIR_SHEETS), TEXT_SUFFIX)[0]),
        oldest_view_age=max(0, seconds - id_time(views[0])) if views else None,
        last_purge=None if last is None else time_text(last), running=running)


def retention_lines(report: Retention) -> List[str]:
    """The report as lines a caller may print: fixed words and numbers."""
    if report.oldest_view_age is None:
        oldest = "oldest view: none"
    else:
        oldest = "oldest view: %d days" % (report.oldest_view_age // DAY_SECONDS)
    return [
        "records: %d" % report.records,
        "views: %d" % report.views,
        "sheets: %d" % report.sheets,
        oldest,
        "last purge: %s" % (report.last_purge or "never"),
        RETENTION_RUNNING if report.running else RETENTION_NOT_RUNNING,
    ]


# --------------------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------------------

MODE_LABELS = ("root", DIR_RECORDS, DIR_VIEWS, DIR_SHEETS, FILE_KEY, FILE_OVERRIDES, FILE_LAST_PURGE,
               FILE_LOCK, "record-file", "view-file", "sheet-file")


def mode_report(root: Any = None) -> List[Tuple[str, int]]:
    """(label, permission bits) of every directory and file of the root that is not 0700 / 0600.

    Empty when all is as it should be, and for a root that does not exist. The labels are
    words of MODE_LABELS; no file name is given. Nothing is opened or changed.
    """
    path = state_root(root)
    wrong: List[Tuple[str, int]] = []

    def check(target: str, label: str, wanted: int) -> None:
        try:
            mode = stat.S_IMODE(os.lstat(target).st_mode)
        except OSError:
            return
        if mode != wanted:
            wrong.append((label, mode))

    check(path, "root", MODE_DIR)
    for name in (FILE_KEY, FILE_OVERRIDES, FILE_LAST_PURGE, FILE_LOCK):
        check(os.path.join(path, name), name, MODE_FILE)
    for name, label in ((DIR_RECORDS, "record-file"), (DIR_VIEWS, "view-file"), (DIR_SHEETS, "sheet-file")):
        directory = os.path.join(path, name)
        check(directory, name, MODE_DIR)
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for entry in names:
            check(os.path.join(directory, entry), label, MODE_FILE)
    return wrong
