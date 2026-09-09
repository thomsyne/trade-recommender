from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase

from forecasts.lifecycle import project_lifecycle
from forecasts.portfolio import cohort_is_open, select_portfolio_cohort
from forecasts.tests import test_portfolio as portfolio_fixtures


class OwnerBoundaryTests(TestCase):
    setUp = portfolio_fixtures.PortfolioAdmissionTests.setUp
    recommendation = portfolio_fixtures.PortfolioAdmissionTests.recommendation
    admit = portfolio_fixtures.PortfolioAdmissionTests.admit

    def open_cohort(self):
        with self.timeline.at(self.now + timedelta(minutes=1)):
            base = self.recommendation("USD_CAD", "sell")
            self.admit([base])
            eur = self.recommendation("EUR_USD", "buy")
            gbp = self.recommendation("GBP_USD", "buy")
            cohort = self.admit([eur, gbp], seconds=1)
        return base, eur, gbp, cohort

    def test_material_new_target_closes_every_member_and_preserves_past_report(self):
        from forecasts.integrity import report
        from forecasts.tests.test_recommendations import evidence
        from market.tests.factories import candle
        from market.tests.timeline import completed_intervals

        _, eur, gbp, cohort = self.open_cohort()
        before_at = self.now + timedelta(seconds=2)
        before = report(as_of=before_at)
        self.assertEqual(before["total"], 0)
        later = self.now + timedelta(minutes=2)
        earlier = completed_intervals(4, "D", before=self.now)[0]
        self.timeline.ingest(
            self.source,
            self.instruments["EUR_USD"],
            "D",
            [candle(earlier)],
            at=later,
            manifest={"test": "late-historical-new-target-evidence", "requests": []},
        )
        self.now = later + timedelta(seconds=2)
        with self.timeline.at(self.now):
            evidence(self.instruments["EUR_USD"], self.now, sha256="4" * 64)
            replacement = self.recommendation("EUR_USD", "buy")
            self.assertNotEqual(replacement.target_occurrence_id, eur.target_occurrence_id)
            newer = self.admit([replacement])
            cohort.refresh_from_db()
            self.assertEqual(cohort.closure.reason_code, "new_target_superseded")
            self.assertEqual(cohort.closure.superseding_cohort_id, newer.pk)
            self.assertFalse(cohort_is_open(cohort))
            for rec in [eur, gbp]:
                self.assertEqual(project_lifecycle(rec)["state"], "closed_unselected")
                self.assertEqual(rec.portfolio_membership.cohort_id, cohort.pk)
            with self.assertRaisesMessage(ValidationError, "closed"):
                select_portfolio_cohort(cohort, [gbp.pk], actor=self.owner)
        self.assertEqual(report(as_of=before_at), before)

    def test_new_admission_displaces_previously_available_frozen_capacity(self):
        from forecasts.portfolio import _active_admitted, _fits
        from forecasts.tests.test_recommendations import evidence

        base, eur, _, cohort = self.open_cohort()
        self.now += timedelta(minutes=2)
        with self.timeline.at(self.now):
            self.assertTrue(_fits(_active_admitted() + [eur]))
            evidence(self.instruments["USD_CAD"], self.now, sha256="5" * 64)
            newcomer = self.recommendation("USD_CAD", "sell")
            admitted = self.admit([newcomer])
            self.assertTrue(admitted.selections.exists())
            self.assertFalse(_fits(_active_admitted() + [eur]))
            with self.assertRaisesMessage(ValidationError, "frozen portfolio risk policy"):
                select_portfolio_cohort(cohort, [eur.pk], actor=self.owner)
            self.assertFalse(cohort.selections.exists())
            self.assertEqual(project_lifecycle(eur)["state"], "awaiting_owner_decision")
            self.assertEqual(project_lifecycle(base)["state"], "admitted_awaiting_entry")
