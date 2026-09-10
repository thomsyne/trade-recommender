from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from market.state.features import Bar
from market.state.fvg import find_fvgs
from market.strategy.contracts import SetupCandidate
from market.strategy.evaluate import evaluate
from market.strategy.orb import opening_range
from market.strategy.setups import fast_mean_reversion
from market.strategy.structure import range_geometry
from market.tests import test_strategy_library_orb as orb_fixture
from market.tests.test_strategy_library_simulation import START, bar


class FormulaBoundaryTests(SimpleTestCase):
    def test_prior_daily_equilibrium_and_h1_alignment(self):
        hourly = tuple(
            bar(
                START + timedelta(hours=i), open="287", high="288", low="286", close="287"
            )._replace(
                granularity="H1",
                end=START + timedelta(hours=i + 1),
                observed_at=START + timedelta(hours=i + 1),
            )
            for i in range(15)
        )
        cutoff = hourly[-1].timestamp
        daily = tuple(
            Bar(
                cutoff - timedelta(days=192 - i),
                D(100 + i),
                D(102 + i),
                D(99 + i),
                D(100 + i),
                cutoff - timedelta(days=191 - i),
                D("0.1"),
                "",
                cutoff - timedelta(days=191 - i),
                1,
                str(i),
            )
            for i in range(192)
        )
        inputs = SimpleNamespace(
            series=lambda g, before=None: (
                hourly
                if g == "H1"
                else tuple(b for b in daily if before is None or b.available_at <= before)
            ),
            payload={"instrument": "EUR_USD"},
            cutoff=hourly[-1].end,
        )
        candidate = fast_mean_reversion(inputs)
        self.assertEqual(candidate.direction, 1)
        self.assertEqual(candidate.stop, D(284))
        self.assertAlmostEqual(candidate.target, D(289), places=6)
        results = evaluate(inputs, "fast-mr-h1-v1")["outputs"]
        self.assertEqual(
            {p["schema"] for p in results},
            {"phase5/setup-v1", "phase5/risk-v1", "phase5/continuous-v1"},
        )
        inputs.cutoff += timedelta(microseconds=1)
        late = evaluate(inputs, "fast-mr-h1-v1")["outputs"]
        self.assertEqual(late[0]["reason"], "snapshot_cutoff_after_entry")
        self.assertNotIn("phase5/setup-v1", {part["schema"] for part in late})
        # Last daily observation arrives one microsecond too late for this H1 start.
        daily = daily[:-1] + (daily[-1]._replace(observed_at=cutoff + timedelta(microseconds=1)),)
        self.assertEqual(fast_mean_reversion(inputs).reason, "warmup_or_gap")

    def test_range_is_edge_only_with_frozen_center_exit(self):
        rejection = bar(open="101", high="102", low="100", close="101.5")
        signal = bar(rejection.end, open="102", high="104", low="102", close="103")
        result = range_geometry(signal, rejection, D(100), D(110), D(2))
        self.assertEqual(result.target, D(105))
        self.assertEqual(result.stop, D("99.5"))
        middle = rejection._replace(low=D(103), high=D(106), close=D(105))
        self.assertEqual(
            range_geometry(signal, middle, D(100), D(110), D(2)).reason, "not_a_unique_range_edge"
        )

    def test_fvg_qualification_and_equality_use_real_phase4_geometry(self):
        fixture, start = orb_fixture.OrbTests().inputs()
        prefix = fixture.series("M15")
        prefix = prefix[:-2] + (
            prefix[-2]._replace(high=D("100.5")),
            prefix[-1]._replace(open=D("99.5"), low=D("99.5"), high=D(102), close=D(102)),
        )
        signal = bar(
            start + timedelta(minutes=15), open="102", low="101", high="104", close="103"
        )._replace(spread=D("0.1"))

        def inputs(last):
            candles = prefix + (last,)
            return SimpleNamespace(
                series=lambda _: candles,
                payload={"granularities": {"M15": {"fvg": find_fvgs(candles, D("0.0001"))}}},
            )

        kwargs = {"session": "london", "session_date": start.date(), "variant": "orb-m15-fvg-v1"}
        result = opening_range(inputs(signal), **kwargs)
        self.assertIsInstance(result, SetupCandidate)
        self.assertEqual(result.entry_at, signal.end)
        self.assertEqual(
            opening_range(inputs(signal._replace(low=D("100.5"))), **kwargs).reason,
            "same_direction_fvg_unavailable",
        )

    def test_garch_convergence_failure_is_not_an_ewma_fallback(self):
        from market.strategy.risk import garch_overlay

        fake = SimpleNamespace(
            arch_model=lambda *a, **kw: SimpleNamespace(
                fit=lambda **kw: SimpleNamespace(convergence_flag=9)
            )
        )
        versions = {"arch": "7.2.0", "numpy": "1.26.4", "scipy": "1.13.1", "pandas": "2.2.3"}
        with (
            patch.dict("sys.modules", {"arch": fake}),
            patch("market.strategy.risk.version", side_effect=versions.__getitem__),
        ):
            self.assertEqual(garch_overlay((D(1),) * 250, D(1)).reason, "garch_nonconvergence")
