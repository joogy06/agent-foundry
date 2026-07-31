#!/usr/bin/env python3
"""controlm_extract.py — deterministic Control-M scheduler extractor (WP-2).

Part of the ``mainframe-lineage-parsers`` skill (the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 — a *complement*, not a
replacement, of the LLM-as-parser family). This is the deterministic Control-M
Automation-API jobs-as-code extractor — a **structural twin of jcl_extract.py**:

    parse jobs-as-code JSON (stdlib ``json`` only)
        -> build ResolvedJob dataclasses
            -> emit the EXISTING ir.IR (no parallel IR)

It slots into ``run_lineage._extract_one`` (WP-3) with zero changes to
``graph_assemble.assemble`` or ``openlineage_emit`` (design §3).

This module is **pure stdlib** — NO LLM, NO ``sqlglot``/``networkx``, NO new pip
deps, NO network, NO shell, NO runtime pip install (design D1 / INV-1). The
deterministic engine has no LLM in the loop, ever (C2). Everything it emits flows
through :mod:`ir` and conforms to the frozen ``references/naming-contract.md``
(WP-1 amendment: §2a Control-M identity, §5 the four scheduler gaps, §6 the
case-sensitivity divergence).

The language here is model-neutral. The extractor runs the same way regardless of
which CLI host invokes the engine (Claude Code, Codex CLI, Copilot CLI,
Antigravity CLI).

------------------------------------------------------------------------------
Input shape (design §3)
------------------------------------------------------------------------------
Control-M Automation-API jobs-as-code JSON::

    { "<Folder>": { defaults.., "<JobName>": { "Type": "Job:Command", .. } } }

Detection is DEFENSIVE: any leaf object carrying a ``"Type"`` value starting
``"Job:"`` is a job; unknown keys are ignored, the parser never crashes. The
top-level object may carry one or more folders; a folder may carry ``Variables``
and other defaults alongside its jobs.

------------------------------------------------------------------------------
Job-type -> IR mapping (design §3 table)
------------------------------------------------------------------------------
  * ``Job:Command``        — ``Command`` argv[0] -> program node
                             ``mainframe://<program-id>`` (program-id = basename
                             of argv[0], extension stripped, UPPER-FOLDED — the
                             LOCKED stitch key that must collide with the COBOL
                             upper-folded program-id). Scheduler->program bind =
                             ``kind=inferred`` (cross-artifact name bind).
  * ``Job:Script``         — ``FileName``+``FilePath`` -> script artifact; the
                             job->script edge is ``grounded`` when both literal.
  * ``Job:EmbeddedScript`` — inline ``Script`` body is OPAQUE -> job node only +
                             a diagnostic (NOT parsed — that is the LLM path).
  * ``Job:FileTransfer``   — ``FileTransfers[].Src``/``Dest`` -> read/write file
                             edges; a runtime-assigned watched name
                             (``FileWatcherOptions.AssignFileNameToVariable``) ->
                             speculative + ``runtime_path`` gap.
  * ``Job:Database:*``     — SQL + ``ConnectionProfile`` -> table edges only if
                             the SQL is literal AND the profile resolves via
                             ``--controlm-connection-profiles``; else speculative
                             + the right gap.
  * ``Job:Dummy``          — DAG node only (a scheduling placeholder).

Unknown ``Job:<X>`` types degrade to a bare scheduler job node (never crash).

------------------------------------------------------------------------------
Job->job DAG (design §3)
------------------------------------------------------------------------------
``eventsToAdd`` (Out) raised by job A and ``eventsToWaitFor`` (In) awaited by job
B are matched on the event-name string -> an A->B dependency edge, resolved
deterministically across the whole folder set. An awaited event with no in-scope
producer -> speculative edge + ``unresolved_event_dep`` gap (C3 — never invented).

------------------------------------------------------------------------------
%%-variable substitution (design §4)
------------------------------------------------------------------------------
``%%VAR`` references reuse the JCL ``&SYMBOL`` precedent: a variable that is
literal-in-document (declared under a folder/job ``Variables`` block) is
substituted deterministically; an unresolved one is left verbatim and forces
``speculative`` + an ``unresolved_variable`` gap (never invented — C3).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ------------------------------------------------------------------------------
# Path-load the sibling IR module — reuse the SHARED ``mlp_ir`` module object so
# the IR/gap nodes this extractor builds are the EXACT classes the assembler's
# ``_coerce_to_ir`` isinstance check expects (run_lineage.py header note). If the
# assembler/jcl already loaded it, reuse that; else load it here.
# ------------------------------------------------------------------------------
def _import_ir():
    name = "mlp_ir"
    if name in sys.modules:
        return sys.modules[name]
    target = Path(__file__).resolve().parent / "ir.py"
    spec = importlib.util.spec_from_file_location(name, target)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load ir.py from {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ir = _import_ir()


# ------------------------------------------------------------------------------
# Namespaces (naming-contract §2a / §3 / §4)
# ------------------------------------------------------------------------------
def job_namespace(folder: str) -> str:
    """``controlm://<folder>`` — CASE-SENSITIVE (naming-contract §2a / §6 rule 5
    EXCEPTION). The folder name is NOT upper-folded."""
    return f"controlm://{folder}"


def program_namespace(program_id: str) -> str:
    """``mainframe://<program-id>`` (program-id already UPPER-FOLDED — §3). This is
    the SAME namespace the COBOL extractor uses, so the scheduler->program edge
    collides onto the COBOL program node (the stitch)."""
    return f"mainframe://{program_id}"


# A Control-M %%-variable reference: ``%%VAR`` (letters/digits/_/-).
_CTM_VAR_RE = re.compile(r"%%[A-Za-z_][A-Za-z0-9_\-]*")


def has_unresolved_variable(text: str) -> bool:
    """True if ``text`` still contains an unresolved ``%%VAR`` after substitution."""
    return bool(_CTM_VAR_RE.search(text or ""))


def substitute_variables(text: str, variables: Dict[str, str]) -> str:
    """Substitute ``%%VAR`` references from ``variables`` (the JCL &SYMBOL
    precedent). A known variable is replaced deterministically; an unknown one is
    left verbatim (so :func:`has_unresolved_variable` can flag it -> the
    ``unresolved_variable`` gap). It is NEVER invented (C3).

    Control-M variable names are case-sensitive; lookup is exact. The map keys may
    be supplied with or without the ``%%`` prefix — both forms are accepted."""
    if not text:
        return text

    def _sub(m: "re.Match[str]") -> str:
        token = m.group(0)            # e.g. "%%HLQ"
        bare = token[2:]              # "HLQ"
        if token in variables:
            return variables[token]
        if bare in variables:
            return variables[bare]
        return token                  # unknown -> verbatim, not invented
    return _CTM_VAR_RE.sub(_sub, text)


# ------------------------------------------------------------------------------
# Program-id stitch rule (design §3, LOCKED)
# ------------------------------------------------------------------------------
def _argv0(command: str) -> str:
    """The first whitespace-delimited token of a Command string (argv[0]).

    Honours a leading quoted path (``"my prog.sh" -v`` -> ``my prog.sh``)."""
    s = (command or "").strip()
    if not s:
        return ""
    if s[0] in ("'", '"'):
        q = s[0]
        end = s.find(q, 1)
        if end > 0:
            return s[1:end]
    return s.split(None, 1)[0]


def program_id_from_command(command: str) -> str:
    """The LOCKED stitch key: program-id = basename of argv[0], extension
    stripped, UPPER-FOLDED. Must match the COBOL extractor's upper-folded
    PROGRAM-ID so the two nodes collide on dedupe (design §3)."""
    arg0 = _argv0(command)
    base = Path(arg0).name if arg0 else ""
    stem = base
    # Strip a single trailing extension (``PAYCALC.sh`` -> ``PAYCALC``); a name
    # with no dot is kept verbatim. Path.stem handles this deterministically.
    if "." in base:
        stem = Path(base).stem
    return stem.upper()


# ------------------------------------------------------------------------------
# Resolved-job model (after variable substitution) — twin of ResolvedStep
# ------------------------------------------------------------------------------
@dataclass
class ResolvedJob:
    """A Control-M job after %%-variable substitution.

    ``folder``/``name`` are CASE-PRESERVED (§2a). ``raw`` is the original job
    object. ``events_out``/``events_in`` are the resolved DAG event-name lists.
    ``variables`` is the merged folder+job Variables map in scope for this job."""

    folder: str
    name: str
    job_type: str
    raw: Dict[str, object]
    variables: Dict[str, str] = field(default_factory=dict)
    events_out: List[str] = field(default_factory=list)
    events_in: List[str] = field(default_factory=list)
    line: int = 1
    file: str = ""


# ------------------------------------------------------------------------------
# Variables block parsing (folder- and job-level)
# ------------------------------------------------------------------------------
def _parse_variables(container: Dict[str, object]) -> Dict[str, str]:
    """Parse a Control-M ``Variables`` block into a flat name->value map.

    Control-M jobs-as-code declares variables as a LIST of single-key objects:
    ``"Variables": [ {"%%HLQ": "PROD"}, {"%%ENV": "PRD"} ]``. We also accept a
    plain object form ``{"%%HLQ": "PROD"}`` defensively. Keys are kept verbatim
    (with their ``%%`` prefix if present) and also indexed bare for lookup."""
    out: Dict[str, str] = {}
    raw = container.get("Variables")
    items: List[dict] = []
    if isinstance(raw, list):
        items = [x for x in raw if isinstance(x, dict)]
    elif isinstance(raw, dict):
        items = [raw]
    for obj in items:
        for k, v in obj.items():
            if isinstance(v, (str, int, float)):
                out[str(k)] = str(v)
    return out


def _is_job(obj: object) -> bool:
    """Defensive job detection: a leaf object with a ``Type`` value starting
    ``Job:`` (design §3)."""
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("Type"), str)
        and obj["Type"].startswith("Job:")
    )


def _event_names(value: object) -> List[str]:
    """Normalise a Control-M events list into a sorted list of event-name strings.

    Accepts ``[{"Event": "ev-a"}, ..]`` (the jobs-as-code shape) or a plain
    ``["ev-a", ..]`` list defensively. Deterministic (sorted, deduped)."""
    names: List[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                ev = item.get("Event") or item.get("Name")
                if isinstance(ev, str) and ev:
                    names.append(ev)
            elif isinstance(item, str) and item:
                names.append(item)
    return sorted(set(names))


# ------------------------------------------------------------------------------
# Parse the whole document into ResolvedJob list (deterministic order)
# ------------------------------------------------------------------------------
def resolve_jobs(doc: Dict[str, object], *, file: str = "") -> List[ResolvedJob]:
    """Walk the jobs-as-code document and resolve every job.

    Folders are processed in sorted order; jobs within a folder in sorted order,
    so the slice is byte-identical on re-run regardless of dict-iteration order.
    Folder-level ``Variables`` are in scope for every job in the folder; a
    job-level ``Variables`` block (if any) overrides the folder one."""
    jobs: List[ResolvedJob] = []
    if not isinstance(doc, dict):
        return jobs
    for folder in sorted(doc.keys()):
        fobj = doc[folder]
        if not isinstance(fobj, dict):
            continue
        folder_vars = _parse_variables(fobj)
        for jobname in sorted(fobj.keys()):
            jobj = fobj[jobname]
            if not _is_job(jobj):
                continue
            job_vars = dict(folder_vars)
            job_vars.update(_parse_variables(jobj))
            events_out = _event_names(jobj.get("eventsToAdd"))
            events_in = _event_names(jobj.get("eventsToWaitFor"))
            jobs.append(
                ResolvedJob(
                    folder=folder,
                    name=jobname,
                    job_type=str(jobj.get("Type", "")),
                    raw=jobj,
                    variables=job_vars,
                    events_out=events_out,
                    events_in=events_in,
                    file=file,
                )
            )
    return jobs


# ------------------------------------------------------------------------------
# File-edge namespace (Control-M FileTransfer / Script artifacts)
# ------------------------------------------------------------------------------
FILE_NAMESPACE = "controlm://file"


def _resolve_path(raw: str, variables: Dict[str, str]) -> Tuple[str, bool]:
    """Substitute %%-vars in a path. Returns ``(resolved, is_runtime)`` where
    ``is_runtime`` is True when the path still holds an unresolved %%-var after
    substitution (a runtime / interpolated path -> speculative + runtime_path)."""
    sub = substitute_variables(raw or "", variables)
    return sub, has_unresolved_variable(sub)


def _join_path(filepath: str, filename: str) -> str:
    """Join a Control-M FilePath + FileName deterministically (no OS dependence —
    always forward-slash, no normalisation that could collapse a runtime token)."""
    fp = (filepath or "").rstrip("/")
    fn = filename or ""
    if fp and fn:
        return f"{fp}/{fn}"
    return fp or fn


# ------------------------------------------------------------------------------
# IR emission per job type (design §3 table)
# ------------------------------------------------------------------------------
def _scheduler_job_node(job: ResolvedJob) -> "ir.Node":
    """The scheduler job node ``controlm://<folder>`` / ``<jobname>`` (CASE-
    PRESERVED, §2a). node_type=job."""
    return ir.make_node(job_namespace(job.folder), job.name, node_type="job",
                        facets={"controlm_type": job.job_type})


def _emit_command(job: ResolvedJob, out: "ir.IR") -> None:
    """``Job:Command`` -> the scheduler->program stitch edge."""
    sched_node = _scheduler_job_node(job)
    out.add_node(sched_node)
    raw_cmd = job.raw.get("Command")
    if not isinstance(raw_cmd, str) or not raw_cmd.strip():
        return
    command = substitute_variables(raw_cmd, job.variables)
    span = ir.SourceSpan(job.file, job.line)

    if has_unresolved_variable(command):
        # The program could not be resolved (a %%-var in argv[0] region) -> a
        # speculative bind + an unresolved_variable gap (C3 — never invented).
        out.add_gap(ir.gap_unresolved_variable(command, source_span=span))
        # Still record an honest speculative bind so the attempted link is visible.
        unresolved_pgm = ir.make_node(
            program_namespace("<unresolved_program>"), "<unresolved_program>",
            node_type="job", facets={"raw_command": command},
        )
        prov = ir.Provenance(
            parser="controlm", engine="stdlib", rule_id="controlm.command.unresolved_variable",
            source_spans=[span], dialect="controlm",
            unresolved_deps=[command],
            raw_tokens={"raw_command": command},
        )
        out.add_edge(ir.make_edge(
            unresolved_pgm, sched_node, kind="unresolved", confidence="speculative",
            symbolic=True, provenance=prov,
        ))
        return

    program_id = program_id_from_command(command)
    if not program_id:
        return
    pgm_node = ir.make_node(program_namespace(program_id), program_id, node_type="job")
    prov = ir.Provenance(
        parser="controlm", engine="stdlib", rule_id="controlm.command.program_bind",
        source_spans=[span], dialect="controlm",
        raw_tokens={"raw_command": command, "program_id": program_id},
    )
    # Cross-artifact name bind: inferred-kind, ceiling inferred (never grounded —
    # same discipline as the JCL->COBOL DDNAME stitch). The program node is the
    # edge SOURCE so it stitches onto the COBOL program job node.
    out.add_edge(ir.make_edge(
        pgm_node, sched_node, kind="inferred", confidence="inferred",
        provenance=prov,
    ))


def _emit_script(job: ResolvedJob, out: "ir.IR") -> None:
    """``Job:Script`` -> a job->script-artifact edge (grounded when both literal)."""
    sched_node = _scheduler_job_node(job)
    out.add_node(sched_node)
    span = ir.SourceSpan(job.file, job.line)
    filename = job.raw.get("FileName")
    filepath = job.raw.get("FilePath")
    fn = filename if isinstance(filename, str) else ""
    fp = filepath if isinstance(filepath, str) else ""
    joined_raw = _join_path(fp, fn)
    if not joined_raw:
        return
    resolved, is_runtime = _resolve_path(joined_raw, job.variables)
    if is_runtime:
        out.add_gap(ir.gap_runtime_path(resolved, source_span=span))
        script_node = ir.make_node(FILE_NAMESPACE, "<runtime_path>",
                                   facets={"raw_path": resolved})
        prov = ir.Provenance(
            parser="controlm", engine="stdlib", rule_id="controlm.script.runtime_path",
            source_spans=[span], dialect="controlm",
            unresolved_deps=[resolved], raw_tokens={"raw_path": resolved},
        )
        out.add_edge(ir.make_edge(
            sched_node, script_node, kind="unresolved", confidence="speculative",
            symbolic=True, provenance=prov,
        ))
        return
    script_node = ir.make_node(FILE_NAMESPACE, resolved, facets={"raw_path": resolved})
    prov = ir.Provenance(
        parser="controlm", engine="stdlib", rule_id="controlm.script.artifact",
        source_spans=[span], dialect="controlm",
        raw_tokens={"raw_path": resolved},
    )
    # Both FileName + FilePath literal -> grounded direct edge.
    out.add_edge(ir.make_edge(
        sched_node, script_node, kind="direct", confidence="grounded",
        literal=True, provenance=prov,
    ))


def _emit_embedded_script(job: ResolvedJob, out: "ir.IR") -> None:
    """``Job:EmbeddedScript`` -> job node only; the inline body is OPAQUE (the LLM
    path). We record a diagnostic facet so the opacity is visible, never parsed."""
    sched_node = _scheduler_job_node(job)
    sched_node.facets["embedded_script"] = "opaque (LLM path — not parsed by the deterministic engine)"
    out.add_node(sched_node)


def _emit_file_transfer(job: ResolvedJob, out: "ir.IR") -> None:
    """``Job:FileTransfer`` -> Src->job (read) + job->Dest (write) file edges.

    A runtime-assigned watched name (FileWatcherOptions.AssignFileNameToVariable)
    -> speculative + runtime_path gap on the affected side."""
    sched_node = _scheduler_job_node(job)
    out.add_node(sched_node)
    span = ir.SourceSpan(job.file, job.line)
    transfers = job.raw.get("FileTransfers")
    if not isinstance(transfers, list):
        return
    # Detect a runtime-assigned watched filename (applies to the Src side).
    fw = job.raw.get("FileWatcherOptions")
    watched_runtime = bool(
        isinstance(fw, dict) and fw.get("AssignFileNameToVariable")
    )
    for t in transfers:
        if not isinstance(t, dict):
            continue
        src_raw = t.get("Src")
        dst_raw = t.get("Dest")
        if isinstance(src_raw, str) and src_raw:
            _emit_transfer_edge(
                out, sched_node, src_raw, job.variables, span,
                direction="read", force_runtime=watched_runtime,
            )
        if isinstance(dst_raw, str) and dst_raw:
            _emit_transfer_edge(
                out, sched_node, dst_raw, job.variables, span,
                direction="write", force_runtime=False,
            )


def _emit_transfer_edge(out, sched_node, raw_path, variables, span, *,
                        direction: str, force_runtime: bool) -> None:
    resolved, is_runtime = _resolve_path(raw_path, variables)
    runtime = is_runtime or force_runtime
    if runtime:
        out.add_gap(ir.gap_runtime_path(resolved, source_span=span))
        file_node = ir.make_node(FILE_NAMESPACE, "<runtime_path>",
                                 facets={"raw_path": resolved})
        prov = ir.Provenance(
            parser="controlm", engine="stdlib",
            rule_id=f"controlm.filetransfer.{direction}.runtime_path",
            source_spans=[span], dialect="controlm",
            unresolved_deps=[resolved], raw_tokens={"raw_path": resolved},
        )
        if direction == "read":
            edge = ir.make_edge(file_node, sched_node, kind="unresolved",
                                confidence="speculative", symbolic=True, provenance=prov)
        else:
            edge = ir.make_edge(sched_node, file_node, kind="unresolved",
                                confidence="speculative", symbolic=True, provenance=prov)
        out.add_edge(edge)
        return
    file_node = ir.make_node(FILE_NAMESPACE, resolved, facets={"raw_path": resolved})
    prov = ir.Provenance(
        parser="controlm", engine="stdlib",
        rule_id=f"controlm.filetransfer.{direction}",
        source_spans=[span], dialect="controlm",
        raw_tokens={"raw_path": resolved},
    )
    if direction == "read":
        edge = ir.make_edge(file_node, sched_node, kind="direct", confidence="grounded",
                            literal=True, provenance=prov)
    else:
        edge = ir.make_edge(sched_node, file_node, kind="direct", confidence="grounded",
                            literal=True, provenance=prov)
    out.add_edge(edge)


# DB2-style table node namespace for Control-M database jobs (placeholder-honest,
# mirroring naming-contract §1: when the connection profile is unknown the
# host/port/db are placeholders).
def _db2_table_node(schema: Optional[str], table: str, *, host=None, port=None, db=None):
    h = host or "<host>"
    p = port or "<port>"
    d = db or "<db>"
    s = schema or "<schema>"
    ns = f"db2://{h}:{p}/{d}"
    name = f"{s}.{table.upper()}"
    return ir.make_node(ns, name, facets={"raw_table": table})


_SQL_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_$#@]*(?:\.[A-Za-z_][A-Za-z0-9_$#@]*)?)",
    re.IGNORECASE,
)


def _emit_database(job: ResolvedJob, out: "ir.IR",
                   connection_profiles: Dict[str, dict]) -> None:
    """``Job:Database:*`` -> DB2-style table edges ONLY when the SQL is literal AND
    the ConnectionProfile resolves via --controlm-connection-profiles; else
    speculative + the right gap (unresolved_connection / unresolved_variable)."""
    sched_node = _scheduler_job_node(job)
    out.add_node(sched_node)
    span = ir.SourceSpan(job.file, job.line)

    profile_name = job.raw.get("ConnectionProfile")
    profile = None
    if isinstance(profile_name, str) and profile_name:
        profile = connection_profiles.get(profile_name)
        if profile is None:
            out.add_gap(ir.gap_unresolved_connection(profile_name, source_span=span))

    # SQL may live under Statement / SQLScript / Text (defensive).
    raw_sql = (
        job.raw.get("Statement")
        or job.raw.get("SQLScript")
        or job.raw.get("Text")
        or job.raw.get("Query")
    )
    if not isinstance(raw_sql, str) or not raw_sql.strip():
        return
    sql = substitute_variables(raw_sql, job.variables)

    if has_unresolved_variable(sql):
        out.add_gap(ir.gap_unresolved_variable(sql, source_span=span))
        sql_literal = False
    else:
        sql_literal = True

    resolved_profile = profile is not None
    host = port = db = schema = None
    if resolved_profile:
        host = profile.get("host")
        port = str(profile["port"]) if profile.get("port") is not None else None
        db = profile.get("db")
        schema = profile.get("schema")

    for raw_table in sorted(set(m.group(1) for m in _SQL_TABLE_RE.finditer(sql))):
        if "." in raw_table:
            tschema, _, tname = raw_table.partition(".")
        else:
            tschema, tname = None, raw_table
        eff_schema = tschema or schema
        table_node = _db2_table_node(eff_schema, tname, host=host, port=port, db=db)
        prov = ir.Provenance(
            parser="controlm", engine="stdlib", rule_id="controlm.database.table",
            source_spans=[span], dialect="db2-sql",
            raw_tokens={"raw_table": raw_table,
                        "connection_profile": profile_name if isinstance(profile_name, str) else ""},
        )
        if sql_literal and resolved_profile:
            # Literal table + resolved connection -> grounded direct edge.
            out.add_edge(ir.make_edge(
                table_node, sched_node, kind="direct", confidence="grounded",
                literal=True, provenance=prov,
            ))
        else:
            # Interpolated SQL or unresolved connection -> speculative (C3 honesty).
            prov.notes.append("controlm database edge speculative: "
                              + ("unresolved connection; " if not resolved_profile else "")
                              + ("interpolated SQL" if not sql_literal else ""))
            out.add_edge(ir.make_edge(
                table_node, sched_node, kind="unresolved", confidence="speculative",
                symbolic=not sql_literal, provenance=prov,
            ))


def _emit_dummy(job: ResolvedJob, out: "ir.IR") -> None:
    """``Job:Dummy`` -> a DAG node only (a scheduling placeholder, no data edges)."""
    sched_node = _scheduler_job_node(job)
    out.add_node(sched_node)


def _emit_unknown(job: ResolvedJob, out: "ir.IR") -> None:
    """Unknown ``Job:<X>`` -> a bare scheduler node (never crash). Diagnostic facet."""
    sched_node = _scheduler_job_node(job)
    sched_node.facets["unmapped_type"] = job.job_type
    out.add_node(sched_node)


# ------------------------------------------------------------------------------
# Job->job DAG (eventsToAdd / eventsToWaitFor)
# ------------------------------------------------------------------------------
def _emit_event_dag(jobs: List[ResolvedJob], out: "ir.IR") -> None:
    """Match eventsToAdd (Out) producers to eventsToWaitFor (In) consumers across
    the folder set -> A->B dependency edges. An awaited event with no in-scope
    producer -> speculative self-edge marker + unresolved_event_dep gap (C3)."""
    # Index producers by event name -> sorted list of producer jobs.
    producers: Dict[str, List[ResolvedJob]] = {}
    for j in jobs:
        for ev in j.events_out:
            producers.setdefault(ev, []).append(j)
    for ev in producers:
        producers[ev].sort(key=lambda j: (j.folder, j.name))

    for consumer in sorted(jobs, key=lambda j: (j.folder, j.name)):
        consumer_node = _scheduler_job_node(consumer)
        for ev in consumer.events_in:
            span = ir.SourceSpan(consumer.file, consumer.line)
            prods = producers.get(ev, [])
            if not prods:
                # No in-scope producer -> unresolved_event_dep gap + a speculative
                # marker so the awaited dependency is visible (C3 — never invented).
                out.add_gap(ir.gap_unresolved_event_dep(ev, source_span=span))
                pseudo = ir.make_node("controlm://event", ev,
                                      facets={"raw_event": ev})
                prov = ir.Provenance(
                    parser="controlm", engine="stdlib",
                    rule_id="controlm.dag.unresolved_event_dep",
                    source_spans=[span], dialect="controlm",
                    unresolved_deps=[ev], raw_tokens={"raw_event": ev},
                )
                out.add_edge(ir.make_edge(
                    pseudo, consumer_node, kind="unresolved", confidence="speculative",
                    symbolic=True, provenance=prov,
                ))
                continue
            for producer in prods:
                if producer.folder == consumer.folder and producer.name == consumer.name:
                    continue  # self-trigger — not a DAG edge
                producer_node = _scheduler_job_node(producer)
                prov = ir.Provenance(
                    parser="controlm", engine="stdlib",
                    rule_id="controlm.dag.event_dependency",
                    source_spans=[span], dialect="controlm",
                    raw_tokens={"raw_event": ev},
                    notes=[f"event dependency on {ev}"],
                )
                # Producer -> consumer scheduling dependency. A resolved in-scope
                # match is a deterministic cross-job bind -> inferred (cross-artifact
                # name bind discipline), ceiling inferred.
                out.add_edge(ir.make_edge(
                    producer_node, consumer_node, kind="inferred", confidence="inferred",
                    provenance=prov,
                ))


# ------------------------------------------------------------------------------
# Public entry points
# ------------------------------------------------------------------------------
_DISPATCH = {
    "Job:Command": _emit_command,
    "Job:Script": _emit_script,
    "Job:EmbeddedScript": _emit_embedded_script,
    "Job:FileTransfer": _emit_file_transfer,
    "Job:Dummy": _emit_dummy,
}


def extract_controlm(
    text: str,
    *,
    file: str = "",
    connection_profiles: Optional[Dict[str, dict]] = None,
    on_violation: str = "coerce",
) -> "ir.IR":
    """Extract lineage IR from a Control-M jobs-as-code JSON document (the WP-2
    public entry point). Parses with stdlib ``json`` only; emits the EXISTING
    ir.IR. Returns a canonical-sorted + deduped slice (byte-identical on re-run).

    A malformed JSON document raises ``json.JSONDecodeError`` (the CLI maps it to a
    fatal exit); a well-formed document with unknown keys never crashes."""
    profiles = dict(connection_profiles or {})
    out = ir.IR()
    try:
        doc = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        raise
    jobs = resolve_jobs(doc, file=file)

    for job in jobs:
        handler = _DISPATCH.get(job.job_type)
        if handler is not None:
            handler(job, out)
        elif job.job_type.startswith("Job:Database"):
            _emit_database(job, out, profiles)
        else:
            _emit_unknown(job, out)

    _emit_event_dag(jobs, out)
    _canonical_sort_dedupe(out)
    return out


def extract_controlm_file(
    path: str,
    *,
    connection_profiles: Optional[Dict[str, dict]] = None,
    on_violation: str = "coerce",
) -> "ir.IR":
    """Read a Control-M jobs-as-code JSON file and extract its IR. Read-only;
    deterministic."""
    p = Path(path)
    raw_bytes = p.read_bytes()  # RAW on-disk bytes, PRE-substitution (INV-6)
    text = raw_bytes.decode("utf-8", errors="replace")
    out = extract_controlm(text, file=str(p), connection_profiles=connection_profiles,
                           on_violation=on_violation)
    ir.stamp_content_sha256(out, ir.content_sha256_of_bytes(raw_bytes), source_file=str(p))
    return out


# ------------------------------------------------------------------------------
# Canonical sort + dedupe (mirrors jcl_extract._canonical_sort_dedupe)
# ------------------------------------------------------------------------------
def _canonical_sort_dedupe(out: "ir.IR") -> None:
    """In-place canonical sort + dedupe of the IR's edges by canonical edge key
    (naming-contract §6 rule 2-4); gap + standalone nodes deduped + sorted; all
    deterministic so the slice is byte-identical in isolation."""
    by_key: Dict[Tuple[str, str, str], "ir.Edge"] = {}
    for e in out.edges:
        k = e.canonical_key
        if k in by_key:
            by_key[k].provenance.merge_from(e.provenance)
        else:
            by_key[k] = e
    out.edges = [by_key[k] for k in sorted(by_key)]

    # Dedupe + sort gap nodes (by type + raw evidence — the Control-M raw_* facets).
    def _gap_key(g: "ir.GapNode") -> Tuple[str, str]:
        raw = (
            g.facets.get("raw_variable")
            or g.facets.get("raw_connection_profile")
            or g.facets.get("raw_path")
            or g.facets.get("raw_event")
            or ""
        )
        return (g.gap_type, raw)

    seen_gaps: Dict[Tuple[str, str], "ir.GapNode"] = {}
    for g in out.gaps:
        seen_gaps.setdefault(_gap_key(g), g)
    out.gaps = [seen_gaps[k] for k in sorted(seen_gaps)]

    # Dedupe standalone nodes by node_id, sorted by (namespace, name).
    seen_nodes: Dict[str, "ir.Node"] = {}
    for n in out.nodes:
        seen_nodes.setdefault(n.node_id, n)
    out.nodes = [
        seen_nodes[nid]
        for nid in sorted(seen_nodes, key=lambda x: (seen_nodes[x].namespace, seen_nodes[x].name))
    ]


__all__ = [
    "job_namespace",
    "program_namespace",
    "FILE_NAMESPACE",
    "has_unresolved_variable",
    "substitute_variables",
    "program_id_from_command",
    "ResolvedJob",
    "resolve_jobs",
    "extract_controlm",
    "extract_controlm_file",
]
