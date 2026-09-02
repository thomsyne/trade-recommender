from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from research.failed_break_detector import (
    CAD_CONVERSION_POLICY_IDENTITY,
    _cad_conversion_with_evidence,
    _persist_data_incomplete_remainder,
)
from research.models import AnalysisRun
from research.pre_s1_governance import CAD_CONVERSION_ROUTES
from research.s0_acceptance import load_s0_acceptance


class S0AcceptanceArtifactTests(SimpleTestCase):
    def test_committed_artifact_is_canonical_self_hashed_and_complete(self):
        artifact = load_s0_acceptance()
        self.assertEqual(artifact["s0"]["eligible_session_observations"], 201101)
        self.assertEqual(len(artifact["s0"]["spread_distribution_hashes"]), 24)
        self.assertEqual(
            set(artifact["s0"]["spread_ceilings"]), set(artifact["s0"]["warmup_counts"])
        )
        self.assertTrue(
            all(
                value == 0
                for granularities in artifact["s0"]["missingness"].values()
                for value in granularities.values()
            )
        )


class CadConversionPolicyTests(SimpleTestCase):
    ENTRY = datetime(2018, 12, 3, 12, tzinfo=UTC)

    @staticmethod
    def leg(instrument, rate, hour):
        completed = CadConversionPolicyTests.ENTRY - timedelta(hours=hour)
        return (
            Decimal(rate),
            completed,
            {
                "instrument": instrument,
                "timestamp": (completed - timedelta(hours=1)).isoformat(),
                "completed_at": completed.isoformat(),
                "midpoint_close": rate,
                "evidence_sha256": instrument.lower().replace("_", "") * 4,
            },
        )

    def test_fixed_jpy_inverse_and_usd_cad_direct_route_is_reconstructible(self):
        legs = {
            "USD_JPY": self.leg("USD_JPY", "112", 3),
            "USD_CAD": self.leg("USD_CAD", "1.32", 1),
        }
        with patch(
            "research.failed_break_detector._latest_pre_entry_leg",
            side_effect=lambda _dataset, code, _entry, _contract: legs[code],
        ):
            rate, effective_at, identity, evidence = _cad_conversion_with_evidence(
                object(), SimpleNamespace(quote_currency="JPY"), self.ENTRY, object()
            )
        self.assertEqual(rate, Decimal("1.32") / Decimal("112"))
        self.assertEqual(effective_at, self.ENTRY - timedelta(hours=1))
        self.assertTrue(identity.startswith(f"{CAD_CONVERSION_POLICY_IDENTITY}:"))
        self.assertEqual(
            [(row["instrument"], row["direction"]) for row in evidence["route"]],
            [("USD_JPY", "divide"), ("USD_CAD", "multiply")],
        )

    def test_route_table_freezes_identity_direct_and_multileg_paths(self):
        self.assertEqual(
            CAD_CONVERSION_ROUTES,
            {
                "CAD": (),
                "USD": (("USD_CAD", "multiply"),),
                "GBP": (("GBP_USD", "multiply"), ("USD_CAD", "multiply")),
                "JPY": (("USD_JPY", "divide"), ("USD_CAD", "multiply")),
            },
        )
        legs = {
            "GBP_USD": self.leg("GBP_USD", "1.25", 72),
            "USD_CAD": self.leg("USD_CAD", "1.32", 71),
        }
        with patch(
            "research.failed_break_detector._latest_pre_entry_leg",
            side_effect=lambda _dataset, code, _entry, _contract: legs[code],
        ):
            rate, effective_at, identity, evidence = _cad_conversion_with_evidence(
                object(), SimpleNamespace(quote_currency="GBP"), self.ENTRY, object()
            )
        self.assertEqual(rate, Decimal("1.25") * Decimal("1.32"))
        self.assertEqual(effective_at, self.ENTRY - timedelta(hours=71))
        self.assertTrue(identity.startswith(f"{CAD_CONVERSION_POLICY_IDENTITY}:"))
        self.assertNotIn("failure", evidence)

    def test_missing_leg_fails_closed_without_conversion(self):
        with patch("research.failed_break_detector._latest_pre_entry_leg", return_value=None):
            rate, effective_at, identity, evidence = _cad_conversion_with_evidence(
                object(), SimpleNamespace(quote_currency="USD"), self.ENTRY, object()
            )
        self.assertIsNone(rate)
        self.assertIsNone(effective_at)
        self.assertEqual(identity, "")
        self.assertEqual(evidence["failure"], "MISSING_OR_CONFLICTING_USD_CAD")


class DataQualityOutcomeTests(SimpleTestCase):
    def test_gap_persists_one_outcome_per_remaining_sealed_h1(self):
        first = datetime(2018, 1, 1, 1, tzinfo=UTC)
        remaining = ((first, first - timedelta(hours=1)), (first + timedelta(hours=4), first))
        with patch("research.failed_break_detector.persist_analysis") as persist:
            _persist_data_incomplete_remainder(
                instrument=object(),
                dataset=object(),
                strategy=object(),
                ranges=(),
                pending=(),
                remaining_h1=remaining,
                failed_at=first,
                reason="MISSING_OR_CONFLICTING_H1_EVIDENCE",
            )
        self.assertEqual(persist.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs["result"] == AnalysisRun.Result.DATA_INCOMPLETE
                for call in persist.call_args_list
            )
        )
        self.assertEqual(
            persist.call_args_list[1].kwargs["evidence"]["reason"],
            "PRIOR_REQUIRED_EVIDENCE_UNRESOLVED",
        )

    def test_gap_cancels_a_still_pending_setup_with_governed_state(self):
        first = datetime(2018, 1, 1, 1, tzinfo=UTC)
        transition_filter = SimpleNamespace(first=lambda: None)
        setup = SimpleNamespace(
            pk=7,
            setuptransition_set=SimpleNamespace(filter=lambda **_kwargs: transition_filter),
        )
        pending = SimpleNamespace(setup=setup)
        with (
            patch("research.failed_break_detector.persist_confirmation") as persist_confirmation,
            patch("research.failed_break_detector.persist_analysis"),
        ):
            _persist_data_incomplete_remainder(
                instrument=object(),
                dataset=object(),
                strategy=object(),
                ranges=(),
                pending=(pending,),
                remaining_h1=((first, first - timedelta(hours=1)),),
                failed_at=first,
                reason="MISSING_OR_CONFLICTING_H1_EVIDENCE",
            )
        confirmation = persist_confirmation.call_args.kwargs["confirmation"]
        self.assertEqual(confirmation.state, "CANCELLED_DATA_QUALITY")
        self.assertEqual(confirmation.at, first)
