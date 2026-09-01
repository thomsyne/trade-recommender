"""Gate 8D3: the committed final-outcome artifact must be tamper-evident.

The loader's job is to refuse anything that is not the exact committed bytes,
so most of these tests corrupt the artifact in one specific way and prove which
layer catches it. Fixtures stay small: the artifact's own content is fixed, and
nothing here rebuilds 365,055 observations — the single complete reconstruction
against the real research rows is performed once, read-only, outside the suite.
"""

import hashlib
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from market.historical_discovery import canonical_hash
from market.provider_observed_outcome import (
    ARTIFACT_NAME,
    ARTIFACT_SCHEMA,
    EXPECTED_CHUNK_COUNT,
    EXPECTED_EARLIER_PER_INSTRUMENT,
    EXPECTED_EXTENSION_OBSERVATIONS,
    EXPECTED_GRANULARITY_OBSERVATIONS,
    EXPECTED_OBSERVATION_TOTAL,
    EXPECTED_RESTRICTED_OBSERVATION_TOTAL,
    OUTCOME_ARTIFACT_SHA256,
    SNAPSHOT_CONVENTION,
    SNAPSHOT_SECTIONS,
    _verify_committed_outcome,
    gate8d3_outcome_path,
    load_committed_gate8d3_outcome,
)


def committed_document():
    return json.loads(gate8d3_outcome_path().read_bytes())


def encode(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def reseal(document):
    """A forgery that is internally consistent: its self-hash is recomputed over
    the tampered body, so only the governed file pin can refuse it."""
    body = {key: value for key, value in document.items() if key != "outcome_sha256"}
    return {**body, "outcome_sha256": canonical_hash(body)}


class Gate8d3ArtifactTests(SimpleTestCase):
    def test_the_committed_artifact_loads_and_its_self_hash_reconstructs(self):
        # 1
        document = load_committed_gate8d3_outcome()
        self.assertEqual(document["schema"], ARTIFACT_SCHEMA)
        body = {key: value for key, value in document.items() if key != "outcome_sha256"}
        self.assertEqual(document["outcome_sha256"], canonical_hash(body))
        committed = gate8d3_outcome_path().read_bytes()
        self.assertEqual(hashlib.sha256(committed).hexdigest(), OUTCOME_ARTIFACT_SHA256)
        self.assertEqual(committed, encode(document))

    def test_the_public_loader_takes_no_digest_and_no_bypass(self):
        # 2
        import inspect

        signature = inspect.signature(load_committed_gate8d3_outcome)
        self.assertEqual(list(signature.parameters), [])
        with self.assertRaisesMessage(ValueError, "does not match its governed pin"):
            _verify_committed_outcome(expected_file_sha256="0" * 64)

    def test_a_corrupt_or_absent_self_hash_is_refused(self):
        # 3
        document = committed_document()
        for mutated in (
            {**document, "outcome_sha256": "0" * 64},
            {key: value for key, value in document.items() if key != "outcome_sha256"},
            {**document, "outcome_sha256": 17},
        ):
            with patch.object(
                type(gate8d3_outcome_path()), "read_bytes", return_value=encode(mutated)
            ):
                data = encode(mutated)
                digest = hashlib.sha256(data).hexdigest()
                with self.assertRaises(ValueError):
                    _verify_committed_outcome(expected_file_sha256=digest)

    def test_an_internally_consistent_forgery_is_refused_by_the_file_pin(self):
        # 4
        forged = reseal({**committed_document(), "successor_discovery_plan_sha256": "f" * 64})
        body = {key: value for key, value in forged.items() if key != "outcome_sha256"}
        self.assertEqual(forged["outcome_sha256"], canonical_hash(body))
        with patch.object(type(gate8d3_outcome_path()), "read_bytes", return_value=encode(forged)):
            with self.assertRaisesMessage(ValueError, "does not match its governed pin"):
                load_committed_gate8d3_outcome()

    def test_non_canonical_bytes_are_refused_even_with_a_matching_pin(self):
        # 5: content that survives the file and self-hash layers because both are
        # computed over the tampered bytes still fails canonical determinism
        document = committed_document()
        data = json.dumps(document, sort_keys=True, separators=(", ", ": ")).encode()
        digest = hashlib.sha256(data).hexdigest()
        with patch.object(type(gate8d3_outcome_path()), "read_bytes", return_value=data):
            with self.assertRaisesMessage(ValueError, "is not canonical JSON"):
                _verify_committed_outcome(expected_file_sha256=digest)

    def _tamper(self, mutate):
        document = committed_document()
        mutate(document)
        forged = reseal(document)
        with patch.object(type(gate8d3_outcome_path()), "read_bytes", return_value=encode(forged)):
            with self.assertRaisesMessage(ValueError, "does not match its governed pin"):
                load_committed_gate8d3_outcome()

    def test_chunk_omission_is_refused(self):
        # 6
        self._tamper(lambda d: d["chunk_records"].pop(40))

    def test_chunk_duplication_is_refused(self):
        # 7
        self._tamper(lambda d: d["chunk_records"].append(dict(d["chunk_records"][3])))

    def test_chunk_reorder_is_refused(self):
        # 8
        def swap(document):
            records = document["chunk_records"]
            records[0], records[1] = records[1], records[0]

        self._tamper(swap)

    def test_a_changed_plan_manifest_count_or_aggregate_is_refused(self):
        # 9
        for mutate in (
            lambda d: d.__setitem__("successor_request_manifest_sha256", "a" * 64),
            lambda d: d.__setitem__("successor_global_semantic_inventory_sha256", "b" * 64),
            lambda d: d["completion"].__setitem__("accepted_inventories", 131),
            lambda d: d["observations"].__setitem__("total", 365054),
        ):
            self._tamper(mutate)

    def test_a_changed_per_chunk_inventory_or_evidence_hash_is_refused(self):
        # 10
        for field in (
            "timestamp_set_sha256",
            "structural_observation_sha256",
            "semantic_inventory_sha256",
            "terminal_event_sha256",
            "operational_evidence_sha256",
        ):
            self._tamper(lambda d, f=field: d["chunk_records"][7].__setitem__(f, "c" * 64))

    def test_the_cross_plan_semantic_distinction_is_stated_and_represented(self):
        # 11
        document = load_committed_gate8d3_outcome()
        self.assertIn("plan-bound", document["semantic_hash_statement"])
        unchanged = [r for r in document["chunk_records"] if r["chunk_role"] == "unchanged_range"]
        self.assertEqual(len(unchanged), 126)
        for record in unchanged:
            # identical content: identical request SHA and identical content hashes
            self.assertEqual(
                record["canonical_request_sha256"], record["predecessor_canonical_request_sha256"]
            )
            self.assertEqual(
                record["timestamp_set_sha256"], record["predecessor_timestamp_set_sha256"]
            )
            self.assertEqual(
                record["structural_observation_sha256"],
                record["predecessor_structural_observation_sha256"],
            )
            # but distinct plan identity, so distinct logical key
            self.assertNotEqual(
                record["logical_discovery_key"], record["predecessor_logical_discovery_key"]
            )

    def test_the_six_instrument_warmup_records_are_complete(self):
        # 12
        document = load_committed_gate8d3_outcome()
        warmup = document["warmup_proof"]
        self.assertEqual(len(warmup), 6)
        self.assertEqual(
            [item["instrument"] for item in warmup], sorted(i["instrument"] for i in warmup)
        )
        for item in warmup:
            self.assertEqual(
                item["earlier_completed_observations"], EXPECTED_EARLIER_PER_INSTRUMENT
            )
            self.assertEqual(item["predecessor_warmup_observations"], 8)
            self.assertEqual(item["combined_completed_warmup_observations"], 25)
            self.assertEqual(item["required_warmup_observations"], 14)
            self.assertEqual(item["missing_overlap_timestamps"], 0)
            self.assertEqual(item["extra_overlap_timestamps"], 0)
            self.assertEqual(item["volume_mismatches"], 0)
            self.assertEqual(item["completeness_mismatches"], 0)
            self.assertEqual(item["presence_mismatches"], 0)
            self.assertEqual(len(item["restricted_overlap_sha256"]), 64)

    def test_the_126_exact_content_mappings_are_recorded(self):
        # 13
        document = load_committed_gate8d3_outcome()
        records = document["chunk_records"]
        self.assertEqual(len(records), EXPECTED_CHUNK_COUNT)
        self.assertEqual([r["ordinal"] for r in records], sorted(r["ordinal"] for r in records))
        self.assertEqual(len({r["ordinal"] for r in records}), EXPECTED_CHUNK_COUNT)
        self.assertEqual(len({r["logical_discovery_key"] for r in records}), EXPECTED_CHUNK_COUNT)
        unchanged = [r for r in records if r["chunk_role"] == "unchanged_range"]
        extended = [r for r in records if r["chunk_role"] == "extended_first_h1"]
        self.assertEqual((len(unchanged), len(extended)), (126, 6))
        self.assertTrue(all(r["content_identical_to_predecessor"] for r in unchanged))
        self.assertTrue(all(r["predecessor_overlap_identical"] for r in extended))
        self.assertTrue(all(r["attempt_number"] == 1 for r in records))
        self.assertTrue(all(r["run_status"] == "succeeded" for r in records))
        self.assertEqual(
            document["observations"]["by_granularity"], EXPECTED_GRANULARITY_OBSERVATIONS
        )
        self.assertEqual(document["observations"]["total"], EXPECTED_OBSERVATION_TOTAL)
        self.assertEqual(
            document["observations"]["restricted_predecessor_equivalent"],
            EXPECTED_RESTRICTED_OBSERVATION_TOTAL,
        )
        self.assertEqual(
            document["observations"]["extension_observations"], EXPECTED_EXTENSION_OBSERVATIONS
        )

    def test_the_snapshot_section_list_is_exactly_the_approved_23_in_order(self):
        # 14
        document = load_committed_gate8d3_outcome()
        snapshot = document["sectioned_snapshot"]
        self.assertEqual(snapshot["convention"], SNAPSHOT_CONVENTION)
        self.assertEqual(snapshot["section_count"], 23)
        self.assertEqual(
            snapshot["section_order"], [name for name, _t, _a, _o in SNAPSHOT_SECTIONS]
        )
        self.assertEqual(len(SNAPSHOT_SECTIONS), 23)
        self.assertEqual(len({name for name, _t, _a, _o in SNAPSHOT_SECTIONS}), 23)

    def test_a_changed_section_order_name_or_hash_is_refused(self):
        # 15
        def reorder(document):
            order = document["sectioned_snapshot"]["section_order"]
            order[0], order[5] = order[5], order[0]

        self._tamper(reorder)
        self._tamper(
            lambda d: d["sectioned_snapshot"]["section_order"].__setitem__(2, "renamed_section")
        )
        self._tamper(
            lambda d: d["sectioned_snapshot"].__setitem__("sectioned_post_gate8d2_sha256", "d" * 64)
        )

    def test_the_empty_section_representation_is_pinned(self):
        # 16
        snapshot = load_committed_gate8d3_outcome()["sectioned_snapshot"]
        self.assertEqual(snapshot["empty_sections"], ["schedules"])
        self.assertIn("JSON null", snapshot["empty_section_rule"])
        self.assertIn("never", snapshot["empty_section_rule"])

    def test_the_continuity_anchors_and_baseline_are_pinned_and_distinguished(self):
        # 17, 18
        snapshot = load_committed_gate8d3_outcome()["sectioned_snapshot"]
        self.assertEqual(
            snapshot["legacy_whole_object_pre_gate8d2_sha256"],
            "a80b1dcd9ae3297652b61b3f74a341adc288eb908ffa6a8750bc9e5a08897438",
        )
        self.assertEqual(
            snapshot["sectioned_pre_gate8d2_sha256"],
            "b0405e22cb9eee52fd40bba4891bed499ef8d649f8457a7606cc196c2550c503",
        )
        self.assertEqual(
            snapshot["sectioned_post_gate8d2_sha256"],
            "2d44278d1fda6046ff7c21759decc77a6c8ab966cb7ab473b316ce7131601292",
        )
        self.assertNotEqual(
            snapshot["legacy_whole_object_pre_gate8d2_sha256"],
            snapshot["sectioned_pre_gate8d2_sha256"],
        )
        self.assertIn("not numerically comparable", snapshot["comparability_statement"])
        self.assertIn("logical discovery key", snapshot["pre_gate8d2_content_definition"])

    def test_the_second_snapshot_implementation_is_described_without_overclaim(self):
        # 19: the artifact must say exactly what implementation B proves, and must
        # not present it as validating the section table it shares with A
        snapshot = load_committed_gate8d3_outcome()["sectioned_snapshot"]
        statement = snapshot["independent_reconstruction"]
        # what B proves
        self.assertIn("23 separately issued single-section statements", statement)
        self.assertIn("agrees across languages", statement)
        self.assertIn("canonical_hash", statement)
        self.assertIn("SQL NULL section hash surfaces as Python None", statement)
        # what B shares, stated plainly
        self.assertIn("SNAPSHOT_SECTIONS", statement)
        self.assertIn("section_hash_sql", statement)
        for shared in (
            "section enumeration",
            "table and alias definitions",
            "per-section SQL construction",
            "ordering",
        ):
            self.assertIn(shared, statement)
        self.assertIn("would appear identically in both", statement)
        # and who did validate the section table
        self.assertIn("separate transcription", statement)
        self.assertIn("acceptance review", statement)
        self.assertNotIn("B independently restates the section list", statement)
        self.assertIn("not a claim of indefinite scalability", snapshot["limit_statement"])

    def test_the_module_docstring_matches_the_artifact_claim(self):
        # the generated wording and the code that generates it must not drift
        from market.provider_observed_outcome import sectioned_snapshot_independent

        docstring = sectioned_snapshot_independent.__doc__
        self.assertIn("What B does not prove", docstring)
        self.assertIn("SNAPSHOT_SECTIONS", docstring)
        self.assertIn("acceptance review", docstring)
        self.assertNotIn("What B checks independently is everything above that", docstring)

    def test_the_report_command_is_read_only_and_builds_no_provider_client(self):
        # 20
        import market.oanda as oanda

        buffer = StringIO()
        with patch.object(oanda, "OandaClient", side_effect=AssertionError("client built")):
            call_command("report_gate8d3_outcome", stdout=buffer)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["artifact"], ARTIFACT_NAME)
        self.assertEqual(payload["chunk_records"], EXPECTED_CHUNK_COUNT)
        self.assertEqual(payload["completion"]["accepted_inventories"], EXPECTED_CHUNK_COUNT)
        self.assertIn("canonical form", payload["verified"])

    def test_the_artifact_carries_no_operational_identifier_or_sensitive_content(self):
        # 21
        import re

        raw = gate8d3_outcome_path().read_text()
        document = load_committed_gate8d3_outcome()
        for pattern, label in (
            (r"\b[0-9a-f]{40}-[0-9a-f]{32}\b", "provider token"),
            (r"\b\d{3}-\d{3}-\d{7}-\d{3}\b", "account identifier"),
            (r"(?i)bearer\s", "authorization header"),
            (r"/Users/|/home/|oluwatomisintaiwo", "local path or username"),
            (r"(?i)https?://|oanda\.com|fxpractice|fxtrade", "url or provider hostname"),
            (r"(?i)\"(password|secret|token|api_key)\"", "credential field"),
            (r"(?i)trade_recommender_research|127\.0\.0\.1|5432", "database name or endpoint"),
            (r"\"(open|high|low|close|mid|return|pnl)\"\s*:", "price or return field"),
        ):
            self.assertIsNone(re.search(pattern, raw), f"artifact contains {label}")
        for record in document["chunk_records"]:
            for forbidden in (
                "id",
                "attempt_id",
                "chunk_id",
                "inventory_id",
                "ingestion_run_id",
                "provider_request_id",
                "created_at",
                "finished_at",
                "started_at",
            ):
                self.assertNotIn(forbidden, record)

    def test_the_artifact_disclaims_authority_and_records_the_withheld_transitions(self):
        # 22
        document = load_committed_gate8d3_outcome()
        self.assertIn("not database authority", document["authority_statement"])
        self.assertIn("Gate 8D3'", document["authority_statement"])
        self.assertIn("No S0 execution", document["strategy_attestation"])
        completion = document["completion"]
        self.assertFalse(completion["plan_sealed"])
        self.assertEqual(completion["plan_approvals"], 0)
        self.assertEqual(completion["plan_registrations"], 0)
        self.assertEqual(completion["successor_bound_contracts"], 0)
        self.assertEqual(completion["attempts_beyond_first"], 0)
        self.assertEqual(completion["failed_or_quarantined_runs"], 0)
        self.assertEqual(completion["running_runs"], 0)
        self.assertEqual(completion["missing_inventories"], 0)
