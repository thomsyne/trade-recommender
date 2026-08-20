from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from forecasts.exposure import build_exposure_report, decompose_pair
from forecasts.models import Recommendation


def setup(pair, action, *, contract_version=2, entered=False, resolved=False, risk=None):
    base, quote = pair.split("_")
    return SimpleNamespace(
        contract_version=contract_version,
        action=action,
        instrument=SimpleNamespace(base_currency=base, quote_currency=quote),
        paper_entry=object() if entered else None,
        paper_result=object() if resolved else None,
        position_size=(
            SimpleNamespace(projected_risk_cad=Decimal(str(risk)), recommended_units=10000)
            if risk is not None
            else None
        ),
    )


class ExposureTests(SimpleTestCase):
    def test_pair_decomposition_uses_base_and_quote_directions(self):
        self.assertEqual(
            decompose_pair("EUR", "USD", Recommendation.Action.BUY),
            (("EUR", 1), ("USD", -1)),
        )
        self.assertEqual(
            decompose_pair("USD", "CAD", Recommendation.Action.SELL),
            (("USD", -1), ("CAD", 1)),
        )

    def test_repeated_currency_direction_is_one_duplicate_bet(self):
        report = build_exposure_report(
            [
                setup("USD_CAD", Recommendation.Action.SELL),
                setup("EUR_USD", Recommendation.Action.BUY),
            ]
        )
        usd = next(row for row in report["currencies"] if row["currency"] == "USD")

        self.assertEqual(usd["short_count"], 2)
        self.assertTrue(usd["has_duplicate"])
        self.assertEqual(report["duplicate_count"], 1)
        self.assertEqual(report["status"], "duplicate")

    def test_opposing_currency_legs_are_reported_as_a_conflict(self):
        report = build_exposure_report(
            [
                setup("USD_CAD", Recommendation.Action.BUY),
                setup("EUR_USD", Recommendation.Action.BUY),
            ]
        )
        usd = next(row for row in report["currencies"] if row["currency"] == "USD")

        self.assertEqual(usd["net_count"], 0)
        self.assertTrue(usd["has_conflict"])
        self.assertEqual(report["conflict_count"], 1)
        self.assertEqual(report["status"], "conflict")

    def test_three_same_direction_legs_exceed_declared_budget(self):
        report = build_exposure_report(
            [
                setup("USD_CAD", Recommendation.Action.SELL),
                setup("EUR_USD", Recommendation.Action.BUY),
                setup("GBP_USD", Recommendation.Action.BUY),
            ]
        )
        usd = next(row for row in report["currencies"] if row["currency"] == "USD")

        self.assertEqual(usd["largest_side"], 3)
        self.assertTrue(usd["over_budget"])
        self.assertEqual(report["over_budget_count"], 1)
        self.assertEqual(report["status"], "over_budget")

    def test_legacy_abstaining_and_resolved_setups_are_excluded(self):
        report = build_exposure_report(
            [
                setup("USD_CAD", Recommendation.Action.BUY, contract_version=1),
                setup("EUR_GBP", Recommendation.Action.ABSTAIN),
                setup("EUR_USD", Recommendation.Action.BUY, resolved=True),
            ]
        )

        self.assertEqual(report["setups"], [])
        self.assertEqual(report["currencies"], [])

    def test_waiting_and_entered_setups_are_both_visible(self):
        report = build_exposure_report(
            [
                setup("USD_CAD", Recommendation.Action.SELL),
                setup("EUR_GBP", Recommendation.Action.SELL, entered=True),
            ]
        )

        self.assertEqual([item["state"] for item in report["setups"]], ["waiting", "entered"])

    def test_cash_risk_is_aggregated_by_setup_and_currency_direction(self):
        report = build_exposure_report(
            [
                setup("USD_CAD", Recommendation.Action.SELL, risk="125.00"),
                setup("EUR_USD", Recommendation.Action.BUY, risk="124.99"),
            ]
        )
        usd = next(row for row in report["currencies"] if row["currency"] == "USD")

        self.assertEqual(report["total_risk_cad"], Decimal("249.99"))
        self.assertEqual(usd["short_risk_cad"], Decimal("249.99"))
        self.assertFalse(usd["over_budget"])
        self.assertEqual(report["sizing_missing_count"], 0)
