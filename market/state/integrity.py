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
``observed_at >= interval_end``. Price features are replayed from the exact cited
candle revisions: a matching output hash alone is not evidence of valid semantics.
Research lineage hashes and availability are checked, and classifications are
reconstructed from cited records. A separate bounded current-ledger build checks
that eligible evidence was not omitted from the claimed input set. Operational
availability/freshness/coverage are a separate axis. ``verify_snapshots``
returns a report whose ``violation_count`` a caller (the CLI) turns into a
nonzero exit.
"""

from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from market.models import CandleObservation
from market.quality import LIVE_GRANULARITIES
from market.services import live_candle_completion
from market.state.canonical import NonCanonicalValue, identity_digest
from market.state.snapshots import snapshot_idempotency_key
from market.state.terminology import terminology_violations

MAX_VIOLATIONS = 500
MAX_SNAPSHOTS = 100
MAX_MANIFEST_ENTRIES = 5000
REQUIRED_PAYLOAD_KEYS = frozenset(
    {
        "schema",
        "definition",
        "instrument",
        "information_cutoff",
        "requested_granularities",
        "granularities",
        "prior_extremes",
        "monthly_context",
        "opening_range",
        "event_state",
        "macro_regime",
    }
)


def verify_snapshots(snapshots):
    violations = []

    def flag(snapshot_id, code, ref=None):
        if len(violations) < MAX_VIOLATIONS:
            entry = {"snapshot_id": snapshot_id, "code": code}
            violations.append(entry)

    checked = 0
    batch = list(
        snapshots.select_related("definition", "instrument").order_by("pk")[: MAX_SNAPSHOTS + 1]
        if hasattr(snapshots, "select_related")
        else snapshots[: MAX_SNAPSHOTS + 1]
    )
    has_more = len(batch) > MAX_SNAPSHOTS
    for snapshot in batch[:MAX_SNAPSHOTS]:
        checked += 1
        definition = snapshot.definition
        if not isinstance(snapshot.information_cutoff, datetime) or not timezone.is_aware(
            snapshot.information_cutoff
        ):
            flag(snapshot.pk, "malformed_information_cutoff")
            continue
        try:
            for value in (
                definition.definition,
                snapshot.output_payload,
                snapshot.input_manifest,
                snapshot.evidence_manifest,
            ):
                identity_digest(value)
        except (NonCanonicalValue, ValueError, TypeError, RecursionError):
            flag(snapshot.pk, "noncanonical_json")
            continue
        if identity_digest(definition.definition) != definition.definition_sha256:
            flag(snapshot.pk, "definition_hash_mismatch", definition.pk)
        if identity_digest(snapshot.output_payload) != snapshot.output_sha256:
            flag(snapshot.pk, "output_hash_mismatch")
        if identity_digest(snapshot.input_manifest) != snapshot.input_manifest_sha256:
            flag(snapshot.pk, "input_manifest_hash_mismatch")
        payload = snapshot.output_payload
        scope = payload.get("requested_granularities", []) if isinstance(payload, dict) else []
        if not isinstance(scope, list) or not all(isinstance(g, str) for g in scope):
            flag(snapshot.pk, "malformed_payload_schema")
            scope = []
        expected_key = snapshot_idempotency_key(
            definition.definition_sha256,
            snapshot.instrument.code,
            snapshot.information_cutoff,
            scope if isinstance(scope, list) else [],
            snapshot.input_manifest_sha256,
            identity_digest(snapshot.evidence_manifest),
        )
        if expected_key != snapshot.idempotency_key:
            flag(snapshot.pk, "idempotency_key_mismatch")
        _verify_payload(snapshot, definition, flag)
        rows = _verify_manifest(snapshot, flag)
        research = _verify_research(snapshot, flag)
        if isinstance(payload, dict) and rows is not None and research is not None:
            _verify_replay(snapshot, rows, scope, research, flag)

    return {
        "axis": "semantic_integrity",
        "checked": checked,
        "has_more": has_more,
        "next_after_id": batch[MAX_SNAPSHOTS - 1].pk if has_more else None,
        "violation_count": len(violations),
        "violations": violations,
    }


def _verify_payload(snapshot, definition, flag):
    from django.core.exceptions import ValidationError

    try:
        snapshot.instrument.clean()
    except ValidationError:
        flag(snapshot.pk, "instrument_currency_contradiction")
    payload = snapshot.output_payload
    if not isinstance(payload, dict):
        flag(snapshot.pk, "malformed_payload_schema")
        return
    if REQUIRED_PAYLOAD_KEYS != set(payload):
        flag(snapshot.pk, "malformed_payload_schema")
    if payload.get("definition") != [definition.key, definition.version]:
        flag(snapshot.pk, "payload_definition_mismatch")
    if payload.get("instrument") != snapshot.instrument.code:
        flag(snapshot.pk, "payload_instrument_mismatch")
    if payload.get("schema") != "market-state/descriptor-v0":
        flag(snapshot.pk, "malformed_payload_schema")
    try:
        cutoff = datetime.fromisoformat(payload["information_cutoff"])
        if not timezone.is_aware(cutoff) or cutoff != snapshot.information_cutoff:
            flag(snapshot.pk, "payload_cutoff_mismatch")
    except (KeyError, TypeError, ValueError):
        flag(snapshot.pk, "payload_cutoff_mismatch")
    granularities = payload.get("granularities")
    scope = payload.get("requested_granularities")
    if (
        not isinstance(granularities, dict)
        or not granularities
        or not isinstance(scope, list)
        or not all(isinstance(g, str) for g in scope)
        or scope != sorted(set(scope))
        or set(scope) != set(granularities)
    ):
        flag(snapshot.pk, "malformed_payload_schema")
    if isinstance(granularities, dict):
        for granularity in granularities:
            if granularity not in LIVE_GRANULARITIES:
                flag(snapshot.pk, "unsupported_granularity", granularity)
    for code in terminology_violations(payload):
        flag(snapshot.pk, code)
    opening = payload.get("opening_range")
    if isinstance(opening, dict):
        for block in opening.values():
            if not isinstance(block, dict) or block.get("state") != "available":
                continue
            try:
                available = datetime.fromisoformat(block["available_at"])
                breakout = datetime.fromisoformat(
                    block.get("breakout_available_at", block["available_at"])
                )
                times = [
                    datetime.fromisoformat(block[field])
                    for field in ("available_at", "breakout_available_at", "failed_at", "retest_at")
                    if field in block
                ]
                if any(not timezone.is_aware(at) for at in times):
                    raise ValueError("naive ORB availability")
                if any(at > snapshot.information_cutoff for at in times):
                    flag(snapshot.pk, "orb_availability_chronology")
                if breakout < available:
                    flag(snapshot.pk, "orb_availability_chronology")
                for field in ("failed_at", "retest_at"):
                    if field in block and datetime.fromisoformat(block[field]) < max(
                        available, breakout
                    ):
                        flag(snapshot.pk, "orb_availability_chronology")
            except (KeyError, ValueError, TypeError):
                flag(snapshot.pk, "malformed_orb_chronology")


def _verify_manifest(snapshot, flag):
    if (
        not isinstance(snapshot.input_manifest, list)
        or len(snapshot.input_manifest) > MAX_MANIFEST_ENTRIES
    ):
        flag(snapshot.pk, "malformed_manifest")
        return
    rows = {g: [] for g in LIVE_GRANULARITIES}
    identities = []
    for entry in snapshot.input_manifest:
        if not isinstance(entry, dict):
            flag(snapshot.pk, "malformed_manifest_entry")
            continue
        try:
            start = datetime.fromisoformat(entry["timestamp"])
            granularity = entry["granularity"]
            revision = entry["revision"]
            content_sha256 = entry["content_sha256"]
        except (KeyError, TypeError, ValueError):
            flag(snapshot.pk, "malformed_manifest_entry")
            continue
        if not isinstance(start, datetime) or not timezone.is_aware(start):
            flag(snapshot.pk, "malformed_manifest_entry")
            continue
        if (
            type(revision) is not int
            or revision < 1
            or revision > 2147483647
            or not isinstance(content_sha256, str)
        ):
            flag(snapshot.pk, "malformed_manifest_entry")
            continue
        if not isinstance(granularity, str) or granularity not in LIVE_GRANULARITIES:
            flag(snapshot.pk, "unsupported_granularity", granularity)
            continue
        try:
            if live_candle_completion(start, granularity) > snapshot.information_cutoff:
                flag(snapshot.pk, "input_after_cutoff")
        except (ValueError, OverflowError):
            flag(snapshot.pk, "malformed_manifest_entry")
            continue
        identities.append((granularity, start, revision, content_sha256))
    if identities != sorted(set(identities)):
        flag(snapshot.pk, "noncanonical_manifest_order")
    # Exact indexed identities, with a bounded predicate size. A forged manifest
    # cannot force loading every historical revision of an instrument.
    for offset in range(0, len(identities), 100):
        batch = identities[offset : offset + 100]
        predicate = Q(pk__in=[])
        for granularity, start, revision, _ in batch:
            predicate |= Q(granularity=granularity, timestamp=start, revision=revision)
        found = {
            (r.granularity, r.timestamp, r.revision): r
            for r in CandleObservation.objects.filter(predicate, instrument=snapshot.instrument)
        }
        for granularity, start, revision, content_sha256 in batch:
            observation = found.get((granularity, start, revision))
            if observation is None:
                flag(snapshot.pk, "missing_candle_identity")
                continue
            if observation.content_sha256 != content_sha256:
                flag(snapshot.pk, "revised_content_substituted")
            if observation.observed_at > snapshot.information_cutoff:
                flag(snapshot.pk, "input_available_after_cutoff")
            if not observation.complete:
                flag(snapshot.pk, "incomplete_candle")
            rows[granularity].append(observation)
    return {g: tuple(sorted(items, key=lambda r: r.timestamp)) for g, items in rows.items()}


def _verify_research(snapshot, flag):
    """Check exact research content and availability without exposing provider data."""
    from django.apps import apps

    from market.state.context import record_identity

    evidence = snapshot.evidence_manifest
    if not isinstance(evidence, dict) or set(evidence) != {"events", "macro"}:
        flag(snapshot.pk, "malformed_evidence_manifest")
        return
    if not isinstance(evidence["events"], list) or not isinstance(evidence["macro"], dict):
        flag(snapshot.pk, "malformed_evidence_manifest")
        return
    groups = evidence["events"] + list(evidence["macro"].values())
    if len(groups) > MAX_MANIFEST_ENTRIES:
        flag(snapshot.pk, "malformed_evidence_manifest")
        return
    models = {
        "research.economicevent",
        "research.macroobservation",
        "research.rawretrieval",
        "research.sourcepolicy",
        "market.sourceregistry",
        "research.macroseries",
    }
    entries = []
    for group in groups:
        if not isinstance(group, list) or len(group) > 20:
            flag(snapshot.pk, "malformed_evidence_manifest")
            return
        entries.extend(group)
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"model", "id", "content_sha256"}
            or not isinstance(entry["model"], str)
            or entry["model"] not in models
            or type(entry["id"]) is not int
            or not 0 < entry["id"] <= 9223372036854775807
        ):
            flag(snapshot.pk, "malformed_evidence_manifest")
            return
    research = {"events": [], "rates": []}
    for model in sorted({entry["model"] for entry in entries}):
        required = [entry for entry in entries if entry["model"] == model]
        queryset = apps.get_model(model).objects.all()
        if model in {"research.economicevent", "research.macroobservation"}:
            queryset = queryset.select_related(
                "retrieval__source_policy__source", "series__source_policy__source"
            )
        records = queryset.in_bulk({entry["id"] for entry in required})
        if model == "research.economicevent":
            research["events"] = sorted(
                records.values(),
                key=lambda e: (e.provider_event_key, e.first_observed_at, e.payload_fingerprint),
            )
        elif model == "research.macroobservation":
            research["rates"] = sorted(
                records.values(),
                key=lambda r: (r.series.code, r.observation_period, r.revision_sequence),
            )
        for entry in required:
            record = records.get(entry["id"])
            if record is None or record_identity(record) != entry:
                flag(snapshot.pk, "research_lineage_mismatch")
                continue
            for field in ("first_observed_at", "available_at", "vintage_at", "fetched_at"):
                value = getattr(record, field, None)
                if value is not None and value > snapshot.information_cutoff:
                    flag(snapshot.pk, "research_available_after_cutoff")
    return research


def _verify_replay(snapshot, rows, scope, research, flag):
    """Recompute price and research semantics from exact cited evidence."""
    from market.state.compute import build_market_state
    from market.state.definitions import DefinitionError

    try:
        payload = snapshot.output_payload
        expected = build_market_state(
            snapshot.instrument,
            snapshot.definition,
            snapshot.information_cutoff,
            scope,
            frozen_inputs=(rows, research),
        )
        if expected[0] != payload:
            flag(snapshot.pk, "feature_semantics_mismatch")
        if expected[2] != snapshot.input_manifest:
            flag(snapshot.pk, "input_manifest_mismatch")
        if expected[4] != snapshot.evidence_manifest:
            flag(snapshot.pk, "evidence_manifest_mismatch")
        # Replay alone cannot detect a self-consistent forgery that omits inputs
        # and consequently reports unavailable features. Check completeness
        # against the same bounded selection contract, not the claimed manifest.
        selected = build_market_state(
            snapshot.instrument,
            snapshot.definition,
            snapshot.information_cutoff,
            scope,
        )
        if selected[2] != snapshot.input_manifest:
            flag(snapshot.pk, "eligible_candle_set_mismatch")
        if selected[4] != snapshot.evidence_manifest:
            flag(snapshot.pk, "eligible_research_set_mismatch")
    except DefinitionError:
        flag(snapshot.pk, "unsupported_definition")
    except (KeyError, TypeError, ValueError, OverflowError, ArithmeticError, AttributeError):
        flag(snapshot.pk, "malformed_feature_payload")
