"""Gate 8B: the successor discovery plan, its staging and its authorization.

Every proof here is a pure unit test. Generation, staging, artifact building
and artifact loading are all offline by construction, so no database fixture is
needed and none is used — which is itself one of the properties under test.
"""

import ast
import hashlib
import inspect
import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

import market.provider_observed_successor as successor_module
from market.historical_acquisition import FROZEN_RANGES, INSTRUMENTS
from market.historical_discovery import (
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    build_replacement_discovery_plan,
    canonical_hash,
    h1_request_boundaries,
    parse_timestamp,
)
from market.provider_observed_successor import (
    ARTIFACT_SCHEMA,
    AUTHORIZATION_FILE_SHA256,
    CANARY_INSTRUMENT,
    EXPECTED_CHUNK_COUNT,
    EXPECTED_STAGE_COUNTS,
    MAX_ATTEMPTS_PER_CHUNK,
    REQUIRED_H1_WARMUP_OBSERVATIONS,
    STAGE_CANARY,
    STAGE_CROSS_INSTRUMENT,
    STAGE_REMAINDER,
    SUCCESSOR_H1_REQUESTED_FROM,
    _verify_committed_authorization,
    build_gate8b_authorization,
    build_successor_discovery_plan,
    canonical_authorization_bytes,
    gate8b_authorization_path,
    load_committed_gate8b_authorization,
    staged_discovery_membership,
    verify_staged_membership,
    verify_successor_plan_shape,
)

FORBIDDEN_DERIVATION_NAMES = frozenset(
    {"DEVELOPMENT_START", "WARMUP_CANDLES", "expected_candle_timestamps", "signal_count"}
)
# Transport is proven absent by what the module imports, not by banning an
# identifier: "requests" is this domain's word for planned provider calls and
# appears throughout as a local variable holding the plan's request manifest.
FORBIDDEN_TRANSPORT_IMPORTS = frozenset(
    {"requests", "urllib", "socket", "httpx", "http", "aiohttp", "oanda"}
)
FORBIDDEN_TRANSPORT_NAMES = frozenset({"OandaClient", "urlopen", "connect"})
FORBIDDEN_STRATEGY_NAMES = frozenset({"JobRun", "AnalysisRun", "SetupEvent", "DatasetRegistration"})


def module_source():
    return Path(sys.modules["market.provider_observed_successor"].__file__).read_text()


def module_ast():
    return ast.parse(module_source())


def imported_modules(tree):
    """Every module path the module imports, split into components."""
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.update(node.module.split("."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.update(alias.name.split("."))
    return modules


def referenced_names(tree):
    """Every name the module's executable code touches, ignoring comments and
    docstrings — prose that discusses a rule must not fail a code check."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.update(node.module.split("."))
            for alias in node.names:
                names.update(alias.name.split("."))
    return names


def h1_requests(plan, instrument=None):
    return [
        item
        for item in sorted(plan["requests"], key=lambda entry: entry["ordinal"])
        if item["canonical_request"]["granularity"] == "H1"
        and (instrument is None or item["canonical_request"]["instrument"] == instrument)
    ]


class SuccessorBoundaryTests(SimpleTestCase):
    def test_h1_start_is_the_exact_governed_literal(self):
        # 1
        self.assertEqual(SUCCESSOR_H1_REQUESTED_FROM, "2009-12-30T22:00:00Z")
        plan = build_successor_discovery_plan()
        for instrument in INSTRUMENTS:
            self.assertEqual(
                h1_requests(plan, instrument)[0]["canonical_request"]["from"],
                "2009-12-30T22:00:00Z",
            )

    def test_the_literal_is_not_derived_from_the_calendar_or_development_start(self):
        """2: the boundary is a plain string constant, not an expression.

        Both plausible derivations land on a different instant, and the module's
        executable code — comments and docstrings excluded, since those discuss
        the rule — references neither the development start nor the calendar."""
        from research.signal_count import DEVELOPMENT_START, WARMUP_CANDLES

        boundary = parse_timestamp(SUCCESSOR_H1_REQUESTED_FROM)
        development_start = DEVELOPMENT_START.astimezone(boundary.tzinfo)
        self.assertNotEqual(boundary, development_start - timedelta(hours=WARMUP_CANDLES["H1"]))
        self.assertNotEqual(boundary, development_start - timedelta(hours=14))

        tree = module_ast()
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SUCCESSOR_H1_REQUESTED_FROM"
                for target in node.targets
            )
        )
        self.assertIsInstance(assignment.value, ast.Constant)
        self.assertEqual(assignment.value.value, "2009-12-30T22:00:00Z")
        self.assertEqual(referenced_names(tree) & FORBIDDEN_DERIVATION_NAMES, set())

    def test_development_and_warmup_governance_is_untouched(self):
        # 4
        from research.signal_count import DEVELOPMENT_END, DEVELOPMENT_START, WARMUP_CANDLES

        self.assertEqual(WARMUP_CANDLES, {"W": 1, "D": 220, "H1": 14})
        self.assertEqual(DEVELOPMENT_START.isoformat(), "2010-01-01T00:00:00-05:00")
        self.assertEqual(DEVELOPMENT_END.isoformat(), "2019-01-01T00:00:00-05:00")
        self.assertEqual(REQUIRED_H1_WARMUP_OBSERVATIONS, WARMUP_CANDLES["H1"])


class SuccessorPlanShapeTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = build_successor_discovery_plan()
        cls.predecessor = build_replacement_discovery_plan()

    def test_d_and_w_requests_are_byte_identical_to_the_accepted_plan(self):
        # 3
        def others(plan):
            return [
                item["canonical_request"]
                for item in sorted(plan["requests"], key=lambda entry: entry["ordinal"])
                if item["canonical_request"]["granularity"] in {"D", "W"}
            ]

        self.assertEqual(others(self.plan), others(self.predecessor))

    def test_h1_end_and_frozen_ranges_are_unchanged(self):
        # 4
        for instrument in INSTRUMENTS:
            self.assertEqual(
                h1_requests(self.plan, instrument)[-1]["canonical_request"]["to"],
                h1_requests(self.predecessor, instrument)[-1]["canonical_request"]["to"],
            )
        self.assertEqual(FROZEN_RANGES["H1"]["from"], "2009-12-31T15:00:00+00:00")
        self.assertEqual(FROZEN_RANGES["H1"]["to"], "2019-01-01T04:00:00+00:00")

    def test_exact_chunk_counts_per_granularity_and_instrument(self):
        # 5, 6, 7
        self.assertEqual(len(self.plan["requests"]), EXPECTED_CHUNK_COUNT)
        self.assertEqual(self.plan["declared_chunk_count"], EXPECTED_CHUNK_COUNT)
        shape = verify_successor_plan_shape(self.plan)
        self.assertEqual(shape["granularity_chunks"], {"D": 6, "H1": 120, "W": 6})
        self.assertEqual(shape["instrument_chunks"], {"D": 1, "H1": 20, "W": 1})

    def test_only_the_first_h1_window_moves_and_no_twenty_first_appears(self):
        # 8
        for instrument in INSTRUMENTS:
            successor = h1_requests(self.plan, instrument)
            predecessor = h1_requests(self.predecessor, instrument)
            self.assertEqual(len(successor), 20)
            self.assertEqual(len(predecessor), 20)
            self.assertEqual(
                [item["canonical_request"] for item in successor[1:]],
                [item["canonical_request"] for item in predecessor[1:]],
            )
            self.assertEqual(successor[0]["canonical_request"]["from"], "2009-12-30T22:00:00Z")
            self.assertEqual(
                successor[0]["canonical_request"]["to"],
                predecessor[0]["canonical_request"]["to"],
            )
        # the extended window stays far inside the provider's 5,000-candle cap
        first = h1_requests(self.plan)[0]["canonical_request"]
        hours = (
            parse_timestamp(first["to"]) - parse_timestamp(first["from"])
        ).total_seconds() / 3600
        self.assertEqual(hours, 4017)
        self.assertLess(hours, 5000)

    def test_request_hashes_ordinals_and_logical_keys_reconstruct(self):
        # 9, 10
        ordinals = [item["ordinal"] for item in self.plan["requests"]]
        self.assertEqual(ordinals, list(range(1, EXPECTED_CHUNK_COUNT + 1)))
        self.assertEqual(len(set(ordinals)), EXPECTED_CHUNK_COUNT)
        keys = set()
        for item in self.plan["requests"]:
            self.assertEqual(
                item["canonical_request_sha256"], canonical_hash(item["canonical_request"])
            )
            keys.add(item["logical_discovery_key"])
        self.assertEqual(len(keys), EXPECTED_CHUNK_COUNT)
        self.assertEqual(
            self.plan["canonical_request_manifest_sha256"], canonical_hash(self.plan["requests"])
        )
        body = {key: value for key, value in self.plan.items() if key != "plan_sha256"}
        self.assertEqual(self.plan["plan_sha256"], canonical_hash(body))

    def test_generation_is_deterministic(self):
        # 12
        again = build_successor_discovery_plan()
        self.assertEqual(
            json.dumps(again, sort_keys=True, separators=(",", ":")),
            json.dumps(self.plan, sort_keys=True, separators=(",", ":")),
        )

    def test_accepted_v2_plan_output_is_unchanged(self):
        # 19: the shared builder must not have moved a single predecessor byte
        self.assertEqual(self.predecessor["plan_sha256"], DISCOVERY_V2_PLAN_SHA256)
        self.assertEqual(
            self.predecessor["canonical_request_manifest_sha256"], DISCOVERY_V2_MANIFEST_SHA256
        )
        self.assertNotEqual(self.plan["plan_sha256"], DISCOVERY_V2_PLAN_SHA256)


class H1BoundaryOverrideTests(SimpleTestCase):
    """The override may only extend. Anything that would move the opening bound
    forward is refused, because it would silently truncate front coverage while
    still returning a plausible twenty-window plan."""

    start = parse_timestamp(FROZEN_RANGES["H1"]["from"])
    end = parse_timestamp(FROZEN_RANGES["H1"]["to"])

    def test_none_reproduces_the_accepted_v2_boundaries(self):
        boundaries = h1_request_boundaries(self.start, self.end)
        self.assertEqual(len(boundaries), 20)
        self.assertEqual(boundaries[0][0], self.start)
        self.assertEqual(boundaries[-1][1], self.end)
        self.assertEqual(
            build_replacement_discovery_plan()["plan_sha256"], DISCOVERY_V2_PLAN_SHA256
        )

    def test_a_genuinely_earlier_start_is_accepted(self):
        earlier = parse_timestamp(SUCCESSOR_H1_REQUESTED_FROM)
        boundaries = h1_request_boundaries(self.start, self.end, first_requested_from=earlier)
        reference = h1_request_boundaries(self.start, self.end)
        self.assertEqual(len(boundaries), 20)
        self.assertEqual(boundaries[0], (earlier, reference[0][1]))
        self.assertEqual(boundaries[1:], reference[1:])

    def test_a_start_equal_to_the_frozen_range_start_is_refused(self):
        with self.assertRaisesMessage(ValueError, "strictly before the frozen range start"):
            h1_request_boundaries(self.start, self.end, first_requested_from=self.start)

    def test_a_later_start_inside_the_first_window_is_refused(self):
        later = parse_timestamp("2010-01-15T00:00:00Z")
        self.assertGreater(later, self.start)
        self.assertLess(later, h1_request_boundaries(self.start, self.end)[0][1])
        with self.assertRaisesMessage(ValueError, "strictly before the frozen range start"):
            h1_request_boundaries(self.start, self.end, first_requested_from=later)

    def test_a_start_at_or_beyond_the_first_window_end_is_refused(self):
        close = h1_request_boundaries(self.start, self.end)[0][1]
        for candidate in (close, self.end):
            with self.assertRaisesMessage(ValueError, "strictly before the frozen range start"):
                h1_request_boundaries(self.start, self.end, first_requested_from=candidate)

    def test_the_accepted_extension_has_no_gap_overlap_or_truncation(self):
        earlier = parse_timestamp(SUCCESSOR_H1_REQUESTED_FROM)
        boundaries = h1_request_boundaries(self.start, self.end, first_requested_from=earlier)
        self.assertEqual(boundaries[0][0], earlier)
        self.assertEqual(boundaries[-1][1], self.end)
        for previous, following in zip(boundaries, boundaries[1:]):
            self.assertEqual(previous[1], following[0])
            self.assertLess(previous[0], previous[1])


class SuccessorStagingTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = build_successor_discovery_plan()
        cls.membership = staged_discovery_membership(cls.plan)

    def test_stages_are_exactly_one_five_and_one_hundred_twenty_six(self):
        # 11
        self.assertEqual(
            {stage: len(items) for stage, items in self.membership.items()},
            dict(EXPECTED_STAGE_COUNTS),
        )
        self.assertEqual(sum(EXPECTED_STAGE_COUNTS.values()), EXPECTED_CHUNK_COUNT)

    def test_stages_are_disjoint_complete_and_content_addressed(self):
        # 11
        keys = [
            item["logical_discovery_key"]
            for stage in (STAGE_CANARY, STAGE_CROSS_INSTRUMENT, STAGE_REMAINDER)
            for item in self.membership[stage]
        ]
        self.assertEqual(len(keys), EXPECTED_CHUNK_COUNT)
        self.assertEqual(len(set(keys)), EXPECTED_CHUNK_COUNT)
        self.assertEqual(
            set(keys), {item["logical_discovery_key"] for item in self.plan["requests"]}
        )

    def test_the_canary_and_cross_instrument_stages_are_the_extended_windows(self):
        # 11
        canary = self.membership[STAGE_CANARY][0]
        self.assertEqual(canary["instrument"], CANARY_INSTRUMENT)
        self.assertEqual(canary["granularity"], "H1")
        self.assertEqual(canary["requested_from"], "2009-12-30T22:00:00Z")
        cross = self.membership[STAGE_CROSS_INSTRUMENT]
        self.assertEqual(
            sorted(item["instrument"] for item in cross),
            sorted(code for code in INSTRUMENTS if code != CANARY_INSTRUMENT),
        )
        self.assertTrue(all(item["requested_from"] == "2009-12-30T22:00:00Z" for item in cross))
        self.assertFalse(
            any(
                item["requested_from"] == "2009-12-30T22:00:00Z"
                for item in self.membership[STAGE_REMAINDER]
            )
        )

    def test_stages_are_ordered_by_plan_ordinal(self):
        # 11
        for stage, items in self.membership.items():
            ordinals = [item["ordinal"] for item in items]
            self.assertEqual(ordinals, sorted(ordinals), stage)

    def test_tampered_staging_fails_closed(self):
        # 16
        broken = {stage: list(items) for stage, items in self.membership.items()}
        broken[STAGE_REMAINDER] = broken[STAGE_REMAINDER][:-1]
        with self.assertRaisesMessage(ValueError, "successor staging must be"):
            verify_staged_membership(broken, self.plan)

        duplicated = {stage: list(items) for stage, items in self.membership.items()}
        duplicated[STAGE_REMAINDER] = duplicated[STAGE_REMAINDER][:-1] + [
            duplicated[STAGE_CANARY][0]
        ]
        with self.assertRaisesMessage(ValueError, "successor staging repeats a chunk"):
            verify_staged_membership(duplicated, self.plan)


class Gate8bAuthorizationArtifactTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.authorization = build_gate8b_authorization()
        cls.committed = gate8b_authorization_path().read_bytes()

    def test_committed_artifact_is_canonical_json(self):
        # 13
        self.assertEqual(
            self.committed,
            json.dumps(json.loads(self.committed), sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertNotIn(b"\n", self.committed)

    def test_file_digest_and_embedded_self_hash_reconstruct(self):
        # 14: the committed document's own claimed hash, recomputed from the
        # committed body — not from anything this process just generated.
        document = json.loads(self.committed)
        body = {key: value for key, value in document.items() if key != "authorization_sha256"}
        self.assertEqual(document["authorization_sha256"], canonical_hash(body))
        self.assertEqual(hashlib.sha256(self.committed).hexdigest(), AUTHORIZATION_FILE_SHA256)
        loaded = load_committed_gate8b_authorization()
        self.assertEqual(loaded["authorization_sha256"], document["authorization_sha256"])

    def test_the_production_loader_pins_the_file_digest_with_no_bypass(self):
        """The public loader takes no argument, so no caller can weaken it, and
        the pinned digest is the real one."""
        self.assertEqual(
            list(inspect.signature(load_committed_gate8b_authorization).parameters), []
        )
        self.assertEqual(AUTHORIZATION_FILE_SHA256, hashlib.sha256(self.committed).hexdigest())

    def test_a_coordinated_artifact_and_constant_change_still_fails_the_digest(self):
        """The correction's whole point. Move the governed boundary and rebuild
        the artifact so file and regeneration agree with each other — the
        production loader must still refuse, because neither agrees with the
        digest pinned in code."""
        with patch.object(successor_module, "SUCCESSOR_H1_REQUESTED_FROM", "2009-12-29T22:00:00Z"):
            forged = canonical_authorization_bytes(build_gate8b_authorization())
            self.assertNotEqual(forged, self.committed)
            # the forgery is internally consistent: its own self-hash verifies
            document = json.loads(forged)
            body = {key: value for key, value in document.items() if key != "authorization_sha256"}
            self.assertEqual(document["authorization_sha256"], canonical_hash(body))
            with (
                patch.object(Path, "read_bytes", return_value=forged),
                self.assertRaisesMessage(ValueError, "does not match its governed pin"),
            ):
                load_committed_gate8b_authorization()

    def test_a_corrupted_embedded_self_hash_is_rejected_by_the_self_hash_check(self):
        """Reach the self-hash layer by naming the corrupted file's own digest,
        and prove the rejection comes from that check rather than from the
        regeneration comparison that follows it."""
        document = json.loads(self.committed)
        document["authorization_sha256"] = "0" * 64
        corrupted = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        with (
            patch.object(Path, "read_bytes", return_value=corrupted),
            self.assertRaisesMessage(ValueError, "self-hash does not verify"),
        ):
            _verify_committed_authorization(
                expected_file_sha256=hashlib.sha256(corrupted).hexdigest()
            )

    def test_digest_and_self_hash_failures_are_distinguishable(self):
        """A caller must be able to tell which boundary refused."""
        document = json.loads(self.committed)
        document["authorization_sha256"] = "0" * 64
        corrupted = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        with patch.object(Path, "read_bytes", return_value=corrupted):
            with self.assertRaisesMessage(ValueError, "does not match its governed pin"):
                load_committed_gate8b_authorization()
            with self.assertRaisesMessage(ValueError, "self-hash does not verify"):
                _verify_committed_authorization(
                    expected_file_sha256=hashlib.sha256(corrupted).hexdigest()
                )

    def test_regeneration_is_byte_identical_to_the_committed_content(self):
        # 15
        self.assertEqual(self.committed, canonical_authorization_bytes(self.authorization))

    def test_artifact_records_the_governed_rules(self):
        # 13
        self.assertEqual(self.authorization["schema"], ARTIFACT_SCHEMA)
        self.assertEqual(self.authorization["successor_h1_requested_from"], "2009-12-30T22:00:00Z")
        self.assertEqual(self.authorization["successor_chunk_count"], EXPECTED_CHUNK_COUNT)
        self.assertEqual(
            self.authorization["successor_granularity_chunks"], {"D": 6, "H1": 120, "W": 6}
        )
        self.assertEqual(self.authorization["staged_execution_counts"], dict(EXPECTED_STAGE_COUNTS))
        self.assertEqual(self.authorization["max_attempts_per_chunk"], MAX_ATTEMPTS_PER_CHUNK)
        self.assertEqual(self.authorization["expected_attempt_count"], EXPECTED_CHUNK_COUNT)
        self.assertFalse(self.authorization["automatic_retry_permitted"])
        self.assertEqual(
            self.authorization["required_h1_warmup_observations"],
            REQUIRED_H1_WARMUP_OBSERVATIONS,
        )
        self.assertIsNone(self.authorization["calendar_exclusion_list"])
        self.assertFalse(self.authorization["strategy_outputs_consulted"])
        self.assertFalse(self.authorization["returns_consulted"])
        self.assertIn("does not authorize", self.authorization["authorization_scope"])
        self.assertIn("never discarded", self.authorization["warmup_acceptance_rule"])

    def test_artifact_carries_no_operational_or_sensitive_value(self):
        # 13
        text = self.committed.decode()
        for forbidden in (
            "token",
            "secret",
            "password",
            "api_key",
            "Authorization:",
            "http://",
            "https://",
            "oanda.com",
            "/Users/",
            "/home/",
            "provider_request_id",
            "account_id",
            "primary_key",
            "postgres",
        ):
            self.assertNotIn(forbidden, text, forbidden)
        for value in json.loads(self.committed).values():
            self.assertNotIsInstance(value, float)

    def test_altered_committed_bytes_fail_closed(self):
        # 16: an edited artifact never reaches regeneration — the pinned digest
        # refuses it first, which is the outer boundary working as intended.
        tampered = json.loads(self.committed)
        tampered["successor_h1_requested_from"] = "2009-12-30T21:00:00Z"
        encoded = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
        with (
            patch.object(Path, "read_bytes", return_value=encoded),
            self.assertRaisesMessage(ValueError, "does not match its governed pin"),
        ):
            load_committed_gate8b_authorization()

    def test_content_drift_is_caught_by_regeneration_when_the_digest_matches(self):
        # 16: past the digest and the self-hash, regeneration is the last check.
        drifted = json.loads(self.committed)
        drifted["successor_chunk_count"] = 131
        body = {k: v for k, v in drifted.items() if k != "authorization_sha256"}
        drifted["authorization_sha256"] = canonical_hash(body)
        encoded = json.dumps(drifted, sort_keys=True, separators=(",", ":")).encode()
        with (
            patch.object(Path, "read_bytes", return_value=encoded),
            self.assertRaisesMessage(ValueError, "does not reconstruct"),
        ):
            _verify_committed_authorization(
                expected_file_sha256=hashlib.sha256(encoded).hexdigest()
            )


class Gate8bIsolationTests(SimpleTestCase):
    """17, 18, 21: generation, staging, artifact building and loading must
    reach no database, no provider transport and no strategy output."""

    def test_no_database_connection_is_attempted(self):
        """17: this whole module is a SimpleTestCase, so Django already forbids
        a database connection. Prove it positively too: every entry point runs
        with connection establishment wired to raise."""
        from django.db.backends.base.base import BaseDatabaseWrapper

        def refuse(self, *args, **kwargs):
            raise AssertionError("a database connection was attempted")

        with patch.object(BaseDatabaseWrapper, "ensure_connection", refuse):
            plan = build_successor_discovery_plan()
            staged_discovery_membership(plan)
            verify_successor_plan_shape(plan)
            build_gate8b_authorization()
            load_committed_gate8b_authorization()

    def test_no_provider_client_or_transport_is_constructed(self):
        # 18
        import market.oanda as oanda

        with patch.object(oanda, "OandaClient", side_effect=AssertionError("client built")):
            build_gate8b_authorization()
            load_committed_gate8b_authorization()
        tree = module_ast()
        self.assertEqual(imported_modules(tree) & FORBIDDEN_TRANSPORT_IMPORTS, set())
        self.assertEqual(referenced_names(tree) & FORBIDDEN_TRANSPORT_NAMES, set())

    def test_module_reads_no_strategy_or_return_table(self):
        # 21
        names = referenced_names(module_ast())
        self.assertEqual(names & FORBIDDEN_STRATEGY_NAMES, set())
        self.assertEqual(names & FORBIDDEN_DERIVATION_NAMES, set())
