import json

from django.core.management.base import BaseCommand, CommandError

from market.provider_observed_outcome import (
    ARTIFACT_NAME,
    load_committed_gate8d3_outcome,
    verify_gate8d3_outcome_against_database,
)


class Command(BaseCommand):
    help = (
        "Report the committed Gate 8D3 successor discovery outcome. By default this"
        " verifies the committed bytes against their governed digest, the artifact's"
        " embedded self-hash, and its canonical form, consulting no database. Pass"
        " --verify-reconstruction to additionally regenerate every value from the raw"
        " discovery rows and compare byte-for-byte; that mode reads all 365,055 successor"
        " observations, so it is requested explicitly rather than run silently. Read-only"
        " under either mode: no database write, no provider client, no credential."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--verify-reconstruction",
            action="store_true",
            help="also regenerate the artifact from raw rows and compare byte-for-byte",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="include the 132 per-chunk records instead of the bounded summary",
        )

    def handle(self, *args, **options):
        try:
            if options["verify_reconstruction"]:
                document = verify_gate8d3_outcome_against_database()
                verification = "committed bytes, self-hash, canonical form and live reconstruction"
            else:
                document = load_committed_gate8d3_outcome()
                verification = "committed bytes, self-hash and canonical form"
        except ValueError as error:
            raise CommandError(str(error)) from error
        if options["full"]:
            payload = document
        else:
            payload = {
                "artifact": ARTIFACT_NAME,
                "schema": document["schema"],
                "verified": verification,
                "outcome_sha256": document["outcome_sha256"],
                "successor_discovery_plan_sha256": document["successor_discovery_plan_sha256"],
                "successor_request_manifest_sha256": document["successor_request_manifest_sha256"],
                "successor_global_semantic_inventory_sha256": document[
                    "successor_global_semantic_inventory_sha256"
                ],
                "successor_accepted_operational_evidence_set_sha256": document[
                    "successor_accepted_operational_evidence_set_sha256"
                ],
                "completion": document["completion"],
                "observations": document["observations"],
                "restricted_overlap_sha256": document["restricted_overlap"][
                    "successor_restricted_sha256"
                ],
                "restricted_overlap_identical": document["restricted_overlap"]["identical"],
                "chunk_records": len(document["chunk_records"]),
                "warmup_instruments": len(document["warmup_proof"]),
                "sectioned_snapshot_convention": document["sectioned_snapshot"]["convention"],
                "sectioned_post_gate8d2_sha256": document["sectioned_snapshot"][
                    "sectioned_post_gate8d2_sha256"
                ],
            }
        self.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
