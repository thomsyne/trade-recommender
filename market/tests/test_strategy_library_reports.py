from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from django.test import SimpleTestCase

from market.strategy.definitions import definition_digest, population_definition
from market.strategy.reports import population, summarize_outcomes


class AttributionTests(SimpleTestCase):
    def row(self, ident="a"):
        return {
            "identity": ident,
            "strategy_sha256": definition_digest("ewmac-d-v1"),
            "era": population_definition()["era"],
            "population": "untouched_holdout",
            "entered_at": datetime(2027, 1, 4, tzinfo=UTC),
            "exited_at": datetime(2027, 1, 5, tzinfo=UTC),
            "gross_r": D(2),
            "net_r": D("1.5"),
        }

    def report(self, rows):
        return summarize_outcomes(rows, strategy="ewmac-d-v1", era=population_definition()["era"])

    def test_correlated_and_overlapping_observations_do_not_inflate_units(self):
        a, b = self.row(), self.row("b")
        b["entered_at"] += timedelta(days=2)
        b["exited_at"] += timedelta(days=2)
        result = self.report([a, b])
        self.assertEqual(result["independent_units"], 1)
        self.assertEqual((result["gross_r"], result["net_r"]), ("4", "3.0"))
        b["entered_at"] += timedelta(days=7)
        b["exited_at"] += timedelta(days=7)
        self.assertEqual(self.report([a, b])["independent_units"], 2)
        a["exited_at"] = b["entered_at"] + timedelta(minutes=15)
        self.assertEqual(self.report([a, b])["independent_units"], 1)

    def test_no_pooling_duplicates_or_holdout_boundary_leak(self):
        for changes in (
            {"strategy_sha256": definition_digest("breakout-d-v1")},
            {"era": "old-failed-break"},
            {"net_r": None},
            {"exited_at": datetime(2028, 1, 1, 0, 1, tzinfo=UTC)},
        ):
            with self.assertRaises(ValueError):
                self.report([self.row() | changes])
        with self.assertRaises(ValueError):
            self.report([self.row(), self.row()])
        self.assertEqual(population(datetime(2027, 1, 1, tzinfo=UTC)), "untouched_holdout")
        self.assertEqual(
            population(datetime(2028, 1, 1, tzinfo=UTC)),
            "exploratory_outside_registered_population",
        )
