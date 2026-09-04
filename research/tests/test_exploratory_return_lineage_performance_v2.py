"""Focused regression tests for the forward-only lineage correction."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from research import exploratory_return_adapter_v2 as adapter_module
from research import exploratory_return_runner_v2 as runner
from research import exploratory_return_runner_v2_governance as governance
from research import exploratory_returns_v2 as calculator
from research.benchmarks.benchmark_exploratory_returns_v2 import synthetic_event


class _QuerySet:
    def __init__(self, calls):
        self.calls = calls

    def filter(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def select_related(self, *_args):
        return self

    def values(self, *_args):
        return []


class LineagePerformanceTests(unittest.TestCase):
    def test_legacy_lookup_rescans_inventory_but_cached_lookup_does_not(self):
        starts = tuple(
            datetime(2010, 1, 1, tzinfo=UTC) + timedelta(hours=index) for index in range(100)
        )
        completions = tuple(value + timedelta(hours=1) for value in starts)
        calls = 0

        def counted(value, _granularity):
            nonlocal calls
            calls += 1
            return value + timedelta(hours=1)

        def legacy(when):
            rebuilt = [counted(value, "H1") for value in starts]
            return starts[adapter_module.bisect_left(rebuilt, when) - 1]

        queries = (completions[10], completions[50], completions[90])
        legacy_results = tuple(legacy(when) for when in queries)
        self.assertEqual(calls, len(starts) * len(queries))
        with mock.patch.object(
            adapter_module,
            "registered_candle_completion",
            side_effect=AssertionError("cached lookup rebuilt completion inventory"),
        ):
            cached_results = tuple(
                adapter_module.DjangoSealedEvidenceAdapter._prior_start(starts, completions, when)
                for when in queries
            )
        self.assertEqual(cached_results, legacy_results)

    def test_cached_lookup_preserves_strict_boundary_semantics(self):
        starts = tuple(
            datetime(2014, 1, 1, tzinfo=UTC) + timedelta(hours=index) for index in range(4)
        )
        completions = tuple(value + timedelta(hours=1) for value in starts)
        self.assertEqual(
            adapter_module.DjangoSealedEvidenceAdapter._prior_start(
                starts, completions, completions[2]
            ),
            starts[1],
        )
        self.assertEqual(
            adapter_module.DjangoSealedEvidenceAdapter._prior_start(
                starts, completions, completions[2] + timedelta(microseconds=1)
            ),
            starts[2],
        )

    def test_cached_lookup_preserves_weekend_dst_and_every_cad_route(self):
        starts = (
            datetime(2014, 3, 7, 21, tzinfo=UTC),
            datetime(2014, 3, 9, 21, tzinfo=UTC),
            datetime(2014, 11, 2, 22, tzinfo=UTC),
        )
        completions = tuple(value + timedelta(hours=1) for value in starts)
        pairs = {pair for route in calculator.CAD_ROUTES.values() for pair, _direction in route}
        self.assertEqual(pairs, {"GBP_USD", "USD_CAD", "USD_JPY"})
        self.assertEqual(set(calculator.CAD_ROUTES), {"CAD", "GBP", "JPY", "USD"})
        for pair in pairs:
            with self.subTest(pair=pair):
                self.assertEqual(
                    adapter_module.DjangoSealedEvidenceAdapter._prior_start(
                        starts, completions, completions[1]
                    ),
                    starts[0],
                )
                self.assertEqual(
                    adapter_module.DjangoSealedEvidenceAdapter._prior_start(
                        starts, completions, completions[1] + timedelta(microseconds=1)
                    ),
                    starts[1],
                )
        with self.assertRaisesRegex(runner.RunnerRefusal, "strictly prior"):
            adapter_module.DjangoSealedEvidenceAdapter._prior_start(
                starts, completions, completions[0]
            )

    def test_candle_query_count_is_fixed_by_governed_groups_not_timestamp_count(self):
        adapter = adapter_module.DjangoSealedEvidenceAdapter()
        adapter._dataset = object()
        groups = {
            (f"PAIR_{index}", granularity): {
                datetime(2014, 1, 1, tzinfo=UTC) + timedelta(hours=row)
                for row in range(1 if size == "small" else 1_000)
            }
            for index in range(6)
            for granularity in ("D", "H1")
            for size in ("large",)
        }
        for timestamps_per_group in (1, 1_000):
            needed = {
                key: set(sorted(values)[:timestamps_per_group]) for key, values in groups.items()
            }
            calls = []
            with mock.patch.object(adapter_module.Candle, "objects", _QuerySet(calls)):
                self.assertEqual(adapter._load_candle_rows(needed), [])
            self.assertEqual(len(calls), 12)

    def test_progress_is_count_only_and_contains_bounded_subphases(self):
        events = [synthetic_event(index) for index in range(82)]
        messages = []
        runner.run_authorized(
            authorization=runner.synthetic_authorization(),
            expected_keys=tuple(row["physical_event_key"] for row in events),
            adapter=runner.SyntheticEvidenceAdapter(events, runner.synthetic_lineage()),
            store=runner.SyntheticAtomicStore(),
            bootstrap=False,
            progress=lambda stage, completed, total: messages.append((stage, completed, total)),
        )
        self.assertEqual(
            [stage for stage, _, _ in messages],
            [
                "upstream_evidence",
                "cohort_reconstruction",
                "entry_evidence",
                "sealed_inventory",
                "evidence_plan",
                "sealed_candles",
                "normalization",
                "normalized",
                "calculation",
                "calculation",
                "commit",
                "commit",
            ],
        )
        self.assertTrue(all(isinstance(value, int) for row in messages for value in row[1:]))
        rendered = repr(messages).lower()
        for forbidden in ("return", "pnl", "profit", "win", "loss", "drawdown", "price"):
            self.assertNotIn(forbidden, rendered)

    def test_both_consumed_authorizations_refuse_and_second_failure_forgery_refuses(self):
        with self.assertRaises(governance.RunnerGovernanceRefusal):
            governance.require_predecessor_execution_authorization()
        with self.assertRaises(governance.RunnerGovernanceRefusal):
            governance.require_consumed_successor_execution_authorization()

        failure = json.loads(governance.SECOND_FAILURE_PATH.read_bytes())
        failure["persistent_state"]["result_rows"] = 1
        body = copy.deepcopy(failure)
        body.pop("failure_sha256")
        failure["failure_sha256"] = governance.digest(body)
        raw = governance.canonical_bytes(failure) + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            forged = Path(directory) / "failure.json"
            forged.write_bytes(raw)
            with (
                mock.patch.object(governance, "SECOND_FAILURE_PATH", forged),
                mock.patch.object(
                    governance,
                    "SECOND_FAILURE_ARTIFACT_SHA256",
                    hashlib.sha256(raw).hexdigest(),
                ),
                mock.patch.object(
                    governance,
                    "SECOND_FAILURE_SELF_SHA256",
                    failure["failure_sha256"],
                ),
                self.assertRaises(governance.RunnerGovernanceRefusal),
            ):
                governance.inspect_execution_authorization()


if __name__ == "__main__":
    unittest.main()
