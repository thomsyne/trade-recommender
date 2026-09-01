import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from market.historical_acquisition import (
    register_historical_dataset,
    replacement_registration_contract,
)
from market.models import DatasetRegistration, DatasetVersion, HistoricalDatasetPlan
from market.provider_observed_registration import (
    load_committed_registration_authorization,
    verify_registration_readiness,
)
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Verify and immutably register one completed failed-break historical dataset."
        " A provider-observed replacement dataset additionally requires the committed"
        " Gate 7C registration authorization and an explicit --execute."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dataset-id", type=int, required=True)
        parser.add_argument("--plan-sha256", required=True)
        parser.add_argument(
            "--execute",
            action="store_true",
            help=(
                "provider-observed datasets only: perform the registration."
                " Without it the command is a complete read-only readiness check."
                " Legacy datasets ignore this flag and keep their existing behaviour."
            ),
        )

    def emit(self, payload):
        self.stdout.write(json.dumps(payload, sort_keys=True))

    def provider_observed_plan(self, dataset_id, plan_sha256):
        """Resolve the replacement contract without writing anything; a legacy
        dataset resolves to None and keeps the unchanged legacy path."""
        dataset = DatasetVersion.objects.get(pk=dataset_id)
        plan = HistoricalDatasetPlan.objects.get(sha256=plan_sha256)
        chunks = list(
            plan.chunks.filter(dataset_version=dataset)
            .select_related("instrument", "discovery_inventory")
            .order_by("instrument__code", "granularity", "requested_from")
        )
        return dataset, plan, replacement_registration_contract(plan, dataset, chunks)

    def handle(self, *args, **options):
        try:
            dataset, plan, contract = self.provider_observed_plan(
                options["dataset_id"], options["plan_sha256"]
            )
        except (DatasetVersion.DoesNotExist, HistoricalDatasetPlan.DoesNotExist) as error:
            raise CommandError(str(error)) from error
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error

        if contract is None:
            return self.handle_legacy(options)
        return self.handle_provider_observed(dataset, plan, options)

    def handle_legacy(self, options):
        """The legacy path is unchanged: it registers on invocation and emits
        exactly the payload it always has."""
        try:
            registration = register_historical_dataset(
                options["dataset_id"], options["plan_sha256"]
            )
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error
        self.emit(
            {
                "dataset_registration_id": registration.pk,
                "report_sha256": registration.report_sha256,
                "row_counts": registration.row_counts,
            }
        )

    def handle_provider_observed(self, dataset, plan, options):
        try:
            authorization = load_committed_registration_authorization()
        except (ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        try:
            readiness = verify_registration_readiness(dataset, plan, authorization=authorization)
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error

        summary = {
            "mode": "provider-observed",
            "ready": True,
            "authorization_sha256": authorization["authorization_sha256"],
            "registration_identity": authorization["registration_identity"],
            "data_contract_sha256": readiness["observed"]["data_contract_sha256"],
            "replacement_plan_sha256": readiness["observed"]["replacement_plan_sha256"],
            "replacement_dataset_manifest_sha256": readiness["observed"][
                "replacement_dataset_manifest_sha256"
            ],
            "global_semantic_inventory_sha256": readiness["observed"][
                "global_semantic_inventory_sha256"
            ],
            "chunk_count": readiness["observed"]["chunk_count"],
            "successful_attempt_count": readiness["observed"]["successful_attempt_count"],
            "ingestion_manifest_count": readiness["observed"]["ingestion_manifest_count"],
            "candle_count": readiness["observed"]["candle_count"],
            "granularity_candle_totals": readiness["observed"]["granularity_candle_totals"],
            "logical_chunk_set_hash": readiness["observed"]["logical_chunk_set_hash"],
            "successful_attempt_set_hash": readiness["observed"]["successful_attempt_set_hash"],
            "ingestion_manifest_set_hash": readiness["observed"]["ingestion_manifest_set_hash"],
            "candle_key_hash": readiness["observed"]["candle_key_hash"],
            "candle_payload_hash": readiness["observed"]["candle_payload_hash"],
        }
        if not options["execute"]:
            self.emit(
                {
                    **summary,
                    "checkpoint": "dry-run",
                    "read_only": True,
                    "registrations_created": 0,
                }
            )
            return
        try:
            with transaction.atomic():
                # Registration is deliberately idempotent, so whether this
                # invocation created the row can only be decided under the same
                # DatasetVersion lock the service itself takes: an unlocked
                # pre-call check would let two concurrent processes both observe
                # zero rows. Taking that lock here first means the existence
                # check below sees exactly the state the service will act on,
                # and a concurrent invocation blocks until this one commits.
                DatasetVersion.objects.select_for_update().get(pk=dataset.pk)
                already_registered = DatasetRegistration.objects.filter(
                    dataset_version=dataset
                ).exists()
                registration = register_historical_dataset(dataset.pk, plan.sha256)
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error
        except DatabaseError as error:
            raise CommandError(
                f"registration rejected before commit: {str(error).strip().splitlines()[0]}"
            ) from error
        self.emit(
            {
                **summary,
                "checkpoint": "already-registered" if already_registered else "registered",
                "read_only": False,
                "registrations_created": 0 if already_registered else 1,
                "report_sha256": registration.report_sha256,
                "configuration_sha256": registration.configuration_sha256,
                "row_counts": registration.row_counts,
            }
        )
