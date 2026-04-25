#!/usr/bin/env python3
"""uri.py -- 6-scheme custom URI resolver with immutable-UUID identity semantics.

Implements the URI resolver specified in S028 ecosystem-keystone design
section 5.1 + section 5.2 (D6 MODIFIED + D17 NEW). Six schemes, hard-fail on
ambiguous/expired, alias-chain walk over
`.design-ledger/entity-lifecycle/<uuid>.history.yaml`.

Public API (contract-map `uri-resolver` component):

    resolve(uri, project_root, *, allow_expired=False) -> ResolvedEntity
    exists(uri, project_root) -> bool
    to_uri(kind, id, fragment=None) -> str

    ResolvedEntity (frozen dataclass)

    UriError (base)
      - UriFormatError
      - UriAmbiguousError
      - UriExpiredError
      - UriSchemaError
      - UriNotFoundError

Schemes:
    capability://<component_id>.<capability_id>
    skeleton://<screen>#<element_id>.<event>
    flow://<flow_id>
    wire://<symbol_path>
    token://<dotted_token_path>
    component://<component_id>

Design references:
    docs/plans/2026-04-23-ecosystem-keystone-design.md section 5.1, 5.2, 6.1
    progress/contract-map.yaml  -- uri-resolver component block
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed. uri.py requires pyyaml.\n")
    sys.exit(3)


# ---------------------------------------------------------------------------
# URI grammar + ID discipline
# ---------------------------------------------------------------------------

URI_RE = re.compile(r"^(?P<scheme>[a-z]+)://(?P<body>[^#]+)(?:#(?P<frag>.+))?$")

# Element-ID discipline: each dot-segment must be a safe slug; no slashes allowed.
_ID_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

ENTITY_LIFECYCLE_SUBDIR = ".design-ledger/entity-lifecycle"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UriError(Exception):
    """Base class for all URI resolution errors."""


class UriFormatError(UriError):
    """URI does not match required grammar (missing scheme/body, bad id chars, etc.)."""


class UriAmbiguousError(UriError):
    """URI matches more than one candidate (e.g. active URI AND retired alias)."""


class UriExpiredError(UriError):
    """URI matches a RETIRED entity with no successor; retry with allow_expired=True
    for historical queries."""


class UriSchemaError(UriError):
    """Target ledger was unreadable or failed schema validation."""


class UriNotFoundError(UriError):
    """URI syntactically valid but no matching entity in any ledger."""


# ---------------------------------------------------------------------------
# ResolvedEntity record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedEntity:
    uri: str
    scheme: str
    ledger_path: Path
    jsonpointer: str
    node: Any
    schema_name: str
    valid: bool
    errors: tuple[str, ...] = ()
    entity_uuid: str | None = None
    resolution_chain: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# YAML / JSON loaders
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    try:
        text = path.read_text()
    except OSError as e:
        raise UriSchemaError(f"cannot read {path}: {e}") from e
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise UriSchemaError(f"yaml parse error in {path}: {e}") from e


def _load_json(path: Path) -> Any:
    try:
        text = path.read_text()
    except OSError as e:
        raise UriSchemaError(f"cannot read {path}: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise UriSchemaError(f"json parse error in {path}: {e}") from e


# ---------------------------------------------------------------------------
# Scheme converters
# ---------------------------------------------------------------------------


def _validate_segments(segments: list[str], uri: str) -> None:
    for seg in segments:
        if not _ID_SEGMENT_RE.match(seg):
            raise UriFormatError(
                f"invalid id segment {seg!r} in {uri!r}: "
                f"must match {_ID_SEGMENT_RE.pattern}"
            )


def _capability_convert(body: str, frag: str | None, uri: str) -> tuple[Path, str]:
    if frag is not None:
        raise UriFormatError(f"capability URIs do not take a fragment: {uri!r}")
    segments = body.split(".")
    if len(segments) != 2:
        raise UriFormatError(
            f"capability URI body must be <component>.<capability>; got {body!r}"
        )
    _validate_segments(segments, uri)
    component_id, capability_id = segments
    ledger_path = Path("progress/contract-map.yaml")
    jsonpointer = f"/components/{component_id}/capabilities/{capability_id}"
    return ledger_path, jsonpointer


def _skeleton_convert(body: str, frag: str | None, uri: str) -> tuple[Path, str]:
    if frag is None:
        raise UriFormatError(f"skeleton URIs require a fragment: {uri!r}")
    screen_segments = body.split(".")
    _validate_segments(screen_segments, uri)
    if "." not in frag:
        raise UriFormatError(
            f"skeleton fragment must be <element>.<event>; got {frag!r}"
        )
    element_id, event = frag.rsplit(".", 1)
    for seg in element_id.split("."):
        if not _ID_SEGMENT_RE.match(seg):
            raise UriFormatError(
                f"invalid element id segment {seg!r} in {uri!r}"
            )
    if not _ID_SEGMENT_RE.match(event):
        raise UriFormatError(f"invalid event name {event!r} in {uri!r}")
    ledger_path = Path(".design-ledger/skeletons") / f"{body}.yaml"
    jsonpointer = f"/elements/{element_id}/interactions/{event}"
    return ledger_path, jsonpointer


def _flow_convert(body: str, frag: str | None, uri: str) -> tuple[Path, str]:
    if frag is not None:
        raise UriFormatError(f"flow URIs do not take a fragment: {uri!r}")
    segments = body.split(".")
    _validate_segments(segments, uri)
    ledger_path = Path("progress/flows.yaml")
    jsonpointer = f"/flows/{body}"
    return ledger_path, jsonpointer


def _wire_convert(body: str, frag: str | None, uri: str) -> tuple[Path, str]:
    if frag is not None:
        raise UriFormatError(f"wire URIs do not take a fragment: {uri!r}")
    segments = body.split(".")
    _validate_segments(segments, uri)
    ledger_path = Path(".wiring/latest.json")
    jsonpointer = f"/symbol_index/{body}"
    return ledger_path, jsonpointer


def _token_convert(body: str, frag: str | None, uri: str) -> tuple[Path, str]:
    if frag is not None:
        raise UriFormatError(f"token URIs do not take a fragment: {uri!r}")
    segments = body.split(".")
    _validate_segments(segments, uri)
    ledger_path = Path(".design-ledger/skeletons/index.yaml")
    jsonpointer = "/tokens/" + "/".join(segments)
    return ledger_path, jsonpointer


def _component_convert(body: str, frag: str | None, uri: str) -> tuple[Path, str]:
    if frag is not None:
        raise UriFormatError(f"component URIs do not take a fragment: {uri!r}")
    segments = body.split(".")
    if len(segments) != 1:
        raise UriFormatError(f"component URI body must be <id>; got {body!r}")
    _validate_segments(segments, uri)
    ledger_path = Path(".design-ledger/skeletons/index.yaml")
    jsonpointer = f"/components/{body}"
    return ledger_path, jsonpointer


# ---------------------------------------------------------------------------
# Scheme registry: (schema_name, converter_fn, loader_fn)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, tuple[str, Callable[[str, str | None, str], tuple[Path, str]],
                           Callable[[Path], Any]]] = {
    "capability": ("contract-map.v1", _capability_convert, _load_yaml),
    "skeleton":   ("design-skeleton.v1", _skeleton_convert, _load_yaml),
    "flow":       ("flows.v1", _flow_convert, _load_yaml),
    "wire":       ("wiring-snapshot.v1", _wire_convert, _load_json),
    "token":      ("design-skeleton-index.v1", _token_convert, _load_yaml),
    "component":  ("design-skeleton-index.v1", _component_convert, _load_yaml),
}


# ---------------------------------------------------------------------------
# Per-scheme node lookup
# ---------------------------------------------------------------------------


def _lookup_capability(doc: Any, component_id: str, capability_id: str) -> Any:
    if not isinstance(doc, dict):
        return None
    for comp in doc.get("components", []) or []:
        if isinstance(comp, dict) and comp.get("id") == component_id:
            caps = comp.get("capabilities", {})
            if isinstance(caps, dict) and capability_id in caps:
                return caps[capability_id]
            return None
    return None


def _lookup_skeleton_interaction(doc: Any, element_id: str, event: str) -> Any:
    if not isinstance(doc, dict):
        return None
    elements = doc.get("elements", {})
    if not isinstance(elements, dict):
        return None
    element = elements.get(element_id)
    if not isinstance(element, dict):
        return None
    interactions = element.get("interactions", []) or []
    for inter in interactions:
        if isinstance(inter, dict) and inter.get("event") == event:
            return inter
    return None


def _lookup_flow(doc: Any, flow_id: str) -> Any:
    if not isinstance(doc, dict):
        return None
    flows = doc.get("flows", {})
    if isinstance(flows, dict):
        return flows.get(flow_id)
    return None


def _lookup_wire(doc: Any, symbol: str) -> Any:
    if not isinstance(doc, dict):
        return None
    idx = doc.get("symbol_index", {})
    if isinstance(idx, dict):
        return idx.get(symbol)
    return None


def _lookup_token(doc: Any, segments: list[str]) -> Any:
    if not isinstance(doc, dict):
        return None
    node: Any = doc.get("tokens")
    for seg in segments:
        if not isinstance(node, dict):
            return None
        node = node.get(seg)
        if node is None:
            return None
    return node


def _lookup_component(doc: Any, component_id: str) -> Any:
    if not isinstance(doc, dict):
        return None
    comps = doc.get("components")
    if isinstance(comps, dict):
        return comps.get(component_id)
    return None


def _extract_entity_uuid(node: Any) -> str | None:
    if isinstance(node, dict):
        val = node.get("entity_uuid")
        if isinstance(val, str):
            return val
    return None


# ---------------------------------------------------------------------------
# Entity-lifecycle / alias-chain walk
# ---------------------------------------------------------------------------


def _load_lifecycle_histories(project_root: Path) -> list[dict]:
    """Load every <uuid>.history.yaml file under .design-ledger/entity-lifecycle/.

    Returns a list of history documents (possibly empty). Never raises on
    individual file errors -- a malformed history is skipped with a stderr
    warning.
    """
    histories: list[dict] = []
    hist_dir = project_root / ENTITY_LIFECYCLE_SUBDIR
    if not hist_dir.is_dir():
        return histories
    for path in sorted(hist_dir.glob("*.history.yaml")):
        try:
            text = path.read_text()
            doc = yaml.safe_load(text)
        except (OSError, yaml.YAMLError) as e:
            sys.stderr.write(f"uri.py: skipping unreadable history {path}: {e}\n")
            continue
        if isinstance(doc, dict):
            histories.append(doc)
    return histories


def _collect_alias_candidates(uri: str, histories: list[dict]) -> list[dict]:
    """Return every history that has `uri` as a `from_uri` in any rename event."""
    hits: list[dict] = []
    for hist in histories:
        events = hist.get("events", []) or []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("event") == "renamed" and ev.get("from_uri") == uri:
                hits.append(hist)
                break
    return hits


def _is_retired_no_successor(hist: dict) -> bool:
    current = hist.get("current", {}) or {}
    if current.get("status") != "retired":
        return False
    successors = current.get("successors") or []
    return len(successors) == 0


def _walk_alias_chain(start_uri: str, histories: list[dict]) -> tuple[str, tuple[str, ...]]:
    """Follow renamed events forward until we reach a terminal (non-alias) URI.

    Returns (current_uri, chain) where chain starts at start_uri and ends at the
    terminal URI. Does not check retired status -- caller inspects terminal
    history to decide allow_expired behavior.
    """
    chain: list[str] = [start_uri]
    visited: set[str] = {start_uri}
    current_uri = start_uri
    while True:
        next_uri: str | None = None
        for hist in histories:
            events = hist.get("events", []) or []
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                if ev.get("event") == "renamed" and ev.get("from_uri") == current_uri:
                    next_uri = ev.get("to_uri")
                    break
            if next_uri is not None:
                break
        if next_uri is None or next_uri in visited:
            break
        chain.append(next_uri)
        visited.add(next_uri)
        current_uri = next_uri
    return current_uri, tuple(chain)


def _history_for_terminal(terminal_uri: str, histories: list[dict]) -> dict | None:
    """Return the history whose current.final_uris or events[].initial_uri matches."""
    for hist in histories:
        current = hist.get("current", {}) or {}
        final_uris = current.get("final_uris") or []
        if terminal_uri in final_uris:
            return hist
        events = hist.get("events", []) or []
        for ev in events:
            if isinstance(ev, dict) and ev.get("event") == "created":
                if ev.get("initial_uri") == terminal_uri:
                    return hist
    return None


# ---------------------------------------------------------------------------
# Parser + dispatch
# ---------------------------------------------------------------------------


def _parse(uri: str) -> tuple[str, str, str | None]:
    m = URI_RE.match(uri)
    if not m:
        raise UriFormatError(f"invalid URI syntax: {uri!r}")
    scheme = m.group("scheme")
    body = m.group("body")
    frag = m.group("frag")
    if "/" in body:
        raise UriFormatError(f"forward slash not allowed in URI body: {uri!r}")
    return scheme, body, frag


def _lookup_node_for_scheme(scheme: str, body: str, frag: str | None, doc: Any) -> Any:
    if scheme == "capability":
        component_id, capability_id = body.split(".", 1)
        return _lookup_capability(doc, component_id, capability_id)
    if scheme == "skeleton":
        assert frag is not None
        element_id, event = frag.rsplit(".", 1)
        return _lookup_skeleton_interaction(doc, element_id, event)
    if scheme == "flow":
        return _lookup_flow(doc, body)
    if scheme == "wire":
        return _lookup_wire(doc, body)
    if scheme == "token":
        return _lookup_token(doc, body.split("."))
    if scheme == "component":
        return _lookup_component(doc, body)
    raise UriSchemaError(f"no lookup configured for scheme {scheme!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve(uri: str, project_root: Path, *, allow_expired: bool = False) -> ResolvedEntity:
    """Resolve a URI to a ResolvedEntity record.

    Raises:
        UriFormatError: URI grammar or id discipline failed.
        UriSchemaError: target ledger unreadable or unknown scheme.
        UriAmbiguousError: URI matches both an active entity AND a retired alias.
        UriExpiredError: URI matches a RETIRED entity without successor; retry
            with allow_expired=True for historical queries.
        UriNotFoundError: URI syntactically valid but no matching entity.
    """
    scheme, body, frag = _parse(uri)

    if scheme not in _REGISTRY:
        raise UriSchemaError(f"unknown URI scheme {scheme!r} in {uri!r}")

    schema_name, converter, loader = _REGISTRY[scheme]
    ledger_path, jsonpointer = converter(body, frag, uri)

    full_path = project_root / ledger_path
    active_node: Any = None
    if full_path.is_file():
        ledger_doc = loader(full_path)
        active_node = _lookup_node_for_scheme(scheme, body, frag, ledger_doc)

    histories = _load_lifecycle_histories(project_root)
    alias_hits = _collect_alias_candidates(uri, histories)

    # Ambiguity rule (D6 MODIFIED): URI resolves to an active entity AND also
    # appears as a from_uri in some history -- cannot guess.
    if active_node is not None and alias_hits:
        raise UriAmbiguousError(
            f"{uri!r} matches an active entity and also appears as a from_uri "
            f"in {len(alias_hits)} lifecycle history(ies); ambiguous. Rename "
            "the active entity or retire the alias to disambiguate."
        )

    if active_node is not None:
        entity_uuid = _extract_entity_uuid(active_node)
        return ResolvedEntity(
            uri=uri,
            scheme=scheme,
            ledger_path=ledger_path,
            jsonpointer=jsonpointer,
            node=active_node,
            schema_name=schema_name,
            valid=True,
            errors=(),
            entity_uuid=entity_uuid,
            resolution_chain=(),
        )

    # No active hit -- try alias chain.
    if alias_hits:
        if len(alias_hits) > 1:
            raise UriAmbiguousError(
                f"{uri!r} is a from_uri in {len(alias_hits)} distinct lifecycle "
                "histories; cannot choose a target."
            )
        source_hist = alias_hits[0]
        terminal_uri, chain = _walk_alias_chain(uri, histories)
        terminal_hist = _history_for_terminal(terminal_uri, histories) or source_hist

        if _is_retired_no_successor(terminal_hist) and not allow_expired:
            raise UriExpiredError(
                f"{uri!r} follows alias chain {list(chain)} to retired entity "
                f"{terminal_hist.get('entity_uuid')!r}; pass allow_expired=True "
                "for historical queries."
            )

        return _resolve_terminal(
            terminal_uri, project_root, terminal_hist, chain, allow_expired
        )

    # URI directly names a retired entity (created + retired, never renamed).
    direct_retired = None
    for hist in histories:
        for ev in hist.get("events", []) or []:
            if (
                isinstance(ev, dict)
                and ev.get("event") == "created"
                and ev.get("initial_uri") == uri
            ):
                current = hist.get("current", {}) or {}
                if current.get("status") == "retired":
                    direct_retired = hist
                    break
        if direct_retired is not None:
            break

    if direct_retired is not None:
        if not allow_expired:
            raise UriExpiredError(
                f"{uri!r} is a retired entity {direct_retired.get('entity_uuid')!r} "
                "with no successor; pass allow_expired=True for historical queries."
            )
        return ResolvedEntity(
            uri=uri,
            scheme=scheme,
            ledger_path=ledger_path,
            jsonpointer=jsonpointer,
            node=None,
            schema_name=schema_name,
            valid=False,
            errors=("retired entity; node not present in active ledger",),
            entity_uuid=direct_retired.get("entity_uuid"),
            resolution_chain=(uri,),
        )

    raise UriNotFoundError(
        f"{uri!r} did not resolve: no active entity in {ledger_path} and no "
        "alias history match."
    )


def _resolve_terminal(
    terminal_uri: str,
    project_root: Path,
    terminal_hist: dict,
    chain: tuple[str, ...],
    allow_expired: bool,
) -> ResolvedEntity:
    """Resolve a terminal URI reached via alias chain; preserves chain provenance."""
    scheme, body, frag = _parse(terminal_uri)
    if scheme not in _REGISTRY:
        raise UriSchemaError(
            f"alias chain terminal has unknown scheme: {terminal_uri!r}"
        )
    schema_name, converter, loader = _REGISTRY[scheme]
    ledger_path, jsonpointer = converter(body, frag, terminal_uri)

    full_path = project_root / ledger_path
    node: Any = None
    if full_path.is_file():
        doc = loader(full_path)
        node = _lookup_node_for_scheme(scheme, body, frag, doc)

    if node is None:
        if _is_retired_no_successor(terminal_hist) and not allow_expired:
            raise UriExpiredError(
                f"alias chain terminal {terminal_uri!r} is retired and absent "
                "from active ledger; pass allow_expired=True."
            )
        return ResolvedEntity(
            uri=terminal_uri,
            scheme=scheme,
            ledger_path=ledger_path,
            jsonpointer=jsonpointer,
            node=None,
            schema_name=schema_name,
            valid=False,
            errors=("alias chain terminal not present in active ledger",),
            entity_uuid=terminal_hist.get("entity_uuid"),
            resolution_chain=chain,
        )

    return ResolvedEntity(
        uri=terminal_uri,
        scheme=scheme,
        ledger_path=ledger_path,
        jsonpointer=jsonpointer,
        node=node,
        schema_name=schema_name,
        valid=True,
        errors=(),
        entity_uuid=_extract_entity_uuid(node) or terminal_hist.get("entity_uuid"),
        resolution_chain=chain,
    )


def exists(uri: str, project_root: Path) -> bool:
    """Return True iff `uri` resolves (active or alias-chain) without raising.

    UriExpiredError counts as 'does not exist' (consistent with default
    allow_expired=False behavior).
    """
    try:
        resolve(uri, project_root, allow_expired=False)
        return True
    except UriError:
        return False


def to_uri(kind: str, id: str, fragment: str | None = None) -> str:
    """Construct a URI from (kind, id, optional fragment).

    Validates scheme and each dot-segment of id (and fragment, if present).
    Pure string construction; no filesystem access.
    """
    if kind not in _REGISTRY:
        raise UriSchemaError(
            f"unknown kind {kind!r}; must be one of {sorted(_REGISTRY.keys())}"
        )
    for seg in id.split("."):
        if not _ID_SEGMENT_RE.match(seg):
            raise UriFormatError(f"invalid id segment {seg!r} in ({kind}, {id!r})")
    if fragment is not None:
        for seg in fragment.split("."):
            if not _ID_SEGMENT_RE.match(seg):
                raise UriFormatError(
                    f"invalid fragment segment {seg!r} in ({kind}, {id!r}, "
                    f"#{fragment})"
                )
        return f"{kind}://{id}#{fragment}"
    return f"{kind}://{id}"
