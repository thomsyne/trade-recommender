"""Real source facts for each legal edge, challenged before the valid append."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase

from forecasts.lifecycle import TRANSITIONS, project_lifecycle, transition
from forecasts.models import RecommendationLifecycleEvent


class TransitionMatrixTests(TestCase):
    def test_every_legal_edge_has_real_source_and_rejects_wrong_source_and_time(self):
        from forecasts.models import PaperLifecycleEvent, PortfolioAdmissionEvent
        from forecasts.paper import resolve_paper_trade
        from forecasts.portfolio import assess_recommendation_batch
        from forecasts.recommendations import generate_recommendation
        from forecasts.sizing import size_recommendation
        from forecasts.targets import resolve_target, target_endpoint
        from forecasts.tests.test_frozen_evidence import FrozenEvidenceTests
        from forecasts.tests.test_recommendations import (
            FakeProvider,
            hourly_candle,
            open_market_hours,
            output,
        )
        from forecasts.tests_phase3.test_execution_boundaries import ExecutionBoundaryTests
        from market.quality import registered_candle_completion
        from market.tests.factories import candle

        seen = set()
        create = RecommendationLifecycleEvent.objects.create

        def checked_create(**values):
            rec = values["recommendation"]
            predecessor = values["predecessor"]
            source = apps.get_model("forecasts", values["source_type"]).objects.get(
                pk=values["source_id"]
            )
            with self.assertRaisesMessage(ValidationError, "illegal_lifecycle_transition"):
                transition(
                    rec,
                    values["state"],
                    reason_code=values["reason_code"],
                    source=source,
                    occurred_at=rec.generated_at - timedelta(microseconds=1),
                )
            with (
                self.assertRaisesRegex(
                    DatabaseError,
                    "source_required|membership_required|admission_required|entry_required",
                ),
                transaction.atomic(),
            ):
                RecommendationLifecycleEvent.objects.bulk_create(
                    [
                        RecommendationLifecycleEvent(
                            **(values | {"source_type": "InvalidSource", "source_id": 987654})
                        )
                    ]
                )
            with (
                self.assertRaisesRegex(
                    DatabaseError,
                    "invalid_lifecycle_evidence|coverage_source_mismatch|closure_source_required|revocation_source_required|terminal_result_source_mismatch",
                ),
                transaction.atomic(),
            ):
                RecommendationLifecycleEvent.objects.bulk_create(
                    [
                        RecommendationLifecycleEvent(
                            **(
                                values
                                | {"occurred_at": rec.generated_at - timedelta(microseconds=1)}
                            )
                        )
                    ]
                )
            event = create(**values)
            seen.add((predecessor.state if predecessor else None, event.state))
            return event

        cases = [
            "target_hit",
            "invalidated",
            "expired_after_entry",
            "expired_not_activated",
            "expired_unobserved",
            "entered_missing",
            "daily_missing",
            "admission_revoked",
            "admitted_cancelled",
            "unassessed_cancelled",
            "owner_cancelled",
            "closed_unselected",
            "portfolio_ineligible",
            "abstained",
        ]
        with patch.object(
            RecommendationLifecycleEvent.objects, "create", side_effect=checked_create
        ):
            for kind in cases:
                with self.subTest(kind=kind), transaction.atomic():
                    case = ExecutionBoundaryTests(
                        "test_entry_then_hourly_gap_closes_missing_without_fabricated_result"
                    )
                    if kind in {
                        "unassessed_cancelled",
                        "owner_cancelled",
                        "closed_unselected",
                        "portfolio_ineligible",
                        "abstained",
                    }:
                        case.daily = FrozenEvidenceTests.daily.__get__(case)
                        FrozenEvidenceTests.setUp(case)
                        with case.timeline.at(case.now):
                            rec = generate_recommendation(
                                case.instrument,
                                provider=FakeProvider(
                                    output(action="abstain", abstention_reason="Synthetic matrix")
                                )
                                if kind == "abstained"
                                else FakeProvider(),
                                generated_at=case.now,
                            )
                            if kind == "portfolio_ineligible":
                                assess_recommendation_batch([rec], generated_at=case.now)
                            if kind in {"owner_cancelled", "closed_unselected"}:
                                size_recommendation(rec, sized_at=case.now)
                                with patch("forecasts.portfolio._fits", return_value=False):
                                    cohort = assess_recommendation_batch(
                                        [rec], generated_at=case.now
                                    )
                        case.rec = rec
                    else:
                        case.setUp()
                        rec = case.rec
                    try:
                        if kind in {
                            "unassessed_cancelled",
                            "owner_cancelled",
                            "admitted_cancelled",
                        }:
                            at = case.now + timedelta(seconds=1)
                            fact = PaperLifecycleEvent.objects.create(
                                recommendation=rec,
                                state="cancelled",
                                reason_code="owner_cancelled",
                                details={"schema_version": 1},
                                occurred_at=at,
                            )
                            transition(
                                rec,
                                "cancelled",
                                reason_code=fact.reason_code,
                                source=fact,
                                occurred_at=at,
                            )
                        elif kind == "closed_unselected":
                            from django.contrib.auth import get_user_model

                            from forecasts.portfolio import select_portfolio_cohort

                            owner = get_user_model().objects.create_superuser(
                                username="matrix-owner"
                            )
                            with case.timeline.at(case.now + timedelta(seconds=1)):
                                select_portfolio_cohort(cohort, [], actor=owner)
                        elif kind == "admission_revoked":
                            original = rec.portfolio_admission_events.get()
                            at = case.now + timedelta(seconds=1)
                            fact = PortfolioAdmissionEvent.objects.create(
                                recommendation=rec,
                                cohort=original.cohort,
                                selection=original.selection,
                                state="revoked",
                                reason_code="owner_withdrew",
                                occurred_at=at,
                            )
                            transition(
                                rec,
                                "admission_revoked",
                                reason_code=fact.reason_code,
                                source=fact,
                                occurred_at=at,
                            )
                        elif kind not in {"portfolio_ineligible", "abstained"}:
                            endpoint = target_endpoint(rec.reference_candle.timestamp, 5)
                            maturity = registered_candle_completion(endpoint, "D")
                            if kind == "daily_missing":
                                shared = resolve_target(rec.target_occurrence, as_of=maturity)
                                fact = PaperLifecycleEvent.objects.create(
                                    recommendation=rec,
                                    state="missing_data",
                                    reason_code="daily_horizon_unavailable",
                                    details={
                                        "schema_version": 1,
                                        "target_resolution_id": shared.pk,
                                    },
                                    occurred_at=maturity,
                                )
                                transition(
                                    rec,
                                    "missing_data",
                                    reason_code=fact.reason_code,
                                    source=fact,
                                    occurred_at=maturity,
                                )
                            else:
                                hours = open_market_hours(rec.generated_at, maturity)
                                if kind in {"expired_after_entry", "expired_not_activated"}:
                                    values = [
                                        hourly_candle(
                                            h,
                                            **(
                                                {
                                                    "bid_open": Decimal("1.3700"),
                                                    "bid_high": Decimal("1.3720"),
                                                    "bid_low": Decimal("1.3690"),
                                                    "bid_close": Decimal("1.3710"),
                                                    "ask_open": Decimal("1.3702"),
                                                    "ask_high": Decimal("1.3722"),
                                                    "ask_low": Decimal("1.3692"),
                                                    "ask_close": Decimal("1.3712"),
                                                }
                                                if kind == "expired_not_activated"
                                                else {}
                                            ),
                                        )
                                        for h in hours
                                    ]
                                elif kind == "target_hit":
                                    values = [
                                        hourly_candle(hours[0]),
                                        hourly_candle(
                                            hours[1],
                                            bid_high=Decimal("1.3602"),
                                            ask_high=Decimal("1.3604"),
                                        ),
                                    ]
                                elif kind == "invalidated":
                                    values = [
                                        hourly_candle(
                                            hours[0],
                                            bid_low=Decimal("1.3390"),
                                            ask_low=Decimal("1.3392"),
                                        )
                                    ]
                                elif kind == "entered_missing":
                                    values = [hourly_candle(hours[0])]
                                else:
                                    values = []
                                if kind in {"expired_after_entry", "expired_not_activated"}:
                                    case.timeline.ingest(
                                        case.source,
                                        case.instrument,
                                        "D",
                                        [candle(endpoint)],
                                        manifest={
                                            "test": "matrix-endpoint-before-execution",
                                            "requests": [],
                                        },
                                    )
                                if values:
                                    run = case.timeline.ingest(
                                        case.source,
                                        case.instrument,
                                        "H1",
                                        values,
                                        manifest={"test": "matrix-" + kind, "requests": []},
                                        requested_from=rec.generated_at,
                                    )
                                    with case.timeline.at(case.timeline.after(run)):
                                        resolve_paper_trade(rec)
                                if kind in {
                                    "expired_after_entry",
                                    "expired_not_activated",
                                    "expired_unobserved",
                                    "entered_missing",
                                }:
                                    run = case.timeline.ingest(
                                        case.source,
                                        case.instrument,
                                        "D",
                                        [candle(endpoint)],
                                        manifest={"test": "matrix-endpoint", "requests": []},
                                    )
                                    with case.timeline.at(case.timeline.after(run)):
                                        resolve_paper_trade(rec)
                        expected = {
                            "entered_missing": "missing_data",
                            "daily_missing": "missing_data",
                            "admitted_cancelled": "cancelled",
                            "unassessed_cancelled": "cancelled",
                            "owner_cancelled": "cancelled",
                        }.get(kind, kind)
                        self.assertEqual(project_lifecycle(rec)["state"], expected)
                    finally:
                        case.doCleanups()
                    transaction.set_rollback(True)
        expected = {
            (state, next_state) for state, allowed in TRANSITIONS.items() for next_state in allowed
        }
        self.assertEqual(
            seen - {(None, "abstained"), (None, "awaiting_portfolio_assessment")}, expected
        )
