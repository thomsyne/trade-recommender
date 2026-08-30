import hashlib
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from market.historical_discovery import (
    DISCOVERY_V2_PLAN_SHA256,
    GATE5_APPROVAL_DECISION_SHA256,
    approve_and_register_discovery,
    build_gate5_approval_decision,
)
from market.models import HistoricalDiscoveryPlan
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Approve, register and seal the completed Gate 4 discovery inventory"
        " against the committed Gate 5 approval-decision artifact"
    )

    def add_arguments(self, parser):
        parser.add_argument("--plan-sha256", required=True)
        parser.add_argument("--decision-artifact", required=True)
        parser.add_argument("--approver", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        if options["plan_sha256"] != DISCOVERY_V2_PLAN_SHA256:
            raise CommandError("--plan-sha256 does not match the approved v2 plan")
        try:
            with open(options["decision_artifact"], "rb") as handle:
                artifact_bytes = handle.read()
        except OSError as error:
            raise CommandError(f"approval-decision artifact is unreadable: {error}") from error
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
        try:
            approver = get_user_model().objects.get(username=options["approver"])
        except get_user_model().DoesNotExist as error:
            raise CommandError("approver must be an existing Django user") from error
        if not options["execute"]:
            plan_exists = HistoricalDiscoveryPlan.objects.filter(
                sha256=DISCOVERY_V2_PLAN_SHA256, sealed_at__isnull=True
            ).exists()
            self.stdout.write(
                json.dumps(
                    {
                        "event": "gate5_dry_run",
                        "artifact_sha256": GATE5_APPROVAL_DECISION_SHA256,
                        "plan_sha256": DISCOVERY_V2_PLAN_SHA256,
                        "approver": approver.get_username(),
                        "unsealed_plan_present": plan_exists,
                        "executed": False,
                    },
                    sort_keys=True,
                )
            )
            return
        try:
            registration = approve_and_register_discovery(
                DISCOVERY_V2_PLAN_SHA256, approver.pk, GATE5_APPROVAL_DECISION_SHA256
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
                    "sealed_at": registration.registered_at.isoformat(),
                    "executed": True,
                },
                sort_keys=True,
            )
        )
