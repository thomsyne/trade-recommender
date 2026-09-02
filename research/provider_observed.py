"""Provider-observed (v2) data membership for S0/S1.

Under a HistoricalDataContract, exact historical membership comes only from
the sealed Gate 5 timestamp inventory — never from the theoretical calendar.
Calendar functions remain in use for strategy-session, completion, DST,
point-in-time and entry semantics; membership questions are answered here.
"""

from __future__ import annotations

from market.models import Candle, HistoricalTimestampObservation, IngestionRun


def contract_for_dataset(dataset):
    """Resolve the effective data contract for a registered dataset.

    Delegates to the single application-level resolver, which validates the
    complete plan/dataset/registration/contract relationship and fails
    closed on incomplete or conflicting v2 lineage.
    """
    from market.services import provider_observed_contract

    return provider_observed_contract(dataset)


def inventory_timestamps(contract, instrument_code, granularity):
    """Chronological sealed observations for one instrument/granularity."""
    from market.models import Instrument
    from market.services import _sealed_series_timestamps

    instrument_id = (
        Instrument.objects.filter(code=instrument_code).values_list("pk", flat=True).first()
    )
    return _sealed_series_timestamps(contract, instrument_id, granularity)


def inventory_window(contract, instrument_code, granularity, start, end):
    """Sealed observations inside the closed-open [start, end) window."""
    return tuple(
        timestamp
        for timestamp in inventory_timestamps(contract, instrument_code, granularity)
        if start <= timestamp < end
    )


def contract_range_bounds(contract, granularity):
    """The sealed discovery request bounds for one granularity."""
    chunks = contract.discovery_registration.plan.chunks.filter(granularity=granularity)
    first = chunks.order_by("requested_from").values_list("requested_from", flat=True).first()
    last = chunks.order_by("-requested_to").values_list("requested_to", flat=True).first()
    return first, last


def entry_timestamp_is_sealed(contract, instrument_code, timestamp):
    """Whether a strategy-derived H1 entry timestamp exists in the inventory."""
    return HistoricalTimestampObservation.objects.filter(
        inventory__chunk__plan=contract.discovery_registration.plan,
        inventory__chunk__instrument__code=instrument_code,
        inventory__chunk__granularity="H1",
        timestamp=timestamp,
    ).exists()


def dataset_inventory_timestamps(dataset, contract, instrument_code, granularity):
    """Ordered governed membership, retaining actual-row legacy compatibility."""
    if contract is not None:
        return inventory_timestamps(contract, instrument_code, granularity)
    return tuple(
        Candle.objects.filter(
            dataset_version=dataset,
            instrument__code=instrument_code,
            granularity=granularity,
            complete=True,
            ingestion_run__dataset_version=dataset,
            ingestion_run__status=IngestionRun.Status.SUCCEEDED,
        )
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
    )
