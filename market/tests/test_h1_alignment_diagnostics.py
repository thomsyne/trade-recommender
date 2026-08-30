import json
from datetime import UTC, datetime, timedelta
from datetime import timezone as datetime_timezone

from django.db import connection
from django.test import TestCase

from market.historical_discovery import (
    CANARY_ATTEMPT1_FETCHED_COUNT,
    CANARY_ATTEMPT1_MISALIGNED_COUNT,
    CANARY_V2_LOGICAL_KEY,
    DISCOVERY_STRUCTURAL_SAMPLE_LIMIT,
    DISCOVERY_V2_VERSION,
    DISCOVERY_VERSION,
    GOVERNING_CANARY_LOGICAL_KEY,
    DiscoveryResponseError,
    StructuralObservation,
    _h1_utc_whole_hour,
    _observation_aligned,
    _validate_response,
    build_replacement_discovery_plan,
    canonical_hash,
    canonical_timestamp,
    create_discovery_plan,
    logical_discovery_key,
    run_discovery_chunk,
)
from market.models import AuditEvent, HistoricalDiscoveryAttempt
from market.services import DatasetQualityError
from market.tests.test_replacement_canary_activation import (
    CANARY_START,
    MisalignedCanaryClient,
    build_superseded_state,
    seed_governed_market,
)

FORBIDDEN_MARKERS = (
    '"o":',
    '"h":',
    '"l":',
    '"c":',
    "bid_open",
    "ask_open",
    "authorization",
    "Bearer",
    "https://",
    "account",
    "token",
)


def evidence_for(chunk, request_id="alignment-test-request"):
    return {
        "endpoint_identity": (
            f"oanda-v20-practice:GET:/v3/instruments/{chunk.instrument.code}/candles"
        ),
        "http_method": "GET",
        "oanda_environment": "practice",
        "http_status": 200,
        "provider_request_id": request_id,
        "canonical_request_sha256": chunk.canonical_request_sha256,
    }


def standalone_h1_plan_payload():
    """A one-request, non-superseded plan carrying the exact canary H1
    request under a distinct version, used to exercise the failure audit
    round-trip without touching the gated replacement plan."""
    base = build_replacement_discovery_plan()
    item = json.loads(json.dumps(base["requests"][1]))
    version = "phase-2b1r-discovery-v9"
    request = item["canonical_request"]
    start = datetime.fromisoformat(request["from"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(request["to"].replace("Z", "+00:00"))
    item["ordinal"] = 1
    item["logical_discovery_key"] = logical_discovery_key(
        request_sha256=item["canonical_request_sha256"],
        instrument=request["instrument"],
        granularity=request["granularity"],
        requested_from=start,
        requested_to=end,
        discovery_version=version,
    )
    body = {
        key: value
        for key, value in base.items()
        if key not in {"requests", "plan_sha256", "canonical_request_manifest_sha256"}
    }
    body.update(
        discovery_version=version,
        identity="standalone-h1-diagnostics-plan",
        declared_chunk_count=1,
        requests=[item],
        canonical_request_manifest_sha256=canonical_hash([item]),
    )
    return {**body, "plan_sha256": canonical_hash(body)}


class H1AlignmentPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_governed_market("h1 alignment policy test")
        cls.superseded, cls.replacement, _ = build_superseded_state()
        cls.canary = cls.replacement.chunks.select_related("plan", "instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )
        cls.v1_h1 = cls.superseded.chunks.select_related("plan", "instrument").get(
            logical_key=GOVERNING_CANARY_LOGICAL_KEY
        )
        cls.v2_daily = cls.replacement.chunks.select_related("plan", "instrument").get(ordinal=1)
        cls.v2_weekly = (
            cls.replacement.chunks.select_related("plan", "instrument")
            .filter(granularity="W")
            .order_by("ordinal")
            .first()
        )

    def test_v2_h1_accepts_whole_hours_regardless_of_new_york_calendar(self):
        saturday_new_york = CANARY_START + timedelta(hours=33)
        observations = [
            StructuralObservation(CANARY_START, True, 1, True, True),
            StructuralObservation(saturday_new_york, True, 2, True, True),
        ]
        accepted, _ = _validate_response(self.canary, observations, evidence_for(self.canary))
        self.assertEqual(len(accepted), 2)
        self.assertTrue(_observation_aligned(self.canary, DISCOVERY_V2_VERSION, saturday_new_york))

    def test_v2_h1_rejects_subhour_components(self):
        for label, delta in (
            ("minute", timedelta(minutes=1)),
            ("second", timedelta(seconds=1)),
            ("microsecond", timedelta(microseconds=1)),
        ):
            with (
                self.subTest(component=label),
                self.assertRaises(DiscoveryResponseError) as raised,
            ):
                _validate_response(
                    self.canary,
                    [StructuralObservation(CANARY_START + delta, True, 1, True, True)],
                    evidence_for(self.canary),
                )
            self.assertIn("timestamp_misaligned", raised.exception.diagnostics["issue_counts"])

    def test_v2_h1_rejects_naive_and_non_utc_timestamps(self):
        naive = datetime(2010, 1, 4, 12)
        offset_aware = datetime(2010, 1, 4, 13, tzinfo=datetime_timezone(timedelta(hours=1)))
        self.assertFalse(_h1_utc_whole_hour(naive))
        self.assertFalse(_h1_utc_whole_hour(offset_aware))
        self.assertFalse(_observation_aligned(self.canary, DISCOVERY_V2_VERSION, naive))
        self.assertFalse(_observation_aligned(self.canary, DISCOVERY_V2_VERSION, offset_aware))
        with self.assertRaises(DiscoveryResponseError) as raised:
            _validate_response(
                self.canary,
                [StructuralObservation(offset_aware, True, 1, True, True)],
                evidence_for(self.canary),
            )
        self.assertIn("timestamp_misaligned", raised.exception.diagnostics["issue_counts"])

    def test_v1_h1_and_d_w_alignment_remain_unchanged(self):
        saturday_new_york = CANARY_START + timedelta(hours=33)
        weekday_open = CANARY_START
        self.assertFalse(_observation_aligned(self.v1_h1, DISCOVERY_VERSION, saturday_new_york))
        self.assertTrue(_observation_aligned(self.v1_h1, DISCOVERY_VERSION, weekday_open))
        daily_aligned = self.v2_daily.requested_from
        self.assertTrue(_observation_aligned(self.v2_daily, DISCOVERY_V2_VERSION, daily_aligned))
        self.assertFalse(
            _observation_aligned(
                self.v2_daily, DISCOVERY_V2_VERSION, daily_aligned + timedelta(hours=1)
            )
        )
        weekly_aligned = self.v2_weekly.requested_from
        self.assertTrue(_observation_aligned(self.v2_weekly, DISCOVERY_V2_VERSION, weekly_aligned))
        self.assertFalse(
            _observation_aligned(
                self.v2_weekly, DISCOVERY_V2_VERSION, weekly_aligned + timedelta(days=1)
            )
        )


class StructuralDiagnosticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = seed_governed_market("structural diagnostics test")
        cls.superseded, cls.replacement, _ = build_superseded_state()
        cls.canary = cls.replacement.chunks.select_related("plan", "instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )

    def ledger_diagnostics(self):
        client = MisalignedCanaryClient(self.canary.canonical_request_sha256)
        observations, _ = client.fetch_historical_inventory(
            "AUD_USD", "H1", self.canary.requested_from, self.canary.requested_to
        )
        with self.assertRaises(DiscoveryResponseError) as raised:
            _validate_response(self.canary, observations, evidence_for(self.canary))
        return observations, raised.exception.diagnostics

    def test_diagnostics_carry_allowlisted_fields_and_reconstructable_hashes(self):
        observations, diagnostics = self.ledger_diagnostics()
        self.assertEqual(diagnostics["observation_count"], CANARY_ATTEMPT1_FETCHED_COUNT)
        self.assertEqual(
            diagnostics["issue_counts"],
            {"timestamp_misaligned": CANARY_ATTEMPT1_MISALIGNED_COUNT},
        )
        self.assertEqual(len(diagnostics["issue_samples"]), CANARY_ATTEMPT1_MISALIGNED_COUNT)
        self.assertFalse(diagnostics["diagnostic_truncated"])
        observed = sorted(canonical_timestamp(item.timestamp) for item in observations)
        invalid = sorted(
            canonical_timestamp(item.timestamp) for item in observations if item.timestamp.minute
        )
        self.assertEqual(diagnostics["first_observed_timestamp"], observed[0])
        self.assertEqual(diagnostics["last_observed_timestamp"], observed[-1])
        self.assertEqual(diagnostics["observed_timestamp_set_sha256"], canonical_hash(observed))
        self.assertEqual(diagnostics["invalid_timestamp_set_sha256"], canonical_hash(invalid))
        self.assertEqual(
            sum(diagnostics["issue_counts_by_new_york_weekday"].values()),
            CANARY_ATTEMPT1_MISALIGNED_COUNT,
        )
        self.assertEqual(
            sum(diagnostics["issue_counts_by_new_york_hour"].values()),
            CANARY_ATTEMPT1_MISALIGNED_COUNT,
        )
        self.assertEqual(
            diagnostics["issue_counts_by_utc_offset"],
            {"-14400": CANARY_ATTEMPT1_MISALIGNED_COUNT},
        )
        expected_sample_keys = {
            "code",
            "index",
            "timestamp_utc",
            "timestamp_new_york",
            "new_york_weekday",
            "utc_offset_seconds",
            "complete",
            "volume",
            "bid_present",
            "ask_present",
        }
        for sample in diagnostics["issue_samples"]:
            self.assertEqual(set(sample), expected_sample_keys)
            self.assertEqual(sample["code"], "timestamp_misaligned")
            self.assertEqual(sample["utc_offset_seconds"], -14400)
            self.assertTrue(sample["complete"])
            self.assertEqual(sample["volume"], 1)
            self.assertTrue(sample["bid_present"])
            self.assertTrue(sample["ask_present"])
            self.assertEqual(observations[sample["index"]].timestamp.minute, 30)

    def test_offset_grouping_distinguishes_est_and_edt(self):
        observations = [
            StructuralObservation(datetime(2010, 1, 4, 12, 30, tzinfo=UTC), True, 1, True, True),
            StructuralObservation(datetime(2010, 6, 7, 12, 30, tzinfo=UTC), True, 1, True, True),
        ]
        with self.assertRaises(DiscoveryResponseError) as raised:
            _validate_response(self.canary, observations, evidence_for(self.canary))
        diagnostics = raised.exception.diagnostics
        self.assertEqual(diagnostics["issue_counts_by_utc_offset"], {"-18000": 1, "-14400": 1})
        offsets = {
            sample["timestamp_utc"]: sample["utc_offset_seconds"]
            for sample in diagnostics["issue_samples"]
        }
        self.assertEqual(offsets["2010-01-04T12:30:00Z"], -18000)
        self.assertEqual(offsets["2010-06-07T12:30:00Z"], -14400)

    def test_diagnostic_truncation_is_deterministic_and_bounded(self):
        observations = [
            StructuralObservation(
                CANARY_START + timedelta(hours=index, minutes=30), True, 1, True, True
            )
            for index in range(300)
        ]
        with self.assertRaises(DiscoveryResponseError) as raised:
            _validate_response(self.canary, observations, evidence_for(self.canary))
        diagnostics = raised.exception.diagnostics
        self.assertEqual(diagnostics["issue_counts"], {"timestamp_misaligned": 300})
        self.assertEqual(len(diagnostics["issue_samples"]), DISCOVERY_STRUCTURAL_SAMPLE_LIMIT)
        self.assertTrue(diagnostics["diagnostic_truncated"])
        self.assertEqual(
            [sample["index"] for sample in diagnostics["issue_samples"]],
            list(range(DISCOVERY_STRUCTURAL_SAMPLE_LIMIT)),
        )

    def test_diagnostics_contain_no_prices_secrets_or_raw_material(self):
        _, diagnostics = self.ledger_diagnostics()
        serialized = json.dumps(diagnostics, sort_keys=True)
        for marker in FORBIDDEN_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_failure_audit_round_trips_revised_diagnostics_through_postgresql(self):
        plan = create_discovery_plan(standalone_h1_plan_payload())
        chunk = plan.chunks.select_related("instrument").get()
        try:
            run_discovery_chunk(
                chunk.logical_key,
                MisalignedCanaryClient(chunk.canonical_request_sha256),
            )
        except DatasetQualityError:
            pass
        attempt = HistoricalDiscoveryAttempt.objects.get(chunk=chunk)
        event = AuditEvent.objects.get(
            event_type="market.historical_discovery_failed",
            subject_id=str(attempt.pk),
        )
        diagnostics = event.payload["diagnostics"]
        self.assertEqual(
            diagnostics["issue_counts"],
            {"timestamp_misaligned": CANARY_ATTEMPT1_MISALIGNED_COUNT},
        )
        self.assertEqual(len(diagnostics["issue_samples"]), CANARY_ATTEMPT1_MISALIGNED_COUNT)
        serialized = json.dumps(diagnostics, sort_keys=True)
        for marker in FORBIDDEN_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_postgresql_rejects_forged_diagnostic_schemas(self):
        _, diagnostics = self.ledger_diagnostics()
        valid = json.loads(json.dumps(diagnostics))
        forged_extra = {**valid, "raw_body": "forged"}
        forged_missing = {k: v for k, v in valid.items() if k != "issue_counts"}
        forged_count = {**valid, "observation_count": 1}
        forged_truncated = {**valid, "diagnostic_truncated": True}
        forged_sample = json.loads(json.dumps(valid))
        forged_sample["issue_samples"][0]["price"] = "1.2345"
        forged_sha = {**valid, "observed_timestamp_set_sha256": "not-a-hash"}

        def variant(**overrides):
            clone = json.loads(json.dumps(valid))
            clone["issue_samples"][0].update(overrides)
            return clone

        unknown_code = json.loads(json.dumps(valid))
        unknown_code["issue_counts"] = {"raw_body_leak": CANARY_ATTEMPT1_MISALIGNED_COUNT}
        for sample in unknown_code["issue_samples"]:
            sample["code"] = "raw_body_leak"
        fabricated_grouping = json.loads(json.dumps(valid))
        fabricated_grouping["issue_counts_by_utc_offset"] = {"-14400": 9999}
        inconsistent_new_york = variant(timestamp_new_york="2010-06-01T08:30:00-04:00")
        wrong_offset = variant(utc_offset_seconds=-18000)
        wrong_weekday = variant(new_york_weekday=99)
        negative_index = variant(index=-1)
        negative_volume = variant(volume=-5)
        cases = (
            ("extra-key", forged_extra),
            ("missing-key", forged_missing),
            ("wrong-count", forged_count),
            ("wrong-truncated", forged_truncated),
            ("sample-extra-key", forged_sample),
            ("bad-sha", forged_sha),
            ("unknown-issue-code", unknown_code),
            ("negative-index", negative_index),
            ("weekday-99", wrong_weekday),
            ("negative-volume", negative_volume),
            ("inconsistent-new-york-timestamp", inconsistent_new_york),
            ("wrong-utc-offset", wrong_offset),
            ("fabricated-grouping-counts", fabricated_grouping),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT market_discovery_structural_diagnostics_valid(%s::jsonb, %s)",
                [json.dumps(valid), CANARY_ATTEMPT1_FETCHED_COUNT],
            )
            self.assertTrue(cursor.fetchone()[0])
            for label, forged in cases:
                with self.subTest(case=label):
                    cursor.execute(
                        "SELECT market_discovery_structural_diagnostics_valid(%s::jsonb, %s)",
                        [json.dumps(forged), CANARY_ATTEMPT1_FETCHED_COUNT],
                    )
                    self.assertFalse(cursor.fetchone()[0])
