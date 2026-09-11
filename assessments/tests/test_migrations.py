from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from assessments.contracts import (
    EMPTY_DECISION_SHA256,
    EMPTY_ELIGIBILITY_ERA,
    EMPTY_MANIFEST_SHA256,
    EMPTY_PROVENANCE_SHA256,
)
from assessments.models import EligibilitySnapshot
from assessments.services import append_reviewed_eligibility, register_method
from market.models import Instrument
from market.tests.test_live_observations import make_market


class MigrationTests(TransactionTestCase):
    def test_empty_roundtrip_and_populated_reversal_refusal(self):
        head = [("assessments", "0003_phase6a_correction_guards")]
        predecessor = [("assessments", "0002_phase6a_guards")]
        old = [("assessments", None)]
        instrument, _ = make_market()
        MigrationExecutor(connection).migrate(old)
        self.assertTrue(Instrument.objects.filter(pk=instrument.pk).exists())
        MigrationExecutor(connection).migrate(predecessor)
        eligibility = append_reviewed_eligibility(
            instrument,
            era=EMPTY_ELIGIBILITY_ERA,
            entries=[],
            decision_known_at=timezone.now(),
            phase55_decision_sha256=EMPTY_DECISION_SHA256,
            phase55_manifest_sha256=EMPTY_MANIFEST_SHA256,
            admission_provenance_sha256=EMPTY_PROVENANCE_SHA256,
        )
        MigrationExecutor(connection).migrate(head)
        self.assertTrue(Instrument.objects.filter(pk=instrument.pk).exists())
        self.assertTrue(EligibilitySnapshot.objects.filter(pk=eligibility.pk).exists())
        register_method()
        with self.assertRaisesMessage(RuntimeError, "phase6a_populated_correction_reverse_refused"):
            MigrationExecutor(connection).migrate(old)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM assessments_assessmentmethod")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_empty_successor_reverse_restores_v1_guards(self):
        head = [("assessments", "0003_phase6a_correction_guards")]
        predecessor = [("assessments", "0002_phase6a_guards")]
        MigrationExecutor(connection).migrate(predecessor)
        MigrationExecutor(connection).migrate(head)
        MigrationExecutor(connection).migrate(predecessor)
        with self.assertRaises(DatabaseError):
            register_method()
        MigrationExecutor(connection).migrate(head)
        self.assertEqual(register_method().version, "1.1.0")
