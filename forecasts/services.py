import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from forecasts.models import EvidenceSnapshot, Forecast, ForecastResolution, TargetContract
from market.models import AuditEvent, Candle, Instrument, TechnicalSnapshot

PRICE_QUANTUM = Decimal("0.000001")
SCORE_QUANTUM = Decimal("0.000001")

CONTRACTS = (
    {
        "key": "macro-endpoint-20-session",
        "version": 1,
        "product": TargetContract.Product.MACRO,
        "horizon_sessions": 20,
        "neutral_atr_multiplier": Decimal("0.500"),
        "spread_multiplier": Decimal("2.00"),
        "scoring_rule": "mean-multiclass-brier-v1",
        "definition": {
            "reference": "latest completed OANDA daily candle midpoint close available at issuance",
            "endpoint": "midpoint close of the twentieth subsequently completed daily candle",
            "outcomes": ["up", "neutral", "down"],
            "neutral_band": "max(0.500 * issue-time daily ATR(14), 2.00 * issue-time close spread)",
            "equality": "neutral",
            "market_closure": "count completed broker daily sessions, not calendar days",
            "missing_data": "remain unresolved until twenty later validated sessions exist",
        },
    },
    {
        "key": "tactical-endpoint-5-session",
        "version": 1,
        "product": TargetContract.Product.TACTICAL,
        "horizon_sessions": 5,
        "neutral_atr_multiplier": Decimal("0.250"),
        "spread_multiplier": Decimal("2.00"),
        "scoring_rule": "mean-multiclass-brier-v1",
        "definition": {
            "reference": "latest completed OANDA daily candle midpoint close available at issuance",
            "endpoint": "midpoint close of the fifth subsequently completed daily candle",
            "outcomes": ["up", "neutral", "down"],
            "neutral_band": "max(0.250 * issue-time daily ATR(14), 2.00 * issue-time close spread)",
            "equality": "neutral",
            "entry_expiry": "fifth subsequently completed daily session",
            "market_closure": "count completed broker daily sessions, not calendar days",
            "missing_data": "remain unresolved until five later validated sessions exist",
        },
    },
)


@transaction.atomic
def ensure_target_contracts():
    contracts = {}
    for specification in CONTRACTS:
        lookup = {"key": specification["key"], "version": specification["version"]}
        contract = TargetContract.objects.filter(**lookup).first()
        if contract:
            for field, expected in specification.items():
                if getattr(contract, field) != expected:
                    raise ValidationError(
                        f"Stored target contract drifted: {contract} field {field}"
                    )
        else:
            contract = TargetContract.objects.create(**specification)
            AuditEvent.objects.create(
                event_type="forecast.contract_created",
                actor="forecasts.services.ensure_target_contracts",
                subject_type="TargetContract",
                subject_id=str(contract.pk),
                payload={"key": contract.key, "version": contract.version},
            )
        contracts[contract.product] = contract
    return contracts


@transaction.atomic
def issue_baselines(instrument, issued_at=None, allow_fixture=False):
    issued_at = issued_at or timezone.now()
    contracts = ensure_target_contracts()
    evidence = _capture_market_evidence(instrument, issued_at)
    if (
        evidence.anchor_candle.ingestion_run.source.name == "Development fixtures"
        and not allow_fixture
    ):
        raise ValidationError("Refusing to issue a prospective baseline from development fixtures")
    macro = _issue_baseline(contracts[TargetContract.Product.MACRO], evidence, issued_at)
    tactical = _issue_baseline(
        contracts[TargetContract.Product.TACTICAL], evidence, issued_at, parent=macro
    )
    return macro, tactical


def issue_all_baselines(issued_at=None, allow_fixture=False):
    issued_at = issued_at or timezone.now()
    return [
        issue_baselines(instrument, issued_at, allow_fixture=allow_fixture)
        for instrument in Instrument.objects.filter(active=True)
    ]


def _capture_market_evidence(instrument, captured_at):
    anchor = (
        Candle.objects.filter(instrument=instrument, granularity="D")
        .select_related("ingestion_run__source")
        .order_by("-timestamp")
        .first()
    )
    if not anchor:
        raise ValidationError(f"No completed daily candles exist for {instrument.code}")
    if captured_at <= anchor.timestamp:
        raise ValidationError(
            "Forecast issuance must occur after its anchor candle interval starts"
        )
    snapshot = TechnicalSnapshot.objects.filter(
        instrument=instrument, granularity="D", as_of=anchor.timestamp
    ).first()
    if not snapshot or snapshot.atr_14 is None or snapshot.ewma_20 is None:
        raise ValidationError(f"No complete daily technical snapshot exists for {instrument.code}")

    payload = {
        "instrument": instrument.code,
        "anchor_candle": {
            "id": anchor.pk,
            "interval_start": anchor.timestamp.isoformat(),
            "bid_close": str(anchor.bid_close),
            "ask_close": str(anchor.ask_close),
            "source": anchor.ingestion_run.source.name,
            "retrieval_manifest": anchor.ingestion_run.request_manifest_hash,
        },
        "technical_snapshot": {
            "id": snapshot.pk,
            "as_of": snapshot.as_of.isoformat(),
            "atr_14": str(snapshot.atr_14),
            "ewma_20": str(snapshot.ewma_20),
            "support": str(snapshot.support) if snapshot.support is not None else None,
            "resistance": str(snapshot.resistance) if snapshot.resistance is not None else None,
        },
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence = EvidenceSnapshot.objects.filter(sha256=digest).first()
    if evidence:
        return evidence
    return EvidenceSnapshot.objects.create(
        instrument=instrument,
        anchor_candle=anchor,
        technical_snapshot=snapshot,
        market_data_cutoff=captured_at,
        payload=payload,
        sha256=digest,
        captured_at=captured_at,
    )


def _issue_baseline(contract, evidence, issued_at, parent=None):
    key = (
        f"mechanical-ewma-v1:{evidence.instrument.code}:{contract.key}:"
        f"{contract.version}:{evidence.sha256}"
    )
    existing = Forecast.objects.filter(idempotency_key=key).first()
    if existing:
        return existing

    anchor = evidence.anchor_candle
    snapshot = evidence.technical_snapshot
    midpoint = anchor.midpoint_close.quantize(PRICE_QUANTUM)
    spread = anchor.ask_close - anchor.bid_close
    neutral_band = max(
        snapshot.atr_14 * contract.neutral_atr_multiplier,
        spread * contract.spread_multiplier,
    ).quantize(PRICE_QUANTUM)
    direction = classify_change(midpoint - snapshot.ewma_20, neutral_band)
    probabilities = {
        Forecast.Direction.UP: (Decimal("0.5000"), Decimal("0.3000"), Decimal("0.2000")),
        Forecast.Direction.NEUTRAL: (
            Decimal("0.2500"),
            Decimal("0.5000"),
            Decimal("0.2500"),
        ),
        Forecast.Direction.DOWN: (
            Decimal("0.2000"),
            Decimal("0.3000"),
            Decimal("0.5000"),
        ),
    }[direction]
    fixture = anchor.ingestion_run.source.name == "Development fixtures"
    forecast = Forecast.objects.create(
        instrument=evidence.instrument,
        target_contract=contract,
        evidence_snapshot=evidence,
        parent=parent,
        method="fixture-mechanical-ewma" if fixture else "mechanical-ewma",
        method_version=1,
        issued_at=issued_at,
        information_cutoff=issued_at,
        reference_midpoint=midpoint,
        neutral_band=neutral_band,
        direction=direction,
        probability_up=probabilities[0],
        probability_neutral=probabilities[1],
        probability_down=probabilities[2],
        abstained=True,
        abstention_reason=(
            "Mechanical controls forecast direction only; no conditional trade setup is authorized."
        ),
        entry_condition=Forecast.EntryCondition.NONE,
        setup_expires_after_sessions=contract.horizon_sessions,
        rationale=(
            f"Frozen EWMA control: issue midpoint {midpoint} is {direction} relative to EWMA(20) "
            f"{snapshot.ewma_20} after applying neutral band {neutral_band}."
        ),
        idempotency_key=key,
    )
    AuditEvent.objects.create(
        event_type="forecast.issued",
        actor="forecasts.services.issue_baselines",
        subject_type="Forecast",
        subject_id=str(forecast.pk),
        payload={
            "contract": str(contract),
            "evidence_sha256": evidence.sha256,
            "method": forecast.method,
            "abstained": forecast.abstained,
        },
    )
    return forecast


def resolve_due_forecasts(instrument=None):
    forecasts = Forecast.objects.filter(resolution__isnull=True).select_related(
        "target_contract", "evidence_snapshot__anchor_candle"
    )
    if instrument:
        forecasts = forecasts.filter(instrument=instrument)
    resolved = []
    for forecast in forecasts:
        resolution = resolve_forecast(forecast)
        if resolution:
            resolved.append(resolution)
    return resolved


@transaction.atomic
def resolve_forecast(forecast):
    forecast = Forecast.objects.select_for_update().get(pk=forecast.pk)
    if ForecastResolution.objects.filter(forecast=forecast).exists():
        return ForecastResolution.objects.get(forecast=forecast)
    later_candles = list(
        Candle.objects.filter(
            instrument=forecast.instrument,
            granularity="D",
            timestamp__gt=forecast.evidence_snapshot.anchor_candle.timestamp,
        ).order_by("timestamp")[: forecast.target_contract.horizon_sessions]
    )
    if len(later_candles) < forecast.target_contract.horizon_sessions:
        return None

    endpoint = later_candles[-1]
    endpoint_midpoint = endpoint.midpoint_close.quantize(PRICE_QUANTUM)
    change = (endpoint_midpoint - forecast.reference_midpoint).quantize(PRICE_QUANTUM)
    outcome = classify_change(change, forecast.neutral_band)
    setup_outcome, setup_details = _resolve_entry_observation(forecast, later_candles)
    resolution = ForecastResolution.objects.create(
        forecast=forecast,
        outcome=outcome,
        horizon_candle=endpoint,
        endpoint_midpoint=endpoint_midpoint,
        midpoint_change=change,
        setup_outcome=setup_outcome,
        brier_score=multiclass_brier(forecast, outcome),
        details={
            "sessions_observed": len(later_candles),
            "endpoint_interval_start": endpoint.timestamp.isoformat(),
            "midpoint_is_feature_not_execution_price": True,
            **setup_details,
        },
    )
    AuditEvent.objects.create(
        event_type="forecast.resolved",
        actor="forecasts.services.resolve_forecast",
        subject_type="ForecastResolution",
        subject_id=str(resolution.pk),
        payload={
            "forecast_id": forecast.pk,
            "outcome": outcome,
            "brier_score": str(resolution.brier_score),
        },
    )
    return resolution


def _resolve_entry_observation(forecast, candles):
    if forecast.entry_condition == Forecast.EntryCondition.NONE or forecast.entry_level is None:
        return ForecastResolution.SetupOutcome.NOT_OFFERED, {}
    side = "ask" if forecast.direction == Forecast.Direction.UP else "bid"
    for candle in candles:
        low = getattr(candle, f"{side}_low")
        high = getattr(candle, f"{side}_high")
        touched = (
            forecast.entry_condition == Forecast.EntryCondition.AT_OR_BELOW
            and low <= forecast.entry_level
        ) or (
            forecast.entry_condition == Forecast.EntryCondition.AT_OR_ABOVE
            and high >= forecast.entry_level
        )
        if touched:
            return ForecastResolution.SetupOutcome.ACTIVATED, {
                "entry_touch_interval_start": candle.timestamp.isoformat(),
                "entry_touch_side": side,
                "entry_is_daily_touch_not_assumed_fill": True,
            }
    return ForecastResolution.SetupOutcome.NOT_ACTIVATED, {}


def classify_change(change, neutral_band):
    if change > neutral_band:
        return Forecast.Direction.UP
    if change < -neutral_band:
        return Forecast.Direction.DOWN
    return Forecast.Direction.NEUTRAL


def multiclass_brier(forecast, outcome):
    probabilities = {
        Forecast.Direction.UP: forecast.probability_up,
        Forecast.Direction.NEUTRAL: forecast.probability_neutral,
        Forecast.Direction.DOWN: forecast.probability_down,
    }
    score = sum(
        (probability - (Decimal(1) if label == outcome else Decimal(0))) ** 2
        for label, probability in probabilities.items()
    ) / Decimal(3)
    return score.quantize(SCORE_QUANTUM)
