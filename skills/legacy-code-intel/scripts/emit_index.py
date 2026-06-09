#!/usr/bin/env python3
"""emit_index.py — assemble + validate a code-index.v1 from accumulated findings.

Takes the artifact-level rollup (summary.json from accumulate.py) plus artifact
metadata (content_sha256, format, source_path, line_count, model_id, prompt_hash,
pipeline_fingerprint) and produces a complete, schema-valid code-index.v1
document. This is the LAST deterministic step before redaction + store.persist.

Responsibilities:
  1. Attach the `artifact` block (with the dedup keys content_sha256 +
     pipeline_fingerprint computed in the ingest path — anti-requirement #4).
  2. Enforce the per-format closed `kind` enum (the JSON schema keeps `kind` as a
     string so one schema serves all three formats; the closed-set check lives
     here). An out-of-set kind for the declared format is a hard error.
  3. Enforce the bright-line confidence classifier post-emission (HARD-RULE 2):
     any occurrence whose evidence_snippet shows interpolation / dynamic CALL /
     COPY REPLACING / DSX RCP markers is FORCED to speculative, regardless of what
     the LLM emitted. Defense-in-depth over the prompt-level rule.
  4. Build refs.by_path (path-side reverse index; symbol IDs stay path-independent).
  5. jsonschema-validate against code-index.v1.json (anti-requirement #1 — the
     schema itself must be draft-07-valid; checked separately by test_schema_valid).
  6. Deterministic output (sort_keys, stable arrays, SOURCE_DATE_EPOCH sentinel).

Pure stdlib + jsonschema. No LLM calls. Atomic writes (HARD-RULE 3).

CLI usage:
    emit_index.py <summary_json> --output <path>
        --content-sha256 H --format cobol --source-path PAY.cbl --line-count N
        --model-id M --prompt-hash H --pipeline-fingerprint H
        [--ingested-at ISO | --source-date-epoch]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

try:
    from jsonschema import Draft7Validator
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "code-index.v1.json"

# Closed per-format kind sets (the only per-format surface; design §3).
KIND_BY_FORMAT = {
    "cobol": {"program", "division", "section", "paragraph", "data_item", "copybook", "file_descriptor", "call_target"},
    "dsx": {"job", "stage", "link", "column", "parameter", "container", "routine", "sequence"},
    "etl": {"function", "variable", "sql_cte", "table", "call_target", "shell_task"},
    "pick": {"program", "subroutine", "paragraph", "dict_item", "file", "common_block", "label", "variable"},
}

# Bright-line classifier markers (HARD-RULE 2). Presence => forced speculative.
# These are intentionally conservative: anything that signals the symbol/target
# cannot be resolved to a literal within the chunk.
_DYNAMIC_MARKERS = [
    re.compile(r"\bCALL\b\s+[A-Za-z0-9-]+\s*$", re.IGNORECASE),      # CALL <data-name> (variable, not 'LITERAL')
    re.compile(r"\bCALL\b\s+(?!['\"])[A-Za-z0-9-]+\b", re.IGNORECASE),  # CALL identifier (no quote)
    re.compile(r"COPY\b.*\bREPLACING\b", re.IGNORECASE),             # COPY ... REPLACING (rename)
    re.compile(r"\bRCP\b", re.IGNORECASE),                            # DSX runtime column propagation
    re.compile(r"#\w+#"),                                              # DSX #PARAM# interpolation
    re.compile(r"\$\{[^}]+\}"),                                        # shell/ETL ${VAR}
    re.compile(r"\$\(\s*[^)]+\)"),                                     # shell $(...)
    re.compile(r"%[-#0-9.]*[sdix]"),                                  # printf-style %s/%d
    re.compile(r"\.format\s*\("),                                     # python .format(
    re.compile(r"\bf['\"]"),                                          # python f-string
    re.compile(r"\bCALL\b\s*@", re.IGNORECASE),                       # Pick CALL @var (indirect call)
    re.compile(r"\b(EXECUTE|PERFORM|CHAIN)\b[^\"']*[<{:]"),           # Pick EXECUTE/CHAIN with an interpolated sentence
]


def _looks_dynamic(snippet: str) -> bool:
    if not snippet:
        return False
    for pat in _DYNAMIC_MARKERS:
        if pat.search(snippet):
            return True
    return False


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def enforce_kind_enum(symbols: list, fmt: str) -> None:
    """Raise ValueError if any symbol.kind is outside the closed set for `fmt`."""
    allowed = KIND_BY_FORMAT.get(fmt)
    if allowed is None:
        raise ValueError(f"unknown format: {fmt!r} (expected one of {sorted(KIND_BY_FORMAT)})")
    for sym in symbols:
        k = sym.get("kind")
        if k not in allowed:
            raise ValueError(
                f"symbol {sym.get('symbol_id')!r} has kind {k!r} not in the {fmt} closed set {sorted(allowed)}"
            )


def apply_confidence_classifier(occurrences: list) -> int:
    """Force speculative on any occurrence whose evidence looks dynamic
    (HARD-RULE 2). Returns the number of forced downgrades."""
    forced = 0
    for occ in occurrences:
        if occ.get("confidence") == "speculative":
            continue
        if _looks_dynamic(occ.get("evidence_snippet", "")):
            occ["confidence"] = "speculative"
            occ["confidence_reason"] = "dynamic_or_interpolated_evidence"
            forced += 1
    return forced


def build_refs_by_path(symbols: list, occurrences: list, source_path: str) -> dict:
    """Map source_path -> sorted list of symbol_ids DEFINED in this artifact.
    Symbol IDs remain path-independent; this is the reverse index."""
    defined = set()
    for occ in occurrences:
        if occ.get("role") == "definition":
            defined.add(occ.get("symbol_id"))
    # Symbols with a definition occurrence; fall back to all symbols if none have
    # an explicit definition occurrence (still want them path-locatable).
    if not defined:
        defined = {s.get("symbol_id") for s in symbols}
    return {source_path: sorted(sid for sid in defined if sid)}


def emit_index(
    summary: dict,
    *,
    content_sha256: str,
    fmt: str,
    source_path: str,
    line_count: int,
    model_id: str,
    prompt_hash: str,
    pipeline_fingerprint: str,
    size: int = 0,
    ingested_at: str = "SOURCE_DATE_EPOCH",
    extractor_version: str = "1.0.0",
    validate: bool = True,
) -> dict:
    """Assemble + (optionally) validate the code-index.v1 document."""
    symbols = [dict(s) for s in summary.get("symbols", [])]
    occurrences = [dict(o) for o in summary.get("occurrences", [])]
    relationships = [dict(r) for r in summary.get("relationships", [])]
    gaps = [dict(g) for g in summary.get("gaps", [])]

    # 2. Closed-set kind enforcement.
    enforce_kind_enum(symbols, fmt)

    # 3. Bright-line confidence classifier (defense-in-depth).
    apply_confidence_classifier(occurrences)

    # Stable ordering for determinism.
    symbols.sort(key=lambda s: (s.get("symbol_id", ""), s.get("kind", "")))
    occurrences.sort(key=lambda o: (
        (o.get("range") or {}).get("start_line", 0),
        (o.get("range") or {}).get("end_line", 0),
        o.get("symbol_id", ""), o.get("role", ""),
    ))
    relationships.sort(key=lambda r: (r.get("rel", ""), r.get("from_id", ""), r.get("to_id", "")))
    gaps.sort(key=lambda g: (g.get("line", 0), g.get("kind", ""), g.get("detail", "")))

    index = {
        "schema_version": "1.0.0",
        "extractor_id": "legacy-code-intel",
        "extractor_version": extractor_version,
        "artifact": {
            "content_sha256": content_sha256,
            "format": fmt,
            "source_path": source_path,
            "size": int(size),
            "line_count": int(line_count),
            "ingested_at": ingested_at,
            "model_id": model_id,
            "prompt_hash": prompt_hash,
            "pipeline_fingerprint": pipeline_fingerprint,
        },
        "symbols": symbols,
        "occurrences": occurrences,
        "relationships": relationships,
        "refs": {"by_path": build_refs_by_path(symbols, occurrences, source_path)},
        "gaps": gaps,
    }

    if validate:
        if not HAVE_JSONSCHEMA:
            raise ImportError("jsonschema not installed. Run `pip install jsonschema>=4.0.0`.")
        with SCHEMA_PATH.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        validator = Draft7Validator(schema)
        errors = sorted(validator.iter_errors(index), key=lambda e: list(e.path))
        if errors:
            msgs = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
            raise ValueError(f"code-index.v1 validation failed: {msgs}")

    return index


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("summary_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--content-sha256", required=True)
    parser.add_argument("--format", required=True, choices=["cobol", "dsx", "etl", "pick"])
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--line-count", type=int, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--prompt-hash", required=True)
    parser.add_argument("--pipeline-fingerprint", required=True)
    parser.add_argument("--size", type=int, default=0)
    parser.add_argument("--ingested-at", default="SOURCE_DATE_EPOCH")
    parser.add_argument("--source-date-epoch", action="store_true",
                        help="Force the deterministic ingested_at sentinel.")
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args(argv)

    if not args.summary_json.exists():
        print(f"ERROR: summary not found: {args.summary_json}", file=sys.stderr)
        return 1
    with args.summary_json.open("r", encoding="utf-8") as f:
        summary = json.load(f)

    ingested_at = "SOURCE_DATE_EPOCH" if args.source_date_epoch else args.ingested_at

    try:
        index = emit_index(
            summary,
            content_sha256=args.content_sha256, fmt=args.format, source_path=args.source_path,
            line_count=args.line_count, model_id=args.model_id, prompt_hash=args.prompt_hash,
            pipeline_fingerprint=args.pipeline_fingerprint, size=args.size,
            ingested_at=ingested_at, validate=not args.no_validate,
        )
    except (ValueError, ImportError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    atomic_write_json(args.output, index)
    print(json.dumps({
        "output_path": str(args.output),
        "symbols": len(index["symbols"]),
        "occurrences": len(index["occurrences"]),
        "relationships": len(index["relationships"]),
        "gaps": len(index["gaps"]),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
