"""Point-in-time macro, scheduled-event and spread context.

Consumes only existing attested research records and their true vintages
(read-only; no research snapshot is written and no macro store is duplicated).
Every read is bounded by the information cutoff on all three of a record's time
axes where they exist (availability, vintage, retrieval), and the latest vintage
known by the cutoff is used — a later revision never influences an earlier
snapshot. Unknown macro state is unavailable, not neutral; a date-only event is
never rendered as an exact intraday risk window; there is no trustworthy event
severity field, so severity is reported unavailable rather than invented. Spread
is the observed bid/ask at the candle close — never backfilled (design §10).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from market.state.canonical import format_decimal, identity_digest

EVENT_STATE_V = "event-state-v1"
MACRO_REGIME_V = "macro-regime-v1"
SPREAD_V = "spread-v1"

#: Explicit currency -> ISO-2 country policy (mirrors research.services).
CURRENCY_COUNTRY = {"USD": "US", "CAD": "CA", "GBP": "GB", "EUR": "EU"}
COUNTRY_CURRENCY = {country: currency for currency, country in CURRENCY_COUNTRY.items()}

EVENT_BOUND_DAYS = 30  # bounded query window around the cutoff
EVENT_LOOKBACK_DAYS = 1  # recent events retained
EVENT_HORIZON_DAYS = 7  # upcoming events retained
MACRO_LOOKBACK_DAYS = 730  # latest two published periods within two calendar years
MAX_RESEARCH_ROWS = 2048


def freeze_research(instrument, earliest, information_cutoff):
    """Materialize bounded vintages before price computation, including reschedules.

    These private model instances have all consumed relations eagerly loaded.
    Callers receive tuple collections and never query them again. Overflow fails
    closed rather than silently classifying a truncated research history.
    """
    from research.models import EconomicEvent, MacroObservation, MacroSeries

    countries = _pair_countries(instrument)
    if countries is None:
        return MappingProxyType({"events": (), "rates": ()})
    candidates = EconomicEvent.objects.filter(
        country__in=countries,
        event_at__gte=earliest - timedelta(days=EVENT_LOOKBACK_DAYS),
        event_at__lte=information_cutoff + timedelta(days=EVENT_HORIZON_DAYS),
    ).values("provider_event_key")
    events = tuple(
        EconomicEvent.objects.filter(
            country__in=countries,
            provider_event_key__in=candidates,
            first_observed_at__lte=information_cutoff,
            retrieval__fetched_at__lte=information_cutoff,
        )
        .select_related("retrieval__source_policy__source", "series__source_policy__source")
        .order_by("provider_event_key", "first_observed_at", "payload_fingerprint")[
            : MAX_RESEARCH_ROWS + 1
        ]
    )
    series = list(
        MacroSeries.objects.filter(
            indicator=MacroSeries.Indicator.POLICY_RATE,
            source_policy__jurisdiction__in=countries,
            unit="%",
            transformation=MacroSeries.Transformation.NONE,
        )
        .select_related("source_policy__source")
        .order_by("code")[: MAX_RESEARCH_ROWS + 1]
    )
    selected = {}
    for item in series:
        selected.setdefault(item.source_policy.jurisdiction, item.pk)
    rates = tuple(
        MacroObservation.objects.filter(
            series_id__in=selected.values(),
            observation_period__gte=earliest.date() - timedelta(days=MACRO_LOOKBACK_DAYS),
            observation_period__lte=information_cutoff.date(),
            available_at__lte=information_cutoff,
            vintage_at__lte=information_cutoff,
            retrieval__fetched_at__lte=information_cutoff,
        )
        .select_related("retrieval__source_policy__source", "series__source_policy__source")
        .order_by("series__code", "observation_period", "revision_sequence")[
            : MAX_RESEARCH_ROWS + 1
        ]
    )
    if max(len(events), len(rates), len(series)) > MAX_RESEARCH_ROWS:
        raise ValueError("research_history_limit_exceeded")
    return MappingProxyType({"events": events, "rates": rates})


def record_identity(record):
    """Bind exact stored content without embedding provider bodies in a snapshot."""
    import hashlib

    values = {}
    for field in record._meta.concrete_fields:
        value = getattr(record, field.attname)
        if isinstance(value, datetime):
            value = _iso(value)
        elif isinstance(value, (date, Decimal)):
            value = str(value)
        elif isinstance(value, (bytes, memoryview)):
            value = hashlib.sha256(bytes(value)).hexdigest()
        values[field.attname] = value
    return {
        "model": record._meta.label_lower,
        "id": record.pk,
        "content_sha256": identity_digest(values),
    }


def research_lineage(record):
    retrieval = record.retrieval
    policy = retrieval.source_policy
    records = [record, retrieval, policy, policy.source]
    if getattr(record, "series_id", None):
        records.append(record.series)
        if record.series.source_policy_id != policy.pk:
            records.extend([record.series.source_policy, record.series.source_policy.source])
    return [record_identity(r) for r in records]


def _iso(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _unavailable(version, reason):
    return {"state": "unavailable", "version": version, "reason_code": reason}


def _pair_countries(instrument):
    try:
        return {
            CURRENCY_COUNTRY[instrument.base_currency],
            CURRENCY_COUNTRY[instrument.quote_currency],
        }
    except KeyError:
        return None


def spread_context(observation, atr):
    """Observed spread (ask-bid at close) of the latest eligible candle."""
    spread = observation.ask_close - observation.bid_close
    result = {
        "state": "available",
        "version": SPREAD_V,
        "spread": format_decimal(spread),
        "units": "price",
    }
    if atr and atr != 0:
        result["spread_atr"] = format_decimal(spread / atr)
    else:
        result["spread_atr"] = {"state": "unavailable", "reason_code": "atr_unavailable"}
    return result


def event_state(instrument, information_cutoff, *, frozen=None):
    """Scheduled-event state for the pair's currencies, vintage-correct at cutoff.

    Every vintage *known by the cutoff* (``first_observed_at`` and its retrieval
    ``fetched_at`` both at or before the cutoff) is considered; the latest vintage
    per event is selected FIRST, and only then is the display window applied — so a
    reschedule out of the window cannot resurrect the obsolete in-window vintage.
    If no event vintage is known at all for the pair, coverage is unavailable
    rather than an attested-empty calendar."""
    from django.db.models import OuterRef, Subquery

    from research.models import EconomicEvent

    countries = _pair_countries(instrument)
    if countries is None:
        return _unavailable(EVENT_STATE_V, "provenance_unavailable")
    if frozen is not None:
        latest = {}
        for event in frozen["events"]:
            if max(event.first_observed_at, event.retrieval.fetched_at) <= information_cutoff:
                key = event.provider_event_key
                old = latest.get(key)
                if old is None or (event.first_observed_at, event.payload_fingerprint) > (
                    old.first_observed_at,
                    old.payload_fingerprint,
                ):
                    latest[key] = event
        return _event_block(
            sorted(
                (
                    e
                    for e in latest.values()
                    if information_cutoff - timedelta(days=EVENT_LOOKBACK_DAYS)
                    <= e.event_at
                    <= information_cutoff + timedelta(days=EVENT_HORIZON_DAYS)
                ),
                key=lambda e: (e.event_at, e.provider_event_key),
            )
        )
    eligible = EconomicEvent.objects.filter(
        country__in=countries,
        first_observed_at__lte=information_cutoff,
        retrieval__fetched_at__lte=information_cutoff,
    )
    window_start = information_cutoff - timedelta(days=EVENT_LOOKBACK_DAYS)
    window_end = information_cutoff + timedelta(days=EVENT_HORIZON_DAYS)
    # The outer indexed date window bounds candidate work. The correlated latest
    # vintage is deliberately NOT date-windowed: a reschedule out of the window
    # must suppress the old in-window release rather than resurrect it.
    latest_id = (
        eligible.filter(provider_event_key=OuterRef("provider_event_key"))
        .order_by("-first_observed_at", "-payload_fingerprint")
        .values("pk")[:1]
    )
    known = (
        eligible.filter(
            event_at__gte=window_start, event_at__lte=window_end, pk=Subquery(latest_id)
        )
        .select_related("retrieval__source_policy__source", "series__source_policy__source")
        .order_by("event_at", "provider_event_key")
    )
    known = list(known[: MAX_RESEARCH_ROWS + 1])
    if len(known) > MAX_RESEARCH_ROWS:
        raise ValueError("research_history_limit_exceeded")
    return _event_block(known)


def _event_block(known):
    from research.models import EconomicEvent

    items = []
    for event in known:
        item = {
            "event_type": event.event_type,
            "country": event.country,
            "currency": COUNTRY_CURRENCY.get(event.country, event.country),
            "time_precision": event.time_precision,
            "status": event.status,
            "first_observed_at": _iso(event.first_observed_at),
            "vintage_id": event.payload_fingerprint,
            "lineage": research_lineage(event),
            "severity": {"state": "unavailable", "reason_code": "severity_unavailable"},
        }
        if event.time_precision == EconomicEvent.TimePrecision.EXACT:
            item["event_at"] = _iso(event.event_at)
            item["intraday_risk_window"] = "defined"
        else:
            item["event_date"] = event.event_at.astimezone(UTC).date().isoformat()
            item["intraday_risk_window"] = {
                "state": "unavailable",
                "reason_code": "event_time_date_only",
            }
        items.append(item)
    # Seeing individual releases is not an attestation of complete calendar coverage.
    # In particular an out-of-window record cannot turn unknown into attested-empty.
    if not items:
        return {**_unavailable(EVENT_STATE_V, "event_coverage_unavailable"), "events": []}
    return {
        "state": "available",
        "version": EVENT_STATE_V,
        "events": items,
        "coverage": "unattested",
    }


def evidence_manifest(event_block, macro_block):
    """The macro/event vintage identities a snapshot consumed, for the snapshot
    identity — so a change of consumed vintage yields a new snapshot."""
    events = [e["lineage"] for e in event_block.get("events", [])]
    macro = {}
    for currency, block in sorted((macro_block.get("by_currency") or {}).items()):
        if isinstance(block, dict) and block.get("state") == "available":
            macro[currency] = block["lineage"]
    return {"events": events, "macro": macro}


def _policy_rate_regime(country, information_cutoff, *, frozen=None):
    from research.models import MacroSeries

    if frozen is not None:
        periods = {}
        for rate in frozen["rates"]:
            if rate.series.source_policy.jurisdiction != country:
                continue
            if (
                not information_cutoff.date() - timedelta(days=MACRO_LOOKBACK_DAYS)
                <= rate.observation_period
                <= information_cutoff.date()
            ):
                continue
            if (
                max(rate.available_at, rate.vintage_at, rate.retrieval.fetched_at)
                > information_cutoff
            ):
                continue
            old = periods.get(rate.observation_period)
            if old is None or (rate.revision_sequence, rate.vintage_at, rate.normalized_value) > (
                old.revision_sequence,
                old.vintage_at,
                old.normalized_value,
            ):
                periods[rate.observation_period] = rate
        return _rate_block([periods[k] for k in sorted(periods, reverse=True)[:2]])
    series = (
        MacroSeries.objects.filter(
            indicator=MacroSeries.Indicator.POLICY_RATE,
            source_policy__jurisdiction=country,
            unit="%",
            transformation=MacroSeries.Transformation.NONE,
        )
        .select_related("source_policy__source")
        .order_by("code")
        .first()
    )
    if series is None:
        return _unavailable(MACRO_REGIME_V, "macro_vintage_unavailable")
    known = (
        series.observations.select_related(
            "retrieval__source_policy__source", "series__source_policy__source"
        )
        .filter(
            observation_period__gte=information_cutoff.date() - timedelta(days=MACRO_LOOKBACK_DAYS),
            observation_period__lte=information_cutoff.date(),
            available_at__lte=information_cutoff,
            vintage_at__lte=information_cutoff,
            retrieval__fetched_at__lte=information_cutoff,
        )
        .order_by("-observation_period", "-revision_sequence", "-vintage_at", "normalized_value")
        .distinct("observation_period")
    )
    # One statement freezes both periods; no second read can observe a new
    # revision between selecting the current and previous observation.
    periods = list(known[:2])
    return _rate_block(periods)


def _rate_block(periods):
    if not periods:
        return _unavailable(MACRO_REGIME_V, "macro_vintage_unavailable")
    latest = periods[0]
    series = latest.series
    prior = periods[1] if len(periods) == 2 else None
    if prior is None:
        direction = "unknown"
    elif latest.value > prior.value:
        direction = "tightening"
    elif latest.value < prior.value:
        direction = "easing"
    else:
        direction = "steady"
    return {
        "state": "available",
        "version": MACRO_REGIME_V,
        "indicator": "policy_rate",
        "series": series.code,
        "value": format_decimal(latest.value),
        "observation_period": latest.observation_period.isoformat(),
        "vintage_at": _iso(latest.vintage_at),
        "availability_precision": latest.availability_precision,
        "direction": direction,
        "unit": series.unit,
        "transformation": series.transformation,
        "lineage": research_lineage(latest) + (research_lineage(prior) if prior else []),
    }


def macro_regime(instrument, information_cutoff, *, frozen=None):
    """Latest point-in-time policy-rate regime for each of the pair's currencies."""
    countries = _pair_countries(instrument)
    if countries is None:
        return _unavailable(MACRO_REGIME_V, "provenance_unavailable")
    per_currency = {}
    for currency in (instrument.base_currency, instrument.quote_currency):
        per_currency[currency] = _policy_rate_regime(
            CURRENCY_COUNTRY[currency], information_cutoff, frozen=frozen
        )
    return {"state": "available", "version": MACRO_REGIME_V, "by_currency": per_currency}
