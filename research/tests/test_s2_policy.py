"""Bounded offline policy tests: no Django, database, prices or returns."""

import ast
import copy
import hashlib
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research import s2_policy as s2


def at(day, hour=0, minute=0):
    return datetime(2018, 12, day, hour, minute, tzinfo=UTC)


def member(opened, completed=None, code="USD_CAD", granularity="H1"):
    return s2.SealedMember(code, granularity, opened, completed or opened + timedelta(hours=1))


def reference(row, **kwargs):
    return s2.AdmittedReference(
        row, s2.digest([row.instrument, row.opened_at.isoformat()]), **kwargs
    )


def reference_latest(inventory, rows, instrument, decision):
    """Deliberately simple independent linear specification for the indexed path."""
    qualifying = [
        m
        for m in inventory
        if m.instrument == instrument and m.granularity == "H1" and m.completed_at < decision
    ]
    if not qualifying:
        raise s2.PolicyRefusal("no prior member")
    chosen = max(qualifying, key=lambda m: m.completed_at)
    matches = [row for row in rows if row.member == chosen]
    if len(matches) != 1:
        raise s2.PolicyRefusal("missing/conflicting evidence")
    result = matches[0]
    if not (
        result.dataset_id == 3 and result.complete and result.successful and not result.conflicting
    ):
        raise s2.PolicyRefusal("inadmissible evidence")
    return result


def reference_horizon(inventory, code, entry):
    daily = sorted(
        m.completed_at
        for m in inventory
        if m.instrument == code and m.granularity == "D" and m.completed_at > entry
    )
    if len(daily) < 10:
        raise s2.PolicyRefusal("insufficient sessions")
    hourly = sorted(
        m.opened_at
        for m in inventory
        if m.instrument == code and m.granularity == "H1" and m.opened_at >= daily[9]
    )
    if not hourly:
        raise s2.PolicyRefusal("missing exit open")
    return hourly[0]


class ArtifactTests(unittest.TestCase):
    def test_canonical_self_hash_sources_and_every_accepted_job_reconstruct(self):
        policy = s2.load_policy()
        self.assertEqual(
            policy["policy_sha256"],
            s2.POLICY_SHA256,
        )
        self.assertEqual(
            s2.POLICY_SHA256,
            "c30896d2fcd943f647f93f53077e7d7d9163c455cca20aad91df8fbcd667e26f",
        )
        self.assertEqual(
            s2.ARTIFACT_SHA256,
            "4f70ea3c86569de5b54ad3f18d7c1021b6067532ba9fb42b62faf1a0b2676e8c",
        )
        self.assertEqual(
            hashlib.sha256(s2.ARTIFACT_PATH.read_bytes()).hexdigest(), s2.ARTIFACT_SHA256
        )
        self.assertEqual(
            s2._verify_jobs(policy["accepted_job_evidence"])["counts"]["entry_eligible"], 204
        )
        self.assertEqual(len(policy["rules"]["costs"]["spread_distribution_hashes"]), 24)
        self.assertEqual(len(policy["rules"]["costs"]["spread_ceilings"]), 6)

    def test_governed_rules_preserved_and_no_predecessor_active_routing(self):
        policy = s2.load_policy()
        self.assertEqual(policy["lineage"]["effective_data_identity"], s2.SUCCESSOR)
        self.assertEqual(policy["lineage"]["dataset_id"], 3)
        self.assertEqual(
            policy["reconstructed_manifest_rules"]["portfolio"]["requested_risk_equity_fraction"],
            0.0025,
        )
        self.assertEqual(policy["rules"]["target"]["minimum_R"], "1.5")
        self.assertEqual(policy["rules"]["holding"]["count"], 10)

    def test_every_reviewed_default_is_exactly_transcribed_and_resolved(self):
        policy = s2.load_policy()
        candidate = s2.load_candidate_policy()
        self.assertEqual(
            [
                {key: value for key, value in row.items() if key != "status"}
                for row in policy["decision_ledger"]
            ],
            [
                {key: value for key, value in row.items() if key != "status"}
                for row in candidate["decision_ledger"]
            ],
        )
        self.assertTrue(
            all(d["status"] == "RESOLVED_OWNER_AUTHORIZED" for d in policy["decision_ledger"])
        )
        self.assertEqual(policy["effective_at"], "2026-09-03")
        self.assertEqual(s2.require_frozen_policy(), policy)

    def test_exploratory_boundary_and_three_authorities_are_exact(self):
        policy = s2.load_policy()
        self.assertIs(policy["exploratory_only"], True)
        self.assertIs(policy["promotion_eligible"], False)
        self.assertIs(policy["promotion_permanently_prohibited"], True)
        self.assertEqual(
            policy["authority_separation"],
            {
                "policy_freeze": "AUTHORIZED_EFFECTIVE",
                "exploratory_return_execution": "SEPARATELY_UNAUTHORIZED",
                "strategy_promotion": "PERMANENTLY_PROHIBITED",
            },
        )
        self.assertFalse(s2.readiness()["execution_ready"])
        self.assertTrue(s2.readiness()["returns_blocked"])

    def test_every_promotion_override_channel_is_powerless(self):
        for channel in ("owner", "cli", "environment", "database", "data_only"):
            with (
                self.subTest(channel=channel),
                self.assertRaisesRegex(s2.PolicyRefusal, "permanently prohibited"),
            ):
                s2.require_strategy_promotion(**{channel: True})
        with patch.dict("os.environ", {"S2_PROMOTION_ELIGIBLE": "true"}):
            with self.assertRaisesRegex(s2.PolicyRefusal, "permanently prohibited"):
                s2.require_strategy_promotion()
        for override in (
            {"future_return": "ADEQUATE"},
            {"successful_outcome": True},
            {"practical_effect_target_R": "0.40"},
        ):
            with (
                self.subTest(override=override),
                self.assertRaisesRegex(s2.PolicyRefusal, "permanently prohibited"),
            ):
                s2.require_strategy_promotion(**override)

    def test_return_execution_remains_separately_unauthorized(self):
        for override in ({}, {"owner": True}, {"database": True}, {"data_only": True}):
            with self.assertRaisesRegex(s2.PolicyRefusal, "separately unauthorized"):
                s2.require_exploratory_return_execution(**override)

    def test_outcome_injection_rehashed_report_still_rejected(self):
        jobs = copy.deepcopy(s2.load_policy()["accepted_job_evidence"])
        report = jobs[2]["evidence"]["report"]
        report["coverage"]["post_entry_price"] = "FORBIDDEN_SENTINEL_NOT_A_PRICE"
        report["report_sha256"] = s2.digest(
            {k: v for k, v in report.items() if k != "report_sha256"}
        )
        with self.assertRaisesRegex(s2.PolicyRefusal, "accepted report hash mismatch"):
            s2._verify_jobs(jobs)

    def test_jobs_wrong_lineage_failed_duplicate_or_configuration_refused(self):
        for mutation in ("dataset", "status", "duplicate", "configuration"):
            jobs = copy.deepcopy(s2.load_policy()["accepted_job_evidence"])
            if mutation == "dataset":
                jobs[2]["dataset_version_id"] = 1
            elif mutation == "status":
                jobs[2]["status"] = "failed"
            elif mutation == "duplicate":
                jobs.append(jobs[-1])
            else:
                jobs[2]["evidence"]["configuration"]["as_of"] = "2025-01-01"
            with self.subTest(mutation=mutation), self.assertRaises(s2.PolicyRefusal):
                s2._verify_jobs(jobs)

    def test_file_digest_noncanonical_and_self_hash_refusals_independent(self):
        raw = s2.ARTIFACT_PATH.read_bytes()
        with self.assertRaisesRegex(s2.PolicyRefusal, "file digest"):
            s2._verified_document(raw + b" ", s2.ARTIFACT_SHA256, "policy_sha256")
        pretty = json.dumps(json.loads(raw), indent=2).encode() + b"\n"
        with self.assertRaisesRegex(s2.PolicyRefusal, "not canonical"):
            s2._verified_document(pretty, hashlib.sha256(pretty).hexdigest(), "policy_sha256")
        body = json.loads(raw)
        body["effective_at"] = "2099-01-01"
        forged = s2.canonical_bytes(body) + b"\n"
        with self.assertRaisesRegex(s2.PolicyRefusal, "self-hash"):
            s2._verified_document(forged, hashlib.sha256(forged).hexdigest(), "policy_sha256")

    def test_loader_refuses_rehashed_boundary_changes_and_override_grants(self):
        mutations = {
            "missing_exploratory": lambda body: body.pop("exploratory_only"),
            "exploratory_false": lambda body: body.__setitem__("exploratory_only", False),
            "missing_permanent": lambda body: body.pop("promotion_permanently_prohibited"),
            "promotion_eligible": lambda body: body.__setitem__("promotion_eligible", True),
            "not_permanent": lambda body: body.__setitem__(
                "promotion_permanently_prohibited", False
            ),
            "authority_grant": lambda body: body["authorization"].__setitem__(
                "strategy_promotion", True
            ),
            "owner_override": lambda body: body["exploratory_boundary"][
                "promotion_override_channels"
            ].__setitem__("owner", "ALLOWED"),
            "practical_effect_target_reinterpretation": lambda body: body[
                "exploratory_boundary"
            ].__setitem__("practical_effect_target_after_geometry", "REINTERPRETED_0.40R"),
            "s2_03_grid_substituted_by_geometry": lambda body: body["sigma_grid_governance"][
                "s2_03_statistical_sensitivity"
            ].__setitem__("sigma_R", list(s2.GEOMETRY_MDE_SIGMA_GRID)),
            "geometry_grid_substituted_by_s2_03": lambda body: body["sigma_grid_governance"][
                "geometry_mde_diagnostic"
            ].__setitem__("sigma_R", list(s2.S2_03_SIGMA_GRID)),
            "geometry_treated_as_s2_03": lambda body: body["sigma_grid_governance"][
                "geometry_mde_diagnostic"
            ].__setitem__("purpose", "HYPOTHETICAL_STATISTICAL_SENSITIVITY_SIMULATION"),
            "cost_grid_treated_as_slippage": lambda body: body["cost_grid_governance"][
                "sensitivity_grid"
            ].__setitem__("classification", "ADVERSE_SLIPPAGE_GRID"),
            "slippage_axis_without_new_policy_version": lambda body: body["cost_grid_governance"][
                "sensitivity_grid"
            ].__setitem__(
                "axes",
                [
                    "round_turn_commission_pips",
                    "annual_notional_financing_rates",
                    "additional_slippage_pips",
                ],
            ),
        }
        original = Path.read_bytes
        for name, mutate in mutations.items():
            body = json.loads(original(s2.ARTIFACT_PATH))
            mutate(body)
            body.pop("policy_sha256", None)
            policy_hash = s2.digest(body)
            body["policy_sha256"] = policy_hash
            raw = s2.canonical_bytes(body) + b"\n"

            def substituted(path, *, _raw=raw):
                return _raw if path.resolve() == s2.ARTIFACT_PATH.resolve() else original(path)

            with (
                self.subTest(name=name),
                patch.object(Path, "read_bytes", substituted),
                patch.object(s2, "ARTIFACT_SHA256", hashlib.sha256(raw).hexdigest()),
                patch.object(s2, "POLICY_SHA256", policy_hash),
                self.assertRaises(s2.PolicyRefusal),
            ):
                s2.load_policy()

    def test_governed_source_drift_refused_without_editing_files(self):
        original = Path.read_bytes

        def changed(path):
            raw = original(path)
            return raw + b" " if path.name == "phase-1-specification.md" else raw

        with (
            patch.object(Path, "read_bytes", changed),
            self.assertRaisesRegex(s2.PolicyRefusal, "source changed"),
        ):
            s2.load_policy()

    def test_fixed_path_no_environment_override(self):
        with patch.dict(
            "os.environ", {"S2_ARTIFACT_PATH": "/not/a/policy", "POSTGRES_DB": "forbidden"}
        ):
            self.assertEqual(s2.load_policy()["policy_sha256"], s2.POLICY_SHA256)
        with self.assertRaises(TypeError):
            s2.load_policy(path="arbitrary.json")

    def test_actual_geometry_adequacy_and_non_authoritative_proxies_are_pinned(self):
        diagnostic = s2.design_diagnostic(s2.load_policy())
        self.assertEqual(diagnostic["combined_eligible_physical_events"], 90)
        self.assertEqual(diagnostic["entry_week_kish_exact"], "2025/34")
        self.assertEqual(diagnostic["shared_factor_kish_exact"], "4050/67")
        self.assertEqual(
            diagnostic["adequacy_at_0_20R"],
            {
                "sigma_0_5_R": "ADEQUATE",
                "sigma_1_0_R": "NOT_ADEQUATE",
                "sigma_1_5_R": "NOT_ADEQUATE",
            },
        )
        self.assertFalse(diagnostic["confirmatory_adequacy_across_geometry_mde_diagnostic_grid"])
        self.assertEqual(
            diagnostic["singleton_408_statistic"],
            "NON_AUTHORITATIVE_NOT_INDEPENDENCE_EVIDENCE",
        )
        self.assertEqual(
            diagnostic["confirmed_setup_kish"],
            "PROHIBITED_SUBSTITUTE_FOR_TRADE_LEVEL_EFFECTIVE_SAMPLE_SIZE",
        )
        self.assertIsNone(diagnostic["attained_power"])

    def test_sigma_grids_have_distinct_exact_non_interchangeable_purposes(self):
        governance = s2.readiness()["sigma_grid_governance"]
        self.assertEqual(
            governance["s2_03_statistical_sensitivity"],
            {
                "hypothetical": True,
                "observed_return_selection_or_estimation": "PROHIBITED",
                "purpose": "HYPOTHETICAL_STATISTICAL_SENSITIVITY_SIMULATION",
                "sigma_R": ["0.5", "1.0", "2.0"],
            },
        )
        self.assertEqual(governance["geometry_mde_diagnostic"]["sigma_R"], ["0.5", "1.0", "1.5"])
        self.assertEqual(
            governance["geometry_mde_diagnostic"]["purpose"],
            "RETURN_BLIND_GEOMETRY_MDE_DIAGNOSTIC",
        )
        self.assertFalse(governance["geometry_mde_diagnostic"]["promotion_authority"])
        self.assertEqual(
            governance["relationship"],
            {
                "interchangeable": False,
                "observed_return_may_select_replace_or_reinterpret": False,
                "override": "NEITHER_GRID_OVERRIDES_THE_OTHER",
            },
        )

    def test_cost_grid_is_exact_commission_by_financing_with_no_slippage_axis(self):
        governance = s2.readiness()["cost_grid_governance"]
        self.assertEqual(governance["additional_slippage_pips"], "0")
        self.assertEqual(governance["additional_slippage_model"], "NONE")
        self.assertEqual(
            governance["observed_bid_ask_spread"],
            "APPLIED_UNDER_GOVERNED_EXECUTION_CONVENTION",
        )
        grid = governance["sensitivity_grid"]
        self.assertEqual(grid["cell_count"], 15)
        self.assertEqual(grid["classification"], "COMMISSION_X_FINANCING_NOT_SLIPPAGE")
        self.assertEqual(
            grid["axes"],
            ["round_turn_commission_pips", "annual_notional_financing_rates"],
        )
        self.assertIs(grid["slippage_axis"], False)
        self.assertEqual(governance["limitation"]["assessment"], "OPTIMISTIC_LIMITATION")
        self.assertIs(
            governance["limitation"][
                "exploratory_results_cannot_authorize_promotion_or_live_trading"
            ],
            True,
        )
        self.assertEqual(
            governance["limitation"]["future_slippage_model_requires"],
            ["NEW_STRATEGY_POLICY_VERSION", "GENUINELY_UNTOUCHED_CONFIRMATORY_EVIDENCE"],
        )

    def test_bad_cluster_histogram_refused(self):
        with self.assertRaises(s2.PolicyRefusal):
            s2._cluster_facts({"size_distribution": {"2": 3}, "clusters": 3, "members": 3})

    def test_cli_offline_readiness_and_authority_refusal(self):
        output = io.StringIO()
        with redirect_stdout(output):
            s2.main([])
        self.assertEqual(
            json.loads(output.getvalue())["status"],
            "EFFECTIVE_EXPLORATORY_ONLY_RETURNS_SEPARATELY_UNAUTHORIZED",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            s2.main(["--require-frozen"])
        self.assertTrue(json.loads(output.getvalue())["policy_freeze_authorized"])
        for option in ("--require-return-execution", "--require-promotion"):
            with (
                self.subTest(option=option),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                s2.main([option])
            self.assertEqual(raised.exception.code, 2)

    def test_execute_and_arbitrary_input_options_do_not_exist(self):
        for option in ("--execute", "--dataset-id", "--artifact", "--outcomes"):
            with (
                self.subTest(option=option),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                s2.main([option])

    def test_stdlib_only_import_boundary_and_no_dynamic_eval(self):
        tree = ast.parse(Path(s2.__file__).read_text())
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if isinstance(node, ast.ImportFrom) else [])
            )
            self.assertTrue(all(name.split(".")[0] in sys.stdlib_module_names for name in names))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"eval", "exec", "__import__"})

    def test_readiness_needs_no_database_network_or_writable_file(self):
        original = Path.read_bytes
        allowed = {
            s2.ARTIFACT_PATH.resolve(),
            s2.CANDIDATE_ARTIFACT_PATH.resolve(),
            s2.GEOMETRY_ARTIFACT_PATH.resolve(),
        }
        policy = s2.load_policy()
        allowed.update((s2.ROOT / path).resolve() for path in policy["source_sha256"])

        def guarded_read(path):
            self.assertIn(path.resolve(), allowed)
            return original(path)

        with (
            patch("socket.socket", side_effect=AssertionError("network forbidden")),
            patch("sqlite3.connect", side_effect=AssertionError("database forbidden")),
            patch.object(Path, "read_bytes", guarded_read),
            patch.object(Path, "write_bytes", side_effect=AssertionError("write forbidden")),
            patch.object(Path, "write_text", side_effect=AssertionError("write forbidden")),
        ):
            self.assertEqual(
                s2.readiness()["status"],
                "EFFECTIVE_EXPLORATORY_ONLY_RETURNS_SEPARATELY_UNAUTHORIZED",
            )

    def test_freeze_provenance_proves_no_outcome_or_persistent_access(self):
        policy = s2.load_policy()
        self.assertEqual(
            {
                key: policy["freeze_provenance"][key]
                for key in (
                    "candle_payload_read",
                    "database_read",
                    "outcome_evidence_accessed",
                    "provider_or_network_access",
                    "return_calculated",
                )
            },
            {
                "candle_payload_read": False,
                "database_read": False,
                "outcome_evidence_accessed": False,
                "provider_or_network_access": False,
                "return_calculated": False,
            },
        )
        self.assertNotIn("merely", policy["rules"]["change_control"]["rule"])
        self.assertIn("unconditionally immutable", policy["rules"]["change_control"]["rule"])


class MetadataBoundaryTests(unittest.TestCase):
    def test_holiday_successor_is_exact_unusual_sealed_member(self):
        friday = member(at(21, 20))
        after_holiday = member(at(26, 22, 7))
        index = s2.SealedMetadataIndex(
            [after_holiday, friday], [reference(friday), reference(after_holiday)]
        )
        self.assertEqual(
            index.next_entry("USD_CAD", friday.completed_at, after_holiday.completed_at).member,
            after_holiday,
        )
        self.assertEqual(
            index.latest_conversion_before("USD_CAD", after_holiday.opened_at).member, friday
        )

    def test_each_conversion_leg_resolves_independently_and_strict_equality_excluded(self):
        old_usd = member(at(3, 8))
        equal_usd = member(at(3, 10))
        gbp = member(at(3, 9), code="GBP_USD")
        rows = [old_usd, equal_usd, gbp]
        index = s2.SealedMetadataIndex(rows, [reference(row) for row in rows])
        self.assertEqual(index.latest_conversion_before("USD_CAD", at(3, 11)).member, old_usd)
        self.assertEqual(index.latest_conversion_before("GBP_USD", at(3, 11)).member, gbp)

    def test_missing_latest_required_member_never_falls_back(self):
        older, required = member(at(3, 8)), member(at(3, 9))
        index = s2.SealedMetadataIndex([older, required], [reference(older)])
        with self.assertRaisesRegex(s2.PolicyRefusal, "expected sealed evidence missing"):
            index.latest_conversion_before("USD_CAD", at(3, 11))

    def test_no_prior_conflicting_failed_incomplete_or_predecessor_refused(self):
        row = member(at(3, 9))
        for flags in (
            {"conflicting": True},
            {"successful": False},
            {"complete": False},
            {"dataset_id": 1},
        ):
            index = s2.SealedMetadataIndex([row], [reference(row, **flags)])
            with (
                self.subTest(flags=flags),
                self.assertRaisesRegex(s2.PolicyRefusal, "DATA_INCOMPLETE"),
            ):
                index.latest_conversion_before("USD_CAD", at(3, 11))
        with self.assertRaisesRegex(s2.PolicyRefusal, "no strictly prior"):
            s2.SealedMetadataIndex([row], [reference(row)]).latest_conversion_before(
                "USD_CAD", at(3, 10)
            )

    def test_duplicates_unregistered_or_overlap_refused(self):
        row = member(at(3, 9))
        bad_cases = [
            ([row, row], []),
            ([row], [reference(row), reference(row)]),
            ([], [reference(row)]),
            ([row, member(at(3, 9, 30))], []),
        ]
        for inventory, refs in bad_cases:
            with self.subTest(inventory=inventory), self.assertRaises(s2.PolicyRefusal):
                s2.SealedMetadataIndex(inventory, refs)

    def test_missing_or_unadmitted_entry_refused_instead_of_shifted(self):
        row, later = member(at(3, 9)), member(at(3, 11))
        index = s2.SealedMetadataIndex([row, later], [reference(later)])
        with self.assertRaises(s2.PolicyRefusal):
            index.next_entry("USD_CAD", at(3, 9), at(3, 12))
        complete = s2.SealedMetadataIndex([row], [reference(row)])
        with self.assertRaises(s2.PolicyRefusal):
            complete.next_entry("USD_CAD", at(3, 9), at(3, 9, 30))

    def test_ten_actual_sessions_entry_containing_and_boundary_equality(self):
        # Observed omissions, not weekday counting. No future candle payloads.
        days = [3, 4, 5, 6, 7, 10, 11, 13, 14, 17, 18]
        daily = [member(at(day, 0), at(day, 22), granularity="D") for day in days]
        hourly = [member(at(day, 22)) for day in days]
        inventory = daily + hourly
        index = s2.SealedMetadataIndex(inventory, [])
        for entry in (at(3, 21), at(3, 22)):
            self.assertEqual(
                index.maximum_horizon_timestamp("USD_CAD", entry),
                reference_horizon(inventory, "USD_CAD", entry),
            )
        self.assertEqual(index.maximum_horizon_timestamp("USD_CAD", at(3, 21)), at(17, 22))
        self.assertEqual(index.maximum_horizon_timestamp("USD_CAD", at(3, 22)), at(18, 22))
        boundary = at(17, 22)
        self.assertFalse(index.maximum_horizon_timestamp("USD_CAD", at(3, 21)) < boundary)

    def test_horizon_insufficient_sessions_or_successor_refused(self):
        daily = [member(at(day), at(day, 22), granularity="D") for day in range(1, 11)]
        for rows in (daily[:9], daily):
            with self.subTest(count=len(rows)), self.assertRaises(s2.PolicyRefusal):
                s2.SealedMetadataIndex(rows, []).maximum_horizon_timestamp("USD_CAD", at(1))

    def test_naive_timestamp_refused(self):
        with self.assertRaises(s2.PolicyRefusal):
            s2.SealedMetadataIndex([member(datetime(2018, 1, 1))], [])

    def test_projection_entry_open_only_and_conversion_strictly_prior(self):
        row = member(at(3, 9))
        valid = {
            "purpose": "entry_open",
            "fields": {"timestamp", "bid_open", "ask_open"},
            "member": row,
            "decision_at": row.opened_at,
            "admitted_as_of": row.completed_at,
        }
        s2.require_projection(**valid)
        for field in (
            "bid_high",
            "bid_low",
            "bid_close",
            "ask_high",
            "ask_low",
            "ask_close",
            "volume",
            "return",
        ):
            with self.subTest(field=field), self.assertRaises(s2.PolicyRefusal):
                s2.require_projection(**{**valid, "fields": valid["fields"] | {field}})
        with self.assertRaises(s2.PolicyRefusal):
            s2.require_projection(**{**valid, "decision_at": at(3, 8)})
        conversion = {
            **valid,
            "purpose": "conversion",
            "fields": {"timestamp", "completed_at", "midpoint_close"},
        }
        with self.assertRaises(s2.PolicyRefusal):
            s2.require_projection(**{**conversion, "decision_at": row.completed_at})
        s2.require_projection(
            **{**conversion, "decision_at": row.completed_at + timedelta(seconds=1)}
        )

    def test_metadata_type_cannot_contain_payload(self):
        with self.assertRaises(TypeError):
            s2.SealedMember("USD_CAD", "H1", at(3), at(3, 1), bid_close="forbidden")

    def test_index_matches_golden_reference_with_gaps_and_progress(self):
        start = datetime(2018, 1, 1, tzinfo=UTC)
        inventory = [member(start + timedelta(hours=2 * n, minutes=n % 7)) for n in range(256)]
        refs = [reference(row) for row in inventory]
        index = s2.SealedMetadataIndex(reversed(inventory), reversed(refs))
        for n in range(1, 256, 3):
            decision = inventory[n].opened_at
            self.assertEqual(
                index.latest_conversion_before("USD_CAD", decision),
                reference_latest(inventory, refs, "USD_CAD", decision),
            )
        self.assertEqual(
            index.progress,
            {"expected_sealed_members": 256, "loaded_members": 256, "metadata_queries": 85},
        )


if __name__ == "__main__":
    unittest.main()
