"""Idempotent, concurrency-safe persistence of immutable market-state snapshots."""

from datetime import UTC

from django.db import connection, transaction

from market.models import MarketStateSnapshot
from market.state.canonical import identity_digest


class DeterminismViolation(ValueError):
    """A snapshot with the same identity already exists with a different output."""


def snapshot_idempotency_key(
    definition_sha256, instrument_code, information_cutoff, manifest_sha256
):
    """Deterministic identity of a snapshot over exactly its defining inputs."""
    return identity_digest(
        [
            definition_sha256,
            instrument_code,
            information_cutoff.astimezone(UTC).isoformat(timespec="microseconds"),
            manifest_sha256,
        ]
    )


@transaction.atomic
def persist_snapshot(
    instrument,
    definition,
    information_cutoff,
    input_manifest,
    input_manifest_sha256,
    output_payload,
    *,
    evidence_manifest=None,
    data_quality_status="complete",
):
    """Persist (or return the existing) snapshot for this identity.

    A duplicate concurrent computation resolves to exactly one canonical
    snapshot: an advisory transaction lock serializes writers on the identity,
    and a matching row is returned unchanged. If a row with the same identity
    exists but its output hash differs, that is a determinism violation and
    fails closed rather than forking the record.
    """
    key = snapshot_idempotency_key(
        definition.definition_sha256, instrument.code, information_cutoff, input_manifest_sha256
    )
    output_sha256 = identity_digest(output_payload)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"market-state:{key}"]
        )
    existing = MarketStateSnapshot.objects.filter(idempotency_key=key).first()
    if existing is not None:
        if existing.output_sha256 != output_sha256:
            raise DeterminismViolation(
                f"snapshot {key} already exists with a different canonical output"
            )
        return existing, False
    snapshot = MarketStateSnapshot.objects.create(
        instrument=instrument,
        definition=definition,
        information_cutoff=information_cutoff,
        input_manifest=input_manifest,
        input_manifest_sha256=input_manifest_sha256,
        evidence_manifest=evidence_manifest or {},
        output_payload=output_payload,
        output_sha256=output_sha256,
        data_quality_status=data_quality_status,
        idempotency_key=key,
    )
    return snapshot, True
