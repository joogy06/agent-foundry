#!/usr/bin/env python3
"""studio_capture.py -- #352 (studio-capture): capture one variant page and measure the neutral floor.

    studio_capture.py --variant <variant dir> --run-dir <run dir> --out <evidence dir> [--timeout S] [--json]

The variant directory holds index.html and its local files. The page is rendered offline in
sandboxed Chrome by capture_page.mjs (node + puppeteer-core); this wrapper checks the arguments,
owns the timeout and a fresh temporary Chrome profile, turns the raw numbers into floor rows and
writes `<out>/evidence.json` beside the tiles (`tiles/w<width>/`) and motion frames (`motion/w<width>/`).

EXIT CODES
    0  the capture ran. Floor rows may still FAIL; read them.
    2  the page asked for something outside its own directory. The URLs are listed, every floor
       row is not_run and no tile is kept.
    3  a named gap: the capture could not run (no node, no puppeteer-core, no Chrome, a timeout,
       output this wrapper could not accept). Every affected floor row is not_run, never a pass.
    4  the arguments were refused; nothing was written.
    128 + N  the wrapper was told to stop by signal N (SIGTERM, SIGHUP): node and the browser were
       killed and the profile removed first; no evidence file was written.

NO BROWSER OUTLIVES THE WRAPPER. A capture that ends, times out or is stopped by a signal kills node
and every process of its browser before it returns. A wrapper that is killed outright (SIGKILL)
runs none of that, so node watches for it: the wrapper holds node's stdin open for as long as it
lives, and capture_page.mjs kills the browser and exits when that stdin ends or its parent changes.
Chrome itself is started on a pipe and exits when node goes.

THE EVIDENCE FILE is what studio_verdict.py's `--variant variant-N=<evidence.json>` reads: `floor_rows`,
`tiles` and `motion_frames`, plus what a reader needs to trust them: the sandbox state, the requested
files, the fonts that rendered, the tool versions.

THE FLOOR TABLE below is the one place this capture keeps thresholds. It mirrors
skills/design-critique/references/neutral-floor.md, and a test fails when the two differ.

THE PAGE IS UNTRUSTED and its measurements reach a model. Nothing the page wrote is copied into the
evidence: rows carry numbers and structural selectors, and every string that comes back from the
browser is checked against a fixed pattern here before it is written.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

CAPTURE_VERSION = "1"
EVIDENCE_SCHEMA = "studio-evidence.v1"
EVIDENCE_FILE = "evidence.json"
MJS = Path(__file__).resolve().parent / "capture_page.mjs"

EXIT_OK, EXIT_FAILED, EXIT_GAP, EXIT_USAGE = 0, 2, 3, 4

# One capture: three widths, two page loads each. A clean page takes well under 30 s here. The limit
# is kept low enough that three captures in a row, each running into it, stay inside one 600 s tool
# call: 3 x (120 s + the 5 s the reap may wait) = 375 s.
DEFAULT_TIMEOUT_S = 120.0
REAP_WAIT_S = 5.0
# Width -> height of the captured screen, CSS px. The widths are the floor table's.
VIEWPORTS: Dict[int, int] = {390: 844, 768: 1024, 1280: 800}
MOTION_TIMES_MS: Tuple[int, ...] = (0, 400, 1200, 2400)
SETTLE_MS = 500
PAGE_TIMEOUT_MS = 20000
# Large text per WCAG 2.2 SC 1.4.3: 18 pt, or 14 pt bold (neutral-floor.md, "Large text").
LARGE_TEXT_PX = 24.0
LARGE_TEXT_BOLD_PX = 18.66


class FloorRow(NamedTuple):
    id: str
    passes_when: str            # ">=" or "<="
    threshold: float
    blocking_at: Tuple[int, ...]
    advisory_at: Tuple[int, ...]


_ALL = (390, 768, 1280)
FLOOR: Tuple[FloorRow, ...] = (
    FloorRow("contrast-text", ">=", 4.5, _ALL, ()),
    FloorRow("contrast-large-text", ">=", 3, _ALL, ()),
    FloorRow("contrast-unmeasured", "<=", 0, (), _ALL),
    FloorRow("body-size", ">=", 16, _ALL, ()),
    FloorRow("overflow-x", "<=", 0, _ALL, ()),
    FloorRow("motion-reduced", "<=", 0, _ALL, ()),
    FloorRow("page-weight", "<=", 3000000, _ALL, ()),
    FloorRow("line-length", "<=", 100, (768, 1280), (390,)),
)

GAPS = (
    "no-node", "no-puppeteer", "no-chrome", "no-launch-module", "chrome-launch-failed", "timeout",
    "capture-error", "bad-probe-output", "bad-input", "load-failed", "probe-failed", "tiles-failed",
)

_SELECTOR = re.compile(
    r"^(?:html|body|none|[a-z][a-z0-9]{0,15}:nth-of-type\(\d{1,5}\))"
    r"(?: > [a-z][a-z0-9]{0,15}:nth-of-type\(\d{1,5}\)){0,4}$"
)
_TILE = re.compile(r"^tiles/w\d{2,5}/s\d{2}-t\d{2}\.png$")
_FRAME = re.compile(r"^motion/w\d{2,5}/f\d{2}-\d{4,6}ms\.png$")
_FAMILY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_+-]{0,63}$")
_PLAIN = re.compile(r"^[A-Za-z0-9 ()/.,:'-]{1,160}$")
_URL_SAFE = re.compile(r"[^A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]")
MAX_URL_CHARS = 300
MAX_URLS = 50
MAX_FILES_LISTED = 200


class UsageError(Exception):
    """The arguments were refused. Nothing has been written."""


class StoppedBySignal(SystemExit):
    """SIGTERM or SIGHUP arrived during a capture. It unwinds through `capture`'s clean-up (node and
    the browser are killed, the profile removed) and then ends the process with 128 + the signal."""

    def __init__(self, signum: int) -> None:
        super().__init__(128 + signum)
        self.signum = signum


class Gap(Exception):
    """The capture could not run. `name` is one of GAPS."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


# --- arguments -----------------------------------------------------------------------------------

def _inside(parent: Path, child: Path) -> bool:
    """True when `child` is strictly below `parent`. Both are resolved paths."""
    try:
        rel = child.relative_to(parent)
    except ValueError:
        return False
    return rel != Path(".")


def check_paths(variant: Path, run_dir: Path, out: Path) -> Tuple[Path, Path]:
    """The resolved variant and output directories, or UsageError. Creates `out` when it is absent."""
    if not variant.is_dir():
        raise UsageError("the variant path is not a directory")
    variant_real = variant.resolve()
    index = variant / "index.html"
    if not index.is_file():
        raise UsageError("the variant directory holds no index.html")
    if not _inside(variant_real, index.resolve()):
        raise UsageError("index.html resolves to a file outside the variant directory")
    if not run_dir.is_dir():
        raise UsageError("the run directory does not exist")
    run_real = run_dir.resolve()
    out_real = out.resolve()
    if not _inside(run_real, out_real):
        raise UsageError("the output directory is not inside the run directory")
    if out_real == variant_real or _inside(variant_real, out_real) or _inside(out_real, variant_real):
        raise UsageError("the output directory and the variant directory must be apart")
    if out_real.exists():
        if not out_real.is_dir():
            raise UsageError("the output path exists and is not a directory")
        if any(out_real.iterdir()):
            raise UsageError("the output directory is not empty; a re-capture gets a directory of its own")
    out_real.mkdir(parents=True, exist_ok=True)
    return variant_real, out_real


# --- running node ----------------------------------------------------------------------------------

def _node_env(puppeteer_path: Optional[str]) -> Dict[str, str]:
    """A small environment: what node and Chrome need to start, and where puppeteer-core is."""
    keep = (
        "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "NODE_PATH", "CHROME_PATH",
        "STUDIO_CAPTURE_PUPPETEER_PATH", "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        "XDG_RUNTIME_DIR", "FONTCONFIG_PATH", "FONTCONFIG_FILE",
    )
    env = {k: os.environ[k] for k in keep if k in os.environ}
    if puppeteer_path is not None:
        env["STUDIO_CAPTURE_PUPPETEER_PATH"] = puppeteer_path
    return env


def _kill(proc: "subprocess.Popen[bytes]") -> None:
    """End node. Chrome is NOT in node's process group (puppeteer starts it detached, in a session
    of its own) and node cannot close it once it is killed: `reap_browser` ends Chrome."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _process_table() -> Dict[int, Tuple[int, str]]:
    """{pid: (parent pid, command line)} of the processes this user can see. Empty where it cannot be read."""
    table: Dict[int, Tuple[int, str]] = {}
    proc_dir = Path("/proc")
    if os.name == "posix" and (proc_dir / "self" / "stat").is_file():
        for entry in proc_dir.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
                stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
                parent = int(stat.rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            table[int(entry.name)] = (parent, command)
        return table
    if os.name == "posix":                                   # macOS and other systems without /proc
        try:
            listed = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=10, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return table
        for line in listed.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                table[int(parts[0])] = (int(parts[1]), parts[2])
    return table


def browser_processes(profile: str) -> List[int]:
    """The processes of the browser that was started on `profile`: every process whose command line
    names that profile directory, and everything below one of those (a renderer does not name it)."""
    table = _process_table()
    needle = f"--user-data-dir={profile}"
    found = {pid for pid, (_, command) in table.items() if needle in command}
    grew = True
    while grew:
        grew = False
        for pid, (parent, _) in table.items():
            if parent in found and pid not in found:
                found.add(pid)
                grew = True
    return sorted(found - {os.getpid()})


def reap_browser(profile: str, wait_s: float = REAP_WAIT_S) -> int:
    """Kill every process of the browser started on `profile` and wait until none is left.

    The profile directory is this capture's own (a fresh temporary directory), so nothing else is
    ever matched. Returns how many processes were killed. On Windows node's tree is ended by
    taskkill in `_kill`; this is a no-op there.
    """
    if os.name != "posix":
        return 0
    killed = set()
    deadline = time.monotonic() + wait_s
    while True:
        left = browser_processes(profile)
        for pid in left:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.add(pid)
            except (OSError, ProcessLookupError):
                pass
        if not left or time.monotonic() > deadline:
            return len(killed)
        time.sleep(0.1)


def run_node(payload: Dict[str, Any], timeout_s: float, node: Optional[str], puppeteer_path: Optional[str],
             debug: bool = False) -> Dict[str, Any]:
    """Run capture_page.mjs and return its JSON object. Raises Gap when it could not run."""
    node_bin = node if node is not None else shutil.which("node")
    if not node_bin or not (shutil.which(node_bin) or Path(node_bin).is_file()):
        raise Gap("no-node")
    if not MJS.is_file():
        raise Gap("capture-error")
    kwargs: Dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
    try:
        proc = subprocess.Popen(
            [node_bin, str(MJS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_node_env(puppeteer_path), **kwargs,
        )
    except OSError:
        raise Gap("no-node") from None
    # node reads the payload as one line and then watches its stdin: this second handle keeps the
    # pipe open for as long as this process lives, and no longer. `communicate` closes its own.
    hold = os.dup(proc.stdin.fileno()) if proc.stdin is not None else None
    try:
        stdout, stderr = proc.communicate(json.dumps(payload).encode("utf-8") + b"\n", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill(proc)
        proc.communicate()
        raise Gap("timeout") from None
    except BaseException:                                    # a signal or Ctrl-C: node must not go on alone
        _kill(proc)
        raise
    finally:
        if hold is not None:
            os.close(hold)
    if debug:
        sys.stderr.write(stderr.decode("utf-8", "replace"))
    try:
        raw = json.loads(stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Gap("capture-error") from None
    if not isinstance(raw, dict):
        raise Gap("bad-probe-output")
    if raw.get("gap"):
        raise Gap(raw["gap"] if raw["gap"] in GAPS else "capture-error")
    if proc.returncode != 0:
        raise Gap("capture-error")
    return raw


# --- checking what came back -------------------------------------------------------------------------

def _number(value: Any, allow_none: bool = False) -> Optional[float]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise Gap("bad-probe-output")
    return value


def _selector(value: Any, allow_none: bool = True) -> Optional[str]:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not _SELECTOR.match(value):
        raise Gap("bad-probe-output")
    return value


def _checked_measures(m: Any) -> Dict[str, Any]:
    """The probe's measurements with every value type-checked. Anything unexpected is a gap."""
    if not isinstance(m, dict):
        raise Gap("bad-probe-output")
    out: Dict[str, Any] = {}
    for key, value_key in (("contrast_text", "min"), ("contrast_large", "min"), ("body_size", "min"), ("line_length", "max")):
        part = m.get(key)
        if not isinstance(part, dict):
            raise Gap("bad-probe-output")
        out[key] = {
            "value": _number(part.get(value_key), allow_none=True),
            "element": _selector(part.get("element")),
            "count": int(_number(part.get("count"))),
        }
    for key in ("unmeasured", "running_animations"):
        part = m.get(key)
        if not isinstance(part, dict):
            raise Gap("bad-probe-output")
        out[key] = {"value": int(_number(part.get("count"))), "element": _selector(part.get("element"))}
    out["overflow_x"] = _number(m.get("overflow_x"))
    out["text_elements"] = int(_number(m.get("text_elements")))
    # Frames a reader sees, and frames the probe ran in. An older probe reports neither: none seen.
    seen, probed = (int(_number(m.get(key, 0))) for key in ("frames_seen", "frames_probed"))
    out["frames_unmeasured"] = max(0, seen - probed)
    # Parts of the page that hold a paragraph-like run nowhere, so their body size is that of their
    # other text; and closed shadow roots that hold text, which nothing measured. Absent: none.
    for key in ("body_from_other_text", "closed_shadow_roots"):
        out[key] = int(_number(m.get(key, 0)))
    return out


def advisory_notes(measures: Dict[str, Any]) -> List[str]:
    """What a reader of the rows should know about how they were measured. Never a reason to block."""
    notes = []
    if measures.get("body_from_other_text") and measures["body_size"]["count"]:
        notes.append("body-size-from-other-text")
    if measures.get("closed_shadow_roots"):
        notes.append("closed-shadow-root-not-measured")
    return notes


def unmeasured_rows(measures: Dict[str, Any]) -> Dict[str, str]:
    """The blocking rows that measured NOTHING on a page that shows something, each with why.

    "Nothing to measure" is a pass only where the thing is truly absent (no large text, no long
    paragraph). It is not a pass when the page has text and the probe reached none of it: text in a
    closed shadow root, in a frame it could not run in, in an image, an <svg> or a <canvas>. Text
    over a raster image is neither: it is counted in the advisory `contrast-unmeasured` row, and so
    is each closed shadow root that holds text beside text the probe did reach.

    `body-size` is measured on the paragraph-like runs of the page and, on a page that has text and
    no such run (headings, links, short list items), on its other text: such a page fails the row
    only when text below the threshold was found, and is unmeasured only when no text was reached.
    """
    reached = (measures["contrast_text"]["count"] + measures["contrast_large"]["count"]
               + measures["unmeasured"]["value"])
    out: Dict[str, str] = {}
    if measures.get("frames_unmeasured", 0):
        out["contrast-text"] = out["body-size"] = "frame-not-measured"
    if reached == 0:
        out.setdefault("contrast-text", "text-not-measured")
    if measures["body_size"]["count"] == 0:
        out.setdefault("body-size", "body-text-not-measured")
    return out


def clean_url(url: Any) -> str:
    """A requested URL made safe to print: URL characters only, everything else percent-encoded, capped."""
    text = url if isinstance(url, str) else ""
    text = _URL_SAFE.sub(lambda ch: "".join("%%%02X" % b for b in ch.group(0).encode("utf-8")), text)
    return text[:MAX_URL_CHARS] if text else "(unreadable)"


def _plain(value: Any, pattern: "re.Pattern[str]", fallback: Optional[str]) -> Optional[str]:
    return value if isinstance(value, str) and pattern.match(value) else fallback


# --- floor rows ------------------------------------------------------------------------------------------

def _passes(row: FloorRow, measured: float) -> bool:
    return measured >= row.threshold if row.passes_when == ">=" else measured <= row.threshold


def _row(row: FloorRow, viewport: int, result: str, element: str, measured: Optional[float]) -> Dict[str, Any]:
    return {
        "id": row.id, "blocking": viewport in row.blocking_at, "result": result, "viewport": viewport,
        "element": element, "measured": measured, "threshold": row.threshold,
    }


def not_run_rows(viewports: Sequence[int]) -> List[Dict[str, Any]]:
    """Every floor row at each viewport as not_run: what a capture that did not run leaves."""
    return [
        _row(row, vp, "not_run", "html", None)
        for vp in viewports for row in FLOOR if vp in row.blocking_at + row.advisory_at
    ]


def floor_rows(viewport: int, measures: Dict[str, Any], weight_bytes: float) -> List[Dict[str, Any]]:
    """The floor rows of one viewport from its checked measurements.

    A row with nothing to measure (no large text on the page, no paragraph of three lines) passes
    with `measured: null` and element `none`: the floor is about what is there. Two rows are held
    to more than that, because every page has text and running text: `contrast-text` and
    `body-size` are `not_run`, which blocks, when the probe reached no text element or measured no
    paragraph, or when a frame of the page went unmeasured (see `unmeasured_rows`).
    """
    source = {
        "contrast-text": measures["contrast_text"],
        "contrast-large-text": measures["contrast_large"],
        # Text over a raster image, and each closed shadow root that holds text: seen, not measured.
        "contrast-unmeasured": {"value": measures["unmeasured"]["value"] + measures.get("closed_shadow_roots", 0),
                                "element": measures["unmeasured"]["element"]},
        "body-size": measures["body_size"],
        "overflow-x": {"value": measures["overflow_x"], "element": "html"},
        "motion-reduced": measures["running_animations"],
        "page-weight": {"value": weight_bytes, "element": "html"},
        "line-length": measures["line_length"],
    }
    rows = []
    unmeasured = unmeasured_rows(measures)
    for row in FLOOR:
        if viewport not in row.blocking_at + row.advisory_at:
            continue
        got = source[row.id]
        if row.id in unmeasured and (got["value"] is None or unmeasured[row.id] == "frame-not-measured"):
            rows.append(_row(row, viewport, "not_run", "none", None))
            continue
        if got["value"] is None:
            rows.append(_row(row, viewport, "pass", "none", None))
            continue
        result = "pass" if _passes(row, got["value"]) else "fail"
        rows.append(_row(row, viewport, result, got["element"] or "html", got["value"]))
    return rows


# --- the evidence set ----------------------------------------------------------------------------------------

def _base_evidence(viewports: Sequence[int]) -> Dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "capture": {"status": "gap", "gap": None, "detail": None},
        "sandbox": {"state": "unknown", "confirmed": False, "method": None, "reason": None},
        "request_scope": "variant-directory",
        "offline_emulation": True,
        "viewports": [{"width": w, "height": VIEWPORTS[w]} for w in viewports],
        "floor_rows": not_run_rows(viewports),
        "tiles": [],
        "motion_frames": [],
        "tile_index": [],
        "requests": {"inside": [], "outside": [], "truncated": False},
        "fonts_rendered": [],
        "variant_fonts": {"families": 0, "glyphs": 0},
        "counts": [],
        "warnings": [],
        "tool_versions": {"capture": CAPTURE_VERSION, "python": platform.python_version()},
    }


def gap_evidence(viewports: Sequence[int], gap: str) -> Dict[str, Any]:
    """The evidence set of a capture that could not run: the gap by name, every row not_run."""
    evidence = _base_evidence(viewports)
    evidence["capture"] = {"status": "gap", "gap": gap, "detail": "the capture could not run; no row was measured"}
    return evidence


def build_evidence(raw: Dict[str, Any], viewports: Sequence[int], out: Path) -> Dict[str, Any]:
    """Turn capture_page.mjs's object into the evidence set. Raises Gap on output it cannot accept."""
    evidence = _base_evidence(viewports)
    warnings: List[str] = evidence["warnings"]

    sandbox = raw.get("sandbox")
    if not isinstance(sandbox, dict) or sandbox.get("state") not in ("on", "off"):
        raise Gap("bad-probe-output")
    confirmed = sandbox.get("confirmed") is True
    evidence["sandbox"] = {
        "state": sandbox["state"],
        "confirmed": confirmed,
        "method": _plain(sandbox.get("method"), _PLAIN, None),
        "reason": _plain(sandbox.get("reason"), _PLAIN, None),
    }
    if sandbox["state"] == "off":
        warnings.append("sandbox-off")
    elif not confirmed:
        warnings.append("sandbox-unconfirmed")

    versions = raw.get("versions") if isinstance(raw.get("versions"), dict) else {}
    for key in ("chrome", "puppeteer_core", "node"):
        evidence["tool_versions"][key] = _plain(versions.get(key), _VERSION, "unknown")

    requests = raw.get("requests")
    if not isinstance(requests, dict) or not isinstance(requests.get("inside"), list) or not isinstance(requests.get("outside"), list):
        raise Gap("bad-probe-output")
    outside = [clean_url(u) for u in requests["outside"]]
    evidence["requests"] = {
        "inside": [clean_url(u) for u in requests["inside"][:MAX_FILES_LISTED]],
        "outside": outside[:MAX_URLS],
        "truncated": bool(requests.get("truncated")) or len(outside) > MAX_URLS or len(requests["inside"]) > MAX_FILES_LISTED,
    }

    per_viewport = raw.get("viewports")
    if not isinstance(per_viewport, list) or [v.get("width") if isinstance(v, dict) else None for v in per_viewport] != list(viewports):
        raise Gap("bad-probe-output")

    rows: List[Dict[str, Any]] = []
    fonts: Dict[str, int] = {}
    variant_fonts = {"families": 0, "glyphs": 0}
    failed_viewport: Optional[str] = None
    for got in per_viewport:
        width = got["width"]
        if got.get("error"):
            failed_viewport = got["error"] if got["error"] in GAPS else "capture-error"
            rows.extend(not_run_rows([width]))
            continue
        measures = _checked_measures(got.get("measures"))
        rows.extend(floor_rows(width, measures, _number(got.get("weight_bytes"))))
        warnings.extend(f"{why}-at-{width}" for why in sorted(set(unmeasured_rows(measures).values())))
        warnings.extend(f"{note}-at-{width}" for note in advisory_notes(measures))
        evidence["counts"].append({
            "viewport": width, "text_elements": measures["text_elements"],
            "body_paragraphs": measures["body_size"]["count"], "running_animations": measures["running_animations"]["value"],
        })
        for tile in got.get("tiles") or []:
            if not isinstance(tile, dict) or not isinstance(tile.get("file"), str) or not _TILE.match(tile["file"]) \
                    or not (out / tile["file"]).is_file():
                raise Gap("bad-probe-output")
            evidence["tiles"].append(tile["file"])
            evidence["tile_index"].append({
                "file": tile["file"], "viewport": width, "section": int(_number(tile.get("section"))),
                "element": _selector(tile.get("element"), allow_none=False), "scroll_y": int(_number(tile.get("scroll_y"))),
            })
        if not got.get("tiles"):
            raise Gap("tiles-failed")
        for frame in got.get("motion_frames") or []:
            if not isinstance(frame, str) or not _FRAME.match(frame) or not (out / frame).is_file():
                raise Gap("bad-probe-output")
            evidence["motion_frames"].append(frame)
        if got.get("motion_error"):
            warnings.append(f"motion-frames-failed-at-{width}")
        if got.get("tiles_truncated"):
            warnings.append(f"tiles-truncated-at-{width}")
        for font in got.get("fonts") or []:
            family = _plain(font.get("family") if isinstance(font, dict) else None, _FAMILY, None)
            if family is None:
                continue
            fonts[family] = max(fonts.get(family, 0), int(_number(font.get("glyphs"))))
        vf = got.get("variant_fonts") if isinstance(got.get("variant_fonts"), dict) else {}
        for key in variant_fonts:
            variant_fonts[key] = max(variant_fonts[key], int(_number(vf.get(key, 0))))

    evidence["floor_rows"] = rows
    evidence["fonts_rendered"] = [{"family": f, "glyphs": g} for f, g in sorted(fonts.items(), key=lambda kv: (-kv[1], kv[0]))]
    evidence["variant_fonts"] = variant_fonts
    if evidence["requests"]["truncated"]:
        warnings.append("request-list-truncated")

    if outside:
        # The page reached outside its directory: nothing it rendered is judged.
        evidence["capture"] = {"status": "failed", "gap": None,
                               "detail": "the page requested addresses outside its own directory; see requests.outside"}
        evidence["floor_rows"] = not_run_rows(viewports)
        evidence["tiles"], evidence["motion_frames"], evidence["tile_index"] = [], [], []
        for name in ("tiles", "motion"):
            shutil.rmtree(out / name, ignore_errors=True)
    elif failed_viewport:
        evidence["capture"] = {"status": "gap", "gap": failed_viewport,
                               "detail": "at least one viewport could not be captured; its rows are not_run"}
    else:
        evidence["capture"] = {"status": "ok", "gap": None, "detail": None}
    return evidence


def write_evidence(out: Path, evidence: Dict[str, Any]) -> Path:
    target = out / EVIDENCE_FILE
    tmp = out / (EVIDENCE_FILE + ".tmp")
    tmp.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def exit_code_of(evidence: Dict[str, Any]) -> int:
    return {"ok": EXIT_OK, "failed": EXIT_FAILED}.get(evidence["capture"]["status"], EXIT_GAP)


# --- the capture -------------------------------------------------------------------------------------------------

class _stop_signals:
    """While a capture runs, SIGTERM and SIGHUP raise StoppedBySignal instead of ending the process
    at once, so the capture's own clean-up runs. Outside the main thread nothing is installed."""

    def __enter__(self) -> "_stop_signals":
        self.old: Dict[int, Any] = {}

        def stop(signum: int, _frame: Any) -> None:
            raise StoppedBySignal(signum)

        for name in ("SIGTERM", "SIGHUP"):
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            try:
                self.old[signum] = signal.signal(signum, stop)
            except (ValueError, OSError):                    # not the main thread
                pass
        return self

    def __exit__(self, *_exc: Any) -> None:
        for signum, handler in self.old.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError, TypeError):
                pass


def capture(variant: Path, run_dir: Path, out: Path, *, timeout_s: float = DEFAULT_TIMEOUT_S,
            widths: Optional[Sequence[int]] = None, motion_times_ms: Optional[Sequence[int]] = None,
            node: Optional[str] = None, chrome_path: Optional[str] = None, puppeteer_path: Optional[str] = None,
            debug: bool = False, _simulate_sandbox_failure: bool = False) -> Tuple[int, Dict[str, Any]]:
    """Capture `variant` into `out` and return (exit code, evidence). Raises UsageError before writing.

    `widths` narrows the capture to some of the floor table's widths; the default is all three.
    `_simulate_sandbox_failure` is for tests: it takes the path a host without a sandbox takes.
    """
    viewports = list(VIEWPORTS) if widths is None else list(widths)
    if not viewports or any(w not in VIEWPORTS for w in viewports):
        raise UsageError("a width outside the floor table's widths")
    variant_real, out_real = check_paths(Path(variant), Path(run_dir), Path(out))
    profile = tempfile.mkdtemp(prefix="studio-capture-profile-")
    payload = {
        "variant_dir": str(variant_real), "out_dir": str(out_real), "profile_dir": profile,
        "viewports": [{"width": w, "height": VIEWPORTS[w]} for w in viewports],
        "motion_times_ms": list(MOTION_TIMES_MS if motion_times_ms is None else motion_times_ms),
        "settle_ms": SETTLE_MS, "page_timeout_ms": PAGE_TIMEOUT_MS,
        "large_px": LARGE_TEXT_PX, "large_bold_px": LARGE_TEXT_BOLD_PX,
        "watch_parent": True,
    }
    if chrome_path is not None:
        payload["chrome_path"] = chrome_path
    if _simulate_sandbox_failure:
        payload["simulate_sandbox_failure"] = True
    with _stop_signals():
        try:
            raw = run_node(payload, timeout_s, node, puppeteer_path, debug=debug)
            evidence = build_evidence(raw, viewports, out_real)
        except Gap as gap:
            for name in ("tiles", "motion"):
                shutil.rmtree(out_real / name, ignore_errors=True)
            evidence = gap_evidence(viewports, gap.name)
        except StoppedBySignal:
            for name in ("tiles", "motion"):                 # nothing half-made is left for a later capture
                shutil.rmtree(out_real / name, ignore_errors=True)
            raise
        finally:
            # Whatever happened to node (and to this wrapper, short of being killed outright), no
            # browser of this capture outlives it, and its profile goes.
            reap_browser(profile)
            shutil.rmtree(profile, ignore_errors=True)
    write_evidence(out_real, evidence)
    return exit_code_of(evidence), evidence


def summary(evidence: Dict[str, Any]) -> List[str]:
    """A few fixed-shape lines for a terminal. Holds ids, numbers and cleaned URLs only."""
    cap = evidence["capture"]
    lines = [f"capture: {cap['status']}" + (f" ({cap['gap']})" if cap["gap"] else "")]
    sandbox = evidence["sandbox"]
    lines.append(f"sandbox: {sandbox['state']}" + (", confirmed" if sandbox["confirmed"] else ", NOT confirmed")
                 + (f" ({sandbox['reason']})" if sandbox["reason"] else ""))
    for url in evidence["requests"]["outside"]:
        lines.append(f"outside request: {url}")
    rows = evidence["floor_rows"]
    unmeasured = all(row["result"] == "not_run" for row in rows)
    if unmeasured:
        lines.append("not_run: every floor row")
    for result in ("fail", "not_run"):
        for row in rows:
            if row["result"] == result and not unmeasured:
                kind = "blocking" if row["blocking"] else "advisory"
                lines.append(f"{result}: {row['id']} at {row['viewport']} ({kind}) measured {row['measured']} threshold {row['threshold']}")
    lines.append(f"rows: {sum(r['result'] == 'pass' for r in rows)} pass, {sum(r['result'] == 'fail' for r in rows)} fail, "
                 f"{sum(r['result'] == 'not_run' for r in rows)} not_run; tiles {len(evidence['tiles'])}, "
                 f"motion frames {len(evidence['motion_frames'])}")
    for warning in evidence["warnings"]:
        lines.append(f"warning: {warning}")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Capture one variant page offline and measure the neutral floor.")
    parser.add_argument("--variant", required=True, help="the variant directory (holds index.html)")
    parser.add_argument("--run-dir", required=True, help="the run directory the output must be inside")
    parser.add_argument("--out", required=True, help="a new or empty directory for the evidence set")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="seconds before the capture is stopped")
    parser.add_argument("--json", action="store_true", help="print the evidence set instead of the summary")
    parser.add_argument("--debug", action="store_true", help="pass the capture script's diagnostics through to stderr")
    args = parser.parse_args(argv)
    try:
        code, evidence = capture(Path(args.variant), Path(args.run_dir), Path(args.out), timeout_s=args.timeout, debug=args.debug)
    except UsageError as refused:
        sys.stderr.write(f"studio_capture: {refused}\n")
        return EXIT_USAGE
    if args.json:
        sys.stdout.write(json.dumps(evidence, indent=2) + "\n")
    else:
        sys.stdout.write("\n".join(summary(evidence)) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
