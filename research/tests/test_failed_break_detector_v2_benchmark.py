import hashlib
import json
from pathlib import Path

from django.test import SimpleTestCase

from research.benchmarks import detector_v2_benchmark as benchmark
from research.benchmarks.detector_v2_benchmark import (
    DEFAULT_EVENT_COUNT,
    DISPOSABLE_DATABASE_PREFIX,
    _synthetic_inventory,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs/strategy/failed-break/v2"


class DetectorV2BenchmarkHarnessTests(SimpleTestCase):
    def test_governed_synthetic_workload_is_exact_and_deterministic(self):
        first = _synthetic_inventory(DEFAULT_EVENT_COUNT)
        second = _synthetic_inventory(DEFAULT_EVENT_COUNT)

        self.assertEqual(first, second)
        self.assertEqual(
            {key: len(value) for key, value in first.items()}, {"H1": 60000, "D": 3000, "W": 500}
        )
        self.assertEqual(sum(map(len, first.values())), DEFAULT_EVENT_COUNT)

    def test_synthetic_workload_refuses_an_unreported_event_count(self):
        with self.assertRaisesMessage(ValueError, "exactly 63500 events"):
            _synthetic_inventory(DEFAULT_EVENT_COUNT - 1)

    def test_persistence_database_prefix_is_narrow(self):
        self.assertEqual(DISPOSABLE_DATABASE_PREFIX, "detector_v2_benchmark_")
        self.assertFalse("trade_recommender".startswith(DISPOSABLE_DATABASE_PREFIX))
        self.assertFalse("trade_recommender_research".startswith(DISPOSABLE_DATABASE_PREFIX))

    def test_committed_results_bind_the_harness_and_disclose_boundaries(self):
        harness_sha256 = hashlib.sha256(Path(benchmark.__file__).read_bytes()).hexdigest()
        compute = json.loads((RESULTS / "detector-v2-compute-benchmark.json").read_bytes())
        persistence = json.loads((RESULTS / "detector-v2-persistence-benchmark.json").read_bytes())

        self.assertEqual(compute["environment"]["harness_sha256"], harness_sha256)
        self.assertEqual(persistence["environment"]["harness_sha256"], harness_sha256)
        self.assertEqual(compute["invocation_workload"]["event_count"], 63500)
        self.assertIn("persistent S1 evidence writes", compute["scope"]["excludes"])
        self.assertTrue(persistence["database_guard"]["schema_removed_after_measurement"])
        self.assertEqual(
            persistence["database_guard"]["required_prefix"], DISPOSABLE_DATABASE_PREFIX
        )
        self.assertIn("a production v2 S1 runner", persistence["scope"]["excludes"])
        self.assertEqual(
            persistence["workload"]["representative_persistence_rows"]["analysis_runs"], 6216
        )
