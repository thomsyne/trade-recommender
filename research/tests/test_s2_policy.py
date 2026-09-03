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
        self.assertEqual(policy["policy_sha256"], s2.POLICY_SHA256)
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

    def test_every_new_rule_pending_and_no_effective_authority(self):
        policy = s2.load_policy()
        self.assertTrue(
            all(d["status"] == "PENDING_OWNER_AUTHORIZATION" for d in policy["decision_ledger"])
        )
        self.assertIsNone(policy["effective_at"])
        self.assertTrue(all(value is False for value in policy["authorization"].values()))
        self.assertFalse(s2.readiness()["execution_ready"])
        with self.assertRaises(s2.PolicyRefusal):
            s2.require_frozen_policy()

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

    def test_count_only_diagnostic_never_counts_family_evaluations_as_independent(self):
        diagnostic = s2.design_diagnostic(s2.load_policy())
        self.assertEqual(diagnostic["combined_eligible_physical_events"], 90)
        self.assertEqual(diagnostic["family_plus_combined_evaluations_not_independent"], 204)
        self.assertEqual(
            diagnostic["confirmed_week_clusters_not_eligible_clusters"],
            {"members": 316, "raw_clusters": 196, "kish_exact": "49928/331"},
        )
        self.assertEqual(
            diagnostic["minimum_independent_units_at_proposed_effect_by_assumed_sigma_R"],
            {"0.5": 50, "1": 197, "2": 785},
        )
        self.assertIsNone(diagnostic["attained_power"])
        self.assertFalse(diagnostic["sufficiency_claim"])

    def test_bad_cluster_histogram_refused(self):
        with self.assertRaises(s2.PolicyRefusal):
            s2._cluster_facts({"size_distribution": {"2": 3}, "clusters": 3, "members": 3})

    def test_cli_offline_readiness_and_authority_refusal(self):
        output = io.StringIO()
        with redirect_stdout(output):
            s2.main([])
        self.assertEqual(json.loads(output.getvalue())["status"], "REVIEW_REQUIRED")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            s2.main(["--require-frozen"])
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
        allowed = {s2.ARTIFACT_PATH.resolve()}
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
            self.assertEqual(s2.readiness()["status"], "REVIEW_REQUIRED")


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
