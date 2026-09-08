import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import connection, transaction
from django.utils import timezone

from market.models import (
    AuditEvent,
    Candle,
    CandleConflict,
    CandleObservation,
    DataQualityIncident,
    IngestionManifest,
    IngestionRun,
    Instrument,
    OandaInstrumentTermsSnapshot,
    TechnicalSnapshot,
    dataset_manifest_sha256,
)
from market.oanda import manifest_hash
from market.quality import (
    expected_candle_timestamps,
    registered_candle_completion,
    validate_candles,
)
from market.technicals import calculate_technicals


class DatasetQualityError(ValueError):
    """Raised when a governed dataset cannot support deterministic analysis."""


@dataclass(frozen=True, slots=True)
class RequiredCandleRange:
    granularity: str
    start: datetime
    end: datetime


def assert_dataset_usable(dataset_version) -> None:
    """Fail closed for any immutable conflict, incident, or unadmitted candle lineage."""
    if dataset_version.manifest_sha256 != dataset_manifest_sha256(dataset_version.manifest):
        raise DatasetQualityError("dataset manifest SHA-256 does not match canonical JSON")
    if dataset_version.conflicts.exists() or dataset_version.incidents.exists():
        raise DatasetQualityError("dataset has unresolved conflict or data-quality incident")
    runs = dataset_version.ingestion_runs.all()
    registration = getattr(dataset_version, "registration", None)
    if registration:
        if runs.filter(historical_attempt__isnull=True).exists():
            raise DatasetQualityError("registered dataset contains an unplanned ingestion")
        if runs.filter(status=IngestionRun.Status.RUNNING).exists():
            raise DatasetQualityError("registered dataset has an unfinished ingestion")
    elif runs.exclude(status=IngestionRun.Status.SUCCEEDED).exists():
        raise DatasetQualityError("dataset has an unsuccessful or unfinished ingestion manifest")
    manifest_runs = runs.filter(status=IngestionRun.Status.SUCCEEDED) if registration else runs
    if manifest_runs.filter(ingestion_manifest__isnull=True).exists():
        raise DatasetQualityError("dataset ingestion run has no governed manifest")
    candles = dataset_version.candles.all()
    if candles.exclude(ingestion_run__status=IngestionRun.Status.SUCCEEDED).exists():
        raise DatasetQualityError("dataset contains candles from an unsuccessful ingestion")
    if candles.exclude(ingestion_run__dataset_version=dataset_version).exists():
        raise DatasetQualityError("dataset candle ingestion lineage does not match")
    if candles.filter(ingestion_run__ingestion_manifest__isnull=True).exists():
        raise DatasetQualityError("dataset candle has no governed ingestion manifest")
    if not candles.exists():
        raise DatasetQualityError("dataset contains no governed candles")


def provider_observed_h1_completion(timestamp):
    """Provider-observed H1 completion: absolute one-hour arithmetic.

    The legacy New-York wall-clock rule maps two distinct provider candles
    onto one completion during the autumn DST fall-back (05:00Z and 06:00Z
    both completing 07:00Z); sealed inventories legitimately contain both
    hours, so v2 H1 completions must stay one-to-one."""
    return timestamp + timedelta(hours=1)


def candle_completion(timestamp, granularity, contract=None):
    """Candle completion under the effective data identity: absolute +1h for
    provider-observed H1; the frozen calendar rule for legacy data and for
    D/W semantics, which are unchanged."""
    if contract is not None and granularity == "H1":
        return provider_observed_h1_completion(timestamp)
    return registered_candle_completion(timestamp, granularity)


def provider_observed_contract(dataset_version):
    """Resolve the explicit provider-observed data contract for a registered
    dataset, or None for legacy datasets. Resolution is strictly relational
    through the registered plan; identity strings and hashes are never used
    to infer v2 on their own. The complete plan/dataset/registration/contract
    relationship must agree; v2 markers with an incomplete or conflicting
    relationship fail closed instead of degrading to legacy behaviour."""
    from market.models import DatasetRegistration, HistoricalDataContract

    registration = getattr(dataset_version, "registration", None)
    if not isinstance(registration, DatasetRegistration):
        # An unregistered dataset carrying explicit v2 markers must fail
        # closed rather than degrade to legacy behaviour.
        sha_marker = getattr(dataset_version, "data_contract_sha256", None)
        manifest = getattr(dataset_version, "manifest", None)
        manifest_markers = (
            (
                manifest.get("historical_data_contract_sha256"),
                manifest.get("global_semantic_inventory_sha256"),
            )
            if isinstance(manifest, dict)
            else (None, None)
        )
        if isinstance(sha_marker, str) or any(
            isinstance(marker, str) for marker in manifest_markers
        ):
            raise DatasetQualityError("provider-observed data-contract lineage does not verify")
        return None
    plan = registration.plan
    contract = plan.data_contract
    if contract is None:
        markers = (
            plan.data_contract_sha256,
            dataset_version.data_contract_sha256,
            registration.data_contract_id,
            registration.global_semantic_inventory_sha256,
        )
        if any(marker is not None for marker in markers):
            raise DatasetQualityError("provider-observed data-contract lineage does not verify")
        return None
    if (
        not isinstance(contract, HistoricalDataContract)
        or plan.data_contract_sha256 != contract.sha256
        or plan.identity != contract.identity
        or dataset_version.data_contract_sha256 != contract.sha256
        or registration.data_contract_id != plan.data_contract_id
        or registration.global_semantic_inventory_sha256
        != contract.global_semantic_inventory_sha256
        or contract.discovery_registration.plan.sealed_at is None
    ):
        raise DatasetQualityError("provider-observed data-contract lineage does not verify")
    return contract


# Sealed inventories are immutable, so full per-series membership is safely
# memoized by content-addressed key (contract sha + instrument code): equal
# keys imply byte-equal sealed membership even across test databases.
_SEALED_MEMBERSHIP_CACHE = {}
_SEALED_MEMBERSHIP_CACHE_LIMIT = 64


def _sealed_series_timestamps(contract, instrument_id, granularity):
    from market.models import HistoricalTimestampObservation, Instrument

    code = Instrument.objects.filter(pk=instrument_id).values_list("code", flat=True).first()
    key = (contract.sha256, code, granularity)
    cached = _SEALED_MEMBERSHIP_CACHE.get(key)
    if cached is None:
        cached = tuple(
            HistoricalTimestampObservation.objects.filter(
                inventory__chunk__plan=contract.discovery_registration.plan,
                inventory__chunk__instrument_id=instrument_id,
                inventory__chunk__granularity=granularity,
            )
            .order_by("timestamp")
            .values_list("timestamp", flat=True)
        )
        if len(_SEALED_MEMBERSHIP_CACHE) >= _SEALED_MEMBERSHIP_CACHE_LIMIT:
            _SEALED_MEMBERSHIP_CACHE.clear()
        _SEALED_MEMBERSHIP_CACHE[key] = cached
    return cached


def sealed_inventory_membership(contract, instrument_id, granularity, start, end):
    """Exact ordered sealed timestamp membership for one closed-open range."""
    import bisect

    series = _sealed_series_timestamps(contract, instrument_id, granularity)
    left = bisect.bisect_left(series, start)
    right = bisect.bisect_left(series, end)
    return series[left:right]


def assert_dataset_window_usable(dataset_version, instrument, required_ranges, as_of) -> None:
    """Prove exact point-in-time coverage for one instrument across ingestion runs."""
    assert_dataset_usable(dataset_version)
    if not timezone.is_aware(as_of):
        raise DatasetQualityError("as_of must be timezone-aware")
    ranges = tuple(required_ranges)
    if not ranges:
        raise DatasetQualityError("at least one required candle range must be declared")
    instrument_id = getattr(instrument, "pk", instrument)
    contract = provider_observed_contract(dataset_version)
    for required in ranges:
        if contract is not None:
            # Provider-observed v2: exact membership comes only from the
            # sealed timestamp inventory, never the theoretical calendar.
            expected = sealed_inventory_membership(
                contract, instrument_id, required.granularity, required.start, required.end
            )
            if not expected:
                raise DatasetQualityError(
                    f"required {required.granularity} range has no sealed"
                    " provider-observed membership"
                )
        else:
            try:
                expected = expected_candle_timestamps(
                    required.start, required.end, required.granularity
                )
            except ValueError as error:
                raise DatasetQualityError(str(error)) from error
        if as_of < required.end:
            raise DatasetQualityError("required candle range is incomplete at as_of")
        rows = list(
            dataset_version.candles.filter(
                instrument_id=instrument_id,
                granularity=required.granularity,
                timestamp__gte=required.start,
                timestamp__lt=required.end,
            )
            .order_by("timestamp")
            .values(
                "timestamp",
                "complete",
                "ingestion_run__instrument_id",
                "ingestion_run__granularity",
                "ingestion_run__requested_from",
                "ingestion_run__requested_to",
                "ingestion_run__status",
                "ingestion_run__dataset_version_id",
                "ingestion_run__ingestion_manifest__dataset_version_id",
            )
        )
        if tuple(row["timestamp"] for row in rows) != expected:
            raise DatasetQualityError(
                f"dataset does not completely cover {required.granularity} range"
            )
        for row in rows:
            completion = candle_completion(row["timestamp"], required.granularity, contract)
            if (
                not row["complete"]
                or row["ingestion_run__instrument_id"] != instrument_id
                or row["ingestion_run__granularity"] != required.granularity
                or row["ingestion_run__requested_from"] > row["timestamp"]
                or row["ingestion_run__requested_to"] < completion
                or row["ingestion_run__status"] != IngestionRun.Status.SUCCEEDED
                or row["ingestion_run__dataset_version_id"] != dataset_version.pk
                or row["ingestion_run__ingestion_manifest__dataset_version_id"]
                != dataset_version.pk
            ):
                raise DatasetQualityError("required candle has invalid ingestion lineage")


@transaction.atomic
def store_ingestion(
    source,
    instrument,
    granularity,
    start,
    end,
    candle_data,
    manifest,
    dataset_version=None,
    ingestion_run=None,
    provider_observed=False,
):
    digest = manifest_hash(manifest)
    if ingestion_run is None:
        run, created = IngestionRun.objects.get_or_create(
            request_manifest_hash=digest,
            dataset_version=dataset_version,
            defaults={
                "source": source,
                "instrument": instrument,
                "granularity": granularity,
                "requested_from": start,
                "requested_to": end,
                "parameters": {key: value for key, value in manifest.items() if key != "requests"},
            },
        )
        if not created:
            return run
    else:
        run = ingestion_run
        if (
            run.status != IngestionRun.Status.RUNNING
            or run.source_id != source.pk
            or run.instrument_id != instrument.pk
            or run.dataset_version_id != getattr(dataset_version, "pk", None)
            or run.granularity != granularity
            or run.requested_from != start
            or run.requested_to != end
        ):
            raise DatasetQualityError("preallocated ingestion run does not match request lineage")
    ingestion_manifest = None
    if dataset_version:
        ingestion_manifest = IngestionManifest.objects.create(
            ingestion_run=run,
            dataset_version=dataset_version,
            payload=manifest,
            sha256=digest,
        )
    issues = validate_candles(
        candle_data,
        granularity,
        require_registered_alignment=dataset_version is not None and not provider_observed,
        enforce_succession=not provider_observed,
    )
    if issues:
        run.status = IngestionRun.Status.FAILED
        run.fetched_count = len(candle_data)
        run.rejected_count = len(candle_data)
        run.failure_reason = "; ".join(f"{issue.code}@{issue.index}" for issue in issues[:20])
        run.finished_at = timezone.now()
        run.save()
        if dataset_version:
            details = {"issues": [issue.__dict__ for issue in issues[:20]]}
            DataQualityIncident.objects.create(
                dataset_version=dataset_version,
                ingestion_run=run,
                code="candle_validation_failed",
                details=details,
                evidence_sha256=_json_hash(details),
            )
        AuditEvent.objects.create(
            event_type="market.ingestion_rejected",
            actor="market.services.store_ingestion",
            subject_type="IngestionRun",
            subject_id=str(run.pk),
            payload={"issues": [issue.__dict__ for issue in issues[:20]]},
        )
        return run

    if dataset_version:
        existing_by_key = {
            row.timestamp: row
            for row in Candle.objects.select_for_update().filter(
                dataset_version=dataset_version,
                instrument=instrument,
                granularity=granularity,
                timestamp__in=[item.timestamp for item in candle_data],
            )
        }
        conflicts = []
        for item in candle_data:
            prior = existing_by_key.get(item.timestamp)
            incoming_payload = _candle_payload(item)
            if prior and _candle_payload(prior) != incoming_payload:
                existing_payload = _candle_payload(prior)
                conflicts.append(
                    CandleConflict(
                        dataset_version=dataset_version,
                        ingestion_manifest=ingestion_manifest,
                        existing_candle=prior,
                        existing_payload_sha256=_json_hash(existing_payload),
                        incoming_payload_sha256=_json_hash(incoming_payload),
                        differing_fields=sorted(
                            field
                            for field in set(existing_payload) | set(incoming_payload)
                            if existing_payload.get(field) != incoming_payload.get(field)
                        ),
                        incoming_payload=incoming_payload,
                    )
                )
        if conflicts:
            CandleConflict.objects.bulk_create(conflicts)
            incident_details = {
                "conflict_count": len(conflicts),
                "incoming_payload_sha256": sorted(
                    conflict.incoming_payload_sha256 for conflict in conflicts
                ),
            }
            DataQualityIncident.objects.create(
                dataset_version=dataset_version,
                ingestion_run=run,
                code="candle_conflict",
                details=incident_details,
                evidence_sha256=_json_hash(incident_details),
            )
            run.status = IngestionRun.Status.QUARANTINED
            run.fetched_count = len(candle_data)
            run.rejected_count = len(candle_data)
            run.failure_reason = "incoming batch conflicts with governed dataset"
            run.finished_at = timezone.now()
            run.save()
            return run

    if dataset_version is not None:
        rows = [
            Candle(
                instrument=instrument,
                ingestion_run=run,
                dataset_version=dataset_version,
                granularity=granularity,
                **item.__dict__,
            )
            for item in candle_data
            if item.timestamp not in existing_by_key
        ]
        Candle.objects.bulk_create(rows)
        run.status = IngestionRun.Status.SUCCEEDED
        run.fetched_count = len(candle_data)
        run.stored_count = len(rows)
        run.finished_at = timezone.now()
        run.save()
        AuditEvent.objects.create(
            event_type="market.ingestion_succeeded",
            actor="market.services.store_ingestion",
            subject_type="IngestionRun",
            subject_id=str(run.pk),
            payload={
                "fetched": run.fetched_count,
                "stored": run.stored_count,
                "manifest": digest,
                "replaced_fixture_candles": 0,
                "discarded_fixture_batch": False,
            },
        )
        return run

    outcome = _store_live_observations(source, instrument, granularity, run, candle_data)
    run.status = IngestionRun.Status.SUCCEEDED
    run.fetched_count = len(candle_data)
    run.stored_count = outcome["stored"]
    run.finished_at = timezone.now()
    run.save()
    AuditEvent.objects.create(
        event_type="market.ingestion_succeeded",
        actor="market.services.store_ingestion",
        subject_type="IngestionRun",
        subject_id=str(run.pk),
        payload={
            "fetched": run.fetched_count,
            "stored": run.stored_count,
            "manifest": digest,
            "replaced_fixture_candles": outcome["replaced_fixture_candles"],
            "discarded_fixture_batch": outcome["discarded_fixture_batch"],
            "observations": outcome["observations"],
        },
    )
    if outcome["conflicts"]:
        AuditEvent.objects.create(
            event_type="market.live_candle_conflict",
            actor="market.services.store_ingestion",
            subject_type="IngestionRun",
            subject_id=str(run.pk),
            payload={
                "instrument": instrument.code,
                "granularity": granularity,
                "conflicts": outcome["conflicts"],
            },
        )
    calculate_and_store_snapshot(instrument, granularity)
    return run


LIVE_STEPS = {
    "W": timedelta(weeks=1),
    "D": timedelta(days=1),
    "H4": timedelta(hours=4),
    "H1": timedelta(hours=1),
}


def live_candle_completion(timestamp, granularity):
    """Completion instant of one live provider candle.

    H1/H4 candles are absolute-duration intervals (the provider never merges
    two hours into one during a DST transition), so completion is exact UTC
    arithmetic. Daily and weekly candles are aligned to the 17:00
    America/New_York close and therefore complete one local day/week later.
    """
    if granularity in {"H1", "H4"}:
        return timestamp + LIVE_STEPS[granularity]
    return registered_candle_completion(timestamp, granularity)


def candle_content_sha256(instrument_code, granularity, candle):
    """Deterministic identity of one candle's evidence content."""
    return _json_hash(
        {
            "instrument": instrument_code,
            "granularity": granularity,
            **_candle_payload(candle),
        }
    )


def candle_is_referenced(candle):
    """True when frozen evidence outside the market app points at this candle row."""
    for relation in Candle._meta.related_objects:
        model = relation.related_model
        if model._meta.app_label == "market":
            continue
        if model._default_manager.filter(**{relation.field.name: candle}).exists():
            return True
    return False


def _serialize_live_series(instrument, granularity):
    """Serialize concurrent live ingestion for one series inside the transaction."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"live-candles:{instrument.pk}:{granularity}"],
        )


def _store_live_observations(source, instrument, granularity, run, candle_data):
    _serialize_live_series(instrument, granularity)
    series = Candle.objects.filter(
        instrument=instrument, granularity=granularity, dataset_version=None
    )
    fixture_source = source.name == "Development fixtures"
    discard_fixture_batch = fixture_source and series.exclude(ingestion_run__source=source).exists()
    replaced_fixture_count = 0
    if not fixture_source:
        fixture_rows = series.filter(provenance=Candle.Provenance.FIXTURE)
        replaced_fixture_count = fixture_rows.count()
        if replaced_fixture_count:
            fixture_rows.delete()
            TechnicalSnapshot.objects.filter(
                instrument=instrument,
                granularity=granularity,
                provenance=TechnicalSnapshot.Provenance.FIXTURE,
            ).delete()
    counts = Counter()
    conflicts = []
    if discard_fixture_batch:
        return {
            "stored": 0,
            "replaced_fixture_candles": replaced_fixture_count,
            "discarded_fixture_batch": True,
            "observations": dict(counts),
            "conflicts": conflicts,
        }

    timestamps = [item.timestamp for item in candle_data]
    existing_by_key = {
        row.timestamp: row for row in series.select_for_update().filter(timestamp__in=timestamps)
    }
    latest_existing = series.order_by("-timestamp").values_list("timestamp", flat=True).first()
    current_observations = {}
    for observation in (
        CandleObservation.objects.filter(
            instrument=instrument,
            granularity=granularity,
            source=source,
            timestamp__in=timestamps,
        )
        .order_by("timestamp", "revision")
        .select_for_update()
    ):
        current_observations[observation.timestamp] = observation
    observed_at = timezone.now()
    provenance = Candle.Provenance.FIXTURE if fixture_source else Candle.Provenance.OBSERVED
    new_rows = []
    new_kinds = []
    revisions = []
    for item in candle_data:
        digest = candle_content_sha256(instrument.code, granularity, item)
        prior = existing_by_key.get(item.timestamp)
        if prior is None:
            kind = (
                CandleObservation.Kind.LATE_ARRIVAL
                if latest_existing is not None and item.timestamp < latest_existing
                else CandleObservation.Kind.INITIAL
            )
            new_rows.append(
                Candle(
                    instrument=instrument,
                    ingestion_run=run,
                    dataset_version=None,
                    granularity=granularity,
                    content_sha256=digest,
                    observed_at=observed_at,
                    provenance=provenance,
                    **item.__dict__,
                )
            )
            new_kinds.append(kind)
            counts[kind] += 1
            continue
        prior_payload = _candle_payload(prior)
        incoming_payload = _candle_payload(item)
        agrees_with_frozen = prior_payload == incoming_payload
        current = current_observations.get(item.timestamp)
        # The current provider view is the highest recorded revision, or the
        # frozen row itself when no observation exists (legacy rows). Content
        # equal to the current view is a no-op. Any other content supersedes
        # it as revision N+1 -- including a return to content the provider
        # published in an earlier revision (A -> B -> A) or to the frozen
        # content itself -- so the ledger records every change of view and a
        # retry of any batch is idempotent.
        if current is None:
            matches_current = agrees_with_frozen
        else:
            matches_current = current.content_sha256 == digest
        if matches_current:
            counts["duplicate" if agrees_with_frozen else "duplicate_revision"] += 1
            continue
        kind = (
            CandleObservation.Kind.CONFLICT
            if not agrees_with_frozen and candle_is_referenced(prior)
            else CandleObservation.Kind.REVISION
        )
        differing = sorted(
            field
            for field in set(prior_payload) | set(incoming_payload)
            if prior_payload.get(field) != incoming_payload.get(field)
        )
        revision = CandleObservation(
            instrument=instrument,
            granularity=granularity,
            timestamp=item.timestamp,
            interval_end=live_candle_completion(item.timestamp, granularity),
            source=source,
            ingestion_run=run,
            candle=prior,
            kind=kind,
            revision=(current.revision if current is not None else 1) + 1,
            supersedes=current,
            content_sha256=digest,
            differing_fields=differing,
            observed_at=observed_at,
            **{key: value for key, value in item.__dict__.items() if key != "timestamp"},
        )
        revisions.append(revision)
        current_observations[item.timestamp] = revision
        counts[kind] += 1
        if kind == CandleObservation.Kind.CONFLICT:
            conflicts.append(
                {
                    "candle_id": prior.pk,
                    "interval_start": item.timestamp.isoformat(),
                    "frozen_content_sha256": prior.content_sha256,
                    "incoming_content_sha256": digest,
                    "differing_fields": differing,
                }
            )
    Candle.objects.bulk_create(new_rows)
    if fixture_source:
        # Development fixtures are not provider observations: they never enter
        # the append-only observation ledger and remain deletable on replacement.
        return {
            "stored": len(new_rows),
            "replaced_fixture_candles": replaced_fixture_count,
            "discarded_fixture_batch": False,
            "observations": dict(counts),
            "conflicts": conflicts,
        }
    initial_observations = [
        CandleObservation(
            instrument=instrument,
            granularity=granularity,
            timestamp=row.timestamp,
            interval_end=live_candle_completion(row.timestamp, granularity),
            complete=row.complete,
            volume=row.volume,
            bid_open=row.bid_open,
            bid_high=row.bid_high,
            bid_low=row.bid_low,
            bid_close=row.bid_close,
            ask_open=row.ask_open,
            ask_high=row.ask_high,
            ask_low=row.ask_low,
            ask_close=row.ask_close,
            source=source,
            ingestion_run=run,
            candle=row,
            kind=kind,
            revision=1,
            supersedes=None,
            content_sha256=row.content_sha256,
            differing_fields=[],
            observed_at=observed_at,
        )
        for row, kind in zip(new_rows, new_kinds, strict=True)
    ]
    CandleObservation.objects.bulk_create(initial_observations + revisions)
    return {
        "stored": len(new_rows),
        "replaced_fixture_candles": replaced_fixture_count,
        "discarded_fixture_batch": False,
        "observations": dict(counts),
        "conflicts": conflicts,
    }


def _candle_payload(candle):
    fields = (
        "timestamp",
        "complete",
        "volume",
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
    )
    return {
        field: (
            value.isoformat()
            if field == "timestamp"
            else format(value, ".6f")
            if field.startswith(("bid_", "ask_"))
            else str(value)
        )
        for field in fields
        if (value := getattr(candle, field)) is not None
    }


def _json_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def technical_source_set_sha256(instrument_code, granularity, candles):
    """Identity of the exact ordered candle evidence a technical calculation consumed."""
    return _json_hash(
        {
            "instrument": instrument_code,
            "granularity": granularity,
            "algorithm_version": TechnicalSnapshot.ALGORITHM_VERSION,
            "candles": [
                {
                    "content_sha256": candle.content_sha256
                    or candle_content_sha256(instrument_code, granularity, candle),
                    "provenance": candle.provenance,
                }
                for candle in candles
            ],
        }
    )


def calculate_and_store_snapshot(instrument, granularity):
    """Append the technical calculation for the current candle set; never rewrite one."""
    candles = list(
        Candle.objects.filter(instrument=instrument, granularity=granularity).order_by(
            "timestamp", "id"
        )
    )
    if not candles:
        return None
    values = calculate_technicals(candles)
    provenance = (
        TechnicalSnapshot.Provenance.FIXTURE
        if any(candle.provenance == Candle.Provenance.FIXTURE for candle in candles)
        else TechnicalSnapshot.Provenance.OBSERVED
    )
    snapshot, _ = TechnicalSnapshot.objects.get_or_create(
        instrument=instrument,
        granularity=granularity,
        as_of=candles[-1].timestamp,
        algorithm_version=TechnicalSnapshot.ALGORITHM_VERSION,
        source_candle_set_sha256=technical_source_set_sha256(instrument.code, granularity, candles),
        defaults={"candle_count": len(candles), "provenance": provenance, **values.__dict__},
    )
    return snapshot


@transaction.atomic
def store_oanda_terms(payload, account_id, captured_at=None):
    captured_at = (captured_at or timezone.now()).replace(minute=0, second=0, microsecond=0)
    account_fingerprint = hashlib.sha256(account_id.encode()).hexdigest()
    snapshots = []
    created_count = 0
    for item in payload["instruments"]:
        instrument = Instrument.objects.get(code=item["name"])
        financing = item["financing"]
        normalized = {
            "instrument": item["name"],
            "account_currency": payload["account_currency"],
            "financing": financing,
            "commission": item.get("commission"),
            "marginRate": item["marginRate"],
            "pipLocation": item["pipLocation"],
            "manifest": payload["manifest"],
        }
        response_sha256 = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot, created = OandaInstrumentTermsSnapshot.objects.get_or_create(
            instrument=instrument,
            environment=payload["manifest"]["environment"],
            account_fingerprint=account_fingerprint,
            captured_at=captured_at,
            defaults={
                "account_currency": payload["account_currency"],
                "long_financing_rate": financing["longRate"],
                "short_financing_rate": financing["shortRate"],
                "financing_days": financing["financingDaysOfWeek"],
                "commission": item.get("commission") or {},
                "commission_supplied": item.get("commission") is not None,
                "margin_rate": item["marginRate"],
                "pip_location": item["pipLocation"],
                "response_sha256": response_sha256,
            },
        )
        created_count += created
        snapshots.append(snapshot)
    if created_count:
        AuditEvent.objects.create(
            event_type="market.oanda_terms_captured",
            actor="market.services.store_oanda_terms",
            subject_type="OandaInstrumentTermsSnapshot",
            subject_id=captured_at.isoformat(),
            payload={
                "instrument_count": len(snapshots),
                "environment": payload["manifest"]["environment"],
                "commission_supplied_count": sum(item.commission_supplied for item in snapshots),
            },
        )
    return snapshots
