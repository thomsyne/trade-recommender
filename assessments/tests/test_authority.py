from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from assessments.contracts import (
    EMPTY_DECISION_SHA256,
    EMPTY_ELIGIBILITY_ERA,
    EMPTY_MANIFEST_SHA256,
    EMPTY_PROVENANCE_SHA256,
)
from assessments.services import (
    append_capacity_assessment,
    append_cost_evidence,
    append_reviewed_eligibility,
)
from assessments.tests.test_engine import STRATEGY
from market.strategy.definitions import definition_digest
from market.tests.test_live_observations import make_market


class AuthorityBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, _ = make_market()

    def test_nonempty_eligibility_has_no_self_attested_production_seam(self):
        with self.assertRaisesRegex(ValueError, "phase55_authority_unavailable"):
            append_reviewed_eligibility(
                self.instrument,
                era="caller-invented-era",
                entries=[
                    {
                        "strategy": STRATEGY,
                        "definition_sha256": definition_digest(STRATEGY),
                        "role": "setup",
                    }
                ],
                decision_known_at=timezone.now(),
                phase55_decision_sha256="1" * 64,
                phase55_manifest_sha256="2" * 64,
                admission_provenance_sha256="3" * 64,
            )

    def test_empty_eligibility_requires_exact_canonical_provenance_and_era(self):
        common = {
            "instrument": self.instrument,
            "entries": [],
            "decision_known_at": timezone.now(),
            "phase55_decision_sha256": EMPTY_DECISION_SHA256,
            "phase55_manifest_sha256": EMPTY_MANIFEST_SHA256,
            "admission_provenance_sha256": EMPTY_PROVENANCE_SHA256,
        }
        with self.assertRaisesRegex(ValueError, "canonical_empty_eligibility_required"):
            append_reviewed_eligibility(era="wrong-era", **common)
        with self.assertRaisesRegex(ValueError, "canonical_empty_eligibility_required"):
            append_reviewed_eligibility(
                era=EMPTY_ELIGIBILITY_ERA,
                **{**common, "phase55_decision_sha256": "1" * 64},
            )
        first = append_reviewed_eligibility(era=EMPTY_ELIGIBILITY_ERA, **common)
        self.assertEqual(first.decision_known_at, common["decision_known_at"])
        with self.assertRaisesRegex(ValueError, "eligibility_identity_conflict"):
            append_reviewed_eligibility(
                era=EMPTY_ELIGIBILITY_ERA,
                **{**common, "decision_known_at": timezone.now()},
            )

    def test_cost_and_capacity_cannot_be_backdated_or_self_attested(self):
        past = timezone.now() - timedelta(days=365)
        with self.assertRaisesRegex(ValueError, "cost_authority_unavailable"):
            append_cost_evidence(
                self.instrument,
                known_at=past,
                stale_after=past + timedelta(hours=1),
                payload={"source_identity": "fabricated", "timestamp_precision": "provider_exact"},
            )
        with self.assertRaisesRegex(ValueError, "capacity_authority_unavailable"):
            append_capacity_assessment(
                self.instrument,
                assessed_at=past,
                payload={"source_identity": "fabricated", "policy_identity": "fabricated"},
            )
