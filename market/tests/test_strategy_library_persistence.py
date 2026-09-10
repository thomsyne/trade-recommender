import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from market.models import StrategyDefinition, StrategyEvaluation
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.definitions import STRATEGIES, definition, definition_digest
from market.strategy.persistence import calculate, integrity, load_snapshot, register
from market.tests.test_live_observations import make_market
from market.tests.test_strategy_library_trend import cost


def snapshot():
    instrument, _ = make_market()
    result, _ = compute_market_state(
        instrument,
        ensure_descriptor_definition(),
        datetime(2026, 1, 5, 13, tzinfo=UTC),
        ["M15", "H1", "H4", "D"],
    )
    return result


class PersistenceTests(TestCase):
    def setUp(self):
        self.snapshot = snapshot()

    def test_subquantum_cost_inputs_remain_distinct_and_replayable(self):
        records = []
        cutoff = self.snapshot.information_cutoff
        for amount in ("0.1000003", "0.1000004"):
            evidence = replace(
                cost("ewmac-2-8", amount),
                quote_currency=self.snapshot.instrument.quote_currency,
                known_at=cutoff,
                valid_from=cutoff,
                valid_through=cutoff,
            )
            row, created = calculate(self.snapshot.pk, "ewmac-d-v1", costs=(evidence,))
            self.assertTrue(created)
            self.assertEqual(row.evidence["costs"][0]["spread"], amount)
            records.append(row.pk)
        self.assertEqual(len(set(records)), 2)
        self.assertEqual(integrity()["violations"], [])

    def test_all_definitions_are_sql_pinned_and_retries_are_exact(self):
        pins = import_module("market.migrations.0040_strategy_contract_corrections").PINS
        self.assertEqual(pins, {s: definition_digest(s) for s in STRATEGIES})
        for strategy in STRATEGIES:
            first, created = calculate(self.snapshot.pk, strategy)
            second, again = calculate(self.snapshot.pk, strategy)
            self.assertTrue(created)
            self.assertFalse(again)
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(first.output, second.output)
        self.assertEqual(StrategyEvaluation.objects.count(), len(STRATEGIES))
        self.assertEqual(integrity()["violations"], [])

    def test_definition_holdout_and_raw_mutations_are_refused(self):
        row = register("ewmac-d-v1")
        with self.assertRaises(ValidationError):
            row.save()
        for statement in (
            "UPDATE market_strategydefinition SET strategy=strategy WHERE id=%s",
            "DELETE FROM market_strategydefinition WHERE id=%s",
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, [row.pk])
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE market_strategydefinition CASCADE")
        body = definition("breakout-d-v1")
        body["population"]["holdout"][0] = "2020-01-01"
        with self.assertRaises(DatabaseError), transaction.atomic():
            StrategyDefinition.objects.create(
                strategy="breakout-d-v1", body=body, body_sha256=identity_digest(body)
            )

    def test_output_attribution_schema_and_hash_are_raw_sql_guarded(self):
        row, _ = calculate(self.snapshot.pk, "fixed-risk-v1")
        for field, value in (
            ("output", json.dumps({"schema": "phase5/evaluation-v1", "strategy": "other"})),
            ("output_sha256", "0" * 64),
            ("identity", "f" * 64),
        ):
            columns = [
                "definition_id",
                "snapshot_id",
                "previous_id",
                "evidence",
                "evidence_sha256",
                "output",
                "output_sha256",
                "identity",
                "created_at",
            ]
            expressions = ["%s" if c == field else c for c in columns]
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"INSERT INTO market_strategyevaluation ({','.join(columns)}) SELECT {','.join(expressions)} FROM market_strategyevaluation WHERE id=%s",
                    [value, row.pk],
                )
        with self.assertRaises(DatabaseError), transaction.atomic():
            StrategyEvaluation.objects.filter(pk=row.pk).update(output={})

    def test_reports_preview_and_integrity_are_select_only(self):
        calculate(self.snapshot.pk, "ewmac-d-v1")
        before = list(StrategyEvaluation.objects.values())
        for action, args in (
            ("report", ()),
            ("integrity", ()),
            ("preview", ("--snapshot", str(self.snapshot.pk), "--strategy", "ewmac-d-v1")),
        ):
            with CaptureQueriesContext(connection) as queries:
                call_command("strategy_library", action, *args, stdout=StringIO())
            self.assertTrue(
                all(q["sql"].lstrip().upper().startswith("SELECT") for q in queries),
                [q["sql"] for q in queries],
            )
        self.assertEqual(before, list(StrategyEvaluation.objects.values()))
        frozen = load_snapshot(self.snapshot.pk)
        with self.assertRaises(ValueError):
            type(frozen)(
                frozen.snapshot_id, frozen.envelope_json.replace("0.12.0", "0.11.0"), frozen.bars
            )


class ConcurrencyTests(TransactionTestCase):
    def test_four_writers_resolve_to_one_immutable_evaluation(self):
        source = snapshot()

        def write(_):
            close_old_connections()
            try:
                row, created = calculate(source.pk, "fixed-risk-v1")
                return row.pk, created
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(4)))
        self.assertEqual(len({pk for pk, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)
