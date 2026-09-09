"""Deterministic, read-only, bounded semantic-integrity report over snapshots.

Recomputes every hash a market-state snapshot binds (definition, output, input
manifest, idempotency key) and rechecks its causal invariants against the live
ledger, without mutating anything: payload schema and definition agreement,
interval-ended-by-cutoff, unsupported granularity, missing candle identity,
silent revision substitution, and duplicate idempotency keys. Diagnostics are
bounded — stable ids and reason codes only, never raw payloads or unbounded
values.

This covers the core semantic-integrity conditions of design §11 that can be
verified from persisted state. Several conditions the brief enumerates are
structurally precluded rather than separately scanned — e.g. immutability
(UPDATE/DELETE/TRUNCATE triggers), unique idempotency keys, and the DB-enforced
``observed_at >= interval_end`` — and feature-internal predicates (BOS/CHoCH
prerequisites, zone chronology) are covered by determinism: the output hash only
recomputes if the deterministic engine produced it. Operational availability/
freshness/coverage are a separate axis and not mixed in here. ``verify_snapshots``
returns a report whose ``violation_count`` a caller (the CLI) turns into a
nonzero exit.
"""

from datetime import datetime

from django.db.models import Count

from market.models import CandleObservation, MarketStateSnapshot
from market.quality import LIVE_GRANULARITIES
from market.services import live_candle_completion
from market.state.canonical import identity_digest
from market.state.snapshots import snapshot_idempotency_key

MAX_VIOLATIONS = 500
REQUIRED_PAYLOAD_KEYS = frozenset({"schema", "definition", "instrument", "granularities"})


def _parse(ts):
    return datetime.fromisoformat(ts)


def verify_snapshots(snapshots):
    violations = []

    def flag(snapshot_id, code, ref=None):
        if len(violations) < MAX_VIOLATIONS:
            entry = {"snapshot_id": snapshot_id, "code": code}
            if ref is not None:
                entry["ref"] = str(ref)[:64]
            violations.append(entry)

    checked = 0
    for snapshot in snapshots.select_related("definition", "instrument").iterator():
        checked += 1
        definition = snapshot.definition
        if identity_digest(definition.definition) != definition.definition_sha256:
            flag(snapshot.pk, "definition_hash_mismatch", definition.pk)
        if identity_digest(snapshot.output_payload) != snapshot.output_sha256:
            flag(snapshot.pk, "output_hash_mismatch")
        if identity_digest(snapshot.input_manifest) != snapshot.input_manifest_sha256:
            flag(snapshot.pk, "input_manifest_hash_mismatch")
        expected_key = snapshot_idempotency_key(
            definition.definition_sha256,
            snapshot.instrument.code,
            snapshot.information_cutoff,
            snapshot.input_manifest_sha256,
        )
        if expected_key != snapshot.idempotency_key:
            flag(snapshot.pk, "idempotency_key_mismatch")
        payload = snapshot.output_payload
        if not isinstance(payload, dict) or not REQUIRED_PAYLOAD_KEYS <= set(payload):
            flag(snapshot.pk, "malformed_payload_schema")
        elif payload.get("definition") != [definition.key, definition.version]:
            flag(snapshot.pk, "payload_definition_mismatch")
        _verify_manifest(snapshot, flag)

    duplicates = (
        MarketStateSnapshot.objects.values("idempotency_key")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    for duplicate in duplicates:
        flag(None, "duplicate_idempotency_key", duplicate["idempotency_key"])

    return {
        "axis": "semantic_integrity",
        "checked": checked,
        "violation_count": len(violations),
        "violations": violations,
    }


def _verify_manifest(snapshot, flag):
    for entry in snapshot.input_manifest:
        try:
            start = _parse(entry["timestamp"])
            granularity = entry["granularity"]
            revision = entry["revision"]
            content_sha256 = entry["content_sha256"]
        except (KeyError, TypeError, ValueError):
            flag(snapshot.pk, "malformed_manifest_entry")
            continue
        if granularity not in LIVE_GRANULARITIES:
            flag(snapshot.pk, "unsupported_granularity", granularity)
            continue
        if live_candle_completion(start, granularity) > snapshot.information_cutoff:
            flag(snapshot.pk, "input_after_cutoff", content_sha256)
        observation = CandleObservation.objects.filter(
            instrument=snapshot.instrument,
            granularity=granularity,
            timestamp=start,
            revision=revision,
        ).first()
        if observation is None:
            flag(snapshot.pk, "missing_candle_identity", content_sha256)
        elif observation.content_sha256 != content_sha256:
            flag(snapshot.pk, "revised_content_substituted", content_sha256)
