"""Manual bounded offline batch. No schedules, consumers or holdout-release option."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from functools import lru_cache

from market.quality import registered_successor
from market.state.canonical import canonical_json, identity_digest
from market.state.features import Bar
from market.state.sessions import session_open_utc
from market.strategy.contracts import SnapshotInput, arithmetic, encoded
from market.strategy.definitions import STRATEGIES
from market.strategy.evaluate import evaluate
from market.strategy.risk import volatility_overlay
from market.strategy.trend import breakout, ewmac, sigma
from research.validation_acquisition import ROOT
from research.validation_data import expected_times, load_development
from research.validation_execution import simulate
from research.validation_registration import Catalog, admit_period
from research.validation_replay import ReplayInput, Series, decision

BLOCKED = {
    "ewmac-d-v1": "genuine_financing_rollover_unavailable",
    "breakout-d-v1": "genuine_financing_rollover_unavailable",
    "carry-readiness-v1": "pit_forwards_financing_rollover_ranking_unavailable",
    "range-m15-v1": "event_expansion_clearance_unavailable",
    "macro-risk-v1": "mandatory_pit_event_vintages_unavailable",
}
OVERLAYS = ("fixed-risk-v1", "ewma-risk-v1", "garch-t-risk-v1", "macro-risk-v1")


@lru_cache(maxsize=8)
def series_for(path, manifest_json, instrument, granularity):
    return Series(load_development(path, json.loads(manifest_json), instrument, granularity))


def timeframe(strategy):
    if strategy in ("ewmac-d-v1", "breakout-d-v1", "carry-readiness-v1"):
        return "D"
    return "H1" if strategy in ("fast-mr-h1-v1", "pullback-h1-v1") else "M15"


def opportunities(strategy, day):
    if strategy.startswith("orb-"):
        if day.weekday() < 5:
            yield session_open_utc(day.date(), strategy.split(":")[1])[0]
    else:
        yield from (
            datetime.fromisoformat(at)
            for at in expected_times(
                day, day + timedelta(days=1), timeframe(strategy), completed=False
            )
        )


def selection(strategy, instrument, at, data):
    if strategy in BLOCKED:
        return {"schema": "phase55/readiness-v1", "reason": BLOCKED[strategy]}, None
    if not strategy.startswith("orb-"):
        output = decision(instrument, strategy, at, data)
        setup = next((p for p in output["outputs"] if p["schema"] == "phase5/setup-v1"), None)
        return output, setup
    # The first attempt is terminal, including unavailability. No full-session
    # snapshot is used to retroactively authorize an earlier signal.
    for step in range(2, 9):
        cutoff = at + timedelta(minutes=15 * step)
        output = decision(instrument, strategy, cutoff, data)
        part = output["outputs"][0]
        if part["schema"] == "phase5/setup-v1":
            return output, part
        if part["reason"] != "no_confirmation_before_expiry":
            return output, None
    return output, None


def row_reason(output):
    if output.get("schema") == "phase55/readiness-v1":
        return output["reason"]
    return output["outputs"][0].get("reason", "setup_unavailable")


@arithmetic
def forecast_step(
    strategy,
    instrument,
    bars,
    *,
    costs,
    cutoff,
    registration,
    scenario,
    conversion_rate,
    execution_spread,
    previous=None,
):
    """Frozen next-D exposure mapping, not a fill or financing simulator.

    Completed bars size the exposure; the execution spread only charges its
    change. The persisted predecessor belongs to this identity/pair/scenario.
    Real batch admission still stops at the genuine-financing readiness gate:
    this pure capability cannot manufacture a financed development observation.
    """
    if strategy not in ("ewmac-d-v1", "breakout-d-v1") or scenario not in registration["scenarios"]:
        raise ValueError("forecast_mapping_attribution")
    if (
        cutoff.utcoffset() != timedelta(0)
        or not bars
        or bars[-1].end != cutoff
        or any(b.granularity != "D" or b.end > cutoff for b in bars)
    ):
        raise ValueError("forecast_mapping_noncausal_bars")
    execute_at = registered_successor(bars[-1].timestamp, "D")
    if scenario == "extra_interval_latency":
        execute_at = registered_successor(execute_at, "D")
    if execute_at >= datetime.fromisoformat(registration["development"][1]):
        raise ValueError("sealed_forecast_execution")
    if previous is not None and (
        previous.get("identity")
        != identity_digest({k: v for k, v in previous.items() if k != "identity"})
        or any(
            previous.get(k) != v
            for k, v in {
                "strategy": strategy,
                "instrument": instrument,
                "scenario": scenario,
                "registration": identity_digest(registration),
            }.items()
        )
        or datetime.fromisoformat(previous["cutoff"]) >= cutoff
        or datetime.fromisoformat(previous["execute_at"]) >= execute_at
    ):
        raise ValueError("forecast_mapping_predecessor")
    prior_forecast = D(previous["buffered"]) if previous else D(0)
    forecast = (ewmac if strategy == "ewmac-d-v1" else breakout)(
        bars, costs=costs, cutoff=cutoff, previous=prior_forecast
    )
    volatility = sigma(tuple(b.close for b in bars))
    if forecast.buffered is None or volatility is None:
        return {
            "state": "unavailable",
            "reason": forecast.reason or "volatility_unavailable",
        }, previous
    rate, spread = conversion_rate, execution_spread
    if (
        rate is None
        or spread is None
        or not rate.is_finite()
        or rate <= 0
        or not spread.is_finite()
        or spread <= 0
    ):
        return {
            "state": "unavailable",
            "reason": "forecast_conversion_or_spread_unavailable",
        }, previous
    price = bars[-1].close
    equity = D(registration["research_equity_CAD"])
    cap = min(
        equity / (price * rate), equity * D(registration["risk_fraction"]) / (volatility * rate)
    )
    units = forecast.buffered / 20 * cap
    change = units - (D(previous["units"]) if previous else D(0))
    state = {
        "strategy": strategy,
        "instrument": instrument,
        "scenario": scenario,
        "registration": identity_digest(registration),
        "cutoff": cutoff.isoformat(),
        "execute_at": execute_at.isoformat(),
        "buffered": str(forecast.buffered),
        "units": str(units),
        "predecessor": previous["identity"] if previous else None,
    }
    state["identity"] = identity_digest(state)
    return {
        "state": "mapped_exposure_not_execution",
        "forecast": json.loads(encoded(forecast)),
        "baseline_units_cap": str(cap),
        "units_change": str(change),
        "turnover_CAD": str(abs(change) * price * rate),
        "spread_CAD": str(abs(change) * spread * rate / 2),
        "commission_CAD": str(
            abs(change) * D(registration["commission_CAD_per_base_side"][scenario])
        ),
        "slippage_CAD": str(
            abs(change) * spread * rate * D(registration["slippage_spreads_per_side"][scenario])
        ),
        "financing_CAD": None,
        "execution_claim": "none",
    }, state


@arithmetic
def day_rows(registration_id, registration, strategy, instrument, day, data, conversions, active):
    rows = []
    for at in opportunities(strategy, day):
        output, setup = selection(strategy, instrument, at, data)
        row = {
            "opportunity": at.isoformat(),
            "strategy": strategy,
            "instrument": instrument,
            "session": strategy.split(":")[1] if ":" in strategy else "regular_fx",
            "decision": output,
            "scenarios": {},
        }
        row["evaluation_identity"] = identity_digest(
            {
                "registration": registration_id,
                "opportunity": row["opportunity"],
                "instrument": instrument,
                "strategy": strategy,
                "decision": output,
            }
        )
        for scenario in registration["scenarios"]:
            if active[scenario] and at < datetime.fromisoformat(active[scenario]):
                result = {"state": "occupied", "reason": "prior_position_active"}
            elif setup is None:
                reason = row_reason(output)
                known_no_setup = reason in {
                    "no_confirmation_before_expiry",
                    "no_aligned_deviation",
                    "no_qualified_pullback",
                    "no_unique_confirmed_failed_break",
                }
                result = {
                    "state": "no_setup" if known_no_setup else "unavailable",
                    "reason": reason,
                }
            else:
                result = simulate(
                    setup,
                    instrument,
                    data[timeframe(strategy)],
                    conversions,
                    registration,
                    scenario,
                )
                # Unavailable accounting is not permission for another overlapping
                # attempt. Reserve the unchanged setup horizon conservatively.
                active[scenario] = result.get("exited_at", setup["exit_at"])
            row["scenarios"][scenario] = result
        # Paired risk decisions share the baseline opportunity and signal cutoff.
        # Outcomes are scaled only in the derived report view, never reselected.
        row["overlays"] = {}
        row["volatility_stratum"] = "unavailable"
        if setup is not None:
            cutoff = datetime.fromisoformat(setup["available_at"])
            daily = ReplayInput(instrument, cutoff, data, strategy).series("D")
            closes = tuple(b.close for b in daily)
            current, prior = sigma(closes), sigma(closes[:-1])
            if current is not None and prior is not None and prior > 0:
                row["volatility_stratum"] = "high" if current > prior * D("1.5") else "other"
        for overlay in OVERLAYS:
            if overlay == "macro-risk-v1":
                risk = {"multiplier": None, "reason": BLOCKED[overlay]}
            elif setup is None:
                risk = {"multiplier": None, "reason": "baseline_has_no_setup"}
            else:
                cutoff = datetime.fromisoformat(setup["available_at"])
                risk = json.loads(
                    encoded(
                        volatility_overlay(ReplayInput(instrument, cutoff, data, overlay), overlay)
                    )
                )
            row["overlays"][overlay] = risk
        rows.append(row)
    return rows


def data_for(acquisition_path, registration, strategy, instrument):
    # All required data is loaded once per focused chunk. Blocked readiness-only
    # identities do not read prices just to restate absent mandatory evidence.
    data, conversions = {}, {}
    manifest_json = canonical_json(registration["manifest"])
    if strategy not in BLOCKED:
        for granularity in ("D", "H4", "H1", "M15"):
            data[granularity] = series_for(acquisition_path, manifest_json, instrument, granularity)
        quote = instrument.split("_")[1]
        pairs = {"USD_CAD"}
        route = {
            "GBP": "GBP_USD",
            "EUR": "EUR_USD",
            "JPY": "USD_JPY",
            "CHF": "USD_CHF",
            "AUD": "AUD_USD",
            "NZD": "NZD_USD",
        }.get(quote)
        if route:
            pairs.add(route)
        if quote != "CAD":
            for pair in sorted(pairs):
                conversions[pair] = series_for(
                    acquisition_path, manifest_json, pair, timeframe(strategy)
                )
    return data, conversions


def run(
    catalog, registration_id, acquisition_path, strategy, instrument, start, end, *, baseline=None
):
    registration = catalog.load(registration_id)
    admit_period(registration, start, end)  # Before any price blob is requested.
    if strategy not in STRATEGIES or instrument not in registration["instruments"]:
        raise ValueError("unregistered_population")
    if (
        start.time() != datetime.min.time()
        or end.time() != datetime.min.time()
        or end - start > timedelta(days=32)
    ):
        raise ValueError("batch_requires_1_to_32_whole_UTC_days")
    if strategy in OVERLAYS:
        if baseline not in STRATEGIES or baseline in OVERLAYS:
            raise ValueError("overlay_requires_paired_baseline")
        strategy = baseline
    elif baseline is not None:
        raise ValueError("baseline_only_for_overlay")
    catalog.acquisition_path = acquisition_path
    # A hash-valid predecessor is insufficient: verify the complete causal prefix
    # before consuming its state. The replay cache only contains computed proofs.
    _, active, predecessor = catalog.verify_chain(
        registration_id, strategy, instrument, stop=start, collect=False
    )
    identities = []
    day = start
    while day < end:
        key = {
            "registration": registration_id,
            "strategy": strategy,
            "instrument": instrument,
            "start": day.isoformat(),
            "end": (day + timedelta(days=1)).isoformat(),
        }
        expected = catalog.replay_checkpoint(key, registration, active, predecessor)
        identities.append(catalog._write_replayed(expected))
        active, predecessor = expected["end_state"], identity_digest(expected)
        day += timedelta(days=1)
    return identities


def shadow_readiness(now):
    start = datetime(2026, 9, 11, tzinfo=UTC)
    if now.utcoffset() is None:
        raise ValueError("aware_shadow_clock_required")
    return {
        "start": start.isoformat(),
        "elapsed_complete_weeks": max(0, (now - start).days // 7),
        "state": "unavailable",
        "reason": "forward_evidence_not_collected",
        "mode": "offline_only",
    }


def forward_shadow(registration, inputs, strategy, *, baseline=None):
    """Manual prospective decision evidence; never retrospective execution claims.

    The caller supplies an original verified Phase4 SnapshotInput. No provider,
    production writer or schedule is invoked. Missing execution evidence stays
    unavailable; elapsed weeks alone never confirm a candidate.
    """
    from research.validation_registration import validate_registration

    validate_registration(registration)
    now = datetime.now(UTC)
    if type(inputs) is not SnapshotInput:
        raise ValueError("forward_requires_original_verified_snapshot")
    inputs.__post_init__()
    if (
        not datetime(2026, 9, 11, tzinfo=UTC) <= inputs.cutoff <= now
        or inputs.cutoff >= datetime.fromisoformat(registration["shadow"]["maximum_end"])
        or strategy not in STRATEGIES
        or inputs.payload["instrument"] not in registration["instruments"]
        or len(inputs.bars) > 1800
        or any(
            type(b) is not Bar or b.observed_at > inputs.cutoff or b.end > inputs.cutoff
            for b in inputs.bars
        )
    ):
        raise ValueError("forward_future_unregistered_or_retrospective_evidence")
    snapshot = json.loads(inputs.envelope_json)["idempotency_key"]
    if strategy in OVERLAYS:
        if (
            not baseline
            or baseline.get("snapshot") != snapshot
            or baseline.get("strategy") not in STRATEGIES
            or baseline["strategy"] in OVERLAYS
            or baseline.get("registration") != identity_digest(registration)
            or baseline.get("identity")
            != identity_digest({k: v for k, v in baseline.items() if k != "identity"})
        ):
            raise ValueError("forward_overlay_requires_same_snapshot_baseline")
    elif baseline is not None:
        raise ValueError("forward_directional_baseline_not_applicable")
    body = {
        "schema": "phase55/forward-shadow-decision-v1",
        "registration": identity_digest(registration),
        "snapshot": snapshot,
        "strategy": strategy,
        "instrument": inputs.payload["instrument"],
        "cutoff": inputs.cutoff.isoformat(),
        "decision": evaluate(inputs, strategy),
        "baseline": baseline["identity"] if baseline else None,
        "execution": {
            "state": "unavailable",
            "reason": "genuine_forward_execution_evidence_not_supplied",
            "net_CAD": None,
        },
        "mode": "offline_prospective_not_retrospective",
        "activation": "forbidden",
    }
    body["identity"] = identity_digest(body)
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "run", "report", "shadow"))
    parser.add_argument("--registration")
    parser.add_argument("--strategy", choices=STRATEGIES)
    parser.add_argument("--instrument")
    parser.add_argument("--baseline", choices=STRATEGIES)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    if args.action == "shadow":
        print(canonical_json(shadow_readiness(datetime.now(UTC))))
        return
    catalog = Catalog(ROOT / ".candidate-data/phase55-v1/validation.sqlite3")
    try:
        if args.action == "register":
            audit = json.loads((ROOT / "docs/phase5.5/acquired-coverage.json").read_text())
            identity, body = catalog.register(audit)
            print(canonical_json({"identity": identity, "body": body}))
        elif args.action == "report":
            from research.validation_reports import export_report

            print(
                canonical_json(
                    {
                        "report": export_report(
                            catalog,
                            args.registration,
                            args.strategy,
                            args.instrument,
                            ROOT / ".candidate-data/phase55-v1/reports",
                            baseline=args.baseline,
                        )
                    }
                )
            )
        else:
            ids = run(
                catalog,
                args.registration,
                ROOT / ".candidate-data/phase55-v1/acquisition.sqlite3",
                args.strategy,
                args.instrument,
                datetime.fromisoformat(args.start),
                datetime.fromisoformat(args.end),
                baseline=args.baseline,
            )
            print(canonical_json({"checkpoints": ids}))
    finally:
        catalog.close()


if __name__ == "__main__":
    main()
