import json
import subprocess
from pathlib import Path

from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from assessments.contracts import (
    EMPTY_DECISION_SHA256,
    EMPTY_ELIGIBILITY_ERA,
    EMPTY_MANIFEST_SHA256,
    EMPTY_PROVENANCE_SHA256,
    METHOD_V1_DIGEST,
    historical_method_payload,
)
from assessments.engine import build_assessment
from assessments.legacy import build_v1_empty_assessment
from assessments.models import AssessmentMethod, EligibilitySnapshot, MultiTimeframeAssessment
from assessments.services import (
    _eligibility_envelope,
    _eligibility_reference,
    append_reviewed_eligibility,
    assess,
    audit_integrity,
    register_method,
    replay,
)
from market.models import Instrument
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.persistence import load_snapshot
from market.tests.test_live_observations import make_market


def frozen_v1_output(snapshot, eligibility_digest):
    root = Path(__file__).resolve().parents[2]
    source = subprocess.run(
        [
            "git",
            "show",
            "28fb56a0b695328fa46357d0519ea9a46c059046:assessments/engine.py",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.replace(
        "from .contracts import METHOD_DIGEST, REASONS, ROLES",
        "from assessments.contracts import METHOD_V1_DIGEST, REASONS, ROLES\n"
        "METHOD_DIGEST = METHOD_V1_DIGEST",
    )
    namespace = {"__name__": "phase6a_frozen_v1_engine"}
    exec(compile(source, "phase6a-frozen-v1-engine.py", "exec"), namespace)
    output, candidate = namespace["build_assessment"](
        method_digest=METHOD_V1_DIGEST,
        snapshot=snapshot,
        eligibility={"identity": eligibility_digest, "entries": []},
        evaluations=[],
    )
    if candidate is not None:
        raise AssertionError("canonical empty v1 unexpectedly produced a candidate")
    return output


class MigrationTests(TransactionTestCase):
    def test_empty_roundtrip_and_populated_reversal_refusal(self):
        head = [("assessments", "0004_phase6a_closure_guards")]
        predecessor = [("assessments", "0002_phase6a_guards")]
        old = [("assessments", None)]
        instrument, _ = make_market()
        MigrationExecutor(connection).migrate(old)
        self.assertTrue(Instrument.objects.filter(pk=instrument.pk).exists())
        MigrationExecutor(connection).migrate(predecessor)
        eligibility = append_reviewed_eligibility(
            instrument,
            era=EMPTY_ELIGIBILITY_ERA,
            entries=[],
            decision_known_at=timezone.now(),
            phase55_decision_sha256=EMPTY_DECISION_SHA256,
            phase55_manifest_sha256=EMPTY_MANIFEST_SHA256,
            admission_provenance_sha256=EMPTY_PROVENANCE_SHA256,
        )
        MigrationExecutor(connection).migrate(head)
        self.assertTrue(Instrument.objects.filter(pk=instrument.pk).exists())
        self.assertTrue(EligibilitySnapshot.objects.filter(pk=eligibility.pk).exists())
        register_method()
        with self.assertRaisesMessage(RuntimeError, "phase6a_populated_closure_reverse_refused"):
            MigrationExecutor(connection).migrate(old)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM assessments_assessmentmethod")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_empty_successor_reverse_restores_v1_guards(self):
        head = [("assessments", "0004_phase6a_closure_guards")]
        predecessor = [("assessments", "0003_phase6a_correction_guards")]
        MigrationExecutor(connection).migrate(predecessor)
        MigrationExecutor(connection).migrate(head)
        MigrationExecutor(connection).migrate(predecessor)
        with self.assertRaises(DatabaseError):
            register_method()
        MigrationExecutor(connection).migrate(head)
        self.assertEqual(register_method().version, "1.2.0")

    def test_populated_v1_replays_after_forward_migration_and_new_v1_is_refused(self):
        v1 = [("assessments", "0002_phase6a_guards")]
        head = [("assessments", "0004_phase6a_closure_guards")]
        MigrationExecutor(connection).migrate(v1)
        instrument, _ = make_market()
        eligibility = append_reviewed_eligibility(
            instrument,
            era=EMPTY_ELIGIBILITY_ERA,
            entries=[],
            decision_known_at=timezone.now(),
            phase55_decision_sha256=EMPTY_DECISION_SHA256,
            phase55_manifest_sha256=EMPTY_MANIFEST_SHA256,
            admission_provenance_sha256=EMPTY_PROVENANCE_SHA256,
        )
        snapshot = compute_market_state(
            instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]
        method_payload = historical_method_payload(METHOD_V1_DIGEST)
        method = AssessmentMethod.objects.create(
            key="deterministic-multi-timeframe-assessment",
            version="1.0.0",
            payload=method_payload,
            digest=METHOD_V1_DIGEST,
        )
        output = frozen_v1_output(snapshot.output_payload, eligibility.digest)
        self.assertEqual(build_v1_empty_assessment(snapshot.output_payload), output)
        manifest = {
            "schema": "phase6a/input-manifest-v1",
            "method": METHOD_V1_DIGEST,
            "snapshot": {"id": snapshot.pk, "identity": snapshot.idempotency_key},
            "eligibility": eligibility.digest,
            "evaluations": [],
            "cost": None,
            "capacity": None,
            "evidence": None,
        }
        row = MultiTimeframeAssessment.objects.create(
            method=method,
            snapshot=snapshot,
            eligibility=eligibility,
            information_cutoff=snapshot.information_cutoff,
            input_manifest=manifest,
            input_digest=identity_digest(manifest),
            output=output,
            output_digest=identity_digest(output),
            recorded_at=timezone.now(),
        )
        frozen_output = json.dumps(row.output, sort_keys=True, separators=(",", ":"))

        MigrationExecutor(connection).migrate(head)
        replayed = replay(row.pk)
        self.assertEqual(
            json.dumps(replayed.output, sort_keys=True, separators=(",", ":")), frozen_output
        )
        self.assertEqual(audit_integrity()["violations"], [])

        later = compute_market_state(
            instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]
        later_output = build_v1_empty_assessment(later.output_payload)
        later_manifest = {
            **manifest,
            "snapshot": {"id": later.pk, "identity": later.idempotency_key},
        }
        with self.assertRaises(DatabaseError):
            MultiTimeframeAssessment.objects.create(
                method=method,
                snapshot=later,
                eligibility=eligibility,
                information_cutoff=later.information_cutoff,
                input_manifest=later_manifest,
                input_digest=identity_digest(later_manifest),
                output=later_output,
                output_digest=identity_digest(later_output),
                recorded_at=timezone.now(),
            )

    def test_populated_v1_noncanonical_empty_cannot_feed_latest_assessment(self):
        v1 = [("assessments", "0002_phase6a_guards")]
        head = [("assessments", "0004_phase6a_closure_guards")]
        MigrationExecutor(connection).migrate(v1)
        instrument, _ = make_market()
        bad_payload = {
            "schema": "phase6a/eligibility-v1",
            "instrument": instrument.code,
            "era": "legacy-caller-era",
            "phase55_decision_sha256": "1" * 64,
            "phase55_manifest_sha256": "2" * 64,
            "admission_provenance_sha256": "3" * 64,
            "entries": [],
        }
        bad = EligibilitySnapshot.objects.create(
            instrument=instrument,
            valid_from=timezone.now(),
            valid_until=None,
            decision_known_at=timezone.now(),
            payload=bad_payload,
            digest=identity_digest(bad_payload),
            recorded_at=timezone.now(),
        )
        bad.refresh_from_db()
        snapshot = compute_market_state(
            instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]
        MigrationExecutor(connection).migrate(head)
        method = register_method()
        inputs = load_snapshot(snapshot.pk)
        with self.assertRaisesRegex(ValueError, "canonical_empty_eligibility_required"):
            _eligibility_envelope(bad, inputs.cutoff, snapshot.instrument_id)
        canonical = {
            "identity": bad.digest,
            "entries": [],
        }
        output, candidate = build_assessment(
            method_digest=method.digest,
            snapshot=inputs.payload,
            eligibility=canonical,
            evaluations=[],
        )
        self.assertIsNone(candidate)
        manifest = {
            "schema": "phase6a/input-manifest-v1",
            "method": method.digest,
            "snapshot": {"id": snapshot.pk, "identity": snapshot.idempotency_key},
            "eligibility": _eligibility_reference(bad),
            "evaluations": [],
            "cost": None,
            "capacity": None,
            "evidence": None,
        }
        with self.assertRaises(DatabaseError):
            MultiTimeframeAssessment.objects.create(
                method=method,
                snapshot=snapshot,
                eligibility=bad,
                information_cutoff=snapshot.information_cutoff,
                input_manifest=manifest,
                input_digest=identity_digest(manifest),
                output=output,
                output_digest=identity_digest(output),
                recorded_at=timezone.now(),
            )

        good = append_reviewed_eligibility(
            instrument,
            era=EMPTY_ELIGIBILITY_ERA,
            entries=[],
            decision_known_at=timezone.now(),
            phase55_decision_sha256=EMPTY_DECISION_SHA256,
            phase55_manifest_sha256=EMPTY_MANIFEST_SHA256,
            admission_provenance_sha256=EMPTY_PROVENANCE_SHA256,
        )
        later = compute_market_state(
            instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]
        row, _, _ = assess(later.pk, good.pk)
        with connection.cursor() as cursor:
            cursor.execute("SELECT phase6a_expected_empty_output(%s)", [later.pk])
            sql_output = cursor.fetchone()[0]
        if isinstance(sql_output, str):
            sql_output = json.loads(sql_output)
        self.assertEqual(sql_output, row.output)
