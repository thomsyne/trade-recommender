from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings

from market.models import IngestionRun, Instrument
from market.tests.historical_database import HistoricalDatabaseMixin
from operations.models import ScheduledJob
from operations.tasks import capture_oanda_terms, ingest_oanda

CODES = (
    "EUR_USD",
    "GBP_USD",
    "EUR_GBP",
    "USD_CAD",
    "USD_JPY",
    "AUD_USD",
    "USD_CHF",
    "NZD_USD",
    "EUR_JPY",
    "GBP_JPY",
    "AUD_JPY",
    "AUD_CAD",
)


@override_settings(
    OANDA_TOKEN="mock-only",
    OANDA_ACCOUNT_ID="mock-account",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
)
class Phase2Tests(TestCase):
    def setUp(self):
        from django.utils import timezone

        self.seed_at = timezone.now()
        with patch(
            "market.management.commands.seed_canonical.timezone.now", return_value=self.seed_at
        ):
            call_command("seed_canonical", verbosity=0)

    def test_registry_and_schedule_contract(self):
        self.assertEqual(list(Instrument.objects.values_list("code", flat=True)), list(CODES))
        self.assertEqual(
            list(Instrument.objects.filter(active=True).values_list("code", flat=True)),
            list(CODES[:4]),
        )
        self.assertEqual(Instrument.objects.filter(ingestion_enabled=True).count(), 12)
        self.assertEqual(
            ScheduledJob.objects.filter(task_name="market.ingest_oanda", enabled=True).count(), 48
        )

    def test_inactive_ingestion_does_not_resolve_or_review(self):
        with (
            patch("operations.tasks.OandaClient") as client,
            patch(
                "operations.tasks.store_ingestion",
                return_value=SimpleNamespace(status=IngestionRun.Status.SUCCEEDED),
            ),
            patch("operations.tasks.resolve_due_forecasts") as forecast,
            patch("operations.tasks.resolve_due_recommendations") as rec,
            patch("operations.tasks.resolve_due_paper_trades") as paper,
            patch("operations.tasks.build_due_review_cohort") as review,
        ):
            client.return_value.__enter__.return_value.fetch_candles.return_value = ([], {})
            ingest_oanda({"instrument": "USD_JPY", "granularity": "D"})
            for downstream in (forecast, rec, paper, review):
                downstream.assert_not_called()

    def test_disabled_direct_execution_fails_before_provider(self):
        Instrument.objects.filter(code="USD_JPY").update(ingestion_enabled=False)
        with patch("operations.tasks.OandaClient") as client:
            with self.assertRaisesMessage(ValueError, "ingestion is disabled"):
                ingest_oanda({"instrument": "USD_JPY", "granularity": "H1"})
            client.assert_not_called()

    def test_terms_use_collection_universe(self):
        with (
            patch("operations.tasks.OandaClient") as client,
            patch("operations.tasks.store_oanda_terms"),
        ):
            capture_oanda_terms()
            client.return_value.__enter__.return_value.fetch_account_terms.assert_called_once_with(
                "mock-account", list(CODES)
            )

    def test_terms_empty_collection_universe_makes_no_account_request(self):
        Instrument.objects.update(ingestion_enabled=False)
        with patch("operations.tasks.OandaClient") as client:
            self.assertEqual(capture_oanda_terms(), [])
            client.assert_not_called()

    def test_seed_preserves_disable_and_deadlines_and_repairs_policy(self):
        Instrument.objects.filter(code="USD_JPY").update(ingestion_enabled=False)
        job = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        original = job.next_run_at
        job.missed_run_policy = "all"
        job.save()
        call_command("seed_canonical", verbosity=0)
        job.refresh_from_db()
        self.assertFalse(job.enabled)
        self.assertEqual(job.missed_run_policy, "latest")
        self.assertEqual(job.next_run_at, original)
        self.assertEqual(job.parameters, {"instrument": "USD_JPY", "granularity": "H1"})
        self.assertEqual(Instrument.objects.count(), 12)

    def test_direct_decision_owners_reject_every_onboarding_pair(self):
        from forecasts.recommendations import generate_recommendation
        from forecasts.services import issue_baselines
        from research.services import capture_pair_evidence

        for instrument in Instrument.objects.filter(code__in=CODES[4:]):
            for owner in (generate_recommendation, issue_baselines, capture_pair_evidence):
                with self.subTest(code=instrument.code, owner=owner.__name__):
                    with self.assertRaisesMessage(ValueError, "Decision workflows are disabled"):
                        owner(instrument)

    def test_stagger_and_latest_only_catchup(self):
        from datetime import timedelta

        from django.utils import timezone

        from operations.services import enqueue_due_jobs

        jobs = ScheduledJob.objects.filter(task_name="market.ingest_oanda")
        self.assertEqual(jobs.values("next_run_at").distinct().count(), 48)
        phases = set()
        for job in jobs:
            delay = int((job.next_run_at - self.seed_at).total_seconds())
            self.assertGreater(delay, 0)
            self.assertLess(delay, job.interval_seconds)
            phases.add(delay % 3600)
        self.assertEqual(len(phases), 48)
        deadlines = dict(jobs.values_list("name", "next_run_at"))
        call_command("seed_canonical", verbosity=0)
        self.assertEqual(dict(jobs.values_list("name", "next_run_at")), deadlines)
        now = timezone.now() + timedelta(days=30)
        created = enqueue_due_jobs(now)
        self.assertEqual(sum(row.task_name == "market.ingest_oanda" for row in created), 48)
        self.assertEqual(enqueue_due_jobs(now), [])

    def test_no_token_disables_all_collection_and_terms_without_provider(self):
        with override_settings(OANDA_TOKEN=""):
            call_command("seed_canonical", verbosity=0)
            self.assertFalse(
                ScheduledJob.objects.filter(task_name="market.ingest_oanda", enabled=True).exists()
            )
            with patch("operations.tasks.OandaClient") as client:
                with self.assertRaises(ValueError):
                    capture_oanda_terms()
                client.assert_not_called()
        with override_settings(OANDA_ACCOUNT_ID=""):
            with self.assertRaises(ValueError):
                capture_oanda_terms()

    def test_mocked_provider_all_pairs_all_granularities_six_decimal_storage(self):
        import json
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal
        from io import StringIO

        import httpx

        from market.management.commands.report_fx_onboarding import forbidden_artifacts
        from market.models import Candle, CandleObservation, TechnicalSnapshot
        from market.oanda import OandaClient
        from market.services import live_candle_completion

        starts = {
            "H1": datetime(2026, 1, 5, 8, tzinfo=UTC),
            "H4": datetime(2026, 1, 5, 10, tzinfo=UTC),
            "D": datetime(2026, 1, 4, 22, tzinfo=UTC),
            "W": datetime(2026, 1, 2, 22, tzinfo=UTC),
        }
        for code in CODES[4:]:
            for granularity, start in starts.items():
                value = Decimal("157.123456") if code.endswith("JPY") else Decimal("0.612345")

                def handler(request):
                    self.assertEqual(request.url.path, f"/v3/instruments/{code}/candles")
                    self.assertEqual(request.url.params["price"], "BA")
                    self.assertEqual(request.url.params["smooth"], "false")
                    self.assertEqual(request.url.params["dailyAlignment"], "17")
                    self.assertEqual(request.url.params["weeklyAlignment"], "Friday")
                    self.assertEqual(request.url.params["alignmentTimezone"], "America/New_York")
                    return httpx.Response(
                        200,
                        json={
                            "candles": [
                                {
                                    "time": start.isoformat(),
                                    "complete": True,
                                    "volume": 1,
                                    "bid": {k: str(value) for k in "ohlc"},
                                    "ask": {k: str(value + Decimal("0.000001")) for k in "ohlc"},
                                }
                            ]
                        },
                    )

                client = OandaClient("mock-only", transport=httpx.MockTransport(handler))
                with (
                    patch("operations.tasks.OandaClient", return_value=client),
                    patch("operations.tasks.resolve_due_forecasts") as forecasts,
                    patch("operations.tasks.resolve_due_recommendations") as rec,
                    patch("operations.tasks.resolve_due_paper_trades") as paper,
                    patch("operations.tasks.build_due_review_cohort") as review,
                ):
                    run = ingest_oanda(
                        {
                            "instrument": code,
                            "granularity": granularity,
                            "from": start.isoformat(),
                            "to": (
                                live_candle_completion(start, granularity) + timedelta(seconds=1)
                            ).isoformat(),
                        }
                    )
                    self.assertEqual(run.status, "succeeded")
                    for owner in (forecasts, rec, paper, review):
                        owner.assert_not_called()
                stored = Candle.objects.get(instrument__code=code, granularity=granularity)
                self.assertEqual(stored.bid_close, value)
                self.assertEqual(CandleObservation.objects.get(candle=stored).bid_close, value)
                self.assertTrue(
                    TechnicalSnapshot.objects.filter(
                        instrument=stored.instrument,
                        granularity=granularity,
                        source_candle_set_sha256__isnull=False,
                    ).exists()
                )
            self.assertFalse(any(forbidden_artifacts(Instrument.objects.get(code=code)).values()))
        output = StringIO()
        call_command("report_fx_onboarding", stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(len(report["rows"]), 32)
        self.assertEqual(report["integrity_errors"], [])
        self.assertEqual({row["state"] for row in report["rows"]}, {"stale"})

    def test_report_empty_disabled_and_boundary_violation(self):
        import json
        from io import StringIO

        from django.core.management.base import CommandError

        output = StringIO()
        call_command("report_fx_onboarding", stdout=output)
        self.assertEqual(
            {row["state"] for row in json.loads(output.getvalue())["rows"]}, {"not_yet_ingested"}
        )
        Instrument.objects.filter(code="USD_JPY").update(active=True)
        with self.assertRaises(CommandError):
            call_command("report_fx_onboarding", stdout=StringIO())

    def test_active_pair_retains_downstream_behavior(self):
        with (
            patch("operations.tasks.OandaClient") as client,
            patch(
                "operations.tasks.store_ingestion", return_value=SimpleNamespace(status="succeeded")
            ),
            patch("operations.tasks.resolve_due_forecasts") as forecast,
            patch("operations.tasks.resolve_due_recommendations") as rec,
            patch("operations.tasks.resolve_due_paper_trades") as paper,
            patch("operations.tasks.build_due_review_cohort") as review,
        ):
            client.return_value.__enter__.return_value.fetch_candles.return_value = ([], {})
            ingest_oanda({"instrument": "EUR_USD", "granularity": "D"})
            for downstream in (forecast, rec, paper, review):
                downstream.assert_called_once()

    def test_report_failed_quarantined_and_disabled_states(self):
        import json
        from datetime import timedelta
        from io import StringIO

        from django.utils import timezone

        from market.models import SourceRegistry

        source = SourceRegistry.objects.get(name="OANDA v20")
        instrument = Instrument.objects.get(code="USD_JPY")
        for granularity, status in [("H1", "failed"), ("H4", "quarantined")]:
            IngestionRun.objects.create(
                source=source,
                instrument=instrument,
                granularity=granularity,
                requested_from=timezone.now() - timedelta(days=1),
                requested_to=timezone.now(),
                parameters={},
                request_manifest_hash=granularity,
                status=status,
                finished_at=timezone.now(),
            )
        ScheduledJob.objects.filter(name="OANDA USD_JPY D").update(enabled=False)
        output = StringIO()
        call_command("report_fx_onboarding", stdout=output)
        states = {
            row["granularity"]: row["state"]
            for row in json.loads(output.getvalue())["rows"]
            if row["instrument"] == "USD_JPY"
        }
        self.assertEqual(
            states, {"H1": "failed", "H4": "quarantined", "D": "disabled", "W": "not_yet_ingested"}
        )


class Phase2MigrationTests(HistoricalDatabaseMixin, TransactionTestCase):
    historical_market_migration = "0030_"

    @override_settings(
        OANDA_TOKEN="mock-only",
        OANDA_ACCOUNT_ID="mock-account",
        ANTHROPIC_API_KEY="",
        EODHD_API_TOKEN="",
    )
    def test_concurrent_seed_serializes_and_preserves_identity(self):
        from concurrent.futures import ThreadPoolExecutor
        from io import StringIO

        from django.db import close_old_connections

        def seed():
            close_old_connections()
            try:
                call_command("seed_canonical", verbosity=0, stdout=StringIO())
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(seed) for _ in range(2)]
            for result in results:
                result.result(timeout=60)
        self.assertEqual(Instrument.objects.count(), 12)
        self.assertEqual(ScheduledJob.objects.filter(task_name="market.ingest_oanda").count(), 48)

    def test_forward_preserves_six_ids_and_active_states_with_safe_unknown_default(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate([("market", "0029_candle_observation_lineage")])
        old = executor.loader.project_state(
            [("market", "0029_candle_observation_lineage")]
        ).apps.get_model("market", "Instrument")
        try:
            ids = {}
            for order, code in enumerate(CODES[:6], 1):
                ids[code] = old.objects.create(
                    code=code,
                    base_currency=code[:3],
                    quote_currency=code[4:],
                    display_order=order,
                    active=order <= 4,
                ).pk
            old.objects.create(
                code="XAU_USD",
                base_currency="XAU",
                quote_currency="USD",
                display_order=20,
                active=False,
            )
            old.objects.create(
                code="XAG_USD",
                base_currency="XAG",
                quote_currency="USD",
                display_order=21,
                active=True,
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate([("market", "0030_ingestion_eligibility")])
        for code, pk in ids.items():
            row = Instrument.objects.get(code=code)
            self.assertEqual(row.pk, pk)
            self.assertEqual(row.active, code in CODES[:4])
            self.assertTrue(row.ingestion_enabled)
        self.assertFalse(Instrument.objects.get(code="XAU_USD").ingestion_enabled)
        self.assertTrue(Instrument.objects.get(code="XAG_USD").ingestion_enabled)


class Phase2MalformedProviderTests(TestCase):
    def test_live_provider_rejects_missing_candles_and_untyped_completion(self):
        from datetime import UTC, datetime, timedelta

        import httpx

        from market.oanda import OandaClient, OandaError

        start = datetime(2026, 1, 5, 8, tzinfo=UTC)
        malformed = [
            {},
            {"candles": None},
            {
                "candles": [
                    {
                        "time": start.isoformat(),
                        "complete": "false",
                        "volume": 1,
                        "bid": {k: "150.123456" for k in "ohlc"},
                        "ask": {k: "150.123457" for k in "ohlc"},
                    }
                ]
            },
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                with OandaClient(
                    "mock",
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(200, json=payload)
                    ),
                ) as client:
                    with self.assertRaises(OandaError):
                        client.fetch_candles("USD_JPY", "H1", start, start + timedelta(hours=1))


@override_settings(
    OANDA_TOKEN="mock-only",
    OANDA_ACCOUNT_ID="mock-account",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
)
class Phase2OverlapTests(TestCase):
    def test_every_onboarding_pair_keeps_overlap_history_and_fails_bad_ohlc(self):
        from dataclasses import replace
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal

        from market.models import Candle, CandleObservation, SourceRegistry
        from market.services import store_ingestion
        from market.tests.factories import candle

        call_command("seed_canonical", verbosity=0)
        start = datetime(2026, 1, 5, 8, tzinfo=UTC)
        source = SourceRegistry.objects.get(name="OANDA v20")
        for code in CODES[4:]:
            instrument = Instrument.objects.get(code=code)
            price = Decimal("151.123456") if code.endswith("JPY") else Decimal("0.612345")
            a = candle(
                start,
                **{
                    f"{side}_{field}": price + (Decimal(".000001") if side == "ask" else 0)
                    for side in ("bid", "ask")
                    for field in ("open", "high", "low", "close")
                },
            )
            b = replace(a, volume=101)
            for attempt, item in enumerate((a, a, b, a)):
                run = store_ingestion(
                    source,
                    instrument,
                    "H1",
                    start,
                    start + timedelta(hours=1),
                    [item],
                    {"instrument": code, "attempt": attempt, "requests": [{"status": 200}]},
                )
                self.assertEqual(run.status, "succeeded")
                self.assertEqual(run.parameters["requests"], [{"status": 200}])
            self.assertEqual(Candle.objects.filter(instrument=instrument).count(), 1)
            observations = CandleObservation.objects.filter(instrument=instrument).order_by(
                "revision"
            )
            self.assertEqual(list(observations.values_list("revision", flat=True)), [1, 2, 3])
            self.assertEqual(list(observations.values_list("volume", flat=True)), [100, 101, 100])
            for attempt, item in enumerate(
                (
                    replace(a, bid_high=price - 1),
                    replace(a, bid_close=price + 1),
                    replace(a, complete=False),
                )
            ):
                run = store_ingestion(
                    source,
                    instrument,
                    "H1",
                    start,
                    start + timedelta(hours=1),
                    [item],
                    {"instrument": code, "bad": attempt},
                )
                self.assertEqual(run.status, "failed")
            self.assertEqual(observations.count(), 3)

    def test_failed_ingestion_task_is_not_reported_as_success(self):
        call_command("seed_canonical", verbosity=0)
        for status in ("failed", "quarantined"):
            with (
                patch("operations.tasks.OandaClient") as client,
                patch(
                    "operations.tasks.store_ingestion", return_value=SimpleNamespace(status=status)
                ),
            ):
                client.return_value.__enter__.return_value.fetch_candles.return_value = ([], {})
                with self.assertRaisesMessage(ValueError, f"OANDA ingestion ended as {status}"):
                    ingest_oanda({"instrument": "USD_JPY", "granularity": "H1"})


@override_settings(
    OANDA_TOKEN="mock-only",
    OANDA_ACCOUNT_ID="mock-account",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
)
class Phase2DecisionEnumerationTests(TestCase):
    def test_batches_portfolio_and_dashboard_keep_only_four_decision_pairs(self):
        from dashboard.context_processors import market_navigation
        from forecasts.recommendations import generate_all_recommendations
        from operations.models import OutboxMessage, ProviderBudgetReservation
        from research.services import capture_all_pair_evidence

        call_command("seed_canonical", verbosity=0)
        with (
            patch(
                "forecasts.recommendations.generate_recommendation",
                side_effect=lambda instrument, **kwargs: SimpleNamespace(instrument=instrument),
            ) as generate,
            patch("forecasts.recommendations.size_recommendation"),
            patch("forecasts.portfolio.assess_recommendation_batch") as portfolio,
        ):
            generate_all_recommendations()
            self.assertEqual(
                [call.args[0].code for call in generate.call_args_list], list(CODES[:4])
            )
            self.assertEqual(
                [item.instrument.code for item in portfolio.call_args.args[0]], list(CODES[:4])
            )
        with patch("research.services.capture_pair_evidence") as capture:
            capture_all_pair_evidence()
            self.assertEqual(
                [call.args[0].code for call in capture.call_args_list], list(CODES[:4])
            )
        self.assertEqual(
            list(market_navigation(None)["instruments_navigation"].values_list("code", flat=True)),
            list(CODES[:4]),
        )
        self.assertEqual(ProviderBudgetReservation.objects.count(), 0)
        self.assertEqual(OutboxMessage.objects.count(), 0)


@override_settings(
    OANDA_TOKEN="mock-only",
    OANDA_ACCOUNT_ID="mock-account",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
)
class Phase2ExactWindowTests(TestCase):
    def test_new_fetch_of_same_window_preserves_a_b_a_but_persistence_replay_is_idempotent(self):
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal

        import httpx

        from market.models import Candle, CandleObservation, SourceRegistry
        from market.oanda import OandaClient
        from market.services import store_ingestion
        from market.tests.factories import candle

        call_command("seed_canonical", verbosity=0)
        start = datetime(2026, 1, 5, 8, tzinfo=UTC)
        end = start + timedelta(hours=1)
        volumes = iter((100, 101, 100))

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "candles": [
                        {
                            "time": start.isoformat(),
                            "complete": True,
                            "volume": next(volumes),
                            "bid": {k: "150.123456" for k in "ohlc"},
                            "ask": {k: "150.123457" for k in "ohlc"},
                        }
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        with patch(
            "operations.tasks.OandaClient",
            side_effect=lambda token, environment: OandaClient(
                token, environment, transport=transport
            ),
        ):
            runs = [
                ingest_oanda(
                    {
                        "instrument": "USD_JPY",
                        "granularity": "H1",
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                    }
                )
                for _ in range(3)
            ]
        self.assertEqual(len({run.pk for run in runs}), 3)
        observations = CandleObservation.objects.filter(instrument__code="USD_JPY").order_by(
            "revision"
        )
        self.assertEqual(list(observations.values_list("volume", flat=True)), [100, 101, 100])
        self.assertEqual(Candle.objects.filter(instrument__code="USD_JPY").count(), 1)
        instrument = Instrument.objects.get(code="USD_JPY")
        replay = store_ingestion(
            SourceRegistry.objects.get(name="OANDA v20"),
            instrument,
            "H1",
            start,
            end,
            [
                candle(
                    start,
                    **{
                        f"{side}_{field}": Decimal("150.123456" if side == "bid" else "150.123457")
                        for side in ("bid", "ask")
                        for field in ("open", "high", "low", "close")
                    },
                )
            ],
            runs[-1].parameters,
        )
        self.assertEqual(replay.pk, runs[-1].pk)
        self.assertEqual(observations.count(), 3)
