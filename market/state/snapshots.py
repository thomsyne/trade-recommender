"""Idempotent, concurrency-safe persistence of immutable market-state snapshots."""

from datetime import UTC

from django.db import connection, transaction
from django.utils import timezone

from market.models import MarketStateSnapshot
from market.state.canonical import identity_digest


class DeterminismViolation(ValueError):
    """A snapshot with the same identity already exists with a different output."""


def snapshot_idempotency_key(
    definition_sha256,
    instrument_code,
    information_cutoff,
    scope,
    manifest_sha256,
    evidence_sha256,
):
    """Deterministic identity of a snapshot over exactly its defining inputs:
    the definition, instrument, cutoff, the requested granularity *scope*, and
    the hashes of every consumed candle (manifest) and macro/event vintage
    (evidence). Binding the scope means an empty M15 request and an empty H4
    request at the same cutoff have distinct identities; binding the evidence
    means a macro/event vintage change yields a new snapshot rather than a
    determinism collision."""
    return identity_digest(
        [
            definition_sha256,
            instrument_code,
            information_cutoff.astimezone(UTC).isoformat(timespec="microseconds"),
            sorted(scope),
            manifest_sha256,
            evidence_sha256,
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
    scope,
    evidence_manifest,
    evidence_sha256,
    data_quality_status="complete",
):
    """Persist (or return the existing) snapshot for this identity.

    A duplicate concurrent computation resolves to exactly one canonical
    snapshot: an advisory transaction lock serializes writers on the identity,
    and a matching row is returned unchanged. If a row with the same identity
    exists but its output hash differs, that is a determinism violation and
    fails closed rather than forking the record.
    """
    if not timezone.is_aware(information_cutoff):
        raise ValueError("naive_information_cutoff")
    if input_manifest_sha256 != identity_digest(
        input_manifest
    ) or evidence_sha256 != identity_digest(evidence_manifest):
        raise ValueError("input_identity_mismatch")
    key = snapshot_idempotency_key(
        definition.definition_sha256,
        instrument.code,
        information_cutoff,
        scope,
        input_manifest_sha256,
        evidence_sha256,
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
    snapshot = MarketStateSnapshot(
        instrument=instrument,
        definition=definition,
        information_cutoff=information_cutoff,
        input_manifest=input_manifest,
        input_manifest_sha256=input_manifest_sha256,
        evidence_manifest=evidence_manifest,
        output_payload=output_payload,
        output_sha256=output_sha256,
        data_quality_status=data_quality_status,
        idempotency_key=key,
    )
    from market.state.integrity import verify_snapshots

    if verify_snapshots([snapshot])["violation_count"]:
        raise ValueError("invalid_snapshot_semantics")
    snapshot.save()
    return snapshot, True
