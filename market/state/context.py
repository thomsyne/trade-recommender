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

from datetime import UTC, timedelta

from market.state.canonical import format_decimal

EVENT_STATE_V = "event-state-v1"
MACRO_REGIME_V = "macro-regime-v1"
SPREAD_V = "spread-v1"

#: Explicit currency -> ISO-2 country policy (mirrors research.services).
CURRENCY_COUNTRY = {"USD": "US", "CAD": "CA", "GBP": "GB", "EUR": "EU"}
COUNTRY_CURRENCY = {country: currency for currency, country in CURRENCY_COUNTRY.items()}

EVENT_BOUND_DAYS = 30  # bounded query window around the cutoff
EVENT_LOOKBACK_DAYS = 1  # recent events retained
EVENT_HORIZON_DAYS = 7  # upcoming events retained


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


def event_state(instrument, information_cutoff):
    """Scheduled-event state for the pair's currencies, vintage-correct at cutoff."""
    from research.models import EconomicEvent

    countries = _pair_countries(instrument)
    if countries is None:
        return _unavailable(EVENT_STATE_V, "provenance_unavailable")
    rows = EconomicEvent.objects.filter(
        country__in=countries,
        first_observed_at__lte=information_cutoff,
        event_at__gte=information_cutoff - timedelta(days=EVENT_BOUND_DAYS),
        event_at__lte=information_cutoff + timedelta(days=EVENT_BOUND_DAYS),
    ).order_by("event_at", "provider_event_key")
    # Keep the latest vintage (max first_observed_at) known by the cutoff per event.
    latest = {}
    for event in rows:
        current = latest.get(event.provider_event_key)
        if current is None or event.first_observed_at > current.first_observed_at:
            latest[event.provider_event_key] = event
    window_start = information_cutoff - timedelta(days=EVENT_LOOKBACK_DAYS)
    window_end = information_cutoff + timedelta(days=EVENT_HORIZON_DAYS)
    items = []
    for event in sorted(latest.values(), key=lambda e: (e.event_at, e.provider_event_key)):
        if not (window_start <= event.event_at <= window_end):
            continue
        item = {
            "event_type": event.event_type,
            "country": event.country,
            "currency": COUNTRY_CURRENCY.get(event.country, event.country),
            "time_precision": event.time_precision,
            "status": event.status,
            "first_observed_at": _iso(event.first_observed_at),
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
    return {"state": "available", "version": EVENT_STATE_V, "events": items}


def _policy_rate_regime(country, information_cutoff):
    from research.models import MacroSeries

    series = MacroSeries.objects.filter(
        indicator=MacroSeries.Indicator.POLICY_RATE, source_policy__jurisdiction=country
    ).first()
    if series is None:
        return _unavailable(MACRO_REGIME_V, "macro_vintage_unavailable")
    known = series.observations.filter(
        available_at__lte=information_cutoff,
        vintage_at__lte=information_cutoff,
        retrieval__fetched_at__lte=information_cutoff,
    )
    latest = known.first()  # ordering: -observation_period, -revision_sequence
    if latest is None:
        return _unavailable(MACRO_REGIME_V, "macro_vintage_unavailable")
    prior = known.exclude(observation_period=latest.observation_period).first()
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
    }


def macro_regime(instrument, information_cutoff):
    """Latest point-in-time policy-rate regime for each of the pair's currencies."""
    countries = _pair_countries(instrument)
    if countries is None:
        return _unavailable(MACRO_REGIME_V, "provenance_unavailable")
    per_currency = {}
    for currency in (instrument.base_currency, instrument.quote_currency):
        per_currency[currency] = _policy_rate_regime(CURRENCY_COUNTRY[currency], information_cutoff)
    return {"state": "available", "version": MACRO_REGIME_V, "by_currency": per_currency}
