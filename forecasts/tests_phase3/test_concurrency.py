from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from forecasts.experiments import ensure_champion_era
from forecasts.lifecycle import transition
from forecasts.models import Forecast, Recommendation, TargetOccurrence
from forecasts.recommendations import generate_recommendation
from forecasts.targets import reconcile_targets
from forecasts.tests.test_recommendations import FakeProvider, evidence
from market.models import Instrument


class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        from forecasts.tests.test_services import ForecastServiceTests

        cls = type(self)
        cls._store_daily_batch = classmethod(ForecastServiceTests._store_daily_batch.__func__)
        ForecastServiceTests.setUpTestData.__func__(cls)
        self.now = self.timeline.poll_instant([self.sessions[19]], "D") + timedelta(seconds=2)

    def test_concurrent_exact_control_issuance_is_one_target_one_control(self):
        def work():
            close_old_connections()
            try:
                target, control = reconcile_targets(
                    Instrument.objects.get(pk=self.instrument.pk), as_of=self.now
                )
                return target.pk, control.pk
            finally:
                connections.close_all()

        with self.timeline.at(self.now), ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: work(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(TargetOccurrence.objects.count(), 1)
        self.assertEqual(Forecast.objects.filter(target_occurrence__isnull=False).count(), 1)

    def test_concurrent_transition_retry_preserves_one_legal_chain(self):
        with self.timeline.at(self.now):
            reconcile_targets(self.instrument, as_of=self.now)
            evidence(self.instrument, self.now, prospective=False)
            ensure_champion_era(FakeProvider(), starts_at=self.now, register=True)
            rec = generate_recommendation(
                self.instrument, provider=FakeProvider(), generated_at=self.now
            )

        def work():
            close_old_connections()
            try:
                return transition(
                    Recommendation.objects.get(pk=rec.pk),
                    "portfolio_ineligible",
                    reason_code="missing_versioned_sizing",
                    occurred_at=self.now + timedelta(seconds=1),
                ).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: work(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(rec.lifecycle_events.count(), 2)

    def test_concurrent_shared_resolution_retry_has_one_outcome(self):
        from forecasts.models import TargetResolution
        from forecasts.targets import resolve_target, target_endpoint
        from market.quality import registered_candle_completion

        with self.timeline.at(self.now):
            target, _ = reconcile_targets(self.instrument, as_of=self.now)
        maturity = registered_candle_completion(
            target_endpoint(target.reference_candle.timestamp, target.horizon_sessions), "D"
        )

        def work():
            close_old_connections()
            try:
                return resolve_target(TargetOccurrence.objects.get(pk=target.pk), as_of=maturity).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: work(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(TargetResolution.objects.count(), 1)
        self.assertEqual(TargetResolution.objects.get().outcome, "missing")
