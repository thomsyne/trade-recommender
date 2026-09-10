from datetime import timedelta
from decimal import Decimal as D
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.persistence import calculate, load_snapshot
from market.tests.factories import candle
from market.tests.test_live_observations import ingest, make_market


class ProvenanceTests(TestCase):
    def test_exact_old_revision_survives_later_candle_spread_revision(self):
        instrument, source = make_market()
        # New evidence keeps the real system recording trigger; no backdating helper.
        now = timezone.now()
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        from market.quality import live_interval_is_aligned

        while not live_interval_is_aligned(start, "H1"):
            start -= timedelta(hours=1)
        original = candle(start)
        ingest(source, instrument, [original], "phase5-original")
        cutoff = timezone.now()
        old, _ = compute_market_state(instrument, ensure_descriptor_definition(), cutoff, ["H1"])
        frozen = load_snapshot(old.pk)
        self.assertEqual(len(frozen.series("H1")), 1)
        self.assertEqual(frozen.series("H1")[0].close, D("1.1011"))
        evaluation, _ = calculate(old.pk, "ewmac-d-v1")
        revision = candle(start, bid_close=D("1.1015"), ask_close=D("1.1019"))
        ingest(source, instrument, [revision], "phase5-revised-spread")
        fresh = load_snapshot(old.pk)
        self.assertEqual(fresh, frozen)
        self.assertEqual(fresh.series("H1")[0].revision, 1)
        self.assertEqual(calculate(old.pk, "ewmac-d-v1")[0].output, evaluation.output)

    def test_dormant_consumers_and_readonly_definitions(self):
        root = Path(__file__).resolve().parents[2]
        for directory in ("forecasts", "operations", "config", "dashboard"):
            for path in (root / directory).rglob("*.py"):
                self.assertNotIn("market.strategy", path.read_text(), str(path))
                self.assertNotIn("market_strategyevaluation", path.read_text(), str(path))
        with self.assertNumQueries(0):
            call_command("strategy_library", "definitions", stdout=StringIO())
