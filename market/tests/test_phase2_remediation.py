"""Adversarial regressions for the five bounded independent-review findings."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from market.models import Candle, Instrument, SourceRegistry, TechnicalSnapshot
from market.oanda import OandaClient
from market.services import store_ingestion
from market.tests.factories import candle
from operations.management.commands.ingest_oanda import Command as IngestCommand
from operations.models import ScheduledJob
from operations.tasks import ingest_oanda


def payload(start, volume=100):
    return {
        "time": start.isoformat(),
        "complete": True,
        "volume": volume,
        "bid": {k: "151.123456" for k in "ohlc"},
        "ask": {k: "151.123457" for k in "ohlc"},
    }


@override_settings(
    OANDA_TOKEN="mock-only", OANDA_ACCOUNT_ID="mock-only", ANTHROPIC_API_KEY="", EODHD_API_TOKEN=""
)
class RemediationTests(TestCase):
    def setUp(self):
        call_command("seed_canonical", stdout=StringIO())
        self.instrument = Instrument.objects.get(code="USD_JPY")
        self.source = SourceRegistry.objects.get(name="OANDA v20")

    def report(self):
        out = StringIO()
        error = None
        try:
            call_command("report_fx_onboarding", stdout=out)
        except CommandError as exc:
            error = exc
        return json.loads(out.getvalue()), error

    def row(self, report, granularity="H1"):
        return next(
            r
            for r in report["rows"]
            if r["instrument"] == "USD_JPY" and r["granularity"] == granularity
        )

    def test_finding1_default_windows_are_canonical_and_attested(self):
        cases = [
            ("H1", "2025-12-22T12:17:00+00:00", "2025-12-21T12:00:00+00:00"),
            ("H4", "2025-12-22T12:17:00+00:00", "2025-12-21T10:00:00+00:00"),
            ("D", "2026-03-10T12:17:00+00:00", "2026-03-08T21:00:00+00:00"),
            ("D", "2025-11-04T12:17:00+00:00", "2025-11-02T22:00:00+00:00"),
            ("W", "2026-03-14T12:17:00+00:00", "2026-03-06T22:00:00+00:00"),
            ("W", "2025-11-08T12:17:00+00:00", "2025-10-31T21:00:00+00:00"),
        ]
        for granularity, to, expected in cases:
            with self.subTest(granularity=granularity, to=to):
                start = datetime.fromisoformat(expected)
                # H4 Sunday morning is closed; first actual candle is Sunday17 NY.
                returned = start if granularity != "H4" else datetime(2025, 12, 21, 22, tzinfo=UTC)
                seen = []

                def handler(request):
                    seen.append(request)
                    return httpx.Response(200, json={"candles": [payload(returned)]})

                with patch(
                    "operations.tasks.OandaClient",
                    side_effect=lambda *args: OandaClient(
                        "mock", transport=httpx.MockTransport(handler)
                    ),
                ):
                    run = ingest_oanda(
                        {
                            "instrument": "USD_JPY",
                            "granularity": granularity,
                            "to": to,
                            "days": 7 if granularity == "W" else 1,
                        }
                    )
                self.assertEqual(run.requested_from, start)
                self.assertEqual(datetime.fromisoformat(seen[0].url.params["from"]), start)
                self.assertEqual(datetime.fromisoformat(run.parameters["from"]), start)
                self.assertEqual(
                    datetime.fromisoformat(run.parameters["to"]), datetime.fromisoformat(to)
                )
                self.assertEqual(run.status, "succeeded")
                self.assertTrue(Candle.objects.filter(ingestion_run=run).exists())
                self.assertTrue(
                    TechnicalSnapshot.objects.filter(
                        instrument=self.instrument, granularity=granularity
                    ).exists()
                )

    def test_finding3_partial_request_is_not_healthy(self):
        end = datetime(2026, 1, 6, 12, tzinfo=UTC)
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            end - timedelta(days=14),
            end,
            [candle(end - timedelta(hours=1))],
            {"test": "partial"},
        )
        with patch("django.utils.timezone.now", return_value=end + timedelta(minutes=1)):
            report, error = self.report()
        self.assertIsNotNone(error)
        self.assertEqual(self.row(report)["state"], "partial")

    def test_finding3_unavailable_source_is_not_fresh(self):
        end = datetime(2026, 1, 6, 12, tzinfo=UTC)
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            end - timedelta(hours=1),
            end,
            [candle(end - timedelta(hours=1))],
            {"test": "complete"},
        )
        SourceRegistry.objects.filter(pk=self.source.pk).update(enabled=False)
        with patch("django.utils.timezone.now", return_value=end + timedelta(minutes=1)):
            report, error = self.report()
        self.assertEqual(self.row(report)["state"], "unavailable")

    def test_finding4_duplicate_and_policy_drift_are_detected(self):
        job = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        duplicate = ScheduledJob.objects.create(
            name="duplicate",
            task_name=job.task_name,
            parameters=job.parameters,
            interval_seconds=3600,
            next_run_at=job.next_run_at,
            enabled=False,
        )
        self.assertIsNotNone(self.report()[1])
        duplicate.delete()
        job.missed_run_policy = "all"
        job.save()
        self.assertIsNotNone(self.report()[1])

    def test_finding5_cli_covers_domain(self):
        parser = IngestCommand().create_parser("manage.py", "ingest_oanda")
        for code in Instrument.Code.values:
            for granularity in ("H1", "H4", "D", "W"):
                with self.subTest(code=code, granularity=granularity):
                    result = parser.parse_args([code, granularity])
                    self.assertEqual(result.instrument, code)
                    self.assertEqual(result.granularity, granularity)

    def test_arbitrary_current_time_uses_canonical_default_from(self):
        end = datetime(2026, 1, 20, 12, 17, 43, tzinfo=UTC)
        for g, start in (
            ("H1", datetime(2026, 1, 6, 12, tzinfo=UTC)),
            ("H4", datetime(2026, 1, 6, 10, tzinfo=UTC)),
        ):
            with self.subTest(g=g):
                seen = []

                def handler(request):
                    seen.append(request)
                    return httpx.Response(200, json={"candles": [payload(start)]})

                with (
                    patch("operations.tasks.datetime", wraps=datetime) as clock,
                    patch(
                        "operations.tasks.OandaClient",
                        side_effect=lambda *args: OandaClient(
                            "mock", transport=httpx.MockTransport(handler)
                        ),
                    ),
                ):
                    clock.now.return_value = end
                    run = ingest_oanda({"instrument": "USD_JPY", "granularity": g})
                self.assertEqual(run.requested_from, start)
                self.assertEqual(run.requested_to, end)
                self.assertEqual(datetime.fromisoformat(seen[0].url.params["from"]), start)
                self.assertEqual(datetime.fromisoformat(run.parameters["from"]), start)

    def test_policy_all_is_reported_independently_of_duplicates(self):
        job = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        job.missed_run_policy = "all"
        job.save()
        self.assertIsNotNone(self.report()[1])

    def test_report_policy_disabled_and_missing_token(self):
        for kind in ("token", "source", "instrument", "schedule"):
            with self.subTest(kind=kind):
                job = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
                if kind == "source":
                    SourceRegistry.objects.filter(pk=self.source.pk).update(enabled=False)
                if kind == "instrument":
                    Instrument.objects.filter(pk=self.instrument.pk).update(ingestion_enabled=False)
                if kind in {"schedule", "instrument"}:
                    job.enabled = False
                    job.save()
                with override_settings(OANDA_TOKEN="" if kind == "token" else "mock-only"):
                    report, error = self.report()
                self.assertEqual(
                    self.row(report)["collection_state"],
                    "unavailable" if kind in {"source", "token"} else "disabled",
                )
                self.assertEqual(self.row(report)["freshness"], "missing")
                self.assertEqual(self.row(report)["coverage"]["state"], "not_yet_ingested")
                SourceRegistry.objects.filter(pk=self.source.pk).update(enabled=True)
                Instrument.objects.filter(pk=self.instrument.pk).update(ingestion_enabled=True)
                job.enabled = True
                job.save()

    def test_schedule_drift_matrix_and_seed_does_not_hide_duplicates(self):
        from django.db import IntegrityError, transaction

        job = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        original = {
            key: getattr(job, key)
            for key in ("interval_seconds", "task_name", "parameters", "missed_run_policy")
        }
        for key, value in [
            ("interval_seconds", 1),
            ("task_name", "wrong"),
            ("parameters", {"instrument": "USD_JPY", "granularity": "D"}),
            ("missed_run_policy", "all"),
            ("missed_run_policy", "skip"),
        ]:
            with self.subTest(key=key, value=value):
                setattr(job, key, value)
                job.save()
                self.assertIsNotNone(self.report()[1])
                setattr(job, key, original[key])
                job.save()
        for enabled in (False, True):
            with self.subTest(duplicate_enabled=enabled):
                dup = ScheduledJob.objects.create(
                    name="alias",
                    task_name=job.task_name,
                    parameters=job.parameters,
                    interval_seconds=3600,
                    next_run_at=job.next_run_at,
                    enabled=enabled,
                )
                self.assertIsNotNone(self.report()[1])
                before = list(ScheduledJob.objects.order_by("pk").values())
                with self.assertRaisesMessage(CommandError, "duplicate semantic"):
                    call_command("seed_canonical", stdout=StringIO())
                self.assertEqual(before, list(ScheduledJob.objects.order_by("pk").values()))
                dup.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ScheduledJob.objects.create(
                name=job.name,
                task_name=job.task_name,
                interval_seconds=3600,
                next_run_at=job.next_run_at,
            )
        job.delete()
        report, error = self.report()
        self.assertIsNotNone(error)
        self.assertEqual(self.row(report)["state"], "integrity_violation")

    def test_latest_policy_repair_preserves_deadline_and_collapses_24_hours(self):
        from django.utils import timezone

        from operations.services import enqueue_due_jobs

        now = timezone.now()
        job = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        job.next_run_at = now - timedelta(hours=24)
        job.missed_run_policy = "all"
        job.save()
        self.assertIsNotNone(self.report()[1])
        for _ in range(2):
            call_command("seed_canonical", stdout=StringIO())
            job.refresh_from_db()
            self.assertEqual(job.next_run_at, now - timedelta(hours=24))
            self.assertEqual(job.missed_run_policy, "latest")
        created = enqueue_due_jobs(now)
        self.assertEqual(sum(o.scheduled_job_id == job.pk for o in created), 1)
        self.assertEqual(enqueue_due_jobs(now), [])

    def test_duplicate_stagger_is_reported_without_resetting_deadlines(self):
        first = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        second = ScheduledJob.objects.get(name="OANDA AUD_USD H1")
        second.next_run_at = first.next_run_at
        second.save()
        self.assertIsNotNone(self.report()[1])
        call_command("seed_canonical", stdout=StringIO())
        second.refresh_from_db()
        self.assertEqual(second.next_run_at, first.next_run_at)
        self.assertIsNotNone(self.report()[1])

    def test_cli_dispatch_and_policy_and_isolation(self):
        from types import SimpleNamespace

        from market.management.commands.report_fx_onboarding import forbidden_artifacts
        from operations.models import OutboxMessage, ProviderBudgetReservation

        for code, g in [("AUD_CAD", "H1"), ("EUR_USD", "W")]:
            with patch(
                "operations.management.commands.ingest_oanda.ingest_oanda",
                return_value=SimpleNamespace(pk=1, status="succeeded"),
            ) as task:
                call_command("ingest_oanda", code, g, stdout=StringIO())
                task.assert_called_once_with({"instrument": code, "granularity": g})
        parser = IngestCommand().create_parser("manage.py", "ingest_oanda")
        for args in [("XYZ_ABC", "H1"), ("EUR_USD", "M1"), ("EUR_USD", "M15")]:
            with self.assertRaises(CommandError):
                parser.parse_args(args)
        Instrument.objects.filter(code="AUD_CAD").update(ingestion_enabled=False)
        with patch("operations.tasks.OandaClient") as client:
            with self.assertRaisesMessage(ValueError, "ingestion is disabled"):
                call_command("ingest_oanda", "AUD_CAD", "H1", stdout=StringIO())
            client.assert_not_called()
        Instrument.objects.filter(code="AUD_CAD").update(ingestion_enabled=True)
        for g, start in [
            ("H1", datetime(2026, 1, 6, 10, tzinfo=UTC)),
            ("D", datetime(2026, 1, 5, 22, tzinfo=UTC)),
        ]:
            from market.services import live_candle_completion

            with patch(
                "operations.tasks.OandaClient",
                side_effect=lambda *args: OandaClient(
                    "mock",
                    transport=httpx.MockTransport(
                        lambda r: httpx.Response(200, json={"candles": [payload(start)]})
                    ),
                ),
            ):
                call_command(
                    "ingest_oanda",
                    "AUD_CAD",
                    g,
                    from_time=start.isoformat(),
                    to_time=live_candle_completion(start, g).isoformat(),
                    stdout=StringIO(),
                )
        self.assertFalse(any(forbidden_artifacts(Instrument.objects.get(code="AUD_CAD")).values()))
        self.assertEqual(ProviderBudgetReservation.objects.count(), 0)
        self.assertEqual(OutboxMessage.objects.count(), 0)

    def test_report_complete_and_partial_coverage_across_dst_and_weekends(self):
        from market.live_acquisition import complete_live_intervals

        for g, start, end, expected_count in [
            ("H1", datetime(2026, 3, 6, 20, tzinfo=UTC), datetime(2026, 3, 9, 0, tzinfo=UTC), 5),
            ("H4", datetime(2026, 3, 6, 18, tzinfo=UTC), datetime(2026, 3, 9, 5, tzinfo=UTC), 3),
            ("D", datetime(2026, 3, 5, 22, tzinfo=UTC), datetime(2026, 3, 10, 21, tzinfo=UTC), 3),
            ("W", datetime(2026, 2, 27, 22, tzinfo=UTC), datetime(2026, 3, 20, 21, tzinfo=UTC), 3),
        ]:
            with self.subTest(g=g):
                keys = complete_live_intervals(start, end, g)
                self.assertEqual(len(keys), expected_count)
                run = store_ingestion(
                    self.source,
                    self.instrument,
                    g,
                    start,
                    end,
                    [candle(t) for t in keys],
                    {"test": "complete", "g": g},
                )
                self.assertEqual(run.status, "succeeded")
                report, error = self.report()
                self.assertIsNone(error)
                row = self.row(report, g)
                self.assertEqual(row["coverage"]["state"], "complete")
                self.assertEqual(row["coverage"]["expected"], expected_count)
                self.assertEqual(row["coverage"]["observed"], expected_count)
                self.assertTrue(row["technical_snapshot_available"])
                # Even preexisting stored data must not conceal a partial response.
                store_ingestion(
                    self.source,
                    self.instrument,
                    g,
                    start,
                    end,
                    [candle(keys[-1])],
                    {"test": "partial-after-complete", "g": g},
                )
                report, error = self.report()
                self.assertIsNotNone(error)
                self.assertEqual(self.row(report, g)["state"], "partial")
                # Restore a successful full observation for the next subcase.
                store_ingestion(
                    self.source,
                    self.instrument,
                    g,
                    start,
                    end,
                    [candle(t) for t in keys],
                    {"test": "complete-again", "g": g},
                )

    def test_report_read_only_deterministic_and_revisions_and_snapshot_absence(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        start = datetime(2026, 1, 6, 10, tzinfo=UTC)
        end = start + timedelta(hours=1)
        for n in (100, 101):
            store_ingestion(
                self.source,
                self.instrument,
                "H1",
                start,
                end,
                [candle(start, volume=n)],
                {"volume": n},
            )
        now = datetime(2026, 1, 6, 11, 1, tzinfo=UTC)
        with (
            patch("django.utils.timezone.now", return_value=now),
            CaptureQueriesContext(connection) as queries,
        ):
            report, error = self.report()
            again, _ = self.report()
        self.assertEqual(report, again)
        self.assertIsNone(error)
        self.assertEqual(self.row(report)["state"], "revised")
        self.assertEqual(self.row(report)["freshness"], "fresh")
        self.assertEqual(self.row(report)["coverage"]["state"], "complete")
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER"))
                for q in queries
            )
        )
        # Simulate a missing calculation at ingestion, leaving actual candle
        # evidence present and actual snapshot rows absent (no report-query mock).
        other = Instrument.objects.get(code="AUD_USD")
        with patch("market.services.calculate_and_store_snapshot", return_value=None):
            store_ingestion(
                self.source,
                other,
                "H1",
                start,
                end,
                [candle(start)],
                {"test": "missing technical calculation"},
            )
        self.assertFalse(TechnicalSnapshot.objects.filter(instrument=other).exists())
        report, error = self.report()
        self.assertIsNone(error)
        row = next(
            row
            for row in report["rows"]
            if row["instrument"] == "AUD_USD" and row["granularity"] == "H1"
        )
        self.assertFalse(row["technical_snapshot_available"])
        self.assertEqual(row["coverage"]["state"], "complete")

    def test_explicit_window_floor_and_leading_complete_candle_filter(self):
        from market.services import live_candle_completion

        cases = [
            ("H1", datetime(2026, 1, 6, 10, tzinfo=UTC)),
            ("H4", datetime(2026, 1, 6, 10, tzinfo=UTC)),
            ("D", datetime(2026, 3, 8, 21, tzinfo=UTC)),
            ("W", datetime(2026, 3, 6, 22, tzinfo=UTC)),
        ]
        for g, start in cases:
            for offset in (timedelta(0), timedelta(minutes=17)):
                with self.subTest(g=g, offset=offset):
                    end = live_candle_completion(start, g)
                    requested = []

                    def handler(request):
                        requested.append(request)
                        return httpx.Response(
                            200,
                            json={
                                "candles": [
                                    payload(start - timedelta(hours=1)),
                                    payload(start),
                                    payload(end),
                                ]
                            },
                        )

                    with patch(
                        "operations.tasks.OandaClient",
                        side_effect=lambda *a: OandaClient(
                            "mock", transport=httpx.MockTransport(handler)
                        ),
                    ):
                        run = ingest_oanda(
                            {
                                "instrument": "USD_JPY",
                                "granularity": g,
                                "from": (start + offset).isoformat(),
                                "to": end.isoformat(),
                            }
                        )
                    self.assertEqual(run.requested_from, start)
                    self.assertEqual(run.requested_to, end)
                    self.assertEqual(run.fetched_count, 1)
                    self.assertEqual(
                        Candle.objects.filter(instrument=self.instrument, granularity=g).count(), 1
                    )
                    self.assertEqual(datetime.fromisoformat(requested[0].url.params["from"]), start)
                    self.assertEqual(datetime.fromisoformat(run.parameters["from"]), start)

    def test_report_detects_injected_evidence_recommendation_paper_and_conflict(self):
        from decimal import Decimal

        from forecasts.models import EvidenceSnapshot, PaperTradeEntry, Recommendation
        from market.models import CandleObservation
        from research.models import PairEvidenceSnapshot

        start = datetime(2026, 1, 6, 10, tzinfo=UTC)
        end = start + timedelta(hours=1)
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            start,
            end,
            [candle(start)],
            {"test": "forbidden-root"},
        )
        anchor = Candle.objects.get(instrument=self.instrument)
        technical = TechnicalSnapshot.objects.get(instrument=self.instrument)
        EvidenceSnapshot.objects.create(
            instrument=self.instrument,
            anchor_candle=anchor,
            technical_snapshot=technical,
            market_data_cutoff=end,
            payload={"test": True},
            sha256="e" * 64,
        )
        report, error = self.report()
        self.assertIsNotNone(error)
        self.assertEqual(self.row(report)["forbidden_artifacts"]["EvidenceSnapshot"], 1)
        pair = PairEvidenceSnapshot.objects.create(
            instrument=self.instrument,
            information_cutoff=start,
            payload={"test": True},
            sha256="f" * 64,
            captured_at=start,
        )
        rec = Recommendation.objects.create(
            instrument=self.instrument,
            evidence_snapshot=pair,
            reference_candle=anchor,
            provider="mock",
            model="mock",
            contract_version=2,
            generated_at=start,
            information_cutoff=start,
            action="buy",
            confidence_percent=50,
            reference_midpoint=Decimal("1.1"),
            neutral_band=Decimal("0.01"),
            probability_up=Decimal("0.6"),
            probability_neutral=Decimal("0.2"),
            probability_down=Decimal("0.2"),
            entry_condition="at_or_below",
            entry_level=Decimal("1.1"),
            target_level=Decimal("1.2"),
            invalidation_level=Decimal("1.0"),
            output={"test": True},
            input_payload={"test": True},
            request_sha256="a" * 64,
            idempotency_key="injected-forbidden",
        )
        PaperTradeEntry.objects.create(
            recommendation=rec,
            candle=anchor,
            execution_side="ask",
            fill_price=Decimal("1.1"),
            observed_open_spread=Decimal("0.0002"),
            details={"test": "injected forbidden artifact"},
        )
        report, error = self.report()
        self.assertIsNotNone(error)
        row = self.row(report)
        self.assertEqual(row["state"], "integrity_violation")
        for name in ("PairEvidenceSnapshot", "Recommendation", "PaperTradeEntry"):
            self.assertEqual(row["forbidden_artifacts"][name], 1)
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            start,
            end,
            [candle(start, volume=101)],
            {"test": "referenced-change"},
        )
        self.assertEqual(CandleObservation.objects.filter(kind="conflict").count(), 1)
        report, error = self.report()
        self.assertIsNotNone(error)
        self.assertEqual(self.row(report)["conflicts"], 1)
        # The conflict status independently surfaces when no forbidden roots are
        # present in the report's scope (the boundary census itself tested above).
        with patch(
            "market.management.commands.report_fx_onboarding.forbidden_artifacts", return_value={}
        ):
            report, error = self.report()
        self.assertEqual(self.row(report)["state"], "conflicted")
        self.assertIsNone(error)

    def test_report_complete_fresh_then_stale_is_distinct_from_coverage(self):
        start = datetime(2026, 1, 6, 10, tzinfo=UTC)
        end = start + timedelta(hours=1)
        store_ingestion(
            self.source, self.instrument, "H1", start, end, [candle(start)], {"test": "fresh-stale"}
        )
        for now, state in (
            (end + timedelta(minutes=1), "fresh"),
            (end + timedelta(days=3), "stale"),
        ):
            with self.subTest(state=state), patch("django.utils.timezone.now", return_value=now):
                report, error = self.report()
            self.assertIsNone(error)
            self.assertEqual(self.row(report)["state"], state)
            self.assertEqual(self.row(report)["freshness"], state)
            self.assertEqual(self.row(report)["coverage"]["state"], "complete")

    def test_report_failed_quarantine_and_clean_empty_exit_codes(self):
        from django.utils import timezone

        from market.models import IngestionRun

        report, error = self.report()
        self.assertIsNone(error)
        self.assertEqual(self.row(report)["state"], "not_yet_ingested")
        for g, status in (("H1", "failed"), ("H4", "quarantined")):
            IngestionRun.objects.create(
                source=self.source,
                instrument=self.instrument,
                granularity=g,
                requested_from=timezone.now() - timedelta(days=1),
                requested_to=timezone.now(),
                status=status,
                finished_at=timezone.now(),
                request_manifest_hash=g,
                parameters={"test": "terminal run"},
            )
            report, error = self.report()
            self.assertIsNone(error)
            self.assertEqual(self.row(report, g)["state"], status)


class LivePaginationRemediationTests(SimpleTestCase):
    def test_multi_page_overlap_keeps_every_complete_boundary_once(self):
        from market.quality import NEW_YORK, _market_is_open

        start = datetime(2025, 1, 6, 0, tzinfo=UTC)
        end = start + timedelta(hours=6000, minutes=17)
        expected = []
        t = start
        while t + timedelta(hours=1) <= end:
            if _market_is_open(t.astimezone(NEW_YORK)):
                expected.append(t)
            t += timedelta(hours=1)
        requests = []

        def handler(request):
            requests.append(request)
            a = datetime.fromisoformat(request.url.params["from"])
            b = datetime.fromisoformat(request.url.params["to"])
            include = request.url.params["includeFirst"] == "true"
            keys = [
                t
                for t in expected
                if (t >= a if include else t > a) and t + timedelta(hours=1) <= b
            ]
            return httpx.Response(200, json={"candles": [payload(t) for t in keys]})

        with OandaClient("mock", transport=httpx.MockTransport(handler)) as client:
            candles, manifest = client.fetch_candles("AUD_CAD", "H1", start, end)
        self.assertGreater(len(requests), 1)
        self.assertEqual([c.timestamp for c in candles], expected)
        self.assertEqual(len(candles), len(set(c.timestamp for c in candles)))
        self.assertEqual(requests[1].url.params["includeFirst"], "false")
        self.assertEqual(manifest["includeFirstByPage"], [True, False])
        self.assertEqual(manifest["requests"][1]["url"], str(requests[1].url))
        self.assertEqual(datetime.fromisoformat(manifest["from"]), start)
        self.assertEqual(datetime.fromisoformat(manifest["to"]), end)

    def test_dst_window_expected_keys_match_registered_calendar(self):
        from market.live_acquisition import canonical_live_start, complete_live_intervals
        from market.quality import expected_candle_timestamps

        for g, start, end in [
            ("D", datetime(2025, 10, 30, 21, tzinfo=UTC), datetime(2025, 11, 4, 22, tzinfo=UTC)),
            ("D", datetime(2026, 3, 5, 22, tzinfo=UTC), datetime(2026, 3, 10, 21, tzinfo=UTC)),
            ("W", datetime(2025, 10, 24, 21, tzinfo=UTC), datetime(2025, 11, 14, 22, tzinfo=UTC)),
            ("W", datetime(2026, 2, 27, 22, tzinfo=UTC), datetime(2026, 3, 20, 21, tzinfo=UTC)),
        ]:
            with self.subTest(g=g, start=start):
                self.assertEqual(canonical_live_start(start + timedelta(minutes=17), g), start)
                self.assertEqual(
                    complete_live_intervals(start, end, g),
                    expected_candle_timestamps(start, end, g),
                )
