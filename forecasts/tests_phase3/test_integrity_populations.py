"""Corrupt read populations are injected at the query boundary, never by disabling SQL.

Constraints prohibit many corrupt rows in an ordinary database. These tests prove
that the independent diagnostic still detects those populations if encountered.
Valid records and the clean counterexample use the real database and services.
"""

from copy import copy
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch

from django.test import TestCase

from forecasts.integrity import report
from forecasts.lifecycle import project_lifecycle


class Rows(list):
    def filter(self, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def select_related(self, *args):
        return self

    def iterator(self):
        return iter(self)

    def exists(self):
        return bool(self)

    def first(self):
        return self[0] if self else None

    def count(self):
        return len(self)

    def values_list(self, *args):
        return []


class IntegrityPopulationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from forecasts.tests_phase3.test_database import ProspectiveDatabaseTests

        ProspectiveDatabaseTests.setUpTestData.__func__(cls)

    def setUp(self):
        from forecasts.tests_phase3.test_database import ProspectiveDatabaseTests

        self.prepare = ProspectiveDatabaseTests.prepare.__get__(self)
        self.now, self.rec = ProspectiveDatabaseTests.directional(self)
        self.rec.refresh_from_db()
        self.as_of = self.now + timedelta(seconds=2)
        self.projection = project_lifecycle(self.rec, as_of=self.as_of)
        self.assertEqual(report(as_of=self.as_of)["total"], 0)

    def projected_rec(self):
        rec = self.rec
        values = {f.name: getattr(rec, f.name) for f in rec._meta.fields}
        values.update({f.attname: getattr(rec, f.attname) for f in rec._meta.fields})
        values.update(
            pk=rec.pk,
            lifecycle_events=rec.lifecycle_events,
            paper_lifecycle_events=rec.paper_lifecycle_events,
            portfolio_membership=None,
            portfolio_disposition=rec.portfolio_disposition,
            portfolio_admission_events=Rows(),
            paper_result=None,
            resolution=None,
        )
        return NS(**values)

    def diagnostic(self, rows, projection=None):
        with (
            patch("forecasts.integrity.Recommendation.objects.filter", return_value=Rows(rows)),
            patch(
                "forecasts.integrity.project_lifecycle", return_value=projection or self.projection
            ),
        ):
            return report(as_of=self.as_of)

    def test_named_recommendation_violations_with_clean_counterexamples(self):
        cases = [
            (
                "recommendation_missing_target",
                {"target_occurrence_id": None, "target_occurrence": None},
                {},
            ),
            (
                "recommendation_missing_control",
                {"control_forecast_id": None, "control_forecast": None},
                {},
            ),
            ("canonical_lifecycle_missing", {"lifecycle_events": Rows()}, {}),
            ("directional_disposition_missing", {"portfolio_disposition": None}, {}),
            ("entry_without_active_admission", {}, {"entry_id": 42, "admission_status": None}),
            (
                "non_admitted_awaiting_entry",
                {},
                {"state": "admitted_awaiting_entry", "admission_status": None},
            ),
            ("terminal_result_nonterminal_lifecycle", {}, {"result_id": 42, "terminal": False}),
            ("abstention_execution_records", {"action": "abstain"}, {"entry_id": 42}),
            (
                "result_entry_admission_mismatch",
                {"paper_result": NS(resolved_at=self.as_of, outcome="target", entry_id=None)},
                {},
            ),
            (
                "admission_selection_mismatch",
                {"portfolio_admission_events": Rows([NS(cohort_id=55)])},
                {},
            ),
            (
                "membership_disposition_missing",
                {
                    "portfolio_disposition": None,
                    "portfolio_membership": NS(cohort=NS(generated_at=self.now), cohort_id=55),
                },
                {},
            ),
        ]
        for code, changes, projection in cases:
            with self.subTest(code=code):
                row = self.projected_rec()
                row.__dict__.update(changes)
                result = self.diagnostic([row], self.projection | projection)
                self.assertEqual(result["violations"].get(code), 1)
                self.assertEqual(self.diagnostic([self.projected_rec()])["total"], 0)

    def test_nine_missing_dispositions_are_nine_violations(self):
        rows = []
        for index in range(9):
            row = self.projected_rec()
            row.pk = 100 + index
            row.portfolio_disposition = None
            rows.append(row)
        result = self.diagnostic(rows)
        self.assertEqual(result["violations"]["directional_disposition_missing"], 9)
        self.assertEqual(len(result["details"]), 9)

    def test_late_control_identity_and_shared_disagreement(self):
        for change, code in [
            ("late", "retrospective_control"),
            ("band", "recommendation_control_identity_mismatch"),
            ("shared", "recommendation_shared_resolution_disagreement"),
        ]:
            row = self.projected_rec()
            if change == "shared":
                row.resolution = NS(resolved_at=self.as_of, target_resolution_id=999, outcome="up")
            else:
                control = copy(row.control_forecast)
                if change == "late":
                    control.issued_at = self.as_of
                else:
                    control.neutral_band += 1
                row.control_forecast = control
            with self.subTest(change=change):
                self.assertEqual(self.diagnostic([row])["violations"][code], 1)
            self.assertEqual(self.diagnostic([self.projected_rec()])["total"], 0)

    def test_missing_mature_resolution_and_immature_false_resolution(self):
        from forecasts.targets import target_endpoint
        from market.quality import registered_candle_completion

        target = self.rec.target_occurrence
        maturity = registered_candle_completion(
            target_endpoint(target.reference_candle.timestamp, 5), "D"
        )
        self.assertEqual(
            report(as_of=maturity)["violations"]["mature_target_missing_resolution"], 1
        )
        self.assertEqual(report(as_of=self.as_of)["total"], 0)
        fake = copy(target)
        fake._state = copy(target._state)
        fake._state.fields_cache = dict(target._state.fields_cache)
        fake._state.fields_cache["resolution"] = NS(
            target=target,
            outcome="missing",
            resolved_at=self.as_of,
            resolution_method=target.resolution_method,
            horizon_candle_id=None,
            endpoint_midpoint=None,
            midpoint_change=None,
            horizon_content_sha256="",
        )
        with patch(
            "forecasts.integrity.TargetOccurrence.objects.filter", return_value=Rows([fake])
        ):
            value = report(as_of=self.as_of)
        self.assertEqual(value["violations"]["immature_target_marked_missing"], 1)
        self.assertEqual(value["violations"]["shared_resolution_invalid"], 1)

    def projected_target(self):
        target = self.rec.target_occurrence
        values = {f.name: getattr(target, f.name) for f in target._meta.fields}
        values.update({f.attname: getattr(target, f.attname) for f in target._meta.fields})
        values.update(pk=target.pk, controls=Rows([self.rec.control_forecast]), resolution=None)
        return NS(**values)

    def test_target_control_and_resolution_population_violations(self):
        for code, change in [
            ("target_identity_invalid", "identity"),
            ("multiple_incompatible_target_controls", "methods"),
            ("duplicate_target_control", "duplicate"),
            ("control_target_identity_mismatch", "band"),
            ("multiple_target_resolutions", "resolutions"),
        ]:
            target = self.projected_target()
            controls = Rows([copy(self.rec.control_forecast)])
            if change == "identity":
                target.identity_sha256 = "f" * 64
            if change in ["methods", "duplicate"]:
                second = copy(controls[0])
                second.pk += 100
                if change == "methods":
                    second.method = "other"
                controls.append(second)
            if change == "band":
                controls[0].neutral_band += 1
            target.controls = controls
            with (
                self.subTest(code=code),
                patch(
                    "forecasts.integrity.TargetOccurrence.objects.filter",
                    return_value=Rows([target]),
                ),
            ):
                if change == "resolutions":
                    with patch(
                        "forecasts.integrity.TargetResolution.objects.filter",
                        return_value=Rows([1, 2]),
                    ):
                        value = report(as_of=self.as_of)
                else:
                    value = report(as_of=self.as_of)
                self.assertEqual(value["violations"][code], 1)
            self.assertEqual(report(as_of=self.as_of)["total"], 0)

    def test_selection_and_deadline_violations(self):
        fake = NS(
            pk=600,
            recommendation=self.rec,
            selection=NS(cohort=NS(members=Rows()), admission_events=Rows()),
        )
        with patch(
            "forecasts.integrity.PortfolioSelectionMember.objects.filter", return_value=Rows([fake])
        ):
            value = report(as_of=self.as_of)
        self.assertEqual(value["violations"]["selection_member_outside_cohort"], 1)
        self.assertEqual(value["violations"]["selection_without_admission"], 1)
        cohort = NS(
            pk=700,
            closure=None,
            generated_at=self.now,
            decision_deadline=self.as_of,
            members=Rows(),
        )
        with patch(
            "forecasts.integrity.PortfolioCohort.objects.filter",
            side_effect=[Rows([cohort]), Rows()],
        ):
            value = report(as_of=self.as_of)
        self.assertEqual(value["violations"]["open_cohort_past_deadline"], 1)
        self.assertEqual(report(as_of=self.as_of)["total"], 0)

    def test_mixed_era_before_start_and_independence_reported(self):
        original = self.rec.experiment_samples.get()
        for code, change in [
            ("mixed_contract_era", "method"),
            ("sample_before_cutover", "start"),
            ("repeated_target_independence_mismatch", "identity"),
        ]:
            sample = NS(
                pk=original.pk,
                recommendation=self.projected_rec(),
                era=NS(method=original.era.method, starts_at=original.era.starts_at),
                issuance_cluster_key=original.issuance_cluster_key,
                dependence_cluster_key=original.dependence_cluster_key,
            )
            if change == "method":
                sample.recommendation.provider = "different-method"
            if change == "start":
                sample.era.starts_at = self.as_of
            if change == "identity":
                sample.issuance_cluster_key = "fake-independent-target"
            with (
                self.subTest(code=code),
                patch(
                    "forecasts.integrity.ExperimentSample.objects.filter",
                    return_value=Rows([sample]),
                ),
            ):
                self.assertEqual(report(as_of=self.as_of)["violations"][code], 1)
            self.assertEqual(report(as_of=self.as_of)["total"], 0)

    def test_assessment_population_pairing_cutoff_and_readiness_violations(self):
        from decimal import Decimal

        from forecasts.experiments import refresh_experiment_assessment

        era = self.rec.experiment_samples.get().era
        assessment = refresh_experiment_assessment(era, assessed_at=self.as_of)
        for code, change in [
            ("mature_coverage_denominator_mismatch", "coverage"),
            ("assessment_population_or_cutoff_mismatch", "populations"),
            ("unpaired_sample_or_cutoff_comparison_mismatch", "paired"),
            ("assessment_score_or_cutoff_mismatch", "score"),
            ("paired_readiness_without_complete_controls", "promotion"),
            ("malformed_assessment_metrics", "malformed"),
        ]:
            row = copy(assessment)
            row.metrics = dict(assessment.metrics)
            if change == "coverage":
                row.resolution_coverage = Decimal(1)
            if change == "populations":
                row.metrics["populations"] = {"mature_targets": 999}
            if change == "paired":
                row.metrics["mechanical_comparison"] = {"sample_count": 999}
            if change == "score":
                row.mean_brier_score = Decimal(1)
            if change == "promotion":
                row.status = "promotion_eligible"
            if change == "malformed":
                row.metrics = ["unsafe-provider-body"]
            with (
                self.subTest(code=code),
                patch(
                    "forecasts.integrity.ExperimentAssessment.objects.filter",
                    return_value=Rows([row]),
                ),
            ):
                result = report(as_of=self.as_of)
                self.assertEqual(result["violations"][code], 1)
                self.assertNotIn("unsafe-provider-body", str(result))
            self.assertEqual(report(as_of=self.as_of)["total"], 0)

    def test_superseded_cohort_and_semantic_terminal_source(self):
        class Values(Rows):
            def values_list(self, *args):
                return list(self)

        cohort = NS(
            pk=710,
            closure=None,
            generated_at=self.now,
            decision_deadline=self.as_of + timedelta(hours=1),
            members=Values([(self.rec.instrument_id, self.rec.target_occurrence_id)]),
        )
        with patch(
            "forecasts.integrity.PortfolioCohort.objects.filter",
            side_effect=[
                Rows([cohort]),
                Values([(self.rec.instrument_id, self.rec.target_occurrence_id + 1)]),
            ],
        ):
            result = report(as_of=self.as_of)
        self.assertEqual(result["violations"]["superseded_cohort_without_closure"], 1)
        row = self.projected_rec()
        row.paper_lifecycle_events = Rows(
            [
                NS(
                    pk=720,
                    recommendation=self.rec,
                    state="expired_unobserved",
                    reason_code="hourly_coverage_unavailable",
                    details={"schema_version": 1},
                    occurred_at=self.as_of,
                )
            ]
        )
        result = self.diagnostic([row])
        self.assertEqual(result["violations"]["semantic_lifecycle_evidence_invalid"], 1)
        self.assertEqual(result["violations"]["terminal_source_nonterminal_lifecycle"], 1)
        self.assertEqual(report(as_of=self.as_of)["total"], 0)

    def test_after_cutover_downgrade_is_not_grandfathered(self):
        row = self.projected_rec()
        row.contract_version = 3
        result = self.diagnostic([row])
        self.assertEqual(result["violations"]["prospective_contract_downgrade"], 1)
        row.recorded_at = None
        result = self.diagnostic([row])
        self.assertEqual(result["total"], 0)
        self.assertEqual(sum(result["legacy"].values()), 1)

    def test_forecast_shared_resolution_disagreement(self):
        from forecasts.services import resolve_forecast
        from forecasts.targets import resolve_target, target_endpoint
        from market.quality import registered_candle_completion

        target = self.rec.target_occurrence
        maturity = registered_candle_completion(
            target_endpoint(target.reference_candle.timestamp, 5), "D"
        )
        shared = resolve_target(target, as_of=maturity)
        with self.timeline.at(maturity):
            derived = resolve_forecast(self.rec.control_forecast)
        target_row = self.projected_target()
        target_row.resolution = shared
        control = copy(self.rec.control_forecast)
        control._state = copy(control._state)
        control._state.fields_cache = dict(control._state.fields_cache)
        changed = copy(derived)
        changed.target_resolution_id += 100
        control._state.fields_cache["resolution"] = changed
        target_row.controls = Rows([control])
        with patch(
            "forecasts.integrity.TargetOccurrence.objects.filter", return_value=Rows([target_row])
        ):
            result = report(as_of=maturity)
        self.assertEqual(result["violations"]["forecast_shared_resolution_disagreement"], 1)
        self.assertNotIn(
            "forecast_shared_resolution_disagreement", report(as_of=maturity)["violations"]
        )

    def test_invalid_projection_is_bounded_and_does_not_echo_exception(self):
        with (
            patch(
                "forecasts.integrity.Recommendation.objects.filter",
                return_value=Rows([self.rec] * 61),
            ),
            patch("forecasts.integrity.project_lifecycle", side_effect=ValueError("unsafe-body")),
        ):
            result = report(as_of=self.as_of)
        self.assertEqual(result["violations"]["canonical_projection_invalid"], 61)
        self.assertEqual(len(result["details"]), 50)
        self.assertNotIn("unsafe-body", str(result))
        self.assertEqual(report(as_of=self.as_of)["total"], 0)

    def test_corrupt_assessment_source_is_structured_not_an_exception(self):
        from forecasts.experiments import refresh_experiment_assessment

        sample = copy(self.rec.experiment_samples.get())
        era = sample.era
        assessment = refresh_experiment_assessment(era, assessed_at=self.as_of)
        row = NS(pk=assessment.pk)
        sample.recommendation = copy(self.rec)
        sample.recommendation.target_occurrence = copy(self.rec.target_occurrence)
        sample.recommendation.target_occurrence.horizon_sessions = ["unsafe-body"]
        row.attempt = NS(
            assessed_at=self.as_of,
            era=NS(
                starts_at=era.starts_at,
                evaluation_policy=era.evaluation_policy,
                samples=Rows([sample]),
            ),
        )
        with patch(
            "forecasts.integrity.ExperimentAssessment.objects.filter", return_value=Rows([row])
        ):
            result = report(as_of=self.as_of)
        self.assertEqual(result["violations"]["assessment_source_invalid"], 1)
        self.assertNotIn("unsafe-body", str(result))
        self.assertEqual(report(as_of=self.as_of)["total"], 0)
