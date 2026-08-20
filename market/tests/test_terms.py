from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from market.models import AuditEvent, Instrument, OandaInstrumentTermsSnapshot
from market.services import store_oanda_terms


class OandaTermsSnapshotTests(TestCase):
    def setUp(self):
        self.instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        self.payload = {
            "account_currency": "CAD",
            "manifest": {
                "endpoint": "account-summary-and-instruments",
                "environment": "practice",
                "instruments": ["USD_CAD"],
                "summary_status": 200,
                "instruments_status": 200,
            },
            "instruments": [
                {
                    "name": "USD_CAD",
                    "marginRate": "0.02",
                    "pipLocation": -4,
                    "financing": {
                        "longRate": "-0.0200000000",
                        "shortRate": "0.0100000000",
                        "financingDaysOfWeek": [{"dayOfWeek": "WEDNESDAY", "daysCharged": 3}],
                    },
                }
            ],
        }

    def test_snapshot_is_private_idempotent_and_audited(self):
        captured_at = datetime(2026, 8, 20, 20, 21, tzinfo=UTC)

        first = store_oanda_terms(self.payload, "private-account-id", captured_at)
        second = store_oanda_terms(self.payload, "private-account-id", captured_at)

        self.assertEqual(first, second)
        self.assertEqual(OandaInstrumentTermsSnapshot.objects.count(), 1)
        snapshot = first[0]
        self.assertEqual(snapshot.account_currency, "CAD")
        self.assertFalse(snapshot.commission_supplied)
        self.assertNotEqual(snapshot.account_fingerprint, "private-account-id")
        self.assertNotIn("private-account-id", str(snapshot.__dict__))
        self.assertEqual(
            AuditEvent.objects.filter(event_type="market.oanda_terms_captured").count(), 1
        )

    def test_snapshot_rejects_model_mutation(self):
        snapshot = store_oanda_terms(self.payload, "private-account-id")[0]
        snapshot.long_financing_rate = 0

        with self.assertRaises(ValidationError):
            snapshot.save()
