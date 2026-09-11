import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from assessments.contracts import (
    EMPTY_DECISION_SHA256,
    EMPTY_ELIGIBILITY_ERA,
    EMPTY_MANIFEST_SHA256,
    EMPTY_PROVENANCE_SHA256,
)
from assessments.models import (
    EligibleTradeIntentCandidate,
    MultiTimeframeAssessment,
)
from assessments.services import (
    _eligibility_reference,
    append_reviewed_eligibility,
    assess,
    audit_integrity,
    register_method,
    replay,
)
from assessments.tests.test_engine import STRATEGY
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.persistence import calculate as calculate_strategy
from market.strategy.persistence import register
from market.tests.test_live_observations import make_market
from research.evidence_store import freeze_packet


class DatabaseBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, _ = make_market()

    def empty_eligibility(self):
        now = timezone.now()
        return append_reviewed_eligibility(
            self.instrument,
            era=EMPTY_ELIGIBILITY_ERA,
            entries=[],
            decision_known_at=now,
            phase55_decision_sha256=EMPTY_DECISION_SHA256,
            phase55_manifest_sha256=EMPTY_MANIFEST_SHA256,
            admission_provenance_sha256=EMPTY_PROVENANCE_SHA256,
        )

    def frozen_snapshot(self):
        return compute_market_state(
            self.instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]

    def test_database_clock_no_backdating_immutable_and_empty_default_replays(self):
        eligibility = self.empty_eligibility()
        self.assertGreaterEqual(eligibility.valid_from, eligibility.decision_known_at)
        snapshot = self.frozen_snapshot()
        row, candidate, created = assess(snapshot.pk, eligibility.pk)
        again, again_candidate, again_created = assess(snapshot.pk, eligibility.pk)
        self.assertTrue(created)
        self.assertFalse(again_created)
        self.assertEqual(row.pk, again.pk)
        self.assertIsNone(candidate)
        self.assertIsNone(again_candidate)
        self.assertEqual(
            row.output["decision"]["primary_reason"], "no_economically_admitted_strategy"
        )
        self.assertEqual(replay(row.pk).output_digest, row.output_digest)
        self.assertEqual(audit_integrity()["violations"], [])
        with connection.cursor() as cursor:
            cursor.execute("SELECT phase6a_expected_empty_output(%s)", [snapshot.pk])
            sql_output = cursor.fetchone()[0]
            self.assertEqual(
                json.loads(sql_output) if isinstance(sql_output, str) else sql_output, row.output
            )
        self.assertEqual(EligibleTradeIntentCandidate.objects.count(), 0)
        with self.assertRaises(ValidationError):
            row.save()
        for statement, table in (
            ("UPDATE assessments_multitimeframeassessment SET output=output WHERE id=%s", "row"),
            ("DELETE FROM assessments_eligibilitysnapshot WHERE id=%s", "eligibility"),
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, [row.pk if table == "row" else eligibility.pk])

    def test_raw_sql_eligibility_and_hash_consistent_assessment_forgery_fail(self):
        eligibility = self.empty_eligibility()
        snapshot = self.frozen_snapshot()
        method = register_method()
        register(STRATEGY)
        invented_admission = {
            **eligibility.payload,
            "era": "caller-invented-era",
            "phase55_decision_sha256": "1" * 64,
            "phase55_manifest_sha256": "2" * 64,
            "admission_provenance_sha256": "3" * 64,
            "entries": [
                {
                    "strategy": STRATEGY,
                    "definition_sha256": register(STRATEGY).body_sha256,
                    "role": "setup",
                    "required_evidence_ids": [],
                }
            ],
        }
        for forged_eligibility in (
            {**eligibility.payload, "era": "wrong-era"},
            {**eligibility.payload, "phase55_decision_sha256": "1" * 64},
            invented_admission,
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO assessments_eligibilitysnapshot "
                    "(instrument_id,valid_from,valid_until,decision_known_at,payload,digest,recorded_at) "
                    "VALUES (%s,now()-interval '1 year',NULL,now(),%s,%s,now()-interval '1 year')",
                    [
                        self.instrument.pk,
                        json.dumps(forged_eligibility),
                        identity_digest(forged_eligibility),
                    ],
                )
        manifest = {
            "schema": "phase6a/input-manifest-v1",
            "method": method.digest,
            "snapshot": {"id": snapshot.pk, "identity": snapshot.idempotency_key},
            "eligibility": _eligibility_reference(eligibility),
            "evaluations": [],
            "cost": None,
            "capacity": None,
            "evidence": None,
        }
        forged_output = {
            "schema": "phase6a/assessment-v2",
            "status": "available",
            "information_cutoff": snapshot.output_payload["information_cutoff"],
            "htf_regime": {"state": "available"},
            "major_zones": {"state": "available"},
            "eligible_strategies": {"state": "available"},
            "directional_triggers": {"state": "available"},
            "mechanical_trigger": {"state": "available"},
            "reward_and_cost": {"state": "available"},
            "capacity": {"state": "available"},
            "terminal_state": {"state": "available"},
            "decision": {"state": "available", "primary_reason": None, "gates": []},
        }
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO assessments_multitimeframeassessment "
                "(method_id,snapshot_id,eligibility_id,cost_id,capacity_id,evidence_packet_id,"
                "information_cutoff,input_manifest,input_digest,output,output_digest,recorded_at) "
                "VALUES (%s,%s,%s,NULL,NULL,NULL,%s,%s,%s,%s,%s,now())",
                [
                    method.pk,
                    snapshot.pk,
                    eligibility.pk,
                    snapshot.information_cutoff,
                    json.dumps(manifest),
                    identity_digest(manifest),
                    json.dumps(forged_output),
                    identity_digest(forged_output),
                ],
            )
        row, _, _ = assess(snapshot.pk, eligibility.pk)
        self.assertEqual(MultiTimeframeAssessment.objects.count(), 1)

        evaluation_row, _ = calculate_strategy(snapshot.pk, STRATEGY)
        for entry in ("not-a-price", "1.100000"):
            candidate = {
                "schema": "phase6a/eligible-trade-intent-candidate-v2",
                "authority": "caller-escalated",
                "evaluation_identity": evaluation_row.identity,
                "semantic_identity": identity_digest([entry]),
                "entry": entry,
            }
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO assessments_eligibletradeintentcandidate "
                    "(assessment_id,evaluation_id,predecessor_id,semantic_identity,payload,digest,recorded_at) "
                    "VALUES (%s,%s,NULL,%s,%s,%s,now())",
                    [
                        row.pk,
                        evaluation_row.pk,
                        candidate["semantic_identity"],
                        json.dumps(candidate),
                        identity_digest(candidate),
                    ],
                )

    def test_raw_sql_cost_capacity_and_packet_provenance_are_closed(self):
        eligibility = self.empty_eligibility()
        snapshot = self.frozen_snapshot()
        past = snapshot.information_cutoff - timedelta(days=1)
        cost_payload = {
            "schema": "phase6a/cost-evidence-v1",
            "source_identity": "fabricated",
            "source_version": "v1",
            "timestamp_precision": "provider_exact",
            "known_at": past.isoformat(timespec="microseconds"),
            "stale_after": (past + timedelta(hours=1)).isoformat(timespec="microseconds"),
            "components": {
                "spread": "0.000001",
                "commission": "0.000000",
                "slippage_latency": "0.000000",
                "financing": "0.000000",
            },
        }
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO assessments_costevidence "
                "(instrument_id,known_at,stale_after,payload,digest,recorded_at) VALUES (%s,%s,%s,%s,%s,now()-interval '1 year')",
                [
                    self.instrument.pk,
                    past,
                    past + timedelta(hours=1),
                    json.dumps(cost_payload),
                    identity_digest(cost_payload),
                ],
            )
        capacity_payload = {
            "schema": "phase6a/capacity-v1",
            "policy_identity": "fabricated",
            "source_identity": "fabricated",
            "aggregate": "available",
            "currency_legs": [],
            "assessed_at": past.isoformat(timespec="microseconds"),
        }
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO assessments_capacityassessment "
                "(instrument_id,assessed_at,payload,digest,recorded_at) VALUES (%s,%s,%s,%s,now()-interval '1 year')",
                [
                    self.instrument.pk,
                    past,
                    json.dumps(capacity_payload),
                    identity_digest(capacity_payload),
                ],
            )

        other, _ = make_market("EUR_USD", 2)
        later_cutoff = timezone.now()
        self.assertGreater(later_cutoff, snapshot.information_cutoff)
        packets = (
            freeze_packet(self.instrument, cutoff=later_cutoff),
            freeze_packet(other, cutoff=snapshot.information_cutoff),
        )
        legitimate, _, _ = assess(snapshot.pk, eligibility.pk)
        for packet in packets:
            with self.assertRaisesRegex(ValueError, "unrequired_evidence_packet"):
                assess(snapshot.pk, eligibility.pk, evidence_packet_id=packet.pk)
            method = register_method()
            manifest = {
                "schema": "phase6a/input-manifest-v1",
                "method": method.digest,
                "snapshot": {"id": snapshot.pk, "identity": snapshot.idempotency_key},
                "eligibility": _eligibility_reference(eligibility),
                "evaluations": [],
                "cost": None,
                "capacity": None,
                "evidence": packet.digest,
            }
            forged_output = {"schema": "phase6a/assessment-v2", "status": "closed"}
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO assessments_multitimeframeassessment "
                    "(method_id,snapshot_id,eligibility_id,cost_id,capacity_id,evidence_packet_id,"
                    "information_cutoff,input_manifest,input_digest,output,output_digest,recorded_at) "
                    "VALUES (%s,%s,%s,NULL,NULL,%s,%s,%s,%s,%s,%s,now())",
                    [
                        method.pk,
                        snapshot.pk,
                        eligibility.pk,
                        packet.pk,
                        snapshot.information_cutoff,
                        json.dumps(manifest),
                        identity_digest(manifest),
                        json.dumps(forged_output),
                        identity_digest(forged_output),
                    ],
                )

        packet = packets[0]
        forged_manifest = {
            **legitimate.input_manifest,
            "evidence": packet.digest,
        }
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "ALTER TABLE assessments_multitimeframeassessment DISABLE TRIGGER phase6a_validate"
            )
            try:
                cursor.execute(
                    "INSERT INTO assessments_multitimeframeassessment "
                    "(method_id,snapshot_id,eligibility_id,cost_id,capacity_id,evidence_packet_id,"
                    "information_cutoff,input_manifest,input_digest,output,output_digest,recorded_at) "
                    "VALUES (%s,%s,%s,NULL,NULL,%s,%s,%s,%s,%s,%s,now()) RETURNING id",
                    [
                        legitimate.method_id,
                        snapshot.pk,
                        eligibility.pk,
                        packet.pk,
                        snapshot.information_cutoff,
                        json.dumps(forged_manifest),
                        identity_digest(forged_manifest),
                        json.dumps(legitimate.output),
                        identity_digest(legitimate.output),
                    ],
                )
                forged_id = cursor.fetchone()[0]
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            finally:
                cursor.execute(
                    "ALTER TABLE assessments_multitimeframeassessment "
                    "ENABLE TRIGGER phase6a_validate"
                )
        with self.assertRaisesRegex(ValueError, "unrequired_evidence_packet"):
            replay(forged_id)
        self.assertIn(forged_id, {item["id"] for item in audit_integrity(limit=10)["violations"]})

    def test_arbitrary_predecessor_and_missing_pairing_fail_sql_and_audit(self):
        eligibility = self.empty_eligibility()
        assessments = []
        evaluations = []
        for _ in range(3):
            snapshot = self.frozen_snapshot()
            assessments.append(assess(snapshot.pk, eligibility.pk)[0])
            evaluations.append(calculate_strategy(snapshot.pk, STRATEGY)[0])

        candidate_ids = []
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE assessments_eligibletradeintentcandidate "
                "DISABLE TRIGGER phase6a_validate"
            )
            cursor.execute(
                "ALTER TABLE assessments_eligibletradeintentcandidate "
                "DISABLE TRIGGER phase6a_candidate_pairing"
            )
            try:
                for index, (assessment, evaluation_row) in enumerate(
                    zip(assessments, evaluations, strict=True)
                ):
                    payload = {
                        "schema": "historical-forgery-fixture",
                        "strategy": STRATEGY,
                        "direction": 1,
                        "semantic_identity": identity_digest(["candidate", index]),
                    }
                    cursor.execute(
                        "INSERT INTO assessments_eligibletradeintentcandidate "
                        "(assessment_id,evaluation_id,predecessor_id,semantic_identity,payload,digest,recorded_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,now()) RETURNING id",
                        [
                            assessment.pk,
                            evaluation_row.pk,
                            candidate_ids[0] if index == 2 else None,
                            payload["semantic_identity"],
                            json.dumps(payload),
                            identity_digest(payload),
                        ],
                    )
                    candidate_ids.append(cursor.fetchone()[0])
            finally:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(
                    "ALTER TABLE assessments_eligibletradeintentcandidate "
                    "ENABLE TRIGGER phase6a_validate"
                )
                cursor.execute(
                    "ALTER TABLE assessments_eligibletradeintentcandidate "
                    "ENABLE TRIGGER phase6a_candidate_pairing"
                )

        forged_observation = {
            "schema": "phase6a/intent-supersession-v1",
            "predecessor": "wrong",
            "successor": "wrong",
            "observed_at_cutoff": assessments[2].information_cutoff.isoformat(
                timespec="microseconds"
            ),
        }
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO assessments_intentsupersession "
                "(predecessor_id,successor_id,payload,digest,recorded_at) VALUES (%s,%s,%s,%s,now())",
                [
                    candidate_ids[1],
                    candidate_ids[2],
                    json.dumps(forged_observation),
                    identity_digest(forged_observation),
                ],
            )
        self.assertEqual(
            {item["id"] for item in audit_integrity(limit=10)["violations"]},
            {assessment.pk for assessment in assessments},
        )

    def test_future_decision_and_expired_validity_refuse(self):
        with self.assertRaisesRegex(ValueError, "eligibility_chronology"):
            append_reviewed_eligibility(
                self.instrument,
                era="forged",
                entries=[],
                decision_known_at=timezone.now() + timedelta(days=1),
                phase55_decision_sha256="1" * 64,
                phase55_manifest_sha256="2" * 64,
                admission_provenance_sha256="3" * 64,
            )

    def test_method_registration_is_exact_and_idempotent(self):
        first = register_method()
        second = register_method()
        self.assertEqual(first.pk, second.pk)
