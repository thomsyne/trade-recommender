from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from assessments.models import MultiTimeframeAssessment
from assessments.services import append_reviewed_eligibility, assess
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.tests.test_live_observations import make_market


class ConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.instrument, _ = make_market()
        eligibility = append_reviewed_eligibility(
            self.instrument,
            era="phase6a-canonical-empty-v1",
            entries=[],
            decision_known_at=timezone.now(),
            phase55_decision_sha256=identity_digest([]),
            phase55_manifest_sha256=identity_digest({}),
            admission_provenance_sha256=identity_digest("canonical-empty-no-phase55-outcome"),
        )
        snapshot = compute_market_state(
            self.instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]
        self.ids = snapshot.pk, eligibility.pk

    def test_concurrent_identical_inputs_create_one_canonical_assessment(self):
        def run(_):
            close_old_connections()
            try:
                row, candidate, created = assess(*self.ids)
                return row.pk, candidate, created
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        self.assertEqual({row_id for row_id, _, _ in results}, {results[0][0]})
        self.assertEqual(sum(created for _, _, created in results), 1)
        self.assertTrue(all(candidate is None for _, candidate, _ in results))
        self.assertEqual(MultiTimeframeAssessment.objects.count(), 1)
