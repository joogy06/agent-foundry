#!/usr/bin/env python3
"""review_risk.py -- deterministic, model-free risk tagging for a change set.

S081 revision 4, stream A (design 2026-09-15 section 2.1, decision D22). Some
changes must not be reviewed cheaply. A light review buys a cheaper model; on a
change that moves a gate, a protected-role resolution, a secret path or a signed
contract, that saving is paid for out of the one review that mattered.

This module decides that mechanically, BEFORE any model is chosen: given the
paths (and optionally the symbols) a change touched, it returns the tags that
fired and the review size those tags imply.

WHY IT IS PURE
--------------
`assess()` is a function of its arguments and nothing else -- no git, no
network, no model, no filesystem, no clock. Two consequences, both deliberate:

  * it is callable on a list of strings with NO repo present, which is what
    makes it testable and what keeps a reviewer's own input off the disk;
  * it sits OUTSIDE the reviewers' trust boundary. A component that decides how
    carefully something is reviewed must not itself be steerable by the thing
    under review. Reading the repo would make it so.

The caller supplies the change set (from `git diff --name-only`, a plan's file
list, a dossier) and owns every side effect.

THE SIX FAMILIES (design section 2.1, verbatim)
-----------------------------------------------
  trust_boundary          trust boundary / protected-role resolution
  gates_and_verification  gates.py, audit_spawn, verification_arbiter_spawn, claims
  secrets_and_auth        secrets & auth
  quota_budget_registry   quota / budget / seat registry
  schemas_and_contracts   schemas & contracts
  governance_and_agents   CLAUDE.md / agents / hard-rules

A path may fire several families -- `seat_model.py` is both the protected-role
resolver and the seat registry -- and that is informative, not a bug. Tags are a
SET; every tag records WHAT matched and WHICH RULE matched it, so a report can
show a human why a review was promoted instead of asserting that it was.

THE PROMOTION CONTRACT
----------------------
Promotion is ONE-WAY and only UPWARD: light|medium -> complex. It never lowers a
declared size, and `size_source` is set to `risk` ONLY when the size actually
moved. A caller that already declared `complex` sees no change and no spurious
`size_source` rewrite, so a forge-declared or user-declared provenance survives
a call to this module unchanged.

`--user-request` (L7 rule 4) already forces TOP regardless of size, so there is
nothing left to promote: `user_request=True` returns the tags (still worth
reporting) with the size and provenance untouched. Resolving WHERE a size came
from in the first place is `seat_model`'s job (L7); this module only decides
whether risk moves it.

Consultancy seats use the DECLARED size and are never risk-promoted (design
section 2.1, final sentence) -- that is the CALLER's choice not to call this,
not a flag here, because a module that sometimes ignores its own verdict is one
refactor away from ignoring it everywhere.

THREE JUDGEMENT CALLS, RECORDED
-------------------------------
1. A path under a `fixtures/` directory NEVER promotes. Fixture data does not
   execute, and a fixture named `contract-map.yaml` is a test input, not a
   signed contract. This exclusion runs before every rule.

2. A test MODULE named after a protected module promotes under that module's
   family (`tests/test_gates.py` -> gates_and_verification). Gutting the
   assertions that pin a gate is exactly as dangerous as editing the gate, and
   it is the failure mode this plan's own halt-point ("do not delete the
   identity assertion to pass") exists for. A test module named after an
   unprotected one does not promote, so this does not blanket-promote tests.

3. THIS MODULE IS ITSELF TRUST BOUNDARY. `review_risk.py` is in the trust
   boundary table, so a change to the thing that decides how carefully
   something is reviewed is never itself reviewed cheaply. Leaving it out is
   the one gap the rest of this docstring argues against: a tagger that
   protects every surface except the tagger can be weakened first and then
   used to wave through everything else.

   THE SAME REASONING NOW REACHES `escalation.py` AND `review_dossier.py`,
   added at WP-C1. It always did; only the referents were missing. The earlier
   text deferred them to "the WPs that create them", which "can add
   themselves" -- and that promise was UNFULFILLABLE THE MOMENT IT WAS
   WRITTEN, because the table lives in THIS file, whose only owner (WP-A1) was
   already complete, and no later work package listed it. AN OBLIGATION WITH
   NO OWNER IS NOT DEFERRED, IT IS ABANDONED, and it reads exactly like a
   deferral until someone measures. What made the gap sharp rather than
   untidy: the table PROTECTED ITS OWN AUTHOR (judgement call 3, above) while
   LACKING the two modules it was deferring -- care applied to the near case
   and a promise issued for the far one.

   Both belong here on the merits, not merely to discharge the promise.
   `escalation.py` decides WHICH MODEL a failed work package climbs to; a
   change there that nobody reviewed carefully can hand a stronger model to
   work that did not earn it, or withhold one from work that did.
   `review_dossier.py` decides WHAT A REVIEWER IS ALLOWED TO SEE; weaken it
   and every review downstream is reading a diff someone else curated. Both
   are exactly the shape of "must not be reviewed cheaply".

Stdlib only. No import-time side effects.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Sizes
# --------------------------------------------------------------------------

SIZES: Tuple[str, ...] = ("light", "medium", "complex")
#: The sizes risk promotion can move. `complex` is already the ceiling.
PROMOTABLE: Tuple[str, ...] = ("light", "medium")
#: The size an absent declaration resolves to (L7 rule 6, back-compat).
DEFAULT_SIZE = "complex"
DEFAULT_SIZE_SOURCE = "default"
#: `size_source` this module stamps, and only when it actually promoted.
RISK_SIZE_SOURCE = "risk"

FAMILIES: Tuple[str, ...] = (
    "trust_boundary",
    "gates_and_verification",
    "secrets_and_auth",
    "quota_budget_registry",
    "schemas_and_contracts",
    "governance_and_agents",
)


class ReviewRiskError(ValueError):
    """An input this module refuses to guess about (an unknown size)."""


# --------------------------------------------------------------------------
# Rule vocabulary
#
# Each family is a tuple of (rule_name, matcher). A matcher takes the parsed
# path and returns True. Rule names are part of the output -- they are what a
# report shows a human -- so they are written to be read, not to be terse.
# --------------------------------------------------------------------------

#: Excluded before anything else: a directory of test inputs, not live surface.
EXCLUDED_SEGMENTS = frozenset({"fixtures"})

TRUST_BOUNDARY_BASENAMES = frozenset({
    "seat_model.py",          # protected-role resolution itself
    "codex_model.py",         # TOP selection feeding those roles
    "identity_check.py",      # the dual-location identity watchlist
    "live_home_guard.py",     # the test-suite/real-HOME boundary
    "settings.json",          # the harness permission surface
    "settings.local.json",
    "review_risk.py",         # this module -- judgement call 3
    "escalation.py",          # the rung ladder (stream B)
    "review_dossier.py",      # the reviewer's evidence package (stream C)
})
TRUST_BOUNDARY_SYMBOLS = frozenset({
    "ROLE_TABLE", "PROTECTED_ROLES", "PROTECTED", "SEAT_ROLES",
    "resolve_seat", "seat_model", "_resolve_protected",
})

GATE_BASENAMES = frozenset({
    "gates.py",
    "claims.py",
    "audit_spawn.py",
    "verification_arbiter_spawn.py",
    "visual_arbiter_spawn.py",
    "design_drift_arbiter_spawn.py",
    "deterministic_arm.py",
    "arbiter_arm.py",
    "trusted_runner.py",
    "classify.py",
    "classify_emit.py",
    "pause_state.py",
    "scope_delta.py",
    "scope_reaction.py",
})
GATE_SYMBOLS = frozenset({
    "assert_verified_preconditions",
    "consume_verdict",
    "consume_visual_verdict",
    "apply_request_idempotent",
    "check_transition_legal",
    "verify_claim_on_transition",
    "issue_claim",
    "classify_bundle_evidence",
    "corroborate_citations",
})
#: A gate id. `G_SECURITY`, `G_CONTRACT_SCOPE`, `check_G2` ...
GATE_SYMBOL_RE = re.compile(r"^(check_)?G[_0-9][A-Za-z0-9_]*$")

SECRET_TOKENS = frozenset({
    "secret", "secrets", "credential", "credentials",
    "password", "passwords", "passwd", "htpasswd",
    "auth", "oauth", "apikey", "keyring",
})
SECRET_BASENAMES = frozenset({".env", ".netrc", ".npmrc", "id_rsa", "id_ed25519"})
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")

QUOTA_BASENAMES = frozenset({
    "codex_quota.py",
    "seat_model.py",
    "model_policy.py",
    "model-policy.yaml",
    "seat-model-pins.json",
    "seat-model-tops.json",
    "astra-budget.jsonl",
})
QUOTA_TOKENS = frozenset({"quota", "budget", "budgets"})
QUOTA_SYMBOLS = frozenset({
    "admit", "record_substitution", "SUBSTITUTION_USES", "LIMITS", "USE_LIMITS",
})

SCHEMA_SEGMENTS = frozenset({"schemas"})
SCHEMA_BASENAMES = frozenset({"contract-map.yaml"})
SCHEMA_SUFFIXES = (".schema.json", ".sig")
#: A versioned contract document: `execution-report.v1.json`, `dual-verdict.v1.json`.
SCHEMA_VERSIONED_RE = re.compile(r"\.v[0-9]+\.(json|ya?ml)$")
SCHEMA_TOKENS = frozenset({"schema", "schemas", "contract", "contracts"})
SCHEMA_SYMBOLS = frozenset({"SCHEMA_VERSION", "schema_version"})

GOVERNANCE_BASENAMES = frozenset({
    "CLAUDE.md", "AGENTS.md", "hard-rules-checklist.md",
})
GOVERNANCE_SEGMENTS = frozenset({"agents"})


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def normalize_path(path: str) -> str:
    """Return `path` in the one spelling the rules are written against.

    Backslashes become `/` so a change set collected on Windows matches the same
    rules as one collected here, `./` prefixes go, and trailing slashes go.
    Nothing touches the filesystem, so a path that does not exist normalizes
    exactly like one that does.
    """
    text = str(path).strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = posixpath.normpath(text) if text else text
    return "" if text in (".", "") else text.rstrip("/")


def _tokens(text: str) -> frozenset:
    """Whole word-ish tokens of `text`, lowercased.

    Tokenising is what keeps `auth` from matching `workflow-authoring` and
    `author.py`. Substring matching on these keywords promotes half the tree.
    """
    return frozenset(t for t in re.split(r"[^a-z0-9]+", text.lower()) if t)


class _Path:
    """A normalized path, parsed once so every rule reads the same view."""

    __slots__ = ("raw", "text", "basename", "segments", "tokens", "lower")

    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.text = normalize_path(raw)
        self.basename = posixpath.basename(self.text)
        self.segments = tuple(p for p in self.text.split("/") if p)
        self.tokens = _tokens(self.text)
        self.lower = self.text.lower()

    @property
    def excluded(self) -> bool:
        return bool(EXCLUDED_SEGMENTS.intersection(self.segments))

    @property
    def test_subject(self) -> Optional[str]:
        """The module basename a test module is a test OF, else None.

        `skills/_meta/tests/test_gates.py` -> `gates.py`. Only inside a `tests`
        directory, so a production module that happens to start with `test_`
        is not silently re-pointed at something else.
        """
        if "tests" not in self.segments:
            return None
        if not (self.basename.startswith("test_") and self.basename.endswith(".py")):
            return None
        return self.basename[len("test_"):]


# --------------------------------------------------------------------------
# Family rules
# --------------------------------------------------------------------------

def _match_trust_boundary(p: _Path) -> Optional[str]:
    if p.basename in TRUST_BOUNDARY_BASENAMES:
        return "protected-role resolution or harness trust surface"
    return None


def _match_gates(p: _Path) -> Optional[str]:
    if p.basename in GATE_BASENAMES:
        return "gate, claim ledger or verification arm"
    return None


def _match_secrets(p: _Path) -> Optional[str]:
    if p.basename in SECRET_BASENAMES or p.basename.startswith(".env."):
        return "credential file"
    if p.lower.endswith(SECRET_SUFFIXES):
        return "key or certificate material"
    hit = SECRET_TOKENS.intersection(p.tokens)
    if hit:
        return "secrets or auth surface ({0})".format(sorted(hit)[0])
    return None


def _match_quota(p: _Path) -> Optional[str]:
    if p.basename in QUOTA_BASENAMES:
        return "quota, budget or seat registry"
    hit = QUOTA_TOKENS.intersection(p.tokens)
    if hit:
        return "quota or budget surface ({0})".format(sorted(hit)[0])
    return None


def _match_schemas(p: _Path) -> Optional[str]:
    if SCHEMA_SEGMENTS.intersection(p.segments):
        return "schema directory"
    if p.basename in SCHEMA_BASENAMES:
        return "signed contract"
    if p.lower.endswith(SCHEMA_SUFFIXES):
        return "schema or signature file"
    if SCHEMA_VERSIONED_RE.search(p.basename):
        return "versioned contract document"
    hit = SCHEMA_TOKENS.intersection(p.tokens)
    if hit:
        return "schema or contract surface ({0})".format(sorted(hit)[0])
    return None


def _match_governance(p: _Path) -> Optional[str]:
    if p.basename in GOVERNANCE_BASENAMES:
        return "governance document"
    if GOVERNANCE_SEGMENTS.intersection(p.segments):
        return "agent definition"
    return None


_PATH_RULES = (
    ("trust_boundary", _match_trust_boundary),
    ("gates_and_verification", _match_gates),
    ("secrets_and_auth", _match_secrets),
    ("quota_budget_registry", _match_quota),
    ("schemas_and_contracts", _match_schemas),
    ("governance_and_agents", _match_governance),
)


def _match_symbol(symbol: str) -> List[Tuple[str, str]]:
    """Families a bare symbol name fires, with the reason.

    The symbol arm is deliberately NARROWER than the path arm: a symbol carries
    no directory context, so only unambiguous names are listed. A generic name
    like `resolve` or `main` is not a risk signal and is not treated as one.
    """
    out: List[Tuple[str, str]] = []
    name = symbol.strip()
    if not name:
        return out
    toks = _tokens(name)
    if name in TRUST_BOUNDARY_SYMBOLS:
        out.append(("trust_boundary", "protected-role resolution symbol"))
    if name in GATE_SYMBOLS:
        out.append(("gates_and_verification", "gate or ledger transition symbol"))
    elif GATE_SYMBOL_RE.match(name):
        out.append(("gates_and_verification", "gate identifier"))
    if SECRET_TOKENS.intersection(toks):
        out.append(("secrets_and_auth", "secrets or auth symbol"))
    if name in QUOTA_SYMBOLS or QUOTA_TOKENS.intersection(toks):
        out.append(("quota_budget_registry", "quota or budget symbol"))
    if name in SCHEMA_SYMBOLS or SCHEMA_TOKENS.intersection(toks):
        out.append(("schemas_and_contracts", "schema or contract symbol"))
    return out


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------

class Tag:
    """One reason a change set is risky. Hashable, so tags form a real set."""

    __slots__ = ("family", "kind", "matched", "rule")

    def __init__(self, family: str, kind: str, matched: str, rule: str) -> None:
        self.family = family
        self.kind = kind          # "path" | "symbol"
        self.matched = matched    # the path or symbol that fired
        self.rule = rule          # why it fired, in words a report can print

    @property
    def _key(self) -> Tuple[str, str, str, str]:
        return (self.family, self.kind, self.matched, self.rule)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Tag) and other._key == self._key

    def __hash__(self) -> int:
        return hash(self._key)

    def __repr__(self) -> str:
        return "Tag({0!r}, {1!r}, {2!r}, {3!r})".format(
            self.family, self.kind, self.matched, self.rule)

    def to_dict(self) -> Dict[str, str]:
        return {"family": self.family, "kind": self.kind,
                "matched": self.matched, "rule": self.rule}


def tag_paths(paths: Iterable[str]) -> List[Tag]:
    """Tags fired by `paths`, in a stable order (path, then family order)."""
    tags: List[Tag] = []
    seen = set()
    for raw in paths or ():
        p = _Path(raw)
        if not p.text or p.excluded:
            continue
        for family, matcher in _PATH_RULES:
            reason = matcher(p)
            if reason is None:
                continue
            tag = Tag(family, "path", p.text, reason)
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
        subject = p.test_subject
        if subject is None:
            continue
        # Judgement call 2: a test module inherits its subject's families.
        sub = _Path(subject)
        for family, matcher in _PATH_RULES:
            reason = matcher(sub)
            if reason is None:
                continue
            tag = Tag(family, "path", p.text,
                      "test of a protected module ({0})".format(reason))
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def tag_symbols(symbols: Iterable[str]) -> List[Tag]:
    """Tags fired by bare symbol names, in a stable order."""
    tags: List[Tag] = []
    seen = set()
    for raw in symbols or ():
        name = str(raw).strip()
        if not name:
            continue
        for family, reason in _match_symbol(name):
            tag = Tag(family, "symbol", name, reason)
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def tag_change_set(paths: Iterable[str] = (),
                   symbols: Iterable[str] = ()) -> Tuple[Tag, ...]:
    """Every tag a change set fires. Paths first, then symbols."""
    return tuple(tag_paths(paths)) + tuple(tag_symbols(symbols))


# --------------------------------------------------------------------------
# Assessment
# --------------------------------------------------------------------------

class Assessment:
    """The verdict: what fired, and what size it implies."""

    __slots__ = ("tags", "families", "declared_size", "size",
                 "size_source", "promoted", "user_request")

    def __init__(self, tags: Sequence[Tag], declared_size: str, size: str,
                 size_source: Optional[str], promoted: bool,
                 user_request: bool) -> None:
        self.tags = tuple(tags)
        self.families = tuple(sorted({t.family for t in tags}))
        self.declared_size = declared_size
        self.size = size
        self.size_source = size_source
        self.promoted = promoted
        self.user_request = user_request

    def __repr__(self) -> str:
        return ("Assessment(size={0!r}, size_source={1!r}, promoted={2!r}, "
                "families={3!r})".format(self.size, self.size_source,
                                         self.promoted, self.families))

    def to_dict(self) -> Dict[str, object]:
        return {
            "size": self.size,
            "size_source": self.size_source,
            "promoted": self.promoted,
            "declared_size": self.declared_size,
            "user_request": self.user_request,
            "families": list(self.families),
            "tags": [t.to_dict() for t in self.tags],
        }


def assess(paths: Iterable[str] = (),
           symbols: Iterable[str] = (),
           *,
           size: Optional[str] = None,
           size_source: Optional[str] = None,
           user_request: bool = False) -> Assessment:
    """Tag `paths`/`symbols` and apply the promotion contract to `size`.

    `size=None` resolves to `complex` / `size_source="default"` (L7 rule 6), so
    an unsized caller is already at the ceiling and nothing promotes.

    Promotion is upward-only and sets `size_source="risk"` ONLY when the size
    actually moved. `user_request=True` forces TOP upstream, so it suppresses
    promotion and leaves the caller's provenance untouched.
    """
    declared = DEFAULT_SIZE if size is None else str(size)
    if declared not in SIZES:
        raise ReviewRiskError(
            "unknown review size {0!r}; expected one of {1}".format(
                size, ", ".join(SIZES)))
    source = size_source
    if size is None and source is None:
        source = DEFAULT_SIZE_SOURCE

    tags = tag_change_set(paths, symbols)
    promote = bool(tags) and not user_request and declared in PROMOTABLE
    if promote:
        return Assessment(tags, declared, DEFAULT_SIZE, RISK_SIZE_SOURCE,
                          True, user_request)
    return Assessment(tags, declared, declared, source, False, user_request)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_risk.py",
        description=("Tag a change set and report the review size it implies. "
                     "Pure: reads no repo, calls no model."))
    parser.add_argument("paths", nargs="*", help="changed paths")
    parser.add_argument("--symbol", action="append", default=[],
                        metavar="NAME", help="a changed symbol (repeatable)")
    parser.add_argument("--size", choices=list(SIZES), default=None,
                        help="the declared review size (absent: complex)")
    parser.add_argument("--size-source", default=None,
                        help="provenance of the declared size")
    parser.add_argument("--user-request", action="store_true",
                        help="the user asked for TOP; suppresses promotion")
    parser.add_argument("--json", action="store_true",
                        help="emit the assessment as canonical JSON")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = assess(args.paths, args.symbol, size=args.size,
                        size_source=args.size_source,
                        user_request=args.user_request)
    except ReviewRiskError as exc:
        print("review_risk.py: error: {0}".format(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True,
                         separators=(",", ":")))
        return 0
    print("size={0} size_source={1} promoted={2}".format(
        result.size, result.size_source, result.promoted))
    for tag in result.tags:
        print("  {0}: {1} -- {2}".format(tag.family, tag.matched, tag.rule))
    return 0


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
