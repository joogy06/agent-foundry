#!/usr/bin/env python3
"""test_uri_resolver.py -- S028 WP-1 URI resolver unit tests.

Covers the 5 test scenarios TS-URI-01..05 declared in
`progress/contract-map.yaml` for the `uri-resolver` component:

    TS-URI-01: resolve capability URI to contract-map node
    TS-URI-02: resolve skeleton URI with fragment to interaction jsonpointer
    TS-URI-03: UriAmbiguousError on collision between active and retired aliases
    TS-URI-04: alias chain walk populates resolution_chain
    TS-URI-05: allow_expired semantics

Additional smoke cases are included for the remaining schemes (flow, token,
component, wire) and for URI format / not-found error paths.

Run:
    python -m pytest ~/.claude/skills/_meta/tests/test_uri_resolver.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# This test file lives at ~/.claude/skills/_meta/tests/ — the parent dir
# holds uri.py. Resolve it relative to __file__ so we do not rely on PYTHONPATH.
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPT_DIR))

import uri  # noqa: E402

# Fixture root lives inside the skill_factory project workspace.
FIXTURE_ROOT = (
    Path("/path/to/project/tests/fixtures/uri-resolver/"
         "project-root-sample")
)


class TSUri01_CapabilityResolve(unittest.TestCase):
    """TS-URI-01 — capability URI → contract-map jsonpointer."""

    def test_happy_path_capability(self):
        result = uri.resolve(
            "capability://journey_controller.advance_step", FIXTURE_ROOT
        )
        self.assertEqual(result.scheme, "capability")
        self.assertEqual(result.schema_name, "contract-map.v1")
        self.assertEqual(result.ledger_path, Path("progress/contract-map.yaml"))
        self.assertEqual(
            result.jsonpointer,
            "/components/journey_controller/capabilities/advance_step",
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())
        self.assertEqual(
            result.entity_uuid, "11111111-1111-1111-1111-111111111111"
        )
        self.assertEqual(result.resolution_chain, ())
        self.assertIsInstance(result.node, dict)
        self.assertEqual(result.node.get("entry_point"), "api_public")


class TSUri02_SkeletonFragment(unittest.TestCase):
    """TS-URI-02 — skeleton fragment splits on LAST dot to element.event."""

    def test_skeleton_click_interaction(self):
        result = uri.resolve(
            "skeleton://journey_main#step_card.1.click", FIXTURE_ROOT
        )
        self.assertEqual(result.scheme, "skeleton")
        self.assertEqual(result.schema_name, "design-skeleton.v1")
        self.assertEqual(
            result.ledger_path,
            Path(".design-ledger/skeletons/journey_main.yaml"),
        )
        # Fragment split on last dot: element = step_card.1, event = click
        self.assertEqual(
            result.jsonpointer,
            "/elements/step_card.1/interactions/click",
        )
        self.assertTrue(result.valid)
        self.assertIsInstance(result.node, dict)
        self.assertEqual(result.node.get("event"), "click")
        self.assertEqual(
            result.node.get("binds_to"),
            "capability://journey_controller.advance_step",
        )

    def test_skeleton_visual_only_hover(self):
        """Hover is visual_only but still resolves."""
        result = uri.resolve(
            "skeleton://journey_main#step_card.1.hover", FIXTURE_ROOT
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.node.get("event"), "hover")
        self.assertTrue(result.node.get("visual_only"))

    def test_skeleton_requires_fragment(self):
        with self.assertRaises(uri.UriFormatError):
            uri.resolve("skeleton://journey_main", FIXTURE_ROOT)

    def test_skeleton_fragment_nonexistent_event(self):
        with self.assertRaises(uri.UriNotFoundError):
            uri.resolve(
                "skeleton://journey_main#step_card.1.dblclick",
                FIXTURE_ROOT,
            )

    def test_skeleton_screen_missing(self):
        with self.assertRaises(uri.UriNotFoundError):
            uri.resolve(
                "skeleton://no_such_screen#step_card.1.click", FIXTURE_ROOT
            )


class TSUri03_Ambiguous(unittest.TestCase):
    """TS-URI-03 — URI matches both an active entity AND a retired alias.

    Fixture: `capability://onboarding_controller.advance` is:
      - Active in contract-map (entity 33333333-...)
      - Also a `from_uri` in history eeeeeeee-...'s renamed event
    Resolver MUST raise UriAmbiguousError (no silent closest-match).
    """

    def test_active_and_alias_collision_raises(self):
        with self.assertRaises(uri.UriAmbiguousError) as ctx:
            uri.resolve(
                "capability://onboarding_controller.advance", FIXTURE_ROOT
            )
        self.assertIn("ambiguous", str(ctx.exception).lower())


class TSUri04_AliasChain(unittest.TestCase):
    """TS-URI-04 — alias chain walk populates resolution_chain.

    Fixture: `capability://journey_controller.advance` was renamed to
    `capability://journey_controller.advance_step`. Resolving the OLD URI
    should follow the chain forward and return the current node with chain
    provenance.
    """

    def test_alias_chain_walk(self):
        result = uri.resolve(
            "capability://journey_controller.advance", FIXTURE_ROOT
        )
        # Terminal URI is the renamed-to value
        self.assertEqual(
            result.uri, "capability://journey_controller.advance_step"
        )
        # Chain starts at the original and ends at the current
        self.assertEqual(
            result.resolution_chain,
            (
                "capability://journey_controller.advance",
                "capability://journey_controller.advance_step",
            ),
        )
        self.assertTrue(result.valid)
        self.assertEqual(
            result.entity_uuid, "11111111-1111-1111-1111-111111111111"
        )


class TSUri05_Expired(unittest.TestCase):
    """TS-URI-05 — allow_expired toggles UriExpiredError on retired entities.

    Fixture: `capability://journey_controller.legacy_advance` is a retired
    entity (status: retired, successors: []). Default resolution raises;
    allow_expired=True returns a ResolvedEntity with node=None + uuid set.
    """

    def test_expired_default_raises(self):
        with self.assertRaises(uri.UriExpiredError):
            uri.resolve(
                "capability://journey_controller.legacy_advance",
                FIXTURE_ROOT,
            )

    def test_expired_allow_returns_retired(self):
        result = uri.resolve(
            "capability://journey_controller.legacy_advance",
            FIXTURE_ROOT,
            allow_expired=True,
        )
        self.assertFalse(result.valid)
        self.assertIsNone(result.node)
        self.assertEqual(
            result.entity_uuid, "dddddddd-dddd-dddd-dddd-dddddddddddd"
        )
        self.assertIn("retired", result.errors[0].lower())


# ---------------------------------------------------------------------------
# Additional scheme coverage (still within WP-1 scope)
# ---------------------------------------------------------------------------


class SchemeCoverage(unittest.TestCase):
    """Smoke-tests the remaining schemes against the fixture tree."""

    def test_flow_happy(self):
        result = uri.resolve("flow://journey.advance", FIXTURE_ROOT)
        self.assertEqual(result.scheme, "flow")
        self.assertEqual(result.ledger_path, Path("progress/flows.yaml"))
        self.assertEqual(result.jsonpointer, "/flows/journey.advance")
        self.assertTrue(result.valid)

    def test_flow_not_found(self):
        with self.assertRaises(uri.UriNotFoundError):
            uri.resolve("flow://journey.dream", FIXTURE_ROOT)

    def test_token_nested(self):
        result = uri.resolve("token://color.accent.sun", FIXTURE_ROOT)
        self.assertEqual(result.scheme, "token")
        self.assertEqual(
            result.ledger_path,
            Path(".design-ledger/skeletons/index.yaml"),
        )
        self.assertEqual(result.jsonpointer, "/tokens/color/accent/sun")
        self.assertTrue(result.valid)
        self.assertEqual(result.node.get("value"), "#ffcc33")

    def test_component_happy(self):
        result = uri.resolve("component://step_card", FIXTURE_ROOT)
        self.assertEqual(result.scheme, "component")
        self.assertEqual(result.jsonpointer, "/components/step_card")
        self.assertTrue(result.valid)

    def test_wire_happy(self):
        result = uri.resolve(
            "wire://packages.journey_controller.step_handlers", FIXTURE_ROOT
        )
        self.assertEqual(result.scheme, "wire")
        self.assertEqual(result.ledger_path, Path(".wiring/latest.json"))
        self.assertTrue(result.valid)


class ErrorPaths(unittest.TestCase):
    """Error-class smoke tests."""

    def test_unknown_scheme(self):
        with self.assertRaises(uri.UriSchemaError):
            uri.resolve("notaurl://foo", FIXTURE_ROOT)

    def test_invalid_format_slashes(self):
        with self.assertRaises(uri.UriFormatError):
            uri.resolve("capability://bad/id/with/slashes", FIXTURE_ROOT)

    def test_not_found(self):
        with self.assertRaises(uri.UriNotFoundError):
            uri.resolve(
                "capability://journey_controller.nonexistent", FIXTURE_ROOT
            )

    def test_exists_true(self):
        self.assertTrue(
            uri.exists(
                "capability://journey_controller.advance_step", FIXTURE_ROOT
            )
        )

    def test_exists_false_on_expired(self):
        # allow_expired=False is the default; an expired URI should return False.
        self.assertFalse(
            uri.exists(
                "capability://journey_controller.legacy_advance", FIXTURE_ROOT
            )
        )

    def test_exists_false_on_not_found(self):
        self.assertFalse(
            uri.exists(
                "capability://journey_controller.nonexistent", FIXTURE_ROOT
            )
        )

    def test_to_uri_capability(self):
        self.assertEqual(
            uri.to_uri("capability", "journey_controller.advance_step"),
            "capability://journey_controller.advance_step",
        )

    def test_to_uri_skeleton_with_fragment(self):
        self.assertEqual(
            uri.to_uri(
                "skeleton", "journey_main", fragment="step_card.1.click"
            ),
            "skeleton://journey_main#step_card.1.click",
        )

    def test_to_uri_rejects_unknown_scheme(self):
        with self.assertRaises(uri.UriSchemaError):
            uri.to_uri("bogus", "foo")

    def test_to_uri_rejects_bad_segment(self):
        with self.assertRaises(uri.UriFormatError):
            uri.to_uri("capability", "bad/id")


if __name__ == "__main__":
    unittest.main(verbosity=2)
