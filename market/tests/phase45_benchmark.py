"""Opt-in operational probe: manage.py test market.tests.phase45_benchmark.

Run alone on an otherwise idle task-owned exact-version cluster: WAL counters
are cluster-wide. Synthetic live-ledger workload, never accepted acquisition.
"""

import json
import resource
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from market.models import CandleObservation, Instrument, MarketStateSnapshot, SourceRegistry
from market.state.compute import LOOKBACKS, compute_market_state, ensure_descriptor_definition
from market.state.integrity import verify_snapshots
from market.state.manifest import eligible_observations
from market.tests.factories import candle
from market.tests.timeline import completed_intervals


def storage():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname,pg_relation_size(c.oid),pg_indexes_size(c.oid),"
            "CASE WHEN c.reltoastrelid=0 THEN 0 ELSE pg_total_relation_size(c.reltoastrelid) END "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND c.relname IN "
            "('market_candleobservation','market_marketstatesnapshot') ORDER BY c.relname"
        )
        return {
            name: {"heap": heap, "indexes": indexes, "toast": toast}
            for name, heap, indexes, toast in cursor.fetchall()
        }


class OperationalCertificationTests(TransactionTestCase):
    def test_bounded_history_concurrency_restart_and_resource_envelope(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            version = cursor.fetchone()[0]
            self.assertIn(version.split()[0], {"15.14", "17.6"})
            cursor.execute("SELECT pg_current_wal_insert_lsn()::text")
            wal_start = cursor.fetchone()[0]
        before = storage()
        instrument = Instrument.objects.create(
            code="EUR_USD", base_currency="EUR", quote_currency="USD", display_order=1, active=False
        )
        source = SourceRegistry.objects.create(
            name="Phase4.5 synthetic probe",
            tier="quarantine",
            base_url="https://example.invalid",
            retention_policy="disposable benchmark only",
        )
        from market.services import live_candle_completion, store_ingestion

        # Fixed relative history and prices; real system recording stays enabled.
        # D spans five years, W ten years; each intraday series exceeds lookback.
        today = timezone.now().date()
        horizon = datetime.combine(today, datetime.min.time(), tzinfo=UTC) - timedelta(days=2)
        counts = {"M15": 2000, "H1": 1200, "H4": 600, "D": 1300, "W": 520}
        ingest_start = time.perf_counter()
        for granularity, count in counts.items():
            if granularity == "M15":
                from market.live_acquisition import complete_live_intervals

                starts = complete_live_intervals(
                    horizon - timedelta(days=40), horizon, granularity
                )[-count:]
            else:
                starts = completed_intervals(count, granularity, before=horizon)
            for offset in range(0, len(starts), 200):
                batch = starts[offset : offset + 200]
                candles = []
                for index, at in enumerate(batch, offset):
                    shift = Decimal(index % 37) / Decimal("10000")
                    candles.append(
                        candle(
                            at,
                            bid_open=Decimal("1.1000") + shift,
                            bid_high=Decimal("1.1020") + shift,
                            bid_low=Decimal("1.0990") + shift,
                            bid_close=Decimal("1.1010") + shift,
                            ask_open=Decimal("1.1002") + shift,
                            ask_high=Decimal("1.1022") + shift,
                            ask_low=Decimal("1.0992") + shift,
                            ask_close=Decimal("1.1012") + shift,
                        )
                    )
                run = store_ingestion(
                    source,
                    instrument,
                    granularity,
                    batch[0],
                    live_candle_completion(batch[-1], granularity),
                    candles,
                    {
                        "synthetic": True,
                        "batch": offset,
                        "granularity": granularity,
                        "requests": [],
                    },
                )
                self.assertEqual(run.status, "succeeded")
        ingest_seconds = time.perf_counter() - ingest_start
        self.assertEqual(CandleObservation.objects.count(), sum(counts.values()))
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE market_candleobservation")
        definition = ensure_descriptor_definition()
        cutoff = timezone.now()
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            first, created = compute_market_state(instrument, definition, cutoff, sorted(counts))
        first_seconds = time.perf_counter() - start
        self.assertTrue(created)
        query_count = len(queries)
        self.assertEqual(verify_snapshots([first])["violation_count"], 0)
        with CaptureQueriesContext(connection) as selection:
            rows = eligible_observations(instrument, "M15", cutoff, lookback=LOOKBACKS["M15"])
        self.assertLessEqual(len(rows), LOOKBACKS["M15"])
        self.assertEqual(len(selection), 1)
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + selection[0]["sql"])
            explain = cursor.fetchone()[0][0]

        race_cutoff = cutoff + timedelta(microseconds=1)

        def replay():
            try:
                row, created = compute_market_state(
                    instrument, definition, race_cutoff, sorted(counts)
                )
                return row.pk, created
            finally:
                connection.close()

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: replay(), range(4)))
        concurrent_seconds = time.perf_counter() - start
        self.assertEqual(len({pk for pk, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)
        # Replay a bounded backlog, interrupt the connection mid-drain and resume.
        backlog = [cutoff + timedelta(microseconds=i) for i in range(8)]
        start = time.perf_counter()
        for index, at in enumerate(backlog):
            if index == 4:
                connection.close()
            compute_market_state(instrument, definition, at, sorted(counts))
        backlog_seconds = time.perf_counter() - start
        self.assertEqual(MarketStateSnapshot.objects.count(), 8)
        self.assertEqual(verify_snapshots(MarketStateSnapshot.objects.all())["violation_count"], 0)
        after = storage()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),%s)::bigint", [wal_start]
            )
            wal_bytes = cursor.fetchone()[0]
            cursor.execute("SELECT pg_backend_pid()")
            backend_pid = cursor.fetchone()[0]
        backend_rss = (
            int(
                subprocess.check_output(
                    ["ps", "-o", "rss=", "-p", str(backend_pid)], text=True
                ).strip()
            )
            * 1024
        )
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            rss_bytes *= 1024
        report = {
            "version": version,
            "synthetic": True,
            "counts": counts,
            "ingest_seconds": round(ingest_seconds, 3),
            "first_seconds": round(first_seconds, 3),
            "first_queries": query_count,
            "concurrent_workers": 4,
            "concurrent_seconds": round(concurrent_seconds, 3),
            "backlog_items": 8,
            "backlog_seconds": round(backlog_seconds, 3),
            "peak_python_rss_bytes": rss_bytes,
            "sampled_postgres_backend_rss_bytes": backend_rss,
            "wal_bytes": wal_bytes,
            "storage_before": before,
            "storage_after": after,
            "selection_plan": explain,
        }
        print("PHASE45_BENCHMARK=" + json.dumps(report, sort_keys=True))
        self.assertLessEqual(query_count, 200)
        self.assertLess(first_seconds, 30)
        self.assertLess(concurrent_seconds, 120)
        self.assertLess(backlog_seconds, 240)
        self.assertLess(rss_bytes, 1024**3)
        self.assertLess(backend_rss, 256 * 1024**2)
        self.assertLess(wal_bytes, 512 * 1024**2)
        self.assertLess(sum(sum(sizes.values()) for sizes in after.values()), 128 * 1024**2)
