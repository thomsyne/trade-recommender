from datetime import UTC, datetime
from decimal import Decimal

from django.test import SimpleTestCase

from forecasts.lifecycle import TRANSITIONS
from forecasts.targets import identity_digest, target_endpoint


class ContractBoundaryTests(SimpleTestCase):
    def test_identity_is_order_independent_and_sensitive_to_every_field(self):
        fields = {
            "instrument": "EUR_USD",
            "cutoff": "2026-03-06T22:00:00Z",
            "reference": "a" * 64,
            "midpoint": "1.100000",
            "band": "0.002000",
            "horizon": 5,
            "contract": "tactical:2",
            "resolution": "session-v2",
        }
        expected = identity_digest(fields)
        self.assertEqual(expected, identity_digest(dict(reversed(list(fields.items())))))
        for field in fields:
            with self.subTest(field=field):
                self.assertNotEqual(expected, identity_digest(fields | {field: "changed"}))

    def test_endpoint_counts_registered_sessions_across_dst_weekend(self):
        reference = datetime(2026, 3, 5, 22, tzinfo=UTC)
        self.assertEqual(target_endpoint(reference, 5), datetime(2026, 3, 12, 21, tzinfo=UTC))

    def test_terminal_cannot_reopen_and_unselected_cannot_enter(self):
        self.assertEqual(TRANSITIONS["abstained"], frozenset())
        self.assertEqual(TRANSITIONS["closed_unselected"], frozenset())
        self.assertNotIn("entered", TRANSITIONS["awaiting_owner_decision"])

    def test_asymmetric_brier_expectation_is_independent(self):
        from types import SimpleNamespace

        from forecasts.services import multiclass_brier

        forecast = SimpleNamespace(
            probability_up=Decimal("0.6"),
            probability_neutral=Decimal("0.3"),
            probability_down=Decimal("0.1"),
        )
        self.assertEqual(multiclass_brier(forecast, "down"), Decimal("0.420000"))

    def test_control_probabilities_use_frozen_target_band_before_classification(self):
        from datetime import UTC, datetime
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from forecasts.services import _issue_baseline

        now = datetime(2026, 8, 1, tzinfo=UTC)
        anchor = NS(
            midpoint_close=Decimal("1.10"),
            ask_close=Decimal("1.1001"),
            bid_close=Decimal("1.0999"),
            ingestion_run=NS(source=NS(name="OANDA v20")),
        )
        snapshot = NS(atr_14=Decimal("1"), ewma_20=Decimal("1.09"))
        evidence = NS(
            anchor_candle=anchor,
            technical_snapshot=snapshot,
            instrument=NS(code="USD_CAD"),
            sha256="a" * 64,
        )
        contract = NS(
            key="tactical",
            version=2,
            horizon_sessions=5,
            neutral_atr_multiplier=Decimal(".25"),
            spread_multiplier=Decimal("2"),
        )
        target = NS(
            identity_sha256="b" * 64,
            reference_midpoint=Decimal("1.10"),
            neutral_band=Decimal(".005"),
            horizon_sessions=5,
            information_cutoff=now,
        )
        with (
            patch("forecasts.services.Forecast.objects") as manager,
            patch("forecasts.services.AuditEvent.objects.create"),
        ):
            manager.filter.return_value.first.return_value = None
            manager.create.side_effect = lambda **values: NS(pk=1, **values)
            control = _issue_baseline(contract, evidence, now, target=target)
        # The target band .005 makes a .01 displacement UP. The old .25 band
        # would classify NEUTRAL and issue (.25,.50,.25), reversing this oracle.
        self.assertEqual(control.direction, "up")
        self.assertEqual(
            (control.probability_up, control.probability_neutral, control.probability_down),
            (Decimal(".5"), Decimal(".3"), Decimal(".2")),
        )
        self.assertEqual(control.neutral_band, Decimal(".005"))
