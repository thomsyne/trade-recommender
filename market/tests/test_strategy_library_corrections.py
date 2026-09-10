"""Independent-review counterexamples; initially red on 4424f5a."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Inexact, localcontext
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from market.models import StrategyEvaluation
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.contracts import Component, RiskOverlay, SnapshotInput, encoded
from market.strategy.definitions import definition
from market.strategy.evaluate import evaluate
from market.strategy.persistence import (
    _verified_chain,
    calculate,
    integrity,
    load_snapshot,
    register,
)
from market.strategy.simulation import simulate
from market.strategy.trend import breakout, buffer, ema, ewmac
from market.tests.factories import candle, daily_sessions
from market.tests.test_live_observations import ingest, make_market
from market.tests.test_strategy_library_persistence import snapshot
from market.tests.test_strategy_library_simulation import SimulationTests, bar
from market.tests.test_strategy_library_trend import NOW, bars, cost


class PureCorrections(SimpleTestCase):
    def fixture(self):
        fixture = SimulationTests()
        fixture.setUp()
        return fixture

    def test_terminal_outcome_survives_production_series_gap(self):
        fixture = self.fixture()
        original = fixture.run_model()
        suffix = bar(fixture.outcome.end + timedelta(minutes=15))
        assembled = SnapshotInput.series(
            SimpleNamespace(bars=(fixture.outcome, suffix)), "M15", outcome=True
        )
        self.assertEqual(
            simulate(
                fixture.setup,
                assembled,
                cost=fixture.cost,
                calendar=fixture.calendar,
                profile="fixture",
                terms=fixture.terms,
            ),
            original,
        )

    def test_incomplete_outcome_terms_cannot_produce_account_net(self):
        fixture = self.fixture()
        for changes in ({"account_currency": ""}, {"source_sha256": "x"}):
            with self.subTest(changes=changes):
                result = fixture.run_model(terms=replace(fixture.terms, **changes))
                self.assertEqual(result.schema, "phase5/unavailable-v1")

    def test_mr_owns_a_separate_limit_hypothesis(self):
        self.assertEqual(
            definition("fast-mr-h1-v1")["simulator"]["version"],
            "adverse-limit-h1-v1",
        )

    def test_public_ema_is_independent_of_ambient_decimal_context(self):
        outputs = []
        for rounding in (ROUND_HALF_EVEN, ROUND_UP, ROUND_DOWN):
            with localcontext() as ctx:
                ctx.prec = 9
                ctx.rounding = rounding
                value = ema((D(1), D("5.32098275")), 6)
                outputs.append(encoded(Component("ema", value, None, "fixture")))
        self.assertEqual(len(set(outputs)), 1)

    def test_full_arithmetic_boundaries_ignore_precision_rounding_and_traps(self):
        fixture = self.fixture()
        history = bars(110)
        outputs = []
        for mode in (ROUND_HALF_EVEN, ROUND_UP, ROUND_DOWN):
            with localcontext() as ctx:
                ctx.prec = 3
                ctx.rounding = mode
                ctx.traps[Inexact] = True
                outputs.append(
                    (
                        encoded(ewmac(history, costs={}, cutoff=NOW)),
                        encoded(breakout(history, costs={}, cutoff=NOW)),
                        str(buffer(D("4.123456789"), D("1.1"))),
                        str(fixture.cost.roundtrip),
                        encoded(fixture.run_model()),
                    )
                )
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_terms_types_units_and_time_bounds(self):
        f = self.fixture()
        invalid = (
            {"account_currency": "ZZZ"},
            {"base_currency": "usd"},
            {"quote_currency": ""},
            {"source_sha256": "A" * 64},
            {"provenance": " "},
            {"cost_unit": "pips"},
            {"conversion_unit": "quote_per_account"},
            {"conversion_rate": D("NaN")},
            {"conversion_rate": D("Infinity")},
            {"conversion_rate": True},
            {"from_at": f.terms.from_at.replace(tzinfo=None)},
            {"from_at": f.terms.through_at + timedelta(seconds=1)},
            {"known_at": f.terms.conversion_at + timedelta(microseconds=1)},
            {"conversion_at": f.terms.conversion_at + timedelta(seconds=1)},
        )
        for change in invalid:
            with self.subTest(change=change):
                self.assertEqual(
                    f.run_model(terms=replace(f.terms, **change)).schema, "phase5/unavailable-v1"
                )
        # GBP/JPY quote returns converted to CHF, not hardcoded CAD or USD.
        f.cost = replace(f.cost, quote_currency="JPY")
        f.terms = replace(
            f.terms,
            base_currency="GBP",
            quote_currency="JPY",
            account_currency="CHF",
            conversion_rate=D(".006"),
        )
        self.assertEqual(f.run_model().net_account, D("-.01476"))

    def test_terminal_prefix_stop_target_expiry_and_active_gaps(self):
        for high, low, expected in (
            ("105", "97", "stop_adverse_path"),
            ("105", "99", "target_no_improvement"),
            ("101", "99", "time_stop"),
        ):
            f = self.fixture()
            f.setup = replace(f.setup, exit_at=f.setup.entry_at + timedelta(minutes=45))
            prefix = (
                bar(f.setup.entry_at, high="101", low="99", close="100"),
                bar(f.setup.entry_at + timedelta(minutes=15), high="101", low="99", close="100"),
            )
            terminal = bar(
                f.setup.entry_at + timedelta(minutes=30), high=high, low=low, close="100"
            )
            f.terms = replace(
                f.terms, through_at=terminal.end, conversion_at=terminal.end, known_at=terminal.end
            )
            original = f.run_model(prefix + (terminal,))
            self.assertEqual(original.reason, expected)
            for distance in (15, 180):
                assembled = SnapshotInput.series(
                    SimpleNamespace(
                        bars=prefix + (terminal, bar(terminal.end + timedelta(minutes=distance)))
                    ),
                    "M15",
                    outcome=True,
                )
                self.assertEqual(f.run_model(assembled), original)
            self.assertEqual(f.run_model((prefix[0], terminal)).reason, "outcome_interval_gap")
        f = self.fixture()
        f.setup = replace(f.setup, entry_at=f.setup.expires_at)
        self.assertEqual(f.run_model((bar(f.setup.entry_at),)).reason, "pre_entry_interval_gap")

    def test_limit_fill_nonfill_gap_ambiguity_latency_and_quote(self):
        f = self.fixture()
        start = f.setup.signal_start
        f.setup = replace(
            f.setup,
            strategy="fast-mr-h1-v1",
            granularity="H1",
            available_at=start + timedelta(hours=1),
            entry_at=start + timedelta(hours=1),
            expires_at=start + timedelta(hours=2),
            exit_at=start + timedelta(hours=7),
        )
        f.cost = replace(f.cost, component=f.setup.strategy)

        def hour(open, high, low):
            return bar(f.setup.entry_at, open=open, high=high, low=low, close=open)._replace(
                granularity="H1", end=f.setup.entry_at + timedelta(hours=1)
            )

        f.outcome = hour("99.8", "105", "99")
        f.terms = replace(
            f.terms, through_at=f.outcome.end, conversion_at=f.outcome.end, known_at=f.outcome.end
        )
        filled = f.run_model()
        self.assertEqual(filled.entry, D(100))
        self.assertEqual(filled.net_quote, D("3.74"))
        self.assertEqual(f.run_model((hour("99", "105", "98.5"),)).entry, D(100))
        self.assertEqual(
            f.run_model((hour("97", "105", "96"),)).reason, "limit_gap_beyond_invalidation"
        )
        self.assertEqual(
            f.run_model((hour("101", "102", "100.1"),)).reason, "limit_expired_unfilled"
        )
        self.assertEqual(
            f.run_model((hour("101", "105", "99"),)).reason, "limit_intrabar_fill_unavailable"
        )
        self.assertEqual(
            f.run_model(cost=replace(f.cost, latency_seconds=1)).reason, "latency_misses_next_open"
        )
        self.assertEqual(
            f.run_model(cost=replace(f.cost, spread=None)).reason, "incomplete_cost_evidence"
        )
        self.assertNotEqual(filled.intent_sha256, self.fixture().run_model().intent_sha256)
        prerequisite = f.outcome
        f.setup = replace(
            f.setup,
            available_at=f.setup.available_at + timedelta(microseconds=1),
            entry_at=f.setup.expires_at,
        )
        f.outcome = hour("99.8", "105", "99")
        f.terms = replace(
            f.terms, through_at=f.outcome.end, conversion_at=f.outcome.end, known_at=f.outcome.end
        )
        delayed = f.run_model((prerequisite, f.outcome))
        self.assertEqual(delayed.entry, D(100))
        self.assertEqual(delayed.entered_at, f.setup.entry_at)


class StorageCorrections(TestCase):
    def test_cross_kind_hash_consistent_record_is_rejected(self):
        source = snapshot()
        registered = register("fixed-risk-v1")
        evidence = {"snapshot_key": source.idempotency_key, "costs": [], "previous_id": None}
        output = {
            "schema": "phase5/evaluation-v1",
            "strategy": registered.strategy,
            "activation": "forbidden",
            "outputs": [
                json.loads(encoded(RiskOverlay(registered.strategy, D(1), "fixed")))
                | {"value": "20", "buffered": "19", "components": []}
            ],
        }
        with self.assertRaises(DatabaseError), transaction.atomic():
            StrategyEvaluation.objects.create(
                definition=registered,
                snapshot=source,
                evidence=evidence,
                evidence_sha256=identity_digest(evidence),
                output=output,
                output_sha256=identity_digest(output),
                identity=identity_digest(
                    [registered.body_sha256, source.pk, identity_digest(evidence)]
                ),
            )

    def test_forged_parent_cannot_contaminate_a_replayable_child(self):
        instrument, source = make_market()
        observations = []
        for i, start in enumerate(daily_sessions(110)):
            close = D("1.1") + D(i % 7) / D(1000) + D(i) / D(10000)
            observations.append(
                candle(
                    start,
                    bid_close=close,
                    ask_close=close + D(".0002"),
                    bid_high=D("1.2"),
                    ask_high=D("1.2002"),
                )
            )
        ingest(source, instrument, observations, "review-lineage", "D")
        old, _ = compute_market_state(
            instrument, ensure_descriptor_definition(), timezone.now(), ["D"]
        )
        later, _ = compute_market_state(
            instrument, ensure_descriptor_definition(), timezone.now(), ["D"]
        )
        costs = (
            replace(
                cost("ewmac-2-8", "0.00001"),
                quote_currency="CAD",
                known_at=old.information_cutoff,
                valid_from=old.information_cutoff,
                valid_through=later.information_cutoff + timedelta(days=1),
            ),
        )
        legitimate, _ = calculate(old.pk, "ewmac-d-v1", costs=costs)
        output = json.loads(json.dumps(legitimate.output))
        output["outputs"][0]["buffered"] = "19.000000"
        evidence = legitimate.evidence | {"review_forgery": True}
        forged = StrategyEvaluation.objects.create(
            definition=legitimate.definition,
            snapshot=old,
            evidence=evidence,
            evidence_sha256=identity_digest(evidence),
            output=output,
            output_sha256=identity_digest(output),
            identity=identity_digest(
                [legitimate.definition.body_sha256, old.pk, identity_digest(evidence)]
            ),
        )
        self.assertTrue(integrity(after_id=forged.pk - 1, limit=1)["violations"])
        with self.assertRaises(ValueError):
            calculate(later.pk, "ewmac-d-v1", costs=costs, previous_id=forged.pk)
        valid, _ = calculate(later.pk, "ewmac-d-v1", costs=costs, previous_id=legitimate.pk)
        self.assertFalse(integrity(after_id=valid.pk - 1, limit=1)["violations"])
        with self.assertRaisesMessage(ValueError, "previous_attribution_or_cutoff"):
            calculate(later.pk, "breakout-d-v1", previous_id=legitimate.pk)
        other, _ = make_market("EUR_USD", order=2)
        other_snapshot, _ = compute_market_state(
            other, ensure_descriptor_definition(), timezone.now(), ["D"]
        )
        with self.assertRaisesMessage(ValueError, "previous_attribution_or_cutoff"):
            calculate(other_snapshot.pk, "ewmac-d-v1", previous_id=legitimate.pk)
        # A hash-consistent child with correct local replay must still expose its
        # invalid parent, and its grandchild must expose the invalid grandparent.
        parent = forged
        for _ in range(2):
            source, _ = compute_market_state(
                instrument, ensure_descriptor_definition(), timezone.now(), ["D"]
            )
            ev = {
                "snapshot_key": source.idempotency_key,
                "costs": legitimate.evidence["costs"],
                "previous_id": parent.pk,
            }
            out = evaluate(
                load_snapshot(source.pk),
                "ewmac-d-v1",
                costs=costs,
                previous=D(parent.output["outputs"][0]["buffered"]),
            )
            parent = StrategyEvaluation.objects.create(
                definition=legitimate.definition,
                snapshot=source,
                previous=parent,
                evidence=ev,
                evidence_sha256=identity_digest(ev),
                output=out,
                output_sha256=identity_digest(out),
                identity=identity_digest(
                    [legitimate.definition.body_sha256, source.pk, identity_digest(ev)]
                ),
            )
            self.assertTrue(integrity(after_id=parent.pk - 1, limit=1)["violations"])
        with self.assertRaisesMessage(ValueError, "lineage_depth"):
            _verified_chain(valid.pk, max_depth=1)
        with self.assertRaisesMessage(ValueError, "lineage_missing_ancestor"):
            _verified_chain(999999999)
        # Normal SQL guards forbid making a cycle; verifier also fails boundedly
        # if presented with corruption from outside the normal admission path.
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE market_strategyevaluation SET previous_id=id WHERE id=%s", [valid.pk]
            )
        corrupt = SimpleNamespace(pk=valid.pk, previous_id=valid.pk)
        with patch(
            "market.strategy.persistence.StrategyEvaluation.objects.select_related"
        ) as query:
            query.return_value.get.return_value = corrupt
            with self.assertRaisesMessage(ValueError, "lineage_cycle"):
                _verified_chain(valid.pk)
