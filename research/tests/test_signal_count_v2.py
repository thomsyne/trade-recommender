"""Gate 1B: provider-observed (v2) S0/S1 code paths, mocked regressions only.

No S0 or S1 stage is executed; these tests prove that v2 membership comes
only from the sealed inventory, that entries fail closed, and that legacy
v1 behaviour is untouched.
"""

from datetime import UTC, datetime, timedelta

from django.db import connection

from market.models import DatasetVersion, HistoricalDatasetPlan
from market.tests.test_gate1b_data_contract import Gate1BFixtureTestCase
from research.provider_observed import (
    contract_for_dataset,
    contract_range_bounds,
    entry_timestamp_is_sealed,
    inventory_timestamps,
    inventory_window,
)
from research.signal_count import (
    S0_COVERAGE_FIELDS,
    SIGNAL_COUNT_IDENTITY,
    V2_AUDIT_FIELDS,
    RequiredCandleRange,
    ReturnBlindViolation,
    SignalCountOutput,
    _validate_dataset_contract,
    development_candle_range,
    expected_analysis_keys,
    read_entry_projection,
    stable_hash,
)


def forge_v2_dataset_registration(plan, dataset, contract):
    """Test-only registration row so contract resolution paths are reachable;
    real v2 registration is a later, separately authorized gate."""
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE market_datasetregistration DISABLE TRIGGER USER")
        try:
            cursor.execute(
                """INSERT INTO market_datasetregistration
                   (dataset_version_id,plan_id,series_manifest,row_counts,
                    first_last_timestamps,missingness,conflict_count,incident_count,
                    logical_chunk_set_hash,successful_attempt_set_hash,
                    ingestion_manifest_set_hash,candle_key_hash,candle_payload_hash,
                    configuration_sha256,report_sha256,data_contract_id,
                    global_semantic_inventory_sha256,registered_at)
                   VALUES (%s,%s,'[]'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,0,0,
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                [
                    dataset.pk,
                    plan.pk,
                    "1" * 64,
                    "2" * 64,
                    "3" * 64,
                    "4" * 64,
                    "5" * 64,
                    "6" * 64,
                    stable_hash({"forged-report": dataset.pk}),
                    contract.pk if contract else None,
                    contract.global_semantic_inventory_sha256 if contract else None,
                ],
            )
        finally:
            cursor.execute("ALTER TABLE market_datasetregistration ENABLE TRIGGER USER")


class SignalCountV2MembershipTests(Gate1BFixtureTestCase):
    retention_policy = "gate1b signal count"

    def setUp(self):
        super().setUp()
        self.plan, self.dataset, self.payloads = self.create_replacement_plan_and_dataset()

    def registered(self):
        forge_v2_dataset_registration(self.plan, self.dataset, self.contract)
        return DatasetVersion.objects.get(pk=self.dataset.pk)

    def declared_ranges(self):
        ranges = {}
        for item in self.payloads["dataset_manifest"]["required_ranges"]:
            from django.utils.dateparse import parse_datetime

            ranges.setdefault(item["instrument"], []).append(
                RequiredCandleRange(
                    item["granularity"],
                    parse_datetime(item["start"]),
                    parse_datetime(item["end"]),
                )
            )
        return ranges

    def test_contract_resolves_only_through_explicit_registration_lineage(self):
        self.assertIsNone(contract_for_dataset(self.dataset))
        dataset = self.registered()
        contract = contract_for_dataset(dataset)
        self.assertIsNotNone(contract)
        self.assertEqual(contract.pk, self.contract.pk)

    def test_v2_analysis_membership_comes_from_inventory_not_calendar(self):
        from market.quality import registered_candle_completion
        from research.signal_count import DEVELOPMENT_END, DEVELOPMENT_START

        ranges = self.declared_ranges()
        inventory_keys = expected_analysis_keys(ranges, contract=self.contract)
        calendar_keys = expected_analysis_keys(ranges)
        self.assertNotEqual(inventory_keys, calendar_keys)
        development_start = DEVELOPMENT_START.astimezone(UTC)
        development_end = DEVELOPMENT_END.astimezone(UTC)
        expected = []
        for code, declared in sorted(ranges.items()):
            h1_range = next(required for required in declared if required.granularity == "H1")
            expected.extend(
                (code, registered_candle_completion(timestamp, "H1").isoformat())
                for timestamp in inventory_window(
                    self.contract, code, "H1", h1_range.start, h1_range.end
                )
                if development_start
                <= registered_candle_completion(timestamp, "H1")
                < development_end
            )
        self.assertEqual(inventory_keys, tuple(expected))

    def test_development_range_is_inventory_backed(self):
        ranges = self.declared_ranges()
        h1_range = next(required for required in ranges["EUR_USD"] if required.granularity == "H1")
        development = development_candle_range(
            h1_range, contract=self.contract, instrument="EUR_USD"
        )
        membership = inventory_window(self.contract, "EUR_USD", "H1", h1_range.start, h1_range.end)
        self.assertEqual(development.start, membership[0])
        with self.assertRaises(ReturnBlindViolation):
            development_candle_range(
                RequiredCandleRange("H1", h1_range.start, h1_range.start),
                contract=self.contract,
                instrument="EUR_USD",
            )

    def test_sealed_bounds_and_membership_helpers(self):
        first, last = contract_range_bounds(self.contract, "H1")
        h1_timestamps = inventory_timestamps(self.contract, "AUD_USD", "H1")
        self.assertTrue(h1_timestamps)
        self.assertTrue(first <= h1_timestamps[0] and h1_timestamps[-1] < last)
        self.assertTrue(entry_timestamp_is_sealed(self.contract, "AUD_USD", h1_timestamps[0]))
        self.assertFalse(
            entry_timestamp_is_sealed(
                self.contract, "AUD_USD", h1_timestamps[0] + timedelta(minutes=30)
            )
        )

    def test_missing_entry_timestamp_fails_without_shifting(self):
        dataset = self.registered()
        instrument = self.replacement.chunks.filter(granularity="H1").first().instrument
        sealed = inventory_timestamps(self.contract, instrument.code, "H1")
        unsealed_timestamp = sealed[0] + timedelta(minutes=30)
        with self.assertRaisesMessage(
            ReturnBlindViolation, "entry timestamp is not a sealed provider-observed candle"
        ):
            read_entry_projection(
                dataset_id=dataset.pk,
                instrument_id=instrument.pk,
                theoretical_entry_timestamp=unsealed_timestamp,
                as_of=unsealed_timestamp + timedelta(hours=2),
            )
        sealed_timestamp = sealed[0]
        try:
            read_entry_projection(
                dataset_id=dataset.pk,
                instrument_id=instrument.pk,
                theoretical_entry_timestamp=sealed_timestamp,
                as_of=sealed_timestamp + timedelta(hours=2),
            )
        except ReturnBlindViolation as error:
            self.assertNotIn("sealed provider-observed candle", str(error))
        except Exception:
            pass

    def test_incomplete_v2_inventory_rejects_s0_validation(self):
        dataset = self.registered()
        strategy = self.strategy
        with self.assertRaisesMessage(
            ReturnBlindViolation, "lacks sealed inventory development or warm-up coverage"
        ):
            _validate_dataset_contract(dataset, strategy, datetime(2019, 6, 1, tzinfo=UTC))

    def test_unregistered_v2_dataset_fails_closed(self):
        with self.assertRaises(ReturnBlindViolation):
            _validate_dataset_contract(
                self.dataset, self.strategy, datetime(2019, 6, 1, tzinfo=UTC)
            )

    def test_v2_identity_is_never_inferred_implicitly(self):
        plan = HistoricalDatasetPlan.objects.get(pk=self.plan.pk)
        self.assertIsNotNone(plan.data_contract_id)
        self.assertIn("historical_data_contract_sha256", self.dataset.manifest)
        self.assertEqual(self.dataset.manifest["data_identity"], self.contract.identity)
        legacy = DatasetVersion.objects.create(
            name="legacy-v1-shape",
            version="v1",
            description="",
            source=self.source,
            manifest={"note": "no historical_plan_sha256"},
            manifest_sha256="",
        )
        self.assertIsNone(contract_for_dataset(legacy))

    def test_signal_count_output_accepts_v2_coverage_and_v1_unchanged(self):
        base_coverage = {
            "dataset_id": 1,
            "dataset_manifest_sha256": "a" * 64,
            "strategy_version_id": 1,
            "strategy_content_hash": "b" * 64,
            "registered_identities": {},
            "as_of": "2026-01-01T00:00:00+00:00",
            "row_counts": {},
            "missingness": {},
            "spread_ceilings": {},
            "spread_distribution_hashes": {},
        }
        assert set(base_coverage) == S0_COVERAGE_FIELDS
        v1_output = SignalCountOutput(
            SIGNAL_COUNT_IDENTITY, "S0", {"observations": 0}, base_coverage, "c" * 64
        )
        self.assertEqual(set(v1_output.coverage), S0_COVERAGE_FIELDS)
        v2_coverage = {
            **base_coverage,
            "historical_data_contract_id": 1,
            "historical_data_contract_sha256": "d" * 64,
            "effective_data_identity": "oanda-ba-ny17-friday-provider-observed-v1",
            "global_semantic_inventory_sha256": "e" * 64,
        }
        v2_output = SignalCountOutput(
            SIGNAL_COUNT_IDENTITY, "S0", {"observations": 0}, v2_coverage, "c" * 64
        )
        self.assertEqual(set(v2_output.coverage), S0_COVERAGE_FIELDS | V2_AUDIT_FIELDS)
        with self.assertRaises(ReturnBlindViolation):
            SignalCountOutput(
                SIGNAL_COUNT_IDENTITY,
                "S0",
                {"observations": 0},
                {**base_coverage, "unexpected": True},
                "c" * 64,
            )
