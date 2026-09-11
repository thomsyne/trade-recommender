import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from assessments.models import (
    EligibleTradeIntentCandidate,
    MultiTimeframeAssessment,
)
from assessments.services import (
    append_reviewed_eligibility,
    assess,
    audit_integrity,
    register_method,
    replay,
)
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.tests.test_live_observations import make_market


class DatabaseBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, _ = make_market()

    def empty_eligibility(self):
        now = timezone.now()
        return append_reviewed_eligibility(
            self.instrument,
            era="phase6a-canonical-empty-v1",
            entries=[],
            decision_known_at=now,
            phase55_decision_sha256=identity_digest([]),
            phase55_manifest_sha256=identity_digest({}),
            admission_provenance_sha256=identity_digest("canonical-empty-no-phase55-outcome"),
        )

    def frozen_snapshot(self):
        return compute_market_state(
            self.instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]

    def test_database_clock_no_backdating_immutable_and_empty_default_replays(self):
        eligibility = self.empty_eligibility()
        self.assertGreaterEqual(eligibility.valid_from, eligibility.decision_known_at)
        snapshot = self.frozen_snapshot()
        row, candidate, created = assess(snapshot.pk, eligibility.pk)
        again, again_candidate, again_created = assess(snapshot.pk, eligibility.pk)
        self.assertTrue(created)
        self.assertFalse(again_created)
        self.assertEqual(row.pk, again.pk)
        self.assertIsNone(candidate)
        self.assertIsNone(again_candidate)
        self.assertEqual(
            row.output["decision"]["primary_reason"], "no_economically_admitted_strategy"
        )
        self.assertEqual(replay(row.pk).output_digest, row.output_digest)
        self.assertEqual(audit_integrity()["violations"], [])
        self.assertEqual(EligibleTradeIntentCandidate.objects.count(), 0)
        with self.assertRaises(ValidationError):
            row.save()
        for statement, table in (
            ("UPDATE assessments_multitimeframeassessment SET output=output WHERE id=%s", "row"),
            ("DELETE FROM assessments_eligibilitysnapshot WHERE id=%s", "eligibility"),
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, [row.pk if table == "row" else eligibility.pk])

    def test_raw_sql_eligibility_and_hash_consistent_assessment_forgery_fail(self):
        eligibility = self.empty_eligibility()
        snapshot = self.frozen_snapshot()
        row, _, _ = assess(snapshot.pk, eligibility.pk)
        forged_eligibility = dict(eligibility.payload)
        forged_eligibility["instrument"] = "GBP_USD"
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO assessments_eligibilitysnapshot "
                "(instrument_id,valid_from,valid_until,decision_known_at,payload,digest,recorded_at) "
                "VALUES (%s,now()-interval '1 year',NULL,now(),%s,%s,now()-interval '1 year')",
                [
                    self.instrument.pk,
                    json.dumps(forged_eligibility),
                    identity_digest(forged_eligibility),
                ],
            )
        forged_manifest = {**row.input_manifest, "caller_override": True}
        forged_output = dict(row.output)
        forged_output["status"] = "available"
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO assessments_multitimeframeassessment "
                "(method_id,snapshot_id,eligibility_id,cost_id,capacity_id,evidence_packet_id,"
                "information_cutoff,input_manifest,input_digest,output,output_digest,recorded_at) "
                "VALUES (%s,%s,%s,NULL,NULL,NULL,%s,%s,%s,%s,%s,now())",
                [
                    row.method_id,
                    snapshot.pk,
                    eligibility.pk,
                    snapshot.information_cutoff,
                    json.dumps(forged_manifest),
                    identity_digest(forged_manifest),
                    json.dumps(forged_output),
                    identity_digest(forged_output),
                ],
            )
        self.assertEqual(MultiTimeframeAssessment.objects.count(), 1)

    def test_future_decision_and_expired_validity_refuse(self):
        with self.assertRaisesRegex(ValueError, "eligibility_chronology"):
            append_reviewed_eligibility(
                self.instrument,
                era="forged",
                entries=[],
                decision_known_at=timezone.now() + timedelta(days=1),
                phase55_decision_sha256="1" * 64,
                phase55_manifest_sha256="2" * 64,
                admission_provenance_sha256="3" * 64,
            )

    def test_method_registration_is_exact_and_idempotent(self):
        first = register_method()
        second = register_method()
        self.assertEqual(first.pk, second.pk)
