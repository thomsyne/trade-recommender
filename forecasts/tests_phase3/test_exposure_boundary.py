"""F9: factual current risk, including stale callers and exact effective times."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from forecasts.exposure import active_directional_recommendations, build_exposure_report
from forecasts.lifecycle import project_lifecycle, transition
from forecasts.models import PaperLifecycleEvent, PortfolioAdmissionEvent
from forecasts.paper import resolve_paper_trade
from forecasts.portfolio import _active_admitted
from forecasts.tests.test_recommendations import hourly_candle, open_market_hours
from market.quality import registered_candle_completion
from market.tests.factories import candle


class CurrentRiskBoundaryTests(TestCase):
    def setUp(self):
        from forecasts.tests_phase3.test_execution_boundaries import ExecutionBoundaryTests

        ExecutionBoundaryTests.setUp(self)

    def assert_risk(self, expected, at):
        # self.rec deliberately predates any reverse-relation terminal cache.
        with self.timeline.at(at):
            selected = list(active_directional_recommendations())
            self.assertEqual([r.pk for r in selected], [self.rec.pk] if expected else [])
            self.assertEqual([r.pk for r in _active_admitted()], [self.rec.pk] if expected else [])
            for rows in (selected, [self.rec]):
                report = build_exposure_report(rows)
                self.assertEqual(report["total_risk_cad"], Decimal("125") if expected else 0)
                self.assertEqual(len(report["setups"]), expected)

    def boundary(self, state, at):
        self.assertEqual(project_lifecycle(self.rec)["state"], state)
        self.assert_risk(1, at - timedelta(microseconds=1))
        self.assert_risk(0, at)
        self.assert_risk(0, at + timedelta(microseconds=1))

    def enter(self):
        hour = self.timeline.hours_after(self.rec.generated_at, 1)[0]
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(hour)],
            manifest={"test": "f9-entry", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        self.assertEqual(project_lifecycle(self.rec)["state"], "entered")
        return self.timeline.after(run)

    def test_admitted_and_entered_are_positive(self):
        self.assert_risk(1, self.now)
        self.assert_risk(1, self.enter())

    def test_cancelled_source_only_and_stale_iterable(self):
        at = self.now + timedelta(seconds=30)
        fact = PaperLifecycleEvent.objects.create(
            recommendation=self.rec,
            state="cancelled",
            reason_code="owner_cancelled",
            details={"schema_version": 1},
            occurred_at=at,
        )
        transition(self.rec, "cancelled", reason_code=fact.reason_code, source=fact, occurred_at=at)
        self.boundary("cancelled", at)

    def test_revocation_and_stale_iterable(self):
        at = self.now + timedelta(seconds=30)
        admission = self.rec.portfolio_admission_events.get()
        fact = PortfolioAdmissionEvent.objects.create(
            recommendation=self.rec,
            cohort=admission.cohort,
            selection=admission.selection,
            state="revoked",
            reason_code="owner_revoked",
            occurred_at=at,
        )
        transition(
            self.rec,
            "admission_revoked",
            reason_code="admission_revoked",
            source=fact,
            occurred_at=at,
        )
        self.boundary("admission_revoked", at)

    def gap(self, entered):
        if entered:
            self.enter()
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "D",
            [candle(self.timeline.session(5))],
            manifest={"test": "f9-gap", "requests": []},
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        event = self.rec.lifecycle_events.first()
        self.boundary("missing_data" if entered else "expired_unobserved", event.occurred_at)
        self.assertIsNone(project_lifecycle(self.rec)["result_id"])

    def test_expired_unobserved_source_only(self):
        self.gap(False)

    def test_entered_missing_data_source_only(self):
        self.gap(True)

    def hit(self, target):
        self.enter()
        hour = self.timeline.hours_after(self.rec.generated_at, 2)[1]
        changes = (
            {"bid_high": Decimal("2.0"), "ask_high": Decimal("2.0002")}
            if target
            else {"bid_low": Decimal("1.0"), "ask_low": Decimal("1.0002")}
        )
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(hour, **changes)],
            manifest={"test": "f9-hit", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        result = self.rec.paper_result
        self.boundary("target_hit" if target else "invalidated", result.resolved_at)

    def test_target_result_effective_time(self):
        self.hit(True)

    def test_invalidated_result_effective_time(self):
        self.hit(False)

    def expiry(self, activate):
        endpoint = self.timeline.session(5)
        maturity = registered_candle_completion(endpoint, "D")
        self.timeline.ingest(
            self.source,
            self.instrument,
            "D",
            [candle(endpoint)],
            manifest={"test": "f9-expiry-daily", "requests": []},
        )
        changes = (
            {}
            if activate
            else {
                "bid_open": Decimal("1.3600"),
                "bid_high": Decimal("1.3601"),
                "bid_low": Decimal("1.3599"),
                "bid_close": Decimal("1.3600"),
                "ask_open": Decimal("1.3602"),
                "ask_high": Decimal("1.3603"),
                "ask_low": Decimal("1.3601"),
                "ask_close": Decimal("1.3602"),
            }
        )
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [
                hourly_candle(h, **changes)
                for h in open_market_hours(self.rec.generated_at, maturity)
            ],
            manifest={"test": "f9-expiry-hours", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        self.boundary(
            "expired_after_entry" if activate else "expired_not_activated",
            self.rec.paper_result.resolved_at,
        )

    def test_after_entry_expiry_effective_time(self):
        self.expiry(True)

    def test_no_activation_expiry_effective_time(self):
        self.expiry(False)
