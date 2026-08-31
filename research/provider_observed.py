"""Provider-observed (v2) data membership for S0/S1.

Under a HistoricalDataContract, exact historical membership comes only from
the sealed Gate 5 timestamp inventory — never from the theoretical calendar.
Calendar functions remain in use for strategy-session, completion, DST,
point-in-time and entry semantics; membership questions are answered here.
"""

from __future__ import annotations

from market.models import HistoricalDataContract, HistoricalTimestampObservation


def contract_for_dataset(dataset):
    """Resolve the effective data contract for a registered dataset.

    Returns None for legacy v1 datasets. A v2 identity is never inferred
    implicitly: only an explicit plan-level binding to a real
    HistoricalDataContract row qualifies.
    """
    registration = getattr(dataset, "registration", None)
    if registration is None:
        return None
    contract = registration.plan.data_contract
    if not isinstance(contract, HistoricalDataContract):
        return None
    return contract


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
