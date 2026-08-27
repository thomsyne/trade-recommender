import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from research.models import StrategyDefinition, StrategyParameterManifest, StrategyVersion

SPEC_SHA256 = "47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd"
MANIFEST_SHA256 = "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882"
DOCUMENT_DIRECTORY = Path("docs/strategy/failed-break/v1")


def _read_verified(path: Path, expected_hash: str) -> bytes:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise CommandError(f"approved artifact hash mismatch: {path}")
    return content


class Command(BaseCommand):
    help = "Register the approved immutable Phase 1 strategy manifest"

    @transaction.atomic
    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR) / DOCUMENT_DIRECTORY
        _read_verified(root / "phase-1-specification.md", SPEC_SHA256)
        manifest_bytes = _read_verified(root / "phase-1-freeze-manifest.json", MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes)
        identities = manifest["identities"]

        definition, _ = StrategyDefinition.objects.get_or_create(
            key="top-down-failed-break-continuation",
            defaults={
                "name": "Top-Down Failed-Break Continuation",
                "description": "Approved Phase 1 deterministic research strategy.",
            },
        )
        strategy, _ = StrategyVersion.objects.get_or_create(
            definition=definition,
            version=manifest["manifest_id"],
            defaults={
                "detector_version": identities["detector"],
                "data_identity": identities["data"],
                "event_identity": identities["event_policy"],
                "execution_identity": identities["primary_execution"],
                "cost_identity": identities["primary_cost"],
                "portfolio_identity": identities["portfolio"],
                "pair_metadata": {"instruments": manifest["instruments"]},
                "timeframe_metadata": manifest["timeframes"],
                "content_hash": MANIFEST_SHA256,
            },
        )
        expected_strategy = {
            "detector_version": identities["detector"],
            "data_identity": identities["data"],
            "event_identity": identities["event_policy"],
            "execution_identity": identities["primary_execution"],
            "cost_identity": identities["primary_cost"],
            "portfolio_identity": identities["portfolio"],
            "pair_metadata": {"instruments": manifest["instruments"]},
            "timeframe_metadata": manifest["timeframes"],
            "content_hash": MANIFEST_SHA256,
        }
        if any(getattr(strategy, field) != value for field, value in expected_strategy.items()):
            raise CommandError("registered strategy version conflicts with approved manifest")
        parameter_manifest, created = StrategyParameterManifest.objects.get_or_create(
            strategy_version=strategy,
            defaults={
                "payload": manifest,
                "sha256": MANIFEST_SHA256,
                "phase1_spec_hash": SPEC_SHA256,
                "phase1_manifest_hash": MANIFEST_SHA256,
            },
        )
        expected = {
            "payload": manifest,
            "sha256": MANIFEST_SHA256,
            "phase1_spec_hash": SPEC_SHA256,
            "phase1_manifest_hash": MANIFEST_SHA256,
        }
        if not created and any(
            getattr(parameter_manifest, field) != value for field, value in expected.items()
        ):
            raise CommandError("registered parameter manifest conflicts with approved artifacts")
        self.stdout.write(self.style.SUCCESS(f"registered {strategy.version}"))
