from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

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
from market.services import store_ingestion
from market.tests.factories import candle
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
        self.now = timezone.now() + timedelta(seconds=2)
        self.instruments = {}
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
            reference = self.now - timedelta(days=1)
            store_ingestion(
                self.source,
                instrument,
                "D",
                reference,
                reference + timedelta(days=1),
                [candle(reference)],
                {"test": f"portfolio-{code}", "requests": []},
            )
            evidence(instrument, self.now, sha256=str(order) * 64)
        conversion_at = self.now - timedelta(minutes=1)
        store_ingestion(
            self.source,
            self.instruments["USD_CAD"],
            "H1",
            conversion_at,
            self.now,
            [hourly_candle(conversion_at)],
            {"test": "portfolio-conversion", "requests": []},
        )

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
        first = assess_recommendation_batch([base], generated_at=self.now)
        self.assertEqual(first.selections.first().mode, PortfolioSelection.Mode.AUTOMATIC)
        self.assertFalse(cohort_is_open(first))
        with self.assertRaisesMessage(ValidationError, "closed"):
            select_portfolio_cohort(first, [], actor=self.owner)

        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = assess_recommendation_batch(
            [eur, gbp], generated_at=self.now + timedelta(seconds=1)
        )

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
        PortfolioPolicyActivation.objects.create(
            policy_key="fixed-cad-risk",
            policy_version=1,
            effective_at=self.now + timedelta(days=1),
        )
        recommendation = self.recommendation("USD_CAD", "sell")

        self.assertIsNone(assess_recommendation_batch([recommendation], generated_at=self.now))
        self.assertFalse(recommendation.portfolio_admission_events.exists())

    def test_any_member_price_trigger_closes_selection(self):
        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = assess_recommendation_batch([eur, gbp], generated_at=self.now)
        trigger_at = self.now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        store_ingestion(
            self.source,
            self.instruments["EUR_USD"],
            "H1",
            self.now,
            trigger_at + timedelta(hours=1),
            [
                hourly_candle(
                    trigger_at,
                    ask_low=eur.entry_level - Decimal("0.0001"),
                )
            ],
            {"test": "portfolio-trigger", "requests": []},
        )

        self.assertFalse(cohort_is_open(cohort))
        with self.assertRaisesMessage(ValidationError, "closed"):
            select_portfolio_cohort(cohort, [gbp.pk], actor=self.owner)

    def test_concurrent_owner_selections_cannot_over_admit(self):
        base = self.recommendation("USD_CAD", "sell")
        assess_recommendation_batch([base], generated_at=self.now)
        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = assess_recommendation_batch(
            [eur, gbp], generated_at=self.now + timedelta(seconds=1)
        )

        def choose(recommendation_id):
            close_old_connections()
            try:
                return select_portfolio_cohort(
                    cohort,
                    [recommendation_id],
                    actor=get_user_model().objects.get(pk=self.owner.pk),
                ).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            selection_ids = list(executor.map(choose, (eur.pk, gbp.pk)))

        self.assertEqual(len(set(selection_ids)), 2)
        active = set(active_admitted_recommendation_ids())
        self.assertIn(base.pk, active)
        self.assertEqual(len(active & {eur.pk, gbp.pk}), 1)

    def test_owner_selector_is_csrf_protected_and_records_decision(self):
        base = self.recommendation("USD_CAD", "sell")
        assess_recommendation_batch([base], generated_at=self.now)
        eur = self.recommendation("EUR_USD", "buy")
        gbp = self.recommendation("GBP_USD", "buy")
        cohort = assess_recommendation_batch(
            [eur, gbp], generated_at=self.now + timedelta(seconds=1)
        )
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
