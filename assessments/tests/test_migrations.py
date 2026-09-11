from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from assessments.services import register_method
from market.models import Instrument
from market.tests.test_live_observations import make_market


class MigrationTests(TransactionTestCase):
    def test_empty_roundtrip_and_populated_reversal_refusal(self):
        head = [("assessments", "0002_phase6a_guards")]
        old = [("assessments", None)]
        instrument, _ = make_market()
        MigrationExecutor(connection).migrate(old)
        self.assertTrue(Instrument.objects.filter(pk=instrument.pk).exists())
        MigrationExecutor(connection).migrate(head)
        self.assertTrue(Instrument.objects.filter(pk=instrument.pk).exists())
        register_method()
        with self.assertRaisesMessage(RuntimeError, "phase6a_populated_reverse_refused"):
            MigrationExecutor(connection).migrate(old)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM assessments_assessmentmethod")
            self.assertEqual(cursor.fetchone()[0], 1)
