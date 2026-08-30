import hashlib
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from market.historical_discovery import (
    ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
    DISCOVERY_COMPLETION_SUMMARY_SHA256,
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    GATE5_ACCEPTED_INVENTORY_COUNT,
    GATE5_APPROVAL_DECISION_SHA256,
    GATE5_STRUCTURAL_OBSERVATION_COUNT,
    GLOBAL_SEMANTIC_INVENTORY_SHA256,
    _registration_hashes,
    _verify_canary_success_lineage,
    approve_and_register_discovery,
    build_gate5_approval_decision,
)
from market.models import (
    HistoricalDiscoveryPlan,
    HistoricalDiscoverySupersession,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
)
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Approve, register and seal the completed Gate 4 discovery inventory"
        " against the committed Gate 5 approval-decision artifact and the"
        " committed cross-series discovery-completion summary"
    )

    def add_arguments(self, parser):
        parser.add_argument("--plan-sha256", required=True)
        parser.add_argument("--decision-artifact", required=True)
        parser.add_argument("--completion-summary", required=True)
        parser.add_argument("--approver", required=True)
        parser.add_argument("--execute", action="store_true")

    def read_bytes(self, label, path):
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except OSError as error:
            raise CommandError(f"{label} is unreadable: {error}") from error

    def dry_run_report(self, approver):
        """Complete Gate 5 validation in a read-only transaction: every count
        and identity is reconstructed, and PostgreSQL's own validator runs,
        before anything is reported. Nothing is committed."""
        report = {
            "event": "gate5_dry_run",
            "executed": False,
            "plan_sha256": DISCOVERY_V2_PLAN_SHA256,
            "approval_decision_sha256": GATE5_APPROVAL_DECISION_SHA256,
            "cross_series_report_sha256": DISCOVERY_COMPLETION_SUMMARY_SHA256,
            "approver": approver.get_username(),
        }
        with transaction.atomic():
            try:
                plan = HistoricalDiscoveryPlan.objects.get(sha256=DISCOVERY_V2_PLAN_SHA256)
            except HistoricalDiscoveryPlan.DoesNotExist as error:
                raise CommandError("the approved v2 discovery plan is not present") from error
            report["plan_sealed"] = plan.sealed_at is not None
            report["approver_active"] = approver.is_active
            report["approver_has_permission"] = approver.has_perm(
                "market.approve_historical_discovery"
            )
            report["supersession_lineage_count"] = HistoricalDiscoverySupersession.objects.filter(
                replacement_plan=plan, replacement_plan_sha256=plan.sha256
            ).count()
            report["chunk_count"] = plan.chunks.count()
            report["inventory_count"] = HistoricalTimestampInventory.objects.filter(
                chunk__plan=plan
            ).count()
            report["observation_count"] = HistoricalTimestampObservation.objects.filter(
                inventory__chunk__plan=plan
            ).count()
            problems = []
            if report["plan_sealed"]:
                problems.append("plan is already sealed")
            if not report["approver_active"] or not report["approver_has_permission"]:
                problems.append("approver lacks active governed approval permission")
            if report["supersession_lineage_count"] != 1:
                problems.append("supersession lineage does not reconstruct")
            try:
                _verify_canary_success_lineage(
                    plan, DatasetQualityError("gate5 canary lineage does not reconstruct")
                )
                report["canary_lineage"] = "reconstructed"
            except DatasetQualityError as error:
                report["canary_lineage"] = str(error)
                problems.append(str(error))
            try:
                chunk_hash, semantic_hash, operational_hash = _registration_hashes(plan)
                report["ordered_chunk_manifest_sha256"] = chunk_hash
                report["global_semantic_inventory_sha256"] = semantic_hash
                report["accepted_operational_evidence_set_sha256"] = operational_hash
                if chunk_hash != DISCOVERY_V2_MANIFEST_SHA256:
                    problems.append("ordered chunk manifest hash does not match the pin")
                if semantic_hash != GLOBAL_SEMANTIC_INVENTORY_SHA256:
                    problems.append("global semantic inventory hash does not match the pin")
                if operational_hash != ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256:
                    problems.append("operational evidence set hash does not match the pin")
            except DatasetQualityError as error:
                problems.append(str(error))
            if report["chunk_count"] != GATE5_ACCEPTED_INVENTORY_COUNT:
                problems.append("chunk count does not match the pin")
            if report["inventory_count"] != GATE5_ACCEPTED_INVENTORY_COUNT:
                problems.append("inventory count does not match the pin")
            if report["observation_count"] != GATE5_STRUCTURAL_OBSERVATION_COUNT:
                problems.append("observation count does not match the pin")
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT market_validate_gate5_registration(%s)", [plan.pk])
                report["postgresql_gate5_validator"] = "reconstructed"
            except Exception as error:  # noqa: BLE001 - surfaced verbatim in the report
                report["postgresql_gate5_validator"] = str(error).splitlines()[0]
                problems.append(report["postgresql_gate5_validator"])
            transaction.set_rollback(True)
        report["ready"] = not problems
        report["problems"] = problems
        return report

    def handle(self, *args, **options):
        if options["plan_sha256"] != DISCOVERY_V2_PLAN_SHA256:
            raise CommandError("--plan-sha256 does not match the approved v2 plan")
        artifact_bytes = self.read_bytes("approval-decision artifact", options["decision_artifact"])
        expected_bytes = json.dumps(
            build_gate5_approval_decision(), sort_keys=True, separators=(",", ":")
        ).encode()
        if (
            hashlib.sha256(artifact_bytes).hexdigest() != GATE5_APPROVAL_DECISION_SHA256
            or artifact_bytes != expected_bytes
        ):
            raise CommandError(
                "approval-decision artifact does not match the committed gate5 decision"
            )
        summary_bytes = self.read_bytes(
            "discovery-completion summary", options["completion_summary"]
        )
        if hashlib.sha256(summary_bytes).hexdigest() != DISCOVERY_COMPLETION_SUMMARY_SHA256:
            raise CommandError(
                "completion summary does not match the committed cross-series report"
            )
        try:
            approver = get_user_model().objects.get(username=options["approver"])
        except get_user_model().DoesNotExist as error:
            raise CommandError("approver must be an existing Django user") from error
        if not options["execute"]:
            report = self.dry_run_report(approver)
            self.stdout.write(json.dumps(report, sort_keys=True))
            if not report["ready"]:
                raise CommandError("gate5 dry run is not ready: " + "; ".join(report["problems"]))
            return
        try:
            registration = approve_and_register_discovery(
                DISCOVERY_V2_PLAN_SHA256, approver.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        except HistoricalDiscoveryPlan.DoesNotExist as error:
            raise CommandError("the approved v2 discovery plan is not present") from error
        except (DatasetQualityError, PermissionDenied) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "event": "gate5_registered",
                    "approval_sha256": registration.approval.sha256,
                    "registration_report_sha256": registration.report_sha256,
                    "global_semantic_inventory_sha256": (
                        registration.global_semantic_inventory_sha256
                    ),
                    "accepted_operational_evidence_set_sha256": (
                        registration.accepted_operational_evidence_set_sha256
                    ),
                    "cross_series_report_sha256": registration.cross_series_report_sha256,
                    "approval_decision_sha256": (
                        registration.approval.payload["approval_decision_sha256"]
                    ),
                    "sealed_at": registration.registered_at.isoformat(),
                    "executed": True,
                },
                sort_keys=True,
            )
        )
