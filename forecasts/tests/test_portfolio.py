from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse

from forecasts.models import (
    PortfolioAdmissionEvent,
    PortfolioPolicyActivation,
    PortfolioSelection,
)
from forecasts.portfolio import (
    active_admitted_recommendation_ids,
    assess_recommendation_batch,
    cohort_is_open,
    select_portfolio_cohort,
)
from forecasts.recommendations import generate_recommendation
from forecasts.sizing import size_recommendation
from forecasts.tests.test_recommendations import FakeProvider, evidence, hourly_candle, output
from market.models import Instrument, SourceRegistry
from market.tests.factories import candle
from market.tests.timeline import EvidenceTimeline, completed_intervals
from operations.models import OwnerNotification


class PortfolioAdmissionTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            username="owner-test", password="test"
        )
        self.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test only",
        )
        # The whole scenario sits on the timeline: references close, the policy
        # is activated, decisions are taken, and only then does a later hour
        # close and trigger. Room is reserved for those trailing hours.
        self.timeline = EvidenceTimeline(daily=2, trailing_hours=6)
        self.instruments = {}
        self.now = None
        for order, (code, base, quote) in enumerate(
            (
                ("USD_CAD", "USD", "CAD"),
                ("EUR_USD", "EUR", "USD"),
                ("GBP_USD", "GBP", "USD"),
            ),
            start=1,
        ):
            instrument = Instrument.objects.create(
                code=code,
                base_currency=base,
                quote_currency=quote,
                display_order=order,
            )
            self.instruments[code] = instrument
            reference_run = self.timeline.ingest(
                self.source,
                instrument,
                "D",
                [candle(self.timeline.session(0))],
                manifest={"test": f"portfolio-{code}", "requests": []},
            )
            if self.now is None:
                self.now = self.timeline.after(reference_run, seconds=2)
            evidence(instrument, self.now, sha256=str(order) * 64)
        # The conversion rate comes from the last hour that actually closed.
        conversion_at = completed_intervals(1, "H1", before=self.now)[0]
        self.timeline.ingest(
            self.source,
            self.instruments["USD_CAD"],
            "H1",
            [hourly_candle(conversion_at)],
            manifest={"test": "portfolio-conversion", "requests": []},
        )

    def admit(self, recommendations, *, seconds=0):
        """Assess a batch at the scenario's decision instant.

        Portfolio policy activation is stamped from the clock on first use, so
        admission has to happen at the moment the recommendations were issued
        or they would predate their own policy.
        """
        assessed_at = self.now + timedelta(seconds=seconds)
        with self.timeline.at(assessed_at):
            return assess_recommendation_batch(recommendations, generated_at=assessed_at)

    def recommendation(self, code, action):
        probabilities = (
            {"probability_up_percent": 62, "probability_down_percent": 15}
            if action == "buy"
            else {"probability_up_percent": 15, "probability_down_percent": 62}
        )
        recommendation = generate_recommendation(
            self.instruments[code],
            provider=FakeProvider(output(action=action, **probabilities)),
            generated_at=self.now,
        )
        size_recommendation(recommendation, sized_at=self.now)
        return recommendation

    def test_competing_setups_require_owner_and_allow_pending_supersession(self):
        base = self.recommendation("USD_CAD", "sell")
        first = self.admit([base])
        self.assertEqual(first.selections.first().mode, PortfolioSelection.Mode.AUTOMATIC)
        self.assertFalse(cohort_is_open(first))
        with self.assertRaisesMessage(ValidationError, "closed"):
            select_portfolio_cohort(first, [], actor=self.owner)

        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = self.admit([eur, gbp], seconds=1)

        self.assertFalse(cohort.selections.exists())
        self.assertTrue(cohort_is_open(cohort))
        self.assertTrue(
            OwnerNotification.objects.filter(subject_id=str(cohort.pk), severity="action").exists()
        )
        with self.assertRaisesMessage(ValidationError, "exceed"):
            select_portfolio_cohort(cohort, [eur.pk, gbp.pk], actor=self.owner)
        with (
            patch("forecasts.portfolio._active_admitted", return_value=[]),
            self.assertRaisesMessage(ValidationError, "frozen"),
        ):
            select_portfolio_cohort(cohort, [eur.pk, gbp.pk], actor=self.owner)

        selected = select_portfolio_cohort(cohort, [eur.pk], actor=self.owner)
        self.assertEqual(
            select_portfolio_cohort(cohort, [eur.pk], actor=self.owner),
            selected,
        )
        self.assertEqual(
            set(active_admitted_recommendation_ids()),
            {base.pk, eur.pk},
        )
        superseding = select_portfolio_cohort(cohort, [gbp.pk], actor=self.owner)
        self.assertEqual(superseding.supersedes, selected)
        self.assertEqual(set(active_admitted_recommendation_ids()), {base.pk, gbp.pk})
        self.assertEqual(
            PortfolioAdmissionEvent.objects.filter(
                recommendation=eur, state=PortfolioAdmissionEvent.State.REVOKED
            ).count(),
            1,
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            PortfolioSelection.objects.filter(pk=superseding.pk).update(mode="automatic")

    def test_pre_activation_recommendation_remains_research_only(self):
        # The policy only becomes effective after this recommendation, so the
        # recommendation stays research-only.
        PortfolioPolicyActivation.objects.create(
            policy_key="fixed-cad-risk",
            policy_version=1,
            effective_at=self.now + timedelta(days=1),
        )
        recommendation = self.recommendation("USD_CAD", "sell")

        self.assertIsNone(self.admit([recommendation]))
        self.assertFalse(recommendation.portfolio_admission_events.exists())

    def test_any_member_price_trigger_closes_selection(self):
        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = self.admit([eur, gbp])
        trigger_at = self.timeline.hours_after(self.now, 1)[0]
        self.timeline.ingest(
            self.source,
            self.instruments["EUR_USD"],
            "H1",
            [
                hourly_candle(
                    trigger_at,
                    ask_low=eur.entry_level - Decimal("0.0001"),
                )
            ],
            manifest={"test": "portfolio-trigger", "requests": []},
            requested_from=self.now,
        )

        self.assertFalse(cohort_is_open(cohort))
        with self.assertRaisesMessage(ValidationError, "closed"):
            select_portfolio_cohort(cohort, [gbp.pk], actor=self.owner)

    def test_concurrent_owner_selections_cannot_over_admit(self):
        base = self.recommendation("USD_CAD", "sell")
        self.admit([base])
        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = self.admit([eur, gbp], seconds=1)

        def choose(recommendation_id):
            close_old_connections()
            try:
                return select_portfolio_cohort(
                    cohort,
                    [recommendation_id],
                    actor=get_user_model().objects.get(pk=self.owner.pk),
                ).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            selection_ids = list(executor.map(choose, (eur.pk, gbp.pk)))

        self.assertEqual(len(set(selection_ids)), 2)
        active = set(active_admitted_recommendation_ids())
        self.assertIn(base.pk, active)
        self.assertEqual(len(active & {eur.pk, gbp.pk}), 1)

    def test_owner_selector_is_csrf_protected_and_records_decision(self):
        base = self.recommendation("USD_CAD", "sell")
        self.admit([base])
        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = self.admit([eur, gbp], seconds=1)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)

        inbox = client.get(reverse("inbox"))
        self.assertContains(inbox, "Confidence is uncalibrated context")
        self.assertContains(inbox, "Record immutable selection")
        self.assertEqual(
            client.post(
                reverse("select-cohort", args=(cohort.pk,)), {"recommendation": eur.pk}
            ).status_code,
            403,
        )
        token = inbox.cookies["csrftoken"].value
        response = client.post(
            reverse("select-cohort", args=(cohort.pk,)),
            {"recommendation": eur.pk, "csrfmiddlewaretoken": token},
        )

        self.assertRedirects(response, reverse("inbox"))
        self.assertIn(eur.pk, active_admitted_recommendation_ids())
